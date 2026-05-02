import pandas as pd


def analyze_dc_retailer_routes(stores, routes):
    stores_data = stores.copy()
    routes_data = routes.copy()

    # DC와 점포 구분
    dc_ids = stores_data[stores_data["type"].str.upper() == "DC"]["store_id"].tolist()
    retailer_ids = stores_data[
        stores_data["type"].str.lower().isin(["retailer", "store", "점포"])
    ]["store_id"].tolist()

    store_name_map = dict(zip(stores_data["store_id"], stores_data["store_name"]))

    result_rows = []

    for _, row in routes_data.iterrows():
        from_id = row["from_id"]
        to_id = row["to_id"]

        # DC -> 점포 방향
        if from_id in dc_ids and to_id in retailer_ids:
            dc_id = from_id
            retailer_id = to_id

        # 점포 -> DC 방향으로 입력된 경우도 처리
        elif from_id in retailer_ids and to_id in dc_ids:
            dc_id = to_id
            retailer_id = from_id

        else:
            continue

        distance_km = row["distance_km"]
        travel_time_min = row["travel_time_min"]
        cost_per_km = row["cost_per_km"]

        transport_cost = distance_km * cost_per_km

        result_rows.append(
            {
                "dc_id": dc_id,
                "dc_name": store_name_map.get(dc_id, dc_id),
                "retailer_id": retailer_id,
                "retailer_name": store_name_map.get(retailer_id, retailer_id),
                "distance_km": distance_km,
                "travel_time_min": travel_time_min,
                "cost_per_km": cost_per_km,
                "transport_cost": transport_cost,
            }
        )

    result = pd.DataFrame(result_rows)

    if result.empty:
        return result, result

    # 점포별로 가장 운송비가 낮은 DC 선택
    best_dc_by_retailer = (
        result.sort_values("transport_cost")
        .groupby("retailer_id")
        .first()
        .reset_index()
    )

    return result, best_dc_by_retailer
