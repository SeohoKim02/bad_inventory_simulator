
import math
import pandas as pd
import numpy as np


def _safe_numeric(value, default=0):
    try:
        if isinstance(value, pd.Series):
            return pd.to_numeric(value, errors="coerce").fillna(default)

        if pd.isna(value):
            return default

        return float(value)
    except Exception:
        return default


def _first_col(df, candidates, default=None):
    for col in candidates:
        if col in df.columns:
            return col
    return default


def _coalesce(df, target, candidates, default=None):
    existing = [c for c in candidates if c in df.columns]

    if target in df.columns:
        existing = [target] + [c for c in existing if c != target]

    if not existing:
        df[target] = default
        return df

    value = df[existing[0]]

    if isinstance(value, pd.DataFrame):
        value = value.bfill(axis=1).iloc[:, 0]

    for col in existing[1:]:
        next_value = df[col]

        if isinstance(next_value, pd.DataFrame):
            next_value = next_value.bfill(axis=1).iloc[:, 0]

        value = value.where(value.notna(), next_value)

    df[target] = value.fillna(default)
    return df


def _dedupe_columns(df):
    if not df.columns.duplicated().any():
        return df

    result = pd.DataFrame(index=df.index)

    for col in dict.fromkeys(df.columns):
        same = df.loc[:, df.columns == col]

        if isinstance(same, pd.DataFrame) and same.shape[1] > 1:
            result[col] = same.bfill(axis=1).iloc[:, 0]
        elif isinstance(same, pd.DataFrame):
            result[col] = same.iloc[:, 0]
        else:
            result[col] = same

    return result


def _haversine_km(lat1, lon1, lat2, lon2):
    try:
        lat1 = float(lat1)
        lon1 = float(lon1)
        lat2 = float(lat2)
        lon2 = float(lon2)
    except Exception:
        return np.nan

    r = 6371
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )

    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _identify_frames(args, kwargs):
    candidate_df = kwargs.get("cutline_result")
    stores = kwargs.get("stores")
    routes = kwargs.get("routes")

    for df in args:
        if not isinstance(df, pd.DataFrame):
            continue

        cols = set(df.columns)

        if candidate_df is None and (
            "product_id" in cols
            and (
                "store_id" in cols
                or "source_store" in cols
                or "store_name" in cols
            )
            and (
                "stock_qty" in cols
                or "current_stock" in cols
                or "quantity" in cols
                or "dead_stock_qty" in cols
            )
        ):
            candidate_df = df
            continue

        if stores is None and (
            "store_id" in cols
            and "store_name" in cols
            and ("latitude" in cols or "longitude" in cols)
        ):
            stores = df
            continue

        if routes is None and (
            "distance_km" in cols
            or "transport_cost" in cols
            or "from_id" in cols
            or "to_id" in cols
            or "from_name" in cols
            or "to_name" in cols
        ):
            routes = df
            continue

    return candidate_df, stores, routes


def _prepare_candidates(df):
    df = df.copy()
    df = _dedupe_columns(df)

    if "product_id" not in df.columns:
        df["product_id"] = df.index.astype(str)

    if "store_id" not in df.columns:
        if "source_store_id" in df.columns:
            df["store_id"] = df["source_store_id"]
        else:
            df["store_id"] = df.index.astype(str)

    df = _coalesce(
        df,
        "store_name",
        ["store_name", "source_store", "target_store", "retailer_name"],
        "-",
    )

    df = _coalesce(
        df,
        "product_name",
        [
            "product_name",
            "product_name_x",
            "product_name_y",
            "inventory_product_name",
        ],
        "상품명 없음",
    )

    df = _coalesce(
        df,
        "category",
        [
            "category",
            "category_x",
            "category_y",
            "inventory_category",
        ],
        "기타",
    )

    qty_col = _first_col(
        df,
        ["stock_qty", "current_stock", "quantity", "inventory_qty", "qty"],
        None,
    )

    if qty_col is None:
        df["stock_qty"] = 0
    else:
        df["stock_qty"] = _safe_numeric(df[qty_col], 0)

    if "current_stock" not in df.columns:
        df["current_stock"] = df["stock_qty"]

    if "sales_30d" not in df.columns and "sales_30" in df.columns:
        df["sales_30d"] = df["sales_30"]

    if "sales_30" not in df.columns and "sales_30d" in df.columns:
        df["sales_30"] = df["sales_30d"]

    if "sales_30d" not in df.columns:
        # 없으면 demand_qty 또는 평균판매량으로 추정
        if "sales_30" in df.columns:
            df["sales_30d"] = df["sales_30"]
        elif "demand_qty" in df.columns:
            df["sales_30d"] = _safe_numeric(df["demand_qty"], 0) * 6
        elif "avg_daily_sales" in df.columns:
            df["sales_30d"] = _safe_numeric(df["avg_daily_sales"], 0) * 30
        else:
            df["sales_30d"] = 0

    if "sales_30" not in df.columns:
        df["sales_30"] = df["sales_30d"]

    df["sales_30d"] = _safe_numeric(df["sales_30d"], 0)
    df["sales_30"] = _safe_numeric(df["sales_30"], 0)

    if "dead_stock_qty" not in df.columns:
        df["dead_stock_qty"] = np.maximum(df["stock_qty"] - df["sales_30d"], 0)
    else:
        df["dead_stock_qty"] = _safe_numeric(df["dead_stock_qty"], 0)

    if "demand_qty" not in df.columns:
        df["demand_qty"] = np.maximum(df["sales_30d"] - df["stock_qty"], 0)
    else:
        df["demand_qty"] = _safe_numeric(df["demand_qty"], 0)

    if "unit_price" not in df.columns:
        df["unit_price"] = 0

    if "unit_cost" not in df.columns:
        df["unit_cost"] = 0

    return df


def _prepare_stores(stores):
    if stores is None or stores.empty:
        return pd.DataFrame(columns=["store_id", "store_name", "latitude", "longitude", "type"])

    stores = stores.copy()
    stores = _dedupe_columns(stores)

    for col in ["store_id", "store_name", "latitude", "longitude"]:
        if col not in stores.columns:
            stores[col] = np.nan

    if "type" not in stores.columns:
        stores["type"] = "STORE"

    return stores


def _prepare_routes(routes):
    if routes is None or routes.empty:
        return pd.DataFrame()

    routes = routes.copy()
    routes = _dedupe_columns(routes)

    distance_col = _first_col(
        routes,
        [
            "distance_km",
            "route_distance_km",
            "direct_distance_km",
            "network_distance_km",
            "total_distance_km",
        ],
        None,
    )

    cost_col = _first_col(
        routes,
        [
            "transport_cost",
            "estimated_cost",
            "direct_cost",
            "transfer_cost",
            "network_cost",
        ],
        None,
    )

    time_col = _first_col(
        routes,
        ["travel_time_min", "route_time_min", "time_min", "network_time_min"],
        None,
    )

    if distance_col is None:
        routes["distance_km"] = np.nan
        distance_col = "distance_km"

    if cost_col is None:
        routes["transport_cost"] = _safe_numeric(routes[distance_col], 0) * 900
        cost_col = "transport_cost"

    if time_col is None:
        routes["travel_time_min"] = _safe_numeric(routes[distance_col], 0) / 30 * 60
        time_col = "travel_time_min"

    routes["_distance_km"] = _safe_numeric(routes[distance_col], np.nan)
    routes["_transport_cost"] = _safe_numeric(routes[cost_col], np.nan)
    routes["_time_min"] = _safe_numeric(routes[time_col], np.nan)

    return routes


def _lookup_route(routes, from_id=None, to_id=None, from_name=None, to_name=None):
    if routes is None or routes.empty:
        return None

    cond = pd.Series([True] * len(routes), index=routes.index)

    if from_id is not None and "from_id" in routes.columns:
        cond = cond & (routes["from_id"].astype(str) == str(from_id))

    if to_id is not None and "to_id" in routes.columns:
        cond = cond & (routes["to_id"].astype(str) == str(to_id))

    if from_name is not None and "from_name" in routes.columns:
        cond = cond & (routes["from_name"].astype(str) == str(from_name))

    if to_name is not None and "to_name" in routes.columns:
        cond = cond & (routes["to_name"].astype(str) == str(to_name))

    matched = routes[cond].copy()

    if matched.empty:
        return None

    matched = matched.sort_values("_distance_km", na_position="last")
    return matched.iloc[0]


def _route_cost_distance(
    routes,
    stores,
    source_store_id,
    target_store_id,
    source_store_name,
    target_store_name,
):
    route = _lookup_route(
        routes,
        from_id=source_store_id,
        to_id=target_store_id,
        from_name=source_store_name,
        to_name=target_store_name,
    )

    if route is not None:
        distance = _safe_numeric(route.get("_distance_km"), np.nan)
        cost = _safe_numeric(route.get("_transport_cost"), np.nan)
        time_min = _safe_numeric(route.get("_time_min"), np.nan)

        if pd.isna(cost) and not pd.isna(distance):
            cost = distance * 900

        return distance, cost, time_min

    # route가 없으면 stores 좌표로 추정
    if stores is not None and not stores.empty:
        source = stores[stores["store_id"].astype(str) == str(source_store_id)]
        target = stores[stores["store_id"].astype(str) == str(target_store_id)]

        if not source.empty and not target.empty:
            distance = _haversine_km(
                source.iloc[0]["latitude"],
                source.iloc[0]["longitude"],
                target.iloc[0]["latitude"],
                target.iloc[0]["longitude"],
            )

            if not pd.isna(distance):
                distance = round(distance * 1.35, 2)
                return distance, round(1500 + distance * 900, 0), round(distance / 30 * 60, 0)

    return np.nan, np.nan, np.nan


def _best_dc_via_cost(routes, stores, source_store_id, target_store_id, source_store_name, target_store_name):
    if stores is None or stores.empty:
        return np.nan, np.nan, np.nan, "-"

    dc_rows = stores[stores["type"].astype(str).str.upper().str.contains("DC", na=False)]

    if dc_rows.empty:
        return np.nan, np.nan, np.nan, "-"

    candidates = []

    for _, dc in dc_rows.iterrows():
        dc_id = dc.get("store_id")
        dc_name = dc.get("store_name", dc_id)

        d1, c1, t1 = _route_cost_distance(
            routes,
            stores,
            source_store_id,
            dc_id,
            source_store_name,
            dc_name,
        )

        d2, c2, t2 = _route_cost_distance(
            routes,
            stores,
            dc_id,
            target_store_id,
            dc_name,
            target_store_name,
        )

        if pd.isna(d1) or pd.isna(d2):
            continue

        candidates.append(
            {
                "dc_name": dc_name,
                "distance": d1 + d2,
                "cost": (0 if pd.isna(c1) else c1) + (0 if pd.isna(c2) else c2),
                "time": (0 if pd.isna(t1) else t1) + (0 if pd.isna(t2) else t2),
            }
        )

    if not candidates:
        return np.nan, np.nan, np.nan, "-"

    best = sorted(candidates, key=lambda x: x["cost"])[0]
    return best["distance"], best["cost"], best["time"], best["dc_name"]


def analyze_direct_vs_dc_transfer(*args, **kwargs):
    """
    점포 간 직접 이동과 DC 경유 이동을 비교하는 함수.

    대형 데이터 대응:
    - sales_30d가 없으면 sales_30, demand_qty, avg_daily_sales로 자동 생성
    - 각 상품별로 source 후보와 target 후보를 제한해서 과도한 조합 생성을 방지
    - direct route가 없으면 좌표 기반으로 거리/비용을 추정
    - DC 경유 비용도 가능한 경우 함께 계산
    """
    candidate_df, stores, routes = _identify_frames(args, kwargs)

    if candidate_df is None or candidate_df.empty:
        return pd.DataFrame()

    candidates = _prepare_candidates(candidate_df)
    stores = _prepare_stores(stores)
    routes = _prepare_routes(routes)

    # stores 이름/좌표 보강
    if not stores.empty:
        store_name_map = stores.set_index(stores["store_id"].astype(str))["store_name"].to_dict()
        candidates["store_name"] = candidates.apply(
            lambda row: store_name_map.get(str(row["store_id"]), row.get("store_name", "-")),
            axis=1,
        )

    results = []

    # 대형 데이터 성능 보호: 상품별 source/target 상위 후보만 비교
    for product_id, group in candidates.groupby("product_id"):
        group = group.copy()

        product_name = group["product_name"].iloc[0] if "product_name" in group.columns else str(product_id)
        category = group["category"].iloc[0] if "category" in group.columns else "기타"

        source_candidates = group[
            (group["dead_stock_qty"] > 0)
            | (group["stock_qty"] > group["sales_30d"])
        ].copy()

        target_candidates = group[
            (group["demand_qty"] > 0)
            | (group["stock_qty"] < group["sales_30d"])
        ].copy()

        if source_candidates.empty:
            source_candidates = group.sort_values("stock_qty", ascending=False).head(3)

        if target_candidates.empty:
            target_candidates = group.sort_values("stock_qty", ascending=True).head(3)

        source_candidates = source_candidates.sort_values(
            ["dead_stock_qty", "stock_qty"],
            ascending=[False, False],
            na_position="last",
        ).head(6)

        target_candidates = target_candidates.sort_values(
            ["demand_qty", "stock_qty"],
            ascending=[False, True],
            na_position="last",
        ).head(6)

        for _, source in source_candidates.iterrows():
            for _, target in target_candidates.iterrows():
                if str(source["store_id"]) == str(target["store_id"]):
                    continue

                source_surplus = max(
                    _safe_numeric(source.get("dead_stock_qty"), 0),
                    _safe_numeric(source.get("stock_qty"), 0) - _safe_numeric(source.get("sales_30d"), 0),
                    0,
                )

                target_shortage = max(
                    _safe_numeric(target.get("demand_qty"), 0),
                    _safe_numeric(target.get("sales_30d"), 0) - _safe_numeric(target.get("stock_qty"), 0),
                    0,
                )

                suggested_qty = int(max(0, min(source_surplus, target_shortage)))

                if suggested_qty <= 0:
                    suggested_qty = int(max(1, min(_safe_numeric(source.get("stock_qty"), 0), 10)))

                source_store_id = source.get("store_id")
                target_store_id = target.get("store_id")
                source_store = source.get("store_name", source_store_id)
                target_store = target.get("store_name", target_store_id)

                direct_distance, direct_cost, direct_time = _route_cost_distance(
                    routes,
                    stores,
                    source_store_id,
                    target_store_id,
                    source_store,
                    target_store,
                )

                via_distance, via_cost, via_time, via_dc_name = _best_dc_via_cost(
                    routes,
                    stores,
                    source_store_id,
                    target_store_id,
                    source_store,
                    target_store,
                )

                if pd.isna(direct_cost) and pd.isna(via_cost):
                    continue

                if pd.isna(via_cost):
                    recommended_path = "직접 이동 추천"
                    estimated_cost = direct_cost
                    recommended_distance = direct_distance
                    recommended_time = direct_time
                    path_reason = "DC 경유 경로가 없어 점포 간 직접 이동을 추천합니다."
                elif pd.isna(direct_cost):
                    recommended_path = "DC 경유 추천"
                    estimated_cost = via_cost
                    recommended_distance = via_distance
                    recommended_time = via_time
                    path_reason = "직접 이동 경로가 없어 DC 경유 이동을 추천합니다."
                elif direct_cost <= via_cost:
                    recommended_path = "직접 이동 추천"
                    estimated_cost = direct_cost
                    recommended_distance = direct_distance
                    recommended_time = direct_time
                    path_reason = "직접 이동 비용이 DC 경유보다 낮아 직접 이동을 추천합니다."
                else:
                    recommended_path = "DC 경유 추천"
                    estimated_cost = via_cost
                    recommended_distance = via_distance
                    recommended_time = via_time
                    path_reason = "DC 경유 비용이 직접 이동보다 낮아 DC 경유를 추천합니다."

                results.append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "category": category,
                        "source_store_id": source_store_id,
                        "target_store_id": target_store_id,
                        "source_store": source_store,
                        "target_store": target_store,
                        "source_stock_qty": _safe_numeric(source.get("stock_qty"), 0),
                        "target_stock_qty": _safe_numeric(target.get("stock_qty"), 0),
                        "sales_30d": _safe_numeric(source.get("sales_30d"), 0),
                        "sales_30": _safe_numeric(source.get("sales_30"), 0),
                        "source_dead_stock_qty": source_surplus,
                        "target_shortage_qty": target_shortage,
                        "suggested_qty": suggested_qty,
                        "direct_distance_km": direct_distance,
                        "direct_cost": direct_cost,
                        "direct_time_min": direct_time,
                        "via_dc_name": via_dc_name,
                        "via_distance_km": via_distance,
                        "via_cost": via_cost,
                        "via_time_min": via_time,
                        "recommended_path": recommended_path,
                        "estimated_cost": estimated_cost,
                        "recommended_distance_km": recommended_distance,
                        "recommended_time_min": recommended_time,
                        "transfer_reason": path_reason,
                        "reason": path_reason,
                    }
                )

    result = pd.DataFrame(results)

    if result.empty:
        return result

    result["estimated_cost"] = _safe_numeric(result["estimated_cost"], np.nan)
    result["suggested_qty"] = _safe_numeric(result["suggested_qty"], 0)
    result["cost_per_unit"] = result["estimated_cost"] / result["suggested_qty"].replace(0, np.nan)
    result["cost_per_unit"] = result["cost_per_unit"].fillna(result["estimated_cost"])

    result = result.sort_values(
        ["estimated_cost", "suggested_qty"],
        ascending=[True, False],
        na_position="last",
    )

    return result.reset_index(drop=True)
