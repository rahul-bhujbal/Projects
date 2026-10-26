# Oracle AI SQL Assistant

Ask a business question in plain English. The assistant writes Oracle SQL, runs it safely on your Oracle database, and explains the answer.

> "What were total sales by region in 2025?" → Oracle SQL → result table + chart → "West led with ..."

## How it works

```
Question
   │
   ▼
Read table schema (ALL_TAB_COLUMNS + column comments)
   │
   ▼
LLM writes Oracle SQL ──► Safety check (SELECT only, one statement, no PL/SQL)
   │                                │
   │           error? ◄─────────────┤  LLM fixes its own SQL once (ORA- error fed back)
   ▼                                │
Run on Oracle (max 200 rows, ROWNUM)
   │
   ▼
LLM explains the result in plain English
   │
   ▼
Streamlit app: SQL + table + chart + answer
```

## Step-by-step setup

### Step 1 – Have an Oracle database
Any Oracle 12c or later works: a local **Oracle Database XE** (free), a company dev database, or an **Oracle Autonomous Database** (free tier on Oracle Cloud).

For local XE 21c, the connection string is usually `localhost:1521/XEPDB1`. Create a demo user (as SYSTEM or SYS):
```sql
ALTER SESSION SET CONTAINER = XEPDB1;
CREATE USER sales_demo IDENTIFIED BY "StrongPass#1";
GRANT CREATE SESSION, CREATE TABLE TO sales_demo;
ALTER USER sales_demo QUOTA 100M ON USERS;
```

### Step 2 – Set up Python
```powershell
cd D:\Anthropic\claude-code-in-one-shot\oracle-ai-sql-assistant
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
`python-oracledb` runs in thin mode, so no Oracle Client install is needed.

### Step 3 – Add your credentials
```powershell
copy .env.example .env
notepad .env
```
Fill in `ANTHROPIC_API_KEY`, `ORACLE_USER`, `ORACLE_PASSWORD` and `ORACLE_DSN`.

### Step 4 – Load the sample sales data (optional)
```powershell
python setup_sample_data.py
```
Creates REGIONS, CUSTOMERS, PRODUCTS, ORDERS and ORDER_ITEMS in your schema with about 6,000 orders for 2024–2025. Skip this if you want to query your own tables; set `ORACLE_SCHEMA` and `ORACLE_TABLES` in `.env` instead.

### Step 5 – Test in the terminal
```powershell
python sql_assistant.py
```
Try: `What were total sales by region in 2025?`

### Step 6 – Launch the web app
```powershell
streamlit run app.py
```
Your browser opens at http://localhost:8501.

## What each step in the code does

| Step | Function | Purpose |
|---|---|---|
| 1 | config block | Loads settings from `.env` |
| 2 | `get_connection` | Connects with python-oracledb (thin mode, optional wallet) |
| 3 | `get_schema_text` | Reads tables, columns and column comments |
| 4 | `generate_sql` | Prompts the LLM to write one read-only Oracle query |
| 5 | `validate_sql` | Blocks DML, DDL, PL/SQL blocks, `FOR UPDATE` and `DBMS_`/`UTL_` packages |
| 6 | `run_sql` | Runs the query with a 200-row `ROWNUM` limit |
| 7 | retry in `answer_question` | Sends the ORA- error back so the LLM fixes its SQL |
| 8 | `summarize` | Turns the result into a plain-English answer |
| 9 | `app.py` | Streamlit UI with SQL, table, chart and answer |

## Example questions (sample data)
- What were total sales by region in 2025?
- Top 10 customers by total order value
- Monthly revenue for 2025
- Which product category has the highest average discount?
- How many orders were cancelled per region?

## Troubleshooting
| Error | Fix |
|---|---|
| `DPY-6005` / `ORA-12541` cannot connect | Check `ORACLE_DSN` host, port and that the listener is running |
| `ORA-12514` service not known | Wrong service name; for XE 21c use `XEPDB1`, not `XE` |
| `ORA-01017` invalid username/password | Check `ORACLE_USER` / `ORACLE_PASSWORD` |
| `No tables found in schema` | Run `setup_sample_data.py` or set `ORACLE_SCHEMA` |
| `ORA-01950` no privileges on tablespace | `ALTER USER sales_demo QUOTA 100M ON USERS;` |

## Ideas to extend it (good for interviews)
- Connect as a **read-only Oracle user** (SELECT grants only) so safety is enforced by the database.
- Log each question, SQL and result to an Oracle table to measure accuracy.
- Add a test set of questions with known answers and score the assistant.
- Use **Oracle Database 23ai Select AI** for comparison.

## Tech stack
Python · Oracle Database · python-oracledb · Anthropic Claude API · Streamlit · pandas
