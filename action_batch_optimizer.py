"""
action_batch_optimizer.py — 처리 배치 최적화
──────────────────────────────────────────────
"지금 가진 N개 추천 후보를 어떤 순서로 처리하면
 총 비용과 폐기 손실을 최소화할 수 있는가?"

초기 버전: 우선순위 점수 기반 정렬
추후: 예산·차량·시간 제약을 받는 LP 최적화로 확장
"""
import numpy as np
import pandas as pd


def _s(val, default=0.0):
    try:
        v = float(val)
        return default if np.isnan(v) else v
    except (TypeError, ValueError):
        return default


def _col(df, *names, default=0.0):
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce").fillna(default)
    return pd.Series([default] * len(df), index=df.index)


def _priority_score(df: pd.DataFrame) -> pd.Series:
    """
    다음 기준을 가중합으로 처리 우선순위 점수 계산:
      VHS v2 점수            35%
      폐기 위험도            25%
      폐기 회피 이익         15%
      유통기한 임박도(역수)  15%
      실행 가능성            10%
    """
    vhs2      = _col(df, "vhs2",                  default=50)
    disposal  = _col(df, "disposal_risk_score",   default=50)
    avoidance = _col(df, "disposal_avoidance_score", default=50)
    expiry    = _col(df, "expiry_days","days_to_expiry", default=30)
    exec_s    = _col(df, "store_capacity_score",  default=50)

    # 유통기한 → 긴급도 (짧을수록 높음, 30일 기준)
    expiry_urgency = (1 - (expiry.clip(0, 30) / 30)) * 100

    priority = (
        vhs2           * 0.35 +
        disposal       * 0.25 +
        avoidance      * 0.15 +
        expiry_urgency * 0.15 +
        exec_s         * 0.10
    ).clip(0, 100)
    return priority.round(1)


def _build_reason(row: pd.Series) -> str:
    """우선 처리 사유 생성."""
    reasons = []
    disposal = str(row.get("disposal_risk_grade", ""))
    turnover = str(row.get("turnover_grade",       ""))
    expiry   = _s(row.get("expiry_days") or row.get("days_to_expiry"), 999)
    avoidance= _s(row.get("disposal_avoidance_score", 0))
    vhs2     = _s(row.get("vhs2", 50))

    if disposal in ("CRITICAL",):              reasons.append("폐기 CRITICAL")
    elif disposal in ("HIGH",):                reasons.append("폐기 HIGH")
    if expiry <= 3:                            reasons.append(f"유통기한 {expiry:.0f}일")
    elif expiry <= 7:                          reasons.append(f"유통기한 {expiry:.0f}일 임박")
    if turnover == "DEAD":                     reasons.append("회전율 DEAD")
    if avoidance >= 70:                        reasons.append(f"회피이익 {avoidance:.0f}점")
    if vhs2 >= 75:                             reasons.append(f"VHS {vhs2:.0f}점")

    return " | ".join(reasons) if reasons else "VHS 기준 처리 권장"


def optimize_action_batch(
    recommendations: pd.DataFrame,
    budget:        float = None,   # 총 예산 (원), None = 무제한
    vehicle_limit: int   = None,   # 사용 가능 차량 수, None = 무제한
    time_limit:    float = None,   # 처리 가능 시간 (시간), None = 무제한
) -> pd.DataFrame:
    """
    처리 배치 최적화.

    Parameters
    ----------
    recommendations : run_all_algorithms() 결과 DataFrame
    budget          : 총 예산 (None = 무제한)
    vehicle_limit   : 차량 수 제약 (None = 무제한)
    time_limit      : 시간 제약 (None = 무제한)

    Returns
    -------
    pd.DataFrame with columns:
        처리순위, 상품명, 보내는점포, 받는점포, 추천전략,
        추천수량, VHS점수, 예상비용, 폐기회피이익, 우선처리사유,
        _within_budget, _priority_score
    """
    if recommendations is None or recommendations.empty:
        return pd.DataFrame()

    df = recommendations.copy()

    # 1. 우선순위 점수 계산
    df["_priority_score"] = _priority_score(df)

    # 2. 예산 제약
    df["_est_cost"] = pd.to_numeric(
        df.get("estimated_cost", pd.Series([0]*len(df))), errors="coerce"
    ).fillna(0)
    df["_within_budget"] = True

    if budget is not None and budget > 0:
        df = df.sort_values("_priority_score", ascending=False).reset_index(drop=True)
        cumcost = df["_est_cost"].cumsum()
        df["_within_budget"] = cumcost <= budget

    # 3. 최종 정렬 (우선순위 높은 순)
    df = df.sort_values("_priority_score", ascending=False).reset_index(drop=True)
    df["처리순위"] = df.index + 1

    # 4. 출력 컬럼 구성
    def _get(col, *fallbacks, default="-"):
        for c in [col] + list(fallbacks):
            if c in df.columns:
                return df[c]
        return pd.Series([default] * len(df), index=df.index)

    result = pd.DataFrame({
        "처리순위":       df["처리순위"],
        "상품명":         _get("product_name"),
        "보내는점포":     _get("source_store"),
        "받는점포":       _get("target_store"),
        "추천전략":       _get("vhs2_action", "vhs_action", "heuristic_grade"),
        "추천수량":       _get("suggested_qty"),
        "VHS점수":        _get("vhs2", "vhs").round(1) if "vhs2" in df.columns else _get("vhs"),
        "예상비용(원)":   df["_est_cost"].astype(int),
        "폐기회피이익":   pd.to_numeric(_get("disposal_avoidance_profit", "disposal_avoidance_score"), errors="coerce").fillna(0).round(0),
        "우선처리사유":   df.apply(_build_reason, axis=1),
        "예산내처리":     df["_within_budget"].map({True: "✅", False: "⛔"}),
        "우선순위점수":   df["_priority_score"],
    })

    # 5. 차량 제약 (단순: 상위 vehicle_limit × 5건)
    if vehicle_limit is not None and vehicle_limit > 0:
        max_items = vehicle_limit * 5
        result = result.head(max_items)

    return result.reset_index(drop=True)


def batch_summary(batch_df: pd.DataFrame) -> dict:
    """처리 배치 요약 통계."""
    if batch_df is None or batch_df.empty:
        return {}
    within = batch_df[batch_df.get("예산내처리", "✅") == "✅"]
    return {
        "total_items":       len(batch_df),
        "within_budget":     len(within),
        "total_cost":        int(batch_df["예상비용(원)"].sum()),
        "total_avoidance":   int(pd.to_numeric(batch_df["폐기회피이익"], errors="coerce").fillna(0).sum()),
        "top_reason":        batch_df["우선처리사유"].iloc[0] if len(batch_df) else "-",
    }
