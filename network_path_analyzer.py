import pandas as pd
import heapq
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
    if minutes is None:
        return "계산불가"

    minutes = int(minutes)

    if minutes >= 24 * 60:
        return "당일 초과"

    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def build_graph(routes):
    graph = {}

    for _, row in routes.iterrows():
        from_id = row["from_id"]
        to_id = row["to_id"]

        distance = float(row["distance_km"])
        time_min = float(row["travel_time_min"])
        cost = distance * float(row["cost_per_km"])

        graph.setdefault(from_id, []).append(
            {
                "to": to_id,
                "distance": distance,
                "time": time_min,
                "cost": cost,
            }
        )

        graph.setdefault(to_id, []).append(
            {
                "to": from_id,
                "distance": distance,
                "time": time_min,
                "cost": cost,
            }
        )

    return graph


def dijkstra_lowest_cost(graph, start, end):
    queue = [(0, start)]
    costs = {start: 0}
    previous = {start: None}
    edge_info = {}

    while queue:
        current_cost, current_node = heapq.heappop(queue)

        if current_node == end:
            break

        if current_cost > costs.get(current_node, float("inf")):
            continue

        for edge in graph.get(current_node, []):
            next_node = edge["to"]
            new_cost = current_cost + edge["cost"]

            if new_cost < costs.get(next_node, float("inf")):
                costs[next_node] = new_cost
                previous[next_node] = current_node
                edge_info[(current_node, next_node)] = edge
                heapq.heappush(queue, (new_cost, next_node))

    if end not in previous:
        return None

    path = []
    node = end

    while node is not None:
        path.append(node)
        node = previous[node]

    path.reverse()

    total_distance = 0
    total_time = 0
    total_cost = 0

    for i in range(len(path) - 1):
        a = path[i]
        b = path[i + 1]
        edge = edge_info[(a, b)]

        total_distance += edge["distance"]
        total_time += edge["time"]
        total_cost += edge["cost"]

    return {
        "path": path,
        "total_distance": total_distance,
        "total_time": total_time,
        "total_cost": total_cost,
    }


def check_path_time_window(path_result, stores, departure_time):
    stores_data = stores.copy()

    stores_data["available_start_min"] = stores_data["available_start"].apply(time_to_minutes)
    stores_data["available_end_min"] = stores_data["available_end"].apply(time_to_minutes)

    start_map = dict(zip(stores_data["store_id"], stores_data["available_start_min"]))
    end_map = dict(zip(stores_data["store_id"], stores_data["available_end_min"]))

    departure_min = departure_time.hour * 60 + departure_time.minute

    path = path_result["path"]

    start_node = path[0]

    if not is_within_window(
        departure_min,
        start_map.get(start_node),
        end_map.get(start_node),
    ):
        return False, "출발 점포 거래가능시간 불만족", None

    arrival_min = departure_min + path_result["total_time"]

    if arrival_min > 24 * 60:
        return False, "도착 시간이 당일 범위를 초과", arrival_min

    end_node = path[-1]

    if not is_within_window(
        arrival_min,
        start_map.get(end_node),
        end_map.get(end_node),
    ):
        return False, "도착 점포 거래가능시간 불만족", arrival_min

    return True, "거래가능시간 만족", arrival_min


def analyze_multi_store_network_paths(
    stores,
    products,
    routes,
    transfer_path_result,
    departure_time,
):
    stores_data = stores.copy()
    products_data = products.copy()
    routes_data = routes.copy()
    transfer_data = transfer_path_result.copy()

    if transfer_data.empty:
        return pd.DataFrame(), "점포 간 이동 후보가 없습니다."

    graph = build_graph(routes_data)

    store_name_to_id = dict(zip(stores_data["store_name"], stores_data["store_id"]))
    store_id_to_name = dict(zip(stores_data["store_id"], stores_data["store_name"]))

    cutline_map = dict(
        zip(products_data["product_id"], products_data["distance_cutline_km"])
    )

    result_rows = []

    for _, row in transfer_data.iterrows():
        product_id = row["product_id"]
        product_name = row["product_name"]

        source_store_name = row["source_store"]
        target_store_name = row["target_store"]

        source_id = store_name_to_id.get(source_store_name)
        target_id = store_name_to_id.get(target_store_name)

        if source_id is None or target_id is None:
            continue

        path_result = dijkstra_lowest_cost(graph, source_id, target_id)

        if path_result is None:
            result_rows.append(
                {
                    "product_name": product_name,
                    "source_store": source_store_name,
                    "target_store": target_store_name,
                    "network_path": "경로 없음",
                    "network_distance_km": None,
                    "network_time_min": None,
                    "network_cost": None,
                    "arrival_time": "계산불가",
                    "cutline_status": "불가능",
                    "time_status": "불가능",
                    "network_status": "불가능",
                    "network_recommendation": "경로 없음",
                    "reason": "연결 가능한 경로가 없습니다.",
                }
            )
            continue

        cutline = cutline_map.get(product_id, 999999)

        cutline_ok = path_result["total_distance"] <= cutline

        time_ok, time_reason, arrival_min = check_path_time_window(
            path_result,
            stores_data,
            departure_time,
        )

        network_available = cutline_ok and time_ok

        path_names = [
            store_id_to_name.get(store_id, store_id)
            for store_id in path_result["path"]
        ]

        direct_cost = row.get("direct_cost")
        via_cost = row.get("via_cost")

        available_costs = []

        if row.get("direct_status") == "가능" and not pd.isna(direct_cost):
            available_costs.append(float(direct_cost))

        if row.get("via_status") == "가능" and not pd.isna(via_cost):
            available_costs.append(float(via_cost))

        existing_best_cost = min(available_costs) if available_costs else None

        if not network_available:
            network_recommendation = "다중 경로 비추천"

            if not cutline_ok:
                reason = "제품별 거리 컷라인을 초과합니다."
            else:
                reason = time_reason

        elif existing_best_cost is None:
            network_recommendation = "다중 경로 추천"
            reason = "기존 직접/DC 경유 이동이 어렵고, 다중 연결 경로가 가능합니다."

        elif path_result["total_cost"] < existing_best_cost:
            network_recommendation = "다중 경로 추천"
            reason = "다중 연결 경로가 기존 직접/DC 경유 방식보다 비용이 낮습니다."

        else:
            network_recommendation = "기존 경로 유지"
            reason = "기존 직접/DC 경유 방식이 다중 연결 경로보다 비용이 낮거나 같습니다."

        result_rows.append(
            {
                "product_name": product_name,
                "source_store": source_store_name,
                "target_store": target_store_name,
                "network_path": " → ".join(path_names),
                "network_distance_km": round(path_result["total_distance"], 1),
                "network_time_min": round(path_result["total_time"], 1),
                "network_cost": round(path_result["total_cost"], 1),
                "arrival_time": minutes_to_time_text(arrival_min),
                "distance_cutline_km": cutline,
                "cutline_status": "가능" if cutline_ok else "불가능",
                "time_status": "가능" if time_ok else "불가능",
                "network_status": "가능" if network_available else "불가능",
                "network_recommendation": network_recommendation,
                "reason": reason,
            }
        )

    return pd.DataFrame(result_rows), None
