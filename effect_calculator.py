"""
effect_calculator.py — Varo 도입 전/후 효과 지표
──────────────────────────────────────────────────
Before : 아무 조치 없이 기존 방식대로 방치했을 때 예상 폐기비용
After  : Varo 추천 적용 후 예상 폐기비용
→ 절감액, 절감률 등 Before/After 비교 지표 계산

계산식은 주석으로 명확히 남김.
"""
import numpy as np
import pandas as pd


def _s(s, d=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(d)

def _col(df, *names, d=0.0):
    for n in names:
        if n in df.columns:
            return _s(df[n], d)
    return pd.Series([d] * len(df), index=df.index)


def calc_effects(
    df:           pd.DataFrame,
    unit_cost_col: str = None,   # override
    qty_col:       str = None,
    disposal_rate_before: float = 0.35,  # 조치 없을 때 폐기 전환율 추정 35%
    disposal_rate_after:  float = 0.08,  # Varo 적용 후 폐기 전환율 추정 8%
) -> dict:
    """
    Before/After 효과 지표 계산.

    계산식:
      폐기비용 = unit_cost × qty × 폐기전환율 × 1.2 (처분비 포함)
      Before   : 폐기전환율 35% (업계 편의점 악성재고 폐기율 추정)
      After    : 폐기전환율  8% (Varo 최적 처리 기준)
      절감액   : Before - After
      절감률   : 절감액 / Before × 100%
    """
    if df is None or df.empty:
        return {}

    unit_cost = _col(df, unit_cost_col or "unit_cost",
                     "state_unit_cost", "unit_price")
    qty       = _col(df, qty_col or "suggested_qty",
                     "stock_qty", "state_source_stock", d=30.0)
    disposal_avoidance = _col(df, "disposal_avoidance_profit",
                               "disposal_avoidance_score", d=0.0)
    est_cost  = _col(df, "estimated_cost", "direct_cost", d=0.0)

    # ── 1. 예상 폐기비용 (Before) ────────────────────────
    # Before = 단가 × 수량 × 폐기전환율 × 1.2 (처분비 20% 포함)
    before_disposal_cost = (unit_cost * qty * disposal_rate_before * 1.2).sum()

    # ── 2. 예상 폐기비용 (After) ──────────────────────────
    # After  = 단가 × 수량 × 폐기전환율(after) × 1.2
    after_disposal_cost  = (unit_cost * qty * disposal_rate_after  * 1.2).sum()

    # ── 3. 절감액·절감률 ──────────────────────────────────
    saving_amount  = max(0.0, before_disposal_cost - after_disposal_cost)
    saving_rate    = saving_amount / max(before_disposal_cost, 1) * 100

    # ── 4. 처리 가능 재고 수량 ────────────────────────────
    # VHS 점수 기준 60점 이상 = 처리 가능
    vhs_col = "vhs2" if "vhs2" in df.columns else "vhs"
    vhs_s   = _col(df, vhs_col, d=0)
    processable_qty = qty[vhs_s >= 60].sum()

    # ── 5. 폐기 위험 감소 상품 수 ─────────────────────────
    # 폐기 위험 HIGH 이상인 상품이 Varo 적용 후 "보류"/"할인"으로 전환된 수
    action_col = "vhs2_action" if "vhs2_action" in df.columns else "vhs_action"
    if action_col in df.columns:
        n_reduced = (
            (df.get("disposal_risk_grade","") == "HIGH") &
            (~df[action_col].isin(["폐기"]))
        ).sum()
    else:
        n_reduced = int((vhs_s >= 55).sum())

    # ── 6. 재고 불균형 개선률 ────────────────────────────
    # 재배치 이동이 일어난 비율 → 불균형 개선 프록시
    if action_col in df.columns:
        n_reallocate = (df[action_col] == "재배치 이동").sum()
        rebalance_rate = n_reallocate / max(len(df), 1) * 100
    else:
        rebalance_rate = 0.0

    # ── 7. 운송비 부담률 ─────────────────────────────────
    # 총 운송비 / (단가 × 수량)
    total_inventory_value = (unit_cost * qty).sum()
    total_transport       = est_cost.sum()
    transport_burden_rate = (
        total_transport / max(total_inventory_value, 1) * 100
    )

    return {
        "before_disposal_cost":     round(before_disposal_cost, 0),
        "after_disposal_cost":      round(after_disposal_cost, 0),
        "saving_amount":            round(saving_amount, 0),
        "saving_rate_pct":          round(saving_rate, 1),
        "processable_qty":          round(processable_qty, 0),
        "n_risk_reduced":           int(n_reduced),
        "rebalance_rate_pct":       round(rebalance_rate, 1),
        "transport_burden_rate_pct":round(transport_burden_rate, 2),
        # 계산식 메모
        "_formula_before": f"단가 × 수량 × {disposal_rate_before:.0%} × 1.2",
        "_formula_after":  f"단가 × 수량 × {disposal_rate_after:.0%} × 1.2",
    }
