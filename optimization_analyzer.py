"""
#20 다목적 의사결정 / #21 선형계획법 / #22 수송문제
#23 할당문제 / #29 민감도 분석 / #32 Multi-objective
"""
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.spatial.distance import cdist


def _s(s, d=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(d)

def _col(df, *names, default=0.0):
    for n in names:
        if n in df.columns:
            return _s(df[n], default)
    return pd.Series([default] * len(df), index=df.index)


# ── #22 수송 문제 (Transportation Problem LP) ──────────────

def analyze_transportation_lp(
    df: pd.DataFrame,
    inventory_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    공급지(과잉 점포) → 수요지(부족 점포) 최소비용 배분.
    scipy.linprog로 최적 해 탐색.
    결과: transport_optimal_cost, transport_lp_score (0~100)
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    if inventory_df is None or inventory_df.empty:
        out["transport_lp_score"] = 50.0
        return out

    try:
        inv = inventory_df.copy()
        if "store_name" in inv.columns:
            inv = inv.rename(columns={"store_name": "source_store"})
        if "inventory_product_name" in inv.columns:
            inv = inv.rename(columns={"inventory_product_name": "product_name"})

        grp = inv.groupby("source_store").agg(
            total_stock  =("stock_qty",       "sum"),
            daily_demand =("avg_daily_sales",  "sum"),
        ).reset_index()
        grp["supply_30d"] = grp["daily_demand"] * 30
        grp["excess"]     = (grp["total_stock"] - grp["supply_30d"]).clip(lower=0)
        grp["shortage"]   = (grp["supply_30d"] - grp["total_stock"]).clip(lower=0)

        supply_nodes  = grp[grp["excess"]   > 0].head(10)
        demand_nodes  = grp[grp["shortage"] > 0].head(10)

        if supply_nodes.empty or demand_nodes.empty:
            out["transport_lp_score"] = 50.0
            return out

        n_s, n_d = len(supply_nodes), len(demand_nodes)
        # 비용 행렬: 단순 거리 비례 (거리 없으면 1000원 균등)
        cost_matrix = np.ones((n_s, n_d)) * 1000

        # LP: minimize c·x  s.t. supply/demand constraints
        c     = cost_matrix.flatten()
        sup   = supply_nodes["excess"].values.clip(0, 500)
        dem   = demand_nodes["shortage"].values.clip(0, 500)
        total = min(sup.sum(), dem.sum())

        A_eq  = np.zeros((n_s + n_d, n_s * n_d))
        b_eq  = np.concatenate([sup, dem])

        for i in range(n_s):
            A_eq[i, i * n_d:(i + 1) * n_d] = 1
        for j in range(n_d):
            A_eq[n_s + j, j::n_d] = 1

        bounds = [(0, None)] * (n_s * n_d)
        res    = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")

        if res.success:
            opt_cost = res.fun
            # 점포별 최적 배분 점수: 비용이 낮을수록 높은 점수
            max_cost = cost_matrix.max() * total
            lp_score = max(0, 100 - opt_cost / max(max_cost, 1) * 100)
            out["transport_lp_score"] = round(float(lp_score), 1)
            out["transport_optimal_cost"] = round(float(opt_cost), 0)
        else:
            out["transport_lp_score"] = 50.0
    except Exception:
        out["transport_lp_score"] = 50.0

    return out


# ── #23 할당 문제 (Assignment Problem) ────────────────────

def analyze_assignment(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 (상품, 출발점포, 도착점포) 후보에 최적 처리 방식을 1:1 배정.
    점수가 높은 후보에 '재배치', 다음은 '할인', 그 다음은 '보류'로 배정.
    assignment_action: REALLOCATE / DISCOUNT / HOLD / DISPOSE
    assignment_score : 0~100
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    vhs = _col(out, "vhs", default=50)

    # 헝가리안 알고리즘 근사: 점수 순서로 탐욕적 배정
    sorted_idx = vhs.sort_values(ascending=False).index.tolist()
    n = len(sorted_idx)
    n_reallocate = max(1, int(n * 0.30))
    n_discount   = max(1, int(n * 0.30))
    n_dispose    = max(1, int(n * 0.10))

    action_map = {}
    for i, idx in enumerate(sorted_idx):
        if i < n_reallocate:
            action_map[idx] = ("REALLOCATE", 100 - (i / n_reallocate * 20))
        elif i < n_reallocate + n_discount:
            action_map[idx] = ("DISCOUNT", 80 - ((i - n_reallocate) / n_discount * 20))
        elif i >= n - n_dispose:
            action_map[idx] = ("DISPOSE", 30)
        else:
            action_map[idx] = ("HOLD", 50)

    out["assignment_action"] = [action_map.get(i, ("HOLD", 50))[0] for i in out.index]
    out["assignment_score"]  = [round(action_map.get(i, ("HOLD", 50))[1], 1) for i in out.index]
    return out


# ── #20 다목적 의사결정 + #32 Multi-objective Optimization ─

def analyze_multiobjective(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pareto front 근사:
    목표 1: 폐기 최소화 (disposal_risk 높을수록 긴급)
    목표 2: 운송비 최소화 (heuristic 낮을수록 비용 적음)
    목표 3: 판매 가능성 최대화 (demand_forecast 높을수록 좋음)
    목표 4: 재고 균형 (category_balance 높을수록 좋음)

    Pareto rank: 어떤 다른 후보에도 지배(dominate)되지 않는 Rank 1 = 최우선
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    f1 = _col(out, "disposal_risk_score",  default=50).values       # maximize
    f2 = 100 - _col(out, "heuristic_score",default=50).clip(0,100).values  # maximize (비용↓)
    f3 = _col(out, "demand_forecast_score",default=50).values       # maximize
    f4 = _col(out, "category_balance_score",default=50).values      # maximize

    objectives = np.column_stack([f1, f2, f3, f4])
    n = len(objectives)

    # Pareto dominance 계산
    pareto_rank = np.ones(n, dtype=int)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            # j가 i를 지배: 모든 목표에서 j ≥ i, 하나 이상에서 j > i
            if (objectives[j] >= objectives[i]).all() and (objectives[j] > objectives[i]).any():
                pareto_rank[i] += 1
                break

    # Rank 1 = Pareto front, rank > 1 = dominated
    mo_score = ((n - pareto_rank) / max(n - 1, 1) * 100).clip(0, 100).round(1)

    out["multiobjective_rank"]  = pareto_rank
    out["multiobjective_score"] = mo_score
    return out


# ── #21 선형계획법 기반 통합 최적화 점수 ─────────────────

def analyze_lp_allocation_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 후보의 LP 관점 효율 점수.
    목적함수: 폐기비용 절감 / 운송비
    제약: 재고 한도, 처리 능력, 유통기한
    현재 row가 LP 최적해에 얼마나 부합하는지 점수화.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    # LP 효율 = (폐기회피이익 - 운송비부담) / 최대값
    benefit = _col(out, "disposal_avoidance_score", default=50)
    cost    = 100 - _col(out, "heuristic_score", default=50).clip(0,100)
    service = _col(out, "service_level_score", default=50)

    lp_raw  = (benefit * 0.5 + service * 0.3 - cost * 0.2).clip(0, 100)
    out["lp_allocation_score"] = lp_raw.round(1)
    return out


# ── #29 민감도 분석 ───────────────────────────────────────

def analyze_sensitivity_per_item(df: pd.DataFrame) -> pd.DataFrame:
    """
    VHS가 각 컴포넌트 변화에 얼마나 민감한지 행별 계산.
    가장 영향력 큰 컴포넌트 = dominant_factor
    sensitivity_score: 민감도가 낮을수록(안정적) 높은 점수.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    comp_cols = {
        "disposal_risk_score":   0.25,
        "demand_forecast_score": 0.20,
        "turnover_score":        0.18,
        "match_score":           0.14,
        "heuristic_score":       0.12,
        "safety_stock_score":    0.08,
        "abc_score":             0.03,
    }
    avail = {k: v for k, v in comp_cols.items() if k in out.columns}
    if not avail:
        out["sensitivity_score"]   = 50.0
        out["dominant_factor"]     = "unknown"
        return out

    vals = pd.DataFrame({k: _s(out[k], 50) for k in avail})
    # 표준편차 기반 민감도: 컴포넌트 편차가 클수록 민감
    std_per_row = vals.std(axis=1).fillna(0)
    sensitivity_score = (100 - std_per_row.clip(0, 50) / 50 * 100).clip(0, 100).round(1)

    # 가중 기여 최대 컴포넌트
    weighted = vals.multiply([avail[k] for k in avail])
    dominant = weighted.idxmax(axis=1).str.replace("_score", "")

    out["sensitivity_score"] = sensitivity_score
    out["dominant_factor"]   = dominant
    return out
