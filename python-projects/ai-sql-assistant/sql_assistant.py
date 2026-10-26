"""
AI SQL Assistant - core logic.

Flow:  question -> read table schema -> LLM writes SQL -> safety check
       -> run on Snowflake (retry once with the error if it fails)
       -> LLM explains the result in plain English.

Run from the terminal:  python sql_assistant.py
"""

import os
import re
from pathlib import Path

import anthropic
import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# STEP 1 - Configuration (values come from the .env file)
# ---------------------------------------------------------------------------
ENV_FILE = Path(__file__).resolve().with_name(".env")
load_dotenv(ENV_FILE)  # always the .env next to this script, whatever folder you run from


def _require(name: str) -> str:
    """Read a required setting, with a clear message if it is missing."""
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing setting {name}.\n"
            f"Expected it in: {ENV_FILE}\n"
            f".env file found: {ENV_FILE.exists()}\n"
            "Copy .env.example to .env (not .env.txt) and fill in your values."
        )
    return value

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
DATABASE = os.getenv("SNOWFLAKE_DATABASE", "SNOWFLAKE_SAMPLE_DATA")
SCHEMA = os.getenv("SNOWFLAKE_SCHEMA", "TPCH_SF1")
TABLES = ["REGION", "NATION", "CUSTOMER", "ORDERS", "LINEITEM", "PART", "SUPPLIER"]
MAX_ROWS = 200        # never pull more than this into the app
MAX_ATTEMPTS = 2      # first try + one self-correction

llm = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


# ---------------------------------------------------------------------------
# STEP 2 - Connect to Snowflake
# ---------------------------------------------------------------------------
def get_connection():
    """Open a Snowflake connection using password/PAT or key-pair auth."""
    params = dict(
        account=_require("SNOWFLAKE_ACCOUNT"),
        user=_require("SNOWFLAKE_USER"),
        warehouse=_require("SNOWFLAKE_WAREHOUSE"),
        database=DATABASE,
        schema=SCHEMA,
    )
    if os.getenv("SNOWFLAKE_ROLE"):
        params["role"] = os.environ["SNOWFLAKE_ROLE"]

    key_file = os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE")
    if key_file:
        params["private_key_file"] = key_file
    else:
        # A programmatic access token (PAT) also goes here.
        params["password"] = _require("SNOWFLAKE_PASSWORD")

    return snowflake.connector.connect(**params)


# ---------------------------------------------------------------------------
# STEP 3 - Read the table structure so the LLM knows what exists
# ---------------------------------------------------------------------------
def get_schema_text(conn) -> str:
    """Return the tables and columns as compact text, e.g. ORDERS(O_ORDERKEY NUMBER, ...)."""
    placeholders = ", ".join(["%s"] * len(TABLES))
    sql = f"""
        SELECT table_name, column_name, data_type
        FROM {DATABASE}.INFORMATION_SCHEMA.COLUMNS
        WHERE table_schema = %s AND table_name IN ({placeholders})
        ORDER BY table_name, ordinal_position
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, [SCHEMA, *TABLES])
        rows = cur.fetchall()
    finally:
        cur.close()

    tables: dict[str, list[str]] = {}
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(f"{column} {dtype}")
    return "\n".join(f"{t}({', '.join(cols)})" for t, cols in tables.items())


# ---------------------------------------------------------------------------
# STEP 4 - Ask the LLM to write SQL
# ---------------------------------------------------------------------------
SQL_SYSTEM_PROMPT = """You are an expert Snowflake SQL analyst.
Write ONE read-only Snowflake SQL query (SELECT or WITH ... SELECT) that answers the user's question.
Rules:
- Use only the tables and columns listed in the schema.
- Fully qualify tables as {db}.{schema}.<TABLE>.
- Use clear column aliases (e.g. total_sales).
- Never modify data.
Return only the SQL inside a ```sql code block, with no explanation."""


def _ask_llm(system: str, user: str, max_tokens: int = 1024) -> str:
    response = llm.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # The model may return a "thinking" block first, so keep only the text blocks.
    return "".join(block.text for block in response.content if block.type == "text")


def _extract_sql(text: str) -> str:
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip().rstrip(";").strip()


def generate_sql(question: str, schema_text: str, previous_error: str | None = None,
                 previous_sql: str | None = None) -> str:
    system = SQL_SYSTEM_PROMPT.format(db=DATABASE, schema=SCHEMA)
    user = f"Schema:\n{schema_text}\n\nQuestion: {question}"
    if previous_error:
        # STEP 7 (self-correction): show the model its own failed SQL and the error
        user += (f"\n\nYour previous query failed.\nQuery:\n{previous_sql}\n"
                 f"Error:\n{previous_error}\nFix the query.")
    return _extract_sql(_ask_llm(system, user))


# ---------------------------------------------------------------------------
# STEP 5 - Safety check: only allow a single read-only query
# ---------------------------------------------------------------------------
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|"
    r"CALL|COPY|PUT|GET|REMOVE|UNDROP|USE|EXECUTE)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> None:
    """Raise ValueError if the SQL is not a single SELECT/WITH query."""
    if ";" in sql:
        raise ValueError("Only one SQL statement is allowed.")
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("The query contains a forbidden keyword.")


# ---------------------------------------------------------------------------
# STEP 6 - Run the SQL on Snowflake (with a row limit)
# ---------------------------------------------------------------------------
def run_sql(conn, sql: str) -> pd.DataFrame:
    limited = f"SELECT * FROM (\n{sql}\n) LIMIT {MAX_ROWS}"
    cur = conn.cursor()
    try:
        cur.execute(limited)
        return cur.fetch_pandas_all()
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# STEP 8 - Explain the result in plain English
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM_PROMPT = """You are a business data analyst.
Answer the user's question in 2-4 short sentences using ONLY the query result provided.
Mention the key numbers. If the result is empty, say so plainly."""


def summarize(question: str, df: pd.DataFrame) -> str:
    preview = df.head(50).to_csv(index=False)
    user = f"Question: {question}\n\nQuery result (CSV, first 50 rows):\n{preview}"
    return _ask_llm(SUMMARY_SYSTEM_PROMPT, user, max_tokens=400)


# ---------------------------------------------------------------------------
# The full pipeline: question -> SQL -> data -> answer
# ---------------------------------------------------------------------------
def answer_question(conn, question: str, schema_text: str) -> dict:
    sql, error = None, None
    for _ in range(MAX_ATTEMPTS):
        sql = generate_sql(question, schema_text, previous_error=error, previous_sql=sql)
        try:
            validate_sql(sql)
            df = run_sql(conn, sql)
            return {"sql": sql, "data": df, "answer": summarize(question, df)}
        except Exception as exc:  # validation or Snowflake error -> let the LLM retry once
            error = str(exc)
    return {"sql": sql, "data": None, "answer": None, "error": error}


# ---------------------------------------------------------------------------
# Terminal mode
# ---------------------------------------------------------------------------
def main() -> None:
    conn = get_connection()
    try:
        schema_text = get_schema_text(conn)
        print("AI SQL Assistant ready. Ask a question (or type 'exit').\n")
        while True:
            question = input("You: ").strip()
            if question.lower() in {"exit", "quit", ""}:
                break
            result = answer_question(conn, question, schema_text)
            print(f"\nSQL:\n{result['sql']}\n")
            if result.get("error"):
                print(f"Could not answer: {result['error']}\n")
                continue
            print(result["data"].head(10).to_string(index=False))
            print(f"\nAnswer: {result['answer']}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
