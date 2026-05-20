"""
#11 판매 추세 변화율 + #12 재고 노후화 지수
──────────────────────────────────────────────
11. 판매 추세 변화율 (Sales Trend)
    최근 7일 일평균 vs 30일 일평균 비교
    trend_rate   = recent_daily / hist_daily (배율)
    trend_score  0~100  (50=안정, >50=증가, <50=감소)
    trend_direction : RISING / STABLE / DECLINING

12. 재고 노후화 지수 (Inventory Aging Index)
    보유일수·저회전·판매감소를 합산
    aging_score  0~100 (높을수록 오래 묶인 재고)
    aging_grade : SEVERE(80+) / HIGH(60+) / MEDIUM(40+) / LOW
"""
import numpy as np
import pandas as pd


def _s(s, d=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(d)

def _col(df, *names, default=0.0):
    for n in names:
        if n in df.columns:
            return _s(df[n], default)
    return pd.Series([default]*len(df), index=df.index)


# ──────────────────────────────────────────────
#  #11 판매 추세 변화율
# ──────────────────────────────────────────────

def analyze_sales_trend(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    hist_daily = _col(out, "avg_daily_sales")
    for col in ["sales_7d", "sales_7"]:
        if col in out.columns:
            recent_daily = _s(out[col]) / 7.0
            break
    else:
        recent_daily = hist_daily  # 데이터 없으면 동일 가정

    safe_hist = hist_daily.replace(0, np.nan)
    trend_rate = (recent_daily / safe_hist).fillna(1.0).clip(0.1, 5.0)

    # 50 = 안정, 1배율 → 50점
    trend_score = ((trend_rate - 1.0) * 25 + 50).clip(0, 100).round(1)

    out["trend_rate"]      = trend_rate.round(3)
    out["trend_score"]     = trend_score
    out["trend_direction"] = trend_rate.apply(
        lambda r: "RISING"   if r > 1.10 else
                  "DECLINING" if r < 0.90 else "STABLE"
    )
    return out


# ──────────────────────────────────────────────
#  #12 재고 노후화 지수
# ──────────────────────────────────────────────

def analyze_inventory_aging(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    inbound = _col(out, "inbound_days", "state_inbound_days")  # 입고 후 경과일
    stock   = _col(out, "stock_qty",    "state_source_stock")
    daily   = _col(out, "avg_daily_sales")
    trend_r = _col(out, "trend_rate") if "trend_rate" in out.columns else pd.Series([1.0]*len(out), index=out.index)

    # ① 보유일수 점수 (0~40): 30일 기준
    age_score = (inbound / 30.0 * 40).clip(0, 40)

    # ② 저회전 점수 (0~35): 재고 대비 판매 속도
    safe_daily = daily.replace(0, np.nan)
    days_to_sell = (stock / safe_daily).fillna(999).clip(0, 180)
    slow_score = (days_to_sell / 180.0 * 35).clip(0, 35)

    # ③ 판매 감소 점수 (0~25): trend_rate < 1이면 감소 점수
    decline_score = ((1.0 - trend_r).clip(0, 1) * 25).clip(0, 25)

    aging_score = (age_score + slow_score + decline_score).clip(0, 100).round(1)

    out["aging_score"] = aging_score
    out["aging_grade"] = aging_score.apply(
        lambda s: "SEVERE" if s >= 80 else
                  "HIGH"   if s >= 60 else
                  "MEDIUM" if s >= 40 else "LOW"
    )
    return out
