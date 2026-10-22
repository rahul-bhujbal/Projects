"""
Insert a day's worth of new SAP sales orders into Oracle (schema SAPSD).

Default: 10 orders with 50 line items in total (randomly split, every order
has at least one item). Each order is written in ONE transaction, the way SAP
saves a sales document, so Debezium/Kafka/Snowflake never see half an order:

    VBAK  header            VBKD  business data       VBPA  partners (AG/WE/RE/RG)
    VBAP  items             VBEP  schedule lines      PRCD_ELEMENTS  pricing

Pricing follows the sample data: list price (PR00), 5 % distributor discount
(K004) on channel 20, GST as CGST+SGST (JOCG/JOSG) within Maharashtra, IGST
(JOIG) otherwise. Customers, ship-tos, materials and prices are read from the
database, so new master data is picked up automatically.

Usage (from the project folder):
    pip install oracledb
    python scripts/daily_orders.py                      # today: 10 orders, 50 items
    python scripts/daily_orders.py --orders 20 --items 120
    python scripts/daily_orders.py --date 2026-10-15    # orders dated a given day
    python scripts/daily_orders.py --backfill-days 7    # one batch per day, last 7 days
    python scripts/daily_orders.py --dry-run            # build and print, insert nothing

Connection: localhost:1522/FREEPDB1 as SAPSD, password SAPSD_PASSWORD from .env.
Override with --host/--port/--service/--user/--password or ORACLE_DSN.
"""
import argparse
import datetime as dt
import os
import pathlib
import random
import sys
from decimal import Decimal, ROUND_HALF_UP

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = "100"
VKORG, SPART, PLANT, COMPANY = "1000", "00", "1000", "IN01"
PLANT_REGION = "13"                 # Maharashtra: intra-state GST
ORDER_RANGE = (100000, 999999)      # VBELN 0000100000-0000999999 for generated orders
CLERKS = ["SD_CLERK01", "SD_CLERK02", "SD_CLERK03", "WEB_ORDER"]
FALLBACK_PRICES = {                 # used only if a material has never been priced
    "MCB-C16-1P": 240, "MCB-C32-3P": 980, "RCCB-40A-4P": 3450, "MCCB-250A-3P": 21500,
    "ACB-1600A-4P": 285000, "CONT-25A-AC3": 1850, "OLR-9-13A": 1450, "VFD-7.5KW": 48500,
    "UPS-10KVA-ONL": 162000, "PNL-LT-800A": 645000, "CBL-4C-16SQ": 420,
}
TWO = Decimal("0.01")


def money(x):
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def read_env(path):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def parse_args():
    env = read_env(ROOT / ".env")
    p = argparse.ArgumentParser(description="Insert daily SAP sales orders into Oracle.")
    p.add_argument("--orders", type=int, default=10, help="orders per day (default 10)")
    p.add_argument("--items", type=int, default=50, help="line items per day in total (default 50)")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="order date YYYY-MM-DD (default today)")
    p.add_argument("--backfill-days", type=int, default=0, help="generate one batch per day for the last N days")
    p.add_argument("--seed", type=int, default=None, help="random seed for repeatable data")
    p.add_argument("--dry-run", action="store_true", help="build orders and print a summary, insert nothing")
    p.add_argument("--host", default=os.getenv("ORACLE_HOST", "localhost"))
    p.add_argument("--port", type=int, default=int(os.getenv("ORACLE_PORT", "1522")))
    p.add_argument("--service", default=os.getenv("ORACLE_SERVICE", "FREEPDB1"))
    p.add_argument("--user", default=os.getenv("ORACLE_USER", "SAPSD"))
    p.add_argument("--password", default=os.getenv("SAPSD_PASSWORD", env.get("SAPSD_PASSWORD", "sapsd")))
    a = p.parse_args()
    if a.orders < 1 or a.items < a.orders:
        p.error("--items must be >= --orders, and --orders >= 1")
    return a


# ---------------------------------------------------------------------------
# Master data and number ranges
# ---------------------------------------------------------------------------
def load_master_data(cur):
    cur.execute("""
        SELECT k.kunnr, k.regio, k.ort01, v.vtweg, v.vkbur, v.vkgrp, v.bzirk,
               v.zterm, v.kdgrp, v.konda, v.pltyp, v.ktgrd, v.inco1, k.adrnr
        FROM kna1 k
        JOIN knvv v ON v.mandt = k.mandt AND v.kunnr = k.kunnr
        WHERE k.mandt = :c AND k.ktokd = '0001' AND v.vkorg = :o
          AND k.loevm IS NULL AND k.aufsd IS NULL""", c=CLIENT, o=VKORG)
    cols = [d[0].lower() for d in cur.description]
    customers = [dict(zip(cols, r)) for r in cur.fetchall()]

    cur.execute("""
        SELECT p.kunnr, p.kunn2, k.ort01, k.adrnr FROM knvp p
        JOIN kna1 k ON k.mandt = p.mandt AND k.kunnr = p.kunn2
        WHERE p.mandt = :c AND p.parvw = 'WE' AND p.kunn2 <> p.kunnr""", c=CLIENT)
    ship_tos = {}
    for kunnr, kunn2, city, adrnr in cur.fetchall():
        ship_tos.setdefault(kunnr, []).append({"kunnr": kunn2, "ort01": city, "adrnr": adrnr})

    cur.execute("""
        SELECT m.matnr, t.maktx, m.matkl, m.meins, m.prdha, m.ntgew
        FROM mara m
        JOIN makt t ON t.mandt = m.mandt AND t.matnr = m.matnr AND t.spras = 'E'
        JOIN marc c ON c.mandt = m.mandt AND c.matnr = m.matnr AND c.werks = :w
        WHERE m.mandt = :c AND m.mtart <> 'DIEN' AND m.lvorm IS NULL""", c=CLIENT, w=PLANT)
    cols = [d[0].lower() for d in cur.description]
    materials = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Latest list price (PR00) actually used for each material.
    cur.execute("""
        SELECT matnr, kbetr FROM (
          SELECT i.matnr, p.kbetr,
                 ROW_NUMBER() OVER (PARTITION BY i.matnr ORDER BY h.erdat DESC, h.vbeln DESC) rn
          FROM vbap i
          JOIN vbak h ON h.mandt = i.mandt AND h.vbeln = i.vbeln
          JOIN prcd_elements p ON p.client = h.mandt AND p.knumv = h.knumv
                              AND p.kposn = i.posnr AND p.kschl = 'PR00')
        WHERE rn = 1""")
    prices = {m: Decimal(str(k)) for m, k in cur.fetchall()}
    for m in materials:
        m["price"] = prices.get(m["matnr"]) or Decimal(FALLBACK_PRICES.get(m["matnr"], 1000))

    if not customers or not materials:
        sys.exit("No customers or materials found in SAPSD - load the sample data first.")
    return customers, ship_tos, materials


def next_numbers(cur):
    cur.execute("SELECT MAX(vbeln) FROM vbak WHERE mandt = :c AND vbeln BETWEEN :lo AND :hi",
                c=CLIENT, lo=f"{ORDER_RANGE[0]:010d}", hi=f"{ORDER_RANGE[1]:010d}")
    last = cur.fetchone()[0]
    next_vbeln = int(last) + 1 if last else ORDER_RANGE[0]
    cur.execute("""SELECT MAX(TO_NUMBER(knumv)) FROM prcd_elements
                   WHERE client = :c AND REGEXP_LIKE(knumv, '^[0-9]+$')""", c=CLIENT)
    next_knumv = int(cur.fetchone()[0] or 0) + 1
    return next_vbeln, next_knumv


# ---------------------------------------------------------------------------
# Building one order (pure Python, no database access)
# ---------------------------------------------------------------------------
def split_items(total, parts, rng):
    """Random split of `total` items into `parts` orders, each >= 1."""
    cuts = sorted(rng.sample(range(1, total), parts - 1)) if parts > 1 else []
    bounds = [0] + cuts + [total]
    sizes = [bounds[i + 1] - bounds[i] for i in range(parts)]
    rng.shuffle(sizes)
    return sizes


def pick_qty(material, rng):
    price = material["price"]
    if material["meins"] == "M":
        return rng.choice([50, 100, 150, 250, 500])
    if price < 2000:
        return rng.choice([10, 20, 25, 50, 100])
    if price < 50000:
        return rng.randint(2, 15)
    return rng.randint(1, 2)


def price_item(knumv, kposn, material, qty, channel, intra, day):
    """PRCD_ELEMENTS rows for one item; returns (rows, net, tax)."""
    gross = money(material["price"] * qty)
    rows = [dict(kschl="PR00", stunr="010", krech="C", kbetr=material["price"],
                 kawrt=Decimal(qty), kwert=gross, koaid="B", kpein=1, kmein=material["meins"])]
    net = gross
    if channel == "20":
        disc = money(-gross * Decimal("0.05"))
        rows.append(dict(kschl="K004", stunr="100", krech="A", kbetr=Decimal(-5),
                         kawrt=gross, kwert=disc, koaid="A", kpein=None, kmein=None))
        net = gross + disc
    if intra:
        half = money(net * Decimal("0.09"))
        rows += [dict(kschl="JOCG", stunr="800", krech="A", kbetr=Decimal(9), kawrt=net, kwert=half,
                      koaid="D", kpein=None, kmein=None),
                 dict(kschl="JOSG", stunr="810", krech="A", kbetr=Decimal(9), kawrt=net, kwert=half,
                      koaid="D", kpein=None, kmein=None)]
        tax = half * 2
    else:
        tax = money(net * Decimal("0.18"))
        rows.append(dict(kschl="JOIG", stunr="820", krech="A", kbetr=Decimal(18), kawrt=net, kwert=tax,
                         koaid="D", kpein=None, kmein=None))
    for r in rows:
        r.update(client=CLIENT, knumv=knumv, kposn=kposn, zaehk="001", kdatu=day, waers="INR", kherk="A")
    return rows, net, tax


def build_order(vbeln, knumv, n_items, day, created_time, customers, ship_tos, materials, rng,
                cust=None, lines=None, vdatu=None, bstnk=None, clerk=None):
    """Random order by default. The portal passes cust (a customers row), lines
    [(material row, qty)], and optionally vdatu (requested date), bstnk (PO) and clerk."""
    explicit = lines is not None
    cust = cust or rng.choice(customers)
    ag = cust["kunnr"]
    ship = rng.choice(ship_tos[ag]) if not explicit and ag in ship_tos and rng.random() < 0.4 else \
        {"kunnr": ag, "ort01": cust["ort01"], "adrnr": cust["adrnr"]}
    channel, intra = cust["vtweg"], cust["regio"] == PLANT_REGION
    clerk, erzet = clerk or rng.choice(CLERKS), created_time.strftime("%H%M%S")
    vdatu = vdatu or day + dt.timedelta(days=rng.randint(4, 10))

    if explicit:
        mats, qtys = [m for m, _ in lines], [q for _, q in lines]
    else:
        # Distinct materials while possible, repeats allowed for very large orders.
        mats = rng.sample(materials, n_items) if n_items <= len(materials) else \
            [rng.choice(materials) for _ in range(n_items)]
        qtys = [pick_qty(m, rng) for m in mats]

    vbap, vbep, prcd = [], [], []
    for i, (m, qty) in enumerate(zip(mats, qtys), 1):
        posnr = f"{i * 10:06d}"
        conds, net, tax = price_item(knumv, posnr, m, qty, channel, intra, day)
        prcd += conds
        vbap.append(dict(
            mandt=CLIENT, vbeln=vbeln, posnr=posnr, matnr=m["matnr"], arktx=m["maktx"], pstyv="TAN",
            matkl=m["matkl"], prodh=m["prdha"], kwmeng=Decimal(qty), vrkme=m["meins"], meins=m["meins"],
            umvkz=1, umvkn=1, netpr=money(net / qty), kpein=1, kmein=m["meins"], netwr=net, mwsbp=tax,
            waerk="INR", werks=PLANT, lgort="0001", vstel=PLANT,
            route="R00001" if intra else "R00002", prctr="PC" + PLANT,
            erdat=day, erzet=erzet, ernam=clerk, gbsta="A", absta="A", lfsta="A"))
        vbep.append(dict(
            mandt=CLIENT, vbeln=vbeln, posnr=posnr, etenr="0001", ettyp="CP", edatu=vdatu,
            wmeng=Decimal(qty), bmeng=Decimal(qty), vrkme=m["meins"], lmeng=Decimal(qty), meins=m["meins"],
            mbdat=vdatu - dt.timedelta(days=2), lddat=vdatu - dt.timedelta(days=2),
            wadat=vdatu - dt.timedelta(days=1), tddat=vdatu - dt.timedelta(days=2)))

    bstnk = (bstnk or f"PO/{ag[-4:]}/{day:%y%m%d}/{rng.randint(100, 999)}")[:35]
    vbak = dict(
        mandt=CLIENT, vbeln=vbeln, erdat=day, erzet=erzet, ernam=clerk, audat=day, vbtyp="C", trvog="0",
        auart="OR", netwr=sum((r["netwr"] for r in vbap), Decimal(0)), waerk="INR", vkorg=VKORG,
        vtweg=channel, spart=SPART, vkgrp=cust["vkgrp"], vkbur=cust["vkbur"], knumv=knumv, vdatu=vdatu,
        bstnk=bstnk, bstdk=day - dt.timedelta(days=1), kunnr=ag, kkber="1000", bukrs_vf=COMPANY,
        gbstk="A", abstk="A", lfstk="A", cmgst="A", spstg="A")
    vbkd = dict(
        mandt=CLIENT, vbeln=vbeln, posnr="000000", zterm=cust["zterm"], inco1=cust["inco1"] or "DAP",
        inco2=ship["ort01"], bstkd=bstnk, prsdt=day, kursk=Decimal(1), kdgrp=cust["kdgrp"],
        bzirk=cust["bzirk"], konda=cust["konda"], pltyp=cust["pltyp"], ktgrd=cust["ktgrd"])
    vbpa = [dict(mandt=CLIENT, vbeln=vbeln, posnr="000000", parvw=pv, kunnr=k, adrnr=a, land1="IN")
            for pv, k, a in [("AG", ag, cust["adrnr"]), ("WE", ship["kunnr"], ship["adrnr"]),
                             ("RE", ag, cust["adrnr"]), ("RG", ag, cust["adrnr"])]]
    return {"vbak": [vbak], "vbap": vbap, "vbep": vbep, "vbkd": [vbkd], "vbpa": vbpa, "prcd_elements": prcd}


# ---------------------------------------------------------------------------
# Database writes
# ---------------------------------------------------------------------------
INSERT_ORDER = ["vbak", "vbap", "vbep", "vbkd", "vbpa", "prcd_elements"]


def insert_order(conn, order):
    """All tables of one order in one transaction: commit together or not at all."""
    with conn.cursor() as cur:
        for table in INSERT_ORDER:
            rows = order[table]
            cols = list(rows[0].keys())
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
            cur.executemany(sql, rows)
    conn.commit()


def run_day(conn, day, args, rng, master):
    customers, ship_tos, materials = master
    if conn:
        with conn.cursor() as cur:
            next_vbeln, next_knumv = next_numbers(cur)
    else:
        next_vbeln, next_knumv = ORDER_RANGE[0], 900000

    sizes = split_items(args.items, args.orders, rng)
    now = dt.datetime.now()
    total_net = Decimal(0)
    for n, n_items in enumerate(sizes):
        vbeln, knumv = f"{next_vbeln + n:010d}", f"{next_knumv + n:010d}"
        created = now if day == now.date() else dt.datetime.combine(
            day, dt.time(rng.randint(9, 18), rng.randint(0, 59), rng.randint(0, 59)))
        order = build_order(vbeln, knumv, n_items, day, created, customers, ship_tos, materials, rng)
        if conn:
            insert_order(conn, order)
        h = order["vbak"][0]
        total_net += h["netwr"]
        print(f"  {'(dry run) ' if not conn else ''}{vbeln}  {h['erdat']}  customer {h['kunnr']}  "
              f"channel {h['vtweg']}  items {len(order['vbap']):3d}  net INR {h['netwr']:>14,.2f}")
    print(f"  {day}: {args.orders} orders, {args.items} items, net INR {total_net:,.2f}")


def main():
    args = parse_args()
    rng = random.Random(args.seed)
    base_day = args.date or dt.date.today()
    days = [base_day - dt.timedelta(days=d) for d in range(args.backfill_days - 1, -1, -1)] \
        if args.backfill_days else [base_day]

    try:
        import oracledb
    except ImportError:
        sys.exit("Missing driver: pip install oracledb")

    dsn = os.getenv("ORACLE_DSN", f"{args.host}:{args.port}/{args.service}")
    print(f"Connecting to {args.user}@{dsn}")
    conn = oracledb.connect(user=args.user, password=args.password, dsn=dsn)
    try:
        with conn.cursor() as cur:
            master = load_master_data(cur)
        print(f"Master data: {len(master[0])} customers, {len(master[2])} materials")
        for day in days:
            run_day(None if args.dry_run else conn, day, args, rng, master)
    finally:
        conn.close()
    if not args.dry_run:
        print("Committed. Changes reach Kafka in seconds and SAP_CORE in Snowflake within ~2 minutes.")


if __name__ == "__main__":
    main()
