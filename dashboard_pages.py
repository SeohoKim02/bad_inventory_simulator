
from numbers import Number
import io
import html as html_lib
import pandas as pd
import streamlit as st

from kakao_map_viewer import show_kakao_map, show_kakao_map_with_highlights

try:
    from kakao_map_viewer import show_kakao_map_with_multi_trucks
except ImportError:
    show_kakao_map_with_multi_trucks = None


# =========================
# 공통 유틸
# =========================
def _format_money(value):
    if isinstance(value, Number):
        return f"{value:,.0f}원"

    try:
        return f"{float(value):,.0f}원"
    except Exception:
        return str(value)


def _safe_numeric(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _clamp(value, low=0, high=100):
    try:
        value = float(value)
    except Exception:
        value = 0

    return max(low, min(high, value))


def _get_unit_price(products, inventory, product_name, source_store=None, stores=None):
    default_price = 1000

    try:
        if products is not None and not products.empty and "product_name" in products.columns:
            matched_product = products[products["product_name"] == product_name]

            if not matched_product.empty:
                product_row = matched_product.iloc[0]

                for col in ["unit_price", "price", "selling_price", "normal_price", "상품가격", "판매가"]:
                    if col in product_row.index and not pd.isna(product_row[col]):
                        return _safe_numeric(product_row[col], default_price)

        if inventory is not None and not inventory.empty:
            for col in ["unit_price", "price", "selling_price", "normal_price", "상품가격", "판매가"]:
                if col in inventory.columns:
                    return _safe_numeric(inventory.iloc[0][col], default_price)

    except Exception:
        pass

    return default_price


def _recommend_transport(product_name, qty, recommended_path="-"):
    text = str(product_name) + " " + str(recommended_path)
    qty = _safe_numeric(qty, 0)

    if any(keyword in text for keyword in ["냉동", "아이스", "만두", "냉장", "우유", "요거트"]):
        return "냉동/냉장 탑차"

    if "DC" in text or "경유" in text:
        return "소형 트럭"

    if qty <= 20:
        return "오토바이"

    if qty <= 80:
        return "소형 차량"

    return "소형 트럭"


TRANSPORT_PROFILES = {
    "오토바이": {
        "icon": "🛵",
        "base_cost": 1200,
        "cost_per_km": 420,
        "capacity": 20,
        "speed_factor": 1.25,
        "description": "소량·근거리 이동에 적합",
        "cold_chain": False,
    },
    "소형 차량": {
        "icon": "🚗",
        "base_cost": 3000,
        "cost_per_km": 620,
        "capacity": 80,
        "speed_factor": 1.0,
        "description": "중간 수량 점포 간 이동에 적합",
        "cold_chain": False,
    },
    "소형 트럭": {
        "icon": "🚚",
        "base_cost": 5500,
        "cost_per_km": 880,
        "capacity": 200,
        "speed_factor": 0.85,
        "description": "대량 재고 또는 DC 경유 이동에 적합",
        "cold_chain": False,
    },
    "냉동/냉장 탑차": {
        "icon": "🧊",
        "base_cost": 7500,
        "cost_per_km": 1050,
        "capacity": 150,
        "speed_factor": 0.75,
        "description": "온도 유지가 필요한 신선·냉동 상품에 적합",
        "cold_chain": True,
    },
}


def _is_cold_product(product_name):
    text = str(product_name)
    return any(keyword in text for keyword in ["냉동", "냉장", "아이스", "만두", "우유", "요거트", "샐러드"])


def _get_transport_profile(transport_type):
    return TRANSPORT_PROFILES.get(transport_type, TRANSPORT_PROFILES["소형 차량"])


def _get_transport_icon(transport_type):
    return _get_transport_profile(transport_type).get("icon", "🚚")


def _estimate_route_distance_km(path_row):
    if path_row is None:
        return 0.0

    distance_columns = [
        "direct_distance_km",
        "via_distance_km",
        "distance_km",
        "network_distance_km",
        "total_distance_km",
        "route_distance_km",
    ]

    for col in distance_columns:
        try:
            if col in path_row.index:
                value = _safe_numeric(path_row.get(col), None)
                if value is not None and value > 0:
                    return value
        except Exception:
            continue

    cost_columns = ["direct_cost", "via_cost", "transfer_cost", "estimated_cost"]

    for col in cost_columns:
        try:
            if col in path_row.index:
                value = _safe_numeric(path_row.get(col), None)
                if value is not None and value > 0:
                    return max(value / 900, 1)
        except Exception:
            continue

    return 5.0


def _calculate_transport_cost(transport_type, distance_km, qty, product_name="-"):
    profile = _get_transport_profile(transport_type)

    distance_km = max(_safe_numeric(distance_km, 0), 0)
    qty = max(_safe_numeric(qty, 0), 0)

    capacity = max(_safe_numeric(profile.get("capacity", 1), 1), 1)
    trips = max(int((qty + capacity - 1) // capacity), 1)

    base_cost = _safe_numeric(profile.get("base_cost", 0), 0)
    cost_per_km = _safe_numeric(profile.get("cost_per_km", 0), 0)

    cost = (base_cost + distance_km * cost_per_km) * trips

    # 냉동/냉장 상품을 일반 이동수단으로 옮기면 보냉 포장/품질 리스크 비용을 추가 반영
    if _is_cold_product(product_name) and not profile.get("cold_chain", False):
        cost *= 1.25

    return round(cost, 0)


def _calculate_transport_options(product_name, qty, distance_km):
    rows = []

    for transport_type, profile in TRANSPORT_PROFILES.items():
        cost = _calculate_transport_cost(
            transport_type=transport_type,
            distance_km=distance_km,
            qty=qty,
            product_name=product_name,
        )

        rows.append(
            {
                "이동수단": transport_type,
                "아이콘": profile["icon"],
                "예상 이동비용": cost,
                "적재 가능 수량": profile["capacity"],
                "속도 계수": profile["speed_factor"],
                "설명": profile["description"],
            }
        )

    return rows


def _choose_transport_type(product_name, qty, recommended_path="-", selected_transport_type="AI 추천 이동수단"):
    if selected_transport_type and selected_transport_type != "AI 추천 이동수단":
        return selected_transport_type

    return _recommend_transport(
        product_name=product_name,
        qty=qty,
        recommended_path=recommended_path,
    )


def _estimate_ratio_summary(move_cost, discount_loss_cost, disposal_cost, score, qty):
    move_cost = _safe_numeric(move_cost, 0)
    discount_loss_cost = _safe_numeric(discount_loss_cost, 0)
    disposal_cost = _safe_numeric(disposal_cost, 0)
    score = _safe_numeric(score, 0)
    qty = _safe_numeric(qty, 0)

    available_costs = [v for v in [move_cost, discount_loss_cost] if v and v > 0]
    best_action_cost = min(available_costs) if available_costs else move_cost

    if disposal_cost > 0:
        profit_recovery_ratio = _clamp(((disposal_cost - best_action_cost) / disposal_cost) * 100)
        cost_burden_ratio = _clamp((best_action_cost / disposal_cost) * 100)
    else:
        profit_recovery_ratio = _clamp(score)
        cost_burden_ratio = _clamp(100 - score)

    disposal_reduction_ratio = _clamp((score * 0.65) + min(qty, 100) * 0.35)

    return {
        "수익 회수 가능성": round(profit_recovery_ratio, 1),
        "폐기 위험 감소 효과": round(disposal_reduction_ratio, 1),
        "비용 부담률": round(cost_burden_ratio, 1),
    }


def _make_ratio_reason(ratios, strategy):
    return (
        f"수익 회수 가능성 {ratios['수익 회수 가능성']}%, "
        f"폐기 위험 감소 효과 {ratios['폐기 위험 감소 효과']}%, "
        f"비용 부담률 {ratios['비용 부담률']}% 기준으로 "
        f"{strategy} 방식의 실행 가치가 높다고 판단했습니다."
    )


def _safe_get(row, key, default="-"):
    try:
        value = row.get(key, default)
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default

def _escape_text(value):
    return html_lib.escape(str(value))


def _display_grade(value):
    text = str(value)

    if text in ["-", "nan", "None", ""]:
        return "검토"

    if "최우선" in text or "최적" in text or "매우" in text or text == "상":
        return "최적"

    if "우선" in text or "추천" in text or "권장" in text or text == "중":
        return "권장"

    if "보류" in text or "비추천" in text or "하" in text:
        return "검토"

    numeric = _safe_numeric(text.replace("점", ""), None)
    if numeric is not None:
        if numeric >= 80:
            return "최적"
        if numeric >= 65:
            return "권장"
        return "검토"

    return "검토"


def _map_grade_series(series):
    return series.apply(_display_grade)


def _prepare_display_dataframe(df, max_rows=500):
    """
    Streamlit 표 표시 전에 데이터 타입과 행 수를 안전하게 정리한다.
    문자/숫자가 섞인 object 컬럼 때문에 생기는 pyarrow 경고를 줄이고,
    큰 표는 화면에 일부만 보여준다.
    """
    if df is None:
        return pd.DataFrame(), 0

    try:
        total_rows = len(df)
    except Exception:
        total_rows = 0

    try:
        display_df = df.head(max_rows).copy()
    except Exception:
        try:
            display_df = pd.DataFrame(df).head(max_rows).copy()
        except Exception:
            display_df = pd.DataFrame({"value": [str(df)]})
            total_rows = 1

    display_df.columns = [str(c) for c in display_df.columns]

    for col in display_df.columns:
        try:
            if str(display_df[col].dtype) in ["object", "category"]:
                display_df[col] = display_df[col].map(lambda x: "" if pd.isna(x) else str(x))
        except Exception:
            display_df[col] = display_df[col].astype(str)

    return display_df, total_rows


def _safe_dataframe(df, **kwargs):
    max_rows = kwargs.pop("max_rows", 500)
    display_df, total_rows = _prepare_display_dataframe(df, max_rows=max_rows)

    if display_df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    try:
        st.dataframe(display_df, **kwargs)
    except Exception:
        st.dataframe(display_df.astype(str), **kwargs)



def _best_row(final_recommendations):
    if final_recommendations is None or final_recommendations.empty:
        return None

    df = final_recommendations.copy()

    # 추천 후보 더보기에서 사용자가 선택한 후보가 있으면
    # 대시보드 메인 카드도 그 후보 기준으로 보여준다.
    selected_candidate_index = st.session_state.get("dashboard_selected_candidate_index", None)

    if selected_candidate_index is not None:
        try:
            # 원본 DataFrame index 기준으로 선택
            if selected_candidate_index in df.index:
                return df.loc[selected_candidate_index]

            # 혹시 문자열로 저장된 경우 대비
            selected_candidate_index_int = int(selected_candidate_index)
            if selected_candidate_index_int in df.index:
                return df.loc[selected_candidate_index_int]

            # 마지막 안전장치: 위치 index로 선택
            if 0 <= selected_candidate_index_int < len(df):
                return df.iloc[selected_candidate_index_int]
        except Exception:
            # 선택값이 꼬였으면 기본 추천으로 돌아감
            st.session_state.pop("dashboard_selected_candidate_index", None)

    if "is_greedy_selected" in df.columns:
        selected = df[df["is_greedy_selected"] == True]
        if not selected.empty:
            return selected.iloc[0]

    if "greedy_rank" in df.columns:
        df["_rank"] = pd.to_numeric(df["greedy_rank"], errors="coerce")
        ranked = df[df["_rank"].notna()].sort_values("_rank")
        if not ranked.empty:
            return ranked.iloc[0]

    if "heuristic_score" in df.columns:
        df["_score"] = pd.to_numeric(df["heuristic_score"], errors="coerce")
        scored = df[df["_score"].notna()].sort_values("_score", ascending=False)
        if not scored.empty:
            return scored.iloc[0]

    if "estimated_cost" in df.columns:
        df["_cost"] = pd.to_numeric(df["estimated_cost"], errors="coerce")
        costed = df[df["_cost"].notna()].sort_values("_cost")
        if not costed.empty:
            return costed.iloc[0]

    return df.iloc[0]


def _go(page_name):
    st.session_state.excel_dashboard_page = page_name
    st.rerun()


def _back_to_dashboard():
    if st.button("← 대시보드로 돌아가기", width="stretch"):
        _go("dashboard")


def _apply_page_style():
    st.markdown(
        """
        <style>
            .dash-hero {
                padding: 22px 28px;
                border-radius: 24px;
                background:
                    radial-gradient(circle at top right, rgba(255, 212, 59, 0.35), transparent 32%),
                    linear-gradient(135deg, #fffbea 0%, #fff3bf 55%, #ffffff 100%);
                border: 2px solid #ffd43b;
                box-shadow: 0 12px 30px rgba(0,0,0,0.07);
                margin: 12px 0 16px 0;
            }

            .dash-small-title {
                font-size: 13px;
                color: #666;
                font-weight: 800;
                margin-bottom: 8px;
            }

            .dash-main-title {
                font-size: 28px;
                font-weight: 950;
                letter-spacing: -0.7px;
                color: #222;
                margin-bottom: 8px;
            }

            .dash-desc {
                font-size: 15px;
                line-height: 1.55;
                color: #444;
            }

            .dash-step-grid {
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                gap: 12px;
                margin: 18px 0 10px 0;
            }

            .dash-step {
                padding: 16px;
                border-radius: 20px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                text-align: center;
                box-shadow: 0 6px 16px rgba(0,0,0,0.035);
            }

            .dash-step-icon {
                font-size: 20px;
                margin-bottom: 6px;
            }

            .dash-step-title {
                font-weight: 900;
                margin-bottom: 4px;
            }

            .dash-step-desc {
                color: #666;
                font-size: 13px;
            }

            .dash-menu-card {
                padding: 16px;
                border-radius: 18px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                box-shadow: 0 8px 22px rgba(0,0,0,0.05);
                min-height: 128px;
                margin-bottom: 8px;
            }

            .compact-metric-grid {
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                gap: 12px;
                margin: 12px 0 14px 0;
            }

            .compact-metric-card {
                background: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 18px;
                padding: 14px 14px 12px 14px;
                min-height: 94px;
                box-shadow: 0 6px 16px rgba(0,0,0,0.035);
                display: flex;
                flex-direction: column;
                justify-content: center;
            }

            .compact-metric-label {
                font-size: 13px;
                font-weight: 750;
                color: #555;
                line-height: 1.25;
                margin-bottom: 8px;
                white-space: normal;
                word-break: keep-all;
            }

            .compact-metric-value {
                font-size: 23px;
                font-weight: 900;
                color: #2b2d36;
                line-height: 1.12;
                letter-spacing: -0.7px;
                white-space: normal;
                word-break: keep-all;
                overflow-wrap: anywhere;
            }

            .compact-metric-value.small {
                font-size: 20px;
                line-height: 1.18;
            }

            @media (max-width: 1250px) {
                .compact-metric-grid {
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                }
            }

            @media (max-width: 760px) {
                .compact-metric-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                .compact-metric-value {
                    font-size: 20px;
                }

                .compact-metric-value.small {
                    font-size: 18px;
                }
            }
            .dash-menu-title {
                font-size: 17px;
                font-weight: 900;
                margin-bottom: 8px;
            }

            .dash-menu-desc {
                color: #666;
                font-size: 13px;
                line-height: 1.55;
                min-height: 44px;
            }

            .dash-page-box {
                padding: 20px 24px;
                border-radius: 24px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                box-shadow: 0 8px 22px rgba(0,0,0,0.045);
                margin: 12px 0 16px 0;
            }

            .formula-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 14px;
                margin-top: 16px;
                margin-bottom: 18px;
            }

            .formula-card {
                padding: 18px 20px;
                border-radius: 20px;
                background: linear-gradient(135deg, #ffffff 0%, #fffbea 100%);
                border: 1px solid #ffe066;
                box-shadow: 0 6px 16px rgba(0,0,0,0.035);
            }

            .formula-title {
                font-size: 15px;
                font-weight: 900;
                margin-bottom: 8px;
                color: #222;
            }

            .formula-desc {
                color: #555;
                font-size: 13px;
                line-height: 1.6;
            }

            .formula-main {
                padding: 20px 22px;
                border-radius: 18px;
                background: linear-gradient(135deg, #eef7ff 0%, #ffffff 100%);
                border: 1px solid #a5d8ff;
                margin: 14px 0 18px 0;
                line-height: 1.7;
            }

            @media (max-width: 1000px) {
                .formula-grid {
                    grid-template-columns: 1fr;
                }
            }

            @media (max-width: 1000px) {
                .dash-step-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================
# 대시보드 메인
# =========================
def _show_dashboard_home(
    final_recommendations,
    final_rec_summary,
    stores=None,
    products=None,
    inventory=None,
    promotion_result=None,
    transfer_path_result=None,
):
    best = _best_row(final_recommendations)

    if best is None:
        st.info("대시보드에 표시할 최종 추천 결과가 없습니다.")
        return

    product_name = _safe_get(best, "product_name")
    source_store = _safe_get(best, "source_store")
    target_store = _safe_get(best, "target_store")
    suggested_qty = _safe_get(best, "suggested_qty", 0)
    final_recommendation = _safe_get(best, "final_recommendation")
    estimated_cost = _safe_get(best, "estimated_cost", 0)
    heuristic_score = _safe_get(best, "heuristic_score", "-")
    heuristic_grade = _safe_get(best, "heuristic_grade", "-")
    original_reason = _safe_get(best, "reason", "-")
    display_grade = _display_grade(heuristic_grade)

    dashboard_reason = original_reason
    dashboard_transport_type = "-"
    dashboard_transport_cost = estimated_cost
    try:
        dashboard_cost_table = _build_cost_comparison_table(
            stores=stores,
            products=products,
            inventory=inventory,
            final_recommendations=final_recommendations,
            promotion_result=promotion_result,
            transfer_path_result=transfer_path_result,
            discount_rate=20.0,
        )

        if dashboard_cost_table is not None and not dashboard_cost_table.empty:
            best_cost_row = dashboard_cost_table.iloc[0]
            dashboard_reason = best_cost_row.get("비율 기반 추천 이유", original_reason)
            dashboard_transport_type = best_cost_row.get("추천 이동수단", "-")
            dashboard_transport_cost = best_cost_row.get("AI 이동수단 비용", estimated_cost)

            dashboard_ratios = {
                "수익 회수 가능성": str(best_cost_row.get("수익 회수 가능성", "0%")).replace("%", ""),
                "폐기 위험 감소 효과": str(best_cost_row.get("폐기 위험 감소 효과", "0%")).replace("%", ""),
                "비용 부담률": str(best_cost_row.get("비용 부담률", "0%")).replace("%", ""),
            }
    except Exception:
        dashboard_reason = original_reason

    st.markdown(
        f"""
        <div class="dash-hero">
            <div class="dash-small-title">AI 추천 결과</div>
            <div class="dash-main-title">{product_name}</div>
            <div style="font-size: 18px; font-weight: 800; color:#333; margin-top:-2px; margin-bottom:12px;">
                {source_store} → {target_store}
            </div>
            <div class="dash-desc">
                추천 전략: <b>{final_recommendation}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_qty = _escape_text(f"{suggested_qty}개")
    metric_cost = _escape_text(_format_money(estimated_cost))
    metric_score = _escape_text(f"{heuristic_score}점")
    metric_grade = _escape_text(display_grade)
    metric_transport = _escape_text(dashboard_transport_type)

    st.markdown(
        f"""
        <div class="compact-metric-grid">
            <div class="compact-metric-card">
                <div class="compact-metric-label">추천 수량</div>
                <div class="compact-metric-value">{metric_qty}</div>
            </div>
            <div class="compact-metric-card">
                <div class="compact-metric-label">예상 비용</div>
                <div class="compact-metric-value small">{metric_cost}</div>
            </div>
            <div class="compact-metric-card">
                <div class="compact-metric-label">총점</div>
                <div class="compact-metric-value">{metric_score}</div>
            </div>
            <div class="compact-metric-card">
                <div class="compact-metric-label">추천 등급</div>
                <div class="compact-metric-value">{metric_grade}</div>
            </div>
            <div class="compact-metric-card">
                <div class="compact-metric-label">추천 이동수단</div>
                <div class="compact-metric-value small">{metric_transport}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    dashboard_ratios = _estimate_ratio_summary(
        move_cost=estimated_cost,
        discount_loss_cost=0,
        disposal_cost=max(_safe_numeric(estimated_cost, 0) * 1.4, 1),
        score=heuristic_score,
        qty=suggested_qty,
    )

    with st.expander("추천 근거", expanded=False):
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("수익 회수 가능성", f"{dashboard_ratios['수익 회수 가능성']}%")
        r2.metric("폐기 위험 감소 효과", f"{dashboard_ratios['폐기 위험 감소 효과']}%")
        r3.metric("비용 부담률", f"{dashboard_ratios['비용 부담률']}%")
        r4.metric("이동수단 비용", _format_money(dashboard_transport_cost))

        st.write(dashboard_reason)

    with st.expander("📈 추천 후보 더보기", expanded=False):
        top_candidates = final_recommendations.copy()

        # 원본 index를 보관해야 후보를 눌렀을 때 대시보드 메인 카드가 같은 후보로 바뀜
        top_candidates["_candidate_original_index"] = top_candidates.index

        if "greedy_rank" in top_candidates.columns:
            top_candidates["_rank"] = pd.to_numeric(top_candidates["greedy_rank"], errors="coerce")
            top_candidates = top_candidates.sort_values("_rank", na_position="last")
        elif "heuristic_score" in top_candidates.columns:
            top_candidates["_score"] = pd.to_numeric(top_candidates["heuristic_score"], errors="coerce")
            top_candidates = top_candidates.sort_values("_score", ascending=False, na_position="last")
        elif "estimated_cost" in top_candidates.columns:
            top_candidates["_cost"] = pd.to_numeric(top_candidates["estimated_cost"], errors="coerce")
            top_candidates = top_candidates.sort_values("_cost", na_position="last")

        # 현재 대시보드에 올라온 후보는 더보기 목록에서 제외.
        # 다른 후보를 누르면 기존 메인 후보가 다시 더보기 목록으로 내려감.
        current_candidate = _best_row(final_recommendations)
        current_original_index = None

        try:
            if current_candidate is not None:
                current_original_index = current_candidate.name
        except Exception:
            current_original_index = None

        if current_original_index is not None:
            top_candidates = top_candidates[
                top_candidates["_candidate_original_index"].astype(str) != str(current_original_index)
            ]

        top_candidates = top_candidates.head(5).reset_index(drop=True)

        if top_candidates.empty:
            st.info("표시할 다른 추천 후보가 없습니다.")
        else:
            for candidate_position, candidate in top_candidates.iterrows():
                original_index = candidate.get("_candidate_original_index")

                c_product = _safe_get(candidate, "product_name", "-")
                c_source = _safe_get(candidate, "source_store", "-")
                c_target = _safe_get(candidate, "target_store", "-")
                c_qty = _safe_get(candidate, "suggested_qty", 0)
                c_cost = _format_money(_safe_get(candidate, "estimated_cost", 0))
                c_strategy = _safe_get(candidate, "final_recommendation", "-")
                c_score = _safe_get(candidate, "heuristic_score", "-")
                c_grade = _display_grade(_safe_get(candidate, "heuristic_grade", "-"))

                rank_text = candidate_position + 1
                if "greedy_rank" in candidate.index and not pd.isna(candidate.get("greedy_rank")):
                    try:
                        rank_text = int(float(candidate.get("greedy_rank")))
                    except Exception:
                        rank_text = candidate_position + 1

                grade_color = _grade_color(c_grade)

                # 순위는 작게, 후보 정보는 크게 보여줌
                st.markdown(
                    f"""
                    <div style="
                        margin-top: 10px;
                        margin-bottom: 3px;
                        font-size: 12px;
                        color: #888;
                        font-weight: 800;
                    ">
                        후보 <span style="color:{grade_color};">#{rank_text}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # 별도의 '이 후보 보기' 버튼을 없애고,
                # 후보 항목 자체가 선택 버튼 역할을 하게 함.
                button_label = (
                    f"{c_product}  ·  {c_source} → {c_target}\n\n"
                    f"{c_score}점 · {c_grade}  |  {c_qty}개  |  {c_cost}  |  {c_strategy}"
                )

                if st.button(
                    button_label,
                    width="stretch",
                    key=f"candidate_row_select_{candidate_position}_{original_index}",
                ):
                    st.session_state["dashboard_selected_candidate_index"] = original_index
                    st.rerun()

    menu_col1, menu_col2, menu_col3 = st.columns(3)

    with menu_col1:
        if st.button("🧠 AI 추천 결과", width="stretch", key="go_score"):
            _go("score")

    with menu_col2:
        if st.button("🗺 재고 이동 지도", width="stretch", key="go_movement"):
            _go("movement")

    with menu_col3:
        if st.button("🤖 강화학습 비교", width="stretch", key="go_rl"):
            _go("rl")

    with st.expander("관리자용 메뉴", expanded=False):
        admin_col1, admin_col2, admin_col3 = st.columns(3)

        with admin_col1:
            if st.button("총점 계산 방식", width="stretch", key="go_score_formula_admin"):
                _go("score_formula")

        with admin_col2:
            if st.button("비용 비교", width="stretch", key="go_cost_compare_admin"):
                _go("cost_compare")

        with admin_col3:
            if st.button("이동수단 기준", width="stretch", key="go_transport_rule_admin"):
                _go("transport_rule")

        admin_col4, admin_col5, admin_col6 = st.columns(3)

        with admin_col4:
            if st.button("그래프 보기", width="stretch", key="go_graph_admin"):
                _go("graph")

        with admin_col5:
            if st.button("설명 보기", width="stretch", key="go_explain_admin"):
                _go("explain")

        with admin_col6:
            if st.button("상세 데이터 보기", width="stretch", key="go_data_admin"):
                _go("data")







# =========================
# 상품별 AI 추천 화면 유틸
# =========================
def _grade_from_score(score, grade_value="-"):
    base_grade = _display_grade(grade_value)
    if base_grade in ["최적", "권장"]:
        return base_grade

    score_value = _safe_numeric(score, None)
    if score_value is None:
        return base_grade

    if score_value >= 80:
        return "최적"
    if score_value >= 65:
        return "권장"
    return "검토"


def _grade_color(grade):
    grade = str(grade)
    if grade == "최적":
        return "#ff6b6b"
    if grade == "권장":
        return "#f59f00"
    if grade == "검토":
        return "#4dabf7"
    return "#adb5bd"


def _make_product_filtered_df(df, product_query="", product_selected="전체"):
    if df is None or df.empty:
        return pd.DataFrame()

    filtered = df.copy()
    product_col = "product_name" if "product_name" in filtered.columns else "상품명" if "상품명" in filtered.columns else None
    if product_col is None:
        return filtered

    if product_selected and product_selected != "전체":
        filtered = filtered[filtered[product_col].astype(str) == str(product_selected)]

    if product_query:
        filtered = filtered[filtered[product_col].astype(str).str.contains(str(product_query), case=False, na=False)]

    return filtered


def _render_product_filter(df, key_prefix="product_filter"):
    """
    상품명 검색/선택 필터.

    - 검색어 입력 후 Enter 가능
    - 검색 버튼 클릭 가능
    - 검색어가 비어 있으면 전체 상품 표시
    """

    if df is None or df.empty:
        return "", "전체"

    product_col = "product_name" if "product_name" in df.columns else "상품명" if "상품명" in df.columns else None
    if product_col is None:
        return "", "전체"

    query_key = f"{key_prefix}_query"
    committed_key = f"{key_prefix}_committed_query"

    if committed_key not in st.session_state:
        st.session_state[committed_key] = ""

    search_col, button_col = st.columns([5, 1])

    with search_col:
        typed_query = st.text_input(
            "상품명 검색",
            value=st.session_state.get(committed_key, ""),
            placeholder="예: 우유, 도시락, 냉동",
            key=query_key,
        )

    with button_col:
        st.write("")
        st.write("")
        search_clicked = st.button(
            "검색",
            width="stretch",
            key=f"{key_prefix}_search_button",
        )

    # Enter로 입력값이 바뀌어도 검색 반영, 검색 버튼을 눌러도 검색 반영
    if search_clicked or typed_query != st.session_state.get(committed_key, ""):
        st.session_state[committed_key] = str(typed_query).strip()

    product_query = st.session_state.get(committed_key, "").strip()

    product_names = sorted([str(x) for x in df[product_col].dropna().unique()])

    if product_query:
        filtered_product_names = [
            name for name in product_names
            if product_query.lower() in name.lower()
        ]
    else:
        filtered_product_names = product_names

    if not filtered_product_names:
        product_selected = "전체"
        st.info("검색 결과가 없습니다.")
    else:
        product_selected = st.selectbox(
            "상품 선택",
            ["전체"] + filtered_product_names,
            key=f"{key_prefix}_select",
        )

    if product_query:
        clear_col, _ = st.columns([1, 5])
        with clear_col:
            if st.button("초기화", width="stretch", key=f"{key_prefix}_clear_button"):
                st.session_state[committed_key] = ""
                st.rerun()

    return product_query, product_selected


def _download_filtered_excel_button(df, file_name, key):
    if df is None or df.empty:
        return

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="filtered_result")

    st.download_button(
        "현재 필터 결과 엑셀 다운로드",
        data=output.getvalue(),
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=key,
    )


def _build_score_view(final_recommendations):
    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame()

    view_cols = ["product_name", "source_store", "target_store", "suggested_qty", "estimated_cost", "final_recommendation", "heuristic_score", "heuristic_grade", "greedy_reason"]
    rename_map = {
        "product_name": "상품명",
        "source_store": "보내는 점포",
        "target_store": "받는 점포",
        "suggested_qty": "추천 수량",
        "estimated_cost": "예상 비용",
        "final_recommendation": "추천 전략",
        "heuristic_score": "총점",
        "heuristic_grade": "추천 등급",
        "greedy_reason": "그리디 선택 근거",
    }

    score_view = final_recommendations[[c for c in view_cols if c in final_recommendations.columns]].rename(columns=rename_map)

    if "총점" in score_view.columns:
        score_view["총점"] = pd.to_numeric(score_view["총점"], errors="coerce").fillna(0).round(1)

    if "추천 등급" in score_view.columns:
        score_view["추천 등급"] = score_view.apply(lambda row: _grade_from_score(row.get("총점", 0), row.get("추천 등급", "-")), axis=1)
    elif "총점" in score_view.columns:
        score_view["추천 등급"] = score_view["총점"].apply(lambda score: _grade_from_score(score, "-"))

    if "예상 비용" in score_view.columns:
        score_view["예상 비용"] = pd.to_numeric(score_view["예상 비용"], errors="coerce").fillna(0)

    if "총점" in score_view.columns:
        score_view = score_view.sort_values("총점", ascending=False, na_position="last")

    return score_view.reset_index(drop=True)


def _render_score_bar_chart(score_view, max_rows=5):
    """
    상품별 AI 추천 결과 그래프.

    기존 버전은 HTML div 문자열을 직접 만들어서 표시했는데,
    일부 환경에서 HTML 코드가 그대로 화면에 보이는 문제가 생길 수 있었다.
    그래서 여기서는 Streamlit 기본 progress bar로 안전하게 표시한다.
    """
    if score_view is None or score_view.empty or "총점" not in score_view.columns:
        st.info("그래프로 표시할 총점 데이터가 없습니다.")
        return

    chart_df = score_view.copy().head(max_rows)
    st.markdown("### 상품별 AI 추천 결과")

    for _, row in chart_df.iterrows():
        product_name = str(row.get("상품명", "-"))
        source_store = str(row.get("보내는 점포", "-"))
        target_store = str(row.get("받는 점포", "-"))

        score = _clamp(_safe_numeric(row.get("총점", 0), 0))
        grade = _display_grade(row.get("추천 등급", _grade_from_score(score, "-")))

        label = f"{product_name}  {source_store} → {target_store}"

        st.markdown(f"**{label}**")
        st.progress(int(score))
        st.write(f"{score:.0f}점 · {grade}")


# =========================
# 개별 페이지
# =========================
def _show_score_page(final_recommendations):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🧠 상품별 AI 추천 결과")

    if st.button("💰 비용 산정 기준 보기", width="stretch", key="go_cost_compare_from_score"):
        _go("cost_compare")

    if final_recommendations is None or final_recommendations.empty:
        st.info("표시할 추천 후보가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    score_view = _build_score_view(final_recommendations)
    product_query, product_selected = _render_product_filter(score_view, key_prefix="score_page_product")
    filtered_view = _make_product_filtered_df(score_view, product_query, product_selected)

    if filtered_view.empty:
        st.info("선택한 상품명에 해당하는 추천 결과가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    selected_grade = st.radio("추천 등급 필터", ["전체", "최적", "권장", "검토"], horizontal=True, key="score_page_grade_filter")

    if selected_grade != "전체" and "추천 등급" in filtered_view.columns:
        filtered_view = filtered_view[filtered_view["추천 등급"] == selected_grade]

    if filtered_view.empty:
        st.info("선택한 등급에 해당하는 추천 결과가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    main_cols = ["상품명", "보내는 점포", "받는 점포", "추천 수량", "예상 비용", "추천 전략", "총점", "추천 등급"]
    display_table = filtered_view[[c for c in main_cols if c in filtered_view.columns]].copy()

    if "예상 비용" in display_table.columns:
        display_table["예상 비용"] = display_table["예상 비용"].apply(_format_money)

    st.subheader("AI 추천 결과 요약")
    _safe_dataframe(display_table, width="stretch", max_rows=300)
    _download_filtered_excel_button(display_table, file_name="상품별_AI_추천_결과.xlsx", key="download_score_filtered_excel")
    _render_score_bar_chart(filtered_view, max_rows=12)

    with st.expander("그리디 선택 근거 상세보기", expanded=False):
        if "그리디 선택 근거" not in filtered_view.columns:
            st.info("표시할 그리디 선택 근거가 없습니다.")
        else:
            reason_cols = ["상품명", "보내는 점포", "받는 점포", "총점", "추천 등급", "그리디 선택 근거"]
            reason_view = filtered_view[[c for c in reason_cols if c in filtered_view.columns]].copy()
            _safe_dataframe(reason_view, width="stretch", max_rows=300)

    st.markdown("</div>", unsafe_allow_html=True)



def _first_existing_value(row, columns, default=None):
    if row is None:
        return default

    for col in columns:
        try:
            if col in row.index:
                value = row.get(col)
                if not pd.isna(value):
                    return value
        except Exception:
            continue

    return default


def _find_matching_row(df, product_name, source_store, target_store):
    if df is None or df.empty:
        return None

    required = ["product_name", "source_store", "target_store"]

    if not all(col in df.columns for col in required):
        return None

    matched = df[
        (df["product_name"] == product_name)
        & (df["source_store"] == source_store)
        & (df["target_store"] == target_store)
    ]

    if matched.empty:
        return None

    return matched.iloc[0]


def _get_disposal_unit_cost(products, inventory, product_name, source_store, stores):
    default_disposal_cost = 300

    try:
        product_id = None
        source_store_id = None

        if products is not None and not products.empty:
            if "product_name" in products.columns and "product_id" in products.columns:
                matched_product = products[products["product_name"] == product_name]
                if not matched_product.empty:
                    product_id = matched_product.iloc[0]["product_id"]
                    product_row = matched_product.iloc[0]

                    product_cost = _first_existing_value(
                        product_row,
                        [
                            "disposal_cost_per_unit",
                            "disposal_cost",
                            "waste_cost_per_unit",
                            "폐기비용",
                        ],
                        None,
                    )

                    if product_cost is not None:
                        return _safe_numeric(product_cost, default_disposal_cost)

        if stores is not None and not stores.empty:
            if "store_name" in stores.columns and "store_id" in stores.columns:
                matched_store = stores[stores["store_name"] == source_store]
                if not matched_store.empty:
                    source_store_id = matched_store.iloc[0]["store_id"]

        if inventory is not None and not inventory.empty and product_id is not None and source_store_id is not None:
            if "store_id" in inventory.columns and "product_id" in inventory.columns:
                matched_inventory = inventory[
                    (inventory["store_id"] == source_store_id)
                    & (inventory["product_id"] == product_id)
                ]

                if not matched_inventory.empty:
                    inv_row = matched_inventory.iloc[0]
                    inv_cost = _first_existing_value(
                        inv_row,
                        [
                            "disposal_cost_per_unit",
                            "disposal_cost",
                            "waste_cost_per_unit",
                            "폐기비용",
                        ],
                        None,
                    )

                    if inv_cost is not None:
                        return _safe_numeric(inv_cost, default_disposal_cost)

    except Exception:
        pass

    return default_disposal_cost


def _build_cost_comparison_table(
    stores,
    products,
    inventory,
    final_recommendations,
    promotion_result,
    transfer_path_result,
    discount_rate=20.0,
):
    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame()

    records = []

    for _, rec in final_recommendations.iterrows():
        product_name = _safe_get(rec, "product_name")
        source_store = _safe_get(rec, "source_store")
        target_store = _safe_get(rec, "target_store")
        suggested_qty = _safe_numeric(_safe_get(rec, "suggested_qty", 0), 0)
        final_recommendation = _safe_get(rec, "final_recommendation", "-")
        total_score = _safe_get(rec, "heuristic_score", "-")
        grade = _display_grade(_safe_get(rec, "heuristic_grade", "-"))

        transfer_row = _find_matching_row(
            transfer_path_result,
            product_name,
            source_store,
            target_store,
        )

        promo_row = _find_matching_row(
            promotion_result,
            product_name,
            source_store,
            target_store,
        )

        move_cost_candidates = []

        if transfer_row is not None:
            for col in ["transfer_cost", "direct_cost", "via_cost", "estimated_transfer_cost"]:
                value = _first_existing_value(transfer_row, [col], None)
                numeric_value = _safe_numeric(value, None)

                if numeric_value is not None and numeric_value > 0:
                    move_cost_candidates.append(numeric_value)

        rec_estimated_cost = _safe_numeric(_safe_get(rec, "estimated_cost", 0), 0)

        if rec_estimated_cost > 0:
            move_cost_candidates.append(rec_estimated_cost)

        move_cost = min(move_cost_candidates) if move_cost_candidates else 0

        unit_price = _get_unit_price(
            products=products,
            inventory=inventory,
            product_name=product_name,
            source_store=source_store,
            stores=stores,
        )

        # 비용 산정 기준 화면의 할인율 입력값이 바로 반영되도록
        # 기존 promotion_result의 고정 계산값을 쓰지 않고, 현재 입력 할인율로 다시 계산한다.
        #
        # 할인손실비용 = 단가 × 추천 수량 × 할인율
        discount_rate = _safe_numeric(discount_rate, 20.0)
        discount_loss_cost = unit_price * suggested_qty * (discount_rate / 100)

        disposal_unit_cost = _get_disposal_unit_cost(
            products,
            inventory,
            product_name,
            source_store,
            stores,
        )

        disposal_cost = disposal_unit_cost * suggested_qty

        cost_values = {
            "이동": move_cost,
            "할인": discount_loss_cost,
            "폐기": disposal_cost,
        }

        positive_costs = {
            key: value
            for key, value in cost_values.items()
            if value is not None and value > 0
        }

        if positive_costs:
            minimum_cost_action = min(positive_costs, key=positive_costs.get)
        else:
            minimum_cost_action = "-"

        distance_km = 5.0

        if transfer_row is not None:
            distance_km = _estimate_route_distance_km(transfer_row)

        transport_type = _choose_transport_type(
            product_name=product_name,
            qty=suggested_qty,
            recommended_path=final_recommendation,
            selected_transport_type="AI 추천 이동수단",
        )

        transport_options = _calculate_transport_options(
            product_name=product_name,
            qty=suggested_qty,
            distance_km=distance_km,
        )

        transport_cost_map = {
            row["이동수단"]: row["예상 이동비용"]
            for row in transport_options
        }

        selected_transport_cost = transport_cost_map.get(
            transport_type,
            move_cost,
        )

        ratios = _estimate_ratio_summary(
            move_cost=move_cost,
            discount_loss_cost=discount_loss_cost,
            disposal_cost=disposal_cost,
            score=total_score,
            qty=suggested_qty,
        )

        ratio_reason = _make_ratio_reason(ratios, final_recommendation)

        records.append(
            {
                "상품명": product_name,
                "보내는 점포": source_store,
                "받는 점포": target_store,
                "추천 수량": int(suggested_qty),
                "추천 이동수단": transport_type,
                "AI 이동수단 비용": selected_transport_cost,
                "오토바이 비용": transport_cost_map.get("오토바이", 0),
                "소형 차량 비용": transport_cost_map.get("소형 차량", 0),
                "소형 트럭 비용": transport_cost_map.get("소형 트럭", 0),
                "냉동/냉장 탑차 비용": transport_cost_map.get("냉동/냉장 탑차", 0),
                "이동비용": move_cost,
                "할인손실비용": discount_loss_cost,
                "적용 할인율": f"{discount_rate:g}%",
                "폐기비용": disposal_cost,
                "비용 최소 방식": minimum_cost_action,
                "AI 추천 방식": final_recommendation,
                "수익 회수 가능성": f"{ratios['수익 회수 가능성']}%",
                "폐기 위험 감소 효과": f"{ratios['폐기 위험 감소 효과']}%",
                "비용 부담률": f"{ratios['비용 부담률']}%",
                "비율 기반 추천 이유": ratio_reason,
                "총점": total_score,
                "추천 등급": grade,
            }
        )

    result = pd.DataFrame(records)

    if result.empty:
        return result

    if "총점" in result.columns:
        result["_score_sort"] = pd.to_numeric(result["총점"], errors="coerce")
        result = result.sort_values("_score_sort", ascending=False, na_position="last")
        result = result.drop(columns=["_score_sort"])

    return result.reset_index(drop=True)




def _transport_usage_text(name):
    if name == "오토바이":
        return "소량·근거리 일반 상품"
    if name == "소형 차량":
        return "중간 수량 점포 간 이동"
    if name == "소형 트럭":
        return "대량 이동 또는 DC 경유"
    if name == "냉동/냉장 탑차":
        return "냉장·냉동·신선식품"
    return "일반 이동"


def _show_transport_rule_page():
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🚛 이동수단·비용 산정 기준")


    cost_rule_df = pd.DataFrame([
        {"항목": "이동비용", "설명": "추천 경로의 이동거리, 경유 여부, 선택 이동수단의 단가를 반영한 예상 운송비"},
        {"항목": "할인손실비용", "설명": "할인 판매 시 정상 판매 대비 감소하는 예상 매출 손실"},
        {"항목": "폐기비용", "설명": "처리하지 못한 재고를 폐기할 때 발생하는 예상 손실 비용"},
        {"항목": "추천 이동수단", "설명": "상품 특성, 이동 수량, 거리, 경유 여부를 기준으로 선택한 운송수단"},
        {"항목": "AI 추천 방식", "설명": "비용, 거리, 시간, 추천 수량, 재고 처리 효과를 함께 반영한 종합 판단"},
    ])

    st.subheader("비용 산정 기준")
    _safe_dataframe(cost_rule_df, width="stretch")

    st.subheader("이동수단별 기준")
    transport_df = pd.DataFrame([
        {
            "이동수단": f"{profile['icon']} {name}",
            "기본비용": _format_money(profile["base_cost"]),
            "km당 비용": _format_money(profile["cost_per_km"]),
            "적재 가능 수량": f"{profile['capacity']}개",
            "특징": profile["description"],
            "추천 상황": _transport_usage_text(name),
        }
        for name, profile in TRANSPORT_PROFILES.items()
    ])

    _safe_dataframe(transport_df, width="stretch")

    st.markdown(
        """
        - **오토바이**: 소량·근거리 일반 상품 이동에 우선 적용합니다.  
        - **소형 차량**: 중간 수량의 점포 간 이동에 적용합니다.  
        - **소형 트럭**: 대량 이동 또는 DC 경유 이동에 적용합니다.  
        - **냉동/냉장 탑차**: 우유, 냉장, 냉동, 아이스, 샐러드처럼 온도 유지가 필요한 상품에 우선 적용합니다.  
        - 최종 선택은 비용만이 아니라 추천 수량, 거리, 시간, 재고 처리 효과까지 반영한 AI 추천 결과와 함께 판단합니다.
        """
    )

    st.markdown("</div>", unsafe_allow_html=True)



def _show_cost_compare_page(
    stores,
    products,
    inventory,
    final_recommendations,
    promotion_result,
    transfer_path_result,
):
    _back_to_dashboard()

    if st.button("← 상품별 AI 추천 결과로 돌아가기", width="stretch", key="back_to_ai_recommendation_from_cost"):
        _go("score")

    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("💰 상품별 비용 산정 기준")


    discount_rate_for_loss = st.number_input("할인손실비용 계산용 할인율(%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0, key="cost_compare_discount_rate")

    compare_table = _build_cost_comparison_table(
        stores=stores,
        products=products,
        inventory=inventory,
        final_recommendations=final_recommendations,
        promotion_result=promotion_result,
        transfer_path_result=transfer_path_result,
        discount_rate=discount_rate_for_loss,
    )

    if compare_table.empty:
        st.info("비교할 비용 데이터가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    product_query, product_selected = _render_product_filter(compare_table, key_prefix="cost_compare_product")
    filtered_table = _make_product_filtered_df(compare_table, product_query, product_selected)

    if filtered_table.empty:
        st.info("선택한 상품명에 해당하는 비용 비교 결과가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    best_row = filtered_table.iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("이동비용", _format_money(best_row["이동비용"]))
    c2.metric("할인손실비용", _format_money(best_row["할인손실비용"]))
    c3.metric("폐기비용", _format_money(best_row["폐기비용"]))

    cost_cols = [
        "보내는 점포",
        "받는 점포",
        "이동비용",
        "할인손실비용",
        "적용 할인율",
        "폐기비용",
        "비용 최소 방식",
        "AI 추천 방식",
        "수익 회수 가능성",
        "폐기 위험 감소 효과",
        "비용 부담률",
    ]
    display_table = filtered_table[[c for c in cost_cols if c in filtered_table.columns]].copy()

    for col in ["이동비용", "할인손실비용", "폐기비용"]:
        if col in display_table.columns:
            display_table[col] = display_table[col].apply(_format_money)

    st.subheader("비용 산정 결과")
    _safe_dataframe(display_table, width="stretch", max_rows=300)
    _download_filtered_excel_button(filtered_table, file_name="상품별_비용_비교.xlsx", key="download_cost_filtered_excel")

    with st.expander("비용 계산 기준", expanded=False):
        if st.button("이동수단 기준 보기", width="stretch", key="go_transport_rule_from_cost"):
            _go("transport_rule")

        st.markdown(
            """
            - **이동비용**: 추천 경로의 이동거리, 경유 여부, 선택 이동수단의 단가를 반영한 예상 운송비.
            - **할인손실비용**: 할인 판매 시 정상 판매 대비 감소하는 예상 매출 손실.
            - **폐기비용**: 처리하지 못한 재고를 폐기할 때 발생하는 예상 손실 비용.
            - **추천 이동수단**: 상품 특성, 추천 수량, 경유 여부를 기준으로 오토바이, 소형 차량, 소형 트럭, 냉동/냉장 탑차 중 하나를 제안합니다.
            - **AI 추천 방식**: 비용뿐 아니라 총점, 추천 수량, 거리, 시간, 재고 처리 효과까지 함께 반영한 결과입니다.
            """
        )

    st.markdown("</div>", unsafe_allow_html=True)



def _show_score_formula_page(final_recommendations):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🧮 총점 계산 방식")

    if final_recommendations is None or final_recommendations.empty:
        st.info("총점 계산 방식을 확인할 추천 후보가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    best = _best_row(final_recommendations)

    product_name = _safe_get(best, "product_name")
    source_store = _safe_get(best, "source_store")
    target_store = _safe_get(best, "target_store")
    suggested_qty = _safe_get(best, "suggested_qty", 0)
    estimated_cost = _safe_get(best, "estimated_cost", 0)
    total_score = _safe_get(best, "heuristic_score", "-")
    grade = _display_grade(_safe_get(best, "heuristic_grade", "-"))
    strategy = _safe_get(best, "final_recommendation", "-")

    st.markdown(
        f"""
        <div class="formula-main">
            <b>선택 후보:</b> {product_name}<br>
            <b>이동 경로:</b> {source_store} → {target_store}<br>
            <b>추천 전략:</b> {strategy}<br>
            <b>현재 총점:</b> {total_score}점 / <b>추천 등급:</b> {grade}
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("추천 수량", f"{suggested_qty}개")
    c2.metric("예상 비용", _format_money(estimated_cost))
    c3.metric("총점", f"{total_score}점")

    st.markdown("### 총점 구조")

    st.markdown(
        """
        <div class="formula-main">
            <b>총점</b>은 추천 후보를 비교하기 위한 평가 점수입니다.<br>
            기존 악성재고 위험점수는 <b>악성재고 여부 판단</b>에 사용하고,
            총점은 <b>여러 처리 후보 중 어떤 후보를 우선 실행할지</b> 결정하는 데 사용합니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="formula-grid">
            <div class="formula-card">
                <div class="formula-title">1. 비용 점수</div>
                <div class="formula-desc">
                    예상 비용이 낮을수록 높은 점수를 부여합니다.<br>
                    이동비용, 프로모션 비용, 처리비용 등이 낮은 후보가 유리합니다.
                </div>
            </div>
            <div class="formula-card">
                <div class="formula-title">2. 수량 점수</div>
                <div class="formula-desc">
                    처리 가능한 재고 수량이 많을수록 높은 점수를 부여합니다.<br>
                    악성재고 해소 효과가 큰 후보를 우선적으로 평가합니다.
                </div>
            </div>
            <div class="formula-card">
                <div class="formula-title">3. 전략 점수</div>
                <div class="formula-desc">
                    재배치, DC 경유, 프로모션 등 추천 전략의 운영 효율성을 반영합니다.<br>
                    비용 절감과 재고 처리 효과가 좋은 전략에 가산점을 줍니다.
                </div>
            </div>
            <div class="formula-card">
                <div class="formula-title">4. 조건 보정 점수</div>
                <div class="formula-desc">
                    거리, 거래가능시간, 추천 이유, 수요 차이 등을 보정 요소로 반영합니다.<br>
                    실제 실행 가능성이 높은 후보가 더 좋은 평가를 받습니다.
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 등급 기준")

    grade_df = pd.DataFrame(
        [
            {"추천 등급": "최적", "의미": "현재 조건에서 가장 우선 실행할 후보"},
            {"추천 등급": "권장", "의미": "실행 가치가 있으나 1순위는 아닌 후보"},
            {"추천 등급": "보류", "의미": "비용, 수량, 조건 측면에서 즉시 실행 우선순위가 낮은 후보"},
        ]
    )

    _safe_dataframe(grade_df, width="stretch")

    with st.expander("현재 추천 후보 전체 총점 보기", expanded=False):
        view_cols = [
            "greedy_rank",
            "product_name",
            "source_store",
            "target_store",
            "suggested_qty",
            "estimated_cost",
            "final_recommendation",
            "heuristic_score",
            "heuristic_grade",
        ]

        score_table = final_recommendations[
            [c for c in view_cols if c in final_recommendations.columns]
        ].rename(
            columns={
                "greedy_rank": "순위",
                "product_name": "상품명",
                "source_store": "보내는 점포",
                "target_store": "받는 점포",
                "suggested_qty": "추천 수량",
                "estimated_cost": "예상 비용",
                "final_recommendation": "추천 전략",
                "heuristic_score": "총점",
                "heuristic_grade": "추천 등급",
            }
        )

        if "추천 등급" in score_table.columns:
            score_table["추천 등급"] = _map_grade_series(score_table["추천 등급"])

        _safe_dataframe(score_table, width="stretch")

    st.markdown("</div>", unsafe_allow_html=True)


def _show_graph_page(final_recommendations, final_rec_summary, promotion_result, transfer_path_result):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("📊 그래프 페이지")

    if final_rec_summary is not None and not final_rec_summary.empty:
        if "final_recommendation" in final_rec_summary.columns and "count" in final_rec_summary.columns:
            st.subheader("추천 유형별 건수")
            st.bar_chart(final_rec_summary.set_index("final_recommendation")["count"])

    if final_recommendations is not None and not final_recommendations.empty:
        if "estimated_cost" in final_recommendations.columns:
            cost_df = final_recommendations.copy()
            cost_df["estimated_cost"] = pd.to_numeric(cost_df["estimated_cost"], errors="coerce")
            cost_df["label"] = (
                cost_df["product_name"].astype(str)
                + " | "
                + cost_df["source_store"].astype(str)
                + "→"
                + cost_df["target_store"].astype(str)
            )
            cost_df = cost_df.dropna(subset=["estimated_cost"]).sort_values("estimated_cost").head(5)

            if not cost_df.empty:
                st.subheader("예상 비용이 낮은 추천 후보 Top 5")
                st.bar_chart(cost_df.set_index("label")["estimated_cost"])

    if transfer_path_result is not None and not transfer_path_result.empty:
        if "recommended_path" in transfer_path_result.columns:
            st.subheader("이동 방식별 후보 수")
            path_summary = (
                transfer_path_result.groupby("recommended_path")
                .size()
                .reset_index(name="count")
            )
            st.bar_chart(path_summary.set_index("recommended_path")["count"])

    if promotion_result is not None and not promotion_result.empty:
        if "final_decision" in promotion_result.columns:
            st.subheader("프로모션 vs 재배치 결정")
            promo_summary = (
                promotion_result.groupby("final_decision")
                .size()
                .reset_index(name="count")
            )
            st.bar_chart(promo_summary.set_index("final_decision")["count"])

    st.markdown("</div>", unsafe_allow_html=True)


def _build_highlight_paths(transfer_path_result, network_path_result):
    highlight_paths = []

    if transfer_path_result is not None and not transfer_path_result.empty:
        recommended_transfer_paths = transfer_path_result[
            transfer_path_result["recommended_path"] != "이동 비추천"
        ]

        for _, path_row in recommended_transfer_paths.iterrows():
            if path_row["recommended_path"] == "직접 이동 추천":
                path_names = [
                    path_row["source_store"],
                    path_row["target_store"],
                ]
            elif path_row["recommended_path"] == "DC 경유 이동 추천":
                path_names = [
                    path_row["source_store"],
                    path_row["via_dc"],
                    path_row["target_store"],
                ]
            else:
                continue

            highlight_paths.append(
                {
                    "path_names": path_names,
                    "label": f"{path_row['product_name']} - {path_row['recommended_path']}",
                }
            )

    if network_path_result is not None and not network_path_result.empty:
        if "network_recommendation" in network_path_result.columns and "network_path" in network_path_result.columns:
            network_recommended_paths = network_path_result[
                network_path_result["network_recommendation"] == "다중 경로 추천"
            ]

            for _, network_row in network_recommended_paths.iterrows():
                path_names = str(network_row["network_path"]).split(" → ")

                highlight_paths.append(
                    {
                        "path_names": path_names,
                        "label": f"{network_row.get('product_name', '-') } - 다중 경로 추천",
                    }
                )

    return highlight_paths


def _show_map_page(stores, routes, kakao_js_key, transfer_path_result, network_path_result):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🗺 지도 페이지")

    if not kakao_js_key:
        st.info("왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하면 지도가 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.subheader("점포 및 전체 경로")
    show_kakao_map(stores, routes, kakao_js_key)

    st.subheader("추천 경로 강조")
    highlight_paths = _build_highlight_paths(transfer_path_result, network_path_result)

    if highlight_paths:
        show_kakao_map_with_highlights(stores, routes, kakao_js_key, highlight_paths)
    else:
        st.info("강조 표시할 추천 경로가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)



def _show_movement_page(
    stores,
    products,
    inventory,
    routes,
    kakao_js_key,
    final_recommendations,
    transfer_path_result,
    network_path_result,
):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🗺 재고 이동 지도")

    if not kakao_js_key:
        st.info("왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하면 지도와 재고 이동 시뮬레이션이 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.subheader("추천 경로 지도")

    highlight_paths = _build_highlight_paths(transfer_path_result, network_path_result)

    if highlight_paths:
        show_kakao_map_with_highlights(stores, routes, kakao_js_key, highlight_paths)
    else:
        show_kakao_map(stores, routes, kakao_js_key)

    st.markdown("---")
    st.subheader("재고 이동 및 재고 변화")

    if show_kakao_map_with_multi_trucks is None:
        st.warning("kakao_map_viewer.py에 show_kakao_map_with_multi_trucks 함수가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        truck_speed = st.slider(
            "이동 배속",
            min_value=0.5,
            max_value=10.0,
            value=1.0,
            step=0.5,
            key="movement_page_speed",
        )

    with col2:
        max_truck_routes = st.slider(
            "표시할 추천 경로 후보 수",
            min_value=1,
            max_value=5,
            value=5,
            step=1,
            key="movement_page_max_routes",
        )

    with col3:
        default_selected_count = st.slider(
            "처음 자동 선택할 이동수단 수",
            min_value=1,
            max_value=5,
            value=3,
            step=1,
            key="movement_page_default_count",
        )

    with col4:
        selected_transport_type = st.selectbox(
            "시뮬레이션 이동수단",
            [
                "AI 추천 이동수단",
                "오토바이",
                "소형 차량",
                "소형 트럭",
                "냉동/냉장 탑차",
            ],
            key="movement_page_transport_type",
        )

    scenarios = _build_truck_scenarios(
        stores=stores,
        products=products,
        inventory=inventory,
        final_recommendations=final_recommendations,
        transfer_path_result=transfer_path_result,
        max_truck_routes=max_truck_routes,
        selected_transport_type=selected_transport_type,
    )

    if scenarios:
        transport_rows = []

        for scenario in scenarios:
            transport_rows.append(
                {
                    "상품명": scenario.get("product_name", "-"),
                    "경로": f"{scenario.get('source_store', '-')} → {scenario.get('target_store', '-')}",
                    "추천 수량": scenario.get("move_qty", 0),
                    "이동거리(km)": scenario.get("distance_km", "-"),
                    "선택 이동수단": f"{scenario.get('transport_icon', '')} {scenario.get('transport_type', '-')}",
                    "이동수단 예상비용": _format_money(scenario.get("transport_cost", 0)),
                    "추천 방식": scenario.get("recommended_path", "-"),
                }
            )

        with st.expander("추천 이동수단 및 비용 보기", expanded=False):
            _safe_dataframe(pd.DataFrame(transport_rows), width="stretch")

            option_rows = []

            for scenario in scenarios:
                for option in scenario.get("transport_cost_options", []):
                    option_rows.append(
                        {
                            "상품명": scenario.get("product_name", "-"),
                            "경로": f"{scenario.get('source_store', '-')} → {scenario.get('target_store', '-')}",
                            "이동수단": f"{option.get('아이콘', '')} {option.get('이동수단', '-')}",
                            "예상 이동비용": _format_money(option.get("예상 이동비용", 0)),
                            "적재 가능 수량": option.get("적재 가능 수량", "-"),
                            "속도 계수": option.get("속도 계수", "-"),
                            "설명": option.get("설명", "-"),
                        }
                    )

            if option_rows:
                st.markdown("#### 이동수단별 예상 비용")
                _safe_dataframe(pd.DataFrame(option_rows), width="stretch")

            if st.button("이동수단 기준 보기", width="stretch", key="go_transport_rule_from_movement"):
                _go("transport_rule")

    if not scenarios:
        st.info("지도에 표시 가능한 이동 경로가 없습니다.")
    else:
        show_kakao_map_with_multi_trucks(
            stores,
            routes,
            kakao_js_key,
            scenarios,
            speed_multiplier=truck_speed,
            default_selected_count=default_selected_count,
        )

    st.markdown("</div>", unsafe_allow_html=True)


def _show_explain_page():
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("📘 설명")

    st.markdown(
        """
        ## 화면 구성

        이 앱은 편의점 악성재고 처리 후보를 자동 계산하고, 실행 가치가 높은 후보를 대시보드에 표시합니다.

        - **AI 추천 결과**: 상품별 추천 후보, 총점, 추천 등급을 확인합니다.
        - **재고 이동 지도**: 선택한 추천 경로를 지도에서 확인합니다.
        - **강화학습 비교**: Greedy 추천과 DQN 기반 추천을 비교합니다.
        - **관리자용 메뉴**: 계산 방식, 비용 기준, 이동수단 기준, 상세 데이터를 확인합니다.

        ## 추천 후보 계산 흐름

        1. 엑셀 데이터에서 점포, 상품, 재고, 경로 정보를 불러옵니다.
        2. 악성재고 가능성이 높은 상품과 이동 후보를 선별합니다.
        3. 이동비용, 할인손실비용, 폐기비용을 계산합니다.
        4. 추천 수량, 거리, 시간, 재고 처리 효과를 함께 반영해 총점을 계산합니다.
        5. 총점 기준으로 최적, 권장, 검토 등급을 부여합니다.
        6. 지도와 표에서 실행 가능한 추천 후보를 확인합니다.

        ## 비용 산정 기준

        - **이동비용**: 추천 경로의 이동거리, 경유 여부, 선택 이동수단의 단가를 반영한 예상 운송비.
        - **할인손실비용**: 할인 판매 시 정상 판매 대비 감소하는 예상 매출 손실.
        - **폐기비용**: 처리하지 못한 재고를 폐기할 때 발생하는 예상 손실 비용.

        ## 이동수단 기준

        - **오토바이**: 소량·근거리 일반 상품 이동에 사용합니다.
        - **소형 차량**: 중간 수량의 점포 간 이동에 사용합니다.
        - **소형 트럭**: 대량 이동 또는 DC 경유 이동에 사용합니다.
        - **냉동/냉장 탑차**: 냉장, 냉동, 아이스, 샐러드 등 온도 유지가 필요한 상품에 사용합니다.

        ## DQN 비교

        DQN은 추천 후보의 상태값을 입력받고, 재고 이동, 할인, 폐기, 보류 중 하나를 선택하도록 학습하는 비교용 강화학습 모델입니다.
        현재 앱에서는 Greedy 추천 결과와 DQN 추천 결과를 비교해 의사결정 보조 자료로 사용합니다.
        """
    )

    st.markdown("</div>", unsafe_allow_html=True)


def _show_data_page(
    stores,
    products,
    inventory,
    routes,
    final_recommendations,
    promotion_result,
    transfer_path_result,
    network_path_result,
    dc_routes,
    cutline_result,
    time_result,
):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🧾 상세 데이터 페이지")

    with st.expander("최종 추천 후보", expanded=True):
        _safe_dataframe(final_recommendations, width="stretch")

    with st.expander("점포 데이터"):
        _safe_dataframe(stores, width="stretch")

    with st.expander("상품 데이터"):
        _safe_dataframe(products, width="stretch")

    with st.expander("재고 데이터"):
        _safe_dataframe(inventory, width="stretch")

    with st.expander("경로 데이터"):
        _safe_dataframe(routes, width="stretch")

    with st.expander("DC-점포 분석"):
        if dc_routes is None or dc_routes.empty:
            st.info("DC-점포 분석 데이터가 없습니다.")
        else:
            _safe_dataframe(dc_routes, width="stretch")

    with st.expander("거리 컷라인 분석"):
        if cutline_result is None or cutline_result.empty:
            st.info("거리 컷라인 분석 데이터가 없습니다.")
        else:
            _safe_dataframe(cutline_result, width="stretch")

    with st.expander("거래가능시간 분석"):
        if time_result is None or time_result.empty:
            st.info("거래가능시간 분석 데이터가 없습니다.")
        else:
            _safe_dataframe(time_result, width="stretch")

    with st.expander("프로모션 비교"):
        if promotion_result is None or promotion_result.empty:
            st.info("프로모션 비교 데이터가 없습니다.")
        else:
            _safe_dataframe(promotion_result, width="stretch")

    with st.expander("직접 이동 vs DC 경유"):
        if transfer_path_result is None or transfer_path_result.empty:
            st.info("점포 간 이동 비교 데이터가 없습니다.")
        else:
            _safe_dataframe(transfer_path_result, width="stretch")

    with st.expander("다중 경로"):
        if network_path_result is None or network_path_result.empty:
            st.info("다중 경로 데이터가 없습니다.")
        else:
            _safe_dataframe(network_path_result, width="stretch")

    st.markdown("</div>", unsafe_allow_html=True)


def _show_rl_page(stores, products, inventory, final_recommendations, transfer_path_result, promotion_result):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🤖 강화학습 비교 페이지")


    # =========================
    # 1. 기존 RL 로그 생성
    # =========================
    try:
        from rl_data_logger import build_rl_training_log

        rl_training_log = build_rl_training_log(
            stores=stores,
            products=products,
            inventory=inventory,
            final_recommendations=final_recommendations,
            transfer_path_result=transfer_path_result,
            promotion_result=promotion_result,
        )

        if rl_training_log.empty:
            st.warning("생성할 강화학습 학습 데이터가 없습니다.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("RL 학습 샘플 수", f"{len(rl_training_log)}개")
            c2.metric("평균 Reward", f"{rl_training_log['reward'].mean():.2f}")
            c3.metric("최대 Reward", f"{rl_training_log['reward'].max():.2f}")

            with st.expander("RL 학습 데이터 미리보기"):
                _safe_dataframe(rl_training_log, width="stretch")

            csv_data = rl_training_log.to_csv(index=False).encode("utf-8-sig")

            st.download_button(
                label="📥 RL 학습 데이터 CSV 다운로드",
                data=csv_data,
                file_name="rl_training_log.csv",
                mime="text/csv",
                key="download_rl_training_log_router",
            )

    except ImportError:
        st.info("rl_data_logger.py 파일이 없어 기본 RL 로그 미리보기는 생략합니다.")
    except Exception as e:
        st.warning(f"강화학습 데이터 생성 중 오류가 발생했습니다: {e}")

    # =========================
    # 2. 실제 DQN 학습
    # =========================
    st.markdown("---")
    st.subheader("🧠 DQN 실제 학습 추천")


    dqn_col1, dqn_col2, dqn_col3 = st.columns(3)

    with dqn_col1:
        dqn_episodes = st.slider(
            "DQN 학습 반복 수",
            min_value=30,
            max_value=500,
            value=120,
            step=30,
            key="dqn_episodes",
        )

    with dqn_col2:
        dqn_sample_limit = st.slider(
            "DQN 학습 후보 수",
            min_value=50,
            max_value=1000,
            value=300,
            step=50,
            key="dqn_sample_limit",
        )

    with dqn_col3:
        dqn_learning_rate = st.selectbox(
            "학습률",
            [0.003, 0.005, 0.01, 0.02],
            index=2,
            key="dqn_learning_rate",
        )

    run_dqn = st.button(
        "DQN 학습 실행",
        width="stretch",
        key="run_actual_dqn_training",
    )

    if run_dqn:
        try:
            from dqn_agent import train_dqn_policy

            with st.spinner("DQN이 후보별 State-Action-Reward를 학습하는 중입니다..."):
                dqn_compare, dqn_history, dqn_summary = train_dqn_policy(
                    final_recommendations=final_recommendations,
                    transfer_path_result=transfer_path_result,
                    inventory=inventory,
                    episodes=dqn_episodes,
                    lr=dqn_learning_rate,
                    hidden_dim=32,
                    batch_size=64,
                    sample_limit=dqn_sample_limit,
                    seed=42,
                    save_artifacts=True,
                    output_dir="dqn_artifacts",
                )

            if dqn_compare.empty:
                st.warning("DQN 학습 결과가 없습니다.")
            else:
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("DQN 학습 후보", f"{dqn_summary['training_samples']}개")
                d2.metric("학습 Transition", f"{dqn_summary['transition_count']}개")
                d3.metric("최종 Loss", f"{dqn_summary['final_loss']:.3f}")
                d4.metric("Greedy-DQN 일치율", f"{dqn_summary['match_rate']:.1f}%")

                st.markdown(
                    f"""
                    **DQN 1순위 추천**  
                    - 상품/경로: **{dqn_summary['dqn_top_product']} / {dqn_summary['dqn_top_route']}**  
                    - DQN 추천 행동: **{dqn_summary['dqn_top_action']}**  
                    - Greedy 기준 행동: **{dqn_summary['greedy_top_action']}**
                    """
                )

                if dqn_summary.get("model_saved"):
                    saved_paths = dqn_summary.get("saved_paths", {})

                    st.success(
                        "DQN 학습 결과를 저장했습니다. "
                        "다음 단계에서는 이 저장 모델을 불러와서 이어서 학습하도록 확장할 수 있습니다."
                    )

                    github_upload = dqn_summary.get("github_upload", {})

                    if github_upload.get("configured"):
                        if github_upload.get("fail_count", 0) == 0:
                            st.success(
                                f"GitHub 외부 저장 완료: {github_upload.get('ok_count', 0)}개 파일 업로드"
                            )
                        else:
                            st.warning(
                                f"GitHub 외부 저장 일부 실패: 성공 {github_upload.get('ok_count', 0)}개 / "
                                f"실패 {github_upload.get('fail_count', 0)}개"
                            )

                        with st.expander("GitHub 외부 저장 결과 보기", expanded=False):
                            for result in github_upload.get("results", []):
                                if result.get("ok"):
                                    st.write(f"✅ `{result.get('github_path')}`")
                                else:
                                    st.write(f"❌ `{result.get('github_path')}` - {result.get('message')}")
                    else:
                        st.info(
                            "GitHub 외부 저장은 아직 설정되지 않았습니다. "
                            "GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH를 Streamlit Secrets에 넣으면 자동 업로드됩니다."
                        )

                    with st.expander("저장된 DQN 파일 확인 및 다운로드", expanded=False):
                        from pathlib import Path as _Path

                        file_labels = [
                            ("모델 가중치", "model_file", "application/octet-stream"),
                            ("추천 결과 CSV", "compare_file", "text/csv"),
                            ("학습 로그 CSV", "history_file", "text/csv"),
                            ("요약 JSON", "summary_file", "application/json"),
                        ]

                        for label, key, mime in file_labels:
                            file_path = saved_paths.get(key)

                            if file_path and _Path(file_path).exists():
                                st.write(f"**{label}**: `{file_path}`")

                                with open(file_path, "rb") as f:
                                    st.download_button(
                                        label=f"{label} 다운로드",
                                        data=f.read(),
                                        file_name=_Path(file_path).name,
                                        mime=mime,
                                        key=f"download_{key}_dqn_saved",
                                    )
                            else:
                                st.caption(f"{label} 파일을 찾지 못했습니다.")

                st.markdown("### DQN 학습 Loss 변화")
                if not dqn_history.empty:
                    st.line_chart(dqn_history.set_index("episode")["loss"])
                    with st.expander("DQN 학습 로그"):
                        _safe_dataframe(dqn_history, width="stretch")

                st.markdown("### Greedy 추천 vs DQN 추천 비교")

                view_cols = [
                    "product_name",
                    "source_store",
                    "target_store",
                    "greedy_action",
                    "dqn_recommended_action",
                    "dqn_expected_q",
                    "heuristic_score",
                    "suggested_qty",
                    "estimated_cost",
                    "dqn_match_greedy",
                ]

                view = dqn_compare[[c for c in view_cols if c in dqn_compare.columns]].rename(
                    columns={
                        "product_name": "상품명",
                        "source_store": "보내는 점포",
                        "target_store": "받는 점포",
                        "greedy_action": "Greedy 기준 Action",
                        "dqn_recommended_action": "DQN 추천 Action",
                        "dqn_expected_q": "DQN 기대 Q값",
                        "heuristic_score": "휴리스틱 총점",
                        "suggested_qty": "추천 수량",
                        "estimated_cost": "예상 비용",
                        "dqn_match_greedy": "Greedy-DQN 비교",
                    }
                )

                _safe_dataframe(view, width="stretch")

                with st.expander("행동별 Q값 보기"):
                    q_cols = [
                        "product_name",
                        "source_store",
                        "target_store",
                        "Q_재고 이동",
                        "Q_할인",
                        "Q_폐기",
                        "Q_보류",
                    ]

                    q_view = dqn_compare[[c for c in q_cols if c in dqn_compare.columns]].rename(
                        columns={
                            "product_name": "상품명",
                            "source_store": "보내는 점포",
                            "target_store": "받는 점포",
                        }
                    )

                    _safe_dataframe(q_view, width="stretch")

                with st.expander("DQN 학습 방식 설명"):
                    st.markdown(
                        """
                        - **State**: 후보의 총점, 추천 수량, 예상 비용, 이동거리, 수요/재고 차이 등으로 구성됩니다.
                        - **Action**: 재고 이동, 할인, 폐기, 보류 4가지 행동입니다.
                        - **Reward**: 비용 절감 가능성, 재고 처리 효과, 수량, 거리, 휴리스틱 총점을 이용해 계산한 시뮬레이션 보상입니다.
                        - **Q값**: 특정 상태에서 특정 행동을 선택했을 때 기대되는 보상입니다.
                        - DQN은 Q값이 가장 높은 행동을 추천합니다.
                        """
                    )

        except ImportError:
            st.error("dqn_agent.py 파일을 찾지 못했습니다. 새로 받은 dqn_agent.py를 프로젝트 폴더에 넣어 주세요.")
        except Exception as e:
            st.error(f"DQN 학습 중 오류가 발생했습니다: {e}")

    else:
        st.info("DQN 학습 결과를 보려면 위의 'DQN 학습 실행' 버튼을 누르세요.")

    # =========================
    # 3. 기존 Q-table 정책 비교
    # =========================
    st.markdown("---")
    st.subheader("기존 정책 테이블 비교")

    try:
        from rl_data_logger import build_rl_training_log
        from rl_policy_helper import recommend_action_for_rl_log

        rl_training_log = build_rl_training_log(
            stores=stores,
            products=products,
            inventory=inventory,
            final_recommendations=final_recommendations,
            transfer_path_result=transfer_path_result,
            promotion_result=promotion_result,
        )

        if not rl_training_log.empty:
            rl_compare_result = recommend_action_for_rl_log(
                rl_training_log,
                policy_file="rl_policy_table.csv",
            )

            if rl_compare_result.empty:
                st.warning("강화학습 정책 비교 결과가 없습니다. rl_policy_table.csv 파일을 확인해 주세요.")
            else:
                matched_count = int(
                    (rl_compare_result["rl_match_status"] == "정책 매칭됨").sum()
                )

                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("비교 후보 수", f"{len(rl_compare_result)}개")
                rc2.metric("정책 매칭 수", f"{matched_count}개")

                if rl_compare_result["expected_reward"].notna().any():
                    avg_expected_reward = rl_compare_result["expected_reward"].dropna().mean()
                    rc3.metric("평균 기대 Reward", f"{avg_expected_reward:.2f}")
                else:
                    rc3.metric("평균 기대 Reward", "-")

                cols = [
                    "product_name",
                    "source_store",
                    "target_store",
                    "action",
                    "rl_recommended_action",
                    "reward",
                    "expected_reward",
                    "heuristic_score",
                    "greedy_rank",
                    "rl_match_status",
                ]

                view = rl_compare_result[[c for c in cols if c in rl_compare_result.columns]].rename(
                    columns={
                        "product_name": "상품명",
                        "source_store": "보내는 점포",
                        "target_store": "받는 점포",
                        "action": "현재 추천 Action",
                        "rl_recommended_action": "정책 추천 Action",
                        "reward": "현재 Reward",
                        "expected_reward": "기대 Reward",
                        "heuristic_score": "총점",
                        "greedy_rank": "Greedy 순위",
                        "rl_match_status": "매칭 상태",
                    }
                )

                _safe_dataframe(view, width="stretch")

    except FileNotFoundError:
        st.info("rl_policy_table.csv 파일이 없어서 기존 Q-table 비교는 생략합니다.")
    except ImportError:
        st.info("rl_policy_helper.py 파일이 없어서 기존 Q-table 비교는 생략합니다.")
    except Exception as e:
        st.warning(f"기존 정책 비교 중 오류가 발생했습니다: {e}")

    st.markdown("</div>", unsafe_allow_html=True)


def _build_truck_scenarios(
    stores,
    products,
    inventory,
    final_recommendations,
    transfer_path_result,
    max_truck_routes,
    selected_transport_type="AI 추천 이동수단",
):
    max_truck_routes = min(int(max_truck_routes), 5)
    store_location_map = {}

    for _, row in stores.iterrows():
        if (
            pd.notna(row.get("store_name"))
            and pd.notna(row.get("latitude"))
            and pd.notna(row.get("longitude"))
        ):
            store_location_map[row["store_name"]] = {
                "name": row["store_name"],
                "lat": float(row["latitude"]),
                "lng": float(row["longitude"]),
            }

    store_name_to_id = dict(zip(stores["store_name"], stores["store_id"]))
    product_name_to_id = dict(zip(products["product_name"], products["product_id"]))

    def get_current_stock(store_id, product_id_value):
        if store_id is None or product_id_value is None:
            return 0

        matched = inventory[
            (inventory["store_id"] == store_id)
            & (inventory["product_id"] == product_id_value)
        ]

        if matched.empty:
            return 0

        return int(matched.iloc[0]["stock_qty"])

    def get_recommendation_match(path_row):
        if final_recommendations is None or final_recommendations.empty:
            return None

        matched = final_recommendations[
            (final_recommendations["product_name"] == path_row["product_name"])
            & (final_recommendations["source_store"] == path_row["source_store"])
            & (final_recommendations["target_store"] == path_row["target_store"])
        ]

        if matched.empty:
            return None

        return matched.iloc[0]

    if transfer_path_result is None or transfer_path_result.empty:
        return []

    truck_candidates = transfer_path_result[
        transfer_path_result["recommended_path"] != "이동 비추천"
    ].copy()

    if (
        not truck_candidates.empty
        and final_recommendations is not None
        and not final_recommendations.empty
        and "greedy_rank" in final_recommendations.columns
    ):
        rank_map = {}

        for _, rec_row in final_recommendations.iterrows():
            key = (
                rec_row["product_name"],
                rec_row["source_store"],
                rec_row["target_store"],
            )
            rank_map[key] = rec_row.get("greedy_rank", 9999)

        truck_candidates["greedy_rank_for_truck"] = truck_candidates.apply(
            lambda row: rank_map.get(
                (row["product_name"], row["source_store"], row["target_store"]),
                9999,
            ),
            axis=1,
        )

        truck_candidates = truck_candidates.sort_values("greedy_rank_for_truck")

    truck_candidates = truck_candidates.head(max_truck_routes)

    scenarios = []

    for scenario_rank, (_, path_row) in enumerate(truck_candidates.iterrows(), start=1):
        product_name = path_row["product_name"]
        source_store = path_row["source_store"]
        target_store = path_row["target_store"]
        recommended_path = path_row["recommended_path"]

        try:
            move_qty = int(path_row["suggested_transfer_qty"])
        except Exception:
            move_qty = 0

        if recommended_path == "DC 경유 이동 추천":
            via_dc = path_row.get("via_dc", None)
            if via_dc and pd.notna(via_dc):
                path_names = [source_store, via_dc, target_store]
            else:
                via_dc = None
                path_names = [source_store, target_store]
        else:
            via_dc = None
            path_names = [source_store, target_store]

        truck_path = []

        for name in path_names:
            if name in store_location_map:
                truck_path.append(store_location_map[name])

        if len(truck_path) < 2:
            continue

        source_store_id = store_name_to_id.get(source_store)
        target_store_id = store_name_to_id.get(target_store)
        product_id = product_name_to_id.get(product_name)

        source_before = get_current_stock(source_store_id, product_id)
        target_before = get_current_stock(target_store_id, product_id)

        source_after = max(source_before - move_qty, 0)
        target_after = target_before + move_qty

        store_inventory = {
            source_store: {
                "role": "보내는 점포",
                "product_name": product_name,
                "before": source_before,
                "after": source_after,
                "change": -move_qty,
            },
            target_store: {
                "role": "받는 점포",
                "product_name": product_name,
                "before": target_before,
                "after": target_after,
                "change": move_qty,
            },
        }

        if via_dc:
            via_dc_id = store_name_to_id.get(via_dc)
            via_before = get_current_stock(via_dc_id, product_id)

            store_inventory[via_dc] = {
                "role": "경유 DC",
                "product_name": product_name,
                "before": via_before,
                "after": via_before,
                "change": 0,
            }

        rec_match = get_recommendation_match(path_row)

        if rec_match is not None:
            estimated_cost = rec_match.get("estimated_cost", "-")
            heuristic_score = rec_match.get("heuristic_score", "-")
            reason = rec_match.get("reason", "-")
        else:
            estimated_cost = path_row.get("direct_cost", path_row.get("via_cost", "-"))
            heuristic_score = "-"
            reason = path_row.get("recommendation_reason", "-")

        distance_km = _estimate_route_distance_km(path_row)

        transport_type = _choose_transport_type(
            product_name=product_name,
            qty=move_qty,
            recommended_path=recommended_path,
            selected_transport_type=selected_transport_type,
        )

        transport_profile = _get_transport_profile(transport_type)

        transport_cost_options = _calculate_transport_options(
            product_name=product_name,
            qty=move_qty,
            distance_km=distance_km,
        )

        selected_transport_cost = _calculate_transport_cost(
            transport_type=transport_type,
            distance_km=distance_km,
            qty=move_qty,
            product_name=product_name,
        )

        scenarios.append(
            {
                "label": f"{scenario_rank}. {product_name} / {source_store} → {target_store}",
                "product_name": product_name,
                "source_store": source_store,
                "target_store": target_store,
                "move_qty": move_qty,
                "recommended_path": recommended_path,
                "estimated_cost": str(estimated_cost),
                "heuristic_score": str(heuristic_score),
                "reason": str(reason),
                "path_names": path_names,
                "path": truck_path,
                "store_inventory": store_inventory,
                "distance_km": round(distance_km, 2),
                "transport_type": transport_type,
                "transport_icon": transport_profile.get("icon", "🚚"),
                "transport_cost": selected_transport_cost,
                "transport_speed_factor": transport_profile.get("speed_factor", 1.0),
                "transport_cost_options": transport_cost_options,
            }
        )

    return scenarios


def _show_truck_page(
    stores,
    products,
    inventory,
    routes,
    kakao_js_key,
    final_recommendations,
    transfer_path_result,
):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🚚 재고 이동 시뮬레이션 페이지")

    if not kakao_js_key:
        st.info("왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하면 재고 이동 시뮬레이션이 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if show_kakao_map_with_multi_trucks is None:
        st.warning("kakao_map_viewer.py에 show_kakao_map_with_multi_trucks 함수가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    col1, col2, col3 = st.columns(3)

    with col1:
        truck_speed = st.slider(
            "이동 배속",
            min_value=0.5,
            max_value=10.0,
            value=1.0,
            step=0.5,
            key="truck_page_speed",
        )

    with col2:
        max_truck_routes = st.slider(
            "지도에 표시할 추천 경로 후보 수",
            min_value=1,
            max_value=5,
            value=5,
            step=1,
            key="truck_page_max_routes",
        )

    with col3:
        default_selected_count = st.slider(
            "처음 자동 선택할 이동수단 수",
            min_value=1,
            max_value=5,
            value=3,
            step=1,
            key="truck_page_default_count",
        )

    scenarios = _build_truck_scenarios(
        stores=stores,
        products=products,
        inventory=inventory,
        final_recommendations=final_recommendations,
        transfer_path_result=transfer_path_result,
        max_truck_routes=max_truck_routes,
    )

    if not scenarios:
        st.info("지도에 표시 가능한 이동 경로가 없습니다.")
    else:
        candidate_labels = []
        label_to_index = {}

        for scenario_index, scenario in enumerate(scenarios):
            product_name = scenario.get("product_name", "-")
            source_store = scenario.get("source_store", "-")
            target_store = scenario.get("target_store", "-")
            move_qty = scenario.get("move_qty", "-")
            recommended_path = scenario.get("recommended_path", "-")
            heuristic_score = scenario.get("heuristic_score", "-")

            try:
                score_text = f" | {float(heuristic_score):.0f}점"
            except Exception:
                score_text = ""

            label = (
                f"AI {scenario_index + 1}위 | {product_name} | "
                f"{source_store} → {target_store} | "
                f"{move_qty}개 | {recommended_path}{score_text}"
            )

            candidate_labels.append(label)
            label_to_index[label] = scenario_index

        default_labels = candidate_labels[: min(default_selected_count, len(candidate_labels))]

        selected_labels = st.multiselect(
            "🚚 지도에 표시할 AI 추천 후보 선택",
            options=candidate_labels,
            default=default_labels,
            key="dashboard_truck_ai_candidate_selector",
        )

        selected_indexes = [
            label_to_index[label]
            for label in selected_labels
            if label in label_to_index
        ]

        selected_scenarios = [
            scenarios[i]
            for i in selected_indexes
            if 0 <= i < len(scenarios)
        ]

        if not selected_scenarios:
            st.info("지도에 표시할 후보를 1개 이상 선택해 주세요.")
        else:
            show_kakao_map_with_multi_trucks(
                stores,
                routes,
                kakao_js_key,
                selected_scenarios,
                speed_multiplier=truck_speed,
                default_selected_count=min(default_selected_count, len(selected_scenarios)),
            )

    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# 라우터
# =========================
def show_dashboard_router(
    stores,
    products,
    inventory,
    routes,
    kakao_js_key,
    final_recommendations,
    final_rec_summary,
    promotion_result,
    transfer_path_result,
    network_path_result,
    dc_routes,
    cutline_result,
    time_result,
):
    _apply_page_style()

    if "excel_dashboard_page" not in st.session_state:
        st.session_state.excel_dashboard_page = "dashboard"

    page = st.session_state.excel_dashboard_page

    if page == "dashboard":
        _show_dashboard_home(
            final_recommendations=final_recommendations,
            final_rec_summary=final_rec_summary,
            stores=stores,
            products=products,
            inventory=inventory,
            promotion_result=promotion_result,
            transfer_path_result=transfer_path_result,
        )

    elif page == "score":
        _show_score_page(final_recommendations)

    elif page == "score_formula":
        _show_score_formula_page(final_recommendations)

    elif page == "cost_compare":
        _show_cost_compare_page(
            stores,
            products,
            inventory,
            final_recommendations,
            promotion_result,
            transfer_path_result,
        )

    elif page == "transport_rule":
        _show_transport_rule_page()

    elif page == "graph":
        _show_graph_page(
            final_recommendations,
            final_rec_summary,
            promotion_result,
            transfer_path_result,
        )

    elif page == "movement":
        _show_movement_page(
            stores,
            products,
            inventory,
            routes,
            kakao_js_key,
            final_recommendations,
            transfer_path_result,
            network_path_result,
        )

    elif page == "map":
        _show_map_page(
            stores,
            routes,
            kakao_js_key,
            transfer_path_result,
            network_path_result,
        )

    elif page == "truck":
        _show_truck_page(
            stores,
            products,
            inventory,
            routes,
            kakao_js_key,
            final_recommendations,
            transfer_path_result,
        )

    elif page == "rl":
        _show_rl_page(
            stores,
            products,
            inventory,
            final_recommendations,
            transfer_path_result,
            promotion_result,
        )

    elif page == "explain":
        _show_explain_page()

    elif page == "data":
        _show_data_page(
            stores,
            products,
            inventory,
            routes,
            final_recommendations,
            promotion_result,
            transfer_path_result,
            network_path_result,
            dc_routes,
            cutline_result,
            time_result,
        )

    else:
        st.session_state.excel_dashboard_page = "dashboard"
        st.rerun()
