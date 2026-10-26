# AI SQL Assistant

Ask a business question in plain English. The assistant writes Snowflake SQL, runs it safely, and explains the answer.

> "What were total sales by region in 1997?" → SQL → Snowflake → "Europe led with ..."

## How it works

```
Question
   │
   ▼
Read table schema (INFORMATION_SCHEMA)
   │
   ▼
LLM writes SQL ──► Safety check (SELECT only, one statement)
   │                         │
   │        error? ◄─────────┤  LLM fixes its own SQL once
   ▼                         │
Run on Snowflake (max 200 rows)
   │
   ▼
LLM explains the result in plain English
   │
   ▼
Streamlit app: SQL + table + chart + answer
```

## Step-by-step setup

### Step 1 – Get a Snowflake account
1. Sign up for a free 30-day trial at signup.snowflake.com.
2. Every account includes the `SNOWFLAKE_SAMPLE_DATA` database. This project uses `TPCH_SF1`, a sales dataset with regions, nations, customers, orders and line items.
3. Note your **account identifier** (Admin → Accounts, or the URL), user name and warehouse (`COMPUTE_WH` by default).

If your account requires MFA, password sign-in from code may be blocked. Create a **programmatic access token** in Snowsight (your profile → Settings → Authentication) and put it in `SNOWFLAKE_PASSWORD`, or use key-pair auth.

### Step 2 – Get an LLM API key
Create an API key at console.anthropic.com and add some credits. Each question costs a fraction of a cent.

### Step 3 – Set up Python
```bash
cd ai-sql-assistant
python -m venv .venv
# Windows: .venv\Scripts\activate     Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### Step 4 – Add your credentials
```bash
cp .env.example .env     # Windows: copy .env.example .env
```
Open `.env` and fill in your values. Add `.env` to `.gitignore` so secrets never reach GitHub.

### Step 5 – Test in the terminal
```bash
python sql_assistant.py
```
Try: `What were total sales by region in 1997?`

### Step 6 – Launch the web app
```bash
streamlit run app.py
```
Your browser opens at http://localhost:8501.

## What each step in the code does

| Step | Function | Purpose |
|---|---|---|
| 1 | config block | Loads settings from `.env` |
| 2 | `get_connection` | Connects to Snowflake |
| 3 | `get_schema_text` | Reads tables and columns so the LLM knows what exists |
| 4 | `generate_sql` | Prompts the LLM to write one read-only query |
| 5 | `validate_sql` | Blocks anything other than a single SELECT |
| 6 | `run_sql` | Runs the query with a 200-row limit |
| 7 | retry in `answer_question` | Sends the error back so the LLM fixes its SQL |
| 8 | `summarize` | Turns the result into a plain-English answer |
| 9 | `app.py` | Streamlit UI with SQL, table, chart and answer |

## Example questions
- What were total sales by region in 1997?
- Top 10 customers by total order value
- Monthly order count for 1996
- Which nation has the most suppliers?
- Average discount by ship mode

## Ideas to extend it (good for interviews)
- Add a **read-only Snowflake role** so safety is enforced by the database, not just the code.
- Log every question, SQL and result to a Snowflake table to measure accuracy.
- Add a small test set of questions with known answers and score the assistant.
- Swap the LLM call for **Snowflake Cortex** (`SNOWFLAKE.CORTEX.COMPLETE`) so data never leaves Snowflake.
- Deploy it as **Streamlit in Snowflake**.

## Tech stack
Python · Snowflake · Anthropic Claude API · Streamlit · pandas
