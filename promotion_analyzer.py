import math
import pandas as pd


def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def get_first_existing_value(row, columns, default=0):
    for col in columns:
        if col in row.index:
            value = row[col]
            if not pd.isna(value):
                return value
    return default


def get_transfer_cost(row):
    recommended_path = str(row.get("recommended_path", ""))

    if "직접" in recommended_path:
        return safe_float(row.get("direct_cost", row.get("transfer_cost", 0)))

    if "DC" in recommended_path or "경유" in recommended_path:
        return safe_float(row.get("via_cost", row.get("transfer_cost", 0)))

    return safe_float(
        get_first_existing_value(
            row,
            [
                "transfer_cost",
                "network_cost",
                "estimated_cost",
                "direct_cost",
                "via_cost",
            ],
            default=0,
        )
    )


def find_source_inventory(inventory, stores, source_store_name, product_name):
    """
    source_store와 product_name에 해당하는 inventory 행을 찾는다.
    데이터 구조가 조금 달라도 최대한 안전하게 찾도록 구성.
    """

    if inventory is None or inventory.empty:
        return None

    inv = inventory.copy()

    # inventory에 store_name이 있으면 바로 사용
    if "store_name" in inv.columns:
        store_matched = inv[inv["store_name"] == source_store_name]
    else:
        store_matched = inv

        if stores is not None and not stores.empty:
            if "store_name" in stores.columns and "store_id" in stores.columns:
                store_id_map = dict(zip(stores["store_name"], stores["store_id"]))
                source_store_id = store_id_map.get(source_store_name)

                if source_store_id is not None and "store_id" in inv.columns:
                    store_matched = inv[inv["store_id"] == source_store_id]

    if store_matched.empty:
        return None

    # inventory에 product_name이 있으면 상품명으로도 필터링
    if "product_name" in store_matched.columns:
        product_matched = store_matched[store_matched["product_name"] == product_name]

        if not product_matched.empty:
            return product_matched.iloc[0]

    # product_name이 없으면 같은 점포의 첫 번째 행 사용
    return store_matched.iloc[0]


def estimate_unit_cost(source_inv, transfer_row):
    """
    unit_cost가 없을 때도 앱이 멈추지 않도록 원가를 추정한다.
    우선순위:
    1. inventory 행의 unit_cost 계열 열
    2. transfer 결과 행의 unit_cost 계열 열
    3. 기본값 1000원
    """

    unit_cost_columns = [
        "unit_cost",
        "cost",
        "product_cost",
        "item_cost",
        "price",
        "unit_price",
    ]

    if source_inv is not None:
        value = get_first_existing_value(source_inv, unit_cost_columns, default=None)
        if value is not None:
            return safe_float(value, 1000)

    value = get_first_existing_value(transfer_row, unit_cost_columns, default=None)
    if value is not None:
        return safe_float(value, 1000)

    return 1000.0


def estimate_daily_holding_cost(source_inv, transfer_row):
    holding_columns = [
        "daily_holding_cost",
        "holding_cost",
        "storage_cost",
        "daily_storage_cost",
    ]

    if source_inv is not None:
        value = get_first_existing_value(source_inv, holding_columns, default=None)
        if value is not None:
            return safe_float(value, 20)

    value = get_first_existing_value(transfer_row, holding_columns, default=None)
    if value is not None:
        return safe_float(value, 20)

    return 20.0


def calculate_promotion_cost(
    promotion_type,
    suggested_qty,
    unit_cost,
    daily_holding_cost,
    promotion_discount_rate,
    promotion_sales_increase_rate,
    promotion_fixed_cost,
):
    suggested_qty = safe_int(suggested_qty, 0)
    unit_cost = safe_float(unit_cost, 1000)
    daily_holding_cost = safe_float(daily_holding_cost, 20)

    discount_rate = safe_float(promotion_discount_rate, 0) / 100
    sales_increase_rate = safe_float(promotion_sales_increase_rate, 0) / 100
    fixed_cost = safe_float(promotion_fixed_cost, 0)

    expected_extra_sales = suggested_qty * sales_increase_rate
    holding_saving = expected_extra_sales * daily_holding_cost

    if promotion_type == "1+1 프로모션":
        # 1+1은 판매 촉진을 위해 대략 절반 수준의 상품 원가 부담이 생긴다고 가정
        promotion_loss = math.ceil(suggested_qty / 2) * unit_cost
        promotion_net_cost = promotion_loss + fixed_cost - holding_saving

        formula = (
            f"1+1 프로모션 순비용 = "
            f"증정 원가({math.ceil(suggested_qty / 2)}개 × {unit_cost:,.0f}원) "
            f"+ 고정비({fixed_cost:,.0f}원) "
            f"- 보관비 절감({holding_saving:,.0f}원) "
            f"= {promotion_net_cost:,.0f}원"
        )

    else:
        # 할인 프로모션
        discount_loss = suggested_qty * unit_cost * discount_rate
        promotion_net_cost = discount_loss + fixed_cost - holding_saving

        formula = (
            f"할인 프로모션 순비용 = "
            f"할인 손실({suggested_qty}개 × {unit_cost:,.0f}원 × {discount_rate * 100:.1f}%) "
            f"+ 고정비({fixed_cost:,.0f}원) "
            f"- 보관비 절감({holding_saving:,.0f}원) "
            f"= {promotion_net_cost:,.0f}원"
        )

    return max(promotion_net_cost, 0), formula


def analyze_promotion_vs_transfer(
    stores,
    inventory,
    transfer_path_result,
    promotion_type,
    promotion_discount_rate,
    promotion_sales_increase_rate,
    promotion_fixed_cost,
):
    """
    프로모션 비용과 재배치 비용을 비교한다.

    입력:
    - stores
    - inventory
    - transfer_path_result
    - promotion_type
    - promotion_discount_rate
    - promotion_sales_increase_rate
    - promotion_fixed_cost

    출력:
    - promotion_result DataFrame
    """

    if transfer_path_result is None or transfer_path_result.empty:
        return pd.DataFrame()

    results = []

    for _, row in transfer_path_result.iterrows():
        recommended_path = str(row.get("recommended_path", ""))

        if recommended_path == "이동 비추천":
            continue

        product_name = row.get("product_name", "-")
        source_store = row.get("source_store", "-")
        target_store = row.get("target_store", "-")

        suggested_qty = safe_int(
            get_first_existing_value(
                row,
                [
                    "suggested_transfer_qty",
                    "suggested_qty",
                    "transfer_qty",
                    "qty",
                ],
                default=0,
            ),
            default=0,
        )

        transfer_cost = get_transfer_cost(row)

        source_inv = find_source_inventory(
            inventory,
            stores,
            source_store,
            product_name,
        )

        unit_cost = estimate_unit_cost(source_inv, row)
        daily_holding_cost = estimate_daily_holding_cost(source_inv, row)

        promotion_net_cost, promotion_formula = calculate_promotion_cost(
            promotion_type=promotion_type,
            suggested_qty=suggested_qty,
            unit_cost=unit_cost,
            daily_holding_cost=daily_holding_cost,
            promotion_discount_rate=promotion_discount_rate,
            promotion_sales_increase_rate=promotion_sales_increase_rate,
            promotion_fixed_cost=promotion_fixed_cost,
        )

        if transfer_cost <= promotion_net_cost:
            final_decision = "재배치 추천"
            decision_reason = "프로모션 순비용이 재배치 비용보다 높습니다."
        else:
            final_decision = "프로모션 추천"
            decision_reason = "프로모션 순비용이 재배치 비용보다 낮습니다."

        results.append(
            {
                "product_name": product_name,
                "source_store": source_store,
                "target_store": target_store,
                "suggested_qty": suggested_qty,
                "recommended_transfer_path": recommended_path,
                "transfer_cost": round(transfer_cost, 0),
                "promotion_type": promotion_type,
                "promotion_net_cost": round(promotion_net_cost, 0),
                "final_decision": final_decision,
                "decision_reason": decision_reason,
                "promotion_formula": promotion_formula,
                "unit_cost_used": round(unit_cost, 0),
                "daily_holding_cost_used": round(daily_holding_cost, 0),
            }
        )

    return pd.DataFrame(results)
