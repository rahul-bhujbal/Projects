"""
Customer order portal on the Snowflake Gold layer.

    browser  ->  FastAPI (this file)  ->  Snowflake  SAP_GOLD.SALES.{SALES_DOC_HDR, SALES_DOC_POS, DEL_DOC_POS}
                                     ->  Oracle SAPSD (only "Place order", optional)

Every screen of the portal is one parameterized, read-only query on the Gold
tables. Placing an order writes a real SAP-style order into Oracle; Debezium,
Kafka and the Snowflake layers bring it back to the portal in about 2-3 minutes.

Run (from the project folder):
    pip install -r portal/requirements.txt
    python -m uvicorn portal.app:app --reload --port 8000
    open http://localhost:8000
Configuration: portal/.env (see portal/.env.example).
"""
import datetime as dt
import os
import pathlib
import random
import sys
import threading
import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _load_env(path):
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env(HERE / ".env")
_load_env(ROOT / ".env")          # SAPSD_PASSWORD for "Place order"

GOLD = os.getenv("GOLD_SCHEMA", "SAP_GOLD.SALES")
HDR, POS, DEL = f"{GOLD}.SALES_DOC_HDR", f"{GOLD}.SALES_DOC_POS", f"{GOLD}.DEL_DOC_POS"
MAX_ROWS = 200


# ---------------------------------------------------------------------------
# Snowflake access (one shared connection, reconnects when it expires)
# ---------------------------------------------------------------------------
class Snowflake:
    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):
        import snowflake.connector
        account = os.environ["SNOWFLAKE_ACCOUNT"]
        account = account.replace("https://", "").replace(".snowflakecomputing.com", "").strip("/")
        args = dict(account=account, user=os.environ["SNOWFLAKE_USER"],
                    role=os.getenv("SNOWFLAKE_ROLE", "SAP_PORTAL_ROLE"),
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "SAP_TRANSFORM_WH"),
                    client_session_keep_alive=True, application="sap_sd_portal")
        key_file = os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE")
        if key_file:
            from cryptography.hazmat.primitives import serialization
            key_path = pathlib.Path(key_file)
            if not key_path.is_absolute():
                key_path = ROOT / key_path
            pwd = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=pwd.encode() if pwd else None)
            args["private_key"] = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption())
        elif os.getenv("SNOWFLAKE_AUTHENTICATOR"):
            args["authenticator"] = os.environ["SNOWFLAKE_AUTHENTICATOR"]     # e.g. externalbrowser
        else:
            args["password"] = os.environ["SNOWFLAKE_PASSWORD"]
        return snowflake.connector.connect(**args)

    def session(self, fresh=False):
        """(host, session token) for Snowflake REST APIs such as Cortex Agents."""
        with self._lock:
            if fresh or self._conn is None or self._conn.is_closed():
                self._conn = self._connect()
            return self._conn.host, self._conn.rest.token

    def query(self, sql, params=None):
        from snowflake.connector import DictCursor
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.is_closed():
                        self._conn = self._connect()
                    with self._conn.cursor(DictCursor) as cur:
                        cur.execute(sql, params or {})
                        return cur.fetchall()
                except Exception as exc:              # expired session -> reconnect once
                    if attempt == 2 or "Authentication token has expired" not in str(exc):
                        raise
                    self._conn = None


sf = Snowflake()


def q(sql, params=None):
    try:
        return sf.query(sql, params)
    except KeyError as exc:
        raise HTTPException(500, f"Snowflake setting missing in portal/.env: {exc}")
    except Exception as exc:
        raise HTTPException(502, f"Snowflake query failed: {exc}")


_cache = {}


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


class Where:
    """Builds a WHERE clause with bound parameters (never string-formats user input)."""

    def __init__(self):
        self.parts, self.params = ["1 = 1"], {}

    def add(self, sql, **params):
        self.parts.append(sql)
        self.params.update(params)
        return self

    def __str__(self):
        return " AND ".join(self.parts)


def customer_filter(w, customer, col="SOLD_TO"):
    if customer:
        w.add(f"{col} = %(customer)s", customer=customer)
    return w


def date_range(w, col, date_from, date_to):
    if date_from:
        w.add(f"{col} >= %(date_from)s", date_from=date_from)
    if date_to:
        w.add(f"{col} <= %(date_to)s", date_to=date_to)
    return w


def like(value):
    return f"%{value.strip()}%"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
app = FastAPI(title="Demo India Customer Portal", version="1.0")

HDR_LIST_COLS = """SALES_DOC, DOC_TYPE_TEXT, DOC_CATEGORY_TEXT, DOC_DATE, REQ_DELIVERY_DATE,
  SOLD_TO, SOLD_TO_NAME, SHIP_TO_NAME, SHIP_TO_CITY, CUSTOMER_PO, CREATED_BY, CURRENCY,
  NET_VALUE, GROSS_VALUE, OPEN_BILLING_VALUE, ITEM_COUNT, OVERALL_STATUS, OVERALL_STATUS_TEXT,
  DELIVERY_STATUS_TEXT, BILLING_STATUS_TEXT, IS_CREDIT_BLOCKED, LAST_GOODS_ISSUE_DATE, LAST_BILLING_DATE"""


@app.get("/api/health")
def health():
    row = q(f"SELECT MAX(LAST_LOADED_AT) AS DATA_AS_OF, CURRENT_ROLE() AS ROLE, "
            f"CURRENT_WAREHOUSE() AS WAREHOUSE FROM {HDR}")[0]
    return {"status": "ok", "oracle_orders_enabled": oracle_enabled(), **row}


@app.get("/api/customers")
def customers():
    return cached("customers", 300, lambda: q(f"""
        SELECT SOLD_TO, ANY_VALUE(SOLD_TO_NAME) AS SOLD_TO_NAME, ANY_VALUE(SOLD_TO_CITY) AS SOLD_TO_CITY,
               ANY_VALUE(DISTR_CHANNEL) AS DISTR_CHANNEL, COUNT(*) AS DOCUMENTS
        FROM {HDR} GROUP BY SOLD_TO ORDER BY SOLD_TO_NAME"""))


@app.get("/api/summary")
def summary(customer: Optional[str] = None):
    w = customer_filter(Where(), customer)
    hdr = q(f"""
        SELECT COUNT_IF(DOC_CATEGORY = 'C' AND OVERALL_STATUS <> 'C')                    AS OPEN_ORDERS,
               SUM(IFF(DOC_CATEGORY = 'C' AND OVERALL_STATUS <> 'C', OPEN_BILLING_VALUE, 0)) AS OPEN_ORDER_VALUE,
               COUNT_IF(DOC_CATEGORY = 'C' AND IS_CREDIT_BLOCKED)                        AS CREDIT_BLOCKED,
               COUNT_IF(DOC_CATEGORY = 'C' AND DOC_DATE >= DATEADD(day, -30, CURRENT_DATE)) AS ORDERS_LAST_30_DAYS,
               SUM(IFF(DOC_CATEGORY = 'C' AND DOC_DATE >= DATEADD(day, -30, CURRENT_DATE), NET_VALUE, 0)) AS VALUE_LAST_30_DAYS,
               MAX(LAST_LOADED_AT)                                                       AS DATA_AS_OF
        FROM {HDR} WHERE {w}""", w.params)[0]
    w2 = customer_filter(Where(), customer)
    dl = q(f"""
        SELECT COUNT(DISTINCT IFF(IS_SHIPPED_NOT_BILLED, DELIVERY_DOC, NULL))          AS SHIPPED_NOT_BILLED,
               SUM(IFF(IS_SHIPPED_NOT_BILLED, DELIVERY_NET_VALUE, 0))                   AS SHIPPED_NOT_BILLED_VALUE,
               COUNT(DISTINCT IFF(NOT IS_GOODS_ISSUED AND NOT IS_RETURN, DELIVERY_DOC, NULL)) AS DELIVERIES_IN_PROCESS
        FROM {DEL} WHERE {w2}""", w2.params)[0]
    return {**hdr, **dl}


@app.get("/api/orders")
def orders(customer: Optional[str] = None,
           view: str = Query("all", pattern="^(quick|recent|open|closed|all)$"),
           status: Optional[str] = Query(None, pattern="^[ABC]$"),
           created_by: Optional[str] = None, q_text: Optional[str] = Query(None, alias="q"),
           date_from: Optional[dt.date] = None, date_to: Optional[dt.date] = None,
           category: str = Query("C", pattern="^(B|C|H|K|ALL)$"), blocked: bool = False):
    w = customer_filter(Where(), customer)
    if blocked:
        w.add("IS_CREDIT_BLOCKED")
    if category != "ALL":
        w.add("DOC_CATEGORY = %(category)s", category=category)
    if view == "quick":                       # open orders placed in the last 30 days
        w.add("OVERALL_STATUS <> 'C' AND DOC_DATE >= DATEADD(day, -30, CURRENT_DATE)")
    elif view == "open":
        w.add("OVERALL_STATUS <> 'C'")
    elif view == "closed":
        w.add("OVERALL_STATUS = 'C'")
    if status:
        w.add("OVERALL_STATUS = %(status)s", status=status)
    if created_by:
        w.add("CREATED_BY ILIKE %(created_by)s", created_by=like(created_by))
    if q_text:
        w.add("(SALES_DOC ILIKE %(q)s OR CUSTOMER_PO ILIKE %(q)s OR SOLD_TO_NAME ILIKE %(q)s)", q=like(q_text))
    date_range(w, "DOC_DATE", date_from, date_to)
    return q(f"SELECT {HDR_LIST_COLS} FROM {HDR} WHERE {w} "
             f"ORDER BY DOC_DATE DESC, SALES_DOC DESC LIMIT {MAX_ROWS}", w.params)


@app.get("/api/search")
def search(type: str = Query(..., pattern="^(order|po|delivery|invoice)$"),
           value: str = Query(..., min_length=1, max_length=40), customer: Optional[str] = None):
    """Order Dashboard search box: find sales documents by order, PO, delivery or invoice number."""
    v = value.strip()
    w = customer_filter(Where(), customer, "h.SOLD_TO")
    if type == "order":
        w.add("(h.SALES_DOC = LPAD(%(v)s, 10, '0') OR h.SALES_DOC ILIKE %(vl)s)", v=v, vl=like(v))
    elif type == "po":
        w.add("h.CUSTOMER_PO ILIKE %(vl)s", vl=like(v))
    elif type == "delivery":
        w.add(f"h.SALES_DOC IN (SELECT SALES_DOC FROM {DEL} WHERE DELIVERY_DOC = LPAD(%(v)s, 10, '0') "
              f"OR DELIVERY_DOC ILIKE %(vl)s)", v=v, vl=like(v))
    else:
        w.add(f"h.SALES_DOC IN (SELECT SALES_DOC FROM {POS} WHERE LAST_INVOICE_DOC = LPAD(%(v)s, 10, '0') "
              f"OR LAST_INVOICE_DOC ILIKE %(vl)s "
              f"UNION SELECT SALES_DOC FROM {DEL} WHERE INVOICE_DOC = LPAD(%(v)s, 10, '0'))", v=v, vl=like(v))
    cols = ", ".join("h." + c.strip() for c in HDR_LIST_COLS.split(","))
    return q(f"SELECT {cols} FROM {HDR} h WHERE {w} ORDER BY h.DOC_DATE DESC LIMIT {MAX_ROWS}", w.params)


@app.get("/api/orders/{sales_doc}")
def order_detail(sales_doc: str):
    p = {"doc": sales_doc.strip().zfill(10)}
    hdr = q(f"SELECT * FROM {HDR} WHERE SALES_DOC = %(doc)s", p)
    if not hdr:
        raise HTTPException(404, f"Sales document {p['doc']} not found")
    items = q(f"""
        SELECT ITEM, MATERIAL, MATERIAL_TEXT, MATERIAL_GROUP, PLANT, ORDER_QTY, SALES_UNIT, CONFIRMED_QTY,
               DELIVERED_QTY, OPEN_DELIVERY_QTY, BILLED_QTY, LIST_PRICE, NET_PRICE, DISCOUNT_VALUE, NET_VALUE,
               TAX_VALUE, GROSS_VALUE, FIRST_CONFIRMED_DATE, LAST_CONFIRMED_DATE, IS_REJECTED, REJECTION_REASON,
               DELIVERY_STATUS_TEXT, BILLING_STATUS_TEXT, LAST_DELIVERY_DOC, LAST_INVOICE_DOC, HAS_BACKORDER
        FROM {POS} WHERE SALES_DOC = %(doc)s ORDER BY ITEM""", p)
    deliveries = q(f"""
        SELECT DELIVERY_DOC, ITEM, SALES_ITEM, MATERIAL, MATERIAL_TEXT, DELIVERY_QTY, SALES_UNIT,
               PLANNED_GOODS_ISSUE_DATE, ACTUAL_GOODS_ISSUE_DATE, GOODS_MOVEMENT_STATUS_TEXT,
               BILLING_STATUS_TEXT, INVOICE_DOC, IS_RETURN
        FROM {DEL} WHERE SALES_DOC = %(doc)s ORDER BY DELIVERY_DOC, ITEM""", p)
    return {"header": hdr[0], "items": items, "deliveries": deliveries}


@app.get("/api/deliveries")
def deliveries(customer: Optional[str] = None, q_text: Optional[str] = Query(None, alias="q"),
               status: str = Query("all", pattern="^(all|in_process|shipped|not_billed)$"),
               date_from: Optional[dt.date] = None, date_to: Optional[dt.date] = None):
    w = customer_filter(Where(), customer)
    if q_text:
        w.add("(DELIVERY_DOC ILIKE %(q)s OR SALES_DOC ILIKE %(q)s OR CUSTOMER_PO ILIKE %(q)s)", q=like(q_text))
    date_range(w, "DELIVERY_CREATED_ON", date_from, date_to)
    having = {"all": "", "in_process": "HAVING NOT BOOLAND_AGG(IS_GOODS_ISSUED)",
              "shipped": "HAVING BOOLAND_AGG(IS_GOODS_ISSUED)",
              "not_billed": "HAVING BOOLOR_AGG(IS_SHIPPED_NOT_BILLED)"}[status]
    return q(f"""
        SELECT DELIVERY_DOC, ANY_VALUE(DELIVERY_TYPE_TEXT) AS DELIVERY_TYPE_TEXT, BOOLOR_AGG(IS_RETURN) AS IS_RETURN,
               MAX(SALES_DOC) AS SALES_DOC, MAX(CUSTOMER_PO) AS CUSTOMER_PO,
               ANY_VALUE(SOLD_TO_NAME) AS SOLD_TO_NAME, ANY_VALUE(SHIP_TO_NAME) AS SHIP_TO_NAME,
               ANY_VALUE(SHIP_TO_CITY) AS SHIP_TO_CITY, ANY_VALUE(PLANT) AS PLANT,
               MAX(DELIVERY_CREATED_ON) AS CREATED_ON, MAX(PLANNED_GOODS_ISSUE_DATE) AS PLANNED_GOODS_ISSUE_DATE,
               MAX(ACTUAL_GOODS_ISSUE_DATE) AS ACTUAL_GOODS_ISSUE_DATE, COUNT(*) AS ITEMS,
               SUM(DELIVERY_QTY) AS TOTAL_QTY, SUM(GROSS_WEIGHT) AS GROSS_WEIGHT, ANY_VALUE(WEIGHT_UNIT) AS WEIGHT_UNIT,
               SUM(DELIVERY_NET_VALUE) AS NET_VALUE, MAX(INVOICE_DOC) AS INVOICE_DOC,
               ANY_VALUE(GOODS_MOVEMENT_STATUS_TEXT) AS GOODS_MOVEMENT_STATUS_TEXT,
               ANY_VALUE(BILLING_STATUS_TEXT) AS BILLING_STATUS_TEXT,
               BOOLAND_AGG(IS_GOODS_ISSUED) AS IS_GOODS_ISSUED, BOOLOR_AGG(IS_SHIPPED_NOT_BILLED) AS IS_SHIPPED_NOT_BILLED
        FROM {DEL} WHERE {w}
        GROUP BY DELIVERY_DOC {having}
        ORDER BY CREATED_ON DESC, DELIVERY_DOC DESC LIMIT {MAX_ROWS}""", w.params)


@app.get("/api/deliveries/{delivery_doc}")
def delivery_detail(delivery_doc: str):
    rows = q(f"""
        SELECT DELIVERY_DOC, ITEM, DELIVERY_TYPE_TEXT, IS_RETURN, SALES_DOC, SALES_ITEM, CUSTOMER_PO,
               SOLD_TO_NAME, SHIP_TO_NAME, SHIP_TO_CITY, SHIP_TO_POSTAL_CODE, PLANT, SHIPPING_POINT, ROUTE,
               MATERIAL, MATERIAL_TEXT, DELIVERY_QTY, SALES_UNIT, NET_WEIGHT, GROSS_WEIGHT, WEIGHT_UNIT,
               DELIVERY_NET_VALUE, PLANNED_DELIVERY_DATE, PLANNED_GOODS_ISSUE_DATE, ACTUAL_GOODS_ISSUE_DATE,
               PICKING_STATUS_TEXT, GOODS_MOVEMENT_STATUS_TEXT, BILLING_STATUS_TEXT, MATERIAL_DOC, INVOICE_DOC,
               INCOTERMS, INCOTERMS_LOCATION, PACKAGES_IN_DELIVERY
        FROM {DEL} WHERE DELIVERY_DOC = %(doc)s ORDER BY ITEM""", {"doc": delivery_doc.strip().zfill(10)})
    if not rows:
        raise HTTPException(404, f"Delivery {delivery_doc} not found")
    return {"header": rows[0], "items": rows}


@app.get("/api/documents")
def documents(customer: Optional[str] = None, q_text: Optional[str] = Query(None, alias="q"),
              doc_type: str = Query("all", pattern="^(all|order|delivery|invoice|return|quotation)$"),
              date_from: Optional[dt.date] = None, date_to: Optional[dt.date] = None):
    """All documents of an account: sales orders, quotations, returns, deliveries, invoices."""
    p = {}
    cust = ""
    if customer:
        cust, p["customer"] = "AND SOLD_TO = %(customer)s", customer
    sql = f"""
      SELECT * FROM (
        SELECT DOC_CATEGORY_TEXT AS DOC_TYPE, SALES_DOC AS DOCUMENT, DOC_DATE AS DOC_DATE, SALES_DOC AS SALES_DOC,
               CUSTOMER_PO, NET_VALUE AS AMOUNT, OVERALL_STATUS_TEXT AS STATUS
        FROM {HDR} WHERE 1 = 1 {cust}
        UNION ALL
        SELECT IFF(BOOLOR_AGG(IS_RETURN), 'Returns delivery', 'Delivery'), DELIVERY_DOC, MAX(DELIVERY_CREATED_ON),
               MAX(SALES_DOC), MAX(CUSTOMER_PO), SUM(DELIVERY_NET_VALUE), ANY_VALUE(GOODS_MOVEMENT_STATUS_TEXT)
        FROM {DEL} WHERE 1 = 1 {cust} GROUP BY DELIVERY_DOC
        UNION ALL
        SELECT 'Invoice', LAST_INVOICE_DOC, MAX(LAST_BILLING_DATE), MAX(SALES_DOC), NULL,
               SUM(NET_BILLED_VALUE), ANY_VALUE(BILLING_STATUS_TEXT)
        FROM {POS} WHERE LAST_INVOICE_DOC IS NOT NULL {cust} GROUP BY LAST_INVOICE_DOC
      ) d WHERE 1 = 1"""
    if doc_type != "all":
        p["dt"] = {"order": "Order", "delivery": "Delivery", "invoice": "Invoice",
                   "return": "Return", "quotation": "Quotation"}[doc_type]
        sql += " AND STARTSWITH(DOC_TYPE, %(dt)s)"
    if q_text:
        sql += " AND (DOCUMENT ILIKE %(q)s OR SALES_DOC ILIKE %(q)s OR CUSTOMER_PO ILIKE %(q)s)"
        p["q"] = like(q_text)
    if date_from:
        sql += " AND DOC_DATE >= %(date_from)s"
        p["date_from"] = date_from
    if date_to:
        sql += " AND DOC_DATE <= %(date_to)s"
        p["date_to"] = date_to
    return q(sql + f" ORDER BY DOC_DATE DESC, DOCUMENT DESC LIMIT {MAX_ROWS}", p)


@app.get("/api/returns")
def returns(customer: Optional[str] = None):
    return orders(customer=customer, view="all", status=None, created_by=None, q_text=None,
                  date_from=None, date_to=None, category="H", blocked=False)


@app.get("/api/categories")
def categories():
    return cached("categories", 600, lambda: q(f"""
        SELECT MATERIAL_GROUP, COUNT(DISTINCT MATERIAL) AS PRODUCTS
        FROM {POS} WHERE MATERIAL_GROUP IS NOT NULL GROUP BY MATERIAL_GROUP ORDER BY MATERIAL_GROUP"""))


@app.get("/api/products")
def products(q_text: Optional[str] = Query(None, alias="q"), category: Optional[str] = None):
    w = Where()
    if q_text:
        w.add("(MATERIAL ILIKE %(q)s OR MATERIAL_TEXT ILIKE %(q)s OR MATERIAL_GROUP ILIKE %(q)s)", q=like(q_text))
    if category:
        w.add("MATERIAL_GROUP = %(category)s", category=category)
    return q(f"""
        SELECT MATERIAL, ANY_VALUE(MATERIAL_TEXT) AS MATERIAL_TEXT, ANY_VALUE(MATERIAL_GROUP) AS MATERIAL_GROUP,
               ANY_VALUE(MATERIAL_TYPE) AS MATERIAL_TYPE, ANY_VALUE(SALES_UNIT) AS SALES_UNIT,
               MAX_BY(LIST_PRICE, DOC_DATE) AS LIST_PRICE, ANY_VALUE(CURRENCY) AS CURRENCY,
               COUNT(DISTINCT SALES_DOC) AS TIMES_ORDERED, SUM(EFFECTIVE_NET_VALUE) AS TOTAL_SOLD_VALUE
        FROM {POS} WHERE {w} AND DOC_CATEGORY = 'C'
        GROUP BY MATERIAL ORDER BY TIMES_ORDERED DESC, MATERIAL LIMIT {MAX_ROWS}""", w.params)


class CartLine(BaseModel):
    material: str = Field(..., min_length=1, max_length=40)
    qty: float = Field(..., gt=0, le=100000)
    requested_date: Optional[dt.date] = None


class AvailabilityRequest(BaseModel):
    lines: List[CartLine] = Field(..., min_length=1, max_length=50)


@app.post("/api/availability")
def availability(req: AvailabilityRequest):
    """Price and an estimated ship date per line. The model has no stock table, so the
    estimate comes from history: average days from order to goods issue for the material."""
    mats = sorted({l.material.strip().upper() for l in req.lines})
    p = {f"m{i}": m for i, m in enumerate(mats)}
    in_list = ", ".join(f"%(m{i})s" for i in range(len(mats)))
    rows = q(f"""
        WITH prod AS (
          SELECT MATERIAL, ANY_VALUE(MATERIAL_TEXT) AS MATERIAL_TEXT, ANY_VALUE(MATERIAL_TYPE) AS MATERIAL_TYPE,
                 ANY_VALUE(SALES_UNIT) AS SALES_UNIT, MAX_BY(LIST_PRICE, DOC_DATE) AS LIST_PRICE,
                 SUM(IFF(DOC_CATEGORY = 'C', OPEN_DELIVERY_QTY, 0)) AS OPEN_BACKLOG_QTY
          FROM {POS} WHERE UPPER(MATERIAL) IN ({in_list}) GROUP BY MATERIAL),
        lead AS (
          SELECT MATERIAL, ROUND(AVG(DAYS_ORDER_TO_GOODS_ISSUE)) AS AVG_LEAD_DAYS, COUNT(*) AS SHIPMENTS
          FROM {DEL} WHERE UPPER(MATERIAL) IN ({in_list}) AND IS_GOODS_ISSUED AND NOT IS_RETURN GROUP BY MATERIAL),
        all_lead AS (
          SELECT ROUND(AVG(DAYS_ORDER_TO_GOODS_ISSUE)) AS AVG_LEAD_DAYS
          FROM {DEL} WHERE IS_GOODS_ISSUED AND NOT IS_RETURN)
        SELECT p.*, COALESCE(l.AVG_LEAD_DAYS, a.AVG_LEAD_DAYS, 5) AS LEAD_DAYS,
               (l.MATERIAL IS NOT NULL) AS LEAD_FROM_MATERIAL_HISTORY
        FROM prod p LEFT JOIN lead l ON l.MATERIAL = p.MATERIAL CROSS JOIN all_lead a""", p)
    by_mat = {r["MATERIAL"].upper(): r for r in rows}
    today = dt.date.today()
    out = []
    for line in req.lines:
        r = by_mat.get(line.material.strip().upper())
        if not r:
            out.append({"material": line.material, "qty": line.qty, "found": False,
                        "message": "Part number not found in the sales catalogue"})
            continue
        price = float(r["LIST_PRICE"] or 0)
        est = today + dt.timedelta(days=int(r["LEAD_DAYS"]))
        orderable = r["MATERIAL_TYPE"] != "DIEN"
        out.append({
            "material": r["MATERIAL"], "description": r["MATERIAL_TEXT"], "qty": line.qty,
            "unit": r["SALES_UNIT"], "found": True, "orderable": orderable,
            "list_price": price, "line_value": round(price * line.qty, 2),
            "requested_date": line.requested_date, "estimated_ship_date": est,
            "meets_requested_date": None if not line.requested_date else est <= line.requested_date,
            "lead_days": int(r["LEAD_DAYS"]), "lead_basis": "material history" if r["LEAD_FROM_MATERIAL_HISTORY"]
            else "average of all shipments", "open_backlog_qty": float(r["OPEN_BACKLOG_QTY"] or 0),
            "message": None if orderable else "Service item - order through your sales contact"})
    return {"lines": out, "note": "Ship dates are estimates from shipping history; stock levels are not modelled."}


# ---------------------------------------------------------------------------
# AI assistant -> Snowflake Cortex Agent (snowflake/05_sales_agent.sql)
# ---------------------------------------------------------------------------
AGENT = os.getenv("CORTEX_AGENT", "SAP_GOLD.SALES.SAP_SALES_AGENT")


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    text: str = Field(..., max_length=4000)


class AgentRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    customer: Optional[str] = Field(None, max_length=10)
    page: Optional[str] = Field(None, max_length=200)
    history: List[ChatTurn] = Field(default_factory=list, max_length=12)


def _walk(node):
    """Yield every dict inside a nested JSON structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def parse_agent_response(resp):
    """Pull answer text, result tables and generated SQL out of a Cortex Agent response."""
    text_parts, tables, sqls, seen_q = [], [], [], set()
    for item in resp.get("content", []):
        if item.get("type") == "text" and item.get("text"):
            text_parts.append(item["text"])
    for d in _walk(resp.get("content", [])):
        sql = d.get("sql")
        if isinstance(sql, str) and sql.strip() and sql not in sqls:
            sqls.append(sql)
        rs = d.get("result_set")
        if isinstance(rs, dict):
            qid = rs.get("statementHandle") or d.get("query_id") or id(rs)
            if qid in seen_q:
                continue
            seen_q.add(qid)
            cols = [c.get("name") for c in (rs.get("resultSetMetaData") or {}).get("rowType", [])]
            rows = rs.get("data") or []
            if cols:
                tables.append({"title": d.get("title") or "", "columns": cols, "rows": rows[:200],
                               "row_count": len(rows)})
    warnings = [w.get("message") for w in resp.get("warnings", []) if isinstance(w, dict)]
    return {"answer": "\n\n".join(text_parts).strip(), "tables": tables, "sql": sqls, "warnings": warnings}


@app.post("/api/agent")
def ask_agent(req: AgentRequest):
    import json
    import urllib.error
    import urllib.request

    db, schema, name = AGENT.split(".")
    question = req.question.strip()
    if req.customer:
        cust = next((c for c in customers() if c["SOLD_TO"] == req.customer), None)
        label = f"{cust['SOLD_TO_NAME']} (sold-to {req.customer})" if cust else f"sold-to {req.customer}"
        question = (f"[Context: I am looking at customer {label}. Unless I ask about all customers, "
                    f"answer only for this customer.]\n{question}")
    messages = [{"role": t.role, "content": [{"type": "text", "text": t.text}]} for t in req.history[-10:]]
    messages.append({"role": "user", "content": [{"type": "text", "text": question}]})
    body = json.dumps({"messages": messages, "stream": False}).encode()

    for attempt in (1, 2):
        try:
            host, token = sf.session(fresh=(attempt == 2))
        except KeyError as exc:
            raise HTTPException(500, f"Snowflake setting missing in portal/.env: {exc}")
        except Exception as exc:
            raise HTTPException(502, f"Snowflake login failed: {exc}")
        http = urllib.request.Request(
            f"https://{host}/api/v2/databases/{db}/schemas/{schema}/agents/{name}:run",
            data=body, method="POST",
            headers={"Authorization": f'Snowflake Token="{token}"', "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "sap-sd-portal/1.0"})
        try:
            with urllib.request.urlopen(http, timeout=180) as r:
                return parse_agent_response(json.loads(r.read().decode()))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            if exc.code == 401 and attempt == 1:
                continue                                   # session token expired: log in again
            hint = {401: "not authorised", 403: "the role lacks USAGE on the agent or CORTEX_AGENT_USER",
                    404: f"agent {AGENT} not found or not visible to this role"}.get(exc.code, "")
            raise HTTPException(502, f"Cortex Agent error {exc.code}{' (' + hint + ')' if hint else ''}: {detail}")
        except urllib.error.URLError as exc:
            raise HTTPException(502, f"Cannot reach Snowflake: {exc.reason}")


# ---------------------------------------------------------------------------
# Place order -> Oracle (optional; the order returns via CDC)
# ---------------------------------------------------------------------------
def oracle_enabled():
    return os.getenv("ORACLE_ORDERS_ENABLED", "true").lower() == "true" and bool(os.getenv("SAPSD_PASSWORD"))


class OrderRequest(BaseModel):
    customer: str = Field(..., min_length=10, max_length=10)
    customer_po: str = Field(..., min_length=1, max_length=35)
    lines: List[CartLine] = Field(..., min_length=1, max_length=50)


@app.post("/api/orders")
def place_order(req: OrderRequest):
    if not oracle_enabled():
        raise HTTPException(503, "Order entry is disabled: set SAPSD_PASSWORD (and ORACLE_*) in .env")
    try:
        import oracledb
        import daily_orders as do
    except ImportError as exc:
        raise HTTPException(500, f"Missing dependency: {exc}")

    dsn = os.getenv("ORACLE_DSN", f"{os.getenv('ORACLE_HOST', 'localhost')}:{os.getenv('ORACLE_PORT', '1522')}/"
                                  f"{os.getenv('ORACLE_SERVICE', 'FREEPDB1')}")
    try:
        conn = oracledb.connect(user=os.getenv("ORACLE_USER", "SAPSD"), password=os.environ["SAPSD_PASSWORD"], dsn=dsn)
    except Exception as exc:
        raise HTTPException(502, f"Cannot connect to Oracle at {dsn}: {exc}")
    try:
        with conn.cursor() as cur:
            customers_, ship_tos, materials_ = do.load_master_data(cur)
        cust = next((c for c in customers_ if c["kunnr"] == req.customer), None)
        if not cust:
            raise HTTPException(400, f"Customer {req.customer} cannot place orders (blocked or not a sold-to party)")
        mat_by = {m["matnr"].upper(): m for m in materials_}
        lines, bad = [], []
        for l in req.lines:
            m = mat_by.get(l.material.strip().upper())
            (lines.append((m, int(l.qty) if float(l.qty).is_integer() else l.qty)) if m else bad.append(l.material))
        if bad:
            raise HTTPException(400, f"Not orderable online: {', '.join(bad)}")
        dates = [l.requested_date for l in req.lines if l.requested_date]
        vdatu = min(dates) if dates else None

        for attempt in range(3):          # another order may take the same number at the same time
            with conn.cursor() as cur:
                next_vbeln, next_knumv = do.next_numbers(cur)
            vbeln, knumv = f"{next_vbeln:010d}", f"{next_knumv:010d}"
            order = do.build_order(vbeln, knumv, len(lines), dt.date.today(), dt.datetime.now(),
                                   customers_, ship_tos, materials_, random.Random(),
                                   cust=cust, lines=lines, vdatu=vdatu, bstnk=req.customer_po, clerk="WEB_PORTAL")
            try:
                do.insert_order(conn, order)
                break
            except oracledb.IntegrityError:
                conn.rollback()
                if attempt == 2:
                    raise HTTPException(409, "Could not allocate an order number, please retry")
        h = order["vbak"][0]
        tax = sum(float(i["mwsbp"]) for i in order["vbap"])
        return {"sales_doc": vbeln, "customer_po": h["bstnk"], "items": len(order["vbap"]),
                "net_value": float(h["netwr"]), "tax_value": round(tax, 2),
                "requested_delivery_date": h["vdatu"],
                "message": "Order saved in SAP (Oracle). It reaches this portal through CDC in about 2-3 minutes."}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Front-end
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    # no-cache so the browser always picks up a new version of the page after an update
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})
