"""
varo_promotion.py
──────────────────
할인/프로모션 현실성 보완 모듈.

- 기존 promotion_analyzer.py / discount_analyzer.py 기능을 활용
- 카테고리별 할인 반응, 예상 판매 증가율, 프로모션 손익 계산
- 기존 Varo Hybrid Score / 최종 추천 미수정
"""

import math
import numpy as np
import pandas as pd

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 기본값 (한 곳에서 관리)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_default_promotion_config() -> dict:
    return {
        "default_discount_rate":         0.20,
        "emergency_discount_rate":        0.40,
        "one_plus_one_effective_discount":0.50,
        "default_promotion_cost":         5000.0,
        "min_margin_rate":                0.10,
        "markdown_response_low":          0.05,
        "markdown_response_medium":       0.15,
        "markdown_response_high":         0.30,
    }

_CFG = get_default_promotion_config()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _sn(value, default: float = 0.0) -> float:
    try:
        f = float(str(value).replace(",", "").replace("원", "").replace("%", "").strip())
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def _first(row, *names, default=None):
    for n in names:
        try:
            v = row.get(n) if hasattr(row, 'get') else None
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                return v
        except Exception:
            pass
    return default

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 카테고리별 할인 반응
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_CATEGORY_RESPONSE = {
    "높음": ["도시락", "김밥", "샌드위치", "간편식", "유제품", "디저트",
             "냉장", "신선", "흰우유", "요거트"],
    "보통": ["냉동", "음료", "빙과", "아이스크림", "즉석", "컵라면"],
    "낮음": ["과자", "가공식품", "생활용품", "비식품", "화장품", "의약"],
}

def get_default_promotion_response_by_category() -> dict:
    result = {}
    for level, keywords in _CATEGORY_RESPONSE.items():
        for kw in keywords:
            result[kw] = level
    return result

def infer_promotion_response_level(category: str) -> str:
    """카테고리 문자열 → 할인 반응 수준 (높음/보통/낮음)."""
    if not category or str(category).lower() in ("nan", "none", ""):
        return "보통"
    cat = str(category).lower()
    for level, keywords in _CATEGORY_RESPONSE.items():
        if any(kw.lower() in cat for kw in keywords):
            return level
    return "보통"

def get_expected_sales_lift(category: str, discount_rate: float,
                             demand_status: str = None) -> float:
    """
    할인율 + 카테고리 반응 + 수요 수준 → 예상 판매 증가율 (0~1).
    """
    dr   = max(0.0, min(1.0, _sn(discount_rate, 0.20)))
    resp = infer_promotion_response_level(str(category or ""))

    # 기본 증가율 테이블 (dr × 반응)
    base_lifts = {
        "낮음":  dr * 0.25,
        "보통":  dr * 0.60,
        "높음":  dr * 1.10,
    }
    lift = base_lifts.get(resp, dr * 0.60)

    # 수요 수준 보정
    if demand_status == "높음":    lift *= 1.20
    elif demand_status == "낮음":  lift *= 0.70

    return round(min(1.0, lift), 4)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 판매 예측
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def estimate_sales_lift(discount_rate: float, response_level: str,
                        demand_status: str = None) -> float:
    """할인율 + 반응 수준 → 판매 증가율."""
    return get_expected_sales_lift(response_level, discount_rate, demand_status)

def estimate_promotion_sales_qty(base_daily_demand: float, sales_lift: float,
                                  shelf_life_days: float, current_stock: float) -> float:
    """프로모션 기간 내 예상 판매 수량."""
    period  = max(1.0, min(_sn(shelf_life_days, 7), 30))
    lifted  = _sn(base_daily_demand, 1.0) * (1 + _sn(sales_lift, 0)) * period
    return round(min(_sn(current_stock, lifted), lifted), 1)

def estimate_remaining_stock_after_promotion(current_stock: float,
                                              expected_sales_qty: float) -> float:
    return max(0.0, round(_sn(current_stock, 0) - _sn(expected_sales_qty, 0), 1))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 프로모션 손익 계산
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_promotion_pnl(row, cfg: dict = None) -> dict:
    """
    단일 행에 대한 프로모션 손익 계산.
    반환: promotion_* 컬럼 dict
    """
    cfg = cfg or _CFG
    out = {}

    # ── 기본값 파싱 ──────────────────────────────────────
    unit_price  = _sn(_first(row, "unit_price"), 0)
    unit_cost   = _sn(_first(row, "unit_cost", "state_unit_cost"), 0)
    stock       = _sn(_first(row, "suggested_qty", "stock_qty", "current_stock",
                              "dead_stock_qty"), 0)
    disp_cost   = _sn(_first(row, "disposal_cost_per_unit", "disposal_cost"), 0)
    category    = str(_first(row, "category", "product_category") or "")
    shelf_life  = _sn(_first(row, "shelf_life_days", "expiry_days", "days_to_expiry"), 7)
    demand_st   = str(_first(row, "demand_status") or "")
    daily_dem   = _sn(_first(row, "expected_daily_demand", "avg_daily_sales"), 1.0)
    final_rec   = str(_first(row, "final_recommendation", "vhs2_action") or "")
    base_cost   = _sn(_first(row, "estimated_cost"), 0)

    # ── 추천 전략에 맞는 할인율 결정 ─────────────────────
    if "긴급" in final_rec:
        dr = cfg["emergency_discount_rate"]
        promo_type = "긴급 할인"
    elif "1+1" in final_rec or "one_plus" in final_rec.lower():
        dr = cfg["one_plus_one_effective_discount"]
        promo_type = "1+1 프로모션"
    elif any(k in final_rec for k in ["할인", "프로모션", "discount"]):
        dr = cfg["default_discount_rate"]
        promo_type = "할인 판매"
    else:
        dr = cfg["default_discount_rate"]
        promo_type = "할인 판매"

    out["promotion_type"]      = promo_type
    out["applied_discount_rate"] = round(dr, 4)

    # ── 가격이 없으면 unit_cost로 추정 ───────────────────
    if unit_price <= 0 and unit_cost > 0:
        unit_price = unit_cost * 1.25  # 마진 25% 가정

    if unit_price <= 0 and stock <= 0:
        out.update({
            "expected_sales_lift": 0, "expected_promotion_sales_qty": 0,
            "expected_remaining_qty": 0, "discount_loss_cost": 0,
            "promotion_fixed_cost": 0, "avoided_disposal_cost": 0,
            "promotion_net_benefit": 0, "promotion_feasibility_score": 50.0,
            "promotion_status": "데이터 부족",
        })
        return out

    # ── 예상 판매 증가율 ─────────────────────────────────
    lift = get_expected_sales_lift(category, dr, demand_st)
    out["expected_sales_lift"] = round(lift, 4)

    # ── 예상 판매 수량 ────────────────────────────────────
    promo_sales = estimate_promotion_sales_qty(daily_dem, lift, shelf_life, stock)
    remaining   = estimate_remaining_stock_after_promotion(stock, promo_sales)
    out["expected_promotion_sales_qty"] = promo_sales
    out["expected_remaining_qty"]       = remaining

    # ── 비용 계산 ─────────────────────────────────────────
    # 할인 손실 = 할인율 × 단가 × 판매 수량
    discount_loss    = unit_price * dr * promo_sales
    promo_fixed      = _sn(_first(row, "promotion_fixed_cost"), cfg["default_promotion_cost"])
    # 폐기 회피 비용 = 폐기 감소 수량 × 폐기 단가
    # (기존 추천이 이동이었다면 이동 비용과 비교)
    disposal_per_u   = max(disp_cost, unit_cost * 0.10)  # 최소 원가의 10%
    prev_remaining   = stock   # 프로모션 없으면 전체 잔여
    avoided_disposal = max(0.0, (prev_remaining - remaining) * disposal_per_u)

    # 순 효과 = 폐기 회피 - 할인 손실 - 고정 비용
    net_benefit = avoided_disposal - discount_loss - promo_fixed
    out["discount_loss_cost"]    = round(discount_loss, 0)
    out["promotion_fixed_cost"]  = round(promo_fixed, 0)
    out["avoided_disposal_cost"] = round(avoided_disposal, 0)
    out["promotion_net_benefit"] = round(net_benefit, 0)

    # ── 실행 가능성 점수 (0~100) ─────────────────────────
    margin_ok = (unit_price * (1 - dr)) >= (unit_cost * (1 + cfg["min_margin_rate"]))
    resp      = infer_promotion_response_level(category)
    resp_score = {"높음": 80, "보통": 60, "낮음": 35}.get(resp, 50)
    net_score  = 60 + min(40, net_benefit / max(unit_cost, 1) * 10) if net_benefit > 0 \
                 else 60 + max(-40, net_benefit / max(unit_cost, 1) * 5)
    lift_score = min(100, lift * 150)
    feasibility = resp_score * 0.35 + net_score * 0.35 + lift_score * 0.30
    if not margin_ok:
        feasibility *= 0.7

    feasibility = round(max(0, min(100, feasibility)), 1)
    out["promotion_feasibility_score"] = feasibility

    # ── 상태 분류 ─────────────────────────────────────────
    if net_benefit > 0 and feasibility >= 65:
        status = "유리"
    elif feasibility >= 50 or net_benefit >= 0:
        status = "보통"
    elif net_benefit < 0 and feasibility < 40:
        status = "비추천"
    else:
        status = "보통"

    # 유통기한 임박 + 수요 높음 → 긴급 할인 → 상태 강화
    if shelf_life <= 5 and demand_st == "높음" and "긴급" in promo_type:
        status = "유리"

    out["promotion_status"] = status
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. DataFrame 전체에 프로모션 피처 추가
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PROMO_COLS = [
    "promotion_type", "applied_discount_rate", "expected_sales_lift",
    "expected_promotion_sales_qty", "expected_remaining_qty",
    "discount_loss_cost", "promotion_fixed_cost", "avoided_disposal_cost",
    "promotion_net_benefit", "promotion_feasibility_score", "promotion_status",
]

def add_promotion_features(
    df: pd.DataFrame,
    products_df: pd.DataFrame = None,
    config_overrides: dict    = None,
) -> pd.DataFrame:
    """
    추천 후보 DataFrame에 프로모션 분석 컬럼 추가.
    기존 컬럼을 수정하지 않음.
    """
    if df is None or df.empty:
        return df

    cfg = {**_CFG, **(config_overrides or {})}
    out = df.copy()

    # products_df 조인 (unit_price, category, shelf_life_days, disposal_cost_per_unit)
    if products_df is not None and not products_df.empty:
        prod_name_col = next(
            (c for c in products_df.columns if c.lower() in
             ("product_name","상품명","item_name","name","product")), None
        )
        if prod_name_col and "product_name" in out.columns:
            merge_src_cols = [c for c in ["unit_price","unit_cost","category",
                               "shelf_life_days","disposal_cost_per_unit"]
                              if c in products_df.columns and c not in out.columns]
            if merge_src_cols:
                p = products_df[[prod_name_col] + merge_src_cols].rename(
                    columns={prod_name_col: "product_name"}
                ).drop_duplicates("product_name")
                out = out.merge(p, on="product_name", how="left")

    # 행별 프로모션 계산
    rows_data = []
    for _, row in out.iterrows():
        try:
            pnl = calculate_promotion_pnl(row, cfg)
        except Exception:
            pnl = {c: ("데이터 부족" if c == "promotion_status" else 0)
                   for c in _PROMO_COLS}
        rows_data.append(pnl)

    pnl_df = pd.DataFrame(rows_data, index=out.index)
    for col in _PROMO_COLS:
        out[col] = pnl_df.get(col, "데이터 부족" if col == "promotion_status" else 0)

    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. 요약
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_promotion_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty or "promotion_status" not in df.columns:
        return {}
    vc = df["promotion_status"].value_counts().to_dict()
    net = pd.to_numeric(df.get("promotion_net_benefit", pd.Series()), errors="coerce")
    lift_mean = pd.to_numeric(df.get("expected_sales_lift", pd.Series()), errors="coerce")
    avoided   = pd.to_numeric(df.get("avoided_disposal_cost", pd.Series()), errors="coerce")
    return {
        "유리":          int(vc.get("유리", 0)),
        "보통":          int(vc.get("보통", 0)),
        "비추천":        int(vc.get("비추천", 0)),
        "데이터 부족":   int(vc.get("데이터 부족", 0)),
        "평균 판매증가율":f'{lift_mean.mean()*100:.1f}%' if not lift_mean.empty else "-",
        "총 순효과":      round(float(net.sum()), 0) if not net.empty else 0,
        "폐기회피비용 합":round(float(avoided.sum()), 0) if not avoided.empty else 0,
    }


def get_promotion_view_df(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "product_name":                   "상품명",
        "source_store":                   "점포",
        "promotion_type":                 "추천 전략",
        "applied_discount_rate":          "할인율",
        "expected_sales_lift":            "예상 판매 증가율",
        "expected_promotion_sales_qty":   "예상 판매 수량",
        "expected_remaining_qty":         "예상 잔여 수량",
        "promotion_net_benefit":          "프로모션 순효과",
        "promotion_status":               "프로모션 상태",
    }
    avail = [c for c in col_map if c in df.columns]
    view  = df[avail].rename(columns=col_map).copy()
    if "할인율" in view.columns:
        view["할인율"] = pd.to_numeric(view["할인율"], errors="coerce").apply(
            lambda x: f"{x:.0%}" if pd.notna(x) else "-"
        )
    if "예상 판매 증가율" in view.columns:
        view["예상 판매 증가율"] = pd.to_numeric(view["예상 판매 증가율"], errors="coerce").apply(
            lambda x: f"{x:.1%}" if pd.notna(x) else "-"
        )
    return view.reset_index(drop=True)
