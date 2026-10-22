/* =====================================================================
   GOLD LAYER: SAP_GOLD.SALES (business-ready, dynamic tables)
     SALES_DOC_HDR  one row per sales document
     SALES_DOC_POS  one row per sales document item
     DEL_DOC_POS    one row per delivery item
   Source: SAP_CURATED.SD (04_curated_layer.sql). Refresh lag: 1 minute.
   ===================================================================== */

/* ---------------------------------------------------------------------
   0. Database and grants (admin, once)
   --------------------------------------------------------------------- */
USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS SAP_GOLD COMMENT = 'Business-ready SAP models';
CREATE SCHEMA   IF NOT EXISTS SAP_GOLD.SALES;

USE ROLE SECURITYADMIN;
GRANT USAGE                ON DATABASE SAP_GOLD       TO ROLE SAP_TRANSFORM_ROLE;
GRANT USAGE                ON SCHEMA   SAP_GOLD.SALES TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE DYNAMIC TABLE ON SCHEMA   SAP_GOLD.SALES TO ROLE SAP_TRANSFORM_ROLE;
GRANT CREATE VIEW          ON SCHEMA   SAP_GOLD.SALES TO ROLE SAP_TRANSFORM_ROLE;

USE ROLE SAP_TRANSFORM_ROLE;
USE WAREHOUSE SAP_TRANSFORM_WH;

/* ---------------------------------------------------------------------
   1. SALES_DOC_HDR
   --------------------------------------------------------------------- */
CREATE OR REPLACE DYNAMIC TABLE SAP_GOLD.SALES.SALES_DOC_HDR
  TARGET_LAG = '1 minute'
  WAREHOUSE  = SAP_TRANSFORM_WH
  COMMENT    = 'Sales document header with partners, statuses and item/delivery/billing totals'
AS
WITH
itm AS (
  SELECT "MANDT", "VBELN",
         COUNT(*)                                            AS ITEM_COUNT,
         COUNT_IF("ABGRU" IS NOT NULL)                       AS REJECTED_ITEM_COUNT,
         SUM(IFF("ABGRU" IS NULL, "KWMENG", 0))              AS ORDER_QTY,
         SUM(IFF("ABGRU" IS NULL, "NETWR", 0))               AS ITEM_NET_VALUE,
         SUM(IFF("ABGRU" IS NULL, "MWSBP", 0))               AS ITEM_TAX_VALUE
  FROM SAP_CURATED.SD.VBAP
  WHERE NOT CDC_IS_DELETED
  GROUP BY "MANDT", "VBELN"
),
sched AS (
  SELECT "MANDT", "VBELN",
         SUM("BMENG")                                        AS CONFIRMED_QTY,
         MIN(IFF("BMENG" > 0, "EDATU", NULL))                AS FIRST_CONFIRMED_DATE,
         MAX(IFF("BMENG" > 0, "EDATU", NULL))                AS LAST_CONFIRMED_DATE
  FROM SAP_CURATED.SD.VBEP
  WHERE NOT CDC_IS_DELETED
  GROUP BY "MANDT", "VBELN"
),
dlv AS (
  SELECT p."MANDT", p."VGBEL"                                AS "VBELN",
         COUNT(DISTINCT p."VBELN")                           AS DELIVERY_COUNT,
         SUM(p."LFIMG")                                      AS DELIVERED_QTY,
         MAX(h."WADAT_IST")                                  AS LAST_GOODS_ISSUE_DATE
  FROM SAP_CURATED.SD.LIPS p
  JOIN SAP_CURATED.SD.LIKP h
    ON h."MANDT" = p."MANDT" AND h."VBELN" = p."VBELN" AND NOT h.CDC_IS_DELETED
  WHERE NOT p.CDC_IS_DELETED
  GROUP BY p."MANDT", p."VGBEL"
),
bil AS (
  SELECT p."MANDT", p."AUBEL"                                AS "VBELN",
         COUNT(DISTINCT IFF(h."VBTYP" = 'M', p."VBELN", NULL)) AS INVOICE_COUNT,
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."NETWR") AS NET_BILLED_VALUE,
         MAX(h."FKDAT")                                      AS LAST_BILLING_DATE
  FROM SAP_CURATED.SD.VBRP p
  JOIN SAP_CURATED.SD.VBRK h
    ON h."MANDT" = p."MANDT" AND h."VBELN" = p."VBELN" AND NOT h.CDC_IS_DELETED
  WHERE NOT p.CDC_IS_DELETED
  GROUP BY p."MANDT", p."AUBEL"
),
ptn AS (
  SELECT "MANDT", "VBELN",
         MAX(IFF("PARVW" = 'AG', "KUNNR", NULL))             AS SOLD_TO,
         MAX(IFF("PARVW" = 'WE', "KUNNR", NULL))             AS SHIP_TO,
         MAX(IFF("PARVW" = 'RE', "KUNNR", NULL))             AS BILL_TO,
         MAX(IFF("PARVW" = 'RG', "KUNNR", NULL))             AS PAYER
  FROM SAP_CURATED.SD.VBPA
  WHERE NOT CDC_IS_DELETED AND "POSNR" = '000000'
  GROUP BY "MANDT", "VBELN"
)
SELECT
  h."MANDT"                                   AS CLIENT,
  h."VBELN"                                   AS SALES_DOC,
  h."AUART"                                   AS DOC_TYPE,
  t."BEZEI"                                   AS DOC_TYPE_TEXT,
  h."VBTYP"                                   AS DOC_CATEGORY,
  CASE h."VBTYP" WHEN 'B' THEN 'Quotation' WHEN 'C' THEN 'Order'
                 WHEN 'H' THEN 'Return'    WHEN 'K' THEN 'Credit memo request'
                 ELSE h."VBTYP" END           AS DOC_CATEGORY_TEXT,
  h."AUGRU"                                   AS ORDER_REASON,
  h."VGBEL"                                   AS REFERENCE_DOC,
  h."AUDAT"                                   AS DOC_DATE,
  TO_NUMBER(TO_CHAR(h."AUDAT", 'YYYYMMDD'))   AS DOC_DATE_KEY,
  h."ERDAT"                                   AS CREATED_ON,
  h."ERNAM"                                   AS CREATED_BY,
  h."VDATU"                                   AS REQ_DELIVERY_DATE,
  h."GUEBG"                                   AS VALID_FROM,
  h."GUEEN"                                   AS VALID_TO,
  h."VKORG"                                   AS SALES_ORG,
  h."VTWEG"                                   AS DISTR_CHANNEL,
  h."SPART"                                   AS DIVISION,
  h."VKBUR"                                   AS SALES_OFFICE,
  h."VKGRP"                                   AS SALES_GROUP,
  h."BUKRS_VF"                                AS COMPANY_CODE,
  COALESCE(p.SOLD_TO, h."KUNNR")              AS SOLD_TO,
  ca."NAME1"                                  AS SOLD_TO_NAME,
  ca."ORT01"                                  AS SOLD_TO_CITY,
  ca."REGIO"                                  AS SOLD_TO_REGION,
  p.SHIP_TO,
  cw."NAME1"                                  AS SHIP_TO_NAME,
  cw."ORT01"                                  AS SHIP_TO_CITY,
  p.BILL_TO,
  p.PAYER,
  h."BSTNK"                                   AS CUSTOMER_PO,
  h."BSTDK"                                   AS CUSTOMER_PO_DATE,
  k."ZTERM"                                   AS PAYMENT_TERMS,
  k."INCO1"                                   AS INCOTERMS,
  k."INCO2"                                   AS INCOTERMS_LOCATION,
  h."WAERK"                                   AS CURRENCY,
  h."NETWR"                                   AS NET_VALUE,
  COALESCE(i.ITEM_TAX_VALUE, 0)               AS TAX_VALUE,
  h."NETWR" + COALESCE(i.ITEM_TAX_VALUE, 0)   AS GROSS_VALUE,
  COALESCE(b.NET_BILLED_VALUE, 0)             AS NET_BILLED_VALUE,
  h."NETWR" - COALESCE(b.NET_BILLED_VALUE, 0) AS OPEN_BILLING_VALUE,
  COALESCE(i.ITEM_COUNT, 0)                   AS ITEM_COUNT,
  COALESCE(i.REJECTED_ITEM_COUNT, 0)          AS REJECTED_ITEM_COUNT,
  COALESCE(i.ORDER_QTY, 0)                    AS ORDER_QTY,
  COALESCE(s.CONFIRMED_QTY, 0)                AS CONFIRMED_QTY,
  COALESCE(d.DELIVERED_QTY, 0)                AS DELIVERED_QTY,
  COALESCE(i.ORDER_QTY, 0) - COALESCE(d.DELIVERED_QTY, 0) AS OPEN_DELIVERY_QTY,
  COALESCE(d.DELIVERY_COUNT, 0)               AS DELIVERY_COUNT,
  COALESCE(b.INVOICE_COUNT, 0)                AS INVOICE_COUNT,
  s.FIRST_CONFIRMED_DATE,
  s.LAST_CONFIRMED_DATE,
  d.LAST_GOODS_ISSUE_DATE,
  b.LAST_BILLING_DATE,
  h."GBSTK"                                   AS OVERALL_STATUS,
  DECODE(h."GBSTK", 'A','Open', 'B','In process', 'C','Completed', 'Not relevant') AS OVERALL_STATUS_TEXT,
  h."LFSTK"                                   AS DELIVERY_STATUS,
  DECODE(h."LFSTK", 'A','Not delivered', 'B','Partially delivered', 'C','Fully delivered', 'Not relevant') AS DELIVERY_STATUS_TEXT,
  h."FKSTK"                                   AS BILLING_STATUS,
  DECODE(h."FKSTK", 'A','Not billed', 'B','Partially billed', 'C','Fully billed', 'Not relevant') AS BILLING_STATUS_TEXT,
  h."ABSTK"                                   AS REJECTION_STATUS,
  h."CMGST"                                   AS CREDIT_STATUS,
  (h."CMGST" = 'B')                           AS IS_CREDIT_BLOCKED,
  (h."LIFSK" IS NOT NULL)                     AS IS_DELIVERY_BLOCKED,
  (h."FAKSK" IS NOT NULL)                     AS IS_BILLING_BLOCKED,
  (s.FIRST_CONFIRMED_DATE <= h."VDATU")       AS CONFIRMED_ON_REQUEST_DATE,
  DATEDIFF('day', h."AUDAT", d.LAST_GOODS_ISSUE_DATE) AS DAYS_ORDER_TO_SHIP,
  DATEDIFF('day', h."AUDAT", b.LAST_BILLING_DATE)     AS DAYS_ORDER_TO_BILL,
  h.CDC_OP                                    AS LAST_CDC_OP,
  h.CDC_SOURCE_TS                             AS LAST_CHANGED_IN_SOURCE,
  h.CDC_LOADED_AT                             AS LAST_LOADED_AT
FROM SAP_CURATED.SD.VBAK h
LEFT JOIN SAP_CURATED.SD.VBKD k
  ON k."MANDT" = h."MANDT" AND k."VBELN" = h."VBELN" AND k."POSNR" = '000000' AND NOT k.CDC_IS_DELETED
LEFT JOIN ptn p   ON p."MANDT" = h."MANDT" AND p."VBELN" = h."VBELN"
LEFT JOIN SAP_CURATED.SD.KNA1 ca
  ON ca."MANDT" = h."MANDT" AND ca."KUNNR" = COALESCE(p.SOLD_TO, h."KUNNR") AND NOT ca.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.KNA1 cw
  ON cw."MANDT" = h."MANDT" AND cw."KUNNR" = p.SHIP_TO AND NOT cw.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.TVAK t
  ON t."MANDT" = h."MANDT" AND t."AUART" = h."AUART" AND NOT t.CDC_IS_DELETED
LEFT JOIN itm   i ON i."MANDT" = h."MANDT" AND i."VBELN" = h."VBELN"
LEFT JOIN sched s ON s."MANDT" = h."MANDT" AND s."VBELN" = h."VBELN"
LEFT JOIN dlv   d ON d."MANDT" = h."MANDT" AND d."VBELN" = h."VBELN"
LEFT JOIN bil   b ON b."MANDT" = h."MANDT" AND b."VBELN" = h."VBELN"
WHERE NOT h.CDC_IS_DELETED;

/* ---------------------------------------------------------------------
   2. SALES_DOC_POS
   --------------------------------------------------------------------- */
CREATE OR REPLACE DYNAMIC TABLE SAP_GOLD.SALES.SALES_DOC_POS
  TARGET_LAG = '1 minute'
  WAREHOUSE  = SAP_TRANSFORM_WH
  COMMENT    = 'Sales document items with pricing, confirmation, delivery and billing'
AS
WITH
sched AS (
  SELECT "MANDT", "VBELN", "POSNR",
         COUNT(*)                                       AS SCHEDULE_LINE_COUNT,
         SUM("BMENG")                                   AS CONFIRMED_QTY,
         MIN(IFF("BMENG" > 0, "EDATU", NULL))           AS FIRST_CONFIRMED_DATE,
         MAX(IFF("BMENG" > 0, "EDATU", NULL))           AS LAST_CONFIRMED_DATE,
         MAX("ETTYP")                                   AS SCHEDULE_LINE_CATEGORY
  FROM SAP_CURATED.SD.VBEP
  WHERE NOT CDC_IS_DELETED
  GROUP BY "MANDT", "VBELN", "POSNR"
),
prc AS (
  SELECT c."CLIENT"                                     AS "MANDT", c."KNUMV", c."KPOSN",
         MAX(IFF(c."KSCHL" = 'PR00', c."KBETR", NULL))  AS LIST_PRICE,
         SUM(IFF(c."KSCHL" = 'PR00', c."KWERT", 0))     AS GROSS_PRICE_VALUE,
         SUM(IFF(c."KOAID" = 'A', c."KWERT", 0))        AS DISCOUNT_VALUE,
         SUM(IFF(c."KSCHL" = 'JOCG', c."KWERT", 0))     AS CGST_VALUE,
         SUM(IFF(c."KSCHL" = 'JOSG', c."KWERT", 0))     AS SGST_VALUE,
         SUM(IFF(c."KSCHL" = 'JOIG', c."KWERT", 0))     AS IGST_VALUE,
         SUM(IFF(c."KOAID" = 'D', c."KWERT", 0))        AS TAX_FROM_CONDITIONS
  FROM SAP_CURATED.SD.PRCD_ELEMENTS c
  WHERE NOT c.CDC_IS_DELETED AND NVL(c."KINAK", ' ') = ' '
  GROUP BY c."CLIENT", c."KNUMV", c."KPOSN"
),
dlv AS (
  SELECT p."MANDT", p."VGBEL" AS "VBELN", p."VGPOS" AS "POSNR",
         COUNT(DISTINCT p."VBELN")                      AS DELIVERY_COUNT,
         SUM(p."LFIMG")                                 AS DELIVERED_QTY,
         SUM(IFF(h."WADAT_IST" IS NOT NULL, p."LFIMG", 0)) AS GOODS_ISSUED_QTY,
         MAX(h."WADAT_IST")                             AS LAST_GOODS_ISSUE_DATE,
         MAX(p."VBELN")                                 AS LAST_DELIVERY_DOC
  FROM SAP_CURATED.SD.LIPS p
  JOIN SAP_CURATED.SD.LIKP h
    ON h."MANDT" = p."MANDT" AND h."VBELN" = p."VBELN" AND NOT h.CDC_IS_DELETED
  WHERE NOT p.CDC_IS_DELETED
  GROUP BY p."MANDT", p."VGBEL", p."VGPOS"
),
bil AS (
  SELECT p."MANDT", p."AUBEL" AS "VBELN", p."AUPOS" AS "POSNR",
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."FKIMG") AS NET_BILLED_QTY,
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."NETWR") AS NET_BILLED_VALUE,
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."WAVWR") AS NET_BILLED_COST,
         MAX(h."FKDAT")                                 AS LAST_BILLING_DATE,
         MAX(IFF(h."VBTYP" = 'M' AND NVL(h."FKSTO", ' ') <> 'X', p."VBELN", NULL)) AS LAST_INVOICE_DOC
  FROM SAP_CURATED.SD.VBRP p
  JOIN SAP_CURATED.SD.VBRK h
    ON h."MANDT" = p."MANDT" AND h."VBELN" = p."VBELN" AND NOT h.CDC_IS_DELETED
  WHERE NOT p.CDC_IS_DELETED
  GROUP BY p."MANDT", p."AUBEL", p."AUPOS"
)
SELECT
  i."MANDT"                                   AS CLIENT,
  i."VBELN"                                   AS SALES_DOC,
  i."POSNR"                                   AS ITEM,
  i."VBELN" || '-' || i."POSNR"               AS SALES_DOC_ITEM_KEY,
  i."UEPOS"                                   AS HIGHER_LEVEL_ITEM,
  i."PSTYV"                                   AS ITEM_CATEGORY,
  CASE i."PSTYV" WHEN 'TAN' THEN 'Standard item'   WHEN 'TAD' THEN 'Service item'
                 WHEN 'AGN' THEN 'Quotation item'  WHEN 'REN' THEN 'Returns item'
                 ELSE i."PSTYV" END           AS ITEM_CATEGORY_TEXT,
  h."AUART"                                   AS DOC_TYPE,
  h."VBTYP"                                   AS DOC_CATEGORY,
  h."AUDAT"                                   AS DOC_DATE,
  TO_NUMBER(TO_CHAR(h."AUDAT", 'YYYYMMDD'))   AS DOC_DATE_KEY,
  h."VDATU"                                   AS REQ_DELIVERY_DATE,
  h."VKORG"                                   AS SALES_ORG,
  h."VTWEG"                                   AS DISTR_CHANNEL,
  h."VKBUR"                                   AS SALES_OFFICE,
  h."KUNNR"                                   AS SOLD_TO,
  c."NAME1"                                   AS SOLD_TO_NAME,
  c."REGIO"                                   AS SOLD_TO_REGION,
  i."MATNR"                                   AS MATERIAL,
  COALESCE(mt."MAKTX", i."ARKTX")             AS MATERIAL_TEXT,
  m."MTART"                                   AS MATERIAL_TYPE,
  i."MATKL"                                   AS MATERIAL_GROUP,
  i."PRODH"                                   AS PRODUCT_HIERARCHY,
  m."SPART"                                   AS MATERIAL_DIVISION,
  i."WERKS"                                   AS PLANT,
  i."LGORT"                                   AS STORAGE_LOCATION,
  i."VSTEL"                                   AS SHIPPING_POINT,
  i."ROUTE"                                   AS ROUTE,
  i."PRCTR"                                   AS PROFIT_CENTER,
  i."KWMENG"                                  AS ORDER_QTY,
  i."VRKME"                                   AS SALES_UNIT,
  COALESCE(s.CONFIRMED_QTY, 0)                AS CONFIRMED_QTY,
  i."KWMENG" - COALESCE(s.CONFIRMED_QTY, 0)   AS UNCONFIRMED_QTY,
  COALESCE(d.DELIVERED_QTY, 0)                AS DELIVERED_QTY,
  COALESCE(d.GOODS_ISSUED_QTY, 0)             AS GOODS_ISSUED_QTY,
  IFF(i."ABGRU" IS NULL, i."KWMENG" - COALESCE(d.DELIVERED_QTY, 0), 0) AS OPEN_DELIVERY_QTY,
  COALESCE(b.NET_BILLED_QTY, 0)               AS BILLED_QTY,
  i."WAERK"                                   AS CURRENCY,
  p.LIST_PRICE,
  i."NETPR"                                   AS NET_PRICE,
  COALESCE(p.GROSS_PRICE_VALUE, i."NETWR")    AS GROSS_PRICE_VALUE,
  COALESCE(p.DISCOUNT_VALUE, 0)               AS DISCOUNT_VALUE,
  i."NETWR"                                   AS NET_VALUE,
  COALESCE(p.CGST_VALUE, 0)                   AS CGST_VALUE,
  COALESCE(p.SGST_VALUE, 0)                   AS SGST_VALUE,
  COALESCE(p.IGST_VALUE, 0)                   AS IGST_VALUE,
  i."MWSBP"                                   AS TAX_VALUE,
  i."NETWR" + COALESCE(i."MWSBP", 0)          AS GROSS_VALUE,
  IFF(i."ABGRU" IS NULL, i."NETWR", 0)        AS EFFECTIVE_NET_VALUE,
  COALESCE(b.NET_BILLED_VALUE, 0)             AS NET_BILLED_VALUE,
  COALESCE(b.NET_BILLED_COST, 0)              AS NET_BILLED_COST,
  COALESCE(b.NET_BILLED_VALUE, 0) - COALESCE(b.NET_BILLED_COST, 0) AS NET_BILLED_MARGIN,
  IFF(i."ABGRU" IS NULL, i."NETWR" - COALESCE(b.NET_BILLED_VALUE, 0), 0) AS OPEN_BILLING_VALUE,
  s.FIRST_CONFIRMED_DATE,
  s.LAST_CONFIRMED_DATE,
  d.LAST_GOODS_ISSUE_DATE,
  b.LAST_BILLING_DATE,
  COALESCE(s.SCHEDULE_LINE_COUNT, 0)          AS SCHEDULE_LINE_COUNT,
  COALESCE(d.DELIVERY_COUNT, 0)               AS DELIVERY_COUNT,
  d.LAST_DELIVERY_DOC,
  b.LAST_INVOICE_DOC,
  i."VGBEL"                                   AS REFERENCE_DOC,
  i."VGPOS"                                   AS REFERENCE_ITEM,
  i."ABGRU"                                   AS REJECTION_REASON,
  (i."ABGRU" IS NOT NULL)                     AS IS_REJECTED,
  i."GBSTA"                                   AS OVERALL_STATUS,
  DECODE(i."GBSTA", 'A','Open', 'B','In process', 'C','Completed', 'Not relevant') AS OVERALL_STATUS_TEXT,
  i."LFSTA"                                   AS DELIVERY_STATUS,
  DECODE(i."LFSTA", 'A','Not delivered', 'B','Partially delivered', 'C','Fully delivered', 'Not relevant') AS DELIVERY_STATUS_TEXT,
  i."FKSTA"                                   AS BILLING_STATUS,
  DECODE(i."FKSTA", 'A','Not billed', 'B','Partially billed', 'C','Fully billed', 'Not relevant') AS BILLING_STATUS_TEXT,
  IFF(i."KWMENG" > 0, ROUND(COALESCE(s.CONFIRMED_QTY, 0) / i."KWMENG" * 100, 2), NULL) AS CONFIRMATION_RATE_PCT,
  IFF(i."KWMENG" > 0, ROUND(COALESCE(d.DELIVERED_QTY, 0) / i."KWMENG" * 100, 2), NULL) AS FILL_RATE_PCT,
  (s.FIRST_CONFIRMED_DATE <= h."VDATU")       AS CONFIRMED_ON_REQUEST_DATE,
  (s.LAST_CONFIRMED_DATE > s.FIRST_CONFIRMED_DATE) AS HAS_BACKORDER,
  DATEDIFF('day', h."AUDAT", d.LAST_GOODS_ISSUE_DATE) AS DAYS_ORDER_TO_SHIP,
  i."ERDAT"                                   AS CREATED_ON,
  i."ERNAM"                                   AS CREATED_BY,
  i."AEDAT"                                   AS CHANGED_ON,
  i.CDC_OP                                    AS LAST_CDC_OP,
  i.CDC_SOURCE_TS                             AS LAST_CHANGED_IN_SOURCE,
  i.CDC_LOADED_AT                             AS LAST_LOADED_AT
FROM SAP_CURATED.SD.VBAP i
JOIN SAP_CURATED.SD.VBAK h
  ON h."MANDT" = i."MANDT" AND h."VBELN" = i."VBELN" AND NOT h.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.KNA1 c
  ON c."MANDT" = h."MANDT" AND c."KUNNR" = h."KUNNR" AND NOT c.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.MARA m
  ON m."MANDT" = i."MANDT" AND m."MATNR" = i."MATNR" AND NOT m.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.MAKT mt
  ON mt."MANDT" = i."MANDT" AND mt."MATNR" = i."MATNR" AND mt."SPRAS" = 'E' AND NOT mt.CDC_IS_DELETED
LEFT JOIN sched s ON s."MANDT" = i."MANDT" AND s."VBELN" = i."VBELN" AND s."POSNR" = i."POSNR"
LEFT JOIN prc   p ON p."MANDT" = h."MANDT" AND p."KNUMV" = h."KNUMV" AND p."KPOSN" = i."POSNR"
LEFT JOIN dlv   d ON d."MANDT" = i."MANDT" AND d."VBELN" = i."VBELN" AND d."POSNR" = i."POSNR"
LEFT JOIN bil   b ON b."MANDT" = i."MANDT" AND b."VBELN" = i."VBELN" AND b."POSNR" = i."POSNR"
WHERE NOT i.CDC_IS_DELETED;

/* ---------------------------------------------------------------------
   3. DEL_DOC_POS
   --------------------------------------------------------------------- */
CREATE OR REPLACE DYNAMIC TABLE SAP_GOLD.SALES.DEL_DOC_POS
  TARGET_LAG = '1 minute'
  WAREHOUSE  = SAP_TRANSFORM_WH
  COMMENT    = 'Outbound and returns delivery items with order, goods issue and billing'
AS
WITH
bil AS (
  SELECT p."MANDT", p."VGBEL" AS "VBELN", p."VGPOS" AS "POSNR",
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."FKIMG")  AS NET_BILLED_QTY,
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."NETWR")  AS NET_BILLED_VALUE,
         SUM(IFF(h."VBTYP" IN ('N','O'), -1, 1) * p."WAVWR")  AS NET_BILLED_COST,
         MAX(h."FKDAT")                                       AS LAST_BILLING_DATE,
         MAX(IFF(h."VBTYP" = 'M' AND NVL(h."FKSTO", ' ') <> 'X', p."VBELN", NULL)) AS INVOICE_DOC
  FROM SAP_CURATED.SD.VBRP p
  JOIN SAP_CURATED.SD.VBRK h
    ON h."MANDT" = p."MANDT" AND h."VBELN" = p."VBELN" AND NOT h.CDC_IS_DELETED
  WHERE NOT p.CDC_IS_DELETED
  GROUP BY p."MANDT", p."VGBEL", p."VGPOS"
),
gm AS (
  SELECT "MANDT", "VBELV" AS "VBELN", "POSNV" AS "POSNR",
         MAX("VBELN")                                         AS MATERIAL_DOC,
         MAX("ERDAT")                                         AS MATERIAL_DOC_DATE
  FROM SAP_CURATED.SD.VBFA
  WHERE NOT CDC_IS_DELETED AND "VBTYP_N" IN ('R', 'h')
  GROUP BY "MANDT", "VBELV", "POSNV"
)
SELECT
  p."MANDT"                                   AS CLIENT,
  p."VBELN"                                   AS DELIVERY_DOC,
  p."POSNR"                                   AS ITEM,
  p."VBELN" || '-' || p."POSNR"               AS DELIVERY_ITEM_KEY,
  h."LFART"                                   AS DELIVERY_TYPE,
  t."BEZEI"                                   AS DELIVERY_TYPE_TEXT,
  h."VBTYP"                                   AS DELIVERY_CATEGORY,
  (h."VBTYP" = 'T')                           AS IS_RETURN,
  p."PSTYV"                                   AS ITEM_CATEGORY,
  p."VGBEL"                                   AS SALES_DOC,
  p."VGPOS"                                   AS SALES_ITEM,
  p."VGBEL" || '-' || p."VGPOS"               AS SALES_DOC_ITEM_KEY,
  o."AUART"                                   AS SALES_DOC_TYPE,
  o."AUDAT"                                   AS ORDER_DATE,
  o."VDATU"                                   AS REQ_DELIVERY_DATE,
  o."BSTNK"                                   AS CUSTOMER_PO,
  h."VKORG"                                   AS SALES_ORG,
  h."VSTEL"                                   AS SHIPPING_POINT,
  h."ROUTE"                                   AS ROUTE,
  p."WERKS"                                   AS PLANT,
  p."LGORT"                                   AS STORAGE_LOCATION,
  p."CHARG"                                   AS BATCH,
  p."PRCTR"                                   AS PROFIT_CENTER,
  h."INCO1"                                   AS INCOTERMS,
  h."INCO2"                                   AS INCOTERMS_LOCATION,
  h."KUNAG"                                   AS SOLD_TO,
  ca."NAME1"                                  AS SOLD_TO_NAME,
  h."KUNNR"                                   AS SHIP_TO,
  cw."NAME1"                                  AS SHIP_TO_NAME,
  cw."ORT01"                                  AS SHIP_TO_CITY,
  cw."REGIO"                                  AS SHIP_TO_REGION,
  cw."PSTLZ"                                  AS SHIP_TO_POSTAL_CODE,
  p."MATNR"                                   AS MATERIAL,
  COALESCE(mt."MAKTX", p."ARKTX")             AS MATERIAL_TEXT,
  p."MATKL"                                   AS MATERIAL_GROUP,
  p."LFIMG"                                   AS DELIVERY_QTY,
  p."VRKME"                                   AS SALES_UNIT,
  p."LGMNG"                                   AS DELIVERY_QTY_BASE_UNIT,
  p."MEINS"                                   AS BASE_UNIT,
  IFF(h."VBTYP" = 'T', -1, 1) * p."LFIMG"     AS DELIVERY_QTY_SIGNED,
  IFF(h."WADAT_IST" IS NOT NULL, p."LFIMG", 0) AS GOODS_ISSUED_QTY,
  oi."KWMENG"                                 AS ORDER_QTY,
  COALESCE(b.NET_BILLED_QTY, 0)               AS BILLED_QTY,
  p."LFIMG" - ABS(COALESCE(b.NET_BILLED_QTY, 0)) AS OPEN_BILLING_QTY,
  p."NTGEW"                                   AS NET_WEIGHT,
  p."BRGEW"                                   AS GROSS_WEIGHT,
  p."GEWEI"                                   AS WEIGHT_UNIT,
  h."ANZPK"                                   AS PACKAGES_IN_DELIVERY,
  oi."WAERK"                                  AS CURRENCY,
  oi."NETPR"                                  AS NET_PRICE,
  ROUND(oi."NETPR" / NULLIF(oi."KPEIN", 0) * p."LFIMG", 2) AS DELIVERY_NET_VALUE,
  IFF(h."VBTYP" = 'T', -1, 1)
    * ROUND(oi."NETPR" / NULLIF(oi."KPEIN", 0) * p."LFIMG", 2) AS DELIVERY_NET_VALUE_SIGNED,
  COALESCE(b.NET_BILLED_VALUE, 0)             AS NET_BILLED_VALUE,
  COALESCE(b.NET_BILLED_COST, 0)              AS NET_BILLED_COST,
  h."ERDAT"                                   AS DELIVERY_CREATED_ON,
  h."LFDAT"                                   AS PLANNED_DELIVERY_DATE,
  h."KODAT"                                   AS PICKING_DATE,
  h."LDDAT"                                   AS LOADING_DATE,
  h."WADAT"                                   AS PLANNED_GOODS_ISSUE_DATE,
  h."WADAT_IST"                               AS ACTUAL_GOODS_ISSUE_DATE,
  TO_NUMBER(TO_CHAR(h."WADAT_IST", 'YYYYMMDD')) AS GOODS_ISSUE_DATE_KEY,
  b.LAST_BILLING_DATE,
  g.MATERIAL_DOC,
  g.MATERIAL_DOC_DATE,
  b.INVOICE_DOC,
  p."KOSTA"                                   AS PICKING_STATUS,
  DECODE(p."KOSTA", 'A','Not picked', 'B','Partially picked', 'C','Fully picked', 'Not relevant') AS PICKING_STATUS_TEXT,
  p."WBSTA"                                   AS GOODS_MOVEMENT_STATUS,
  DECODE(p."WBSTA", 'A','Not posted', 'B','Partially posted', 'C','Goods issue posted', 'Not relevant') AS GOODS_MOVEMENT_STATUS_TEXT,
  p."FKSTA"                                   AS BILLING_STATUS,
  DECODE(p."FKSTA", 'A','Not billed', 'B','Partially billed', 'C','Fully billed', 'Not relevant') AS BILLING_STATUS_TEXT,
  p."GBSTA"                                   AS OVERALL_STATUS,
  DECODE(p."GBSTA", 'A','Open', 'B','In process', 'C','Completed', 'Not relevant') AS OVERALL_STATUS_TEXT,
  (h."LIFSK" IS NOT NULL)                     AS IS_DELIVERY_BLOCKED,
  (h."WADAT_IST" IS NOT NULL)                 AS IS_GOODS_ISSUED,
  (h."WADAT_IST" IS NOT NULL AND NVL(p."FKSTA", 'A') <> 'C' AND h."VBTYP" = 'J') AS IS_SHIPPED_NOT_BILLED,
  IFF(h."WADAT_IST" IS NOT NULL, h."WADAT_IST" <= h."WADAT", NULL)  AS GOODS_ISSUE_ON_TIME,
  IFF(h."WADAT_IST" IS NOT NULL, h."WADAT_IST" <= o."VDATU", NULL)  AS SHIPPED_BY_REQUEST_DATE,
  DATEDIFF('day', h."WADAT", h."WADAT_IST")   AS GOODS_ISSUE_DELAY_DAYS,
  DATEDIFF('day', o."AUDAT", h."WADAT_IST")   AS DAYS_ORDER_TO_GOODS_ISSUE,
  DATEDIFF('day', h."WADAT_IST", b.LAST_BILLING_DATE) AS DAYS_GOODS_ISSUE_TO_BILL,
  p."ERNAM"                                   AS CREATED_BY,
  p."AEDAT"                                   AS CHANGED_ON,
  p.CDC_OP                                    AS LAST_CDC_OP,
  p.CDC_SOURCE_TS                             AS LAST_CHANGED_IN_SOURCE,
  GREATEST(p.CDC_LOADED_AT, h.CDC_LOADED_AT)  AS LAST_LOADED_AT
FROM SAP_CURATED.SD.LIPS p
JOIN SAP_CURATED.SD.LIKP h
  ON h."MANDT" = p."MANDT" AND h."VBELN" = p."VBELN" AND NOT h.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.VBAP oi
  ON oi."MANDT" = p."MANDT" AND oi."VBELN" = p."VGBEL" AND oi."POSNR" = p."VGPOS" AND NOT oi.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.VBAK o
  ON o."MANDT" = p."MANDT" AND o."VBELN" = p."VGBEL" AND NOT o.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.KNA1 ca
  ON ca."MANDT" = h."MANDT" AND ca."KUNNR" = h."KUNAG" AND NOT ca.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.KNA1 cw
  ON cw."MANDT" = h."MANDT" AND cw."KUNNR" = h."KUNNR" AND NOT cw.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.MAKT mt
  ON mt."MANDT" = p."MANDT" AND mt."MATNR" = p."MATNR" AND mt."SPRAS" = 'E' AND NOT mt.CDC_IS_DELETED
LEFT JOIN SAP_CURATED.SD.TVLK t
  ON t."MANDT" = h."MANDT" AND t."LFART" = h."LFART" AND NOT t.CDC_IS_DELETED
LEFT JOIN bil b ON b."MANDT" = p."MANDT" AND b."VBELN" = p."VBELN" AND b."POSNR" = p."POSNR"
LEFT JOIN gm  g ON g."MANDT" = p."MANDT" AND g."VBELN" = p."VBELN" AND g."POSNR" = p."POSNR"
WHERE NOT p.CDC_IS_DELETED;
