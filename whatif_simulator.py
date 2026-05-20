"""
What-if 시뮬레이션 (What-if Simulation)
───────────────────────────────────────────────────────────
핵심 파라미터를 변경했을 때 추천 점수와 의사결정이
어떻게 달라지는지 시나리오별로 비교한다.

  시뮬레이션 파라미터
    discount_rate       : 할인율 (0~1) — 폐기 대신 할인 판매 시 단가 손실
    cost_multiplier     : 이동비용 배율 (0.5~2.0) — 운송비 변동 민감도
    demand_change_pct   : 수요 변동률 (%) — +20이면 수요 20% 증가
    service_level       : 서비스 수준 (0.90/0.95/0.99) — Safety Stock Z계수
    lead_time_change    : 리드타임 변동 (일) — +1이면 1일 추가

  출력
    scenario_df : 시나리오별 추천 건수·점수·비용 비교
    delta_df    : 파라미터별 민감도 (점수 변화량 / 파라미터 단위 변화)
    recommendation_df : 파라미터 변경 후 재계산된 추천 결과
"""

import numpy as np
import pandas as pd
import copy


# ─── 기본 시나리오 정의 ──────────────────────────────────
DEFAULT_PARAMS = {
    "discount_rate":     0.20,   # 20% 할인
    "cost_multiplier":   1.00,   # 이동비용 배율 100%
    "demand_change_pct": 0.00,   # 수요 변동 없음
    "service_level":     0.95,   # 95% 서비스 수준
    "lead_time_change":  0,      # 리드타임 변동 없음
}

PRESET_SCENARIOS = {
    "현재 기준 (Base)": {
        "discount_rate":     0.20,
        "cost_multiplier":   1.00,
        "demand_change_pct": 0.00,
        "service_level":     0.95,
        "lead_time_change":  0,
    },
    "낙관 시나리오 (Optimistic)": {
        "discount_rate":     0.10,   # 할인율 낮춤
        "cost_multiplier":   0.80,   # 이동비용 20% 절감
        "demand_change_pct": 15.0,   # 수요 15% 증가
        "service_level":     0.90,   # 서비스 수준 낮춤
        "lead_time_change":  -1,     # 리드타임 1일 단축
    },
    "비관 시나리오 (Pessimistic)": {
        "discount_rate":     0.35,   # 할인율 높임
        "cost_multiplier":   1.40,   # 이동비용 40% 증가
        "demand_change_pct": -15.0,  # 수요 15% 감소
        "service_level":     0.99,   # 서비스 수준 높임
        "lead_time_change":  2,      # 리드타임 2일 증가
    },
    "비용 절감 집중": {
        "discount_rate":     0.25,
        "cost_multiplier":   0.70,
        "demand_change_pct": 0.00,
        "service_level":     0.95,
        "lead_time_change":  0,
    },
    "재고 안전성 강화": {
        "discount_rate":     0.20,
        "cost_multiplier":   1.00,
        "demand_change_pct": 0.00,
        "service_level":     0.99,
        "lead_time_change":  1,
    },
}

_Z_MAP = {0.90: 1.28, 0.95: 1.65, 0.99: 2.33}


# ─── 파라미터 적용 함수들 ────────────────────────────────

def _apply_discount(df: pd.DataFrame, discount_rate: float) -> pd.DataFrame:
    """
    할인율 변경 → estimated_cost 재계산.
    estimated_cost = 이동비용 + 할인손실
    할인손실 = unit_cost × discount_rate × suggested_qty
    """
    out = df.copy()
    has_unit = "unit_cost" in out.columns or "state_unit_cost" in out.columns
    has_qty  = "suggested_qty" in out.columns

    if has_unit and has_qty:
        unit = pd.to_numeric(
            out.get("unit_cost", out.get("state_unit_cost", 0)), errors="coerce"
        ).fillna(0)
        qty = pd.to_numeric(out["suggested_qty"], errors="coerce").fillna(0)
        discount_loss = unit * discount_rate * qty

        if "direct_cost" in out.columns:
            transfer_cost = pd.to_numeric(out["direct_cost"], errors="coerce").fillna(0)
        else:
            transfer_cost = pd.to_numeric(
                out.get("estimated_cost", 0), errors="coerce"
            ).fillna(0) * 0.4

        out["estimated_cost_sim"] = (transfer_cost + discount_loss).round(0)
    else:
        out["estimated_cost_sim"] = pd.to_numeric(
            out.get("estimated_cost", 0), errors="coerce"
        ).fillna(0)

    return out


def _apply_cost_multiplier(df: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    """이동비용 배율 → heuristic_score의 비용 관련 항 조정."""
    out = df.copy()
    for col in ["direct_cost", "via_cost", "transport_cost", "transfer_cost"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0) * multiplier
    return out


def _apply_demand_change(df: pd.DataFrame, change_pct: float) -> pd.DataFrame:
    """수요 변동 → avg_daily_sales, demand_forecast_daily 재계산."""
    out = df.copy()
    factor = 1 + change_pct / 100.0
    for col in ["avg_daily_sales", "demand_forecast_daily",
                "demand_forecast_7d", "state_source_sales_30d", "sales_30d"]:
        if col in out.columns:
            out[col] = (
                pd.to_numeric(out[col], errors="coerce").fillna(0) * factor
            ).round(2)
    return out


def _apply_service_level(df: pd.DataFrame, service_level: float) -> pd.DataFrame:
    """서비스 수준 → safety_stock 재계산."""
    out = df.copy()
    z = _Z_MAP.get(service_level, 1.65)

    if "demand_std" in out.columns and "lead_time_days" in out.columns:
        d_std = pd.to_numeric(out["demand_std"], errors="coerce").fillna(0)
        lead  = pd.to_numeric(out["lead_time_days"], errors="coerce").fillna(3).clip(1)
        new_ss = (z * d_std * np.sqrt(lead)).round(1)
        if "safety_stock" in out.columns:
            out["safety_stock"] = new_ss
    return out


def _apply_lead_time(df: pd.DataFrame, lead_change: int) -> pd.DataFrame:
    """리드타임 변동 → safety_stock, reorder_point 재계산."""
    out = df.copy()
    if "lead_time_days" in out.columns:
        out["lead_time_days"] = (
            pd.to_numeric(out["lead_time_days"], errors="coerce").fillna(3) + lead_change
        ).clip(lower=1)
    return out


# ─── 점수 재계산 ──────────────────────────────────────────

def _recalc_heuristic_score(df: pd.DataFrame, params: dict) -> pd.Series:
    """
    파라미터 변경 후 heuristic_score 근사 재계산.
    기존 점수에서 비용·수요 변동에 따른 delta를 더함.
    """
    base = pd.to_numeric(df.get("heuristic_score", 50), errors="coerce").fillna(50)

    # 비용 배율 영향: 비용 증가 → 점수 하락
    cost_delta = -(params["cost_multiplier"] - 1.0) * 15

    # 수요 변동 영향: 수요 증가 → 점수 상승
    demand_delta = params["demand_change_pct"] * 0.3

    # 할인율 영향: 할인 높을수록 할인판매 이익 감소 → 미미한 영향
    discount_delta = -(params["discount_rate"] - 0.20) * 10

    # 서비스 수준 영향: 높을수록 안전재고 증가 → 비용 상승
    sl_delta = -(_Z_MAP.get(params["service_level"], 1.65) - 1.65) * 5

    # 리드타임 영향: 길수록 재주문점 증가 → 점수 하락
    lt_delta = -params["lead_time_change"] * 2

    total_delta = cost_delta + demand_delta + discount_delta + sl_delta + lt_delta
    return (base + total_delta).clip(0, 100).round(1)


# ─── 시나리오 실행 ────────────────────────────────────────

def run_scenario(
    df: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """
    단일 시나리오 파라미터 적용 후 DataFrame 반환.

    Parameters
    ----------
    df     : final_recommendations DataFrame
    params : dict with discount_rate, cost_multiplier, etc.

    Returns
    -------
    DataFrame with _sim suffix columns + heuristic_score_sim
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    out = _apply_demand_change(out, params.get("demand_change_pct", 0))
    out = _apply_lead_time(out, params.get("lead_time_change", 0))
    out = _apply_service_level(out, params.get("service_level", 0.95))
    out = _apply_cost_multiplier(out, params.get("cost_multiplier", 1.0))
    out = _apply_discount(out, params.get("discount_rate", 0.20))

    out["heuristic_score_sim"] = _recalc_heuristic_score(out, params)
    out["score_delta"] = (
        out["heuristic_score_sim"] -
        pd.to_numeric(df.get("heuristic_score", 50), errors="coerce").fillna(50)
    ).round(1)

    return out


# ─── 시나리오 비교 ────────────────────────────────────────

def compare_scenarios(
    df: pd.DataFrame,
    scenarios: dict = None,
) -> pd.DataFrame:
    """
    여러 시나리오를 한 번에 실행하고 비교 테이블 반환.

    Parameters
    ----------
    df        : original final_recommendations
    scenarios : {name: params_dict}, 없으면 PRESET_SCENARIOS 사용

    Returns
    -------
    pd.DataFrame : 시나리오 × 지표 비교 테이블
    """
    if df is None or df.empty:
        return pd.DataFrame()

    scenarios = scenarios or PRESET_SCENARIOS
    rows = []

    base_score = pd.to_numeric(df.get("heuristic_score", 50), errors="coerce").mean()
    base_cost  = pd.to_numeric(df.get("estimated_cost",  0), errors="coerce").sum()

    for name, params in scenarios.items():
        sim_df = run_scenario(df, params)

        avg_sim_score = sim_df["heuristic_score_sim"].mean()
        total_sim_cost = pd.to_numeric(
            sim_df.get("estimated_cost_sim", sim_df.get("estimated_cost", 0)),
            errors="coerce",
        ).sum()

        n_excellent = (sim_df["heuristic_score_sim"] >= 80).sum()
        n_good      = ((sim_df["heuristic_score_sim"] >= 60) & (sim_df["heuristic_score_sim"] < 80)).sum()

        rows.append({
            "시나리오":       name,
            "평균점수":       round(avg_sim_score, 1),
            "점수변화":       round(avg_sim_score - base_score, 1),
            "총이동비용(원)": int(total_sim_cost),
            "비용변화(원)":   int(total_sim_cost - base_cost),
            "우선추천(80+)":  int(n_excellent),
            "권장추천(60+)":  int(n_good),
            "할인율":         f"{params['discount_rate']*100:.0f}%",
            "비용배율":       f"{params['cost_multiplier']:.1f}×",
            "수요변동":       f"{params['demand_change_pct']:+.0f}%",
        })

    return pd.DataFrame(rows)


# ─── 민감도 분석 ──────────────────────────────────────────

def sensitivity_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 파라미터를 ±단위로 변동했을 때 평균 점수 변화 계산.
    Returns: 파라미터별 민감도 DataFrame
    """
    if df is None or df.empty:
        return pd.DataFrame()

    base_score = pd.to_numeric(
        df.get("heuristic_score", 50), errors="coerce"
    ).fillna(50).mean()

    tests = [
        ("할인율 +10%",    {**DEFAULT_PARAMS, "discount_rate":     0.30}),
        ("할인율 -10%",    {**DEFAULT_PARAMS, "discount_rate":     0.10}),
        ("이동비용 +20%",  {**DEFAULT_PARAMS, "cost_multiplier":   1.20}),
        ("이동비용 -20%",  {**DEFAULT_PARAMS, "cost_multiplier":   0.80}),
        ("수요 +15%",      {**DEFAULT_PARAMS, "demand_change_pct": 15.0}),
        ("수요 -15%",      {**DEFAULT_PARAMS, "demand_change_pct":-15.0}),
        ("서비스수준 99%", {**DEFAULT_PARAMS, "service_level":     0.99}),
        ("서비스수준 90%", {**DEFAULT_PARAMS, "service_level":     0.90}),
        ("리드타임 +2일",  {**DEFAULT_PARAMS, "lead_time_change":  2}),
        ("리드타임 -1일",  {**DEFAULT_PARAMS, "lead_time_change": -1}),
    ]

    rows = []
    for label, params in tests:
        sim_df     = run_scenario(df, params)
        sim_score  = sim_df["heuristic_score_sim"].mean()
        delta      = round(sim_score - base_score, 2)
        direction  = "▲ 유리" if delta > 0 else ("▼ 불리" if delta < 0 else "→ 변화없음")
        rows.append({
            "파라미터 변경": label,
            "평균점수 변화":  delta,
            "방향":          direction,
        })

    return pd.DataFrame(rows).sort_values("평균점수 변화", ascending=False).reset_index(drop=True)
