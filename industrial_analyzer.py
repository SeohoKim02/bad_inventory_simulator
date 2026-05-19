import pandas as pd


ABC_SCORE_MAP = {
    "A": 100,
    "B": 70,
    "C": 45,
}


def _safe_numeric(series_or_value, default=0.0):
    try:
        if isinstance(series_or_value, pd.Series):
            return pd.to_numeric(series_or_value, errors="coerce").fillna(default)
        if pd.isna(series_or_value):
            return default
        return float(series_or_value)
    except Exception:
        return default


def _first_existing_column(df, columns):
    if df is None or df.empty:
        return None
    for col in columns:
        if col in df.columns:
            return col
    return None


def _normalize_series(series, default=0.0):
    s = pd.to_numeric(series, errors="coerce").fillna(default)
    if len(s) == 0:
        return s

    min_value = s.min()
    max_value = s.max()

    if pd.isna(min_value) or pd.isna(max_value) or min_value == max_value:
        return pd.Series([0.0] * len(s), index=s.index)

    return (s - min_value) / (max_value - min_value)


def _normalize_abc_class(value):
    text = str(value).strip().upper()
    if text in ["A", "B", "C"]:
        return text
    return "C"


def _abc_score(value):
    return ABC_SCORE_MAP.get(_normalize_abc_class(value), 45)


def _make_product_name_column(products):
    out = products.copy()
    if "product_name" not in out.columns:
        if "inventory_product_name" in out.columns:
            out["product_name"] = out["inventory_product_name"]
        elif "상품명" in out.columns:
            out["product_name"] = out["상품명"]
        else:
            out["product_name"] = out.get("product_id", out.index).astype(str)
    return out


def _make_inventory_base(inventory, products=None):
    if inventory is None or inventory.empty:
        return pd.DataFrame()

    inv = inventory.copy()

    if "product_name" not in inv.columns:
        if "inventory_product_name" in inv.columns:
            inv["product_name"] = inv["inventory_product_name"]
        elif "상품명" in inv.columns:
            inv["product_name"] = inv["상품명"]
        elif products is not None and not products.empty and "product_id" in inv.columns and "product_id" in products.columns:
            product_cols = ["product_id"]
            for col in ["product_name", "category", "unit_cost", "unit_price", "ABC_class"]:
                if col in products.columns and col not in product_cols:
                    product_cols.append(col)
            inv = inv.merge(products[product_cols].drop_duplicates("product_id"), on="product_id", how="left")
        else:
            inv["product_name"] = inv.get("product_id", inv.index).astype(str)

    if "store_name" not in inv.columns:
        if "source_store" in inv.columns:
            inv["store_name"] = inv["source_store"]
        elif "점포명" in inv.columns:
            inv["store_name"] = inv["점포명"]
        else:
            inv["store_name"] = inv.get("store_id", inv.index).astype(str)

    if "category" not in inv.columns:
        if "inventory_category" in inv.columns:
            inv["category"] = inv["inventory_category"]
        elif products is not None and not products.empty and "product_id" in inv.columns and "product_id" in products.columns and "category" in products.columns:
            inv = inv.merge(products[["product_id", "category"]].drop_duplicates("product_id"), on="product_id", how="left", suffixes=("", "_product"))
        else:
            inv["category"] = "전체"

    for col in [
        "current_stock",
        "quantity",
        "stock_qty",
        "dead_stock_qty",
        "demand_qty",
        "avg_daily_sales",
        "days_to_expiry",
        "unit_cost",
        "unit_price",
        "disposal_cost_per_unit",
        "recent_7_sales",
        "recent_30_sales",
        "avg_inventory",
        "turnover_rate",
        "days_inventory_on_hand",
        "safety_stock",
        "reorder_point",
        "expiry_risk_score",
        "expiry_priority_score",
    ]:
        if col in inv.columns:
            inv[col] = pd.to_numeric(inv[col], errors="coerce")

    if "current_stock" not in inv.columns:
        stock_col = _first_existing_column(inv, ["quantity", "stock_qty", "재고수량"])
        inv["current_stock"] = _safe_numeric(inv[stock_col], 0) if stock_col else 0

    if "quantity" not in inv.columns:
        inv["quantity"] = inv["current_stock"]

    if "stock_qty" not in inv.columns:
        inv["stock_qty"] = inv["current_stock"]

    if "dead_stock_qty" not in inv.columns:
        inv["dead_stock_qty"] = (pd.to_numeric(inv["current_stock"], errors="coerce").fillna(0) * 0.3).round(0)

    if "demand_qty" not in inv.columns:
        inv["demand_qty"] = 0

    if "avg_inventory" not in inv.columns:
        inv["avg_inventory"] = pd.to_numeric(inv["current_stock"], errors="coerce").fillna(0).replace(0, 1)

    if "recent_30_sales" not in inv.columns:
        sales_col = _first_existing_column(inv, ["sales_30d", "sales_30", "최근30일판매량"])
        if sales_col:
            inv["recent_30_sales"] = _safe_numeric(inv[sales_col], 0)
        elif "avg_daily_sales" in inv.columns:
            inv["recent_30_sales"] = _safe_numeric(inv["avg_daily_sales"], 0) * 30
        else:
            inv["recent_30_sales"] = 0

    if "avg_daily_sales" not in inv.columns:
        inv["avg_daily_sales"] = _safe_numeric(inv["recent_30_sales"], 0) / 30

    if "turnover_rate" not in inv.columns:
        avg_inventory = _safe_numeric(inv["avg_inventory"], 0).replace(0, pd.NA)
        inv["turnover_rate"] = (_safe_numeric(inv["recent_30_sales"], 0) / avg_inventory).fillna(0)

    if "days_inventory_on_hand" not in inv.columns:
        avg_daily_sales = _safe_numeric(inv["avg_daily_sales"], 0).replace(0, pd.NA)
        inv["days_inventory_on_hand"] = (_safe_numeric(inv["current_stock"], 0) / avg_daily_sales).fillna(999)

    if "unit_price" not in inv.columns:
        inv["unit_price"] = 0

    if "unit_cost" not in inv.columns:
        inv["unit_cost"] = 0

    if "ABC_class" not in inv.columns:
        if products is not None and not products.empty and "product_id" in inv.columns and "product_id" in products.columns and "ABC_class" in products.columns:
            inv = inv.merge(products[["product_id", "ABC_class"]].drop_duplicates("product_id"), on="product_id", how="left", suffixes=("", "_product"))
            if "ABC_class_product" in inv.columns:
                inv["ABC_class"] = inv["ABC_class"].fillna(inv["ABC_class_product"])
        else:
            inv["ABC_class"] = "C"

    inv["ABC_class"] = inv["ABC_class"].apply(_normalize_abc_class)
    inv["abc_score"] = inv["ABC_class"].apply(_abc_score)

    return inv


def analyze_abc(products, inventory):
    inv = _make_inventory_base(inventory, products)

    if inv.empty:
        return pd.DataFrame(), pd.DataFrame()

    if "sales_amount_30" not in inv.columns:
        inv["sales_amount_30"] = _safe_numeric(inv["recent_30_sales"], 0) * _safe_numeric(inv["unit_price"], 0)

    if "stock_value" not in inv.columns:
        inv["stock_value"] = _safe_numeric(inv["current_stock"], 0) * _safe_numeric(inv["unit_cost"], 0)

    product_abc = (
        inv.groupby(["product_name", "category", "ABC_class"], dropna=False)
        .agg(
            sales_amount_30=("sales_amount_30", "sum"),
            stock_value=("stock_value", "sum"),
            current_stock=("current_stock", "sum"),
            recent_30_sales=("recent_30_sales", "sum"),
            abc_score=("abc_score", "max"),
        )
        .reset_index()
    )

    if product_abc["sales_amount_30"].sum() > 0:
        product_abc = product_abc.sort_values("sales_amount_30", ascending=False).reset_index(drop=True)
        total_sales = product_abc["sales_amount_30"].sum()
        product_abc["sales_share_pct"] = (product_abc["sales_amount_30"] / total_sales * 100).round(1)
        product_abc["cumulative_share_pct"] = product_abc["sales_share_pct"].cumsum().round(1)
    else:
        product_abc["sales_share_pct"] = 0
        product_abc["cumulative_share_pct"] = 0

    abc_summary = (
        product_abc.groupby("ABC_class", dropna=False)
        .agg(
            product_count=("product_name", "nunique"),
            sales_amount_30=("sales_amount_30", "sum"),
            stock_value=("stock_value", "sum"),
            current_stock=("current_stock", "sum"),
        )
        .reset_index()
        .sort_values("ABC_class")
    )

    return product_abc, abc_summary


def analyze_turnover(inventory, products=None):
    inv = _make_inventory_base(inventory, products)

    if inv.empty:
        return pd.DataFrame(), pd.DataFrame()

    turnover = inv.copy()

    turnover["turnover_rate"] = _safe_numeric(turnover["turnover_rate"], 0)
    turnover["days_inventory_on_hand"] = _safe_numeric(turnover["days_inventory_on_hand"], 999)

    def classify_turnover(row):
        group = str(row.get("turnover_group", ""))
        if "고" in group:
            return "고회전"
        if "저" in group:
            return "저회전"

        rate = _safe_numeric(row.get("turnover_rate"), 0)
        days = _safe_numeric(row.get("days_inventory_on_hand"), 999)

        if rate >= 2.0 or days <= 10:
            return "고회전"
        if rate >= 0.8 or days <= 25:
            return "중회전"
        return "저회전"

    turnover["turnover_group_final"] = turnover.apply(classify_turnover, axis=1)

    turnover["turnover_risk_score"] = (
        (1 - _normalize_series(turnover["turnover_rate"]).fillna(0)) * 45
        + _normalize_series(turnover["days_inventory_on_hand"]).fillna(0) * 55
    ).round(1)

    turnover["turnover_action"] = turnover["turnover_group_final"].map(
        {
            "고회전": "판매 유지/보충 관찰",
            "중회전": "할인 또는 소량 재배치 검토",
            "저회전": "재배치·프로모션 우선 검토",
        }
    ).fillna("검토")

    turnover_summary = (
        turnover.groupby("turnover_group_final")
        .agg(
            inventory_count=("inventory_id", "count") if "inventory_id" in turnover.columns else ("product_name", "count"),
            avg_turnover_rate=("turnover_rate", "mean"),
            avg_days_inventory_on_hand=("days_inventory_on_hand", "mean"),
            avg_turnover_risk_score=("turnover_risk_score", "mean"),
        )
        .reset_index()
    )

    for col in ["avg_turnover_rate", "avg_days_inventory_on_hand", "avg_turnover_risk_score"]:
        if col in turnover_summary.columns:
            turnover_summary[col] = turnover_summary[col].round(1)

    return turnover, turnover_summary


def analyze_expiry_risk(inventory, products=None):
    inv = _make_inventory_base(inventory, products)

    if inv.empty:
        return pd.DataFrame(), pd.DataFrame()

    risk = inv.copy()

    if "days_to_expiry" not in risk.columns:
        risk["days_to_expiry"] = 999

    days_to_expiry = _safe_numeric(risk["days_to_expiry"], 999)
    current_stock = _safe_numeric(risk["current_stock"], 0)
    demand_qty = _safe_numeric(risk["demand_qty"], 0)
    days_on_hand = _safe_numeric(risk["days_inventory_on_hand"], 0)

    stock_pressure = current_stock / (current_stock + demand_qty + 1)
    expiry_pressure = ((14 - days_to_expiry).clip(lower=0) / 14).clip(0, 1)
    holding_pressure = (days_on_hand / 30).clip(0, 1)

    if "expiry_risk_score" not in risk.columns or risk["expiry_risk_score"].isna().all():
        risk["expiry_risk_score"] = (
            expiry_pressure * 55
            + stock_pressure * 25
            + holding_pressure * 20
        ).round(1).clip(0, 100)
    else:
        risk["expiry_risk_score"] = _safe_numeric(risk["expiry_risk_score"], 0).clip(0, 100)

    if "expiry_priority_score" not in risk.columns:
        risk["expiry_priority_score"] = (
            risk["expiry_risk_score"] * 0.65
            + risk["abc_score"] * 0.15
            + _normalize_series(risk["dead_stock_qty"]).fillna(0) * 20
        ).round(1).clip(0, 100)
    else:
        risk["expiry_priority_score"] = _safe_numeric(risk["expiry_priority_score"], 0).clip(0, 100)

    def classify_risk(score):
        score = _safe_numeric(score, 0)
        if score >= 80:
            return "긴급"
        if score >= 60:
            return "주의"
        return "관찰"

    def action_from_risk(row):
        status = row.get("expiry_risk_level", "")
        if status == "긴급":
            return "즉시 재배치/할인"
        if status == "주의":
            return "프로모션 또는 근거리 재배치"
        return "보류 또는 일반 판매"

    risk["expiry_risk_level"] = risk["expiry_risk_score"].apply(classify_risk)
    risk["expiry_action"] = risk.apply(action_from_risk, axis=1)

    expiry_summary = (
        risk.groupby("expiry_risk_level")
        .agg(
            inventory_count=("inventory_id", "count") if "inventory_id" in risk.columns else ("product_name", "count"),
            avg_expiry_risk_score=("expiry_risk_score", "mean"),
            avg_days_to_expiry=("days_to_expiry", "mean"),
            total_dead_stock_qty=("dead_stock_qty", "sum"),
        )
        .reset_index()
    )

    for col in ["avg_expiry_risk_score", "avg_days_to_expiry", "total_dead_stock_qty"]:
        if col in expiry_summary.columns:
            expiry_summary[col] = pd.to_numeric(expiry_summary[col], errors="coerce").fillna(0).round(1)

    return risk, expiry_summary


def build_dqn_state_features(inventory_analysis):
    if inventory_analysis is None or inventory_analysis.empty:
        return pd.DataFrame()

    df = inventory_analysis.copy()

    for col in ["expiry_risk_score", "turnover_rate", "days_inventory_on_hand", "current_stock", "dead_stock_qty", "abc_score"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    dqn = pd.DataFrame()
    dqn["store_name"] = df.get("store_name", "-")
    dqn["product_name"] = df.get("product_name", "-")
    dqn["ABC_class"] = df.get("ABC_class", "C")
    dqn["dqn_abc_score"] = (df["abc_score"] / 100).round(3)
    dqn["dqn_turnover_norm"] = _normalize_series(df["turnover_rate"]).round(3)
    dqn["dqn_days_inventory_norm"] = _normalize_series(df["days_inventory_on_hand"]).round(3)
    dqn["dqn_expiry_risk_norm"] = (df["expiry_risk_score"] / 100).clip(0, 1).round(3)
    dqn["dqn_dead_stock_norm"] = _normalize_series(df["dead_stock_qty"]).round(3)
    dqn["dqn_stock_pressure_norm"] = _normalize_series(df["current_stock"]).round(3)

    return dqn


def analyze_industrial_algorithms(stores, products, inventory):
    """
    Varo 샘플 8차부터 사용하는 산업경영공학 분석 묶음.

    구현 범위:
    1) ABC 분석
    2) 재고 회전율 분석
    3) 폐기 위험도 점수
    4) DQN state로 연결할 숫자 feature
    """
    product_abc, abc_summary = analyze_abc(products, inventory)
    turnover_analysis, turnover_summary = analyze_turnover(inventory, products)
    expiry_analysis, expiry_summary = analyze_expiry_risk(inventory, products)

    if expiry_analysis is not None and not expiry_analysis.empty:
        inventory_analysis = expiry_analysis.copy()

        keep_turnover_cols = [
            "store_name",
            "product_name",
            "turnover_group_final",
            "turnover_risk_score",
            "turnover_action",
        ]
        if not turnover_analysis.empty:
            merge_cols = [c for c in keep_turnover_cols if c in turnover_analysis.columns]
            inventory_analysis = inventory_analysis.merge(
                turnover_analysis[merge_cols].drop_duplicates(["store_name", "product_name"]),
                on=["store_name", "product_name"],
                how="left",
            )

        inventory_analysis["industrial_priority_score"] = (
            pd.to_numeric(inventory_analysis["expiry_risk_score"], errors="coerce").fillna(0) * 0.45
            + pd.to_numeric(inventory_analysis.get("turnover_risk_score", 0), errors="coerce").fillna(0) * 0.25
            + pd.to_numeric(inventory_analysis["abc_score"], errors="coerce").fillna(45) * 0.15
            + _normalize_series(inventory_analysis["dead_stock_qty"]).fillna(0) * 15
        ).round(1).clip(0, 100)

        def priority_grade(score):
            score = _safe_numeric(score, 0)
            if score >= 80:
                return "최적"
            if score >= 60:
                return "권장"
            return "검토"

        inventory_analysis["industrial_recommendation_grade"] = inventory_analysis["industrial_priority_score"].apply(priority_grade)
    else:
        inventory_analysis = pd.DataFrame()

    dqn_state_features = build_dqn_state_features(inventory_analysis)

    if inventory_analysis.empty:
        summary_metrics = {
            "total_inventory_rows": 0,
            "urgent_expiry_count": 0,
            "low_turnover_count": 0,
            "a_class_count": 0,
            "avg_industrial_priority_score": 0,
        }
    else:
        summary_metrics = {
            "total_inventory_rows": int(len(inventory_analysis)),
            "urgent_expiry_count": int((inventory_analysis.get("expiry_risk_level", "") == "긴급").sum()),
            "low_turnover_count": int((inventory_analysis.get("turnover_group_final", "") == "저회전").sum()),
            "a_class_count": int((inventory_analysis.get("ABC_class", "") == "A").sum()),
            "avg_industrial_priority_score": float(pd.to_numeric(inventory_analysis["industrial_priority_score"], errors="coerce").fillna(0).mean().round(1)),
        }

    return {
        "product_abc": product_abc,
        "abc_summary": abc_summary,
        "turnover_analysis": turnover_analysis,
        "turnover_summary": turnover_summary,
        "expiry_analysis": expiry_analysis,
        "expiry_summary": expiry_summary,
        "inventory_analysis": inventory_analysis,
        "dqn_state_features": dqn_state_features,
        "summary_metrics": summary_metrics,
    }


def enrich_recommendations_with_industrial_features(final_recommendations, industrial_result):
    """최종 추천 후보에 ABC/회전율/폐기위험도 feature를 붙인다."""
    if final_recommendations is None or final_recommendations.empty:
        return final_recommendations

    if not industrial_result:
        return final_recommendations

    inventory_analysis = industrial_result.get("inventory_analysis")
    if inventory_analysis is None or inventory_analysis.empty:
        return final_recommendations

    df = final_recommendations.copy()
    features = inventory_analysis.copy()

    if "product_name" not in features.columns or "store_name" not in features.columns:
        return df

    feature_cols = [
        "store_name",
        "product_name",
        "ABC_class",
        "abc_score",
        "turnover_rate",
        "days_inventory_on_hand",
        "turnover_group_final",
        "turnover_risk_score",
        "expiry_risk_score",
        "expiry_priority_score",
        "expiry_risk_level",
        "industrial_priority_score",
        "industrial_recommendation_grade",
        "dead_stock_qty",
        "current_stock",
    ]
    features = features[[c for c in feature_cols if c in features.columns]].copy()
    features = features.rename(columns={"store_name": "source_store"})

    numeric_aggs = {
        "abc_score": "max",
        "turnover_rate": "mean",
        "days_inventory_on_hand": "max",
        "turnover_risk_score": "max",
        "expiry_risk_score": "max",
        "expiry_priority_score": "max",
        "industrial_priority_score": "max",
        "dead_stock_qty": "sum",
        "current_stock": "sum",
    }
    agg_map = {}
    for col, func in numeric_aggs.items():
        if col in features.columns:
            agg_map[col] = func
    for col in ["ABC_class", "turnover_group_final", "expiry_risk_level", "industrial_recommendation_grade"]:
        if col in features.columns:
            agg_map[col] = "first"

    grouped = features.groupby(["source_store", "product_name"], dropna=False).agg(agg_map).reset_index()

    df = df.merge(grouped, on=["source_store", "product_name"], how="left")

    return df
