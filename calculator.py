def calculate_inventory_analysis(
    stock_qty,
    sales_30d,
    inbound_days,
    unit_cost,
    daily_holding_cost,
    discount_rate,
    expected_sales_increase_rate,
    transfer_possible,
    distance_km,
    cost_per_km,
    target_store_sales_30d,
    disposal_cost_per_unit,
):
    # 1. 재고 소진 예상 일수
    if sales_30d > 0:
        stock_cover_days = stock_qty / (sales_30d / 30)
    else:
        stock_cover_days = 999

    # 2. 악성재고 위험점수 계산
    risk_score = 0
    reasons = []

    if inbound_days > 45:
        risk_score += 40
        reasons.append("장기보관")

    if sales_30d <= 5:
        risk_score += 30
        reasons.append("판매저조")

    if stock_cover_days > 60:
        risk_score += 30
        reasons.append("과잉재고")

    is_bad_stock = risk_score >= 70

    # 3. 유지 비용 계산
    expected_remaining_days = min(stock_cover_days, 30)
    keep_cost = stock_qty * daily_holding_cost * expected_remaining_days

    # 4. 할인 전략 계산
    discounted_unit_loss = unit_cost * (discount_rate / 100)
    discount_loss_total = stock_qty * discounted_unit_loss
    improved_sales_30d = sales_30d * (1 + expected_sales_increase_rate / 100)

    if improved_sales_30d > 0:
        discount_stock_cover_days = stock_qty / (improved_sales_30d / 30)
    else:
        discount_stock_cover_days = 999

    discount_saved_holding_cost = max(0, keep_cost - (stock_qty * daily_holding_cost * min(discount_stock_cover_days, 30)))
    discount_net_cost = discount_loss_total - discount_saved_holding_cost

    # 5. 타점포 이동 전략 계산
    if transfer_possible:
        transfer_cost = distance_km * cost_per_km

        if target_store_sales_30d > 0:
            transfer_stock_cover_days = stock_qty / (target_store_sales_30d / 30)
        else:
            transfer_stock_cover_days = 999

        transfer_saved_holding_cost = max(
            0,
            keep_cost - (stock_qty * daily_holding_cost * min(transfer_stock_cover_days, 30))
        )
        transfer_net_cost = transfer_cost - transfer_saved_holding_cost
    else:
        transfer_cost = 0
        transfer_net_cost = 999999

    # 6. 폐기 전략 계산
    disposal_cost = stock_qty * disposal_cost_per_unit

    # 7. 최종 추천
    options = {
        "유지": keep_cost,
        "할인": discount_net_cost,
        "타점포 이동": transfer_net_cost,
        "폐기": disposal_cost,
    }

    best_action = min(options, key=options.get)

    if best_action == "유지":
        recommendation_reason = "현재 상태를 유지하는 것이 다른 전략보다 비용이 가장 낮습니다."
    elif best_action == "할인":
        recommendation_reason = "할인 전략이 보관비 부담을 줄이면서 가장 낮은 순비용을 보입니다."
    elif best_action == "타점포 이동":
        recommendation_reason = "타점포 이동이 현재 점포 보관보다 더 효율적이며 비용 절감 효과가 있습니다."
    else:
        recommendation_reason = "폐기 비용이 다른 전략보다 낮아 손실 최소화에 가장 유리합니다."

    if inbound_days > 90 or best_action == "폐기":
        order_advice = "다음 발주 중단 또는 대폭 축소 검토"
    elif inbound_days > 60:
        order_advice = "다음 발주 축소 추천"
    else:
        order_advice = "발주 유지 가능"

    # 7. 계산식 설명
        formula_text = {
        "stock_cover_days_formula": f"재고소진일수 = {stock_qty} / ({sales_30d} / 30) = {round(stock_cover_days, 1)}일" if sales_30d > 0 else "재고소진일수 = 판매량 0으로 인해 매우 큼(999 처리)",
        "risk_formula": f"위험점수 = {risk_score}점 (" + ", ".join(reasons) + ")" if reasons else "위험점수 = 0점",
        "keep_cost_formula": f"유지비용 = {stock_qty} × {daily_holding_cost} × {round(expected_remaining_days, 1)} = {round(keep_cost, 1)}원",
        "discount_formula": f"할인비용 = 총 할인손실 {round(discount_loss_total, 1)} - 절감 보관비 {round(discount_saved_holding_cost, 1)} = {round(discount_net_cost, 1)}원",
        "transfer_formula": f"이동비용 = 거리 {distance_km}km × km당 운송비 {cost_per_km}원 = {round(transfer_cost, 1)}원, 순비용 = 이동비 {round(transfer_cost, 1)} - 절감 보관비 {round(transfer_saved_holding_cost, 1) if transfer_possible else 0} = {round(transfer_net_cost, 1) if transfer_possible else '계산불가'}원",
        "disposal_formula": f"폐기비용 = {stock_qty} × {disposal_cost_per_unit} = {round(disposal_cost, 1)}원",
    }

        return {
        "stock_cover_days": round(stock_cover_days, 1),
        "risk_score": risk_score,
        "is_bad_stock": is_bad_stock,
        "reasons": reasons,
        "keep_cost": round(keep_cost, 1),
        "discount_net_cost": round(discount_net_cost, 1),
        "transfer_cost": round(transfer_cost, 1),
        "transfer_net_cost": round(transfer_net_cost, 1) if transfer_possible else None,
        "disposal_cost": round(disposal_cost, 1),
        "best_action": best_action,
        "recommendation_reason": recommendation_reason,
        "order_advice": order_advice,
        "formula_text": formula_text,
    }