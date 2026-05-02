import pandas as pd


def build_final_recommendations(promotion_result, network_path_result):
    rows = []

    # 1. 프로모션 vs 재배치 결과 정리
    if promotion_result is not None and not promotion_result.empty:
        for _, row in promotion_result.iterrows():
            if row["final_decision"] == "프로모션 추천":
                estimated_cost = row["promotion_net_cost"]
            else:
                estimated_cost = row["transfer_cost"]

            rows.append(
                {
                    "product_name": row["product_name"],
                    "source_store": row["source_store"],
                    "target_store": row["target_store"],
                    "suggested_qty": row["suggested_qty"],
                    "final_recommendation": row["final_decision"],
                    "estimated_cost": estimated_cost,
                    "reason": row["decision_reason"],
                }
            )

    # 2. 다중 경로 추천 결과 정리
    if network_path_result is not None and not network_path_result.empty:
        network_recommended = network_path_result[
            network_path_result["network_recommendation"] == "다중 경로 추천"
        ]

        for _, row in network_recommended.iterrows():
            rows.append(
                {
                    "product_name": row["product_name"],
                    "source_store": row["source_store"],
                    "target_store": row["target_store"],
                    "suggested_qty": "-",
                    "final_recommendation": "다중 경로 추천",
                    "estimated_cost": row["network_cost"],
                    "reason": row["reason"],
                }
            )

    final_df = pd.DataFrame(rows)

    if final_df.empty:
        summary_df = pd.DataFrame()
        return final_df, summary_df

    summary_df = (
        final_df.groupby("final_recommendation")
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    return final_df, summary_df
