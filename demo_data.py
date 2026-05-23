"""
demo_data.py — 데모 모드용 내장 샘플 데이터
────────────────────────────────────────────
엑셀 업로드 없이 바로 시연 가능한 시나리오 데이터 생성.
실제 업로드 기능은 그대로 유지.
"""
import numpy as np
import pandas as pd

DEMO_SCENARIOS = {
    "샘플 A: 유통기한 임박":     "expiry_urgent",
    "샘플 B: 냉장·냉동 과잉":    "cold_excess",
    "샘플 C: 지역 수요 급증":    "demand_surge",
    "샘플 D: 배송비 상승":       "high_transport",
    "샘플 E: 종합 스트레스 테스트": "stress",
}

_STORES = [
    "강남점","홍대점","잠실점","역삼점","신촌점",
    "건대점","종로점","용산점","구로점","사당점",
]
_PRODUCTS = {
    "expiry_urgent":  ["서울우유","유어스샐러드랩","매일바이오플레인요거트","심플리쿡리코타치즈샐러드","헤자로운햄구이도시락"],
    "cold_excess":    ["냉동만두","냉동김밥","냉장삼각김밥","유어스치즈케이크","서울우유"],
    "demand_surge":   ["브레디크소금버터롤","카페25","심플리쿡닭가슴살샌드위치","오뚜기진라면컵","롯데카스타드"],
    "high_transport": ["제주삼다수","롯데칠성음료","서울우유","농심새우깡","오리온초코파이"],
    "stress":         ["서울우유","유어스샐러드랩","냉동만두","브레디크소금버터롤","카페25"],
}
_CATS = {
    "expiry_urgent":  ["신선", "신선", "유제품", "신선", "도시락"],
    "cold_excess":    ["냉동", "냉동", "냉장", "냉장", "유제품"],
    "demand_surge":   ["베이커리","음료","신선","라면","스낵"],
    "high_transport": ["음료","음료","유제품","스낵","스낵"],
    "stress":         ["유제품","신선","냉동","베이커리","음료"],
}

def _rng(seed=42):
    return np.random.default_rng(seed)


def _make_stores(n=10) -> pd.DataFrame:
    rows = []
    for i, name in enumerate(_STORES[:n]):
        rows.append({
            "store_id":   f"S{i+1:03d}",
            "store_name": name,
            "region":     ["강남구","마포구","송파구","강남구","서대문구",
                           "광진구","종로구","용산구","구로구","동작구"][i],
            "latitude":   37.48 + i*0.02,
            "longitude":  127.02 + i*0.015,
        })
    return pd.DataFrame(rows)


def _make_products(scenario: str) -> pd.DataFrame:
    prods = _PRODUCTS.get(scenario, _PRODUCTS["stress"])
    cats  = _CATS.get(scenario, _CATS["stress"])
    rows = []
    for i, (p, c) in enumerate(zip(prods, cats)):
        rows.append({
            "product_id":   f"P{i+1:03d}",
            "product_name": p,
            "category":     c,
            "unit_cost":    np.random.randint(500, 4500),
            "unit_price":   np.random.randint(800, 5500),
        })
    return pd.DataFrame(rows)


def _make_inventory(scenario: str, stores, products, rng) -> pd.DataFrame:
    rows = []
    for si, srow in stores.iterrows():
        for pi, prow in products.iterrows():
            base_stock = int(rng.integers(30, 250))
            base_sales = float(rng.uniform(2, 40))

            # 시나리오별 특수값
            if scenario == "expiry_urgent":
                expiry = int(rng.integers(1, 8))
                stock  = int(rng.integers(50, 300))
            elif scenario == "cold_excess":
                expiry = int(rng.integers(3, 20))
                stock  = int(rng.integers(100, 400))
            elif scenario == "demand_surge":
                expiry = int(rng.integers(7, 30))
                stock  = int(rng.integers(20, 150))
                base_sales *= 2.5
            elif scenario == "high_transport":
                expiry = int(rng.integers(5, 30))
                stock  = base_stock
            else:
                expiry = int(rng.integers(2, 30))
                stock  = base_stock

            rows.append({
                "store_id":      srow["store_id"],
                "store_name":    srow["store_name"],
                "product_id":    prow["product_id"],
                "product_name":  prow["product_name"],
                "inventory_category": prow["category"],
                "stock_qty":     stock,
                "avg_daily_sales": round(base_sales, 1),
                "sales_7d":      int(base_sales * 7 * rng.uniform(0.7, 1.3)),
                "sales_30d":     int(base_sales * 30 * rng.uniform(0.8, 1.2)),
                "expiry_days":   expiry,
                "unit_cost":     prow["unit_cost"],
                "disposal_cost": int(prow["unit_cost"] * 0.15),
                "demand_std":    round(base_sales * 0.3, 2),
                "lead_time_days": int(rng.integers(1, 4)),
                "cold_required": "Y" if prow["category"] in ("냉동","냉장","유제품") else "N",
            })
    return pd.DataFrame(rows)


def _make_routes(stores: pd.DataFrame, scenario: str, rng) -> pd.DataFrame:
    rows = []
    store_list = stores["store_name"].tolist()
    for i, s1 in enumerate(store_list):
        for j, s2 in enumerate(store_list):
            if i == j: continue
            dist = float(rng.uniform(1.0, 15.0))
            base_cost = dist * 400
            if scenario == "high_transport":
                base_cost *= 2.5
            rows.append({
                "source_store":   s1,
                "target_store":   s2,
                "distance_km":    round(dist, 1),
                "transport_cost": int(base_cost),
                "via_distance_km":       round(dist * 1.3, 1),
                "direct_distance_km":    round(dist, 1),
                "recommended_distance_km": round(dist * 1.1, 1),
                "transport_type":        "오토바이" if dist < 5 else "트럭",
            })
    return pd.DataFrame(rows)


def get_demo_sheets(scenario_key: str) -> dict:
    """
    시나리오 키 → Varo 분석 가능한 4개 시트 dict 반환.
    scenario_key: 'expiry_urgent' | 'cold_excess' | 'demand_surge' |
                  'high_transport' | 'stress'
    """
    rng = _rng(seed={"expiry_urgent":1,"cold_excess":2,"demand_surge":3,
                     "high_transport":4,"stress":5}.get(scenario_key, 42))
    stores   = _make_stores(n=8)
    products = _make_products(scenario_key)
    inv      = _make_inventory(scenario_key, stores, products, rng)
    routes   = _make_routes(stores, scenario_key, rng)
    return {
        "stores":   stores,
        "products": products,
        "inventory": inv,
        "routes":   routes,
    }


def scenario_description(scenario_key: str) -> str:
    desc = {
        "expiry_urgent":  "유통기한 1~7일 상품 비중 높음 — 폐기 위험 긴급 처리 시나리오",
        "cold_excess":    "냉장·냉동 상품 과잉 재고 — 운반 제약 처리 시나리오",
        "demand_surge":   "최근 7일 판매량 급증 — 재배치 우선 시나리오",
        "high_transport": "경로 평균 운송비 2.5배 — 비용 최적화 시나리오",
        "stress":         "유통기한 임박 + 냉동 과잉 + 수요 급증 복합 스트레스",
    }
    return desc.get(scenario_key, "")
