"""
#17 할인 민감도 + #18 폐기 회피 이익 + #19 Newsvendor + #20 TOPSIS
──────────────────────────────────────────────────────────────────
17. 할인 민감도 (Discount Sensitivity)
    예상 판매 증가율 / 할인율 → 할인 효율 0~100
18. 폐기 회피 이익 (Disposal Avoidance Profit)
    예상 폐기비용 - 처리비용 → 절감 효과 0~100
19. Newsvendor Model
    과잉/부족 비용 균형으로 신선식품 적정 재고 수준 판단 0~100
20. TOPSIS 다기준 의사결정
    비용·위험·판매가능성·거리·실행가능성 동시 비교 → 최종 순위 0~100
"""
import numpy as np
import pandas as pd
try:
    from scipy.stats import norm
except ImportError:
    import math
    class norm:
        @staticmethod
        def cdf(x):
            return 0.5 * (1 + math.erf(float(x) / math.sqrt(2)))


def _s(s, d=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(d)

def _col(df, *names, default=0.0):
    for n in names:
        if n in df.columns:
            return _s(df[n], default)
    return pd.Series([default]*len(df), index=df.index)


# ──────────────────────────────────────────────
#  #17 할인 민감도
# ──────────────────────────────────────────────

def analyze_discount_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    # 할인율 (기본 20%)
    discount_rate = _col(out, "discount_rate", default=0.20).clip(0.05, 0.60)

    # 판매 증가율 추정: 가격탄력성 -1.5 가정 (편의점 탄력성 통상 -1.2~-2.0)
    price_elasticity = -1.5
    expected_increase = (-price_elasticity * discount_rate).clip(0, 1.5)

    # 할인 효율 = 판매 증가율 / 할인율 (높을수록 할인 효과 좋음)
    efficiency = (expected_increase / discount_rate.replace(0, 0.01)).clip(0, 5)

    # 0~100 정규화 (효율 1.5 = 100점 기준)
    discount_sensitivity_score = (efficiency / 5 * 100).clip(0, 100).round(1)

    out["expected_sales_increase_rate"] = expected_increase.round(3)
    out["discount_sensitivity_score"]   = discount_sensitivity_score
    return out


# ──────────────────────────────────────────────
#  #18 폐기 회피 이익
# ──────────────────────────────────────────────

def analyze_disposal_avoidance(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    unit_cost   = _col(out, "unit_cost", "state_unit_cost")
    qty         = _col(out, "suggested_qty", default=30)
    disposal_c  = _col(out, "disposal_cost_per_unit", default=0.0)
    transport_c = _col(out, "estimated_cost", default=0.0)

    # 폐기 예상 손실 = unit_cost × qty × 1.2 (처분비 포함) + disposal_cost × qty
    disposal_loss = (unit_cost * 1.2 + disposal_c) * qty

    # 처리 비용 = 이동/할인/프로모션 비용
    handling_cost = transport_c.clip(lower=0)

    # 폐기 회피 이익 = 손실 절감 - 처리 비용
    net_saving = (disposal_loss - handling_cost).clip(lower=0)

    # 0~100 정규화 (50,000원 절감 = 100점 기준)
    disposal_avoidance_profit = net_saving.round(0)
    disposal_avoidance_score  = (net_saving / 50_000 * 100).clip(0, 100).round(1)

    out["disposal_avoidance_profit"] = disposal_avoidance_profit
    out["disposal_avoidance_score"]  = disposal_avoidance_score
    return out


# ──────────────────────────────────────────────
#  #19 Newsvendor Model
# ──────────────────────────────────────────────
# Critical Ratio = Cu / (Cu + Co)
# Cu = shortage cost (기회손실), Co = overage cost (폐기손실)
# 최적 서비스수준 → 현재 재고가 그 수준에 얼마나 맞는지

_FRESH_CATS = {"신선", "유제품", "냉장", "냉동", "냉", "도시락", "샐러드", "우유"}

def analyze_newsvendor(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    unit_cost = _col(out, "unit_cost", "state_unit_cost")
    unit_price = (unit_cost * 1.5).clip(lower=1)   # 마진 50% 가정
    salvage    = (unit_cost * 0.2).clip(lower=0)    # 폐기 시 회수가 20%

    # Cu = 판매 기회손실 = price - cost
    cu = (unit_price - unit_cost).clip(lower=0)
    # Co = 과잉 재고 손실 = cost - salvage
    co = (unit_cost - salvage).clip(lower=0)

    # Critical Ratio
    safe_denom = (cu + co).replace(0, 1)
    critical_ratio = (cu / safe_denom).clip(0, 1)

    # 현재 서비스 수준 추정: safety_stock 기반
    if "safety_stock" in out.columns and "demand_std" in out.columns:
        d_std   = _s(out["demand_std"], 1.0).replace(0, 1)
        ss      = _s(out["safety_stock"], 0.0)
        current_z = (ss / d_std).clip(-3, 3)
        current_sl = pd.Series([float(norm.cdf(z)) for z in current_z], index=out.index)
    else:
        current_sl = pd.Series([0.5]*len(out), index=out.index)

    # 이상-현재 서비스수준 차이 → 재고 적정성 판단
    gap = (critical_ratio - current_sl).abs()
    newsvendor_score = ((1 - gap) * 100).clip(0, 100).round(1)

    # 신선식품 여부 (카테고리 기준)
    cat_col = next((c for c in ["category","inventory_category"] if c in out.columns), None)
    if cat_col:
        is_fresh = out[cat_col].fillna("").astype(str).apply(
            lambda c: any(k in c for k in _FRESH_CATS)
        )
    else:
        is_fresh = pd.Series([False]*len(out), index=out.index)

    out["newsvendor_critical_ratio"] = critical_ratio.round(3)
    out["newsvendor_optimal_sl"]     = critical_ratio.round(3)
    out["newsvendor_score"]          = newsvendor_score
    out["is_fresh_product"]          = is_fresh
    return out


# ──────────────────────────────────────────────
#  #20 TOPSIS 다기준 의사결정
# ──────────────────────────────────────────────

def analyze_topsis(df: pd.DataFrame) -> pd.DataFrame:
    """
    비용·폐기위험·판매가능성·거리·실행가능성 5개 기준으로 TOPSIS 순위 산출.
    모든 기준을 '높을수록 좋음' 방향으로 정규화 후 계산.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    # 기준 컬럼 수집 (없으면 50점 기본값)
    cost_score     = 100 - _col(out, "heuristic_score", default=50)   # 낮을수록 좋음 → 반전
    disposal_score = _col(out, "disposal_risk_score", default=50)
    demand_score   = _col(out, "demand_forecast_score", default=50)
    distance_raw   = _col(out, "state_distance_km", "direct_distance_km", default=5.0)
    distance_score = (1 - distance_raw / 20.0).clip(0, 1) * 100  # 가까울수록 높은 점수
    feasibility    = _col(out, "match_score", default=50)

    criteria = pd.DataFrame({
        "cost":        cost_score,
        "disposal":    disposal_score,
        "demand":      demand_score,
        "distance":    distance_score,
        "feasibility": feasibility,
    })

    # TOPSIS 계산
    # 1) 정규화
    norms = np.sqrt((criteria**2).sum())
    norms = norms.replace(0, 1)
    norm_m = criteria / norms

    # 2) 가중치 적용 (균등)
    weights = np.array([0.25, 0.25, 0.20, 0.15, 0.15])
    weighted = norm_m * weights

    # 3) 이상해·최악해
    ideal     = weighted.max()
    anti_ideal= weighted.min()

    # 4) 거리 계산
    d_pos = np.sqrt(((weighted - ideal)**2).sum(axis=1))
    d_neg = np.sqrt(((weighted - anti_ideal)**2).sum(axis=1))

    # 5) 성능 지수 (0~1)
    safe_denom = (d_pos + d_neg).replace(0, 1)
    topsis_ci  = d_neg / safe_denom

    out["topsis_score"] = (topsis_ci * 100).clip(0, 100).round(1)
    out["topsis_rank"]  = out["topsis_score"].rank(ascending=False, method="min").astype(int)

    return out
