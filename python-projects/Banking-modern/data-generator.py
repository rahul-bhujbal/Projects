import time
import oracledb
from decimal import Decimal, ROUND_DOWN
from faker import Faker
import random
import argparse
import sys
import os
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Project configuration (safe to hardcode here)
# -----------------------------
NUM_CUSTOMERS = 10
ACCOUNTS_PER_CUSTOMER = 2
NUM_TRANSACTIONS = 50
MAX_TXN_AMOUNT = 1000.00
CURRENCY = "USD"

# Non-zero initial balances
INITIAL_BALANCE_MIN = Decimal("10.00")
INITIAL_BALANCE_MAX = Decimal("1000.00")

# Loop config
DEFAULT_LOOP = True
SLEEP_SECONDS = 2

# CLI override (run once mode)
parser = argparse.ArgumentParser(description="Run fake data generator")
parser.add_argument("--once", action="store_true", help="Run a single iteration and exit")
args = parser.parse_args()
LOOP = not args.once and DEFAULT_LOOP

# -----------------------------
# Helpers
# -----------------------------
fake = Faker()

def random_money(min_val: Decimal, max_val: Decimal) -> Decimal:
    val = Decimal(str(random.uniform(float(min_val), float(max_val))))
    return val.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

# -----------------------------
# Connect to Postgres
# -----------------------------
import oracledb

# Connect using service name
con = oracledb.connect(
    user="bank_modern",
    password="bank",
    dsn="localhost:1521/XEPDB1"   # host:port/service_name
)

print("✅ Connected to Oracle 18c!")

cur = con.cursor()

# -----------------------------
# Core generation logic (one iteration)
# -----------------------------
def run_iteration():
    try:
        print("Generate customers started")
        customers = []
        # 1. Generate customers
        for i in range(NUM_CUSTOMERS):
            first_name = fake.first_name()
            last_name = fake.last_name()
            email = fake.unique.email()
            print((first_name, last_name, email))
            customer_id = cur.var(int)
            cur.execute(
                """
                INSERT INTO bank_modern.customers (first_name, last_name, email) 
                VALUES (:1, :2, :3)
                RETURNING id INTO :4
                """,
                (first_name, last_name, email, customer_id)
            )

            customers.append(customer_id.getvalue()[0])

            con.commit()
        print("Generate customers finished")
    except Exception as e:
            print("Full Error:", str(e))

    # 2. Generate accounts
    ACCOUNT_TYPES = ["SAVINGS", "CURRENT"]
    CURRENCIES = ["USD", "INR", "EUR"]

    accounts = []

    try:
        print("Generate accounts started")

        for customer_id in customers:

            # Each customer can have 1 to 3 accounts
            num_accounts = random.randint(1, 3)

            for _ in range(num_accounts):
                account_type = random.choice(ACCOUNT_TYPES)
                balance = round(random.uniform(1000, 100000), 2)
                currency = random.choice(CURRENCIES)
                print(customer_id, account_type, balance, currency)
                account_id_var = cur.var(int)

                cur.execute("""
                    INSERT INTO bank_modern.accounts
                    (customer_id, account_type, balance, currency)
                    VALUES (:1, :2, :3, :4)
                    RETURNING id INTO :5
                """, (customer_id, account_type, balance, currency, account_id_var))

                account_id = account_id_var.getvalue()[0]

                accounts.append({
                    "account_id": account_id,
                    "customer_id": customer_id
                })

        # ✅ Commit once
        con.commit()

        print("Generate accounts finished")

    except Exception as e:
        print("Full Error:", str(e))
    # 3. Generate transactions
    txn_types = ["DEPOSIT", "WITHDRAWAL", "TRANSFER"]
    try:
        print("Generate transactions started")

        for _ in range(NUM_TRANSACTIONS):

            account = random.choice(accounts)
            account_id = account["account_id"]

            txn_type = random.choice(txn_types)
            amount = round(random.uniform(1, MAX_TXN_AMOUNT), 2)

            related_account_id = None

            if txn_type == "TRANSFER" and len(accounts) > 1:
                target = random.choice([a for a in accounts if a != account])
                related_account_id = target["account_id"]

            cur.execute(
                """
                INSERT INTO bank_modern.transactions 
                (account_id, txn_type, amount, related_account_id, status)
                VALUES (:1, :2, :3, :4, 'COMPLETED')
                """,
                (account_id, txn_type, amount, related_account_id),
            )

        con.commit()

        print("Generate transactions finished")
        print(f"✅ Generated {len(customers)} customers, {len(accounts)} accounts, {NUM_TRANSACTIONS} transactions.")

    except Exception as e:
        print("Full Error:", str(e))
# -----------------------------
# Main loop
# -----------------------------
try:
    iteration = 0
    while True:
        iteration += 1
        print(f"\n--- Iteration {iteration} started ---")
        run_iteration()
        print(f"--- Iteration {iteration} finished ---")
        if not LOOP:
            break
        time.sleep(SLEEP_SECONDS)

except KeyboardInterrupt:
    print("\nInterrupted by user. Exiting gracefully...")

finally:
    cur.close()
    con.close()
    sys.exit(0)