"""
Generates snowflake/04_curated_layer.sql: a structured CURATED layer built
straight from the raw CDC tables the Kafka connector writes.

  SAP_RAW.SD.<TABLE>_RAW        RECORD_CONTENT / RECORD_METADATA (VARIANT)
        |  stream (append-only) + task every minute: parse, type, dedupe, MERGE
        v
  SAP_CURATED.SD.<TABLE>        one typed column per Oracle column
                                + CDC_OP, CDC_SCN, CDC_SOURCE_TS, CDC_LOADED_AT, CDC_IS_DELETED
        |  dynamic tables, 1-minute target lag
        v
  SAP_CURATED.SD.FCT_SALES_ORDER_ITEM   order item + header + customer + material
  SAP_CURATED.SD.FCT_BILLING_ITEM       billing item with signed revenue (cancellations
                                        and credit memos negative: never counted twice)

Independent of 02_snowflake_core.sql (own streams), so it can run alongside it
or replace it.

Run after changing the Oracle DDL:  python3 scripts/generate_curated.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from generate_from_ddl import parse_ddl, DDL, ROOT, RAW, WAREHOUSE  # noqa: E402

CURATED_DB = "SAP_CURATED"
CUR = f"{CURATED_DB}.SD"
TASK_SCHEDULE = "1 MINUTE"
FACT_LAG = "1 minute"


def sf_type(typ, p, s):
    if typ == "VARCHAR2":
        return f"VARCHAR({p})"
    if typ == "NUMBER":
        return f"NUMBER({p},{s or 0})" if p else "NUMBER(38,10)"
    if typ == "DATE":
        return "DATE"
    if typ == "RAW":
        return f"VARCHAR({int(p) * 2})"      # stored as uppercase hex, like Oracle shows RAW
    raise ValueError(typ)


def parse_expr(col, typ, p, s):
    """Debezium JSON value (in alias R) -> typed Snowflake value. TRY_ so one bad
    value becomes NULL instead of failing the whole MERGE."""
    v = f'R:"{col}"'
    if typ == "VARCHAR2":
        return f"{v}::VARCHAR"
    if typ == "NUMBER":                      # decimals arrive as strings, integers as numbers
        return f"TRY_TO_NUMBER({v}::VARCHAR, {p}, {s or 0})" if p else f"TRY_TO_NUMBER({v}::VARCHAR, 38, 10)"
    if typ == "DATE":                        # Oracle DATE -> epoch milliseconds
        return f"TO_DATE(TO_TIMESTAMP_NTZ(TRY_TO_NUMBER({v}::VARCHAR), 3))"
    if typ == "RAW":                         # bytes -> base64 in JSON
        return f"HEX_ENCODE(TRY_BASE64_DECODE_BINARY({v}::VARCHAR))"
    raise ValueError(typ)


def q(c):
    return f'"{c}"'


def table_block(t):
    name, cols, pk = t["name"], t["cols"], t["pk"]
    col_defs = ",\n  ".join(f"{q(c)} {sf_type(ty, p, s)}{' NOT NULL' if c in pk else ''}"
                            for c, ty, p, s in cols)
    parsed = ",\n      ".join(f"{parse_expr(c, ty, p, s)} AS {q(c)}" for c, ty, p, s in cols)
    pk_list = ", ".join(q(c) for c in pk)
    on = " AND ".join(f"t.{q(c)} = s.{q(c)}" for c in pk)
    non_pk = [c for c, *_ in cols if c not in pk]
    set_cols = ",\n  ".join(f"{q(c)} = s.{q(c)}" for c in non_pk)
    all_cols = [c for c, *_ in cols] + ["CDC_OP", "CDC_SCN", "CDC_SOURCE_TS", "CDC_LOADED_AT", "CDC_IS_DELETED"]
    ins_cols = ", ".join(q(c) if c in dict.fromkeys(x[0] for x in cols) else c for c in all_cols)
    ins_vals = ", ".join(
        [f"s.{q(c)}" for c, *_ in cols] +
        ["s.CDC_OP", "s.CDC_SCN", "s.CDC_SOURCE_TS", "CURRENT_TIMESTAMP()", "(s.CDC_OP = 'd')"])
    return f"""
-- ======================= {name} =======================
CREATE TABLE IF NOT EXISTS {CUR}.{name} (
  {col_defs},
  CDC_OP          VARCHAR(1),
  CDC_SCN         NUMBER(38,0),
  CDC_SOURCE_TS   TIMESTAMP_NTZ,
  CDC_LOADED_AT   TIMESTAMP_LTZ,
  CDC_IS_DELETED  BOOLEAN,
  CONSTRAINT PK_CUR_{name} PRIMARY KEY ({pk_list})
);

CREATE STREAM IF NOT EXISTS {CUR}.STM_{name}
  ON TABLE {RAW}.{name}_RAW
  APPEND_ONLY = TRUE
  SHOW_INITIAL_ROWS = TRUE;

CREATE OR REPLACE TASK {CUR}.TSK_{name}
  WAREHOUSE = {WAREHOUSE}
  SCHEDULE = '{TASK_SCHEDULE}'
  WHEN SYSTEM$STREAM_HAS_DATA('{CUR}.STM_{name}')
AS
MERGE INTO {CUR}.{name} t
USING (
    SELECT
      {parsed},
      CDC_OP, CDC_SCN, CDC_SOURCE_TS
    FROM (
      SELECT COALESCE(RECORD_CONTENT:after, RECORD_CONTENT:before)          AS R,
             RECORD_CONTENT:op::VARCHAR                                     AS CDC_OP,
             TRY_TO_NUMBER(RECORD_CONTENT:source.scn::VARCHAR)              AS CDC_SCN,
             TO_TIMESTAMP_NTZ(RECORD_CONTENT:source.ts_ms::NUMBER, 3)       AS CDC_SOURCE_TS,
             RECORD_METADATA:offset::NUMBER                                 AS KAFKA_OFFSET
      FROM {CUR}.STM_{name}
      WHERE RECORD_CONTENT:op IS NOT NULL
    )
    QUALIFY ROW_NUMBER() OVER (PARTITION BY {", ".join(f"{parse_expr(c, ty, p, s)}" for c, ty, p, s in cols if c in pk)}
                               ORDER BY CDC_SCN DESC, KAFKA_OFFSET DESC) = 1
) s
ON {on}
WHEN MATCHED AND s.CDC_SCN >= t.CDC_SCN THEN UPDATE SET
  {set_cols},
  CDC_OP = s.CDC_OP,
  CDC_SCN = s.CDC_SCN,
  CDC_SOURCE_TS = s.CDC_SOURCE_TS,
  CDC_LOADED_AT = CURRENT_TIMESTAMP(),
  CDC_IS_DELETED = (s.CDC_OP = 'd')
WHEN NOT MATCHED THEN INSERT ({ins_cols})
  VALUES ({ins_vals});"""


def curated_sql(tables):
    names = [t["name"] for t in tables]
    out = [f"""/* =====================================================================
   CURATED LAYER: structured SAP SD tables in Snowflake
   GENERATED by scripts/generate_curated.py - edit the generator, not this file.

   {RAW}.<TABLE>_RAW  (VARIANT, every CDC event, append-only)
        -> stream + task every {TASK_SCHEDULE.lower()}
   {CUR}.<TABLE>   (typed columns, one row per primary key, soft deletes)
        -> dynamic tables
   {CUR}.FCT_SALES_ORDER_ITEM, {CUR}.FCT_BILLING_ITEM

   MERGE rules (same as the pipeline's three rules):
     1. latest event per key wins (Oracle SCN, then Kafka offset); an older or
        replayed event never overwrites newer data -> no double counting
     2. a failed task run leaves the stream where it was -> safe to retry
     3. deletes set CDC_IS_DELETED = TRUE; everything can be rebuilt from raw
        (section F)

   Run order: section A as ACCOUNTADMIN, the rest as SAP_TRANSFORM_ROLE
   (one run of the whole file works for a user that has both roles).
   Prerequisite: the Kafka sink has created the 30 *_RAW tables.
   ===================================================================== */

/* ---------------------------------------------------------------------
   A. Database, grants, change tracking on raw tables (admin, once)
   --------------------------------------------------------------------- */
USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS {CURATED_DB}
  DATA_RETENTION_TIME_IN_DAYS = 1
  COMMENT = 'Structured, typed SAP tables built from SAP_RAW CDC events';
CREATE SCHEMA IF NOT EXISTS {CUR}
  COMMENT = 'SAP Sales & Distribution curated tables';

USE ROLE SECURITYADMIN;
GRANT USAGE                ON DATABASE {CURATED_DB} TO ROLE SAP_TRANSFORM_ROLE;
GRANT USAGE                ON SCHEMA   {CUR}        TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE TABLE         ON SCHEMA   {CUR}        TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE VIEW          ON SCHEMA   {CUR}        TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE STREAM        ON SCHEMA   {CUR}        TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE TASK          ON SCHEMA   {CUR}        TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE DYNAMIC TABLE ON SCHEMA   {CUR}        TO ROLE SAP_TRANSFORM_ROLE;

-- Streams need change tracking on the raw tables (owned by the connector role).
USE ROLE SYSADMIN;"""]
    out += [f"ALTER TABLE IF EXISTS {RAW}.{n}_RAW SET CHANGE_TRACKING = TRUE;" for n in names]

    out.append(f"""
/* ---------------------------------------------------------------------
   B. Curated tables, streams, MERGE tasks
   --------------------------------------------------------------------- */
USE ROLE SAP_TRANSFORM_ROLE;
USE WAREHOUSE {WAREHOUSE};""")
    out += [table_block(t) for t in tables]

    out.append(f"""
/* ---------------------------------------------------------------------
   C. Business fact tables (dynamic tables refresh themselves)
      Only live rows (CDC_IS_DELETED = FALSE) are used.
   --------------------------------------------------------------------- */
CREATE OR REPLACE DYNAMIC TABLE {CUR}.FCT_SALES_ORDER_ITEM
  TARGET_LAG = '{FACT_LAG}'
  WAREHOUSE = {WAREHOUSE}
  COMMENT = 'One row per sales document item, with header, customer and material attributes'
AS
SELECT
  h."VBELN"                         AS SALES_DOC,
  i."POSNR"                         AS ITEM,
  h."AUART"                         AS DOC_TYPE,
  h."VBTYP"                         AS DOC_CATEGORY,
  h."AUDAT"                         AS DOC_DATE,
  h."ERDAT"                         AS CREATED_ON,
  h."VDATU"                         AS REQ_DELIVERY_DATE,
  h."VKORG"                         AS SALES_ORG,
  h."VTWEG"                         AS DISTR_CHANNEL,
  h."VKBUR"                         AS SALES_OFFICE,
  h."KUNNR"                         AS SOLD_TO,
  c."NAME1"                         AS SOLD_TO_NAME,
  c."ORT01"                         AS SOLD_TO_CITY,
  c."REGIO"                         AS SOLD_TO_REGION,
  i."MATNR"                         AS MATERIAL,
  m."MAKTX"                         AS MATERIAL_TEXT,
  i."MATKL"                         AS MATERIAL_GROUP,
  i."WERKS"                         AS PLANT,
  i."KWMENG"                        AS ORDER_QTY,
  i."VRKME"                         AS SALES_UNIT,
  i."NETPR"                         AS NET_PRICE,
  i."NETWR"                         AS NET_VALUE,
  i."MWSBP"                         AS TAX_AMOUNT,
  i."NETWR" + COALESCE(i."MWSBP", 0) AS GROSS_VALUE,
  i."WAERK"                         AS CURRENCY,
  i."ABGRU"                         AS REJECTION_REASON,
  (i."ABGRU" IS NOT NULL)           AS IS_REJECTED,
  i."LFSTA"                         AS DELIVERY_STATUS,
  i."FKSTA"                         AS BILLING_STATUS,
  h."CMGST"                         AS CREDIT_STATUS,
  GREATEST(h.CDC_LOADED_AT, i.CDC_LOADED_AT) AS LAST_LOADED_AT
FROM {CUR}.VBAP i
JOIN {CUR}.VBAK h
  ON h."MANDT" = i."MANDT" AND h."VBELN" = i."VBELN" AND NOT h.CDC_IS_DELETED
LEFT JOIN {CUR}.KNA1 c
  ON c."MANDT" = h."MANDT" AND c."KUNNR" = h."KUNNR" AND NOT c.CDC_IS_DELETED
LEFT JOIN {CUR}.MAKT m
  ON m."MANDT" = i."MANDT" AND m."MATNR" = i."MATNR" AND m."SPRAS" = 'E' AND NOT m.CDC_IS_DELETED
WHERE NOT i.CDC_IS_DELETED;

CREATE OR REPLACE DYNAMIC TABLE {CUR}.FCT_BILLING_ITEM
  TARGET_LAG = '{FACT_LAG}'
  WAREHOUSE = {WAREHOUSE}
  COMMENT = 'Billing items with signed revenue: invoices +, cancellations and credit memos -'
AS
SELECT
  b."VBELN"                         AS BILLING_DOC,
  p."POSNR"                         AS ITEM,
  b."FKART"                         AS BILLING_TYPE,
  b."VBTYP"                         AS BILLING_CATEGORY,
  b."FKDAT"                         AS BILLING_DATE,
  b."GJAHR"                         AS FISCAL_YEAR,
  b."POPER"                         AS POSTING_PERIOD,
  b."KUNRG"                         AS PAYER,
  c."NAME1"                         AS PAYER_NAME,
  b."VTWEG"                         AS DISTR_CHANNEL,
  p."AUBEL"                         AS SALES_DOC,
  p."AUPOS"                         AS SALES_ITEM,
  p."VGBEL"                         AS REFERENCE_DOC,
  p."MATNR"                         AS MATERIAL,
  p."MATKL"                         AS MATERIAL_GROUP,
  p."FKIMG"                         AS BILLED_QTY,
  p."VRKME"                         AS SALES_UNIT,
  p."NETWR"                         AS NET_VALUE,
  p."MWSBP"                         AS TAX_AMOUNT,
  p."WAVWR"                         AS COST,
  CASE WHEN b."VBTYP" IN ('N', 'O') THEN -1 ELSE 1 END       AS REVENUE_SIGN,
  CASE WHEN b."VBTYP" IN ('N', 'O') THEN -1 ELSE 1 END * p."NETWR" AS SIGNED_NET_REVENUE,
  CASE WHEN b."VBTYP" IN ('N', 'O') THEN -1 ELSE 1 END
       * (p."NETWR" - COALESCE(p."WAVWR", 0))                AS SIGNED_MARGIN,
  b."WAERK"                         AS CURRENCY,
  (b."FKSTO" = 'X')                 AS IS_CANCELLED,
  b."SFAKN"                         AS CANCELLED_DOC,
  GREATEST(b.CDC_LOADED_AT, p.CDC_LOADED_AT) AS LAST_LOADED_AT
FROM {CUR}.VBRP p
JOIN {CUR}.VBRK b
  ON b."MANDT" = p."MANDT" AND b."VBELN" = p."VBELN" AND NOT b.CDC_IS_DELETED
LEFT JOIN {CUR}.KNA1 c
  ON c."MANDT" = b."MANDT" AND c."KUNNR" = b."KUNRG" AND NOT c.CDC_IS_DELETED
WHERE NOT p.CDC_IS_DELETED;

/* ---------------------------------------------------------------------
   D. Start the tasks and load the initial snapshot now
   --------------------------------------------------------------------- */""")
    out += [f"ALTER TASK {CUR}.TSK_{n} RESUME;" for n in names]
    out.append("")
    out += [f"EXECUTE TASK {CUR}.TSK_{n};" for n in names]

    out.append(f"""
/* ---------------------------------------------------------------------
   E. Checks (run a minute after section D)
   --------------------------------------------------------------------- */
-- Live rows per curated table: compare with oracle/91_row_counts.sql
{chr(10).join(("SELECT" if i == 0 else "UNION ALL SELECT") + f" '{n}' AS TABLE_NAME, COUNT_IF(NOT CDC_IS_DELETED) AS LIVE_ROWS, COUNT_IF(CDC_IS_DELETED) AS DELETED_ROWS, MAX(CDC_LOADED_AT) AS LAST_LOADED_AT FROM {CUR}.{n}" for i, n in enumerate(names))}
ORDER BY 1;

-- Values that failed type conversion (should return no rows)
SELECT 'VBAK' AS TABLE_NAME, COUNT(*) AS NULL_NETWR FROM {CUR}.VBAK WHERE "NETWR" IS NULL AND NOT CDC_IS_DELETED
UNION ALL SELECT 'VBAP', COUNT(*) FROM {CUR}.VBAP WHERE "NETWR" IS NULL AND NOT CDC_IS_DELETED
UNION ALL SELECT 'VBRK', COUNT(*) FROM {CUR}.VBRK WHERE "NETWR" IS NULL AND NOT CDC_IS_DELETED
HAVING COUNT(*) > 0;

-- Typed columns: no JSON paths needed any more
SELECT "VBELN", "AUART", "ERDAT", "KUNNR", "NETWR", "GBSTK", CDC_OP, CDC_LOADED_AT
FROM {CUR}.VBAK WHERE NOT CDC_IS_DELETED ORDER BY "VBELN" DESC LIMIT 20;

-- Business questions on the fact tables
SELECT DOC_DATE, COUNT(DISTINCT SALES_DOC) AS ORDERS, COUNT(*) AS ITEMS, SUM(NET_VALUE) AS NET_VALUE
FROM {CUR}.FCT_SALES_ORDER_ITEM
WHERE DOC_CATEGORY = 'C' AND NOT IS_REJECTED
GROUP BY DOC_DATE ORDER BY DOC_DATE DESC;

SELECT BILLING_DATE, SUM(SIGNED_NET_REVENUE) AS NET_REVENUE, SUM(SIGNED_MARGIN) AS MARGIN
FROM {CUR}.FCT_BILLING_ITEM GROUP BY BILLING_DATE ORDER BY BILLING_DATE DESC;

-- Task runs in the last hour (look for FAILED)
SELECT name, state, scheduled_time, error_message
FROM TABLE({CURATED_DB}.INFORMATION_SCHEMA.TASK_HISTORY(
       SCHEDULED_TIME_RANGE_START => DATEADD(hour, -1, CURRENT_TIMESTAMP()), RESULT_LIMIT => 200))
WHERE state <> 'SKIPPED' ORDER BY scheduled_time DESC;

/* ---------------------------------------------------------------------
   F. Rebuild one curated table from the full raw history (rule 3)
      Example for VBAK; replace the table name as needed.
   --------------------------------------------------------------------- */
-- ALTER TASK {CUR}.TSK_VBAK SUSPEND;
-- TRUNCATE TABLE {CUR}.VBAK;
-- CREATE OR REPLACE STREAM {CUR}.STM_VBAK ON TABLE {RAW}.VBAK_RAW
--   APPEND_ONLY = TRUE SHOW_INITIAL_ROWS = TRUE;
-- ALTER TASK {CUR}.TSK_VBAK RESUME;
-- EXECUTE TASK {CUR}.TSK_VBAK;

/* ---------------------------------------------------------------------
   G. Pause everything (saves credits). Resume with section D.
   --------------------------------------------------------------------- */
-- ALTER DYNAMIC TABLE {CUR}.FCT_SALES_ORDER_ITEM SUSPEND;
-- ALTER DYNAMIC TABLE {CUR}.FCT_BILLING_ITEM SUSPEND;""")
    out += [f"-- ALTER TASK {CUR}.TSK_{n} SUSPEND;" for n in names]
    return "\n".join(out) + "\n"


def main():
    tables = parse_ddl(DDL.read_text())
    out = ROOT / "snowflake" / "04_curated_layer.sql"
    out.write_text(curated_sql(tables))
    print(f"Wrote {out.relative_to(ROOT)} for {len(tables)} tables")


if __name__ == "__main__":
    main()
