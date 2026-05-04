import pandas as pd
from datetime import time


def time_to_minutes(value):
    if pd.isna(value):
        return None

    if isinstance(value, time):
        return value.hour * 60 + value.minute

    value_str = str(value).strip()
    parts = value_str.split(":")

    if len(parts) >= 2:
        return int(parts[0]) * 60 + int(parts[1])

    return None


def is_within_window(target_min, start_min, end_min):
    if start_min is None or end_min is None:
        return False

    return start_min <= target_min <= end_min


def minutes_to_time_text(minutes):
    minutes = int(minutes)

    if minutes >= 24 * 60:
        return "당일 초과"

    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def build_route_lookup(routes):
    route_lookup = {}

    for _, row in routes.iterrows():
        from_id = row["from_id"]
        to_id = row["to_id"]

        route_info = {
            "distance_km": row["distance_km"],
            "travel_time_min": row["travel_time_min"],
            "cost_per_km": row["cost_per_km"],
            "transport_cost": row["distance_km"] * row["cost_per_km"],
        }

        route_lookup[(from_id, to_id)] = route_info
        route_lookup[(to_id, from_id)] = route_info

    return route_lookup


def check_direct_path(
    source_id,
    target_id,
    route_lookup,
    time_start_map,
    time_end_map,
    departure_min,
):
    route = route_lookup.get((source_id, target_id))

    if route is None:
        return {
            "available": False,
            "distance_km": None,
            "travel_time_min": None,
            "cost": None,
            "arrival_min": None,
            "reason": "직접 경로 없음",
        }

    arrival_min = departure_min + route["travel_time_min"]

    source_depart_possible = is_within_window(
        departure_min,
        time_start_map.get(source_id),
        time_end_map.get(source_id),
    )

    target_arrival_possible = (
        arrival_min <= 24 * 60
        and is_within_window(
            arrival_min,
            time_start_map.get(target_id),
            time_end_map.get(target_id),
        )
    )

    available = source_depart_possible and target_arrival_possible

    if available:
        reason = "직접 이동 가능"
    elif not source_depart_possible:
        reason = "출발 점포 거래가능시간 불만족"
    else:
        reason = "도착 점포 거래가능시간 불만족"

    return {
        "available": available,
        "distance_km": route["distance_km"],
        "travel_time_min": route["travel_time_min"],
        "cost": route["transport_cost"],
        "arrival_min": arrival_min,
        "reason": reason,
    }


def check_via_dc_path(
    source_id,
    target_id,
    dc_id,
    route_lookup,
    time_start_map,
    time_end_map,
    departure_min,
):
    route_1 = route_lookup.get((source_id, dc_id))
    route_2 = route_lookup.get((dc_id, target_id))

    if route_1 is None or route_2 is None:
        return {
            "available": False,
            "distance_km": None,
            "travel_time_min": None,
            "cost": None,
            "arrival_min": None,
            "reason": "DC 경유 경로 없음",
        }

    dc_arrival_min = departure_min + route_1["travel_time_min"]
    target_arrival_min = dc_arrival_min + route_2["travel_time_min"]

    source_depart_possible = is_within_window(
        departure_min,
        time_start_map.get(source_id),
        time_end_map.get(source_id),
    )

    dc_available = (
        dc_arrival_min <= 24 * 60
        and is_within_window(
            dc_arrival_min,
            time_start_map.get(dc_id),
            time_end_map.get(dc_id),
        )
    )

    target_arrival_possible = (
        target_arrival_min <= 24 * 60
        and is_within_window(
            target_arrival_min,
            time_start_map.get(target_id),
            time_end_map.get(target_id),
        )
    )

    available = source_depart_possible and dc_available and target_arrival_possible

    total_distance = route_1["distance_km"] + route_2["distance_km"]
    total_time = route_1["travel_time_min"] + route_2["travel_time_min"]
    total_cost = route_1["transport_cost"] + route_2["transport_cost"]

    if available:
        reason = "DC 경유 이동 가능"
    elif not source_depart_possible:
        reason = "출발 점포 거래가능시간 불만족"
    elif not dc_available:
        reason = "DC 거래가능시간 불만족"
    else:
        reason = "도착 점포 거래가능시간 불만족"

    return {
        "available": available,
        "distance_km": total_distance,
        "travel_time_min": total_time,
        "cost": total_cost,
        "arrival_min": target_arrival_min,
        "reason": reason,
    }


def analyze_direct_vs_dc_transfer(stores, products, inventory, routes, departure_time):
    stores_data = stores.copy()
    products_data = products.copy()
    inventory_data = inventory.copy()
    routes_data = routes.copy()

    route_lookup = build_route_lookup(routes_data)

    dc_ids = stores_data[stores_data["type"].str.upper() == "DC"]["store_id"].tolist()

    retailer_ids = stores_data[
        stores_data["type"].str.lower().isin(["retailer", "store", "점포"])
    ]["store_id"].tolist()

    store_name_map = dict(zip(stores_data["store_id"], stores_data["store_name"]))
    product_name_map = dict(zip(products_data["product_id"], products_data["product_name"]))
    cutline_map = dict(zip(products_data["product_id"], products_data["distance_cutline_km"]))

    stores_data["available_start_min"] = stores_data["available_start"].apply(time_to_minutes)
    stores_data["available_end_min"] = stores_data["available_end"].apply(time_to_minutes)

    time_start_map = dict(zip(stores_data["store_id"], stores_data["available_start_min"]))
    time_end_map = dict(zip(stores_data["store_id"], stores_data["available_end_min"]))

    departure_min = departure_time.hour * 60 + departure_time.minute

    result_rows = []

    # 같은 상품을 가진 점포끼리 비교
    for product_id in inventory_data["product_id"].unique():
        product_inventory = inventory_data[inventory_data["product_id"] == product_id]
        cutline = cutline_map.get(product_id, 999999)

        for _, source in product_inventory.iterrows():
            source_id = source["store_id"]

            if source_id not in retailer_ids:
                continue

            # 악성재고 후보 조건
            source_is_overstock = (
                source["stock_qty"] > source["sales_30d"]
                and source["sales_30d"] <= 10
            )

            if not source_is_overstock:
                continue

            for _, target in product_inventory.iterrows():
                target_id = target["store_id"]

                if target_id not in retailer_ids:
                    continue

                if source_id == target_id:
                    continue

                # target 점포가 source보다 더 잘 팔리는 경우만 후보
                target_has_better_demand = target["sales_30d"] > source["sales_30d"]

                if not target_has_better_demand:
                    continue

                direct = check_direct_path(
                    source_id,
                    target_id,
                    route_lookup,
                    time_start_map,
                    time_end_map,
                    departure_min,
                )

                # 여러 DC 중에서 가장 비용이 낮은 DC 경유 경로 선택
                via_candidates = []

                for dc_id in dc_ids:
                    via = check_via_dc_path(
                        source_id,
                        target_id,
                        dc_id,
                        route_lookup,
                        time_start_map,
                        time_end_map,
                        departure_min,
                    )

                    via["dc_id"] = dc_id
                    via_candidates.append(via)

                available_via_candidates = [
                    v for v in via_candidates if v["available"] is True
                ]

                if available_via_candidates:
                    best_via = sorted(available_via_candidates, key=lambda x: x["cost"])[0]
                else:
                    best_via = sorted(
                        via_candidates,
                        key=lambda x: x["cost"] if x["cost"] is not None else 999999999,
                    )[0]

                # 제품별 거리 컷라인 적용
                direct_cutline_ok = (
                    direct["distance_km"] is not None
                    and direct["distance_km"] <= cutline
                )

                via_cutline_ok = (
                    best_via["distance_km"] is not None
                    and best_via["distance_km"] <= cutline
                )

                direct_final_available = direct["available"] and direct_cutline_ok
                via_final_available = best_via["available"] and via_cutline_ok

                if direct_final_available and via_final_available:
                    if direct["cost"] <= best_via["cost"]:
                        recommended_path = "직접 이동 추천"
                        recommendation_reason = "직접 이동이 DC 경유보다 비용이 낮습니다."
                    else:
                        recommended_path = "DC 경유 이동 추천"
                        recommendation_reason = "DC 경유 이동이 직접 이동보다 비용이 낮습니다."

                elif direct_final_available:
                    recommended_path = "직접 이동 추천"
                    recommendation_reason = "직접 이동만 거리/시간 조건을 만족합니다."

                elif via_final_available:
                    recommended_path = "DC 경유 이동 추천"
                    recommendation_reason = "DC 경유 이동만 거리/시간 조건을 만족합니다."

                else:
                    recommended_path = "이동 비추천"
                    recommendation_reason = "직접 이동과 DC 경유 이동 모두 조건을 만족하지 못합니다."

                suggested_qty = min(
                    int(source["stock_qty"]),
                    max(1, int(target["sales_30d"] - target["stock_qty"]))
                    if target["sales_30d"] > target["stock_qty"]
                    else min(10, int(source["stock_qty"]))
                )

                result_rows.append(
                    {
                        "product_id": product_id,
                        "product_name": product_name_map.get(product_id, product_id),
                        "source_store": store_name_map.get(source_id, source_id),
                        "target_store": store_name_map.get(target_id, target_id),
                        "source_stock_qty": source["stock_qty"],
                        "source_sales_30d": source["sales_30d"],
                        "target_stock_qty": target["stock_qty"],
                        "target_sales_30d": target["sales_30d"],
                        "suggested_transfer_qty": suggested_qty,
                        "distance_cutline_km": cutline,
                        "direct_distance_km": direct["distance_km"],
                        "direct_time_min": direct["travel_time_min"],
                        "direct_cost": direct["cost"],
                        "direct_arrival_time": minutes_to_time_text(direct["arrival_min"])
                        if direct["arrival_min"] is not None
                        else "계산불가",
                        "direct_status": "가능" if direct_final_available else "불가능",
                        "direct_reason": direct["reason"]
                        if direct_cutline_ok
                        else "제품별 거리 컷라인 초과",
                        "via_dc": store_name_map.get(best_via.get("dc_id"), best_via.get("dc_id")),
                        "via_distance_km": best_via["distance_km"],
                        "via_time_min": best_via["travel_time_min"],
                        "via_cost": best_via["cost"],
                        "via_arrival_time": minutes_to_time_text(best_via["arrival_min"])
                        if best_via["arrival_min"] is not None
                        else "계산불가",
                        "via_status": "가능" if via_final_available else "불가능",
                        "via_reason": best_via["reason"]
                        if via_cutline_ok
                        else "제품별 거리 컷라인 초과",
                        "recommended_path": recommended_path,
                        "recommendation_reason": recommendation_reason,
                    }
                )

    result = pd.DataFrame(result_rows)

    return result