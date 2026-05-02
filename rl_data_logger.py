
import pandas as pd


def _safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _first_existing(row, columns, default=None):
    for col in columns:
        if col in row.index:
            value = row.get(col)
            if not pd.isna(value):
                return value
    return default


def _get_store_id(stores, store_name):
    if stores is None or stores.empty:
        return None

    if "store_name" not in stores.columns or "store_id" not in stores.columns:
        return None

    matched = stores[stores["store_name"] == store_name]

    if matched.empty:
        return None

    return matched.iloc[0]["store_id"]


def _get_product_id(products, product_name):
    if products is None or products.empty:
        return None

    if "product_name" not in products.columns or "product_id" not in products.columns:
        return None

    matched = products[products["product_name"] == product_name]

    if matched.empty:
        return None

    return matched.iloc[0]["product_id"]


def _get_inventory_row(inventory, store_id, product_id):
    if inventory is None or inventory.empty:
        return None

    if "store_id" not in inventory.columns or "product_id" not in inventory.columns:
        return None

    matched = inventory[
        (inventory["store_id"] == store_id)
        & (inventory["product_id"] == product_id)
    ]

    if matched.empty:
        return None

    return matched.iloc[0]


def _get_product_row(products, product_id):
    if products is None or products.empty:
        return None

    if "product_id" not in products.columns:
        return None

    matched = products[products["product_id"] == product_id]

    if matched.empty:
        return None

    return matched.iloc[0]


def _estimate_action(row):
    text = str(row.get("final_recommendation", "")) + " " + str(row.get("recommended_transfer_path", ""))

    if "직접" in text:
        return "direct_transfer"

    if "DC" in text or "경유" in text:
        return "via_dc_transfer"

    if "다중" in text:
        return "multi_store_transfer"

    if "프로모션" in text or "할인" in text or "1+1" in text:
        return "promotion"

    if "폐기" in text:
        return "dispose"

    if "유지" in text:
        return "keep"

    if "재배치" in text or "이동" in text:
        return "transfer"

    return "unknown"


def _calculate_reward(row):
    """
    강화학습용 임시 Reward.
    값이 클수록 좋은 선택이라고 해석.

    기본 아이디어:
    - 휴리스틱 점수가 높으면 보상 증가
    - 예상 비용이 낮으면 보상 증가
    - 이동 수량이 많으면 악성재고 해소 효과가 커져 보상 증가
    - 프로모션 비용보다 재배치 비용이 낮으면 보상 증가
    """

    heuristic_score = _safe_float(row.get("heuristic_score", 50), 50)
    estimated_cost = _safe_float(row.get("estimated_cost", 0), 0)
    suggested_qty = _safe_float(row.get("suggested_qty", 0), 0)

    transfer_cost = _safe_float(row.get("transfer_cost", estimated_cost), estimated_cost)
    promotion_net_cost = _safe_float(row.get("promotion_net_cost", estimated_cost), estimated_cost)

    cost_penalty = estimated_cost / 10000
    quantity_bonus = suggested_qty * 0.4

    if transfer_cost > 0 and promotion_net_cost > 0:
        saving_bonus = max(promotion_net_cost - transfer_cost, 0) / 10000
    else:
        saving_bonus = 0

    reward = heuristic_score + quantity_bonus + saving_bonus - cost_penalty

    return round(reward, 3)


def build_rl_training_log(
    stores,
    products,
    inventory,
    final_recommendations,
    transfer_path_result=None,
    promotion_result=None,
):
    """
    현재 앱의 추천 결과를 강화학습 학습용 로그 형태로 변환한다.

    출력 컬럼 구조:
    - state_*: 상태 변수
    - action: 선택 행동
    - reward: 보상
    - heuristic/greedy: 현재 알고리즘 결과
    """

    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame()

    records = []

    for _, rec in final_recommendations.iterrows():
        product_name = rec.get("product_name", "-")
        source_store = rec.get("source_store", "-")
        target_store = rec.get("target_store", "-")

        product_id = _get_product_id(products, product_name)
        source_store_id = _get_store_id(stores, source_store)
        target_store_id = _get_store_id(stores, target_store)

        source_inv = _get_inventory_row(inventory, source_store_id, product_id)
        target_inv = _get_inventory_row(inventory, target_store_id, product_id)
        product_row = _get_product_row(products, product_id)

        source_stock = _safe_float(source_inv.get("stock_qty", 0), 0) if source_inv is not None else 0
        target_stock = _safe_float(target_inv.get("stock_qty", 0), 0) if target_inv is not None else 0

        source_sales_30d = _safe_float(
            _first_existing(source_inv, ["sales_30d", "recent_sales_30d", "monthly_sales"], 0),
            0,
        ) if source_inv is not None else 0

        target_sales_30d = _safe_float(
            _first_existing(target_inv, ["sales_30d", "recent_sales_30d", "monthly_sales"], 0),
            0,
        ) if target_inv is not None else 0

        inbound_days = _safe_float(
            _first_existing(source_inv, ["inbound_days", "days_since_inbound", "stock_age_days"], 0),
            0,
        ) if source_inv is not None else 0

        unit_cost = _safe_float(
            _first_existing(source_inv, ["unit_cost", "cost", "unit_price"], None),
            None,
        ) if source_inv is not None else None

        if unit_cost is None and product_row is not None:
            unit_cost = _safe_float(
                _first_existing(product_row, ["unit_cost", "cost", "unit_price", "price"], 1000),
                1000,
            )

        distance_km = 0
        transfer_cost = _safe_float(rec.get("estimated_cost", 0), 0)

        if transfer_path_result is not None and not transfer_path_result.empty:
            matched_transfer = transfer_path_result[
                (transfer_path_result["product_name"] == product_name)
                & (transfer_path_result["source_store"] == source_store)
                & (transfer_path_result["target_store"] == target_store)
            ]

            if not matched_transfer.empty:
                trow = matched_transfer.iloc[0]
                distance_km = _safe_float(
                    _first_existing(trow, ["direct_distance_km", "distance_km", "network_distance_km"], 0),
                    0,
                )

                direct_cost = _safe_float(trow.get("direct_cost", 0), 0)
                via_cost = _safe_float(trow.get("via_cost", 0), 0)

                if direct_cost > 0:
                    transfer_cost = direct_cost
                elif via_cost > 0:
                    transfer_cost = via_cost

        promotion_net_cost = 0

        if promotion_result is not None and not promotion_result.empty:
            matched_promo = promotion_result[
                (promotion_result["product_name"] == product_name)
                & (promotion_result["source_store"] == source_store)
                & (promotion_result["target_store"] == target_store)
            ]

            if not matched_promo.empty:
                promotion_net_cost = _safe_float(matched_promo.iloc[0].get("promotion_net_cost", 0), 0)

        row = {
            "product_name": product_name,
            "source_store": source_store,
            "target_store": target_store,

            "state_source_stock": source_stock,
            "state_target_stock": target_stock,
            "state_source_sales_30d": source_sales_30d,
            "state_target_sales_30d": target_sales_30d,
            "state_inbound_days": inbound_days,
            "state_unit_cost": unit_cost,
            "state_distance_km": distance_km,
            "state_transfer_cost": transfer_cost,
            "state_promotion_net_cost": promotion_net_cost,

            "suggested_qty": _safe_float(rec.get("suggested_qty", 0), 0),
            "estimated_cost": _safe_float(rec.get("estimated_cost", 0), 0),
            "final_recommendation": rec.get("final_recommendation", "-"),
            "heuristic_score": _safe_float(rec.get("heuristic_score", 0), 0),
            "heuristic_grade": rec.get("heuristic_grade", "-"),
            "greedy_rank": _safe_int(rec.get("greedy_rank", 9999), 9999),
            "is_greedy_selected": bool(rec.get("is_greedy_selected", False)),
        }

        row["action"] = _estimate_action(rec)
        row["reward"] = _calculate_reward(row)

        records.append(row)

    result = pd.DataFrame(records)

    if result.empty:
        return result

    result = result.sort_values(
        by=["greedy_rank", "reward"],
        ascending=[True, False],
    ).reset_index(drop=True)

    return result
