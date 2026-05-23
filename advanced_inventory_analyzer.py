"""
#19 재고 이동 우선순위 큐 / #25 서비스 수준 재고관리
#27 대기행렬 이론 / #30 병목 분석 / #31 Pareto 분석
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
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        @staticmethod
        def ppf(p):
            # rational approx — Abramowitz & Stegun
            import math
            if p <= 0: return -float('inf')
            if p >= 1: return  float('inf')
            sign = 1 if p >= 0.5 else -1
            q = min(p, 1-p)
            t = math.sqrt(-2*math.log(q))
            c = (2.515517,0.802853,0.010328)
            d = (1.432788,0.189269,0.001308)
            n_val = t - (c[0]+c[1]*t+c[2]*t*t)/(1+d[0]*t+d[1]*t*t+d[2]*t*t*t)
            return sign * n_val


def _s(s, d=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(d)

def _col(df, *names, default=0.0):
    for n in names:
        if n in df.columns:
            return _s(df[n], default)
    return pd.Series([default] * len(df), index=df.index)


# ── #19 재고 이동 우선순위 큐 ─────────────────────────────

def analyze_priority_queue(df: pd.DataFrame) -> pd.DataFrame:
    """
    폐기위험 + 노후화 + 수요매칭 + 처리비용을 가중합으로
    처리 순서 우선순위 점수 계산 (0~100).
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    disposal  = _col(out, "disposal_risk_score",  default=50)
    aging     = _col(out, "aging_score",           default=50)
    demand    = _col(out, "demand_forecast_score", default=50)
    match     = _col(out, "match_score",           default=50)
    cost_norm = 100 - _col(out, "heuristic_score", default=50).clip(0, 100)

    # 우선순위 = 긴급도(40) + 노후화(25) + 수요매칭(20) - 비용부담(15)
    pq = (disposal * 0.40 + aging * 0.25 + match * 0.20
          + demand * 0.10 - cost_norm * 0.05).clip(0, 100).round(1)

    out["priority_queue_score"] = pq
    out["priority_queue_rank"]  = pq.rank(ascending=False, method="min").astype(int)
    return out


# ── #25 서비스 수준 기반 재고관리 ─────────────────────────

def analyze_service_level_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """
    목표 서비스 수준(95%) 대비 현재 재고 충족도.
    현재 재고가 SS+ROP 이상이면 서비스 수준 양호.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    stock    = _col(out, "stock_qty", "state_source_stock")
    ss       = _col(out, "safety_stock", default=0)
    rop      = _col(out, "reorder_point", default=0)
    daily    = _col(out, "avg_daily_sales", default=1)

    # 서비스 수준 달성 여부: 재고 ≥ ROP → 만족
    rop_safe = rop.copy()
    rop_safe[rop_safe == 0] = daily * 3 + 1
    service_ratio = (stock / rop_safe.replace(0, 1)).clip(0, 3)
    sl_score = (service_ratio / 3 * 100).clip(0, 100).round(1)

    # 목표 서비스 수준 대비 실제 달성률
    target_sl = 0.95
    current_z = ((stock - ss) / daily.replace(0, 1)).clip(-3, 3)
    # 벡터화된 norm.cdf (scipy 있으면 ufunc, 없으면 math.erf 배열)
    try:
        import numpy as _np2
        current_sl = pd.Series(
            0.5 * (1 + _np2.vectorize(lambda z: __import__("math").erf(float(z)/_np2.sqrt(2)))(current_z.values)),
            index=out.index
        )
    except Exception:
        current_sl = pd.Series([0.5]*len(out), index=out.index)
    sl_gap = ((current_sl - target_sl) * 100).round(1)

    out["service_level_score"]  = sl_score
    out["service_level_current"] = current_sl.round(3)
    out["service_level_gap"]    = sl_gap
    return out


# ── #27 대기행렬 이론 ─────────────────────────────────────

def analyze_queuing_capacity(df: pd.DataFrame,
                              inventory_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    M/M/1 대기행렬: 점포 처리 속도(μ) vs 입고 속도(λ) → 이용률 ρ
    ρ < 1이면 처리 가능, ρ → 1이면 과부하.
    score = (1 - ρ) × 100 (높을수록 여유 있음)
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    if inventory_df is not None and not inventory_df.empty:
        inv = inventory_df.copy()
        if "store_name" in inv.columns:
            inv = inv.rename(columns={"store_name": "source_store"})
        if "avg_daily_sales" in inv.columns and "source_store" in inv.columns:
            # μ = 일평균판매(처리속도), λ = 입고수요(avg_daily_sales 역산)
            store_mu = inv.groupby("source_store")["avg_daily_sales"].sum().rename("_mu")
            # λ = 입고 도착률 추정: 재고 / 30일 (하루 평균 입고량)
            store_stock = inv.groupby("source_store")["stock_qty"].sum().rename("_stock")
            store_lambda = (store_stock / 30.0).rename("_lambda")
            # ρ = λ/μ: 1 이하면 처리 가능, 1 초과면 과부하
            store_rho = (store_lambda / store_mu.replace(0, 1e-6)).clip(0, 3)
            queue_score = ((1 - store_rho / 3) * 100).clip(0, 100)
            score_map = queue_score.to_dict()
            if "target_store" in out.columns:
                out["queue_capacity_score"] = (
                    out["target_store"].map(score_map).fillna(50.0).round(1)
                )
            else:
                out["queue_capacity_score"] = 50.0
        else:
            out["queue_capacity_score"] = 50.0
    else:
        # fallback: 목적지 판매속도 vs 현재 재고
        tgt  = _col(out, "state_target_sales_30d", default=300) / 30
        src  = _col(out, "stock_qty", "state_source_stock", default=100)
        rho  = (src / (tgt * 30).replace(0, 1)).clip(0, 2)
        out["queue_capacity_score"] = ((1 - rho / 2) * 100).clip(0, 100).round(1)
    return out


# ── #30 병목 분석 ─────────────────────────────────────────

def analyze_bottleneck(df: pd.DataFrame,
                        inventory_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    가장 처리를 막는 제약 요소를 찾아 병목 점수 계산.
    높은 점수 = 병목 없이 실행 가능.
    제약: 냉장차량 필요, 점포 처리 능력 초과, 거리 초과.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    # 거리 제약 (15km 이상이면 병목 위험)
    dist    = _col(out, "state_distance_km", "direct_distance_km", default=3.0)
    d_score = (1 - (dist / 20.0).clip(0, 1)) * 40

    # 처리 능력 제약
    cap     = _col(out, "store_capacity_score", default=50)
    c_score = cap / 100 * 35

    # 수량 제약 (추천 수량 vs 점포 가용 용량)
    qty     = _col(out, "suggested_qty", default=30)
    q_score = (1 - (qty / 200).clip(0, 1)) * 25

    bottleneck_score = (d_score + c_score + q_score).clip(0, 100).round(1)

    # 병목 원인 레이블
    def _label(row):
        issues = []
        if row.get("state_distance_km", 3) > 15: issues.append("거리 초과")
        if row.get("store_capacity_score", 50) < 30: issues.append("처리 능력 부족")
        if row.get("suggested_qty", 30) > 150: issues.append("수량 과다")
        return " · ".join(issues) if issues else "병목 없음"

    out["bottleneck_score"]  = bottleneck_score
    out["bottleneck_reason"] = out.apply(_label, axis=1)
    return out


# ── #31 Pareto 분석 ───────────────────────────────────────

def analyze_pareto(df: pd.DataFrame) -> pd.DataFrame:
    """
    폐기 위험도 × 재고량으로 상위 20% 고위험 상품 식별.
    파레토 등급: CRITICAL_20(상위 20%), IMPORTANT_50, MINOR
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    disposal  = _col(out, "disposal_risk_score", default=50)
    stock_qty = _col(out, "stock_qty", "state_source_stock", default=100)
    unit_cost = _col(out, "unit_cost", "state_unit_cost", default=1000)

    # 파레토 지수 = 폐기위험 × 예상손실가치
    pareto_idx = (disposal / 100 * stock_qty * unit_cost).clip(lower=0)
    total      = pareto_idx.sum()
    if total > 0:
        cum_pct = pareto_idx.sort_values(ascending=False).cumsum() / total
        rank_map = cum_pct.reset_index()
        rank_map.columns = ["orig_idx","cum_pct"]
        rank_map["pareto_grade"] = rank_map["cum_pct"].apply(
            lambda p: "CRITICAL_20"  if p <= 0.20 else
                      "IMPORTANT_50" if p <= 0.50 else "MINOR"
        )
        grade_map = rank_map.set_index("orig_idx")["pareto_grade"].to_dict()
        out["pareto_grade"] = out.index.map(grade_map).fillna("MINOR")
    else:
        out["pareto_grade"] = "MINOR"

    # Pareto 점수: CRITICAL_20 = 100, IMPORTANT_50 = 60, MINOR = 20
    out["pareto_score"] = out["pareto_grade"].map(
        {"CRITICAL_20": 100, "IMPORTANT_50": 60, "MINOR": 20}
    ).fillna(20)
    return out
