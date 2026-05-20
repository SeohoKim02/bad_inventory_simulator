"""
#13 재배치 실패 위험 + #14 대체상품 충돌 + #15 카테고리 균형 + #16 점포 처리 능력
──────────────────────────────────────────────────────────────────────────
13. 재배치 실패 위험 (Relocation Failure Risk)
    수요부족 + 유통기한부족 + 거리위험 → 0~100 (높을수록 이동 후 안 팔릴 위험)
14. 대체 상품 충돌 (Substitute Conflict)
    목적 점포에 같은 카테고리 재고 포화도 → 0~100
15. 카테고리 균형 (Category Balance)
    점포별 카테고리 비율 vs 전체 평균 편차 → 0~100 균형 점수
16. 점포 처리 능력 (Store Processing Capacity)
    추가 재고를 소화할 여력 → 0~100
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
#  #13 재배치 실패 위험
# ──────────────────────────────────────────────

def analyze_relocation_failure(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()

    # 목적지 수요 부족 위험 (0~40)
    tgt_sales = _col(out, "state_target_sales_30d") / 30.0
    src_sales = _col(out, "avg_daily_sales", "state_source_sales_30d")
    if "state_source_sales_30d" in out.columns and "avg_daily_sales" not in out.columns:
        src_sales = src_sales / 30.0
    safe_src = src_sales.replace(0, np.nan)
    demand_ratio = (tgt_sales / safe_src).fillna(0.5).clip(0, 2)
    demand_risk  = ((1 - demand_ratio / 2) * 40).clip(0, 40)

    # 유통기한 부족 위험 (0~35): 이동 시간 고려
    expiry = _col(out, "expiry_days", "days_to_expiry", default=999)
    dist   = _col(out, "state_distance_km", "direct_distance_km", default=2.0)
    transit_days = (dist / 20.0).clip(0.5, 5)   # 이동 시간 추정 (일)
    safe_expiry  = (expiry - transit_days).clip(lower=0)
    expiry_risk  = ((1 - safe_expiry / 10.0).clip(0, 1) * 35).clip(0, 35)

    # 거리 위험 (0~25)
    dist_risk = (dist / 15.0 * 25).clip(0, 25)

    failure_score = (demand_risk + expiry_risk + dist_risk).clip(0, 100).round(1)

    out["relocation_failure_score"] = failure_score
    out["relocation_failure_grade"] = failure_score.apply(
        lambda s: "HIGH"   if s >= 70 else
                  "MEDIUM" if s >= 40 else "LOW"
    )
    return out


# ──────────────────────────────────────────────
#  #14 대체 상품 충돌
# ──────────────────────────────────────────────

def analyze_substitute_conflict(
    df: pd.DataFrame,
    inventory_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    목적 점포에 동일 카테고리 재고가 얼마나 있는지 측정.
    inventory_df 없으면 state_target_stock 대리 지표 사용.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    if inventory_df is not None and "store_name" in inventory_df.columns:
        inv = inventory_df.copy()
        if "inventory_product_name" in inv.columns:
            inv = inv.rename(columns={"inventory_product_name": "product_name"})
        if "inventory_category" in inv.columns:
            inv = inv.rename(columns={"inventory_category": "category"})
        if "store_name" in inv.columns:
            inv = inv.rename(columns={"store_name": "source_store"})

        # 점포×카테고리별 평균 재고
        if "category" in inv.columns and "stock_qty" in inv.columns:
            cat_stock = (
                inv.groupby(["source_store", "category"])["stock_qty"]
                .mean().reset_index()
                .rename(columns={"source_store": "target_store",
                                  "stock_qty": "_tgt_cat_stock"})
            )
            # 전체 평균 대비 포화도
            global_avg = cat_stock["_tgt_cat_stock"].mean()
            cat_stock["_saturation"] = (
                cat_stock["_tgt_cat_stock"] / max(global_avg, 1)
            ).clip(0, 3)

            if "category" not in out.columns and "inventory_category" in out.columns:
                out["category"] = out["inventory_category"]

            if "target_store" in out.columns and "category" in out.columns:
                out = out.merge(cat_stock[["target_store","category","_saturation"]],
                                on=["target_store","category"], how="left")
                conflict = (out["_saturation"].fillna(1.0) / 3.0 * 100).clip(0,100)
                out.drop(columns=["_saturation"], inplace=True, errors="ignore")
            else:
                conflict = pd.Series([50.0]*len(out), index=out.index)
        else:
            conflict = pd.Series([50.0]*len(out), index=out.index)
    else:
        # fallback: 목적 점포 재고가 많을수록 충돌 높음
        tgt_stock = _col(out, "state_target_stock", default=100)
        src_stock  = _col(out, "stock_qty", "state_source_stock", default=100)
        ratio = (tgt_stock / src_stock.replace(0, 1)).clip(0, 3)
        conflict = (ratio / 3 * 100).clip(0, 100)

    out["substitute_conflict_score"] = conflict.round(1)
    return out


# ──────────────────────────────────────────────
#  #15 카테고리 균형
# ──────────────────────────────────────────────

def analyze_category_balance(
    df: pd.DataFrame,
    inventory_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    점포별 카테고리 비율 vs 전체 평균 비율 비교.
    균형이 좋을수록 높은 점수(0~100).
    inventory_df 없으면 중립 50점.
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    if inventory_df is not None and not inventory_df.empty:
        inv = inventory_df.copy()
        if "inventory_product_name" in inv.columns:
            inv = inv.rename(columns={"inventory_product_name": "product_name"})
        if "inventory_category" in inv.columns:
            inv = inv.rename(columns={"inventory_category": "category"})
        if "store_name" in inv.columns:
            inv = inv.rename(columns={"store_name": "source_store"})

        if "category" in inv.columns and "stock_qty" in inv.columns and "source_store" in inv.columns:
            # 점포×카테고리별 재고 비율
            store_total = inv.groupby("source_store")["stock_qty"].sum().rename("_total")
            cat_store   = inv.groupby(["source_store","category"])["stock_qty"].sum().reset_index()
            cat_store   = cat_store.join(store_total, on="source_store")
            cat_store["_ratio"] = cat_store["stock_qty"] / cat_store["_total"].replace(0,1)

            # 전체 평균 카테고리 비율
            global_ratio = (
                cat_store.groupby("category")["_ratio"].mean().rename("_global_ratio")
            )
            cat_store = cat_store.join(global_ratio, on="category")
            cat_store["_deviation"] = (
                (cat_store["_ratio"] - cat_store["_global_ratio"]).abs()
            )
            # 점포별 편차 합계
            store_dev = (
                cat_store.groupby("source_store")["_deviation"].sum()
                .rename("_dev_sum")
            )
            # 편차가 낮을수록 균형 좋음 → 높은 점수
            max_dev = store_dev.max()
            balance = (
                (1 - store_dev / max(max_dev, 0.01)) * 100
            ).clip(0, 100)

            # target_store 기준으로 매핑
            if "target_store" in out.columns:
                out["category_balance_score"] = (
                    out["target_store"].map(balance).fillna(50.0).round(1)
                )
            else:
                out["category_balance_score"] = 50.0
        else:
            out["category_balance_score"] = 50.0
    else:
        out["category_balance_score"] = 50.0

    return out


# ──────────────────────────────────────────────
#  #16 점포 처리 능력
# ──────────────────────────────────────────────

def analyze_store_capacity(
    df: pd.DataFrame,
    inventory_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    받는 점포가 추가 재고를 소화할 여력.
    여력 높을수록 높은 점수(0~100).
    """
    if df is None or df.empty:
        return df
    out = df.copy()

    if inventory_df is not None and not inventory_df.empty:
        inv = inventory_df.copy()
        if "store_name" in inv.columns:
            inv = inv.rename(columns={"store_name": "source_store"})
        if "inventory_category" in inv.columns:
            inv = inv.rename(columns={"inventory_category": "category"})

        if "avg_daily_sales" in inv.columns and "stock_qty" in inv.columns and "source_store" in inv.columns:
            store_cap = inv.groupby("source_store").agg(
                _daily_sum=("avg_daily_sales", "sum"),
                _stock_sum=("stock_qty", "sum"),
                _capacity=("capacity", "first") if "capacity" in inv.columns else ("stock_qty", "count"),
            ).reset_index()

            # 현재 재고 소화 속도 = daily / stock (빠를수록 여력 있음)
            safe_stock = store_cap["_stock_sum"].replace(0, 1)
            store_cap["_throughput"] = (store_cap["_daily_sum"] / safe_stock * 30).clip(0, 3)
            max_t = store_cap["_throughput"].max()
            store_cap["_cap_score"] = (
                store_cap["_throughput"] / max(max_t, 0.01) * 100
            ).clip(0, 100)

            cap_map = store_cap.set_index("source_store")["_cap_score"].to_dict()

            if "target_store" in out.columns:
                out["store_capacity_score"] = (
                    out["target_store"].map(cap_map).fillna(50.0).round(1)
                )
            else:
                out["store_capacity_score"] = 50.0
        else:
            out["store_capacity_score"] = 50.0
    else:
        # fallback: 목적 점포 판매량 / 현재 재고 비율
        tgt_sales = _col(out, "state_target_sales_30d") / 30.0
        tgt_stock = _col(out, "state_target_stock", default=100)
        ratio = (tgt_sales / tgt_stock.replace(0,1) * 30).clip(0, 3)
        out["store_capacity_score"] = (ratio / 3 * 100).clip(0, 100).round(1)

    return out
