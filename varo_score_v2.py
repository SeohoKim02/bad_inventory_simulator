"""
varo_score_v2.py — VHS 7구성요소 통합 점수 (V2)
──────────────────────────────────────────────────
기존 varo_hybrid_score.py를 대체하지 않고,
run_all_algorithms() 결과 위에 새 구조로 덮어씁니다.

7개 구성요소:
  재고 위험      — disposal_risk, turnover, abc, aging
  판매 가능성    — demand_forecast, trend, newsvendor
  점포 이동 적합 — match, service_level, priority_queue, queue_capacity
  비용 절감      — heuristic(비용 낮을수록↑), transport_lp, eoq
  폐기 회피 이익 — disposal_avoidance, discount_sensitivity
  실행 가능성    — bottleneck, store_capacity, category_balance
  이력 보정      — DQN reward 기반 ±8점 보정

최종 VHS = 가중합 → percentile 정규화 → 0~100 전 범위 활용

새 컬럼:
  vhs2                    최종 VHS v2 점수 (0~100)
  vhs2_grade              등급 (최적/권장/검토)
  vhs2_action             추천 액션
  vhs2_confidence         신뢰도 등급
  vhs2_scenario_labels    감지 상황 레이블 목록
  vhs2_weights            적용된 가중치 dict (문자열)
  vhs2_group_*            각 구성요소 점수 (0~100)
"""
import numpy as np
import pandas as pd
from scenario_detector import detect_scenario, adjust_weights_by_scenario, scenario_labels

_INV = float("inf")


def _s(s, d=50.0):
    return pd.to_numeric(s, errors="coerce").fillna(d)


def _col(df, *names, default=50.0):
    for n in names:
        if n in df.columns:
            return _s(df[n], default)
    return pd.Series([default] * len(df), index=df.index)


# ── 구성요소별 알고리즘 매핑 ──────────────────────────────
# (컬럼명, 내부 가중치)
_GROUP_MAP = {
    "재고위험": [
        ("disposal_risk_score", 0.45),
        ("turnover_score",      0.30),
        ("abc_score",           0.15),
        ("aging_score",         0.10),
    ],
    "판매가능성": [
        ("demand_forecast_score", 0.50),
        ("trend_score",           0.30),
        ("newsvendor_score",      0.20),
    ],
    "점포이동적합": [
        ("match_score",          0.45),
        ("service_level_score",  0.25),
        ("priority_queue_score", 0.20),
        ("queue_capacity_score", 0.10),
    ],
    "비용절감": [
        ("heuristic_score",    0.55),   # 낮은 비용 = 높은 점수
        ("transport_lp_score", 0.30),
        ("eoq_score",          0.15),
    ],
    "폐기회피이익": [
        ("disposal_avoidance_score",  0.60),
        ("discount_sensitivity_score",0.40),
    ],
    "실행가능성": [
        ("bottleneck_score",       0.40),
        ("store_capacity_score",   0.40),
        ("category_balance_score", 0.20),
    ],
}

# 보조 지표 (VHS 계산에는 미포함, 화면 표시용)
_AUXILIARY_COLS = [
    "topsis_score","multiobjective_score","pareto_score",
    "assignment_score","lp_allocation_score",
    "substitute_conflict_score","relocation_failure_score",
    "sensitivity_score",
]

# 다기준 의사결정 통합 점수 = TOPSIS + 다목적 결합
def _combined_mcdm(df: pd.DataFrame) -> pd.Series:
    t = _col(df, "topsis_score",        default=50)
    m = _col(df, "multiobjective_score", default=50)
    return (t * 0.55 + m * 0.45).clip(0, 100).round(1)


# ── 그룹 점수 계산 ─────────────────────────────────────────
def _calc_group_scores(df: pd.DataFrame) -> pd.DataFrame:
    groups = {}
    for gname, algo_list in _GROUP_MAP.items():
        avail   = [(c, w) for c, w in algo_list if c in df.columns]
        if not avail:
            groups[gname] = pd.Series([50.0] * len(df), index=df.index)
            continue
        weight_sum = sum(w for _, w in avail)
        scores = sum(_s(df[c], 50.0) * (w / weight_sum) for c, w in avail)
        groups[gname] = scores.clip(0, 100)
    return pd.DataFrame(groups, index=df.index)


# ── DQN 이력 보정 ──────────────────────────────────────────
_DQN_MAX = 8.0

def _history_correction(df: pd.DataFrame) -> pd.Series:
    """reward 컬럼 기반 ±8점 이력 보정."""
    if "reward" not in df.columns:
        return pd.Series(0.0, index=df.index)
    r = pd.to_numeric(df["reward"], errors="coerce").fillna(0.0)
    r_max = r.abs().max()
    if r_max <= 0:
        return pd.Series(0.0, index=df.index)
    return (r / r_max * _DQN_MAX).clip(-_DQN_MAX, _DQN_MAX).round(2)


# ── 정규화 (Percentile) ────────────────────────────────────
def _normalize_to_range(series: pd.Series,
                         target_min=5.0, target_max=98.0) -> pd.Series:
    """
    순위 기반 정규화 → target_min ~ target_max 전 범위 활용.
    단일 항목이면 중앙값 50 반환.
    """
    n = len(series)
    if n <= 1:
        return pd.Series([50.0] * n, index=series.index)
    ranks = series.rank(method="average", na_option="keep")
    pct   = (ranks - 1) / (n - 1)         # 0 ~ 1
    return (pct * (target_max - target_min) + target_min).round(1)


# ── 액션 추천 ──────────────────────────────────────────────
def _recommend_action(row: pd.Series) -> str:
    disposal  = str(row.get("disposal_risk_grade",    "LOW"))
    turnover  = str(row.get("turnover_grade",         "NORMAL"))
    abc       = str(row.get("abc_grade",              "C"))
    match_g   = str(row.get("match_grade",            "FAIR"))
    reorder   = str(row.get("reorder_status",         "SAFE"))
    trend     = str(row.get("demand_trend",           "STABLE"))
    vhs2      = float(row.get("vhs2_raw",             50))
    g_inv     = float(row.get("vhs2_group_재고위험",   50))
    g_sale    = float(row.get("vhs2_group_판매가능성", 50))
    g_move    = float(row.get("vhs2_group_점포이동적합",50))

    # 폐기: 재고위험 높고 판매가능성·이동적합 낮음
    if (disposal in ("CRITICAL",) and turnover == "DEAD"
            and abc == "C" and g_sale < 35 and g_move < 35):
        return "폐기"

    # 재배치: 이동 적합 높고 목적지 수요 있음
    if (match_g in ("EXCELLENT","GOOD")
            and (reorder in ("CRITICAL","WARNING") or trend == "INCREASING")
            and g_move >= 55):
        return "재배치 이동"

    # 할인: 폐기위험 높거나 재고위험 높음
    if disposal in ("CRITICAL","HIGH") or turnover in ("SLOW","DEAD") or g_inv >= 65:
        return "할인 판매"

    return "보류"


_ACTION_ICON = {"재배치 이동":"🚚","할인 판매":"🏷️","폐기":"🗑️","보류":"⏸️"}


# ── 메인 함수 ──────────────────────────────────────────────
def calculate_vhs_v2(
    df: pd.DataFrame,
    inventory_df: pd.DataFrame = None,
    routes_df:    pd.DataFrame = None,
) -> pd.DataFrame:
    """
    기존 run_all_algorithms() 결과 DataFrame에
    VHS v2 컬럼들을 추가하여 반환.
    """
    if df is None or df.empty:
        return df

    out = df.copy()

    # 1. 상황 감지 + 가중치 결정
    scenarios = detect_scenario(out, inventory_df, routes_df)
    weights   = adjust_weights_by_scenario(scenarios)

    out["vhs2_scenario_labels"] = str(scenario_labels(scenarios))
    out["vhs2_weights"]         = str({k: f"{v:.1%}" for k, v in weights.items()})

    # 상황 플래그
    for sk in ["EXPIRY_URGENT","COLD_EXCESS","DEMAND_SURGE",
               "HIGH_TRANSPORT","REORDER_RISK","STRESS"]:
        out[f"sit2_{sk}"] = scenarios.get(sk, 0.0) > 0.25

    # 2. 구성요소 그룹 점수 계산
    group_df = _calc_group_scores(out)
    for gname in _GROUP_MAP:
        out[f"vhs2_group_{gname}"] = group_df[gname].round(1)

    # 3. 다기준 의사결정 통합 점수 (보조)
    out["mcdm_score"] = _combined_mcdm(out)

    # 4. 가중합 (Raw)
    raw = pd.Series(0.0, index=out.index)
    for gname, gw in weights.items():
        if gname == "이력보정":
            continue
        raw += group_df.get(gname, pd.Series(50.0, index=out.index)) * gw

    out["vhs2_raw"] = raw.round(1)

    # 5. 이력 보정 (DQN 기반, 명칭 변경)
    hist_corr = _history_correction(out)
    hist_w    = weights.get("이력보정", 0.05)
    # 이력 보정 = ±8 × 보정 가중치 비례
    correction = hist_corr * (hist_w / 0.05)
    out["vhs2_history_correction"] = correction.round(2)

    # 6. 최종 합산 전 percentile 정규화 → 0~100 전 범위 활용
    vhs_before_norm = (raw + correction).clip(0, 100)
    out["vhs2"] = _normalize_to_range(vhs_before_norm).clip(0, 100)

    # 7. 등급
    def _grade(s):
        if s >= 80: return "최적"
        if s >= 65: return "권장"
        return "검토"

    _grade_v = np.vectorize(_grade)
    out["vhs2_grade"] = _grade_v(out["vhs2"].values)

    # 8. 액션 추천
    # 핵심 컬럼만 뽑아서 vectorize (apply보다 2~5x 빠름)
    _vhs2_arr    = out.get("vhs2_raw", out["vhs2"]).values
    _g_inv       = out.get("vhs2_group_재고위험",   pd.Series(50.0, index=out.index)).values
    _g_sale      = out.get("vhs2_group_판매가능성", pd.Series(50.0, index=out.index)).values
    _g_move      = out.get("vhs2_group_점포이동적합",pd.Series(50.0, index=out.index)).values
    _disposal_g  = out.get("disposal_risk_grade",   pd.Series("NORMAL", index=out.index)).values
    _match_g     = out.get("match_grade",           pd.Series("FAIR",   index=out.index)).values
    _trend       = out.get("demand_trend",          pd.Series("STABLE", index=out.index)).values
    _reorder     = out.get("reorder_status",        pd.Series("SAFE",   index=out.index)).values

    def _action_fast(vhs, g_inv, g_sale, g_move, disp, match, trend, reorder):
        if str(disp)=="CRITICAL" and str(trend)!="INCREASING" and float(g_sale)<35 and float(g_move)<35:
            return "폐기"
        if str(match) in ("EXCELLENT","GOOD") and (str(reorder) in ("CRITICAL","WARNING") or str(trend)=="INCREASING") and float(g_move)>=55:
            return "재배치 이동"
        if str(disp) in ("CRITICAL","HIGH") or float(g_inv)>=65:
            return "할인 판매"
        return "보류"

    _action_v = np.vectorize(_action_fast)
    out["vhs2_action"] = _action_v(_vhs2_arr, _g_inv, _g_sale, _g_move,
                                    _disposal_g, _match_g, _trend, _reorder)
    out["vhs2_action_icon"] = out["vhs2_action"].map(_ACTION_ICON).fillna("⏸️")

    # 9. 순위
    out = out.sort_values("vhs2", ascending=False).reset_index(drop=True)
    out["vhs2_rank"] = out.index + 1

    return out


def get_vhs2_summary(df: pd.DataFrame) -> dict:
    """대시보드용 요약 통계."""
    if df is None or df.empty or "vhs2" not in df.columns:
        return {}
    return {
        "avg_vhs2":      round(df["vhs2"].mean(), 1),
        "top_product":   df.iloc[0].get("product_name","-") if len(df) else "-",
        "top_vhs2":      float(df.iloc[0].get("vhs2", 0)) if len(df) else 0,
        "top_action":    df.iloc[0].get("vhs2_action","-") if len(df) else "-",
        "action_counts": df["vhs2_action"].value_counts().to_dict(),
        "grade_counts":  df["vhs2_grade"].value_counts().to_dict(),
        "n_total":       len(df),
        "scenario_labels": df.iloc[0].get("vhs2_scenario_labels","") if len(df) else "",
    }
