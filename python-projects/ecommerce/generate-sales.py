import pandas as pd
import numpy as np
import random
from faker import Faker
from datetime import datetime, timedelta

fake = Faker()

# CONFIGURATION
NUM_RECORDS = 1000
ERROR_PERCENTAGE = 0.08   # 8% of records will contain errors

countries = ["US", "UK", "IN", "DE", "FR", "CA", "AU"]
categories = ["Electronics", "Clothing", "Home", "Books", "Sports"]
payment_methods = ["Credit Card", "PayPal", "UPI", "Debit Card"]

def generate_data():
    data = []

    for i in range(NUM_RECORDS):
        order_date = fake.date_between(start_date='-1y', end_date='today')
        quantity = random.randint(1, 5)
        price = round(random.uniform(10, 500), 2)

        data.append({
            "transaction_id": f"T{i+1}",
            "order_date": order_date,
            "customer_id": f"C{random.randint(1, 300)}",
            "customer_name": fake.name(),
            "country": random.choice(countries),
            "product_id": f"P{random.randint(1, 200)}",
            "product_category": random.choice(categories),
            "quantity": quantity,
            "price": price,
            "payment_method": random.choice(payment_methods),
            "order_status": random.choice(["Completed", "Cancelled", "Returned"])
        })

    df = pd.DataFrame(data)

    inject_errors(df)

    df.to_csv("ecommerce_sales.csv", index=False)
    print("CSV file generated successfully.")

def inject_errors(df):
    num_errors = int(len(df) * ERROR_PERCENTAGE)

    for _ in range(num_errors):
        row = random.randint(0, len(df) - 1)
        error_type = random.choice([
            "null_customer",
            "negative_quantity",
            "invalid_price",
            "future_date",
            "invalid_country",
            "duplicate_transaction"
        ])

        if error_type == "null_customer":
            df.at[row, "customer_id"] = None

        elif error_type == "negative_quantity":
            df.at[row, "quantity"] = -random.randint(1, 5)

        elif error_type == "invalid_price":
            df.at[row, "price"] = -random.uniform(1, 100)

        elif error_type == "future_date":
            df.at[row, "order_date"] = datetime.now() + timedelta(days=30)

        elif error_type == "invalid_country":
            df.at[row, "country"] = "XYZ"

        elif error_type == "duplicate_transaction":
            df.at[row, "transaction_id"] = "T1"

if __name__ == "__main__":
    generate_data()