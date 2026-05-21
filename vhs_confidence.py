"""
vhs_confidence.py — VHS 추천 신뢰도 등급
────────────────────────────────────────────
신뢰도 기준:
  데이터 충실도  (결측치 적음, 핵심 컬럼 존재)
  알고리즘 일치도 (여러 알고리즘이 같은 방향)
  이력 보정 안정성 (DQN 보정값이 과도하지 않음)

등급: HIGH / MEDIUM / LOW
"""
import numpy as np
import pandas as pd


_KEY_COLS = ["disposal_risk_score","demand_forecast_score","turnover_score",
             "match_score","safety_stock_score"]
_NICE_COLS = ["sales_7d","sales_30d","avg_daily_sales",
              "expiry_days","days_to_expiry","demand_std"]


def _miss_rate(row: pd.Series, cols: list) -> float:
    missing = sum(1 for c in cols if c not in row.index or pd.isna(row.get(c)))
    return missing / max(len(cols), 1)


def _algo_agreement(row: pd.Series) -> float:
    """핵심 알고리즘 점수들이 같은 방향(모두 높거나 모두 낮으면 일치율 높음)."""
    vals = []
    for c in _KEY_COLS:
        v = row.get(c)
        if v is not None and not pd.isna(v):
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if len(vals) < 2:
        return 0.5
    std = float(np.std(vals))
    # 표준편차 낮을수록 일치 → 0~50std를 0~1 반전
    return float(max(0.0, 1.0 - std / 50.0))


def calc_confidence(row: pd.Series) -> str:
    """
    행(row) 하나에 대한 신뢰도 등급 반환.
    HIGH: 0.7+  MEDIUM: 0.4+  LOW: 미만
    """
    score = 0.0
    weight_sum = 0.0

    # ① 핵심 컬럼 결측 (가중치 40%)
    miss_key  = _miss_rate(row, _KEY_COLS)
    data_score = 1.0 - miss_key
    score      += data_score * 0.40
    weight_sum += 0.40

    # ② 보조 데이터 존재 (가중치 20%)
    miss_nice   = _miss_rate(row, _NICE_COLS)
    nice_score  = 1.0 - miss_nice
    score      += nice_score * 0.20
    weight_sum += 0.20

    # ③ 알고리즘 일치도 (가중치 25%)
    agree  = _algo_agreement(row)
    score += agree * 0.25
    weight_sum += 0.25

    # ④ 이력 보정 안정성 (가중치 15%)
    dqn_corr = abs(float(row.get("vhs2_history_correction", 0) or 0))
    stability = max(0.0, 1.0 - dqn_corr / 8.0)
    score    += stability * 0.15
    weight_sum += 0.15

    confidence = score / max(weight_sum, 1e-9)

    if confidence >= 0.68:
        return "HIGH"
    if confidence >= 0.42:
        return "MEDIUM"
    return "LOW"


_CONF_LABEL = {
    "HIGH":   "신뢰도 높음 ●",
    "MEDIUM": "신뢰도 보통 ◑",
    "LOW":    "신뢰도 낮음 ○",
}
_CONF_COLOR = {"HIGH": "#2e7d32", "MEDIUM": "#f9a825", "LOW": "#c62828"}


def add_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame 전체에 vhs2_confidence 컬럼 추가."""
    if df is None or df.empty:
        return df
    out = df.copy()
    out["vhs2_confidence"]       = out.apply(calc_confidence, axis=1)
    out["vhs2_confidence_label"] = out["vhs2_confidence"].map(_CONF_LABEL)
    out["vhs2_confidence_color"] = out["vhs2_confidence"].map(_CONF_COLOR)
    # 나중에 신뢰구간으로 확장할 수 있는 자리 (현재 None)
    out["vhs2_ci_lower"] = None
    out["vhs2_ci_upper"] = None
    return out
