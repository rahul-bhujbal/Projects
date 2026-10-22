# Oracle → Kafka → Snowflake CDC (SAP S/4HANA SD tables)

Near-real-time pipeline that runs on your laptop plus a Snowflake account:

```
Oracle Free (30 SAP SD tables, schema SAPSD)
   │  redo log (LogMiner)
   ▼
Debezium Oracle connector ──► Kafka topic per table  (sap.SAPSD.VBAK, ...)
                                   │
                                   ▼
                     Snowflake Connector for Kafka v4 (Snowpipe Streaming)
                                   │  ~5-10 s
                                   ▼
          SAP_RAW.SD.<TABLE>_RAW   RECORD_CONTENT / RECORD_METADATA (VARIANT)
                                   │  stream + task, every minute
                                   ▼
          SAP_CORE.SD.<TABLE>      current state, soft deletes
          SAP_CORE.SD.V_<TABLE>    typed views   (+ V_NET_REVENUE_DAILY)
```

Expected latency from Oracle commit to `SAP_CORE`: about 1–2 minutes.

## What you need

- Docker Desktop (or Docker Engine) with **8 GB of memory** for containers
- A Snowflake account (a trial works) and a user with ACCOUNTADMIN
- `bash`, `curl`, `openssl` (Linux/macOS terminal, or Git Bash / WSL on Windows)
- Python 3 (only if you regenerate files from the DDL)

## Project layout

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Oracle Free, Kafka (KRaft), Kafka Connect, Kafka UI |
| `connect/Dockerfile` | Debezium Connect image + Snowflake connector v4 + Oracle JDBC |
| `oracle/s4_sd_oracle_ddl.sql` | 30 SAP SD tables |
| `oracle/s4_sd_sample_data.sql` | ~1,140 rows of linked order-to-cash data |
| `oracle/01_debezium_user.sql` | supplemental logging, LogMiner user `c##dbzuser` |
| `oracle/90_test_changes.sql` | insert / update / delete batch to test CDC |
| `connectors/oracle-source.json` | Debezium source config |
| `connectors/snowflake-sink.json` | Snowflake sink config (generated) |
| `snowflake/generate_snowflake_keys.sh` | key pair + rendered setup SQL |
| `snowflake/snowflake_setup.sql` | roles, user, databases, grants |
| `snowflake/02_snowflake_core.sql` | streams, MERGE tasks, typed views (generated) |
| `snowflake/03_checks.sql` | exactly-once, counts, latency, task history (generated) |
| `scripts/*.sh` | setup, connector registration, test changes, status |
| `scripts/generate_from_ddl.py` | regenerates the generated files from the Oracle DDL |

## Step 1 – Snowflake account setup

```bash
cd snowflake
bash generate_snowflake_keys.sh
```

Then in a Snowsight worksheet:

1. Open `snowflake/snowflake_setup_rendered.sql`.
2. In section 4, uncomment and edit
   `GRANT ROLE SAP_TRANSFORM_ROLE TO USER <YOUR_SNOWFLAKE_USER>;`
3. Run the whole file.
4. Check that `RSA_PUBLIC_KEY_FP` (from `DESC USER`) equals the fingerprint the
   key script printed.
5. Copy `snowflake_url_name` from the last query.

## Step 2 – Start the local stack

```bash
cp .env.example .env          # set SNOWFLAKE_URL to the value from step 1
docker compose up -d --build
```

The first start downloads images and builds the Connect image; Oracle needs a
few minutes to initialise.

## Step 3 – Prepare Oracle and load the SAP tables

```bash
./scripts/01_oracle_setup.sh
```

This turns on ARCHIVELOG mode (one database restart inside the container),
creates the Debezium user, creates the 30 tables with full supplemental
logging, loads the sample data, and prints row counts.

## Step 4 – Start CDC into Kafka

```bash
./scripts/02_register_connectors.sh source
```

Debezium snapshots all 30 tables, then streams changes. Watch the topics at
<http://localhost:8080> (Kafka UI): open `sap.SAPSD.VBAK` and look at the
`before` / `after` / `op` / `source.scn` fields.

## Step 5 – Start loading Snowflake

```bash
./scripts/02_register_connectors.sh sink
./scripts/status.sh            # both connectors should be RUNNING
```

In Snowflake, `SHOW TABLES IN SCHEMA SAP_RAW.SD;` should list 30 `*_RAW`
tables within a minute or two.

## Step 6 – Build the current-state layer

Run `snowflake/02_snowflake_core.sql` in Snowsight. It enables change
tracking on the raw tables, creates the core tables, streams, merge tasks and
typed views, then starts the tasks and runs each once for the snapshot.

Query it:

```sql
SELECT * FROM SAP_CORE.SD.V_VBAK ORDER BY "VBELN";
SELECT * FROM SAP_CORE.SD.V_NET_REVENUE_DAILY ORDER BY BILLING_DATE;
```

## Step 7 – Prove it works

```bash
./scripts/03_make_changes.sh
```

Within about two minutes in Snowflake:

- order `0000010022` shows `CMGST = 'A'` (credit released)
- new order `0000019001` appears in `V_VBAK`, `V_VBAP`, `V_VBEP`, `V_VBPA`
- order `0000010023` item `000010` has `ABGRU = '02'` and a lower header `NETWR`
- quotation `0020000002` is gone from `V_VBAK` but still in `SAP_CORE.SD.VBAK`
  with `IS_DELETED = TRUE`

Then run `snowflake/03_checks.sql`:

1. raw events = distinct events for every table (exactly-once)
2. live row counts match Oracle (`docker exec -i oracle sqlplus -s SAPSD/sapsd@//localhost:1521/FREEPDB1 < oracle/91_row_counts.sql`)
3. p50 / p90 latency of streamed changes
4. task history (no FAILED runs)
5. net revenue matches the Oracle query at the end of `oracle/s4_sd_sample_data.sql`

## Break it on purpose

| Do this | Expect |
|---|---|
| `docker restart connect` while `03_make_changes.sh` runs | no duplicates (check 1), counts still match |
| `docker stop connect`, make changes, wait, `docker start connect` | backlog catches up from Kafka offsets |
| run `03_make_changes.sh` twice | order 0000019001 deleted then re-inserted; core shows one live row |
| `ALTER TASK SAP_CORE.SD.TSK_VBAK SUSPEND;` make changes, then resume | stream holds the changes; one MERGE applies them |
| `TRUNCATE TABLE SAP_CORE.SD.VBAK;` then recreate its stream with `SHOW_INITIAL_ROWS = TRUE` | VBAK rebuilt from the raw history |

## Curated layer (structured tables)

`snowflake/04_curated_layer.sql` builds `SAP_CURATED.SD`: one physical table per
SAP table with real typed columns (VARCHAR / NUMBER(p,s) / DATE, the same as in
Oracle) plus `CDC_OP`, `CDC_SCN`, `CDC_SOURCE_TS`, `CDC_LOADED_AT` and
`CDC_IS_DELETED`. A stream and a one-minute MERGE task per table keep it current
from `SAP_RAW`. Two dynamic tables sit on top:

- `FCT_SALES_ORDER_ITEM`: order items with header, customer and material
- `FCT_BILLING_ITEM`: billing items with signed revenue (cancellations and credit memos negative)

Run the whole file in Snowsight once the raw tables exist. Section E has the
checks, and section F shows how to rebuild a table from raw history. Regenerate
it after a DDL change with `python3 scripts/generate_curated.py`.

## Customer portal (web app on the Gold layer)

`portal/` is a customer order portal: account selector, product search, Order
Dashboard (order / PO / delivery / invoice search, quick and recent order
search, manage orders, delivery search, document search, return center) and a
Quick Cart with CSV upload, copy-paste, Check Availability and Place Order.
Every screen reads `SAP_GOLD.SALES` (built by `snowflake/07_gold_sales.sql`)
with parameterized, read-only queries. Place Order writes a real order into
Oracle; it comes back to the portal through CDC in about 2-3 minutes, and the
confirmation page shows when it arrives.

1. Snowflake access: create the portal key pair and run `snowflake/06_portal_access.sql`.
2. `cp portal/.env.example portal/.env` and fill in the account (and key path).
3. Start it from the project folder:

```bash
pip install -r portal/requirements.txt
python -m uvicorn portal.app:app --reload --port 8000
```

4. Open <http://localhost:8000>. API docs: <http://localhost:8000/docs>.

Availability shows list price and an estimated ship date from shipping history
(average days from order to goods issue per material); the model has no stock table.

### AI assistant in the portal

Every page has an **Ask AI** button (and Recent Orders shows suggested
questions). It sends the question, the selected customer and the conversation
so far to the Cortex Agent `SAP_GOLD.SALES.SAP_SALES_AGENT`
(`snowflake/05_sales_agent.sql`) through the Cortex Agents REST API, and shows
the answer with its result table and the SQL it ran. One-time setup: run the
"AI assistant" section at the end of `snowflake/06_portal_access.sql`.

## Daily orders

`scripts/daily_orders.py` inserts a day of new sales orders (default 10 orders,
50 line items in total), each order in one Oracle transaction across VBAK, VBAP,
VBEP, VBKD, VBPA and PRCD_ELEMENTS. Order numbers start at `0000100000`.

```bash
pip install oracledb
python scripts/daily_orders.py --dry-run          # preview, inserts nothing
python scripts/daily_orders.py                    # today: 10 orders, 50 items
python scripts/daily_orders.py --backfill-days 7  # one batch per day for the last week
```

Schedule it every day at 09:00 with Windows Task Scheduler (run once in
Command Prompt, with the real project path):

```
schtasks /create /tn "SAP daily orders" /sc daily /st 09:00 ^
  /tr "\"D:\path\to\oracle-snowflake-cdc\scripts\run_daily_orders.bat\""
```

Output goes to `logs/daily_orders.log`. Docker Desktop and the `oracle`
container must be running at that time.

## Cost control (trial credits)

- The connector is billed per GB ingested; it uses no warehouse.
- The merge tasks run only when their stream has data, on an XS warehouse
  that suspends after 60 seconds.
- When you stop testing, suspend the tasks (section E of
  `02_snowflake_core.sql`) and run `docker compose stop`.
- Streams go stale if tasks stay suspended longer than the table retention
  plus 14 days; then recreate the stream.

## Troubleshooting

| Symptom | Where to look / fix |
|---|---|
| Source connector FAILED, `ORA-01031` / LogMiner errors | re-run `./scripts/01_oracle_setup.sh` (grants are idempotent); `docker logs connect` |
| Source RUNNING but no topics | the snapshot is still running; `docker logs -f connect` |
| Sink FAILED with JWT / auth error | fingerprint mismatch: re-run section 2 of the rendered setup SQL; check `SNOWFLAKE_URL` in `.env` |
| Sink FAILED with privilege error | `SHOW GRANTS TO ROLE KAFKA_CONNECTOR_ROLE;` grants must be direct, not inherited |
| `02_snowflake_core.sql` stream creation fails | raw table not created yet, or change tracking not on: re-run section A as SYSADMIN |
| Task FAILED | check 4 in `03_checks.sql` shows the error message |
| Connect container restarts (OOM) | give Docker more memory; keep `HEAP_OPTS` at about half of `mem_limit` |

## Changing the tables

Edit `oracle/s4_sd_oracle_ddl.sql`, then run
`python3 scripts/generate_from_ddl.py` to regenerate the sink config,
the Snowflake core SQL, the checks, and the Oracle row-count script.
