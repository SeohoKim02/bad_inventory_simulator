"""
varo_weight_optimizer.py
─────────────────────────
Hybrid Score 자동 가중치 탐색 모듈.

- 기본 가중치 VHS와 자동 탐색 가중치 VHS 비교 (비교 모드)
- 기존 최종 추천을 덮어쓰지 않음
- Random Search → Grid Search fallback
- 다운로드 버튼 없음
"""

import math, random, itertools
import numpy as np
import pandas as pd

# ── 의존성 ────────────────────────────────────────────────
try:
    from varo_score_config import (
        normalize_weights, DEFAULT_VHS_WEIGHTS,
        assign_recommendation_grade, safe_number,
    )
    from varo_sensitivity import recalculate_scores_with_weights
except ImportError:
    def normalize_weights(w, _=None):
        t = sum(float(v) for v in w.values() if v >= 0)
        return {k: round(v/t,6) for k,v in w.items()} if t>0 else w
    DEFAULT_VHS_WEIGHTS = {
        "재고위험":0.25,"판매가능성":0.20,"점포이동적합":0.15,
        "비용절감":0.15,"폐기회피이익":0.10,"실행가능성":0.10,"이력보정":0.05,
    }
    def assign_recommendation_grade(s):
        s = float(s) if s else 0
        if s>=80: return "최적"
        if s>=65: return "권장"
        if s>=50: return "검토"
        return "보류"
    def safe_number(v, d=0.0):
        try:
            f = float(v)
            return d if (math.isnan(f) or math.isinf(f)) else f
        except: return d
    from varo_sensitivity import recalculate_scores_with_weights

COMPONENT_KEYS = list(DEFAULT_VHS_WEIGHTS.keys())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 가중치 샘플 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_random_weight_sets(
    component_names: list = None,
    n_trials: int = 100,
    seed: int = 42,
) -> list:
    """Dirichlet 분포로 랜덤 가중치 조합 생성."""
    rng   = np.random.default_rng(seed)
    names = component_names or COMPONENT_KEYS
    sets  = []
    for _ in range(n_trials):
        raw  = rng.dirichlet(np.ones(len(names)))
        sets.append(dict(zip(names, [round(float(v), 6) for v in raw])))
    return sets


def generate_grid_weight_sets(
    component_names: list = None,
    step: float = 0.10,
    max_sets: int = 500,
) -> list:
    """
    Grid 방식 가중치 조합 (합=1 조건).
    항목 수가 많으면 max_sets 초과 시 조기 종료.
    """
    names  = component_names or COMPONENT_KEYS
    n      = len(names)
    ticks  = [round(i * step, 2) for i in range(int(1/step)+1)]
    sets   = []
    for combo in itertools.product(ticks, repeat=n):
        if abs(sum(combo) - 1.0) < 1e-6:
            sets.append(dict(zip(names, combo)))
            if len(sets) >= max_sets:
                break
    return sets


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 목적함수 Objective(w) - 낮을수록 좋음
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _sn(v, d=0.0): return safe_number(v, d)

def evaluate_weight_set(df: pd.DataFrame, weights: dict, top_k: int = 5) -> dict:
    """
    특정 가중치로 점수 재계산 후 목적함수 값 반환.
    반환: {objective, total_cost, avg_confidence, zero_qty_count,
           avg_score, disposal_risk_count, optimization_score}
    """
    if df is None or df.empty:
        return {"objective": 1e9, "optimization_score": 0}

    try:
        scores = recalculate_scores_with_weights(df, weights)
    except Exception:
        scores = pd.Series([50.0]*len(df), index=df.index)

    top_idx = scores.nlargest(top_k).index

    # 비용
    cost_col = next((c for c in ["estimated_cost","opt_cost"] if c in df.columns), None)
    if cost_col:
        top_costs = pd.to_numeric(df.loc[top_idx, cost_col], errors="coerce").fillna(0)
        total_cost = float(top_costs.sum())
    else:
        total_cost = 0.0

    # 수량 0 페널티
    qty_col = next((c for c in ["suggested_qty","move_qty"] if c in df.columns), None)
    zero_qty = int((pd.to_numeric(df.loc[top_idx, qty_col], errors="coerce").fillna(0) <= 0).sum()) if qty_col else 0

    # 신뢰도
    if "confidence_score" in df.columns:
        avg_conf = float(pd.to_numeric(df.loc[top_idx,"confidence_score"], errors="coerce").mean())
    else:
        avg_conf = 50.0

    # 폐기 위험
    if "disposal_risk_score" in df.columns:
        disp_risk = int((pd.to_numeric(df.loc[top_idx,"disposal_risk_score"], errors="coerce").fillna(0) >= 70).sum())
    else:
        disp_risk = 0

    # 수요 낮음 페널티
    low_demand = int((df.loc[top_idx,"demand_status"] == "낮음").sum()) if "demand_status" in df.columns else 0

    # 프로모션 비추천 페널티
    promo_bad = int((df.loc[top_idx,"promotion_status"] == "비추천").sum()) if "promotion_status" in df.columns else 0

    # 폐기 회피 효과 (이득)
    if "avoided_disposal_cost" in df.columns:
        avoided = float(pd.to_numeric(df.loc[top_idx,"avoided_disposal_cost"], errors="coerce").fillna(0).sum())
    else:
        avoided = 0.0

    # 목적함수 = 비용 + 패널티 - 이익
    objective = (
        total_cost * 0.5
        + zero_qty   * 5000
        + disp_risk  * 3000
        + low_demand * 2000
        + promo_bad  * 1000
        - avg_conf   * 100
        - avoided    * 0.3
    )

    # 최적화 점수 (0~100, 높을수록 좋음)
    top_scores_mean = float(scores.loc[top_idx].mean()) if not scores.empty else 0
    opt_score = min(100.0, max(0.0, round(
        top_scores_mean * 0.4
        + (100 - zero_qty * 10) * 0.2
        + avg_conf * 0.2
        + (100 - min(promo_bad * 20, 100)) * 0.2
    , 1)))

    return {
        "objective":           round(objective, 2),
        "total_cost":          round(total_cost, 0),
        "avg_confidence":      round(avg_conf, 1),
        "avg_score":           round(top_scores_mean, 1),
        "zero_qty_count":      zero_qty,
        "disposal_risk_count": disp_risk,
        "optimization_score":  opt_score,
        "top5_retention":      None,  # 비교 시 채워짐
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 자동 가중치 탐색
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def optimize_hybrid_weights(
    recommendations_df: pd.DataFrame,
    method: str = "random",
    n_trials: int = 100,
    top_k: int = 5,
    seed: int = 42,
    max_candidates: int = 50,
) -> dict:
    """
    w* = argmin Objective(w),  Σwk=1, wk≥0

    반환: {
        best_weights, best_result, default_result,
        all_results_df, method_used, n_evaluated,
        status
    }
    """
    empty = {
        "best_weights": dict(DEFAULT_VHS_WEIGHTS),
        "best_result":  {"objective": 1e9, "optimization_score": 0},
        "default_result": {},
        "all_results_df": pd.DataFrame(),
        "method_used": method,
        "n_evaluated": 0,
        "status": "계산 불가",
    }

    if recommendations_df is None or recommendations_df.empty:
        empty["status"] = "데이터 없음"
        return empty

    # 후보 수 제한
    score_col = next((c for c in ["vhs2","heuristic_score"] if c in recommendations_df.columns), None)
    if score_col:
        df = recommendations_df.nlargest(max_candidates, score_col).reset_index(drop=True)
    else:
        df = recommendations_df.head(max_candidates).reset_index(drop=True)

    # 기본 가중치 결과 계산
    default_result = evaluate_weight_set(df, DEFAULT_VHS_WEIGHTS, top_k)

    # 가중치 세트 생성
    try:
        if method == "grid":
            weight_sets = generate_grid_weight_sets(COMPONENT_KEYS, step=0.10)
        else:
            weight_sets = generate_random_weight_sets(COMPONENT_KEYS, n_trials, seed)
    except Exception:
        empty["default_result"] = default_result
        return empty

    if not weight_sets:
        empty["status"] = "가중치 세트 생성 실패"
        return empty

    # 평가
    rows = []
    best_obj  = float("inf")
    best_w    = dict(DEFAULT_VHS_WEIGHTS)
    best_res  = default_result

    for i, w in enumerate(weight_sets):
        try:
            res = evaluate_weight_set(df, w, top_k)
            rows.append({
                "trial":              i + 1,
                "objective_value":    res["objective"],
                "optimization_score": res["optimization_score"],
                "total_cost":         res["total_cost"],
                "avg_confidence":     res["avg_confidence"],
                "avg_score":          res["avg_score"],
                "zero_qty_count":     res["zero_qty_count"],
                "weights_summary":    ", ".join(f"{k[:4]}:{v:.2f}" for k,v in list(w.items())[:4]),
            })
            if res["objective"] < best_obj:
                best_obj = res["objective"]
                best_w   = w
                best_res = res
        except Exception:
            continue

    all_df = pd.DataFrame(rows).nsmallest(10, "objective_value").reset_index(drop=True) if rows else pd.DataFrame()

    return {
        "best_weights":     best_w,
        "best_result":      best_res,
        "default_result":   default_result,
        "all_results_df":   all_df,
        "method_used":      method,
        "n_evaluated":      len(rows),
        "status":           "완료",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 비교 테이블 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def build_weight_comparison_table(default_w: dict, best_w: dict) -> pd.DataFrame:
    """가중치 항목별 기본 vs 자동 비교표."""
    rows = []
    all_keys = list(dict.fromkeys(list(default_w.keys()) + list(best_w.keys())))
    for k in all_keys:
        dv = safe_number(default_w.get(k, 0), 0)
        bv = safe_number(best_w.get(k, 0), 0)
        diff = round(bv - dv, 4)
        rows.append({
            "항목":      k,
            "기본 가중치": f"{dv:.2%}",
            "자동 가중치": f"{bv:.2%}",
            "변화":      f"{'+' if diff>0 else ''}{diff:.2%}",
        })
    return pd.DataFrame(rows)


def build_top_k_comparison(
    recommendations_df: pd.DataFrame,
    best_weights: dict,
    top_k: int = 5,
) -> pd.DataFrame:
    """기본 vs 자동 가중치 TOP K 후보 비교표."""
    if recommendations_df is None or recommendations_df.empty:
        return pd.DataFrame()

    try:
        default_scores = recalculate_scores_with_weights(recommendations_df, DEFAULT_VHS_WEIGHTS)
        best_scores    = recalculate_scores_with_weights(recommendations_df, best_weights)
    except Exception:
        return pd.DataFrame()

    df = recommendations_df.copy()
    df["_def_score"]  = default_scores
    df["_best_score"] = best_scores

    def_top   = df.nlargest(top_k, "_def_score").copy()
    best_top  = df.nlargest(top_k, "_best_score").copy()

    rows = []
    seen = set()

    for rank, (_, row) in enumerate(def_top.iterrows(), 1):
        key = f"{row.get('product_name','-')}|{row.get('source_store','-')}"
        in_best = key in [f"{r.get('product_name','-')}|{r.get('source_store','-')}"
                          for _, r in best_top.iterrows()]
        rows.append({
            "구분":        "기본" if not in_best else "공통",
            "순위":        rank,
            "상품명":      str(row.get("product_name", "-"))[:15],
            "보내는 점포": str(row.get("source_store", "-"))[:10],
            "받는 점포":   str(row.get("target_store", "-"))[:10],
            "추천 수량":   row.get("suggested_qty", "-"),
            "추천 전략":   str(row.get("final_recommendation","") or row.get("vhs2_action","") or "-")[:12],
            "기본 Score":  round(float(row.get("_def_score", 0)), 1),
            "자동 Score":  round(float(best_scores.loc[row.name]), 1) if row.name in best_scores.index else "-",
        })
        seen.add(key)

    for rank, (_, row) in enumerate(best_top.iterrows(), 1):
        key = f"{row.get('product_name','-')}|{row.get('source_store','-')}"
        if key not in seen:
            rows.append({
                "구분": "자동",
                "순위": rank,
                "상품명": str(row.get("product_name","-"))[:15],
                "보내는 점포": str(row.get("source_store","-"))[:10],
                "받는 점포":   str(row.get("target_store","-"))[:10],
                "추천 수량":   row.get("suggested_qty", "-"),
                "추천 전략":   str(row.get("final_recommendation","") or row.get("vhs2_action","") or "-")[:12],
                "기본 Score":  round(float(default_scores.loc[row.name]), 1) if row.name in default_scores.index else "-",
                "자동 Score":  round(float(row.get("_best_score", 0)), 1),
            })

    return pd.DataFrame(rows).sort_values(["구분","순위"], ignore_index=True)


def build_weight_optimization_report(opt_result: dict) -> dict:
    """검증 리포트 연결용 요약 dict."""
    if not opt_result or opt_result.get("status") != "완료":
        return {"weight_optimization_status": opt_result.get("status","계산 불가")}

    def_obj = safe_number(opt_result["default_result"].get("objective"), 1e9)
    best_obj = safe_number(opt_result["best_result"].get("objective"), 1e9)
    impr = round((def_obj - best_obj) / max(abs(def_obj), 1) * 100, 2) if def_obj != 0 else 0

    return {
        "weight_optimization_status": "완료",
        "best_objective_value":       round(best_obj, 2),
        "default_objective_value":    round(def_obj, 2),
        "improvement_rate":           f"{impr:.1f}%",
        "optimized_avg_confidence":   opt_result["best_result"].get("avg_confidence", 0),
        "optimized_total_cost":       opt_result["best_result"].get("total_cost", 0),
        "n_evaluated":                opt_result.get("n_evaluated", 0),
    }
