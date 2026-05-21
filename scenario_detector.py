"""
scenario_detector.py — 상황 감지 + 가중치 자동 조정
────────────────────────────────────────────────────
detect_scenario()         : 현재 데이터에서 상황 탐지 → severity 0~1
adjust_weights_by_scenario(): 상황별 VHS 가중치 재배분
"""
import numpy as np
import pandas as pd

# ── 기본 가중치 (V2) ───────────────────────────────────────
BASE_WEIGHTS_V2 = {
    "재고위험":     0.25,
    "판매가능성":   0.20,
    "점포이동적합": 0.15,
    "비용절감":     0.15,
    "폐기회피이익": 0.10,
    "실행가능성":   0.10,
    "이력보정":     0.05,
}

_COLD_KEYWORDS = ["냉동","냉장","냉","cold","frozen","chilled","유제품","신선","dairy","fresh"]


def _col(df, *names, dtype=None, default=None):
    """컬럼 fallback 탐색. dtype='str'이면 문자열 변환."""
    for n in names:
        if n in df.columns:
            s = df[n]
            if dtype == "str":
                return s.fillna("").astype(str)
            return pd.to_numeric(s, errors="coerce")
    return default


# ──────────────────────────────────────────────────────────
def detect_scenario(
    df: pd.DataFrame,
    inventory_df: pd.DataFrame = None,
    routes_df:    pd.DataFrame = None,
) -> dict:
    """
    Returns dict[scenario_name → severity 0.0~1.0]
    severity 0 = 해당 없음, 1 = 최대 강도

    탐지 상황:
        EXPIRY_URGENT   유통기한 임박
        COLD_EXCESS     냉장/냉동 과잉
        DEMAND_SURGE    지역 수요 급증
        HIGH_TRANSPORT  배송비 상승
        REORDER_RISK    재주문 위험
        STRESS          복합 스트레스 (3개 이상 동시)
    """
    if df is None or df.empty:
        return {}

    scenarios: dict[str, float] = {}
    n = max(len(df), 1)

    # ── 1. 유통기한 임박 ──────────────────────────────────
    expiry = _col(df, "expiry_days", "days_to_expiry")
    if expiry is not None:
        valid   = expiry.dropna()
        if len(valid):
            urgent  = (valid <= 7).mean()         # 7일 이내 비율
            avg_exp = valid.clip(upper=60).mean()  # 평균 유통기한
            sev     = urgent * 0.7 + (1 - avg_exp / 60) * 0.3
            scenarios["EXPIRY_URGENT"] = float(min(1.0, sev))

    # ── 2. 냉장/냉동 과잉 ────────────────────────────────
    cat = _col(df, "category", "inventory_category", dtype="str")
    if cat is None and inventory_df is not None:
        cat = _col(inventory_df, "category", "inventory_category",
                   "inventory_product_category", dtype="str")
    if cat is not None:
        cold_rate = cat.str.lower().apply(
            lambda c: any(k in c for k in _COLD_KEYWORDS)
        ).mean()
        scenarios["COLD_EXCESS"] = float(min(1.0, cold_rate * 2))

    # ── 3. 지역 수요 급증 ────────────────────────────────
    s7  = _col(df, "sales_7d",  "sales_7")
    s30 = _col(df, "sales_30d", "state_source_sales_30d", "sales_30")
    avg = _col(df, "avg_daily_sales")

    if s7 is not None and s30 is not None:
        daily7  = (s7  / 7).clip(lower=0)
        daily30 = (s30 / 30).clip(lower=0.01)
        surge_rate = (daily7 > daily30 * 1.2).mean()
        scenarios["DEMAND_SURGE"] = float(min(1.0, surge_rate * 2))
    elif s7 is not None and avg is not None:
        surge_rate = (s7 / 7 > avg * 1.2).mean()
        scenarios["DEMAND_SURGE"] = float(min(1.0, surge_rate * 2))

    # ── 4. 배송비 상승 ───────────────────────────────────
    baseline_cost = 3_000  # 기준 단가(원/건)
    if routes_df is not None and "transport_cost" in routes_df.columns:
        avg_transport = pd.to_numeric(
            routes_df["transport_cost"], errors="coerce"
        ).dropna().mean()
        if avg_transport and avg_transport > 0:
            sev = min(1.0, max(0.0, (avg_transport - baseline_cost) / baseline_cost))
            scenarios["HIGH_TRANSPORT"] = float(sev)
    else:
        est = _col(df, "estimated_cost", "direct_cost")
        if est is not None:
            avg_est = est.dropna().mean()
            if avg_est and avg_est > 0:
                sev = min(1.0, max(0.0, avg_est / 15_000))
                scenarios["HIGH_TRANSPORT"] = float(sev)

    # ── 5. 재주문 위험 ───────────────────────────────────
    if "reorder_status" in df.columns:
        crisis_rate = df["reorder_status"].isin(["CRITICAL", "WARNING"]).mean()
        scenarios["REORDER_RISK"] = float(min(1.0, crisis_rate * 2))
    elif "safety_stock_score" in df.columns:
        low_ss = (pd.to_numeric(df["safety_stock_score"], errors="coerce") < 40).mean()
        scenarios["REORDER_RISK"] = float(min(1.0, low_ss * 1.5))

    # ── 6. 복합 스트레스 ─────────────────────────────────
    active = sum(1 for v in scenarios.values() if v > 0.30)
    if active >= 3:
        scenarios["STRESS"] = float(min(1.0, active / 5.0))

    return scenarios


# ──────────────────────────────────────────────────────────
def adjust_weights_by_scenario(scenarios: dict) -> dict:
    """
    detect_scenario() 결과를 받아 VHS 가중치 자동 재배분.
    합계 = 1.0 유지.
    """
    w = dict(BASE_WEIGHTS_V2)

    # 유통기한 임박 → 재고위험·폐기회피 증가
    if scenarios.get("EXPIRY_URGENT", 0) > 0.20:
        s = scenarios["EXPIRY_URGENT"]
        w["재고위험"]     = min(0.42, w["재고위험"]     + s * 0.18)
        w["폐기회피이익"] = min(0.22, w["폐기회피이익"] + s * 0.12)

    # 냉장/냉동 과잉 → 실행가능성·점포이동 증가
    if scenarios.get("COLD_EXCESS", 0) > 0.20:
        s = scenarios["COLD_EXCESS"]
        w["실행가능성"]   = min(0.25, w["실행가능성"]   + s * 0.12)
        w["점포이동적합"] = min(0.25, w["점포이동적합"] + s * 0.08)

    # 수요 급증 → 판매가능성·점포이동 증가
    if scenarios.get("DEMAND_SURGE", 0) > 0.20:
        s = scenarios["DEMAND_SURGE"]
        w["판매가능성"]   = min(0.35, w["판매가능성"]   + s * 0.14)
        w["점포이동적합"] = min(0.25, w["점포이동적합"] + s * 0.06)

    # 배송비 상승 → 비용절감 증가
    if scenarios.get("HIGH_TRANSPORT", 0) > 0.20:
        s = scenarios["HIGH_TRANSPORT"]
        w["비용절감"]     = min(0.28, w["비용절감"]     + s * 0.14)

    # 재주문 위험 → 점포이동적합·판매가능성 증가
    if scenarios.get("REORDER_RISK", 0) > 0.20:
        s = scenarios["REORDER_RISK"]
        w["점포이동적합"] = min(0.28, w["점포이동적합"] + s * 0.12)
        w["판매가능성"]   = min(0.30, w["판매가능성"]   + s * 0.06)

    # 복합 스트레스 → 균형 보정 (어느 하나가 40% 초과하면 깎음)
    if scenarios.get("STRESS", 0) > 0.50:
        for k in w:
            if w[k] > 0.38:
                w[k] = 0.38

    # 합계 1.0 정규화
    total = sum(w.values())
    return {k: round(v / total, 4) for k, v in w.items()}


def scenario_labels(scenarios: dict) -> list[str]:
    """상황 이름 → 한국어 레이블 리스트."""
    label_map = {
        "EXPIRY_URGENT":  "⏰ 유통기한 임박",
        "COLD_EXCESS":    "❄️ 냉장·냉동 과잉",
        "DEMAND_SURGE":   "📈 수요 급증",
        "HIGH_TRANSPORT": "💸 배송비 상승",
        "REORDER_RISK":   "🚨 재주문 위험",
        "STRESS":         "⚡ 복합 스트레스",
    }
    return [f"{label_map.get(k,k)} ({v:.0%})"
            for k, v in scenarios.items() if v > 0.15]
