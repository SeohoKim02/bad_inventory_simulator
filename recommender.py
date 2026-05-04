def recommend_action(result):
    data = result.copy()

    data["action"] = ""

    discount_condition = (data["sales_30d"] <= 5) & (data["inbound_days_ago"] <= 60)
    reduce_order_condition = data["inbound_days_ago"] > 60
    urgent_condition = (data["sales_30d"] <= 3) & (data["stock_cover_days"] > 90)

    data.loc[discount_condition, "action"] = "할인 판매 추천"
    data.loc[reduce_order_condition, "action"] = "다음 발주 축소 추천"
    data.loc[urgent_condition, "action"] = "긴급 재고 처리 필요"

    data.loc[data["action"] == "", "action"] = "모니터링 필요"

    return data


def recommend_transfer(result):
    data = result.copy()

    data["transfer_recommendation"] = "이동 추천 없음"

    bad_items = data[data["is_bad_stock"] == True]

    for idx, row in bad_items.iterrows():
        same_product = data[data["product_id"] == row["product_id"]]

        better_store = same_product[
            (same_product["store_id"] != row["store_id"]) &
            (same_product["sales_30d"] > row["sales_30d"]) &
            (same_product["sales_30d"] >= 10)
        ]

        if not better_store.empty:
            best_target = better_store.sort_values("sales_30d", ascending=False).iloc[0]
            data.at[idx, "transfer_recommendation"] = (
                f"{row['store_name']} → {best_target['store_name']} 이동 추천"
            )

    return data