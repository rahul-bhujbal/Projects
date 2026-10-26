"""
Create and load a small sample SALES dataset in your Oracle schema.

Tables: REGIONS, CUSTOMERS, PRODUCTS, ORDERS, ORDER_ITEMS
Data:   5 regions, 300 customers, 40 products, ~6,000 orders (2024-2025)

Run once:  python setup_sample_data.py
Re-running drops and recreates these five tables (only these five).
"""

import random
from datetime import date, timedelta

import oracledb

from sql_assistant import SCHEMA, get_connection

TABLES = ["ORDER_ITEMS", "ORDERS", "PRODUCTS", "CUSTOMERS", "REGIONS"]

DDL = [
    """CREATE TABLE regions (
         region_id   NUMBER PRIMARY KEY,
         region_name VARCHAR2(50) NOT NULL)""",
    """CREATE TABLE customers (
         customer_id   NUMBER PRIMARY KEY,
         customer_name VARCHAR2(100) NOT NULL,
         city          VARCHAR2(50),
         segment       VARCHAR2(20),
         region_id     NUMBER REFERENCES regions(region_id))""",
    """CREATE TABLE products (
         product_id   NUMBER PRIMARY KEY,
         product_name VARCHAR2(100) NOT NULL,
         category     VARCHAR2(50),
         unit_price   NUMBER(10,2))""",
    """CREATE TABLE orders (
         order_id    NUMBER PRIMARY KEY,
         customer_id NUMBER REFERENCES customers(customer_id),
         order_date  DATE NOT NULL,
         status      VARCHAR2(20))""",
    """CREATE TABLE order_items (
         order_id   NUMBER REFERENCES orders(order_id),
         line_no    NUMBER,
         product_id NUMBER REFERENCES products(product_id),
         quantity   NUMBER,
         unit_price NUMBER(10,2),
         discount   NUMBER(4,2),
         CONSTRAINT order_items_pk PRIMARY KEY (order_id, line_no))""",
]

COMMENTS = [
    "COMMENT ON COLUMN customers.segment IS 'Consumer, Corporate or Small Business'",
    "COMMENT ON COLUMN orders.status IS 'DELIVERED, SHIPPED, PENDING or CANCELLED'",
    "COMMENT ON COLUMN order_items.unit_price IS 'Price per unit at time of sale'",
    "COMMENT ON COLUMN order_items.discount IS 'Fraction off, 0.10 = 10 percent. "
    "Line revenue = quantity * unit_price * (1 - discount)'",
]

REGIONS = ["North", "South", "East", "West", "Central"]
CITIES = {
    "North": ["Delhi", "Chandigarh", "Lucknow"],
    "South": ["Bengaluru", "Chennai", "Hyderabad"],
    "East": ["Kolkata", "Bhubaneswar", "Patna"],
    "West": ["Mumbai", "Pune", "Ahmedabad", "Nashik"],
    "Central": ["Bhopal", "Indore", "Nagpur"],
}
CATEGORIES = {
    "Electrical": ["Circuit Breaker", "Switchgear Panel", "Contactor", "Relay", "Fuse Kit",
                   "Busbar", "Surge Protector", "Isolator"],
    "Power Quality": ["UPS 1kVA", "UPS 3kVA", "UPS 10kVA", "Voltage Stabilizer",
                      "Power Analyzer", "Harmonic Filter"],
    "Hydraulics": ["Hydraulic Pump", "Hydraulic Hose", "Valve Block", "Cylinder",
                   "Hydraulic Filter", "Pressure Gauge"],
    "Lighting": ["LED Panel", "Flood Light", "Street Light", "Emergency Light",
                 "Tube Light", "High Bay Light"],
    "Automation": ["PLC Module", "HMI Screen", "Motor Drive", "Sensor Pack",
                   "Control Cable", "Timer Relay", "Push Button Station",
                   "Signal Tower", "Encoder", "Servo Motor", "Safety Switch",
                   "Panel Meter", "Terminal Block", "Power Supply 24V"],
}
SEGMENTS = ["Consumer", "Corporate", "Small Business"]
FIRST = ["Shree", "Om", "Sai", "Ganesh", "Patil", "Kulkarni", "Desai", "Mehta", "Rao",
         "Iyer", "Sharma", "Verma", "Gupta", "Joshi", "Reddy"]
LAST = ["Industries", "Traders", "Engineering", "Electricals", "Enterprises",
        "Automation", "Power Systems", "Infra", "Solutions", "Works"]


def drop_existing(cur):
    cur.execute("SELECT table_name FROM user_tables")
    existing = {r[0] for r in cur.fetchall()}
    for t in TABLES:
        if t in existing:
            cur.execute(f"DROP TABLE {t} CASCADE CONSTRAINTS PURGE")
            print(f"  dropped {t}")


def build_data():
    rnd = random.Random(42)  # same data every time

    regions = [(i + 1, name) for i, name in enumerate(REGIONS)]

    customers = []
    for cid in range(1, 301):
        rid = rnd.randint(1, len(REGIONS))
        region = REGIONS[rid - 1]
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)} {cid}"
        customers.append((cid, name, rnd.choice(CITIES[region]),
                          rnd.choices(SEGMENTS, weights=[3, 5, 2])[0], rid))

    products, pid = [], 0
    for category, names in CATEGORIES.items():
        for name in names:
            pid += 1
            products.append((pid, name, category, round(rnd.uniform(500, 75000), 2)))
    price = {p[0]: p[3] for p in products}

    orders, items = [], []
    start, days = date(2024, 1, 1), 731
    oid = 0
    for _ in range(6000):
        oid += 1
        day = start + timedelta(days=rnd.randrange(days))
        status = rnd.choices(["DELIVERED", "SHIPPED", "PENDING", "CANCELLED"],
                             weights=[78, 10, 6, 6])[0]
        orders.append((oid, rnd.randint(1, 300), day, status))
        for line in range(1, rnd.randint(1, 4) + 1):
            p = rnd.randint(1, len(products))
            items.append((oid, line, p, rnd.randint(1, 20), price[p],
                          rnd.choice([0, 0, 0, 0.05, 0.10, 0.15, 0.20])))
    return regions, customers, products, orders, items


def main():
    conn = get_connection()
    print(f"Loading sample data into schema {SCHEMA} ...")
    regions, customers, products, orders, items = build_data()
    try:
        with conn.cursor() as cur:
            drop_existing(cur)
            for stmt in DDL:
                cur.execute(stmt)
            for stmt in COMMENTS:
                cur.execute(stmt)
            cur.executemany("INSERT INTO regions VALUES (:1, :2)", regions)
            cur.executemany("INSERT INTO customers VALUES (:1, :2, :3, :4, :5)", customers)
            cur.executemany("INSERT INTO products VALUES (:1, :2, :3, :4)", products)
            cur.executemany("INSERT INTO orders VALUES (:1, :2, :3, :4)", orders)
            cur.executemany("INSERT INTO order_items VALUES (:1, :2, :3, :4, :5, :6)", items)
        conn.commit()
        print(f"Done: {len(regions)} regions, {len(customers)} customers, "
              f"{len(products)} products, {len(orders)} orders, {len(items)} order items.")
    except oracledb.Error as exc:
        conn.rollback()
        raise SystemExit(f"Setup failed: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
