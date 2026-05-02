def analyze_discount_options(
    stock_qty,
    sales_30d,
    unit_cost,
    daily_holding_cost,
    discount_rates,
    expected_sales_increase_rate,
):
    results = []

    if sales_30d > 0:
        original_cover_days = stock_qty / (sales_30d / 30)
    else:
        original_cover_days = 999

    original_keep_cost = stock_qty * daily_holding_cost * min(original_cover_days, 30)

    for rate in discount_rates:
        discounted_unit_loss = unit_cost * (rate / 100)
        discount_loss_total = stock_qty * discounted_unit_loss

        improved_sales_30d = sales_30d * (1 + expected_sales_increase_rate / 100)

        if improved_sales_30d > 0:
            discount_cover_days = stock_qty / (improved_sales_30d / 30)
        else:
            discount_cover_days = 999

        discount_keep_cost = stock_qty * daily_holding_cost * min(discount_cover_days, 30)
        saved_holding_cost = max(0, original_keep_cost - discount_keep_cost)
        net_cost = discount_loss_total - saved_holding_cost

        results.append(
            {
                "discount_rate": rate,
                "discount_loss_total": round(discount_loss_total, 1),
                "saved_holding_cost": round(saved_holding_cost, 1),
                "net_cost": round(net_cost, 1),
            }
        )

    return results