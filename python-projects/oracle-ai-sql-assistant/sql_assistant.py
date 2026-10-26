"""
Oracle AI SQL Assistant - core logic.

Flow:  question -> read table schema -> LLM writes Oracle SQL -> safety check
       -> run on Oracle (retry once with the error if it fails)
       -> LLM explains the result in plain English.

Run from the terminal:  python sql_assistant.py
"""

import os
import re
from pathlib import Path

import anthropic
import oracledb
import pandas as pd
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
# Schema whose tables the assistant may query (defaults to the login user)
SCHEMA = (os.getenv("ORACLE_SCHEMA") or os.getenv("ORACLE_USER", "")).strip().upper()
# Optional comma-separated list of tables; empty = every table in the schema (max 40)
TABLES = [t.strip().upper() for t in os.getenv("ORACLE_TABLES", "").split(",") if t.strip()]
MAX_TABLES = 40
MAX_ROWS = 200        # never pull more than this into the app
MAX_ATTEMPTS = 2      # first try + one self-correction

_llm = None


def get_llm():
    """Create the LLM client on first use (so setup_sample_data.py needs no API key)."""
    global _llm
    if _llm is None:
        _llm = anthropic.Anthropic(api_key=_require("ANTHROPIC_API_KEY"))
    return _llm


# ---------------------------------------------------------------------------
# STEP 2 - Connect to Oracle (thin mode: no Oracle Client install needed)
# ---------------------------------------------------------------------------
DB_VERSION = ""          # filled in after connecting, e.g. "11.2.0.2.0"
_thick_ready = False


def _init_thick_mode() -> None:
    """Switch to thick mode (needed for Oracle 11.2 and older) when configured."""
    global _thick_ready
    lib_dir = os.getenv("ORACLE_CLIENT_LIB_DIR", "").strip()
    thick = os.getenv("ORACLE_THICK_MODE", "").strip().lower() in {"1", "true", "yes"}
    if _thick_ready or not (lib_dir or thick):
        return
    try:
        oracledb.init_oracle_client(lib_dir=lib_dir or None)
    except oracledb.Error as exc:
        raise SystemExit(
            f"Could not load the Oracle Client libraries: {exc}\n"
            "Set ORACLE_CLIENT_LIB_DIR in .env to the folder that contains oci.dll "
            "(64-bit Oracle Instant Client, matching 64-bit Python)."
        )
    _thick_ready = True


def get_connection():
    """Open an Oracle connection. DSN format: host:port/service_name."""
    global DB_VERSION
    _init_thick_mode()
    params = dict(
        user=_require("ORACLE_USER"),
        password=_require("ORACLE_PASSWORD"),
        dsn=_require("ORACLE_DSN"),
    )
    # Optional wallet for Oracle Autonomous Database (mTLS)
    wallet_dir = os.getenv("ORACLE_WALLET_DIR", "").strip()
    if wallet_dir:
        params.update(config_dir=wallet_dir, wallet_location=wallet_dir,
                      wallet_password=os.getenv("ORACLE_WALLET_PASSWORD") or None)
    try:
        conn = oracledb.connect(**params)
    except oracledb.Error as exc:
        if "DPY-3010" in str(exc):
            raise SystemExit(
                "This Oracle database is older than 12.1, so it needs thick mode "
                f"(currently thick mode is {'ON' if _thick_ready else 'OFF'}).\n"
                "1. Install 64-bit Oracle Instant Client 19 (Basic package) and unzip it, "
                "e.g. to C:\\oracle\\instantclient_19_x\n"
                "2. Add to .env:  ORACLE_CLIENT_LIB_DIR=C:\\oracle\\instantclient_19_x\n"
                "3. Run the app again."
            )
        if _thick_ready and oracledb.clientversion()[0] >= 21:
            raise SystemExit(
                f"Connection failed: {exc}\n"
                f"Your Oracle Instant Client is version {oracledb.clientversion()[0]}, which "
                "cannot connect to Oracle 11.2 or older. Use Instant Client 19 instead and "
                "point ORACLE_CLIENT_LIB_DIR at it."
            )
        raise
    DB_VERSION = conn.version or ""
    return conn


def _db_major() -> int:
    try:
        return int(DB_VERSION.split(".")[0])
    except ValueError:
        return 12


# ---------------------------------------------------------------------------
# STEP 3 - Read the table structure so the LLM knows what exists
# ---------------------------------------------------------------------------
def get_schema_text(conn) -> str:
    """Return tables and columns as compact text, e.g. ORDERS(ORDER_ID NUMBER, ...)."""
    binds = {"owner": SCHEMA}
    table_filter = ""
    if TABLES:
        names = [f":t{i}" for i in range(len(TABLES))]
        table_filter = f"AND c.table_name IN ({', '.join(names)})"
        binds.update({f"t{i}": t for i, t in enumerate(TABLES)})

    sql = f"""
        SELECT c.table_name, c.column_name, c.data_type, cc.comments
        FROM all_tab_columns c
        JOIN all_tables t
          ON t.owner = c.owner AND t.table_name = c.table_name
        LEFT JOIN all_col_comments cc
          ON cc.owner = c.owner AND cc.table_name = c.table_name
         AND cc.column_name = c.column_name
        WHERE c.owner = :owner {table_filter}
        ORDER BY c.table_name, c.column_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, binds)
        rows = cur.fetchall()

    tables: dict[str, list[str]] = {}
    for table, column, dtype, comment in rows:
        if table not in tables and len(tables) >= MAX_TABLES:
            continue
        col = f"{column} {dtype}"
        if comment:
            col += f" -- {comment}"
        tables.setdefault(table, []).append(col)

    if not tables:
        raise SystemExit(f"No tables found in schema {SCHEMA}. "
                         "Run `python setup_sample_data.py` or set ORACLE_SCHEMA.")
    return "\n".join(f"{t}({', '.join(cols)})" for t, cols in tables.items())


# ---------------------------------------------------------------------------
# STEP 4 - Ask the LLM to write Oracle SQL
# ---------------------------------------------------------------------------
SQL_SYSTEM_PROMPT = """You are an expert Oracle SQL analyst.
Write ONE read-only Oracle SQL query (SELECT or WITH ... SELECT) that answers the user's question.
Rules:
- Use only the tables and columns listed in the schema.
- Qualify tables with the schema name: {schema}.<TABLE>.
- The database is Oracle version {version}. {limit_rule}
- Use Oracle date syntax: EXTRACT(YEAR FROM d) or TO_CHAR(d, 'YYYY-MM'),
  DATE 'YYYY-MM-DD' literals, NVL for null handling.
- Use clear column aliases without quotes (e.g. total_sales).
- Do not end the query with a semicolon. Never modify data.
Return only the SQL inside a ```sql code block, with no explanation."""


def _ask_llm(system: str, user: str, max_tokens: int = 1024) -> str:
    response = get_llm().messages.create(
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
    if _db_major() >= 12:
        limit_rule = "For top-N use ORDER BY ... FETCH FIRST n ROWS ONLY (never LIMIT)."
    else:
        limit_rule = ("For top-N wrap the ordered query and filter WHERE ROWNUM <= n. "
                      "Do NOT use FETCH FIRST, LIMIT, LATERAL or identity columns.")
    system = SQL_SYSTEM_PROMPT.format(schema=SCHEMA, version=DB_VERSION or "12c or later",
                                      limit_rule=limit_rule)
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
    r"RENAME|COMMIT|ROLLBACK|LOCK|EXECUTE|EXEC|CALL|BEGIN|DECLARE|PURGE|FLASHBACK)\b"
    r"|\bFOR\s+UPDATE\b|\bDBMS_\w+|\bUTL_\w+",
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
# STEP 6 - Run the SQL on Oracle (with a row limit)
# ---------------------------------------------------------------------------
def run_sql(conn, sql: str) -> pd.DataFrame:
    limited = f"SELECT * FROM (\n{sql}\n) WHERE ROWNUM <= {MAX_ROWS}"
    with conn.cursor() as cur:
        cur.execute(limited)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=columns)
    # Oracle NUMBER columns arrive as Python numbers; make them numeric for charts
    for col in df.columns:
        if df[col].dtype == object:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().all() and len(df):
                df[col] = converted
    return df


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
        except (ValueError, oracledb.Error) as exc:  # let the LLM retry once
            error = str(exc)
    return {"sql": sql, "data": None, "answer": None, "error": error}


# ---------------------------------------------------------------------------
# Terminal mode
# ---------------------------------------------------------------------------
def main() -> None:
    conn = get_connection()
    try:
        schema_text = get_schema_text(conn)
        print(f"Oracle AI SQL Assistant ready (schema {SCHEMA}). "
              "Ask a question (or type 'exit').\n")
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
