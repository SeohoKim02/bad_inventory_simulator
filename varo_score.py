"""
Varo 통합 점수 (Varo Unified Score)
───────────────────────────────────────────────────────────
휴리스틱(Greedy), DQN, 그리고 산업공학 알고리즘 결과를
'Varo 점수' 하나로 통합한다.

  목표: 개별 알고리즘 점수를 따로 보여주는 것이 아니라,
        Varo만의 단일 점수로 최종 우선순위를 결정한다.

  현재 구현 알고리즘 (단계적 확장)
    Phase 1 (현재)
      - 휴리스틱 점수   (heuristic_score)
      - ABC 등급        (abc_score)
      - 재고 회전율     (turnover_score)
      - 폐기 위험도     (disposal_risk_score)

    Phase 2 (예정 — 컬럼만 있으면 자동 반영)
      - Safety Stock 위험도   (safety_stock_score)
      - EOQ 이탈도            (eoq_score)
      - 수요예측 오차         (demand_forecast_score)
      - 클러스터 매칭도       (cluster_match_score)

  가중치 (총합 100%)
    Phase 1 기준
      heuristic  : 40%  ← 기존 로직 유지 (비용·수량·전략)
      abc        : 20%  ← 핵심상품 우선 처리
      turnover   : 20%  ← 악성재고 판단
      disposal   : 20%  ← 폐기 위험 반영

    Phase 2 컬럼이 존재하면 가중치 재배분 (자동)
"""

import pandas as pd
import numpy as np


# ─── Phase 1 가중치 ───────────────────────────────────────
_WEIGHTS_PHASE1 = {
    "heuristic_score":     0.40,
    "abc_score":           0.20,
    "turnover_score":      0.20,
    "disposal_risk_score": 0.20,
}

# ─── Phase 2 추가 가중치 (컬럼 존재 시 자동 반영) ─────────
_WEIGHTS_PHASE2 = {
    "safety_stock_score":    0.08,
    "eoq_score":             0.07,
    "demand_forecast_score": 0.07,
    "cluster_match_score":   0.05,
    "match_score":           0.05,  # 점포-상품 매칭 최적화
}

# Phase 2 추가 시 Phase 1 비중 조정 비율 (Phase 1 총합 = 1 - Phase 2 사용 비중)
_PHASE1_KEYS = list(_WEIGHTS_PHASE1.keys())
_PHASE2_KEYS = list(_WEIGHTS_PHASE2.keys())


# ─── 등급 ────────────────────────────────────────────────
def _assign_varo_grade(score: float) -> str:
    if score >= 85:
        return "최우선 처리"
    if score >= 70:
        return "우선 처리"
    if score >= 55:
        return "검토 필요"
    if score >= 40:
        return "모니터링"
    return "후순위"


def _normalize_0_100(series: pd.Series) -> pd.Series:
    """0~100 범위로 정규화. 이미 0~100이면 그대로."""
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    min_v, max_v = s.min(), s.max()
    if max_v == min_v:
        return pd.Series([50.0] * len(s), index=s.index)
    normalized = (s - min_v) / (max_v - min_v) * 100
    return normalized.clip(0, 100)


def _build_active_weights(df: pd.DataFrame) -> dict:
    """
    실제로 존재하는 컬럼 기준으로 가중치를 재산출한다.
    Phase 2 컬럼이 일부 있으면 그만큼 Phase 1 비중을 줄인다.
    """
    active_p2 = {k: v for k, v in _WEIGHTS_PHASE2.items() if k in df.columns}

    p2_total = sum(active_p2.values())
    p1_scale = 1.0 - p2_total   # Phase 1이 차지할 총 비중

    weights = {}

    # Phase 1 — 컬럼 없으면 해당 비중을 나머지 Phase 1 컬럼에 균등 재배분
    active_p1 = {k: v for k, v in _WEIGHTS_PHASE1.items() if k in df.columns}
    p1_raw_total = sum(_WEIGHTS_PHASE1[k] for k in active_p1)

    for k, v in active_p1.items():
        weights[k] = (v / p1_raw_total) * p1_scale if p1_raw_total > 0 else p1_scale / len(active_p1)

    # Phase 2
    for k, v in active_p2.items():
        weights[k] = v

    return weights


def calculate_varo_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Varo 통합 점수를 계산하고 결과 컬럼이 추가된 DataFrame을 반환한다.

    이 함수는 abc_analyzer, turnover_analyzer, disposal_risk_analyzer,
    heuristic_optimizer 결과가 모두 합쳐진 DataFrame에 호출된다.

    Parameters
    ----------
    df : pd.DataFrame
        heuristic_score, abc_score, turnover_score, disposal_risk_score
        컬럼이 포함된 DataFrame.

    Returns
    -------
    pd.DataFrame
        원본에 varo_score, varo_grade, varo_rank,
        varo_weight_breakdown 컬럼이 추가된 DataFrame.
    """
    if df is None or df.empty:
        return df

    result = df.copy()

    # 활성 가중치 결정
    weights = _build_active_weights(result)

    if not weights:
        result["varo_score"]            = 50.0
        result["varo_grade"]            = "모니터링"
        result["varo_rank"]             = range(1, len(result) + 1)
        result["varo_weight_breakdown"] = "{}"
        return result

    # 각 컬럼 0~100 정규화 후 가중 합산
    weighted_sum = pd.Series(0.0, index=result.index)

    for col, w in weights.items():
        normalized = _normalize_0_100(result[col])

        # 폐기 위험도는 '높을수록 나쁜' 지표 → 반전 (낮아야 좋은 상품)
        # Varo 점수는 '높을수록 처리 우선순위 높음'이므로 위험도는 그대로 더함
        weighted_sum += normalized * w

    result["varo_score"] = weighted_sum.clip(0, 100).round(1)
    result["varo_grade"] = result["varo_score"].apply(_assign_varo_grade)

    # 순위 (높은 점수 = 낮은 순위 번호)
    result = result.sort_values("varo_score", ascending=False).reset_index(drop=True)
    result["varo_rank"] = result.index + 1

    # 가중치 구성 텍스트 (대시보드 tooltip용)
    breakdown_str = " | ".join(
        f"{col.replace('_score','').upper()} {int(w*100)}%" for col, w in weights.items()
    )
    result["varo_weight_breakdown"] = breakdown_str

    return result


def run_all_algorithms(
    inventory_df:          pd.DataFrame,
    final_recommendations: pd.DataFrame,
    stores_df:             pd.DataFrame = None,
) -> pd.DataFrame:
    """
    모든 Phase 1 알고리즘을 순서대로 실행하고
    Varo 통합 점수까지 계산해서 반환한다.

    이 함수 하나를 app.py / dashboard_pages.py 에서 호출하면 된다.

    Parameters
    ----------
    inventory_df : pd.DataFrame
        엑셀에서 로드한 inventory 시트 (상품별 재고 정보).
    final_recommendations : pd.DataFrame
        heuristic_optimizer.add_heuristic_scores() 를 거친 최종 추천 DataFrame.

    Returns
    -------
    pd.DataFrame
        Varo 통합 점수가 포함된 최종 추천 DataFrame.
    """
    from abc_analyzer             import analyze_abc
    from turnover_analyzer        import analyze_turnover
    from disposal_risk_analyzer   import analyze_disposal_risk
    from safety_stock_analyzer    import analyze_safety_stock
    from eoq_analyzer             import analyze_eoq
    from demand_forecast_analyzer import analyze_demand_forecast
    from store_product_matcher    import analyze_store_product_matching

    if final_recommendations is None or final_recommendations.empty:
        return final_recommendations

    df = final_recommendations.copy()

    # ── Step 1: state_* 컬럼 → 표준명 정규화 ─────────────────────────
    # final_recommendations(rl_training_log)의 컬럼명을 각 analyzer 표준명으로 맞춤
    _state_rename = {
        "state_source_stock":     "stock_qty",
        "state_source_sales_30d": "sales_30d",
        "state_unit_cost":        "unit_cost",
        "state_inbound_days":     "inbound_days",
    }
    for old_col, new_col in _state_rename.items():
        if old_col in df.columns and new_col not in df.columns:
            df = df.rename(columns={old_col: new_col})

    # ── Step 2: inventory 시트에서 보조 컬럼 join ─────────────────────
    if inventory_df is not None and not inventory_df.empty:
        inv = inventory_df.copy()

        # 컬럼명 정규화
        if "inventory_product_name" in inv.columns and "product_name" not in inv.columns:
            inv = inv.rename(columns={"inventory_product_name": "product_name"})
        if "inventory_category" in inv.columns and "category" not in inv.columns:
            inv = inv.rename(columns={"inventory_category": "category"})
        if "days_to_expiry" in inv.columns and "expiry_days" not in inv.columns:
            inv = inv.rename(columns={"days_to_expiry": "expiry_days"})
        # store_name → source_store (점포별 정확한 join 용)
        if "store_name" in inv.columns and "source_store" not in inv.columns:
            inv = inv.rename(columns={"store_name": "source_store"})

        candidate_cols = [
            "avg_daily_sales",        # EOQ·Safety Stock 일평균 판매
            "unit_cost",              # ABC·EOQ 단가 (없으면 state_unit_cost 이미 있음)
            "stock_qty",              # 회전율·Safety Stock·EOQ
            "expiry_days",            # 폐기 위험도
            "inbound_days",           # 폐기 위험도 (없으면 state_inbound_days 이미 있음)
            "category",               # 폐기·EOQ 보관비율
            "avg_inventory",          # 회전율
            "sales_7d",               # 수요예측
            "sales_30d",              # 수요예측·회전율
            "order_cost",             # EOQ
            "disposal_cost_per_unit", # 폐기 비용
            "disposal_cost",          # 폐기 비용 별칭
            "lead_time_days",         # Safety Stock·EOQ
            "demand_std",             # Safety Stock
            "dead_stock_qty",         # 사망재고
        ]
        extra_cols = [c for c in candidate_cols if c in inv.columns]

        # ── sales_30d / sales_7d 파생 (avg_daily_sales 기반) ──────────
        # Excel에 sales_30d/7d 없으면 avg_daily_sales × 기간으로 생성
        if "avg_daily_sales" in inv.columns:
            if "sales_30d" not in inv.columns:
                inv["sales_30d"] = (inv["avg_daily_sales"] * 30).round(0)
                if "sales_30d" not in extra_cols:
                    extra_cols.append("sales_30d")
            if "sales_7d" not in inv.columns:
                inv["sales_7d"] = (inv["avg_daily_sales"] * 7).round(0)
                if "sales_7d" not in extra_cols:
                    extra_cols.append("sales_7d")

        # disposal_cost_per_unit → disposal_cost 별칭
        if "disposal_cost_per_unit" in inv.columns and "disposal_cost" not in inv.columns:
            inv["disposal_cost"] = inv["disposal_cost_per_unit"]
            if "disposal_cost" not in extra_cols:
                extra_cols.append("disposal_cost")

        if extra_cols and "product_name" in inv.columns:
            # 점포명 컬럼이 있으면 (product_name + source_store) 로 정확히 join
            if "source_store" in inv.columns and "source_store" in df.columns:
                join_keys = ["product_name", "source_store"]
            else:
                join_keys = ["product_name"]

            inv_sub = inv[join_keys + extra_cols].drop_duplicates(join_keys)

            # df에 이미 있는 컬럼은 건너뜀
            new_cols = [c for c in extra_cols if c not in df.columns]
            if new_cols:
                df = df.merge(inv_sub[join_keys + new_cols], on=join_keys, how="left")

    # 추천 후보 수 제한 (대량 데이터 처리 속도 최적화)
    _MAX_REC = 500
    if len(df) > _MAX_REC:
        _sc = next((c for c in ["heuristic_score","greedy_rank"] if c in df.columns), None)
        if _sc == "greedy_rank":
            df = df.nsmallest(_MAX_REC, _sc)
        elif _sc:
            df = df.nlargest(_MAX_REC, _sc)
        else:
            df = df.head(_MAX_REC)

    # 알고리즘 순차 실행
    df = analyze_abc(df)
    df = analyze_turnover(df)
    df = analyze_disposal_risk(df)
    df = analyze_safety_stock(df)
    df = analyze_eoq(df)
    df = analyze_demand_forecast(df)
    df = analyze_store_product_matching(df)

    # ── 추가 10개 알고리즘 (11~20) ────────────────────────
    try:
        from trend_aging_analyzer import analyze_sales_trend, analyze_inventory_aging
        df = analyze_sales_trend(df)
        df = analyze_inventory_aging(df)
    except Exception:
        pass

    try:
        from risk_fit_analyzer import (
            analyze_relocation_failure,
            analyze_substitute_conflict,
            analyze_category_balance,
            analyze_store_capacity,
        )
        df = analyze_relocation_failure(df)
        df = analyze_substitute_conflict(df, inventory_df)
        df = analyze_category_balance(df, inventory_df)
        df = analyze_store_capacity(df, inventory_df)
    except Exception:
        pass

    try:
        from decision_analyzer import (
            analyze_discount_sensitivity,
            analyze_disposal_avoidance,
            analyze_newsvendor,
            analyze_topsis,
        )
        df = analyze_discount_sensitivity(df)
        df = analyze_disposal_avoidance(df)
        df = analyze_newsvendor(df)
        df = analyze_topsis(df)
    except Exception:
        pass

    # ── inventory groupby 사전 계산 (캐시 공유) ──────────
    _inv_store_cache = {}
    if inventory_df is not None and not inventory_df.empty:
        _inv = inventory_df.copy()
        # store_name → source_store (단, source_store가 이미 있으면 rename 금지)
        if "store_name" in _inv.columns and "source_store" not in _inv.columns:
            _inv = _inv.rename(columns={"store_name": "source_store"})
        # 중복 컬럼 제거 (groupby 2D 오류 방지)
        if _inv.columns.duplicated().any():
            _inv = _inv.loc[:, ~_inv.columns.duplicated()]
        if "avg_daily_sales" in _inv.columns and "source_store" in _inv.columns:
            try:
                _inv_store_cache["daily"] = _inv.groupby("source_store")["avg_daily_sales"].sum()
            except Exception:
                pass
        if "stock_qty" in _inv.columns and "source_store" in _inv.columns:
            try:
                _inv_store_cache["stock"] = _inv.groupby("source_store")["stock_qty"].sum()
            except Exception:
                pass

    # ── 추가 알고리즘 (#19,#20,#21,#22,#23,#25,#27,#29,#30,#31,#32) ──
    try:
        from advanced_inventory_analyzer import (
            analyze_priority_queue,
            analyze_service_level_inventory,
            analyze_queuing_capacity,
            analyze_bottleneck,
            analyze_pareto,
        )
        df = analyze_priority_queue(df)
        df = analyze_service_level_inventory(df)
        df = analyze_queuing_capacity(df, inventory_df)
        df = analyze_bottleneck(df, inventory_df)
        df = analyze_pareto(df)
    except Exception:
        pass

    try:
        from optimization_analyzer import (
            analyze_transportation_lp,
            analyze_assignment,
            analyze_multiobjective,
            analyze_lp_allocation_score,
            analyze_sensitivity_per_item,
        )
        df = analyze_transportation_lp(df, inventory_df)
        df = analyze_assignment(df)
        df = analyze_multiobjective(df)
        df = analyze_lp_allocation_score(df)
        df = analyze_sensitivity_per_item(df)
    except Exception:
        pass

    # Varo 통합 점수 (기존 호환용)
    df = calculate_varo_score(df)

    # ── VHS v2 (주 점수) ────────────────────────────────
    try:
        from varo_score_v2 import calculate_vhs_v2
        from vhs_confidence import add_confidence
        df = calculate_vhs_v2(df, inventory_df=inventory_df)
        df = add_confidence(df)
        # vhs2 → vhs 별칭 (대시보드 호환)
        if "vhs2" in df.columns and "vhs" not in df.columns:
            df["vhs"]        = df["vhs2"]
            df["vhs_grade"]  = df.get("vhs2_grade", "검토")
            df["vhs_action"] = df.get("vhs2_action", "보류")
    except Exception:
        pass

    # ── VHS 구버전 (호환용, vhs2 없을 때만) ─────────────
    if "vhs2" not in df.columns:
        try:
            from varo_hybrid_score import calculate_varo_hybrid_score
            df = calculate_varo_hybrid_score(df)
        except Exception:
            pass

    return df
