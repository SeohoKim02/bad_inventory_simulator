"""
varo_demand.py
───────────────
수요 예측·적합도 계산 모듈.

- 기존 Varo Hybrid Score / 추천 로직 미수정
- 받는 점포의 수요 가능성을 보조 판단 지표로 제공
- 수요 데이터가 없어도 앱이 정상 실행되도록 방어 처리
"""

import math
import numpy as np
import pandas as pd

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _sn(value, default: float = 0.0) -> float:
    try:
        f = float(value)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def _first_col(row_or_df, *names, default=None):
    """row(Series) 또는 dict에서 첫 번째 유효 값 반환."""
    for n in names:
        try:
            v = row_or_df.get(n) if hasattr(row_or_df, 'get') else row_or_df[n]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                return v
        except (KeyError, TypeError):
            pass
    return default

# demand_level 한글/영문 정규화
_DEMAND_LEVEL_MAP = {
    "상": "높음", "high": "높음", "높음": "높음", "h": "높음",
    "중": "보통", "medium": "보통", "보통": "보통", "m": "보통",
    "하": "낮음", "low": "낮음", "낮음": "낮음", "l": "낮음",
}

def _normalize_demand_level(val) -> str:
    if val is None: return "데이터 없음"
    return _DEMAND_LEVEL_MAP.get(str(val).strip().lower(), "데이터 없음")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 단일 행 기반 계산
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_expected_demand(row) -> float:
    """
    단일 행에서 일 평균 수요 추정.
    우선순위: avg_daily_sales → sales_7d/7 → sales_30d/30 → demand_qty/30 → fallback
    """
    # avg_daily_sales
    v = _sn(_first_col(row, "avg_daily_sales"), -1)
    if v > 0: return round(v, 3)
    # sales_7d
    v = _sn(_first_col(row, "sales_7d", "recent_sales_7d"), -1)
    if v > 0: return round(v / 7, 3)
    # sales_30d
    v = _sn(_first_col(row, "sales_30d", "state_source_sales_30d", "sales_30"), -1)
    if v > 0: return round(v / 30, 3)
    # demand_qty (30일 기준)
    v = _sn(_first_col(row, "demand_qty"), -1)
    if v > 0: return round(v / 30, 3)
    # fallback: demand_level 기반 기준값
    dl = _normalize_demand_level(_first_col(row, "demand_level"))
    if dl == "높음": return 5.0
    if dl == "보통": return 2.0
    if dl == "낮음": return 0.5
    return 0.0


def infer_demand_level(row) -> str:
    """
    단일 행에서 수요 수준 추론.
    demand_level 컬럼 우선, 없으면 수치 기반 추론.
    """
    dl = _first_col(row, "demand_level")
    normalized = _normalize_demand_level(dl)
    if normalized != "데이터 없음":
        return normalized

    daily = calculate_expected_demand(row)
    if daily <= 0:
        return "데이터 없음"
    if daily >= 3.0:
        return "높음"
    if daily >= 0.5:
        return "보통"
    return "낮음"


def calculate_stockout_risk(row) -> float:
    """
    재고 부족 위험도 0~100점.
    현재 재고 / 30일 예상 수요 기반.
    """
    stock = _sn(_first_col(row, "current_stock", "stock_qty", "inventory_qty"), 0)
    daily = calculate_expected_demand(row)
    if daily <= 0:
        # expiry_risk_score 있으면 그대로 활용
        er = _sn(_first_col(row, "expiry_risk_score"), -1)
        if er >= 0: return min(100.0, er)
        return 50.0

    days_of_stock = stock / daily  # 현재 재고로 버티는 날수
    if days_of_stock <= 3:  return 95.0
    if days_of_stock <= 7:  return 80.0
    if days_of_stock <= 14: return 60.0
    if days_of_stock <= 30: return 35.0
    return 10.0


def calculate_demand_fit_score(row) -> float:
    """
    받는 점포 수요 적합도 점수 0~100.
    demand_level + stockout_risk 조합.
    """
    dl     = infer_demand_level(row)
    sr     = calculate_stockout_risk(row)
    dl_base = {"높음": 75.0, "보통": 55.0, "낮음": 30.0, "데이터 없음": 50.0}.get(dl, 50.0)
    # stockout_risk 가중치 반영: 부족 위험 높으면 이동 필요 → 점수 상승
    fit = dl_base * 0.6 + sr * 0.4
    return round(min(100.0, max(0.0, fit)), 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. DataFrame 전체에 수요 피처 추가
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def add_demand_features(
    df: pd.DataFrame,
    products_df: pd.DataFrame = None,
    stores_df: pd.DataFrame   = None,
) -> pd.DataFrame:
    """
    추천 후보 DataFrame에 수요 관련 컬럼 추가.
    products_df가 있으면 demand_level, sales_30d를 product_name으로 조인.
    기존 컬럼을 수정하지 않음.
    """
    if df is None or df.empty:
        return df

    out = df.copy()

    # products_df 조인 (demand_level, sales_30d)
    if products_df is not None and not products_df.empty:
        prod_name_col = next(
            (c for c in products_df.columns if c.lower() in
             ("product_name","상품명","item_name","name","product")), None
        )
        if prod_name_col and "product_name" in out.columns:
            p_merge = products_df[[prod_name_col] + [
                c for c in ["demand_level","sales_30","sales_30d","shelf_life_days"]
                if c in products_df.columns
            ]].rename(columns={prod_name_col: "product_name"})
            # 중복 컬럼은 suffix 처리
            merge_cols = [c for c in p_merge.columns[1:] if c not in out.columns]
            if merge_cols:
                p_merge = p_merge[["product_name"] + merge_cols].drop_duplicates("product_name")
                out = out.merge(p_merge, on="product_name", how="left")

    # 행별 수요 피처 계산
    exp_daily, exp_7d, levels, fit_scores, sr_scores = [], [], [], [], []
    for _, row in out.iterrows():
        ed  = calculate_expected_demand(row)
        dl  = infer_demand_level(row)
        sr  = calculate_stockout_risk(row)
        fit = calculate_demand_fit_score(row)
        exp_daily.append(round(ed, 3))
        exp_7d.append(round(ed * 7, 1))
        levels.append(dl)
        fit_scores.append(fit)
        sr_scores.append(sr)

    out["expected_daily_demand"] = exp_daily
    out["expected_7d_demand"]    = exp_7d
    out["demand_status"]         = levels
    out["demand_fit_score"]      = fit_scores
    out["demand_score"]          = fit_scores   # alias
    out["stockout_risk_score"]   = sr_scores

    return out


def merge_demand_features_to_recommendations(
    recommendations_df: pd.DataFrame,
    demand_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    별도로 생성된 demand_df를 recommendations에 left-join.
    product_name + source_store 기준.
    """
    if recommendations_df is None or recommendations_df.empty:
        return recommendations_df
    if demand_df is None or demand_df.empty:
        return recommendations_df

    demand_cols = [c for c in [
        "demand_status","demand_fit_score","demand_score",
        "expected_daily_demand","expected_7d_demand","stockout_risk_score"
    ] if c in demand_df.columns]

    keys = [k for k in ["product_name","source_store","target_store"]
            if k in recommendations_df.columns and k in demand_df.columns]
    if not keys or not demand_cols:
        return recommendations_df

    merge_src = demand_df[keys + demand_cols].drop_duplicates(keys)
    result = recommendations_df.merge(merge_src, on=keys, how="left")
    if "demand_status" in result.columns:
        result["demand_status"] = result["demand_status"].fillna("데이터 없음")
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 수요 분석 요약
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_demand_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty or "demand_status" not in df.columns:
        return {}
    vc = df["demand_status"].value_counts().to_dict()
    total = len(df)
    high = int(vc.get("높음", 0))
    return {
        "높음": high,
        "보통": int(vc.get("보통", 0)),
        "낮음": int(vc.get("낮음", 0)),
        "데이터 없음": int(vc.get("데이터 없음", 0)),
        "높음 비율": round(high / total * 100, 1) if total else 0.0,
    }


def get_demand_view_df(df: pd.DataFrame) -> pd.DataFrame:
    """수요 분석 표시용 DataFrame."""
    cols = {
        "product_name":        "상품명",
        "target_store":        "받는 점포",
        "demand_status":       "수요 수준",
        "expected_7d_demand":  "예상 7일 수요",
        "stock_qty":           "현재 재고",
        "suggested_qty":       "추천 수량",
        "demand_fit_score":    "수요 적합도",
        "stockout_risk_score": "재고 부족 위험",
    }
    avail = [c for c in cols if c in df.columns]
    return df[avail].rename(columns=cols).reset_index(drop=True)
