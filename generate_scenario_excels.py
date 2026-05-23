"""
generate_scenario_excels.py — 강화학습 학습 데이터용 시나리오 엑셀 10개 생성
실행: py generate_scenario_excels.py
"""
import pandas as pd, numpy as np
from pathlib import Path

RNG = np.random.default_rng(42)
OUT_DIR = Path("scenario_excels"); OUT_DIR.mkdir(exist_ok=True)

STORES = [f"점포{i:02d}" for i in range(1, 16)]
PRODUCTS = [
    ("P01","서울우유200",    "유제품",    1090, 1400),
    ("P02","냉동만두500g",   "냉동식품",  3800, 4500),
    ("P03","유어스샐러드랩", "신선식품",  2450, 3200),
    ("P04","브레디크소금버터롤","베이커리",2090, 2600),
    ("P05","카페25아메리카노","음료",      1210, 1500),
    ("P06","제주삼다수2L",   "음료",      1500, 1800),
    ("P07","롯데카스타드",   "스낵",      2200, 2700),
    ("P08","오뚜기진라면컵", "라면",       950, 1200),
    ("P09","냉동삼각김밥",   "냉동식품",  1800, 2200),
    ("P10","심플리쿡닭가슴살","신선식품", 4200, 5200),
]

def make_stores():
    return pd.DataFrame([{
        "store_id": f"S{i:02d}", "store_name": STORES[i-1],
        "region": ["강남","마포","송파","강남","서대문","광진","종로","용산","구로","동작",
                   "중구","노원","성북","관악","강북"][i-1],
        "latitude":  37.45 + RNG.uniform(-0.1,0.1),
        "longitude": 127.0 + RNG.uniform(-0.1,0.1),
    } for i in range(1, 16)])

def make_products():
    return pd.DataFrame([{
        "product_id": pid, "product_name": name,
        "category": cat, "unit_cost": cost, "unit_price": price,
    } for pid, name, cat, cost, price in PRODUCTS])

def make_routes(stores):
    rows = []
    slist = stores["store_name"].tolist()
    for i,s1 in enumerate(slist):
        for j,s2 in enumerate(slist):
            if i==j: continue
            d = RNG.uniform(1, 20)
            rows.append({
                "source_store": s1, "target_store": s2,
                "distance_km": round(d,1), "transport_cost": int(d*400),
                "direct_distance_km": round(d,1), "via_distance_km": round(d*1.3,1),
            })
    return pd.DataFrame(rows)

def make_inventory(scenario_fn, stores, products):
    rows = []
    for _, srow in stores.iterrows():
        for pid, name, cat, cost, _ in PRODUCTS:
            s, q, d, e = scenario_fn(cat)
            rows.append({
                "store_id": srow["store_id"], "store_name": srow["store_name"],
                "product_id": pid, "product_name": name,
                "inventory_category": cat,
                "stock_qty": max(0, int(s + RNG.integers(-20,20))),
                "avg_daily_sales": max(0.5, round(d + RNG.uniform(-1,1), 1)),
                "sales_30d": max(1, int(d*30 + RNG.integers(-10,10))),
                "days_to_expiry": max(1, int(e + RNG.integers(-2,3))),
                "unit_cost": cost,
                "disposal_cost_per_unit": int(cost*0.15),
                "demand_std": round(d*0.3, 2),
                "lead_time_days": int(RNG.integers(1,4)),
            })
    return pd.DataFrame(rows)

def save_scenario(name, inv_fn, idx):
    stores   = make_stores()
    products = make_products()
    inv      = make_inventory(inv_fn, stores, products)
    routes   = make_routes(stores)
    path     = OUT_DIR / f"scenario_{idx:02d}_{name}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        stores.to_excel(w,   sheet_name="stores",    index=False)
        products.to_excel(w, sheet_name="products",  index=False)
        inv.to_excel(w,      sheet_name="inventory", index=False)
        routes.to_excel(w,   sheet_name="routes",    index=False)
    print(f"  ✅ {path.name}")
    return path

SCENARIOS = [
    ("normal",        lambda c: (80,  80,  5,   20)),
    ("heatwave",      lambda c: (60,  80, 10,   15) if c in ("음료","신선식품")   else (80,60,4,20)),
    ("cold",          lambda c: (50,  80, 10,   20) if c in ("냉동식품","라면")   else (80,60,4,20)),
    ("store_excess",  lambda c: (300, 60,  4,   10)),
    ("stockout_risk", lambda c: (20,  80, 15,   25)),
    ("high_transport",lambda c: (80,  80,  5,   20)),  # routes에서 비용 2배
    ("promo_high",    lambda c: (100, 80,  8,   12)),
    ("promo_low",     lambda c: (100, 80,  3,   25)),
    ("dc_preferred",  lambda c: (80,  80,  5,   20)),
    ("direct_preferred",lambda c:(80, 80,  5,   20)),
]

print("시나리오 엑셀 생성 중...")
for i, (name, fn) in enumerate(SCENARIOS, 1):
    save_scenario(name, fn, i)
print(f"\n✅ {len(SCENARIOS)}개 시나리오 엑셀 → {OUT_DIR}/")
