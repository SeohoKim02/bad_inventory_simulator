import pandas as pd
import numpy as np
import random


def generate_stores(num_stores):
    regions = ["수도권", "충청권", "영남권", "호남권"]
    stores = []

    for i in range(num_stores):
        stores.append({
            "store_id": f"S{i+1:03d}",
            "store_name": f"점포{i+1}",
            "region": random.choice(regions)
        })

    return pd.DataFrame(stores)


def generate_products(num_products):
    categories = ["식품", "생활용품", "계절상품"]
    products = []

    for i in range(num_products):
        products.append({
            "product_id": f"P{i+1:03d}",
            "product_name": f"상품{i+1}",
            "category": random.choice(categories)
        })

    return pd.DataFrame(products)


def generate_inventory(stores, products, bad_ratio):
    rows = []

    for _, store in stores.iterrows():
        for _, product in products.iterrows():
            sales_30d = np.random.randint(0, 31)
            stock_qty = np.random.randint(5, 101)
            inbound_days_ago = np.random.randint(1, 91)
            holding_cost = np.random.randint(100, 1000)

            if random.random() < bad_ratio:
                sales_30d = np.random.randint(0, 6)
                stock_qty = np.random.randint(50, 151)
                inbound_days_ago = np.random.randint(45, 121)

            rows.append({
                "store_id": store["store_id"],
                "store_name": store["store_name"],
                "region": store["region"],
                "product_id": product["product_id"],
                "product_name": product["product_name"],
                "category": product["category"],
                "stock_qty": stock_qty,
                "sales_30d": sales_30d,
                "inbound_days_ago": inbound_days_ago,
                "holding_cost": holding_cost
            })

    return pd.DataFrame(rows)
