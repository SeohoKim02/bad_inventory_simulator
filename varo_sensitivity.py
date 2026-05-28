"""
varo_sensitivity.py
────────────────────
Varo Hybrid Score 민감도 분석 모듈.

- 기존 추천 결과를 덮어쓰지 않고 별도 DataFrame 생성
- vhs2_group_* 컬럼을 이용해 가중치 재조합 (알고리즘 재실행 불필요)
- 6개 preset 시나리오 + 사용자 설정 시나리오 지원
"""

import math
import numpy as np
import pandas as pd

# ── 의존성 ────────────────────────────────────────────────
try:
    from varo_score_config import (
        normalize_weights, safe_number, assign_recommendation_grade,
        DEFAULT_VHS_WEIGHTS,
    )
except ImportError:
    def normalize_weights(w, _=None):
        t = sum(float(v) for v in w.values() if v >= 0)
        return {k: round(v/t, 6) for k, v in w.items()} if t > 0 else w
    def safe_number(v, d=0.0):
        try:
            f = float(v)
            return d if (math.isnan(f) or math.isinf(f)) else f
        except: return d
    def assign_recommendation_grade(s):
        s = safe_number(s, 50)
        if s >= 80: return "최적"
        if s >= 65: return "권장"
        if s >= 50: return "검토"
        return "보류"
    DEFAULT_VHS_WEIGHTS = {
        "재고위험":0.25,"판매가능성":0.20,"점포이동적합":0.15,
        "비용절감":0.15,"폐기회피이익":0.10,"실행가능성":0.10,"이력보정":0.05,
    }

# ── VHS 그룹 컬럼명 ───────────────────────────────────────
GROUP_COL = {
    "재고위험":     "vhs2_group_재고위험",
    "판매가능성":   "vhs2_group_판매가능성",
    "점포이동적합": "vhs2_group_점포이동적합",
    "비용절감":     "vhs2_group_비용절감",
    "폐기회피이익": "vhs2_group_폐기회피이익",
    "실행가능성":   "vhs2_group_실행가능성",
}
HIST_COL = "vhs2_history_correction"  # 이력 보정 컬럼

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 가중치 시나리오 정의
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PRESET_SCENARIOS: dict = {
    "기본": {
        "재고위험":0.25,"판매가능성":0.20,"점포이동적합":0.15,
        "비용절감":0.15,"폐기회피이익":0.10,"실행가능성":0.10,"이력보정":0.05,
    },
    "비용 중시": {
        "재고위험":0.20,"판매가능성":0.15,"점포이동적합":0.15,
        "비용절감":0.30,"폐기회피이익":0.10,"실행가능성":0.05,"이력보정":0.05,
    },
    "폐기 최소화": {
        "재고위험":0.20,"판매가능성":0.15,"점포이동적합":0.15,
        "비용절감":0.10,"폐기회피이익":0.30,"실행가능성":0.05,"이력보정":0.05,
    },
    "재고 위험 우선": {
        "재고위험":0.35,"판매가능성":0.15,"점포이동적합":0.10,
        "비용절감":0.15,"폐기회피이익":0.15,"실행가능성":0.05,"이력보정":0.05,
    },
    "이동 효율 중시": {
        "재고위험":0.20,"판매가능성":0.15,"점포이동적합":0.20,
        "비용절감":0.10,"폐기회피이익":0.05,"실행가능성":0.25,"이력보정":0.05,
    },
    "모델 일치 중시": {
        "재고위험":0.20,"판매가능성":0.15,"점포이동적합":0.15,
        "비용절감":0.15,"폐기회피이익":0.10,"실행가능성":0.10,"이력보정":0.15,
    },
}

def get_sensitivity_weight_scenarios(user_weights: dict = None) -> dict:
    """
    preset 시나리오 반환.
    user_weights가 있으면 '사용자 설정' 시나리오도 포함.
    모든 시나리오 가중치는 합계 1.0 정규화.
    """
    scenarios = {k: normalize_weights(dict(v)) for k, v in _PRESET_SCENARIOS.items()}
    if user_weights and isinstance(user_weights, dict):
        try:
            nw = normalize_weights(user_weights)
            if abs(sum(nw.values()) - 1.0) < 0.05:
                scenarios["사용자 설정"] = nw
        except Exception:
            pass
    return scenarios


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 가중치 재적용 점수 계산
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def recalculate_scores_with_weights(df: pd.DataFrame, weights: dict) -> pd.Series:
    """
    vhs2_group_* 컬럼 + 가중치로 점수 재계산.
    이력 보정 컬럼 있으면 포함.
    반환: 0~100 점수 Series.
    """
    raw = pd.Series(0.0, index=df.index)
    w_sum = 0.0

    for gname, gcol in GROUP_COL.items():
        w = safe_number(weights.get(gname, 0.0), 0.0)
        if w <= 0:
            continue
        if gcol in df.columns:
            scores = pd.to_numeric(df[gcol], errors="coerce").fillna(50.0)
        else:
            scores = pd.Series(50.0, index=df.index)
        raw   += scores * w
        w_sum += w

    if w_sum > 0:
        raw = raw / w_sum * (1.0 - safe_number(weights.get("이력보정", 0.05), 0.0))

    # 이력 보정
    hist_w = safe_number(weights.get("이력보정", 0.05), 0.0)
    if HIST_COL in df.columns and hist_w > 0:
        hist = pd.to_numeric(df[HIST_COL], errors="coerce").fillna(0.0)
        raw  = raw + hist * (hist_w / 0.05)

    return raw.clip(0, 100).round(1)


def _get_strategy_col(df: pd.DataFrame) -> str:
    """전략 컬럼명 자동 감지."""
    for c in ["vhs2_action", "vhs_action", "final_recommendation", "추천 전략"]:
        if c in df.columns:
            return c
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 민감도 분석 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_hybrid_score_sensitivity_analysis(
    recommendations_df: pd.DataFrame,
    scenarios: dict = None,
    user_weights: dict = None,
) -> dict:
    """
    각 시나리오별 점수·등급·전략을 재계산하여 dict 반환.
    기존 DataFrame은 수정하지 않음.

    반환: {시나리오명: DataFrame (원본 + sens_score, sens_grade, sens_rank)}
    """
    if recommendations_df is None or recommendations_df.empty:
        return {}

    if scenarios is None:
        scenarios = get_sensitivity_weight_scenarios(user_weights)

    df = recommendations_df.copy()
    strat_col = _get_strategy_col(df)
    results = {}

    for sc_name, weights in scenarios.items():
        try:
            sc_df = df.copy()
            sc_df["sens_score"] = recalculate_scores_with_weights(sc_df, weights)
            sc_df["sens_grade"] = sc_df["sens_score"].apply(assign_recommendation_grade)
            sc_df["sens_rank"]  = sc_df["sens_score"].rank(ascending=False, method="min").astype(int)
            sc_df["scenario"]   = sc_name
            results[sc_name]    = sc_df
        except Exception:
            continue

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 요약 테이블 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def summarize_sensitivity_results(analysis_results: dict) -> pd.DataFrame:
    """시나리오별 요약 DataFrame."""
    if not analysis_results:
        return pd.DataFrame()

    rows = []
    base_top5 = None
    for sc_name, sc_df in analysis_results.items():
        if sc_df.empty:
            continue

        top5_ids = set(sc_df.nsmallest(5, "sens_rank").index.tolist())
        if sc_name == "기본":
            base_top5 = top5_ids

        strategy_col = _get_strategy_col(sc_df)
        strat_counts = {}
        if strategy_col:
            vc = sc_df[strategy_col].value_counts().to_dict()
            strat_counts = {str(k): v for k, v in vc.items()}

        top5_changed = 0
        if base_top5 is not None and sc_name != "기본":
            top5_changed = len(top5_ids.symmetric_difference(base_top5))

        rows.append({
            "시나리오":          sc_name,
            "평균 Score":        round(float(sc_df["sens_score"].mean()), 1),
            "최적":              int((sc_df["sens_grade"] == "최적").sum()),
            "권장":              int((sc_df["sens_grade"] == "권장").sum()),
            "검토":              int((sc_df["sens_grade"] == "검토").sum()),
            "보류":              int((sc_df["sens_grade"] == "보류").sum()),
            "TOP5 변경":         top5_changed,
        })

    return pd.DataFrame(rows)


def get_top5_by_scenario(analysis_results: dict) -> pd.DataFrame:
    """시나리오별 TOP 5 DataFrame."""
    if not analysis_results:
        return pd.DataFrame()

    frames = []
    for sc_name, sc_df in analysis_results.items():
        if sc_df.empty:
            continue
        top5 = sc_df.nsmallest(5, "sens_rank").copy()
        top5["시나리오"] = sc_name
        frames.append(top5)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # 표시 컬럼
    show_cols = {
        "시나리오":         "시나리오",
        "sens_rank":        "순위",
        "product_name":     "상품명",
        "source_store":     "보내는 점포",
        "target_store":     "받는 점포",
        "suggested_qty":    "추천 수량",
        "sens_score":       "Score",
        "sens_grade":       "등급",
    }
    strat_col = _get_strategy_col(combined)
    if strat_col:
        show_cols[strat_col] = "추천 전략"

    avail = [k for k in show_cols if k in combined.columns]
    view  = combined[avail].rename(columns=show_cols)
    return view.sort_values(["시나리오", "순위"], ignore_index=True)


def compare_top_recommendations_by_scenario(
    analysis_results: dict,
    base_scenario: str = "기본",
    compare_scenario: str = None,
) -> pd.DataFrame:
    """
    기준 시나리오 vs 비교 시나리오 순위 변화 테이블.
    compare_scenario=None이면 기본 외 첫 번째 시나리오와 비교.
    """
    if not analysis_results or base_scenario not in analysis_results:
        return pd.DataFrame()

    sc_names = list(analysis_results.keys())
    if compare_scenario is None:
        others = [s for s in sc_names if s != base_scenario]
        if not others:
            return pd.DataFrame()
        compare_scenario = others[0]

    if compare_scenario not in analysis_results:
        return pd.DataFrame()

    base_df = analysis_results[base_scenario].copy()
    comp_df = analysis_results[compare_scenario].copy()

    strat_col = _get_strategy_col(base_df)

    merge_keys = ["product_name", "source_store", "target_store"]
    avail_keys = [k for k in merge_keys if k in base_df.columns and k in comp_df.columns]
    if not avail_keys:
        return pd.DataFrame()

    base_df = base_df[avail_keys + ["sens_rank", "sens_grade"] +
                      ([strat_col] if strat_col else [])].copy()
    comp_df = comp_df[avail_keys + ["sens_rank", "sens_grade"] +
                      ([strat_col] if strat_col else [])].copy()

    merged = base_df.merge(comp_df, on=avail_keys, suffixes=("_기본", "_비교"))
    merged["순위 변화"] = (merged["sens_rank_기본"] - merged["sens_rank_비교"]).apply(
        lambda d: f"▲{abs(d)}" if d > 0 else (f"▼{abs(d)}" if d < 0 else "—")
    )
    if strat_col:
        merged["전략 변경"] = merged.apply(
            lambda r: "변경" if str(r.get(f"{strat_col}_기본","")) != str(r.get(f"{strat_col}_비교","")) else "유지",
            axis=1
        )

    # 컬럼 정리
    rename = {
        "product_name":           "상품명",
        "source_store":           "보내는 점포",
        "target_store":           "받는 점포",
        "sens_rank_기본":         f"{base_scenario} 순위",
        "sens_rank_비교":         f"{compare_scenario} 순위",
        "순위 변화":               "순위 변화",
        "sens_grade_기본":        f"{base_scenario} 등급",
        "sens_grade_비교":        f"{compare_scenario} 등급",
    }
    if strat_col:
        rename[f"{strat_col}_기본"] = f"{base_scenario} 전략"
        rename[f"{strat_col}_비교"] = f"{compare_scenario} 전략"
        rename["전략 변경"]         = "전략 변경"

    final_cols = [c for c in rename if c in merged.columns]
    return merged[final_cols].rename(columns=rename).sort_values(f"{base_scenario} 순위", ignore_index=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 순위 안정성 검증 (민감도 분석 기반)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_candidate_key(row) -> str:
    """후보 식별 키 생성 (product_name + source_store + target_store)."""
    parts = [
        str(row.get("product_name", "") or ""),
        str(row.get("source_store",  "") or ""),
        str(row.get("target_store",  "") or ""),
    ]
    return "||".join(p.strip() for p in parts)


def _get_top_n_keys(df: pd.DataFrame, n: int) -> set:
    """sens_rank 기준 상위 N개 후보 키 집합."""
    if df is None or df.empty or "sens_rank" not in df.columns:
        return set()
    top = df.nsmallest(n, "sens_rank")
    return {build_candidate_key(row) for _, row in top.iterrows()}


def _key_to_rank(df: pd.DataFrame) -> dict:
    """후보 키 → sens_rank 매핑 dict."""
    if df is None or df.empty or "sens_rank" not in df.columns:
        return {}
    return {build_candidate_key(r): int(r["sens_rank"]) for _, r in df.iterrows()}


def _key_to_col(df: pd.DataFrame, col: str) -> dict:
    """후보 키 → 특정 컬럼 값 매핑."""
    if df is None or df.empty or col not in df.columns:
        return {}
    return {build_candidate_key(r): r[col] for _, r in df.iterrows()}


def calculate_top_n_retention(base_df: pd.DataFrame,
                               scenario_df: pd.DataFrame, n: int = 5) -> float:
    """TOP N 유지율 (0~1)."""
    base_keys = _get_top_n_keys(base_df, n)
    sc_keys   = _get_top_n_keys(scenario_df, n)
    if not base_keys:
        return 0.0
    common = base_keys & sc_keys
    return round(len(common) / len(base_keys), 4)


def calculate_rank_changes(base_df: pd.DataFrame,
                            scenario_df: pd.DataFrame) -> dict:
    """공통 후보의 순위 변화 통계."""
    base_ranks = _key_to_rank(base_df)
    sc_ranks   = _key_to_rank(scenario_df)
    common_keys = set(base_ranks) & set(sc_ranks)
    if not common_keys:
        return {"mean": 0.0, "max": 0, "count": 0}
    changes = [abs(base_ranks[k] - sc_ranks[k]) for k in common_keys]
    return {
        "mean":  round(float(np.mean(changes)),  2),
        "max":   int(max(changes)),
        "count": len(common_keys),
    }


def calculate_strategy_change_rate(base_df: pd.DataFrame,
                                    scenario_df: pd.DataFrame) -> float:
    """추천 전략 변경률 (0~1)."""
    strat_col = _get_strategy_col(base_df) or _get_strategy_col(scenario_df)
    if not strat_col:
        return 0.0
    base_strat = _key_to_col(base_df, strat_col)
    sc_strat   = _key_to_col(scenario_df, strat_col) if strat_col in (scenario_df.columns if scenario_df is not None else []) else {}
    common_keys = set(base_strat) & set(sc_strat)
    if not common_keys:
        return 0.0
    changed = sum(1 for k in common_keys if str(base_strat[k]) != str(sc_strat[k]))
    return round(changed / len(common_keys), 4)


def calculate_grade_change_rate(base_df: pd.DataFrame,
                                 scenario_df: pd.DataFrame) -> float:
    """추천 등급 변경률 (0~1)."""
    col = "sens_grade"
    base_grades = _key_to_col(base_df, col)
    sc_grades   = _key_to_col(scenario_df, col) if scenario_df is not None and col in scenario_df.columns else {}
    common_keys = set(base_grades) & set(sc_grades)
    if not common_keys:
        return 0.0
    changed = sum(1 for k in common_keys if str(base_grades[k]) != str(sc_grades[k]))
    return round(changed / len(common_keys), 4)


def calculate_score_change_summary(base_df: pd.DataFrame,
                                    scenario_df: pd.DataFrame) -> dict:
    """점수 변화 요약."""
    base_scores = _key_to_col(base_df, "sens_score")
    sc_scores   = _key_to_col(scenario_df, "sens_score") if scenario_df is not None and "sens_score" in scenario_df.columns else {}
    common_keys = set(base_scores) & set(sc_scores)
    if not common_keys:
        return {"mean_change": 0.0, "max_change": 0.0}
    changes = [abs(float(base_scores[k]) - float(sc_scores[k])) for k in common_keys]
    return {
        "mean_change": round(float(np.mean(changes)), 2),
        "max_change":  round(float(max(changes)),     2),
    }


def calculate_stability_score(metrics: dict) -> float:
    """
    순위 안정성 점수 0~100.
    StabilityScore = 0.35*Top5 + 0.20*Top1 + 0.20*RankChange + 0.15*Strategy + 0.10*Grade
    """
    # TOP 5 유지율 (0~1 → 0~100)
    top5  = float(metrics.get("top5_retention", 0)) * 100
    top1  = 100.0 if metrics.get("top1_retained", False) else 0.0

    # 순위 변화 점수: 변화 0 → 100, 변화 클수록 감소
    n_cand  = max(metrics.get("n_candidates", 1), 1)
    rchange = float(metrics.get("avg_rank_change", 0))
    rank_sc = max(0.0, 100.0 - (rchange / n_cand * 100))

    # 전략 일관성 (변경률이 낮을수록 높은 점수)
    strat_sc = (1.0 - float(metrics.get("strategy_change_rate", 0))) * 100
    grade_sc = (1.0 - float(metrics.get("grade_change_rate",    0))) * 100

    weights = {"top5": 0.35, "top1": 0.20, "rank": 0.20, "strat": 0.15, "grade": 0.10}
    score = (weights["top5"]  * top5  +
             weights["top1"]  * top1  +
             weights["rank"]  * rank_sc +
             weights["strat"] * strat_sc +
             weights["grade"] * grade_sc)
    return round(min(100.0, max(0.0, score)), 1)


def assign_stability_level(score) -> str:
    """안정성 등급."""
    try:
        s = float(score)
        if s >= 80: return "안정"
        if s >= 60: return "보통"
        return "변동 큼"
    except: return "데이터 없음"


def build_sensitivity_stability_report(
    analysis_results: dict,
    base_scenario: str = "기본",
    top_n: int = 5,
) -> pd.DataFrame:
    """
    시나리오별 순위 안정성 요약 DataFrame.
    base_scenario와 각 비교 시나리오를 비교.
    """
    if not analysis_results or base_scenario not in analysis_results:
        return pd.DataFrame()

    base_df  = analysis_results[base_scenario]
    base_top1 = _get_top_n_keys(base_df, 1)

    rows = []
    for sc_name, sc_df in analysis_results.items():
        if sc_df is None or sc_df.empty:
            continue

        top5 = calculate_top_n_retention(base_df, sc_df, top_n)
        top1_retained = bool(_get_top_n_keys(sc_df, 1) & base_top1)
        rc   = calculate_rank_changes(base_df, sc_df)
        strat_cr = calculate_strategy_change_rate(base_df, sc_df)
        grade_cr = calculate_grade_change_rate(base_df, sc_df)
        score_ch = calculate_score_change_summary(base_df, sc_df)

        metrics = {
            "top5_retention":      top5,
            "top1_retained":       top1_retained,
            "avg_rank_change":     rc["mean"],
            "strategy_change_rate":strat_cr,
            "grade_change_rate":   grade_cr,
            "n_candidates":        len(base_df),
        }
        stab_score = calculate_stability_score(metrics)
        stab_level = assign_stability_level(stab_score)

        rows.append({
            "시나리오":       sc_name,
            "TOP5 유지율":   f"{top5:.0%}",
            "TOP1 유지":     "✅" if top1_retained else "❌",
            "평균 순위 변화":rc["mean"],
            "최대 순위 변화":rc["max"],
            "전략 변경률":   f"{strat_cr:.0%}",
            "등급 변경률":   f"{grade_cr:.0%}",
            "평균 점수 변화":score_ch["mean_change"],
            "안정성 점수":   stab_score,
            "안정성 등급":   stab_level,
        })

    return pd.DataFrame(rows)


def get_top_n_change_detail(
    analysis_results: dict,
    base_scenario: str = "기본",
    compare_scenario: str = None,
    n: int = 5,
) -> pd.DataFrame:
    """
    기본 vs 비교 시나리오 TOP N 후보 변화 상세표.
    """
    if not analysis_results or base_scenario not in analysis_results:
        return pd.DataFrame()

    sc_names = [s for s in analysis_results if s != base_scenario]
    if compare_scenario is None:
        compare_scenario = sc_names[0] if sc_names else None
    if compare_scenario not in analysis_results:
        return pd.DataFrame()

    base_df = analysis_results[base_scenario]
    comp_df = analysis_results[compare_scenario]
    if base_df is None or base_df.empty or comp_df is None or comp_df.empty:
        return pd.DataFrame()

    base_ranks  = _key_to_rank(base_df)
    comp_ranks  = _key_to_rank(comp_df)
    base_top_n  = _get_top_n_keys(base_df, n)
    comp_top_n  = _get_top_n_keys(comp_df, n)

    strat_col_b = _get_strategy_col(base_df)
    strat_col_c = _get_strategy_col(comp_df)
    base_strat  = _key_to_col(base_df, strat_col_b) if strat_col_b else {}
    comp_strat  = _key_to_col(comp_df, strat_col_c) if strat_col_c else {}
    base_scores = _key_to_col(base_df, "sens_score")
    comp_scores = _key_to_col(comp_df, "sens_score")

    all_keys = base_top_n | comp_top_n
    rows = []
    for key in all_keys:
        parts = key.split("||")
        pname = parts[0] if len(parts) > 0 else "-"
        sstor = parts[1] if len(parts) > 1 else "-"
        tstor = parts[2] if len(parts) > 2 else "-"
        b_rank = base_ranks.get(key)
        c_rank = comp_ranks.get(key)
        rank_diff = (b_rank - c_rank) if (b_rank and c_rank) else None

        if key in base_top_n and key in comp_top_n:
            if rank_diff and rank_diff > 0: state = "순위 하락"
            elif rank_diff and rank_diff < 0: state = "순위 상승"
            else: state = "유지"
        elif key in base_top_n:
            state = "TOP N 이탈"
        else:
            state = "신규 진입"

        rows.append({
            "시나리오":        compare_scenario,
            "상품명":          pname,
            "보내는 점포":     sstor,
            "받는 점포":       tstor,
            "기본 순위":       b_rank if b_rank else "-",
            "비교 순위":       c_rank if c_rank else "-",
            "순위 변화":       f"▲{abs(rank_diff)}" if rank_diff and rank_diff > 0
                               else (f"▼{abs(rank_diff)}" if rank_diff and rank_diff < 0 else "—"),
            "기본 전략":       str(base_strat.get(key, "-"))[:15],
            "비교 전략":       str(comp_strat.get(key, "-"))[:15],
            "기본 점수":       round(float(base_scores.get(key, 0)), 1),
            "비교 점수":       round(float(comp_scores.get(key, 0)), 1),
            "상태":            state,
        })

    return pd.DataFrame(rows).sort_values(
        ["상태", "기본 순위"], ascending=[True, True], ignore_index=True
    )


def get_stability_summary(stability_df: pd.DataFrame) -> dict:
    """안정성 보고 전체 요약."""
    if stability_df is None or stability_df.empty:
        return {}

    # TOP5 유지율 — 문자열 "80%" → float 0.8
    def _pct_to_float(s):
        try: return float(str(s).replace("%","").strip()) / 100
        except: return 0.0

    top5_vals = stability_df["TOP5 유지율"].apply(_pct_to_float)
    score_vals = pd.to_numeric(stability_df["안정성 점수"], errors="coerce")
    rank_vals  = pd.to_numeric(stability_df["평균 순위 변화"], errors="coerce")
    strat_vals = stability_df["전략 변경률"].apply(_pct_to_float)
    vc = stability_df["안정성 등급"].value_counts().to_dict()

    avg_score = round(float(score_vals.mean()), 1) if not score_vals.empty else 0
    overall   = assign_stability_level(avg_score)

    return {
        "avg_top5_retention":   round(float(top5_vals.mean()), 4),
        "avg_rank_change":      round(float(rank_vals.mean()),  2),
        "avg_stability_score":  avg_score,
        "avg_strategy_change":  round(float(strat_vals.mean()), 4),
        "overall_level":        overall,
        "grade_counts":         vc,
    }
