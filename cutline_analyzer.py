import pandas as pd


def analyze_product_distance_cutline(products, inventory, dc_routes):
    products_data = products.copy()
    inventory_data = inventory.copy()
    routes_data = dc_routes.copy()

    # 재고 데이터에 상품 정보 붙이기
    inventory_products = inventory_data.merge(
        products_data[
            [
                "product_id",
                "product_name",
                "category",
                "distance_cutline_km",
            ]
        ],
        on="product_id",
        how="left",
    )

    # 점포별 재고 데이터에 DC-점포 경로 정보 붙이기
    route_eval = inventory_products.merge(
        routes_data[
            [
                "dc_id",
                "dc_name",
                "retailer_id",
                "retailer_name",
                "distance_km",
                "travel_time_min",
                "cost_per_km",
                "transport_cost",
            ]
        ],
        left_on="store_id",
        right_on="retailer_id",
        how="left",
    )

    # 거리 컷라인 이내인지 판별
    route_eval["is_within_cutline"] = (
        route_eval["distance_km"] <= route_eval["distance_cutline_km"]
    )

    route_eval["cutline_status"] = route_eval["is_within_cutline"].apply(
        lambda x: "가능" if x else "불가능"
    )

    # 컷라인 안에 들어오는 경로만 필터링
    valid_routes = route_eval[route_eval["is_within_cutline"] == True].copy()

    if valid_routes.empty:
        best_valid_routes = pd.DataFrame()
    else:
        # 상품-점포별로 운송비가 가장 낮은 DC 선택
        best_valid_routes = (
            valid_routes.sort_values("transport_cost")
            .groupby(["store_id", "product_id"])
            .first()
            .reset_index()
        )

    # 이동 불가능 품목 찾기
    all_items = inventory_products[
        [
            "store_id",
            "product_id",
            "product_name",
            "category",
            "stock_qty",
            "sales_30d",
            "distance_cutline_km",
        ]
    ].drop_duplicates()

    if best_valid_routes.empty:
        no_valid_items = all_items.copy()
    else:
        valid_keys = best_valid_routes[["store_id", "product_id"]].drop_duplicates()

        no_valid_items = all_items.merge(
            valid_keys,
            on=["store_id", "product_id"],
            how="left",
            indicator=True,
        )

        no_valid_items = no_valid_items[no_valid_items["_merge"] == "left_only"]
        no_valid_items = no_valid_items.drop(columns=["_merge"])

    return route_eval, best_valid_routes, no_valid_items
