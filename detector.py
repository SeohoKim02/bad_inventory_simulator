import numpy as np


def detect_bad_inventory(inventory):
    result = inventory.copy()

    result["stock_cover_days"] = np.where(
        result["sales_30d"] > 0,
        result["stock_qty"] / (result["sales_30d"] / 30),
        999
    )

    result["risk_score"] = 0
    result["reason"] = ""

    old_condition = result["inbound_days_ago"] > 45
    low_sales_condition = result["sales_30d"] <= 5
    overstock_condition = result["stock_cover_days"] > 60

    result.loc[old_condition, "risk_score"] += 40
    result.loc[low_sales_condition, "risk_score"] += 30
    result.loc[overstock_condition, "risk_score"] += 30

    result.loc[old_condition, "reason"] += "장기보관; "
    result.loc[low_sales_condition, "reason"] += "판매저조; "
    result.loc[overstock_condition, "reason"] += "과잉재고; "

    result["is_bad_stock"] = result["risk_score"] >= 70

    return result
