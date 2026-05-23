
from numbers import Number
import io
import html as html_lib
import pandas as pd
import streamlit as st

try:
    from kakao_map_viewer import show_kakao_map, show_kakao_map_with_highlights, show_store_matching_map
except ImportError:
    show_kakao_map = None
    show_kakao_map_with_highlights = None
    show_store_matching_map = None

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


def _recommend_transport(product_name, qty, recommended_path="-", distance_km=None):
    """
    5차 데이터 기준 이동수단 추천.

    5차부터 도보/전동자전거가 추가되어,
    초근거리·소량 이동은 도보/전동자전거를 우선 고려한다.
    냉장·냉동·신선식품은 냉동/냉장 탑차를 우선한다.
    """
    text = str(product_name) + " " + str(recommended_path)
    qty = _safe_numeric(qty, 0)
    distance = _safe_numeric(distance_km, None)

    if any(keyword in text for keyword in ["냉동", "아이스", "만두", "냉장", "우유", "요거트", "샐러드", "신선"]):
        return "냉동/냉장 탑차"

    if "DC" in text or "경유" in text:
        return "소형 트럭"

    if distance is not None:
        if qty <= 3 and distance <= 0.7:
            return "도보"

        if qty <= 15 and distance <= 3.0:
            return "전동자전거"

    if qty <= 20:
        return "오토바이"

    if qty <= 80:
        return "소형 차량"

    return "소형 트럭"


TRANSPORT_PROFILES = {
    "도보": {
        "icon": "🚶",
        "base_cost": 0,
        "cost_per_km": 50,
        "capacity": 3,
        "speed_factor": 0.35,
        "description": "초근거리 소량 재고 이동",
        "cold_chain": False,
    },
    "전동자전거": {
        "icon": "🚲",
        "base_cost": 700,
        "cost_per_km": 220,
        "capacity": 15,
        "speed_factor": 0.95,
        "description": "근거리 소량 재고 이동",
        "cold_chain": False,
    },
    "오토바이": {
        "icon": "🛵",
        "base_cost": 1200,
        "cost_per_km": 420,
        "capacity": 20,
        "speed_factor": 1.25,
        "description": "긴급 소량 배송",
        "cold_chain": False,
    },
    "소형 차량": {
        "icon": "🚗",
        "base_cost": 3000,
        "cost_per_km": 620,
        "capacity": 80,
        "speed_factor": 1.0,
        "description": "중거리 일반 재고 운송",
        "cold_chain": False,
    },
    "소형 트럭": {
        "icon": "🚚",
        "base_cost": 5500,
        "cost_per_km": 880,
        "capacity": 200,
        "speed_factor": 0.85,
        "description": "대량 일반 재고 운송 및 DC 경유 이동",
        "cold_chain": False,
    },
    "냉동/냉장 탑차": {
        "icon": "🧊",
        "base_cost": 7500,
        "cost_per_km": 1050,
        "capacity": 200,
        "speed_factor": 0.75,
        "description": "신선식품 및 냉장·냉동 재고 운송",
        "cold_chain": True,
    },
}


def _is_cold_product(product_name):
    text = str(product_name)
    return any(keyword in text for keyword in ["냉동", "냉장", "아이스", "만두", "우유", "요거트", "샐러드", "신선"])


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


def _choose_transport_type(product_name, qty, recommended_path="-", selected_transport_type="AI 추천 이동수단", distance_km=None):
    if selected_transport_type and selected_transport_type != "AI 추천 이동수단":
        return selected_transport_type

    return _recommend_transport(
        product_name=product_name,
        qty=qty,
        recommended_path=recommended_path,
        distance_km=distance_km,
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

def _safe_qty(row, default=0):
    """
    추천 수량 컬럼이 여러 개 있을 수 있으므로,
    0보다 큰 값을 우선 찾고 없을 때만 0을 사용한다.
    """
    qty_columns = [
        "suggested_qty",
        "suggested_transfer_qty",
        "move_qty",
        "recommended_qty",
        "transfer_qty",
        "추천 수량",
    ]

    numeric_candidates = []

    for col in qty_columns:
        try:
            if col in row.index:
                value = row.get(col)
                numeric_value = _safe_numeric(value, None)

                if numeric_value is not None:
                    numeric_candidates.append(numeric_value)
        except Exception:
            continue

    positive_candidates = [v for v in numeric_candidates if v > 0]

    if positive_candidates:
        return int(round(positive_candidates[0]))

    if numeric_candidates:
        return int(round(numeric_candidates[0]))

    return int(default)


def _filter_positive_qty_recommendations(df):
    """
    추천 수량이 0 이하인 후보는 실제 실행 추천으로 보기 어렵기 때문에
    대시보드, AI 추천 결과, 지도 후보에서 제외한다.

    단, suggested_qty가 0이어도 suggested_transfer_qty 등 다른 수량 컬럼이
    양수라면 그 양수 값을 사용한다.
    """
    if df is None or df.empty:
        return df

    filtered = df.copy()

    qty_columns = [
        "suggested_qty",
        "suggested_transfer_qty",
        "move_qty",
        "recommended_qty",
        "transfer_qty",
        "추천 수량",
    ]

    existing_qty_cols = [col for col in qty_columns if col in filtered.columns]

    if not existing_qty_cols:
        return filtered

    qty_frame = pd.DataFrame(index=filtered.index)

    for col in existing_qty_cols:
        qty_frame[col] = pd.to_numeric(filtered[col], errors="coerce")

    # 각 행마다 0보다 큰 수량을 우선 사용
    positive_frame = qty_frame.where(qty_frame > 0)
    qty_series = positive_frame.bfill(axis=1).iloc[:, 0]

    # 양수 수량이 전혀 없으면 기존 값 중 첫 번째 값을 fallback으로 사용
    fallback_series = qty_frame.bfill(axis=1).iloc[:, 0]
    qty_series = qty_series.fillna(fallback_series).fillna(0)

    filtered["_display_qty_filter"] = qty_series
    filtered = filtered[filtered["_display_qty_filter"] > 0].drop(columns=["_display_qty_filter"], errors="ignore")

    return filtered


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



def _short_label(value, max_len=18):
    text = str(value)

    if len(text) <= max_len:
        return text

    return text[:max_len - 1] + "…"


def _make_route_label(row):
    product = _short_label(row.get("product_name", row.get("상품명", "-")), 8)
    source = _short_label(row.get("source_store", row.get("보내는 점포", "-")), 6)
    target = _short_label(row.get("target_store", row.get("받는 점포", "-")), 6)

    return f"{product} | {source}→{target}"


def _format_example_table(df, max_rows=5):
    if df is None or df.empty:
        return pd.DataFrame()

    view = df.copy().head(max_rows)

    rename_map = {
        "product_name": "상품명",
        "source_store": "보내는 점포",
        "target_store": "받는 점포",
        "suggested_qty": "추천 수량",
        "suggested_transfer_qty": "추천 수량",
        "move_qty": "추천 수량",
        "estimated_cost": "예상 비용",
        "final_recommendation": "추천 전략",
        "recommended_path": "이동 방식",
        "heuristic_score": "총점",
        "heuristic_grade": "추천 등급",
        "final_decision": "결정",
    }

    view = view.rename(columns=rename_map)

    wanted_cols = [
        "상품명",
        "보내는 점포",
        "받는 점포",
        "추천 수량",
        "예상 비용",
        "추천 전략",
        "이동 방식",
        "결정",
        "총점",
        "추천 등급",
    ]

    existing_cols = [c for c in wanted_cols if c in view.columns]
    view = view[existing_cols].copy()

    if "예상 비용" in view.columns:
        view["예상 비용"] = view["예상 비용"].apply(_format_money)

    if "총점" in view.columns:
        view["총점"] = pd.to_numeric(view["총점"], errors="coerce").fillna(0).round(1)

    return view


def _pick_examples_for_graph(
    title,
    final_recommendations=None,
    transfer_path_result=None,
    promotion_result=None,
    group_col=None,
    group_value=None,
):
    """
    그래프 항목별 대표 후보 5개 추출.
    그래프 카드의 접힘창에서 보여줄 표를 만든다.
    """
    title_text = str(title)

    if "추천 유형" in title_text:
        if final_recommendations is None or final_recommendations.empty:
            return pd.DataFrame()

        df = _filter_positive_qty_recommendations(final_recommendations).copy()

        if group_col and group_value and group_col in df.columns:
            df = df[df[group_col].astype(str) == str(group_value)]

        if "heuristic_score" in df.columns:
            df["heuristic_score"] = pd.to_numeric(df["heuristic_score"], errors="coerce").fillna(0)
            df = df.sort_values("heuristic_score", ascending=False)

        return _format_example_table(df, max_rows=5)

    if "낮은 예상 비용" in title_text:
        if final_recommendations is None or final_recommendations.empty:
            return pd.DataFrame()

        df = _filter_positive_qty_recommendations(final_recommendations).copy()

        if "estimated_cost" in df.columns:
            df["estimated_cost"] = pd.to_numeric(df["estimated_cost"], errors="coerce")
            df = df.dropna(subset=["estimated_cost"]).sort_values("estimated_cost", ascending=True)

        return _format_example_table(df, max_rows=5)

    if "이동 방식" in title_text:
        if transfer_path_result is None or transfer_path_result.empty:
            return pd.DataFrame()

        df = transfer_path_result.copy()

        if group_col and group_value and group_col in df.columns:
            df = df[df[group_col].astype(str) == str(group_value)]

        if "suggested_transfer_qty" in df.columns:
            df["suggested_transfer_qty"] = pd.to_numeric(df["suggested_transfer_qty"], errors="coerce").fillna(0)
            df = df[df["suggested_transfer_qty"] > 0]

        if "estimated_cost" in df.columns:
            df["estimated_cost"] = pd.to_numeric(df["estimated_cost"], errors="coerce")

        return _format_example_table(df, max_rows=5)

    if "프로모션" in title_text or "재배치" in title_text:
        if promotion_result is None or promotion_result.empty:
            return pd.DataFrame()

        df = promotion_result.copy()

        if group_col and group_value and group_col in df.columns:
            df = df[df[group_col].astype(str) == str(group_value)]

        # promotion_result에 점수/비용이 있으면 보기 좋게 정렬
        for sort_col in ["heuristic_score", "estimated_cost", "promotion_net_cost", "transfer_cost"]:
            if sort_col in df.columns:
                df[sort_col] = pd.to_numeric(df[sort_col], errors="coerce")

        if "heuristic_score" in df.columns:
            df = df.sort_values("heuristic_score", ascending=False)
        elif "estimated_cost" in df.columns:
            df = df.sort_values("estimated_cost", ascending=True)

        return _format_example_table(df, max_rows=5)

    return pd.DataFrame()


def _render_compact_chart_card(
    df,
    label_col,
    value_col,
    title,
    top_n=5,
    value_suffix="",
    ascending=False,
    examples_df=None,
):
    """
    Streamlit 기본 요소로 만든 안전한 그래프 카드.
    카드 아래에 대표 후보 5개 접힘창을 붙인다.
    """
    if df is None or df.empty or label_col not in df.columns or value_col not in df.columns:
        return

    chart_df = df[[label_col, value_col]].copy()
    chart_df[value_col] = pd.to_numeric(chart_df[value_col], errors="coerce")
    chart_df = chart_df.dropna(subset=[value_col])

    if chart_df.empty:
        return

    chart_df = chart_df.sort_values(value_col, ascending=ascending).head(top_n)
    chart_df[label_col] = chart_df[label_col].astype(str).apply(lambda x: _short_label(x, 22))

    max_value = chart_df[value_col].max()

    if max_value <= 0:
        max_value = 1

    with st.container(border=True):
        st.markdown(f"### {title}")

        for _, row in chart_df.iterrows():
            label = row[label_col]
            value = float(row[value_col])
            ratio = max(min(value / float(max_value), 1), 0)
            progress_value = int(round(ratio * 100))

            left_col, right_col = st.columns([3, 1])

            with left_col:
                st.markdown(f"**{label}**")

            with right_col:
                st.markdown(f"**{value:,.0f}{value_suffix}**")

            st.progress(progress_value)

        if examples_df is not None and not examples_df.empty:
            with st.expander("대표 후보 5개 보기", expanded=False):
                _safe_dataframe(examples_df, width="stretch", max_rows=5)



def _best_row(final_recommendations):
    if final_recommendations is None or final_recommendations.empty:
        return None

    df = _filter_positive_qty_recommendations(final_recommendations)
    if df is None or df.empty:
        return None

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
    if st.button("← 대시보드", key=None, help="메인 대시보드로 돌아가기"):
        _go("dashboard")
    st.markdown("<div style='margin-bottom:6px;'></div>", unsafe_allow_html=True)


# ── VHS 공통 상수 (모듈 레벨) ─────────────────────────────
_ACT_COLOR = {
    "재배치 이동": "#1976d2",
    "할인 판매":   "#f57c00",
    "폐기":        "#ef5350",
    "보류":        "#43a047",
}
_ACT_ICON = {"재배치 이동": "🚚", "할인 판매": "🏷️", "폐기": "🗑️", "보류": "⏸️"}

def _vhs_color(score):
    if score is None: return "#aaa"
    if score >= 80:   return "#e57373"   # 연한 빨강
    if score >= 65:   return "#f57c00"   # 연한 주황
    if score >= 50:   return "#ffb74d"   # 연한 노랑
    return "#43a047"



def show_friendly_error(context: str, err: Exception) -> None:
    """사용자 친화적 오류 메시지 표시 (Streamlit)."""
    import streamlit as st

    _MSG_MAP = {
        "필수 시트":      "필수 시트가 없습니다. stores, products, inventory, routes 시트가 필요합니다.",
        "필수 컬럼":      "필수 컬럼이 누락되었습니다. stock_qty, avg_daily_sales 컬럼을 확인해주세요.",
        "숫자 컬럼":      "숫자 컬럼에 문자가 들어가 있습니다. 엑셀 데이터를 확인해주세요.",
        "점포 ID":        "점포 ID와 상품 ID 연결이 깨졌습니다. store_id, product_id를 확인해주세요.",
        "카카오맵":       "카카오맵 키 또는 도메인 설정을 확인해주세요.",
        "ModuleNotFound": "필요한 라이브러리가 없습니다. requirements.txt를 확인해주세요.",
    }
    msg = next((v for k,v in _MSG_MAP.items() if k in str(err) or k in context), None)
    if not msg:
        msg = f"분석 중 문제가 발생했습니다: {context}"

    st.error(f"⚠️ {msg}")
    with st.expander("🔧 상세 오류 (관리자용)", expanded=False):
        import traceback as _tb
        st.code(_tb.format_exc())

def _apply_page_style():
    # ── 구글 번역 차단 (JS + 메타태그) ──────────────────────
    st.markdown(
        """<script>
        document.documentElement.setAttribute('translate','no');
        document.documentElement.setAttribute('lang','ko');
        if(typeof MutationObserver!='undefined'){
            var obs=new MutationObserver(function(m){
                m.forEach(function(mu){
                    if(mu.addedNodes) mu.addedNodes.forEach(function(n){
                        if(n.nodeType===1) n.setAttribute('translate','no');
                    });
                });
            });
            obs.observe(document.body,{childList:true,subtree:true});
        }
        </script>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <meta name="google" content="notranslate">
        <meta http-equiv="Content-Language" content="ko">
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
            /* ── 다크모드 강제 차단 ───────────────────────── */
            :root {
                color-scheme: light only !important;
            }
            html, body,
            [data-testid="stApp"],
            [data-testid="stAppViewContainer"],
            [data-testid="stMain"],
            [data-testid="stSidebar"],
            section[data-testid="stMain"] > div,
            .main .block-container {
                background-color: #ffffff !important;
                color:            #2b2d36 !important;
            }
            /* Streamlit 기본 텍스트 강제 */
            p, span, div, label, li, td, th, h1, h2, h3, h4 {
                color: inherit;
            }
            /* 다크모드 미디어쿼리 차단 */
            @media (prefers-color-scheme: dark) {
                :root { color-scheme: light only !important; }
                html, body,
                [data-testid="stApp"],
                [data-testid="stAppViewContainer"],
                .main { background-color: #ffffff !important; color: #2b2d36 !important; }
            }

            /* ── 구글 번역 UI 숨기기 ────────────────────── */
            .goog-te-banner-frame,
            .goog-te-balloon-frame,
            #goog-gt-tt,
            .goog-tooltip,
            .goog-tooltip-container {
                display: none !important;
            }
            body { top: 0 !important; }
            .skiptranslate { display: none !important; }

            /* 액션 필터 태그 잘림 방지 */
            [data-baseweb="tag"] {
                max-width: none !important;
                white-space: nowrap !important;
                overflow: visible !important;
                padding-left: 10px !important;
                margin-left: 4px !important;
            }
            /* 태그 텍스트 span에 추가 여백 */
            [data-baseweb="tag"] > span:first-of-type {
                padding-left: 6px !important;
                overflow: visible !important;
            }
            /* 멀티셀렉트 전체 컨테이너 왼쪽 여백 */
            .stMultiSelect [data-baseweb="select"] > div:first-child {
                padding-left: 8px !important;
            }
            [data-baseweb="tag"] span:first-child {
                overflow: visible !important;
                text-overflow: initial !important;
                white-space: nowrap !important;
                max-width: none !important;
                padding-left: 4px !important;
            }
            [data-baseweb="tag"] span[title] {
                overflow: visible !important;
                text-overflow: initial !important;
                white-space: nowrap !important;
                max-width: none !important;
                padding-left: 4px !important;
            }
            .stMultiSelect [data-baseweb="select"] > div {
                flex-wrap: wrap !important;
            }
            [data-baseweb="multi-value"] {
                max-width: none !important;
                padding: 0 4px !important;
            }
            /* st.metric 숫자 크기 축소 → 잘림 방지 */
            [data-testid="stMetricValue"] {
                font-size: 1.4rem !important;
                white-space: nowrap !important;
            }

            /* ── 기존 대시보드 스타일 ────────────────────── */
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
    suggested_qty = _safe_qty(best, 0)
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
        <div class="dash-hero" translate="no">
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

    metric_qty       = _escape_text(f"{suggested_qty}개")
    metric_cost      = _escape_text(_format_money(estimated_cost))
    metric_transport = _escape_text(dashboard_transport_type)

    # ── VHS / 점수 파싱 ────────────────────────────────────
    import math
    def _sf(v):
        try:
            f = float(v); return None if math.isnan(f) else f
        except (TypeError, ValueError):
            return None

    # vhs2 우선, 없으면 vhs fallback
    vhs_val    = _sf(best.get("vhs2"))   if best is not None and _sf(best.get("vhs2")) is not None \
                 else (_sf(best.get("vhs")) if best is not None else None)
    varo_val   = _sf(best.get("varo_score")) if best is not None else None
    vhs_action = str(best.get("vhs2_action") or best.get("vhs_action", "-")) \
                 if best is not None else "-"
    vhs_grade  = str(best.get("vhs2_grade")  or best.get("vhs_grade", "-")) \
                 if best is not None else "-"
    vhs_confidence = str(best.get("vhs2_confidence_label", "")) \
                     if best is not None else ""
    act_col    = _ACT_COLOR.get(vhs_action, "#555")
    act_icon   = _ACT_ICON.get(vhs_action, "")

    # ── 점수 카드 (VHS > Varo > 휴리스틱 순서로 우선) ──────
    if vhs_val is not None:
        gc = _vhs_color(vhs_val)
        score_card = (
            f'<div class="compact-metric-card" style="border:2px solid {gc};'
            f'background:linear-gradient(160deg,#fff,#f8f9ff);">'
            f'<div class="compact-metric-label" style="color:{gc};font-weight:800;">'
            f'VHS · {vhs_grade}</div>'
            f'<div class="compact-metric-value" style="color:{gc};">{vhs_val:.0f}점</div>'
            f'<div style="background:#eee;border-radius:3px;height:4px;margin:4px 0;">'
            f'<div style="width:{vhs_val:.0f}%;height:100%;background:{gc};border-radius:3px;">'
            f'</div></div>'
            f'<div style="font-size:11px;color:{act_col};font-weight:700;">'
            f'{act_icon} {vhs_action}</div>'
            f'<div style="font-size:10px;color:#888;margin-top:2px;">{vhs_confidence}</div>'
            f'</div>'
        )
    elif varo_val is not None:
        vg = str(best.get("varo_grade", "-")) if best is not None else "-"
        score_card = (
            f'<div class="compact-metric-card" style="border:2px solid #ffd43b;">'
            f'<div class="compact-metric-label">Varo 점수</div>'
            f'<div class="compact-metric-value">{varo_val:.1f}점</div>'
            f'<div style="font-size:11px;color:#888;margin-top:2px;">{vg}</div>'
            f'</div>'
        )
    else:
        hs = _escape_text(f"{heuristic_score}점")
        dg = _escape_text(display_grade)
        score_card = (
            f'<div class="compact-metric-card">'
            f'<div class="compact-metric-label">총점 · 등급</div>'
            f'<div class="compact-metric-value">{hs}</div>'
            f'<div style="font-size:11px;color:#888;margin-top:2px;">{dg}</div>'
            f'</div>'
        )

    st.markdown(
        f"""
        <div class="compact-metric-grid">
            {score_card}
            <div class="compact-metric-card">
                <div class="compact-metric-label">추천 수량</div>
                <div class="compact-metric-value">{metric_qty}</div>
            </div>
            <div class="compact-metric-card">
                <div class="compact-metric-label">예상 비용</div>
                <div class="compact-metric-value small">{metric_cost}</div>
            </div>
            <div class="compact-metric-card">
                <div class="compact-metric-label">이동수단</div>
                <div class="compact-metric-value small">{metric_transport}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 상황 감지 + 액션 분포 (활성 상황이 있을 때만 표시) ──
    if final_recommendations is not None and not final_recommendations.empty:
        fr = final_recommendations
        _SIT = {
            "sit_EXPIRY_URGENT": "⏰ 유통기한 임박",
            "sit_FROZEN_EXCESS": "❄️ 냉동·냉장 과잉",
            "sit_DEAD_STOCK":    "💀 악성재고",
            "sit_REORDER_CRISIS":"🚨 재주문 위기",
            "sit_DEMAND_SURGE":  "📈 수요 급증",
            "sit_HIGH_COST":     "💸 이동비용 높음",
        }
        sit_html = "".join(
            f'<span style="border:1px solid #ffd54f;background:#fff8e1;color:#c77000;'
            f'padding:2px 9px;border-radius:12px;font-size:11px;font-weight:700;'
            f'margin:2px;display:inline-block;">{lab} {int(fr[col].sum())}건</span>'
            for col, lab in _SIT.items()
            if col in fr.columns and int(fr[col].sum()) > 0
        )
        act_html = ""
        if "vhs_action" in fr.columns:
            act_html = "".join(
                f'<span style="background:{_ACT_COLOR.get(a,"#888")};color:#fff;'
                f'padding:2px 9px;border-radius:12px;font-size:11px;font-weight:700;'
                f'margin:2px;display:inline-block;">{_ACT_ICON.get(a,"")} {a} {c}건</span>'
                for a, c in fr["vhs_action"].value_counts().items()
            )
        if act_html or sit_html:
            st.markdown(
                f'<div style="padding:8px 12px;background:#f8f9ff;border-radius:10px;'
                f'border:1px solid #e8eaf0;margin-bottom:8px;">'
                f'{act_html}'
                f'{"<div style=margin-top:4px;>" + sit_html + "</div>" if sit_html else ""}'
                f'</div>',
                unsafe_allow_html=True,
            )

    dashboard_ratios = _estimate_ratio_summary(
        move_cost=estimated_cost,
        discount_loss_cost=0,
        disposal_cost=max(_safe_numeric(estimated_cost, 0) * 1.4, 1),
        score=heuristic_score,
        qty=suggested_qty,
    )

    with st.expander("📋 추천 근거 & 지표", expanded=False):
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("수익 회수", f"{dashboard_ratios['수익 회수 가능성']}%")
        rc2.metric("폐기위험 감소", f"{dashboard_ratios['폐기 위험 감소 효과']}%")
        rc3.metric("비용 부담률", f"{dashboard_ratios['비용 부담률']}%")
        rc4.metric("이동 비용", _format_money(dashboard_transport_cost))
        if dashboard_reason and str(dashboard_reason) not in ("-", ""):
            st.caption(str(dashboard_reason)[:200])

    with st.expander("📈 다른 추천 후보", expanded=False):
        top_candidates = _filter_positive_qty_recommendations(final_recommendations).copy()

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
                c_qty = _safe_qty(candidate, 0)
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

                # VHS 점수가 있으면 우선 사용
                c_vhs = candidate.get("vhs", None)
                try:
                    c_vhs_val = float(c_vhs) if c_vhs is not None else None
                except (TypeError, ValueError):
                    c_vhs_val = None
                c_vhs_action = str(candidate.get("vhs_action", "")) if c_vhs_val else ""

                # 카드 색상 — 순위별 뚜렷한 색
                _CARD_BG = ["#64b5f6","#81c784","#ce93d8","#e57373","#ffb74d"]
                card_bg = _CARD_BG[candidate_position % len(_CARD_BG)]

                score_disp = f"{c_vhs_val:.0f}" if c_vhs_val else str(c_score)
                grade_disp = c_vhs_action if c_vhs_action else c_grade

                st.markdown(
                    f"""
                    <div style="background:{card_bg};border-radius:12px;
                                padding:13px 16px;margin:6px 0;">
                      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                        <div style="flex:1;">
                          <div style="color:#fff;font-size:15px;font-weight:900;line-height:1.3;">
                            #{rank_text} {c_product}
                          </div>
                          <div style="color:rgba(255,255,255,0.80);font-size:12px;margin-top:3px;">
                            {c_source} → {c_target}
                          </div>
                        </div>
                        <div style="text-align:right;min-width:64px;">
                          <div style="color:#fff;font-size:22px;font-weight:900;line-height:1;">
                            {score_disp}점
                          </div>
                          <div style="color:rgba(255,255,255,0.75);font-size:11px;margin-top:2px;">
                            {grade_disp}
                          </div>
                        </div>
                      </div>
                      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">
                        <span style="background:rgba(255,255,255,0.20);color:#fff;
                                     padding:2px 9px;border-radius:8px;font-size:11px;font-weight:600;">
                          {c_qty}개
                        </span>
                        <span style="background:rgba(255,255,255,0.20);color:#fff;
                                     padding:2px 9px;border-radius:8px;font-size:11px;font-weight:600;">
                          {c_cost}
                        </span>
                        <span style="background:rgba(255,255,255,0.20);color:#fff;
                                     padding:2px 9px;border-radius:8px;font-size:11px;font-weight:600;">
                          {c_strategy}
                        </span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(
                    "✓ 이 후보로 변경",
                    key=f"candidate_row_select_{candidate_position}_{original_index}",
                ):
                    st.session_state["dashboard_selected_candidate_index"] = original_index
                    st.rerun()

                # 추천 근거 expander
                try:
                    from vhs_reason import render_reason_expander
                    render_reason_expander(candidate, idx=candidate_position)
                except Exception:
                    pass

    # ── 네비게이션 ───────────────────────────────────────
    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    n1, n2 = st.columns(2)
    with n1:
        if st.button("🧠 AI 추천 결과",   width="stretch", key="go_score"):      _go("score")
    with n2:
        if st.button("🗺 재고 이동 지도", width="stretch", key="go_movement"):   _go("movement")

    st.markdown("<div style='margin-top:5px;'></div>", unsafe_allow_html=True)

    n3, n4 = st.columns(2)
    with n3:
        if st.button("📊 VARO 상세 분석", width="stretch", key="go_algorithms"): _go("algorithms")
    with n4:
        if st.button("🌐 최소비용 경로",  width="stretch", key="go_network"):    _go("network")

    st.markdown("<div style='margin-top:5px;'></div>", unsafe_allow_html=True)
    n5, n6 = st.columns(2)
    with n5:
        if st.button("📦 처리 배치 최적화", width="stretch", key="go_batch"):     _go("batch")
    with n6:
        if st.button("📊 Before/After 효과", width="stretch", key="go_effect"):   _go("effect")

    st.markdown("<div style='margin-top:5px;'></div>", unsafe_allow_html=True)
    if st.button("📚 Varo 가이드 & 설명", width="stretch", key="go_guide"):      _go("guide")

    st.markdown("<div style='margin-top:5px;'></div>", unsafe_allow_html=True)
    ng1, ng2 = st.columns(2)
    with ng1:
        if st.button("🎮 데모 모드",   width="stretch", key="go_demo"):      _go("demo")
    with ng2:
        if st.button("🔍 데이터 검증", width="stretch", key="go_validator"): _go("validator")

    # ── 데이터 주의사항 (관리자 메뉴 바로 위) ──────────────
    _vw = st.session_state.get("_validation_warning")
    if _vw is not None:
        with st.expander("⚠️ 데이터 주의사항 (클릭해서 확인)", expanded=False):
            try:
                from sample_validator import render_validation_result
                render_validation_result(_vw)
            except Exception:
                pass

    with st.expander("⚙️ 관리자 메뉴", expanded=False):
        a1, a2 = st.columns(2)
        with a1:
            if st.button("🤖 이력 보정 비교", width="stretch", key="go_rl_a"):    _go("rl")
        with a2:
            if st.button("🔮 What-if 시뮬",  width="stretch", key="go_whatif_a"):_go("whatif")
        a3, a4 = st.columns(2)
        with a3:
            if st.button("📈 그래프 보기",   width="stretch", key="go_graph_a"): _go("graph")
        with a4:
            if st.button("🧾 상세 데이터",   width="stretch", key="go_data_a"):  _go("data")





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

    view_cols = [
        "category",
        "product_category",
        "category_name",
        "product_name",
        "source_store",
        "target_store",
        "suggested_qty",
        "suggested_transfer_qty",
        "move_qty",
        "recommended_qty",
        "transfer_qty",
        "estimated_cost",
        "recommended_distance_km",
        "distance_km",
        "direct_distance_km",
        "network_distance_km",
        "final_recommendation",
        "heuristic_score",
        "heuristic_grade",
        "greedy_reason",
    ]
    rename_map = {
        "category": "카테고리",
        "product_category": "카테고리",
        "category_name": "카테고리",
        "product_name": "상품명",
        "source_store": "보내는 점포",
        "target_store": "받는 점포",
        "suggested_qty": "추천 수량",
        "suggested_transfer_qty": "추천 수량",
        "move_qty": "추천 수량",
        "recommended_qty": "추천 수량",
        "transfer_qty": "추천 수량",
        "estimated_cost": "예상 비용",
        "recommended_distance_km": "이동거리",
        "distance_km": "이동거리",
        "direct_distance_km": "이동거리",
        "network_distance_km": "이동거리",
        "final_recommendation": "추천 전략",
        "heuristic_score": "총점",
        "heuristic_grade": "추천 등급",
        "greedy_reason": "그리디 선택 근거",
    }

    score_view = final_recommendations[[c for c in view_cols if c in final_recommendations.columns]].rename(columns=rename_map)

    if "카테고리" not in score_view.columns:
        score_view["카테고리"] = "전체"
    else:
        if isinstance(score_view["카테고리"], pd.DataFrame):
            score_view["카테고리"] = score_view["카테고리"].iloc[:, 0]
        score_view["카테고리"] = score_view["카테고리"].fillna("전체").astype(str)

    if "총점" in score_view.columns:
        score_view["총점"] = pd.to_numeric(score_view["총점"], errors="coerce").fillna(0).round(1)

    if "추천 등급" in score_view.columns:
        score_view["추천 등급"] = score_view.apply(lambda row: _grade_from_score(row.get("총점", 0), row.get("추천 등급", "-")), axis=1)
    elif "총점" in score_view.columns:
        score_view["추천 등급"] = score_view["총점"].apply(lambda score: _grade_from_score(score, "-"))

    if "추천 수량" in score_view.columns:
        if isinstance(score_view["추천 수량"], pd.DataFrame):
            score_view["추천 수량"] = score_view["추천 수량"].bfill(axis=1).iloc[:, 0]
        score_view["추천 수량"] = pd.to_numeric(score_view["추천 수량"], errors="coerce").fillna(0).round(0).astype(int)

    if "예상 비용" in score_view.columns:
        score_view["예상 비용"] = pd.to_numeric(score_view["예상 비용"], errors="coerce").fillna(0)

    # 이동거리 컬럼 후보가 여러 개 들어온 경우 첫 번째 유효 컬럼만 사용
    if "이동거리" in score_view.columns:
        if isinstance(score_view["이동거리"], pd.DataFrame):
            score_view["이동거리"] = score_view["이동거리"].bfill(axis=1).iloc[:, 0]
        score_view["이동거리"] = pd.to_numeric(score_view["이동거리"], errors="coerce")

    if "총점" in score_view.columns:
        score_view = score_view.sort_values("총점", ascending=False, na_position="last")

    return score_view.reset_index(drop=True)


def _pick_ai_summary_top5(score_view):
    """
    AI 추천 결과 요약용 5개 후보 선별.

    1순위: 최적 후보 우선
    2순위: 최적이 5개 미만이면 권장 후보로 보충
    3순위: 권장 후보는 최적 후보의 보내는 점포와 같은 후보를 우선하고,
          이동거리/예상비용/총점 기준으로 정렬
    4순위: 그래도 부족하면 검토 후보로 보충
    """
    if score_view is None or score_view.empty:
        return pd.DataFrame()

    df = score_view.copy()

    if "추천 등급" not in df.columns:
        return df.head(5).copy()

    if "총점" in df.columns:
        df["_score_sort"] = pd.to_numeric(df["총점"], errors="coerce").fillna(0)
    else:
        df["_score_sort"] = 0

    if "예상 비용" in df.columns:
        df["_cost_sort"] = pd.to_numeric(df["예상 비용"], errors="coerce").fillna(0)
    else:
        df["_cost_sort"] = 0

    if "이동거리" in df.columns:
        df["_distance_sort"] = pd.to_numeric(df["이동거리"], errors="coerce").fillna(999999)
    else:
        df["_distance_sort"] = 999999

    df["_grade_text"] = df["추천 등급"].astype(str)

    optimal = df[df["_grade_text"] == "최적"].copy()
    recommended = df[df["_grade_text"] == "권장"].copy()
    review = df[df["_grade_text"] == "검토"].copy()

    optimal = optimal.sort_values(["_score_sort", "_cost_sort"], ascending=[False, True])
    selected = optimal.head(5).copy()

    if len(selected) < 5:
        needed = 5 - len(selected)

        source_candidates = set()
        if not selected.empty and "보내는 점포" in selected.columns:
            source_candidates = set(selected["보내는 점포"].dropna().astype(str).tolist())

        if not recommended.empty:
            if source_candidates and "보내는 점포" in recommended.columns:
                recommended["_near_source_priority"] = recommended["보내는 점포"].astype(str).apply(
                    lambda x: 0 if x in source_candidates else 1
                )
            else:
                recommended["_near_source_priority"] = 1

            recommended = recommended.sort_values(
                ["_near_source_priority", "_distance_sort", "_score_sort", "_cost_sort"],
                ascending=[True, True, False, True],
            )

            selected = pd.concat([selected, recommended.head(needed)], ignore_index=True)

    if len(selected) < 5 and not review.empty:
        needed = 5 - len(selected)
        review = review.sort_values(["_distance_sort", "_score_sort", "_cost_sort"], ascending=[True, False, True])
        selected = pd.concat([selected, review.head(needed)], ignore_index=True)

    selected = selected.drop(
        columns=["_score_sort", "_cost_sort", "_distance_sort", "_grade_text", "_near_source_priority"],
        errors="ignore",
    )

    return selected.head(5).reset_index(drop=True)


def _render_grade_category_top3(score_view):
    if score_view is None or score_view.empty:
        return

    if "추천 등급" not in score_view.columns:
        return

    st.subheader("등급별 카테고리 추천")

    selected_grade = st.radio(
        "추천 등급",
        ["최적", "권장", "검토"],
        horizontal=True,
        key="score_page_grade_category_buttons",
    )

    grade_df = score_view[score_view["추천 등급"].astype(str) == selected_grade].copy()

    if grade_df.empty:
        st.info(f"{selected_grade} 등급 추천 후보가 없습니다.")
        return

    if "카테고리" not in grade_df.columns:
        grade_df["카테고리"] = "전체"

    if "총점" in grade_df.columns:
        grade_df["_score_sort"] = pd.to_numeric(grade_df["총점"], errors="coerce").fillna(0)
        grade_df = grade_df.sort_values(["카테고리", "_score_sort"], ascending=[True, False])
    else:
        grade_df["_score_sort"] = 0

    picked = (
        grade_df.groupby("카테고리", group_keys=False)
        .head(3)
        .drop(columns=["_score_sort"], errors="ignore")
        .reset_index(drop=True)
    )

    display_cols = ["상품명", "보내는 점포", "받는 점포", "추천 수량", "예상 비용", "추천 전략", "총점", "추천 등급"]

    for category_name, category_df in picked.groupby("카테고리", sort=True):
        st.markdown(f"### {category_name}")
        category_view = category_df[[c for c in display_cols if c in category_df.columns]].copy()

        if "예상 비용" in category_view.columns:
            category_view["예상 비용"] = category_view["예상 비용"].apply(_format_money)

        _safe_dataframe(category_view, width="stretch", max_rows=3)


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

    score_source = _filter_positive_qty_recommendations(final_recommendations)
    score_view = _build_score_view(score_source)
    product_query, product_selected = _render_product_filter(score_view, key_prefix="score_page_product")
    filtered_view = _make_product_filtered_df(score_view, product_query, product_selected)

    if filtered_view.empty:
        st.info("선택한 상품명에 해당하는 추천 결과가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    summary_view = _pick_ai_summary_top5(filtered_view)

    main_cols = ["상품명", "보내는 점포", "받는 점포", "추천 수량", "예상 비용", "추천 전략", "총점", "추천 등급"]
    display_table = summary_view[[c for c in main_cols if c in summary_view.columns]].copy()

    if "예상 비용" in display_table.columns:
        display_table["예상 비용"] = display_table["예상 비용"].apply(_format_money)

    st.subheader("AI 추천 결과 요약")
    _safe_dataframe(display_table, width="stretch", max_rows=5)
    _download_filtered_excel_button(display_table, file_name="상품별_AI_추천_결과.xlsx", key="download_score_filtered_excel")

    _render_score_bar_chart(summary_view, max_rows=5)
    _render_grade_category_top3(filtered_view)

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
            distance_km=distance_km,
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
                "도보 비용": transport_cost_map.get("도보", 0),
                "전동자전거 비용": transport_cost_map.get("전동자전거", 0),
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
    if name == "도보":
        return "초근거리·극소량 이동"
    if name == "전동자전거":
        return "근거리·소량 이동"
    if name == "오토바이":
        return "긴급 소량 배송"
    if name == "소형 차량":
        return "중거리 일반 재고 운송"
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

    final_recommendations_for_cost = _filter_positive_qty_recommendations(final_recommendations)

    compare_table = _build_cost_comparison_table(
        stores=stores,
        products=products,
        inventory=inventory,
        final_recommendations=final_recommendations_for_cost,
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
            - **추천 이동수단**: 상품 특성, 추천 수량, 경유 여부를 기준으로 도보, 전동자전거, 오토바이, 소형 차량, 소형 트럭, 냉동/냉장 탑차 중 하나를 제안합니다.
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
    suggested_qty = _safe_qty(best, 0)
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
    st.header("📊 그래프 요약")

    chart_items = []

    if final_rec_summary is not None and not final_rec_summary.empty:
        if "final_recommendation" in final_rec_summary.columns and "count" in final_rec_summary.columns:
            summary_df = final_rec_summary.copy()
            summary_df["final_recommendation"] = summary_df["final_recommendation"].astype(str)
            summary_df["count"] = pd.to_numeric(summary_df["count"], errors="coerce").fillna(0)

            # 가장 건수가 많은 추천 유형의 대표 후보 5개
            top_type = None
            if not summary_df.empty:
                top_type = summary_df.sort_values("count", ascending=False).iloc[0]["final_recommendation"]

            examples_df = _pick_examples_for_graph(
                title="추천 유형별 건수",
                final_recommendations=final_recommendations,
                group_col="final_recommendation",
                group_value=top_type,
            )

            chart_items.append(
                {
                    "df": summary_df,
                    "label_col": "final_recommendation",
                    "value_col": "count",
                    "title": "추천 유형별 건수",
                    "top_n": 5,
                    "suffix": "건",
                    "ascending": False,
                    "examples_df": examples_df,
                }
            )

    if final_recommendations is not None and not final_recommendations.empty:
        if "estimated_cost" in final_recommendations.columns:
            cost_df = _filter_positive_qty_recommendations(final_recommendations).copy()

            if not cost_df.empty:
                cost_df["estimated_cost"] = pd.to_numeric(cost_df["estimated_cost"], errors="coerce")
                cost_df["label"] = cost_df.apply(_make_route_label, axis=1)
                cost_df = cost_df.dropna(subset=["estimated_cost"])

                examples_df = _pick_examples_for_graph(
                    title="낮은 예상 비용 Top 5",
                    final_recommendations=final_recommendations,
                )

                chart_items.append(
                    {
                        "df": cost_df,
                        "label_col": "label",
                        "value_col": "estimated_cost",
                        "title": "낮은 예상 비용 Top 5",
                        "top_n": 5,
                        "suffix": "원",
                        "ascending": True,
                        "examples_df": examples_df,
                    }
                )

    if transfer_path_result is not None and not transfer_path_result.empty:
        if "recommended_path" in transfer_path_result.columns:
            path_summary = (
                transfer_path_result.groupby("recommended_path")
                .size()
                .reset_index(name="count")
            )
            path_summary["recommended_path"] = path_summary["recommended_path"].astype(str)

            top_path = None
            if not path_summary.empty:
                top_path = path_summary.sort_values("count", ascending=False).iloc[0]["recommended_path"]

            examples_df = _pick_examples_for_graph(
                title="이동 방식별 후보 수",
                transfer_path_result=transfer_path_result,
                group_col="recommended_path",
                group_value=top_path,
            )

            chart_items.append(
                {
                    "df": path_summary,
                    "label_col": "recommended_path",
                    "value_col": "count",
                    "title": "이동 방식별 후보 수",
                    "top_n": 5,
                    "suffix": "건",
                    "ascending": False,
                    "examples_df": examples_df,
                }
            )

    if promotion_result is not None and not promotion_result.empty:
        if "final_decision" in promotion_result.columns:
            promo_summary = (
                promotion_result.groupby("final_decision")
                .size()
                .reset_index(name="count")
            )
            promo_summary["final_decision"] = promo_summary["final_decision"].astype(str)

            top_decision = None
            if not promo_summary.empty:
                top_decision = promo_summary.sort_values("count", ascending=False).iloc[0]["final_decision"]

            examples_df = _pick_examples_for_graph(
                title="프로모션/재배치 결정",
                promotion_result=promotion_result,
                group_col="final_decision",
                group_value=top_decision,
            )

            chart_items.append(
                {
                    "df": promo_summary,
                    "label_col": "final_decision",
                    "value_col": "count",
                    "title": "프로모션/재배치 결정",
                    "top_n": 5,
                    "suffix": "건",
                    "ascending": False,
                    "examples_df": examples_df,
                }
            )

    if not chart_items:
        st.info("표시할 그래프 데이터가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for i in range(0, len(chart_items), 2):
        col1, col2 = st.columns(2)

        for col, item in zip([col1, col2], chart_items[i:i + 2]):
            with col:
                _render_compact_chart_card(
                    df=item["df"],
                    label_col=item["label_col"],
                    value_col=item["value_col"],
                    title=item["title"],
                    top_n=item["top_n"],
                    value_suffix=item["suffix"],
                    ascending=item["ascending"],
                    examples_df=item["examples_df"],
                )

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


def _show_map_page(stores, routes, kakao_js_key, transfer_path_result, network_path_result, final_recommendations=None):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("📍 내 주변 점포 재고 매칭 지도")

    if not kakao_js_key:
        st.info("왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하면 지도가 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if stores is None or stores.empty or "store_name" not in stores.columns:
        st.info("표시할 점포 데이터가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    show_store_matching_map(
        stores=stores,
        routes=routes,
        final_recommendations=final_recommendations,
        kakao_js_key=kakao_js_key,
        selected_store_name=None,
    )

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

    # =========================
    # 내 주변 점포 매칭 지도
    # =========================
    st.subheader("📍 내 주변 점포 재고 매칭 지도")

    show_store_matching_map(
        stores=stores,
        routes=routes,
        final_recommendations=final_recommendations,
        kakao_js_key=kakao_js_key,
        selected_store_name=None,
    )

    st.markdown("---")

    # =========================
    # 재고 이동 시뮬레이션
    # =========================
    st.subheader("재고 이동 및 재고 변화")

    if show_kakao_map_with_multi_trucks is None:
        st.warning("kakao_map_viewer.py에 show_kakao_map_with_multi_trucks 함수가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    control_col1, control_col2 = st.columns([2, 1])

    with control_col1:
        selected_transport_type = st.selectbox(
            "시뮬레이션 이동수단",
            [
                "AI 추천 이동수단",
                "도보",
                "전동자전거",
                "오토바이",
                "소형 차량",
                "소형 트럭",
                "냉동/냉장 탑차",
            ],
            key="movement_page_transport_type",
        )

    with control_col2:
        truck_speed = st.slider(
            "이동 배속",
            min_value=0.5,
            max_value=10.0,
            value=1.0,
            step=0.5,
            key="movement_page_speed",
        )

    all_scenarios = _build_truck_scenarios(
        stores=stores,
        products=products,
        inventory=inventory,
        final_recommendations=final_recommendations,
        transfer_path_result=transfer_path_result,
        max_truck_routes=200,
        selected_transport_type=selected_transport_type,
    )

    if not all_scenarios:
        st.info("지도에 표시 가능한 이동 경로가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    def _scenario_score_value(scenario):
        try:
            return float(scenario.get("heuristic_score", 0))
        except Exception:
            return 0.0

    all_scenarios = sorted(all_scenarios, key=_scenario_score_value, reverse=True)

    selection_mode = st.radio(
        "지도에 표시할 AI 추천 기준",
        ["AI 추천 후보", "보내는 점포 기준", "상품 기준"],
        horizontal=True,
        key="movement_candidate_selection_mode",
    )

    def _scenario_label(scenario, index):
        product_name = scenario.get("product_name", "-")
        source_store = scenario.get("source_store", "-")
        target_store = scenario.get("target_store", "-")
        move_qty = scenario.get("move_qty", "-")
        recommended_path = scenario.get("recommended_path", "-")
        transport_icon = scenario.get("transport_icon", "")
        transport_type = scenario.get("transport_type", "-")
        heuristic_score = scenario.get("heuristic_score", "-")

        try:
            score_text = f"{float(heuristic_score):.0f}점"
        except Exception:
            score_text = "-"

        return (
            f"{index}. {product_name} / {source_store} → {target_store} · "
            f"{move_qty}개 · {score_text} · {recommended_path} · {transport_icon} {transport_type}"
        )

    if selection_mode == "AI 추천 후보":
        candidate_scenarios = all_scenarios[:5]
        selector_label = "AI 추천 후보 자동 선택"

    elif selection_mode == "보내는 점포 기준":
        source_store_options = sorted(
            {str(s.get("source_store", "-")) for s in all_scenarios if str(s.get("source_store", "-")) not in ["", "-"]}
        )

        selected_source_store = st.selectbox(
            "보내는 점포 선택",
            source_store_options,
            key="movement_source_store_selector",
        )

        candidate_scenarios = [
            s for s in all_scenarios
            if str(s.get("source_store", "-")) == str(selected_source_store)
        ][:5]

        selector_label = f"{selected_source_store}에서 보낼 AI 추천 후보"

    else:
        product_options = sorted(
            {str(s.get("product_name", "-")) for s in all_scenarios if str(s.get("product_name", "-")) not in ["", "-"]}
        )

        selected_product_name = st.selectbox(
            "상품 선택",
            product_options,
            key="movement_product_selector",
        )

        candidate_scenarios = [
            s for s in all_scenarios
            if str(s.get("product_name", "-")) == str(selected_product_name)
        ][:5]

        selector_label = f"{selected_product_name} AI 추천 이동 후보"

    if not candidate_scenarios:
        st.info("선택한 조건에 해당하는 이동 후보가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # 사용자가 후보를 하나씩 체크하지 않아도 되도록,
    # 현재 조건에서 AI 점수순 상위 후보를 자동으로 최대 5개 선택한다.
    selected_scenarios = candidate_scenarios[:5]

    with st.expander(f"{selector_label} 결과 ({len(selected_scenarios)}개)", expanded=False):
        preview_rows = []

        for scenario_index, scenario in enumerate(selected_scenarios, start=1):
            preview_rows.append(
                {
                    "순위": scenario_index,
                    "상품명": scenario.get("product_name", "-"),
                    "보내는 점포": scenario.get("source_store", "-"),
                    "받는 점포": scenario.get("target_store", "-"),
                    "추천 수량": scenario.get("move_qty", 0),
                    "총점": scenario.get("heuristic_score", "-"),
                    "추천 방식": scenario.get("recommended_path", "-"),
                    "이동수단": f"{scenario.get('transport_icon', '')} {scenario.get('transport_type', '-')}",
                }
            )

        _safe_dataframe(pd.DataFrame(preview_rows), width="stretch", max_rows=5)

    transport_rows = []

    for scenario in selected_scenarios:
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

        for scenario in selected_scenarios:
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

    show_kakao_map_with_multi_trucks(
        stores,
        routes,
        kakao_js_key,
        selected_scenarios,
        speed_multiplier=truck_speed,
        default_selected_count=len(selected_scenarios),
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
        - **이력 보정 비교**: Greedy 추천과 DQN 기반 추천을 비교합니다.
        - **📊 산업공학 알고리즘 분석 결과**: ABC 분석, 재고 회전율, 폐기 위험도, Safety Stock 결과를 확인합니다.
        - **관리자용 메뉴**: 계산 방식, 비용 기준, 이동수단 기준, 상세 데이터를 확인합니다.

        ## 추천 후보 계산 흐름

        1. 엑셀 데이터에서 점포, 상품, 재고, 경로 정보를 불러옵니다.
        2. 악성재고 가능성이 높은 상품과 이동 후보를 선별합니다.
        3. 이동비용, 할인손실비용, 폐기비용을 계산합니다.
        4. 추천 수량, 거리, 시간, 재고 처리 효과를 함께 반영해 총점을 계산합니다.
        5. **산업공학 알고리즘 4종**을 실행해 결과를 Varo 통합 점수에 반영합니다.
        6. 총점 기준으로 최적, 권장, 검토 등급을 부여합니다.
        7. 지도와 표에서 실행 가능한 추천 후보를 확인합니다.

        ## 산업공학 알고리즘

        | 알고리즘 | 설명 | 핵심 지표 |
        |---------|------|---------|
        | **ABC 분석** | 매출가치 기준으로 A/B/C 등급 분류 | abc_grade (A/B/C) |
        | **재고 회전율** | 소진일수 기반 악성재고 판단 | turnover_grade (FAST/NORMAL/SLOW/DEAD) |
        | **폐기 위험도** | 유통기한·판매속도·보관기간 복합 점수화 | disposal_risk_score (0~100) |
        | **Safety Stock** | 수요 변동성·리드타임 기반 안전재고·재주문점 계산 | reorder_status (CRITICAL/WARNING/MONITOR/SAFE) |

        ## Varo 통합 점수

        4개 알고리즘 결과를 하나의 점수로 통합합니다.

        | 구성 요소 | 가중치 | 설명 |
        |---------|------|------|
        | 휴리스틱 점수 | 40% | 비용·수량·전략 기반 기존 점수 |
        | ABC 점수 | 20% | 핵심 상품 우선 처리 |
        | 재고 회전율 | 20% | 악성재고 판단 |
        | 폐기 위험도 | 20% | 폐기 위험 반영 |
        | Safety Stock | +8% | Phase 2 — 자동 반영 |

        ## 비용 산정 기준

        - **이동비용**: 추천 경로의 이동거리, 경유 여부, 선택 이동수단의 단가를 반영한 예상 운송비.
        - **할인손실비용**: 할인 판매 시 정상 판매 대비 감소하는 예상 매출 손실.
        - **폐기비용**: 처리하지 못한 재고를 폐기할 때 발생하는 예상 손실 비용.

        ## 이동수단 기준

        - **도보**: 초근거리·극소량 이동에 사용합니다.
        - **전동자전거**: 근거리·소량 이동에 사용합니다.
        - **오토바이**: 긴급 소량 배송에 사용합니다.
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
    st.header("🤖 이력 보정 비교 페이지")


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

    # ── 학습 메타데이터 입력 ─────────────────────────────
    meta_c1, meta_c2 = st.columns(2)
    with meta_c1:
        dqn_sample_no = st.text_input(
            "샘플 번호 (예: sample09)",
            value=st.session_state.get("dqn_sample_no_val", "sample01"),
            key="dqn_sample_no",
            help="파일명에 포함됩니다. 예: sample01, sample09",
        )
        st.session_state["dqn_sample_no_val"] = dqn_sample_no
    with meta_c2:
        dqn_scenario = st.text_input(
            "시나리오명 (예: expiry)",
            value=st.session_state.get("dqn_scenario_val", ""),
            key="dqn_scenario_name",
            help="학습 목적/상황. 예: expiry, cold, surge",
        )
        st.session_state["dqn_scenario_val"] = dqn_scenario

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
                    sample_no=dqn_sample_no,
                    scenario_name=dqn_scenario,
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

                    # ── 저장 결과 3종 표시 ────────────────────────────
                    named   = saved_paths.get("named_prefix", "")
                    comp    = saved_paths.get("comparison_file", "")
                    ts_pre  = saved_paths.get("timestamp_model_file","").replace("_model.npz","")

                    st.success("✅ DQN 학습 결과 저장 완료")

                    r1, r2, r3 = st.columns(3)
                    with r1:
                        st.markdown(
                            '<div style="background:#e8f5e9;padding:10px;border-radius:8px;font-size:12px;">'
                            '<b>✅ latest 저장 완료</b><br>'
                            'dqn_latest_model.npz<br>'
                            'dqn_latest_recommendations.csv<br>'
                            'dqn_latest_history.csv<br>'
                            'dqn_latest_summary.json</div>',
                            unsafe_allow_html=True,
                        )
                    with r2:
                        st.markdown(
                            f'<div style="background:#e3f2fd;padding:10px;border-radius:8px;font-size:12px;">'
                            f'<b>✅ sample 보관 파일 저장 완료</b><br>'
                            f'{named}_model.npz<br>'
                            f'{named}_recommendations.csv<br>'
                            f'{named}_history.csv<br>'
                            f'{named}_summary.json</div>' if named else
                            '<div style="background:#fff3e0;padding:10px;border-radius:8px;font-size:12px;">'
                            '⚠️ sample_no 미입력<br>sample00_default_* 로 저장됨</div>',
                            unsafe_allow_html=True,
                        )
                    with r3:
                        comp_ok = bool(comp)
                        st.markdown(
                            f'<div style="background:{"#e8f5e9" if comp_ok else "#fce4ec"};padding:10px;border-radius:8px;font-size:12px;">'
                            f'<b>{"✅" if comp_ok else "❌"} dqn_training_comparison.csv<br>누적 기록 완료</b><br>'
                            f'{"위치: dqn_artifacts/" if comp_ok else "저장 실패"}</div>',
                            unsafe_allow_html=True,
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

                # ── 요약 카드 (7단계 추가) ────────────────────────
                total_count = len(rl_compare_result)
                action_match = 0
                action_diff  = 0
                if "action" in rl_compare_result.columns and "rl_recommended_action" in rl_compare_result.columns:
                    valid = rl_compare_result.dropna(subset=["rl_recommended_action"])
                    action_match = int((valid["action"] == valid["rl_recommended_action"]).sum())
                    action_diff  = len(valid) - action_match

                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("비교 후보 수",         f"{total_count}개")
                rc2.metric("정책 매칭 수",         f"{matched_count}개")
                rc3.metric("Greedy=RL 일치",       f"{action_match}개")
                rc4.metric("Greedy≠RL 불일치",     f"{action_diff}개")

                if rl_compare_result["expected_reward"].notna().any():
                    avg_er = rl_compare_result["expected_reward"].dropna().mean()
                    st.caption(f"평균 기대 Reward: **{avg_er:.2f}**")

                # ── 해석 문구 (7단계 추가) ──────────────────────
                st.markdown("---")
                for _, row in rl_compare_result.iterrows():
                    greedy_act = row.get("action", "")
                    rl_act     = row.get("rl_recommended_action", "")
                    if pd.isna(rl_act) or rl_act == "":
                        continue
                    if greedy_act == rl_act:
                        badge = "🟢 **일치**"
                        msg   = "현재 조건 기준의 Greedy 추천과 학습된 정책이 같은 방향을 제안합니다."
                    else:
                        badge = "🔴 **불일치**"
                        msg   = (f"Greedy는 현재 점수 기준의 단기 최적 후보를 선택했지만, "
                                 f"RL은 누적 학습된 보상 기준에서 다른 행동을 추천했습니다. "
                                 f"(Greedy: `{greedy_act}` → RL: `{rl_act}`)")
                    prod = row.get("product_name", "")
                    st.markdown(f"- **{prod}** {badge}: {msg}")
                st.markdown("---")

                cols = [
                    "product_name", "source_store", "target_store",
                    "action", "action_label",
                    "rl_recommended_action",
                    "reward", "expected_reward",
                    "heuristic_score", "greedy_rank", "rl_match_status",
                ]
                # action_label 없으면 자동 생성
                if "action_label" not in rl_compare_result.columns:
                    try:
                        from rl_data_logger import get_action_label_ko
                        rl_compare_result = rl_compare_result.copy()
                        rl_compare_result["action_label"] = rl_compare_result["action"].apply(get_action_label_ko)
                    except Exception:
                        pass

                view = rl_compare_result[[c for c in cols if c in rl_compare_result.columns]].rename(
                    columns={
                        "product_name":           "상품명",
                        "source_store":           "보내는 점포",
                        "target_store":           "받는 점포",
                        "action":                 "현재 Action",
                        "action_label":           "한글 Action",
                        "rl_recommended_action":  "정책 추천 Action",
                        "reward":                 "현재 Reward",
                        "expected_reward":        "기대 Reward",
                        "heuristic_score":        "총점",
                        "greedy_rank":            "Greedy 순위",
                        "rl_match_status":        "매칭 상태",
                    }
                )
                _safe_dataframe(view, width="stretch")

    except FileNotFoundError:
        st.info("rl_policy_table.csv 파일이 없어서 기존 Q-table 비교는 생략합니다.")
    except ImportError:
        st.info("rl_policy_helper.py 파일이 없어서 기존 Q-table 비교는 생략합니다.")
    except Exception as e:
        st.warning(f"기존 정책 비교 중 오류가 발생했습니다: {e}")

    # ── 학습 이력 비교 (dqn_training_comparison.csv) ─────
    st.markdown("---")
    st.subheader("📋 전체 학습 결과 비교")
    st.caption("매 학습 실행 시 dqn_artifacts/dqn_training_comparison.csv에 자동 누적됩니다.")

    try:
        import pandas as _pd
        from pathlib import Path as _Path
        _comp_path = _Path("dqn_artifacts/dqn_training_comparison.csv")
        if _comp_path.exists():
            _comp_df = _pd.read_csv(_comp_path, encoding="utf-8-sig")
            if not _comp_df.empty:
                # 표시용 컬럼 정리
                _disp_cols = [c for c in [
                    "sample_no","scenario_name","learning_rate","episodes",
                    "candidate_count","final_loss","mean_reward","match_rate","trained_at"
                ] if c in _comp_df.columns]
                _disp = _comp_df[_disp_cols].copy()
                # 최신 학습 먼저
                if "trained_at" in _disp.columns:
                    _disp = _disp.sort_values("trained_at", ascending=False)

                # 요약 지표
                sm1, sm2, sm3 = st.columns(3)
                sm1.metric("누적 학습 횟수", f"{len(_comp_df)}회")
                if "match_rate" in _comp_df.columns:
                    sm2.metric("평균 일치율", f"{_comp_df['match_rate'].mean():.1f}%")
                if "final_loss" in _comp_df.columns:
                    sm3.metric("최저 Loss", f"{_comp_df['final_loss'].min():.4f}")

                st.dataframe(_disp, use_container_width=True, hide_index=True)

                # 파일 경로 전체 보기
                with st.expander("📁 저장 파일 경로 전체 보기", expanded=False):
                    _file_cols = [c for c in ["model_file","summary_file","recommendations_file"] if c in _comp_df.columns]
                    if _file_cols:
                        st.dataframe(_comp_df[["trained_at","sample_no"] + _file_cols],
                                     use_container_width=True, hide_index=True)
            else:
                st.info("아직 학습 기록이 없습니다. DQN 학습을 실행하면 자동으로 기록됩니다.")
        else:
            st.info("학습 결과 파일이 없습니다. 첫 번째 DQN 학습 실행 후 여기에 표시됩니다.")
    except Exception as _e:
        st.warning(f"학습 이력 로드 오류: {_e}")

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
    max_truck_routes = max(1, min(int(max_truck_routes), 200))
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

        valid_final_recommendations = _filter_positive_qty_recommendations(final_recommendations)
        if valid_final_recommendations is None or valid_final_recommendations.empty:
            return None

        matched = valid_final_recommendations[
            (valid_final_recommendations["product_name"] == path_row["product_name"])
            & (valid_final_recommendations["source_store"] == path_row["source_store"])
            & (valid_final_recommendations["target_store"] == path_row["target_store"])
        ]

        if matched.empty:
            return None

        return matched.iloc[0]

    if transfer_path_result is None or transfer_path_result.empty:
        return []

    truck_candidates = transfer_path_result[
        transfer_path_result["recommended_path"] != "이동 비추천"
    ].copy()

    truck_candidates = _filter_positive_qty_recommendations(truck_candidates)
    if truck_candidates is None or truck_candidates.empty:
        return []

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

        # 실제 이동 경로 계산에는 transfer_path_result의 이동 방식이 필요하다.
        route_path_type = path_row["recommended_path"]

        rec_match = get_recommendation_match(path_row)

        # 지도 클릭 결과는 대시보드/AI 추천 결과와 같은 final_recommendations 값을 우선 사용한다.
        if rec_match is not None:
            recommended_path = rec_match.get("final_recommendation", route_path_type)
            move_qty = _safe_qty(rec_match, int(_safe_numeric(path_row.get("suggested_transfer_qty", 0), 0)))
            estimated_cost = rec_match.get("estimated_cost", "-")
            heuristic_score = rec_match.get("heuristic_score", "-")
            heuristic_grade = rec_match.get("heuristic_grade", "-")
            reason = rec_match.get("reason", "-")
        else:
            recommended_path = route_path_type
            try:
                move_qty = int(path_row["suggested_transfer_qty"])
            except Exception:
                move_qty = 0
            estimated_cost = path_row.get("direct_cost", path_row.get("via_cost", "-"))
            heuristic_score = "-"
            heuristic_grade = "-"
            reason = path_row.get("recommendation_reason", "-")

        if move_qty <= 0:
            continue

        if route_path_type == "DC 경유 이동 추천":
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

        distance_km = _estimate_route_distance_km(path_row)

        transport_type = _choose_transport_type(
            product_name=product_name,
            qty=move_qty,
            recommended_path=route_path_type,
            selected_transport_type=selected_transport_type,
            distance_km=distance_km,
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
                "recommended_path": str(recommended_path),
                "route_path_type": str(route_path_type),
                "estimated_cost": _format_money(estimated_cost) if _safe_numeric(estimated_cost, None) is not None else str(estimated_cost),
                "heuristic_score": str(round(_safe_numeric(heuristic_score, 0), 1)) if _safe_numeric(heuristic_score, None) is not None else str(heuristic_score),
                "heuristic_grade": str(heuristic_grade),
                "reason": str(reason),
                "candidate_key": f"{product_name}|{source_store}|{target_store}",
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
# 산업공학 알고리즘 페이지
# =========================
def _show_batch_page(final_recommendations):
    """처리 배치 최적화 페이지."""
    _back_to_dashboard()
    st.header("📦 처리 배치 최적화")
    st.caption("오늘 처리할 상품들을 어떤 순서로 진행하면 비용·폐기 손실을 최소화할 수 있는지 보여줍니다.")

    if final_recommendations is None or (
        isinstance(final_recommendations, pd.DataFrame) and final_recommendations.empty
    ):
        st.info("분석 결과가 없습니다.")
        return

    try:
        from action_batch_optimizer import optimize_action_batch, batch_summary
    except ImportError:
        st.error("action_batch_optimizer 모듈을 찾을 수 없습니다.")
        return

    # 제약 조건 입력
    with st.expander("⚙️ 처리 제약 조건 (선택)", expanded=False):
        c1, c2, c3 = st.columns(3)
        budget       = c1.number_input("예산 (원, 0=무제한)", min_value=0, value=0, step=10000, key="batch_budget")
        vehicle_lim  = c2.number_input("차량 수 (0=무제한)",  min_value=0, value=0, step=1,     key="batch_vehicle")
        budget_val   = float(budget)   if budget > 0   else None
        vehicle_val  = int(vehicle_lim) if vehicle_lim > 0 else None

    batch_df = optimize_action_batch(
        final_recommendations,
        budget=budget_val,
        vehicle_limit=vehicle_val,
    )

    if batch_df.empty:
        st.info("처리 순서를 계산할 수 없습니다.")
        return

    summ = batch_summary(batch_df)
    def _num(v, suffix=""): return f"{int(v):,}{suffix}"
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'''<div style="border:1px solid #eee;border-radius:10px;padding:16px;text-align:center;">
            <div style="font-size:12px;color:#888;margin-bottom:4px;">처리 대상</div>
            <div style="font-size:22px;font-weight:800;">{_num(summ.get("total_items",0),"건")}</div></div>''', unsafe_allow_html=True)
    with m2:
        st.markdown(f'''<div style="border:1px solid #eee;border-radius:10px;padding:16px;text-align:center;">
            <div style="font-size:12px;color:#888;margin-bottom:4px;">총 예상 비용</div>
            <div style="font-size:20px;font-weight:800;">{_num(summ.get("total_cost",0),"원")}</div></div>''', unsafe_allow_html=True)
    with m3:
        st.markdown(f'''<div style="border:1px solid #eee;border-radius:10px;padding:16px;text-align:center;">
            <div style="font-size:12px;color:#888;margin-bottom:4px;">폐기 회피 이익</div>
            <div style="font-size:20px;font-weight:800;">{_num(summ.get("total_avoidance",0),"원")}</div></div>''', unsafe_allow_html=True)
    with m4:
        st.markdown(f'''<div style="border:1px solid #eee;border-radius:10px;padding:16px;text-align:center;">
            <div style="font-size:12px;color:#888;margin-bottom:4px;">예산 내 처리</div>
            <div style="font-size:22px;font-weight:800;">{_num(summ.get("within_budget",0),"건")}</div></div>''', unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🏆 오늘의 최적 처리 순서")
    st.dataframe(batch_df, width="stretch", hide_index=True)


def _show_effect_page(final_recommendations):
    """Before/After 효과 지표 페이지."""
    _back_to_dashboard()
    st.header("📊 Varo 도입 전/후 효과 분석")
    st.caption("Varo 추천 적용 시 예상 폐기비용 절감 및 재고 균형 개선 효과를 추정합니다.")

    if final_recommendations is None or (
        isinstance(final_recommendations, pd.DataFrame) and final_recommendations.empty
    ):
        st.info("분석 결과가 없습니다.")
        return

    try:
        from effect_calculator import calc_effects
    except ImportError:
        st.error("effect_calculator 모듈을 찾을 수 없습니다.")
        return

    eff = calc_effects(final_recommendations)
    if not eff:
        st.info("효과 계산에 필요한 데이터가 부족합니다.")
        return

    # 핵심 카드
    st.markdown("### 💡 핵심 효과 요약")
    def _mc(label, value, delta=None, color="#333"):
        delta_html = f'<div style="font-size:11px;color:#ef5350;margin-top:2px;">{delta}</div>' if delta else ""
        return f'''<div style="border:1px solid #eee;border-radius:10px;padding:16px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">{label}</div>
            <div style="font-size:18px;font-weight:800;color:{color};">{value}</div>{delta_html}</div>'''
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(_mc("기존 방식 예상 폐기비용", f'{int(eff.get("before_disposal_cost",0)):,}원'), unsafe_allow_html=True)
    with c2: st.markdown(_mc("Varo 적용 후 예상 폐기비용", f'{int(eff.get("after_disposal_cost",0)):,}원', delta=f'-{int(eff.get("saving_amount",0)):,}원'), unsafe_allow_html=True)
    with c3: st.markdown(_mc("폐기비용 절감률", f'{eff.get("saving_rate_pct",0):.1f}%', color="#2e7d32"), unsafe_allow_html=True)
    with c4: st.markdown(_mc("위험 감소 상품 수", f'{eff.get("n_risk_reduced",0)}개'), unsafe_allow_html=True)

    st.markdown("---")
    c5, c6, c7 = st.columns(3)
    with c5: st.markdown(_mc("처리 가능 재고 수량", f'{int(eff.get("processable_qty",0)):,}개'), unsafe_allow_html=True)
    with c6: st.markdown(_mc("재고 불균형 개선률",  f'{eff.get("rebalance_rate_pct",0):.1f}%'), unsafe_allow_html=True)
    with c7: st.markdown(_mc("운송비 부담률",       f'{eff.get("transport_burden_rate_pct",0):.2f}%'), unsafe_allow_html=True)

    with st.expander("📐 계산식 보기", expanded=False):
        st.markdown(f"""
        | 항목 | 계산식 |
        |------|--------|
        | 기존 폐기비용 | {eff.get('_formula_before','-')} |
        | Varo 적용 폐기비용 | {eff.get('_formula_after','-')} |
        | 절감액 | 기존 폐기비용 − Varo 적용 폐기비용 |
        | 절감률 | 절감액 ÷ 기존 폐기비용 × 100% |
        | 재고 불균형 개선률 | 재배치 이동 건수 ÷ 전체 추천 수 × 100% |
        """)
    st.caption("※ 추정치입니다. 실제 결과는 점포 운영 조건에 따라 달라질 수 있습니다.")


def _show_guide_page(final_recommendations=None):
    """Varo 가이드 & 설명 — 기존 설명 페이지들을 탭으로 통합."""
    _back_to_dashboard()
    st.header("📚 Varo 가이드 & 설명")

    tg1, tg2, tg3, tg4, tg5 = st.tabs([
        "🧭 Varo 개요",
        "🧮 VHS 알고리즘",
        "💰 비용 산정 기준",
        "🚚 이동수단 기준",
        "📖 용어 설명",
    ])

    # ── 탭 1: Varo 개요 ──────────────────────────────────
    with tg1:
        st.markdown(
            """
            ## Varo란?
            Varo는 편의점 악성재고를 자동으로 감지하고, 상품별로 최적 처리 방법을 추천하는
            의사결정 시스템입니다.

            ### 처리 흐름
            1. **엑셀 데이터 업로드** — 점포, 상품, 재고, 경로 정보 입력
            2. **자동 분석** — 10개 산업공학 알고리즘 순차 실행
            3. **VARO Hybrid Score(VHS) 계산** — 알고리즘 결과 → 단일 점수
            4. **처리 액션 자동 추천** — 재배치 이동 / 할인 판매 / 폐기 / 보류
            5. **대시보드 확인** — 상품별 우선순위 및 실행 계획 확인

            ### 4가지 처리 액션
            | 액션 | 조건 | 설명 |
            |------|------|------|
            | 🚚 재배치 이동 | 매칭 GOOD+ + 목적지 수요 있음 | 재고를 필요한 점포로 이동 |
            | 🏷️ 할인 판매 | 폐기위험 HIGH+ 또는 회전율 SLOW+ | 할인으로 빠른 소진 |
            | 🗑️ 폐기 | 폐기 CRITICAL + 회전 DEAD + C등급 | 손실 최소화 후 폐기 |
            | ⏸️ 보류 | 위 조건 미해당 | 추가 모니터링 유지 |

            ### 메뉴 안내
            | 버튼 | 내용 |
            |------|------|
            | 🧠 AI 추천 결과 | 상품별 추천 후보, 점수, 등급 |
            | 🗺 재고 이동 지도 | 추천 경로를 지도에서 확인 |
            | 🤖 이력 보정 비교 | Greedy vs DQN 비교 |
            | 📊 VARO 상세 분석 | VHS 전체 분석, 알고리즘 비교 |
            | 🔮 What-if 시뮬 | 파라미터 변경 시나리오 비교 |
            | 🌐 최소비용 경로 | 네트워크 최적화 분석 |
            """
        )

    # ── 탭 2: VHS 알고리즘 ───────────────────────────────
    with tg2:
        st.markdown(
            """
            ## VARO Hybrid Score (VHS)

            10개 산업공학 알고리즘 결과를 **상황 감지 → 가중치 조정 → 이력 보정** 과정을
            거쳐 0~100점 단일 점수로 통합합니다.

            ### 컴포넌트 가중치
            | 역할 | 컴포넌트 | 가중치 | 설명 |
            |------|----------|--------|------|
            | A. 긴급도 | 폐기위험도 | **22%** | 유통기한·판매속도 복합 점수 |
            | A. 긴급도 | 재고회전율 | **18%** | 악성재고 판단의 본질 지표 |
            | A. 긴급도 | 수요예측 | **14%** | 재고 소진 임박 위험 |
            | C. 비용효율 | 휴리스틱 | 12% | 비용·거리·수량 종합 |
            | B. 이동적합 | 안전재고/ROP | 10% | 목적지 재고 필요성 |
            | B. 이동적합 | 점포매칭 | 9% | 점포-상품 매칭 적합도 |
            | E. 상품맥락 | ABC등급 | 6% | 상품 가치 (A/B/C) |
            | D. 기존연동 | 그리디선택 | 5% | 그리디 순위 + 선택 여부 |
            | C. 비용효율 | EOQ | 3% | 발주량 과잉·과소 |
            | C. 비용효율 | 최소비용경로 | 1% | 네트워크 경로 효율 |

            ### 상황 감지 & 가중치 자동 조정
            | 상황 | 감지 조건 | 조정 내용 |
            |------|-----------|-----------|
            | ⏰ 유통기한 임박 | expiry_days ≤ 5일 | 폐기위험 ×2.0, 수요예측 ×1.5 |
            | ❄️ 냉동·냉장 과잉 | 냉동/냉장 카테고리 | EOQ ×1.8, 매칭 ×1.5 |
            | 💸 이동비용 높음 | 비용 상위 20% | 네트워크비용 ×2.5 |
            | 📈 수요 급증 | demand_trend=INCREASING | 수요예측 ×1.8, 매칭 ×1.4 |
            | 💀 악성재고 | turnover_grade=DEAD | 회전율 ×1.8, 폐기위험 ×1.4 |
            | 🚨 재주문 위기 | reorder_status=CRITICAL | 안전재고 ×2.0, 수요예측 ×1.5 |

            ### 이력 보정
            강화학습 reward 신호를 학습 데이터로 활용해 VHS를 ±8점 범위 내에서 보정합니다.
            상황별 경험이 쌓일수록 보정 정확도가 높아집니다.
            """
        )

    # ── 탭 3: 비용 산정 기준 ─────────────────────────────
    with tg3:
        st.markdown(
            """
            ## 비용 산정 기준

            ### 이동비용 (Transport Cost)
            추천 경로의 **이동거리 × 이동수단 단가** + 경유 여부에 따른 추가비용.

            | 이동수단 | 기준 단가 | 적합 거리 |
            |----------|-----------|-----------|
            | 도보 | 0원/km | 0.5km 이내 |
            | 전동자전거 | ~200원/km | 1km 이내 |
            | 오토바이 | ~400원/km | 3km 이내 |
            | 소형 차량 | ~600원/km | 10km 이내 |
            | 냉동·냉장 탑차 | ~1,200원/km | DC 경유 포함 |

            ### 할인손실비용 (Discount Loss)
            할인 판매 시 정상가 대비 감소하는 예상 매출 손실.
            `할인손실 = unit_cost × 할인율 × 처리 수량`

            ### 폐기비용 (Disposal Cost)
            처리하지 못한 재고를 폐기할 때 발생하는 손실.
            `폐기비용 ≈ unit_cost × 처리 수량 × 1.4` (물류 포함)

            ### 비용 비교 기준
            Varo는 **이동비용 < 폐기비용**인 경우 이동을 우선 추천합니다.
            """
        )

    # ── 탭 4: 이동수단 기준 ──────────────────────────────
    with tg4:
        st.markdown(
            """
            ## 이동수단 선택 기준

            | 이동수단 | 최대 거리 | 최대 수량 | 특이사항 |
            |----------|-----------|-----------|----------|
            | 🚶 도보 | 0.5 km | 10개 | 초근거리 소량 |
            | 🛴 전동자전거 | 1 km | 30개 | 근거리 소량 |
            | 🏍 오토바이 | 3 km | 20개 | 긴급 소량 배송 |
            | 🚗 소형 차량 | 10 km | 150개 | 일반 점포간 이동 |
            | 🚛 냉동·냉장 탑차 | 제한 없음 | 제한 없음 | DC 경유, 냉장 필수 상품 |

            ### 이동수단 자동 선택 로직
            1. 냉동·냉장 상품 → 냉동탑차 우선
            2. 거리·수량에 따라 적합한 이동수단 선택
            3. 비용 최소화 방향으로 최종 선택
            4. DC 경유가 직접 이동보다 비용이 낮으면 경유 추천
            """
        )

    # ── 탭 5: 용어 설명 ──────────────────────────────────
    with tg5:
        st.markdown(
            """
            ## 주요 용어 설명

            | 용어 | 설명 |
            |------|------|
            | **VHS** | VARO Hybrid Score — 10개 알고리즘 통합 점수 (0~100) |
            | **ABC 분석** | 매출가치 기준 A(상위 80%) / B(80~95%) / C(하위 5%) 분류 |
            | **재고 회전율** | 소진일수 기반 FAST / NORMAL / SLOW / DEAD 등급 |
            | **폐기 위험도** | 유통기한·판매속도·보관기간 복합 CRITICAL~LOW 등급 |
            | **Safety Stock** | 수요 변동 대비 최소 보유 재고량 (SS = Z × σ × √L) |
            | **ROP** | Reorder Point — 재주문이 필요한 재고 수준 |
            | **EOQ** | Economic Order Quantity — 총 비용 최소화 발주량 |
            | **수요 예측** | WMA / SMA / NAIVE 방법으로 7일 수요 예측 |
            | **클러스터링** | K-means로 위치·재고 특성 기반 점포 그룹화 |
            | **점포-상품 매칭** | 수요 적합성·긴급도·ABC·클러스터·거리 종합 매칭 점수 |
            | **최소비용 네트워크** | SSP 알고리즘으로 전체 재고 이동 비용 최소화 경로 |
            | **DQN** | Deep Q-Network — 강화학습 기반 의사결정 보정 |
            | **그리디 선택** | 휴리스틱 점수 기준 최고점 후보 자동 선택 |
            | **상황 감지** | 유통기한 임박 등 6가지 상황 자동 감지 후 VHS 가중치 조정 |
            """
        )


def _show_whatif_page(final_recommendations):
    """What-if 시뮬레이션 페이지."""
    _back_to_dashboard()
    st.header("🔮 What-if 시뮬레이션")

    if final_recommendations is None or (
        isinstance(final_recommendations, pd.DataFrame) and final_recommendations.empty
    ):
        st.info("추천 결과가 없습니다. 먼저 분석을 실행해주세요.")
        return

    try:
        from whatif_simulator import (
            run_scenario, compare_scenarios, sensitivity_analysis,
            PRESET_SCENARIOS, DEFAULT_PARAMS,
        )
    except ImportError:
        st.error("whatif_simulator 모듈을 찾을 수 없습니다.")
        return

    df = final_recommendations

    # ── 탭 구성 ──────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["🎛 파라미터 직접 조정", "📊 시나리오 비교", "📐 민감도 분석"])

    # ── 탭 1: 파라미터 직접 조정 ─────────────────────────
    with tab1:
        st.subheader("파라미터 조정 후 점수 재계산")

        preset_name = st.selectbox(
            "프리셋 시나리오 선택 (또는 아래에서 직접 조정)",
            ["직접 조정"] + list(PRESET_SCENARIOS.keys()),
            key="whatif_preset",
        )

        # ── 슬라이더 session_state 초기화 (최초 1회) ──────
        if "whatif_discount" not in st.session_state:
            st.session_state["whatif_discount"] = int(DEFAULT_PARAMS["discount_rate"] * 100)
        if "whatif_demand" not in st.session_state:
            st.session_state["whatif_demand"]   = int(DEFAULT_PARAMS["demand_change_pct"])
        if "whatif_cost" not in st.session_state:
            st.session_state["whatif_cost"]     = float(DEFAULT_PARAMS["cost_multiplier"])
        if "whatif_lead" not in st.session_state:
            st.session_state["whatif_lead"]     = int(DEFAULT_PARAMS["lead_time_change"])

        # ── 프리셋 변경 시 session_state만 업데이트 후 rerun ──
        if preset_name != "직접 조정":
            preset_p = PRESET_SCENARIOS[preset_name]
            if preset_name != st.session_state.get("_whatif_prev_preset", "직접 조정"):
                st.session_state["whatif_discount"] = int(preset_p["discount_rate"] * 100)
                st.session_state["whatif_demand"]   = int(preset_p["demand_change_pct"])
                st.session_state["whatif_cost"]     = float(preset_p["cost_multiplier"])
                st.session_state["whatif_lead"]     = int(preset_p["lead_time_change"])
                st.session_state["_whatif_prev_preset"] = preset_name
                st.rerun()
        else:
            st.session_state["_whatif_prev_preset"] = "직접 조정"

        # ── 슬라이더: value= 없이 key만 사용 (session_state 충돌 방지) ──
        c1, c2 = st.columns(2)
        with c1:
            discount_rate = st.slider(
                "💸 할인율 (%)", 0, 50, step=5,
                help="폐기 대신 할인 판매 시 단가 손실 비율",
                key="whatif_discount",
            ) / 100.0
            demand_change = st.slider(
                "📦 수요 변동 (%)", -30, 30, step=5,
                help="수요가 기준 대비 얼마나 변했는가",
                key="whatif_demand",
            )
        with c2:
            cost_mult = st.slider(
                "🚚 이동비용 배율 (×)", 0.5, 2.0, step=0.1,
                help="운송비 변동 배율 (1.0 = 현재 기준)",
                key="whatif_cost",
            )
            lead_change = st.slider(
                "⏱ 리드타임 변동 (일)", -2, 5, step=1,
                help="발주~입고 리드타임 변동",
                key="whatif_lead",
            )

        sl_options = [0.90, 0.95, 0.99]
        _sl_cur = st.session_state.get("whatif_sl", 0.95)
        _sl_idx = sl_options.index(_sl_cur) if _sl_cur in sl_options else 1
        sl_val = st.selectbox(
            "🎯 서비스 수준 (Safety Stock Z계수)",
            sl_options,
            index=_sl_idx,
            format_func=lambda x: f"{x:.0%} (Z={[1.28,1.65,2.33][sl_options.index(x)]})",
            key="whatif_sl",
        )

        params = {
            "discount_rate":     discount_rate,
            "cost_multiplier":   cost_mult,
            "demand_change_pct": float(demand_change),
            "service_level":     sl_val,
            "lead_time_change":  lead_change,
        }

        sim_df = run_scenario(df, params)

        # 결과 요약
        base_avg  = pd.to_numeric(df.get("heuristic_score", 50), errors="coerce").mean()
        sim_avg   = sim_df["heuristic_score_sim"].mean()
        delta     = sim_avg - base_avg

        st.markdown("---")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("현재 평균 점수",    f"{base_avg:.1f}점")
        mc2.metric("시뮬레이션 점수",   f"{sim_avg:.1f}점",  f"{delta:+.1f}점")
        mc3.metric("점수 상승 상품",
                   f"{(sim_df['score_delta'] > 0).sum()}개",
                   help="시뮬레이션 후 점수가 오른 추천 건수")
        mc4.metric("점수 하락 상품",
                   f"{(sim_df['score_delta'] < 0).sum()}개",
                   help="시뮬레이션 후 점수가 내린 추천 건수")

        with st.expander("상위/하위 변화 상품 보기", expanded=True):
            show_cols = ["product_name", "source_store", "target_store",
                         "heuristic_score", "heuristic_score_sim", "score_delta"]
            show_df = sim_df[[c for c in show_cols if c in sim_df.columns]].copy()
            show_df = show_df.sort_values("score_delta", ascending=False).head(20).reset_index(drop=True)
            st.dataframe(show_df, width="stretch")

    # ── 탭 2: 시나리오 비교 ──────────────────────────────
    with tab2:
        st.subheader("5개 프리셋 시나리오 비교")
        cmp_df = compare_scenarios(df, PRESET_SCENARIOS)
        if not cmp_df.empty:
            st.dataframe(cmp_df, width="stretch")

            # 최적 시나리오 강조
            best_idx = cmp_df["평균점수"].idxmax()
            best_name = cmp_df.loc[best_idx, "시나리오"]
            st.success(f"🏆 최고 점수 시나리오: **{best_name}** ({cmp_df.loc[best_idx,'평균점수']}점)")

    # ── 탭 3: 민감도 분석 ────────────────────────────────
    with tab3:
        st.subheader("파라미터 민감도 분석")
        st.caption("각 파라미터를 단위 변경했을 때 평균 추천 점수의 변화량")
        sens_df = sensitivity_analysis(df)
        if not sens_df.empty:
            st.dataframe(sens_df, width="stretch")

            # 가장 민감한 파라미터
            max_abs = sens_df["평균점수 변화"].abs().idxmax()
            most_sensitive = sens_df.loc[max_abs, "파라미터 변경"]
            st.info(f"📌 가장 민감한 파라미터: **{most_sensitive}** — 점수 변화 {sens_df.loc[max_abs,'평균점수 변화']:+.2f}점")

            st.markdown(
                """
                **해석 방법**
                - **▲ 유리**: 이 파라미터 변화가 추천 점수를 높임
                - **▼ 불리**: 이 파라미터 변화가 추천 점수를 낮춤
                - 절댓값이 클수록 해당 파라미터에 민감한 시스템
                """
            )


def _show_network_page():
    """최소비용 네트워크 분석 결과 페이지."""
    _back_to_dashboard()
    st.header("🌐 최소비용 네트워크 분석")

    flow_df   = st.session_state.get("_network_flow_df",  None)
    node_df   = st.session_state.get("_network_node_df",  None)
    summary   = st.session_state.get("_network_summary",  {})

    if flow_df is None or (isinstance(flow_df, pd.DataFrame) and flow_df.empty):
        st.info("네트워크 분석 결과가 없습니다. routes 데이터를 확인하거나 앱을 재시작해주세요.")
        return

    # 요약 카드
    total_cost     = summary.get("total_cost", 0)
    solved_rate    = summary.get("solved_rate", 0)
    total_flow     = summary.get("total_flow_qty", 0)
    n_flows        = summary.get("n_flows", 0)
    avg_path       = summary.get("avg_path_len", 0)

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#e8f5e9,#f1f8e9);
                    border:1px solid #a5d6a7;border-radius:16px;
                    padding:18px 24px;margin-bottom:20px;">
            <div style="font-size:13px;color:#555;font-weight:700;margin-bottom:8px;">
                네트워크 최적화 요약
            </div>
            <div style="display:flex;gap:28px;flex-wrap:wrap;">
                <div><div style="font-size:26px;font-weight:900;color:#2e7d32;">
                    {solved_rate:.1f}%</div>
                    <div style="font-size:12px;color:#888;">수요 해소율</div></div>
                <div><div style="font-size:26px;font-weight:900;color:#333;">
                    {int(total_cost):,}원</div>
                    <div style="font-size:12px;color:#888;">최소 총 이동비용</div></div>
                <div><div style="font-size:26px;font-weight:900;color:#1565c0;">
                    {int(total_flow):,}개</div>
                    <div style="font-size:12px;color:#888;">총 이동 수량</div></div>
                <div><div style="font-size:22px;font-weight:800;color:#6a1b9a;">
                    {n_flows}건</div>
                    <div style="font-size:12px;color:#888;">최적 이동 경로 수</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["📦 최적 이동 경로", "🏪 점포별 공급/수요", "💡 알고리즘 설명"])

    with tab1:
        st.subheader("최소비용 최적 이동 경로")
        if isinstance(flow_df, pd.DataFrame) and not flow_df.empty:
            show_df = flow_df.sort_values("total_cost").reset_index(drop=True)
            st.dataframe(show_df, width="stretch")
            st.caption(f"평균 경로 길이: {avg_path:.1f}홉")
        else:
            st.info("이동 경로가 없습니다.")

    with tab2:
        st.subheader("점포별 공급/수요 현황")
        if isinstance(node_df, pd.DataFrame) and not node_df.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("📤 공급 점포", f"{(node_df['role']=='SUPPLY').sum()}개")
            c2.metric("📥 수요 점포", f"{(node_df['role']=='DEMAND').sum()}개")
            c3.metric("⚖️ 균형 점포", f"{(node_df['role']=='BALANCED').sum()}개")

            with st.expander("공급 과잉 점포 (상위 15)", expanded=True):
                sup = node_df[node_df["role"]=="SUPPLY"].nlargest(15,"excess")
                st.dataframe(sup[["store_name","total_stock","supply_30d","excess"]].reset_index(drop=True), width="stretch")
            with st.expander("재고 부족 점포 (상위 15)", expanded=False):
                dem = node_df[node_df["role"]=="DEMAND"].nsmallest(15,"excess")
                st.dataframe(dem[["store_name","total_stock","supply_30d","excess"]].reset_index(drop=True), width="stretch")

    with tab3:
        st.markdown(
            """
            ### 최소비용 네트워크 알고리즘 (SSP)

            | 항목 | 내용 |
            |------|------|
            | 알고리즘 | Successive Shortest Path (SSP) |
            | 최단경로 | Dijkstra (heapq 기반) |
            | 비용 기준 | routes 시트의 `transport_cost` |
            | 공급 기준 | 30일 수요 대비 재고 과잉량 |
            | 수요 기준 | 30일 수요 대비 재고 부족량 |
            | DC 역할 | 중간 허브 (비용 없이 경유) |

            **수요 해소율** = 최적 흐름으로 처리된 수요 ÷ 전체 수요 × 100%
            """
        )


def _show_algorithms_page(final_recommendations, inventory=None):
    """VARO Hybrid Score 통합 대시보드."""
    _back_to_dashboard()

    if final_recommendations is None or (
        isinstance(final_recommendations, pd.DataFrame) and final_recommendations.empty
    ):
        st.info("분석 결과가 없습니다. 먼저 엑셀 파일을 업로드해 주세요.")
        return

    df = final_recommendations.copy()

    # VHS 없으면 즉석 계산
    if "vhs" not in df.columns:
        try:
            from varo_hybrid_score import calculate_varo_hybrid_score
            df = calculate_varo_hybrid_score(df)
        except Exception:
            pass

    try:
        from varo_hybrid_score import get_vhs_summary, _BASE_WEIGHTS, _ACTION_ICONS, _SITUATION_MODS
        summary = get_vhs_summary(df) if "vhs" in df.columns else {}
    except Exception:
        summary = {}; _BASE_WEIGHTS = {}; _ACTION_ICONS = {}; _SITUATION_MODS = {}

    has_vhs = "vhs" in df.columns

    # ══════════════════════════════════════════════════════
    #  헤더 — VHS 요약 카드
    # ══════════════════════════════════════════════════════
    avg_vhs     = summary.get("avg_vhs", 0)
    top_prod    = summary.get("top_product", "-")
    top_vhs     = summary.get("top_vhs", 0)
    top_action  = summary.get("top_action", "-")
    action_cnt  = summary.get("action_counts", {})
    sit_cnt     = summary.get("situation_counts", {})
    grade_cnt   = summary.get("grade_counts", {})

    top_icon  = _ACTION_ICONS.get(top_action, "")
    act_color = {"재배치 이동":"#1976d2","할인 판매":"#f57c00",
                 "폐기":"#ef5350","보류":"#43a047"}.get(top_action, "#555")

    def _gauge_color(s):
        if s >= 80: return "#e57373"
        if s >= 65: return "#e65100"
        if s >= 50: return "#f9a825"
        return "#43a047"

    grade_bar = "".join(
        f'<span style="display:inline-block;background:{["#ef5350","#e65100","#f9a825","#66bb6a","#aaa"][i]};'
        f'color:#fff !important;padding:3px 10px;border-radius:4px;'
        f'font-size:12px;font-weight:700;margin:2px;">'
        f'{g} {grade_cnt.get(g,0)}건</span>'
        for i, g in enumerate(["최우선 처리","우선 처리","검토 필요","모니터링","후순위"])
    )

    act_chips = "".join(
        f'<span style="display:inline-block;padding:4px 12px;border-radius:12px;'
        f'font-size:13px;font-weight:700;margin:3px;'
        f'background:{["#1565c0","#e65100","#e57373","#2e7d32"][i]};color:#fff !important;">'
        f'{["🚚","🏷️","🗑️","⏸️"][i]} {a} {action_cnt.get(a,0)}건</span>'
        for i,a in enumerate(["재배치 이동","할인 판매","폐기","보류"])
    )

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#60a5fa 0%,#93c5fd 60%,#3b82f6 100%);
                    border-radius:20px;padding:24px 28px;margin-bottom:18px;
                    box-shadow:0 4px 18px rgba(37,99,235,0.25);">
            <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:center;">
                <div>
                    <div style="font-size:10px;color:#bfdbfe !important;font-weight:900;letter-spacing:2px;text-transform:uppercase;margin-bottom:4px;opacity:1;">VARO HYBRID SCORE</div>
                    <div style="font-size:48px;font-weight:900;color:#ffffff;line-height:1;text-shadow:0 2px 8px rgba(0,0,0,0.4);-webkit-text-fill-color:#fff;">
                        {avg_vhs}
                        <span style="font-size:18px;color:#dbeafe;"> 점</span>
                    </div>
                    <div style="font-size:12px;color:#dbeafe;margin-top:4px;">전체 {summary.get("n_total",0)}건 평균
                    </div>
                </div>
                <div style="border-left:1px solid rgba(255,255,255,0.25);padding-left:24px;">
                    <div style="font-size:10px;color:#bfdbfe;font-weight:900;letter-spacing:1px;margin-bottom:6px;">최우선 처리 상품</div>
                    <div style="font-size:16px;font-weight:900;color:#fff;text-shadow:0 1px 4px rgba(0,0,0,0.3);">{top_prod}</div>
                    <div style="display:inline-block;background:{act_color};color:#fff !important;
                                padding:5px 14px;border-radius:20px;font-size:14px;font-weight:800;margin-top:6px;">
                        {top_icon} {top_action}
                    </div>
                    <div style="font-size:12px;color:#dbeafe;margin-top:4px;">VHS {top_vhs:.1f}점</div>
                </div>
                <div style="border-left:1px solid rgba(255,255,255,0.25);padding-left:24px;flex:1;">
                    <div style="font-size:10px;color:#bfdbfe;font-weight:900;letter-spacing:1px;margin-bottom:8px;">처리 액션 분포</div>
                    {act_chips}
                    <div style="margin-top:10px;">{grade_bar}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 상황 감지 뱃지
    active_sits = {k: v for k, v in sit_cnt.items() if v > 0}
    if active_sits:
        badges = " ".join(
            f'<span style="background:#fff3e0;border:1px solid #ffcc02;border-radius:20px;'
            f'padding:4px 12px;font-size:12px;font-weight:700;color:#e65100;margin:2px;display:inline-block;">'
            f'⚡ {k} {v}건</span>'
            for k, v in active_sits.items()
        )
        st.markdown(f'<div style="margin-bottom:14px;">{badges}</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════
    #  탭 구성
    # ══════════════════════════════════════════════════════
    t1, t2, t3, t4, t5, t6 = st.tabs([
        "🎯 VHS 추천 목록",
        "📊 알고리즘 vs VHS 비교",
        "🏗️ 8구성요소 분석",
        "⚖️ 가중치 & 상황 감지",
        "🔬 컴포넌트 기여 분석",
        "📋 32개 알고리즘 현황",
    ])

    # ══════════════════════════════════════════════════════
    #  탭 1: VHS 추천 목록 (시각 카드 + 테이블)
    # ══════════════════════════════════════════════════════
    with t1:
        if not has_vhs:
            st.info("VHS 결과 없음")
        else:
            # 액션 필터
            all_actions = sorted(set(
                    ("  " + str(a)) if not str(a).startswith(" ") else str(a)
                    for a in (df["vhs2_action"] if "vhs2_action" in df.columns else df["vhs_action"]).dropna()
                ))
            selected_acts = st.multiselect(
                "액션 필터", all_actions, default=all_actions, key="vhs_act_filter",
            )
            show_df = df[(df["vhs2_action"] if "vhs2_action" in df.columns else df["vhs_action"])
                .apply(lambda x: ("  " + str(x)) if not str(x).startswith(" ") else str(x))
                .isin(selected_acts)].copy() if selected_acts else df.copy()

            # 상위 5개 시각 카드
            st.markdown("**🏆 VHS 상위 5개 추천**")
            top5 = show_df.head(5)
            cols5 = st.columns(min(len(top5), 5))
            for i, (_, row) in enumerate(top5.iterrows()):
                vhs_v  = float(row.get("vhs2") or row.get("vhs", 0))
                action = str(row.get("vhs2_action") or row.get("vhs_action", "-"))
                ac     = {"재배치 이동":"#1976d2","할인 판매":"#f57c00",
                          "폐기":"#ef5350","보류":"#43a047"}.get(action, "#555")
                gauge  = _gauge_color(vhs_v)
                icon   = _ACTION_ICONS.get(action, "")
                with cols5[i]:
                    st.markdown(
                        f"""
                        <div style="border:2px solid {ac};border-radius:14px;
                                    padding:14px 12px;text-align:center;
                                    background:linear-gradient(160deg,#fff,#f8f9ff);">
                            <div style="font-size:11px;color:#888;font-weight:700;
                                        overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                                {str(row.get("product_name","-"))[:14]}
                            </div>
                            <div style="font-size:28px;font-weight:900;color:{gauge};margin:6px 0;">
                                {vhs_v:.0f}
                            </div>
                            <div style="height:5px;background:#eee;border-radius:3px;margin:6px 0;">
                                <div style="width:{vhs_v}%;height:100%;background:{gauge};border-radius:3px;"></div>
                            </div>
                            <div style="background:{ac};color:#fff;border-radius:10px;
                                        padding:2px 8px;font-size:11px;font-weight:700;">
                                {icon}{action}
                            </div>
                            <div style="font-size:10px;color:#aaa;margin-top:4px;">
                                {str(row.get("source_store","-"))[:8]}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)

            # 전체 테이블 (배지 포함)
            st.markdown("**전체 목록**")
            disp = show_df[[
                c for c in ["vhs_rank","product_name","source_store","target_store",
                            "vhs2","vhs2_grade","vhs2_action","vhs2_scenario_labels","vhs2_confidence_label",
                            "vhs2_history_correction"]
                if c in show_df.columns
            ]].copy()
            disp.columns = [
                {"vhs_rank":"순위","vhs2":"VHS","vhs":"VHS(구)","vhs2_grade":"등급",
                 "vhs2_action":"추천액션","vhs2_scenario_labels":"감지상황",
                 "vhs2_confidence_label":"신뢰도",
                 "product_name":"상품명","source_store":"출발","target_store":"도착",
                 "vhs2_history_correction":"이력보정"}.get(c, c)
                for c in disp.columns
            ]
            st.dataframe(disp, width="stretch")

    # ══════════════════════════════════════════════════════
    #  탭 2: 알고리즘 vs VHS 비교
    # ══════════════════════════════════════════════════════
    with t2:
        st.subheader("📊 알고리즘 vs VHS 효율 비교")
        st.caption("개별 알고리즘 점수와 VHS를 직접 비교해 통합 점수의 효율을 확인합니다.")

        if not has_vhs or "vhs" not in df.columns:
            st.info("VHS 결과가 없습니다.")
        else:
            try:
                from scipy.stats import spearmanr
            except ImportError:
                import numpy as np
                def spearmanr(x, y):
                    """scipy 없을 때 Spearman 상관계수 수동 계산"""
                    import pandas as _pd
                    n = len(x)
                    if n < 2:
                        return 0.0, None
                    rx = _pd.Series(x).rank().values.astype(float)
                    ry = _pd.Series(y).rank().values.astype(float)
                    d  = rx - ry
                    rho = 1.0 - 6.0 * float((d**2).sum()) / max(n*(n**2-1), 1)
                    return rho, None

            # ── 선택 가능한 알고리즘 목록 ─────────────────
            _ALGO_META = {
                "disposal_risk_score": " #3  폐기 위험도",
                "turnover_score": " #2  재고 회전율",
                "abc_score": " #1  ABC 분석",
                "demand_forecast_score": " #6  수요 예측",
                "safety_stock_score": " #4  Safety Stock",
                "eoq_score": " #5  EOQ",
                "match_score": " #8  점포-상품 매칭",
                "heuristic_score":           "휴리스틱 (기존)",
                "aging_score": " #11 재고 노후화",
                "trend_score": " #12 판매 추세",
                "relocation_failure_score": " #16 재배치 실패위험",
                "substitute_conflict_score": " #13 대체상품 충돌",
                "category_balance_score": " #14 카테고리 균형",
                "store_capacity_score": " #15 점포 처리 능력",
                "discount_sensitivity_score": " #17 할인 민감도",
                "disposal_avoidance_score": " #18 폐기 회피 이익",
                "priority_queue_score": " #19 우선순위 큐",
                "newsvendor_score": " #26 Newsvendor",
                "topsis_score": " #24 TOPSIS",
                "pareto_score": " #31 Pareto 분석",
                "multiobjective_score": " #20 다목적 의사결정",
                "service_level_score": " #25 서비스 수준",
                "queue_capacity_score": " #27 대기행렬",
                "bottleneck_score": " #30 병목 분석",
                "sensitivity_score": " #29 민감도 분석",
                "transport_lp_score": " #22 수송 문제 LP",
                "lp_allocation_score": " #21 선형계획법",
                "assignment_score": " #23 할당 문제",
            }
            avail_algos = {k: v for k, v in _ALGO_META.items() if k in df.columns}

            if not avail_algos:
                st.info("비교 가능한 알고리즘 점수 컬럼이 없습니다.")
            else:
                # 알고리즘 선택 (기본: 주요 5개)
                default_sel = [k for k in [
                    "disposal_risk_score","turnover_score","heuristic_score",
                    "demand_forecast_score","match_score"
                ] if k in avail_algos][:5]

                selected_keys = st.multiselect(
                    "비교할 알고리즘 선택",
                    options=list(avail_algos.keys()),
                    default=default_sel,
                    format_func=lambda k: avail_algos.get(k, k),
                    key="algo_compare_select",
                )

                # 8개 초과 선택 시 안내
                if len(selected_keys) > 8:
                    st.warning("8개 이하로 선택하면 더 읽기 쉽습니다.")
                    selected_keys = selected_keys[:8]

                if not selected_keys:
                    st.info("알고리즘을 선택해주세요.")
                else:
                    vhs_s = pd.to_numeric(df["vhs"], errors="coerce").fillna(50)
                    vhs_action = df.get("vhs_action", pd.Series(["보류"]*len(df)))

                    # ── 요약 지표 카드 ───────────────────────
                    st.markdown("---")
                    st.markdown("**📐 순위 상관관계 & 액션 일치율**")
                    st.caption("Spearman ρ가 높을수록 VHS 순위와 유사 · 일치율이 낮을수록 VHS가 추가 정보를 활용")

                    metrics = []
                    for k in selected_keys:
                        algo_s = pd.to_numeric(df[k], errors="coerce").fillna(50)
                        # Spearman 상관
                        rho, pval = spearmanr(algo_s, vhs_s)
                        rho = round(float(rho), 3) if not pd.isna(rho) else 0.0

                        # 액션 일치율: 단일 알고리즘으로 액션 추론 vs VHS 액션
                        def _infer_action(score):
                            if score >= 75: return "재배치 이동"
                            if score >= 55: return "할인 판매"
                            if score <= 30: return "폐기"
                            return "보류"

                        algo_action = algo_s.apply(_infer_action)
                        agree_rate  = round((algo_action == vhs_action).mean() * 100, 1)

                        # 평균 점수 차이 (VHS - algo)
                        avg_gap = round(float(vhs_s.mean() - algo_s.mean()), 1)

                        # 효율 향상률: VHS 분산 / algo 분산 비율
                        algo_std = float(algo_s.std())
                        vhs_std  = float(vhs_s.std())
                        spread_ratio = round(vhs_std / max(algo_std, 0.1), 2)

                        metrics.append({
                            "알고리즘":        avail_algos[k],
                            "평균점수":        round(float(algo_s.mean()), 1),
                            "VHS 평균":        round(float(vhs_s.mean()), 1),
                            "점수 갭(VHS−알고)": avg_gap,
                            "순위상관(ρ)":     rho,
                            "액션 일치율":     f"{agree_rate}%",
                            "분산 비율(VHS/알고)": spread_ratio,
                            "_key":            k,
                            "_rho":            rho,
                            "_agree":          agree_rate,
                        })

                    metrics_df = pd.DataFrame(metrics)

                    # 색상 카드로 핵심 지표 표시
                    cols = st.columns(len(selected_keys))
                    for ci, row in metrics_df.iterrows():
                        rho_v    = row["_rho"]
                        agree_v  = row["_agree"]
                        rho_color = "#1565c0" if rho_v >= 0.7 else ("#f9a825" if rho_v >= 0.4 else "#ef5350")
                        ag_color  = "#2e7d32" if agree_v >= 70 else ("#f9a825" if agree_v >= 50 else "#ef5350")
                        with cols[ci % len(cols)]:
                            st.markdown(
                                f'''<div style="border:1.5px solid #ddd;border-radius:10px;
                                            padding:10px 12px;margin:3px 0;background:#fafafa;">
                                  <div style="font-size:11px;font-weight:800;color:#555;margin-bottom:6px;
                                              white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                    {row["알고리즘"]}
                                  </div>
                                  <div style="display:flex;justify-content:space-between;margin:3px 0;">
                                    <span style="font-size:11px;color:#777;">순위상관 ρ</span>
                                    <span style="font-size:14px;font-weight:900;color:{rho_color};">{rho_v:.2f}</span>
                                  </div>
                                  <div style="display:flex;justify-content:space-between;margin:3px 0;">
                                    <span style="font-size:11px;color:#777;">액션 일치</span>
                                    <span style="font-size:14px;font-weight:900;color:{ag_color};">{agree_v:.0f}%</span>
                                  </div>
                                  <div style="display:flex;justify-content:space-between;margin:3px 0;">
                                    <span style="font-size:11px;color:#777;">평균점수</span>
                                    <span style="font-size:13px;font-weight:700;color:#333;">{row["평균점수"]}점</span>
                                  </div>
                                </div>''',
                                unsafe_allow_html=True,
                            )

                    # ── 점수 분포 비교 막대 차트 ─────────────
                    st.markdown("---")
                    st.markdown("**📈 평균 점수 비교 (알고리즘 vs VHS)**")
                    chart_data = pd.DataFrame({
                        "알고리즘 점수": [r["평균점수"] for r in metrics],
                        "VHS 점수":      [r["VHS 평균"] for r in metrics],
                    }, index=[avail_algos[k].split(" ",1)[-1] for k in selected_keys])
                    st.bar_chart(chart_data, height=260)

                    # ── Spearman ρ 시각화 ────────────────────
                    st.markdown("**🔗 순위 상관관계 (ρ 높을수록 VHS와 유사)**")
                    for row in metrics:
                        rho_v = row["_rho"]
                        pct   = max(0, min(100, (rho_v + 1) / 2 * 100))
                        color = "#1565c0" if rho_v >= 0.7 else ("#f9a825" if rho_v >= 0.4 else "#ef5350")
                        label = avail_algos[row["_key"]].split(" ",1)[-1]
                        st.markdown(
                            f'''<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                              <div style="width:160px;font-size:12px;font-weight:600;color:#444;
                                          white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{label}</div>
                              <div style="flex:1;background:#eee;border-radius:4px;height:14px;">
                                <div style="width:{pct:.1f}%;background:{color};height:100%;border-radius:4px;"></div>
                              </div>
                              <div style="width:44px;text-align:right;font-size:13px;
                                          font-weight:900;color:{color};">{rho_v:.2f}</div>
                            </div>''',
                            unsafe_allow_html=True,
                        )

                    # ── 상품별 점수 비교 테이블 ──────────────
                    st.markdown("---")
                    st.markdown("**🔍 상품별 점수 비교 (상위 20개)**")
                    cmp_base = [c for c in ["product_name","source_store","vhs","vhs_action"] if c in df.columns]
                    cmp_cols = [k for k in selected_keys if k in df.columns]
                    cmp_df   = df[cmp_base + cmp_cols].head(20).copy()
                    rename_m = {k: avail_algos[k].split(" ",1)[-1][:12] for k in cmp_cols}
                    cmp_df   = cmp_df.rename(columns=rename_m)

                    # VHS 대비 갭 하이라이트
                    if "vhs" in cmp_df.columns:
                        for k in selected_keys:
                            short = avail_algos[k].split(" ",1)[-1][:12]
                            if short in cmp_df.columns:
                                gap_col = f"갭({short[:6]})"
                                cmp_df[gap_col] = (
                                    pd.to_numeric(cmp_df["vhs"], errors="coerce") -
                                    pd.to_numeric(cmp_df[short], errors="coerce")
                                ).round(1)

                    st.dataframe(cmp_df.round(1), width="stretch")

                    # ── 해석 가이드 ──────────────────────────
                    with st.expander("📖 지표 해석 방법", expanded=False):
                        st.markdown("""
| 지표 | 해석 |
|------|------|
| **순위 상관 ρ** | 1에 가까울수록 해당 알고리즘 순위 = VHS 순위. 낮으면 VHS가 다른 정보 반영 |
| **액션 일치율** | 개별 알고리즘 기준 추천 액션이 VHS와 얼마나 같은지 (낮으면 VHS가 더 정교) |
| **평균점수 갭** | VHS − 알고리즘. 양수면 VHS가 더 높게 평가 (통합 효과) |
| **분산 비율** | VHS 분산 / 알고 분산. 1보다 크면 VHS가 더 넓은 분포 (변별력 ↑) |
                        """)

    #  탭 3: 8구성요소 분석    #  탭 3: 8구성요소 분석
    with t3:
        st.subheader("🏗️ Varo Hybrid Score — 8개 구성요소 구조")
        _G8 = {
            "A. 재고 위험 (22%)":   (["disposal_risk_score","turnover_score","abc_score","aging_score"],"#e57373"),
            "B. 판매 가능성 (18%)": (["demand_forecast_score","trend_score","newsvendor_score"],"#ab47bc"),
            "C. 점포 적합도 (18%)": (["match_score","service_level_score","priority_queue_score","queue_capacity_score"],"#42a5f5"),
            "D. 재고 균형 (12%)":   (["category_balance_score","safety_stock_score","transport_lp_score"],"#26a69a"),
            "E. 폐기 회피 (8%)":    (["disposal_avoidance_score","discount_sensitivity_score"],"#ffa726"),
            "F. 실행 가능성 (8%)":  (["bottleneck_score","store_capacity_score","lp_allocation_score"],"#66bb6a"),
            "G. 최적화 모델 (8%)":  (["multiobjective_score","topsis_score","pareto_score","assignment_score"],"#8d6e63"),
            "H. 기존 연동 (6%)":    (["heuristic_score","greedy_score","eoq_score"],"#78909c"),
        }
        _PENALTY = ["relocation_failure_score","substitute_conflict_score"]

        for grp, (cols, color) in _G8.items():
            avail = [c for c in cols if c in df.columns]
            avg   = sum(float(df[c].mean()) for c in avail) / max(len(avail),1) if avail else 50
            chips = " ".join(
                f'<span style="background:#f0f0f0;border-radius:5px;padding:2px 8px;'
                f'font-size:11px;margin:2px;display:inline-block;">'
                f'{c.replace("_score","")}: {float(df[c].mean()):.1f}</span>'
                for c in avail
            ) if avail else "<em>데이터 없음</em>"
            st.markdown(
                f'<div style="border-left:4px solid {color};padding:7px 14px;'
                f'margin:4px 0;border-radius:0 10px 10px 0;background:#fafafa;">'
                f'<strong style="font-size:13px;">{grp}</strong> 평균 {avg:.1f}점'
                f'<div style="margin-top:3px;">{chips}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("**⛔ 실패 위험 패널티 (차감)**")
        for pc in _PENALTY:
            if pc in df.columns:
                st.markdown(
                    f'<div style="border-left:3px solid #e57373;padding:4px 12px;'
                    f'margin:2px 0;border-radius:0 6px 6px 0;background:#fff3f3;font-size:12px;">'
                    f'{pc.replace("_score","")} 평균 {float(df[pc].mean()):.1f}점 (차감)</div>',
                    unsafe_allow_html=True,
                )

        new32 = [c for c in [
            "trend_direction","aging_grade","priority_queue_rank",
            "relocation_failure_grade","substitute_conflict_score",
            "category_balance_score","store_capacity_score","queue_capacity_score",
            "bottleneck_reason","discount_sensitivity_score","disposal_avoidance_profit",
            "newsvendor_score","pareto_grade","topsis_rank",
            "multiobjective_rank","assignment_action","sensitivity_score",
            "dominant_factor","transport_lp_score","service_level_gap",
        ] if c in df.columns]
        if new32:
            with st.expander(f"📋 전체 알고리즘 결과 상세 ({len(new32)}개 컬럼)", expanded=False):
                base = [c for c in ["product_name","source_store","vhs","vhs_action"] if c in df.columns]
                st.dataframe(df[base + new32].head(20), width="stretch")

        contrib_cols = {
            c.replace("vhs_contrib_","").replace("_score",""): c
            for c in df.columns if c.startswith("vhs_contrib_")
        }

        if contrib_cols:
            # 전체 평균 기여 파이형 바
            avg_contrib_vals = {
                k: float(df[v].mean()) for k, v in contrib_cols.items()
            }
            total_contrib = sum(avg_contrib_vals.values())
            if total_contrib > 0:
                st.markdown("**전체 평균 VHS 구성 (기여도 %)**")
                color_map = {
                    "disposal_risk": "#e57373",
                    "turnover":      "#ec407a",
                    "demand_forecast":"#ab47bc",
                    "heuristic":     "#42a5f5",
                    "safety_stock":  "#26a69a",
                    "match":         "#66bb6a",
                    "abc":           "#ffa726",
                    "greedy":        "#8d6e63",
                    "eoq":           "#78909c",
                    "network_cost":  "#b0bec5",
                }
                bar_html = '<div style="display:flex;height:28px;border-radius:8px;overflow:hidden;margin-bottom:8px;">'
                legend_html = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;">'
                for k, v in sorted(avg_contrib_vals.items(), key=lambda x: -x[1]):
                    pct = v / total_contrib * 100
                    if pct < 0.5: continue
                    col_c = color_map.get(k, "#aaa")
                    bar_html += (
                        f'<div style="width:{pct:.1f}%;background:{col_c};'
                        f'display:flex;align-items:center;justify-content:center;">'
                        f'<span style="font-size:10px;color:#fff;font-weight:700;'
                        f'white-space:nowrap;overflow:hidden;">'
                        f'{pct:.0f}%</span></div>'
                    )
                    legend_html += (
                        f'<span style="background:{col_c};color:#fff;border-radius:6px;'
                        f'padding:2px 8px;font-size:11px;font-weight:700;">'
                        f'{k} {v:.1f}pt</span>'
                    )
                bar_html += '</div>'
                legend_html += '</div>'
                st.markdown(bar_html + legend_html, unsafe_allow_html=True)

            # 상품별 기여 상세 (상위 20)
            st.markdown("**상품별 컴포넌트 기여 점수 (상위 20)**")
            base_cols = [c for c in ["product_name","source_store","vhs","vhs_action"] if c in df.columns]
            contrib_list = list(contrib_cols.values())
            detail = df[base_cols + contrib_list].head(20).copy()
            rename = {v: k for k, v in contrib_cols.items()}
            detail = detail.rename(columns=rename)
            st.dataframe(detail.round(2), width="stretch")

        else:
            st.info("기여 점수 컬럼이 없습니다.")

    # ══════════════════════════════════════════════════════
    #  탭 4: 가중치 & 상황 감지
    with t4:
        # 가중치 및 상황 감지 — 독립 import로 실패 방지
        try:
            from varo_hybrid_score import _BASE_WEIGHTS as _BW, _SITUATION_MODS as _SM
        except Exception:
            _BW  = {}
            _SM  = {}

        # 26개 컴포넌트 역할·색상 매핑
        _RC = {
            "disposal_risk_score":          ("#e57373", "A.재고위험"),
            "turnover_score":               ("#ec407a", "A.재고위험"),
            "abc_score":                    ("#f06292", "A.재고위험"),
            "aging_score":                  ("#ce93d8", "A.재고위험"),
            "demand_forecast_score":        ("#ab47bc", "B.판매가능"),
            "trend_score":                  ("#7e57c2", "B.판매가능"),
            "newsvendor_score":             ("#5c6bc0", "B.판매가능"),
            "match_score":                  ("#42a5f5", "C.점포적합"),
            "service_level_score":          ("#26c6da", "C.점포적합"),
            "priority_queue_score":         ("#26a69a", "C.점포적합"),
            "queue_capacity_score":         ("#66bb6a", "C.점포적합"),
            "category_balance_score":       ("#9ccc65", "D.재고균형"),
            "safety_stock_score":           ("#d4e157", "D.재고균형"),
            "transport_lp_score":           ("#ffca28", "D.재고균형"),
            "disposal_avoidance_score":     ("#ffa726", "E.폐기회피"),
            "discount_sensitivity_score":   ("#ff7043", "E.폐기회피"),
            "bottleneck_score":             ("#8d6e63", "F.실행가능"),
            "store_capacity_score":         ("#78909c", "F.실행가능"),
            "lp_allocation_score":          ("#90a4ae", "F.실행가능"),
            "multiobjective_score":         ("#546e7a", "G.최적화"),
            "topsis_score":                 ("#607d8b", "G.최적화"),
            "pareto_score":                 ("#455a64", "G.최적화"),
            "assignment_score":             ("#37474f", "G.최적화"),
            "heuristic_score":              ("#b0bec5", "H.기존연동"),
            "greedy_score":                 ("#cfd8dc", "H.기존연동"),
            "eoq_score":                    ("#eceff1", "H.기존연동"),
        }

        col_w, col_s = st.columns([1, 1])

        with col_w:
            st.subheader("⚖️ VHS 가중치 구성")
            if _BW:
                rows = []
                for k, v in _BW.items():
                    color, role = _RC.get(k, ("#aaa", "기타"))
                    rows.append({
                        "컴포넌트": k.replace("_score",""),
                        "역할": role,
                        "가중치": f"{v*100:.0f}%",
                        "최대기여": f"{v*100:.1f}점",
                    })
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

                st.markdown("**역할별 비중**")
                from collections import defaultdict as _dd2
                _rs = _dd2(float)
                for k, v in _BW.items():
                    _rs[_RC.get(k, ("#","기타"))[1]] += v
                _role_colors = {
                    "A.재고위험":"#ef5350","B.판매가능":"#ab47bc",
                    "C.점포적합":"#42a5f5","D.재고균형":"#26a69a",
                    "E.폐기회피":"#ffa726","F.실행가능":"#8d6e63",
                    "G.최적화":"#546e7a","H.기존연동":"#b0bec5",
                }
                for role, pct in sorted(_rs.items()):
                    rc = _role_colors.get(role, "#aaa")
                    st.markdown(
                        f'<div style="margin:3px 0;">'
                        f'<span style="font-size:12px;font-weight:700;">{role}</span> '
                        f'<span style="font-size:12px;color:#666;">{pct*100:.0f}%</span>'
                        f'<div style="background:#eee;border-radius:3px;height:7px;margin-top:2px;">'
                        f'<div style="background:{rc};width:{pct*100:.1f}%;height:100%;border-radius:3px;"></div>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.info("가중치 데이터를 불러오는 중입니다...")

        with col_s:
            st.subheader("🌡 상황 감지 현황")
            _sit_map = {
                "sit_EXPIRY_URGENT":  ("⏰", "유통기한 임박",  "#e57373"),
                "sit_FROZEN_EXCESS":  ("❄️", "냉동·냉장 과잉", "#42a5f5"),
                "sit_HIGH_COST":      ("💸", "이동비용 높음",  "#ff7043"),
                "sit_DEMAND_SURGE":   ("📈", "수요 급증",      "#66bb6a"),
                "sit_DEAD_STOCK":     ("💀", "악성재고",       "#ec407a"),
                "sit_REORDER_CRISIS": ("🚨", "재주문 위기",    "#ab47bc"),
            }
            for col_key, (icon, label, color) in _sit_map.items():
                cnt = int(df[col_key].sum()) if col_key in df.columns else 0
                pct = cnt / max(len(df), 1) * 100
                st.markdown(
                    f'<div style="border-left:4px solid {color};padding:7px 12px;'
                    f'margin:5px 0;border-radius:0 8px 8px 0;background:#fafafa;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                    f'<span style="font-weight:700;font-size:13px;">{icon} {label}</span>'
                    f'<span style="color:{color};font-weight:800;font-size:13px;">{cnt}건 ({pct:.0f}%)</span>'
                    f'</div>'
                    f'<div style="background:#eee;border-radius:3px;height:5px;margin-top:5px;">'
                    f'<div style="background:{color};width:{min(pct,100):.1f}%;height:100%;border-radius:3px;"></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            if _SM:
                st.markdown("---")
                st.markdown("**상황 감지 가중치 배율**")
                for sit, mods in _SM.items():
                    with st.expander(f"⚡ {sit}", expanded=False):
                        md = pd.DataFrame([
                            {"컴포넌트": k.replace("_score",""), "배율": f"×{v:.1f}"}
                            for k, v in mods.items()
                        ])
                        st.dataframe(md, hide_index=True, width="stretch")

    # ── 탭 5: 컴포넌트 기여 ────────────────────────────────
    with t5:
        st.subheader("🔬 VHS 컴포넌트 기여 분석")
        contrib_cols_t5 = {
            c.replace("vhs_contrib_","").replace("_score",""): c
            for c in df.columns if c.startswith("vhs_contrib_")
        }
        if contrib_cols_t5:
            avg_c = {k: float(df[v].mean()) for k, v in contrib_cols_t5.items()}
            total_c = sum(avg_c.values())
            if total_c > 0:
                st.markdown("**전체 평균 VHS 구성**")
                bar_html = '<div style="display:flex;height:24px;border-radius:6px;overflow:hidden;margin-bottom:8px;">'
                leg_html = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;">'
                _CC = ["#ef5350","#ab47bc","#42a5f5","#26a69a","#ffa726","#66bb6a","#8d6e63","#78909c","#b0bec5"]
                for ci,(k,v) in enumerate(sorted(avg_c.items(), key=lambda x:-x[1])):
                    pct = v/total_c*100
                    if pct < 0.3: continue
                    col = _CC[ci % len(_CC)]
                    bar_html += f'<div style="width:{pct:.1f}%;background:{col};"></div>'
                    leg_html += f'<span style="background:{col};color:#fff;border-radius:4px;padding:2px 7px;font-size:10px;">{k} {v:.1f}pt</span>'
                st.markdown(bar_html+"</div>"+leg_html+"</div>", unsafe_allow_html=True)

            base_c = [c for c in ["product_name","source_store","vhs","vhs_action"] if c in df.columns]
            st.dataframe(df[base_c + list(contrib_cols_t5.values())].head(20).round(2), width="stretch")
        else:
            st.info("기여 점수 컬럼이 없습니다.")

    # ── 탭 6: 32개 알고리즘 전체 현황 ───────────────────────
    with t6:
        st.subheader("📋 Varo 32개 알고리즘 전체 현황")
        _ALL32 = [
            ("#1",  "ABC 분석",           "abc_score",                   "✅"),
            ("#2",  "재고 회전율",         "turnover_score",              "✅"),
            ("#3",  "폐기 위험도",         "disposal_risk_score",         "✅"),
            ("#4",  "Safety Stock/ROP",    "safety_stock_score",          "✅"),
            ("#5",  "EOQ",                "eoq_score",                   "✅"),
            ("#6",  "수요 예측",           "demand_forecast_score",       "✅"),
            ("#7",  "점포 클러스터링",     "source_cluster",              "✅"),
            ("#8",  "점포-상품 매칭",      "match_score",                 "✅"),
            ("#9",  "최소비용 네트워크",   "network_cost_score",          "✅"),
            ("#10", "What-if 시뮬레이션",  None,                          "✅"),
            ("#11", "재고 노후화 지수",    "aging_score",                 "✅"),
            ("#12", "판매 추세 변화율",    "trend_score",                 "✅"),
            ("#13", "대체 상품 충돌",      "substitute_conflict_score",   "✅"),
            ("#14", "카테고리 균형",       "category_balance_score",      "✅"),
            ("#15", "점포 처리 능력",      "store_capacity_score",        "✅"),
            ("#16", "재배치 실패 위험",    "relocation_failure_score",    "✅"),
            ("#17", "할인 민감도",         "discount_sensitivity_score",  "✅"),
            ("#18", "폐기 회피 이익",      "disposal_avoidance_score",    "✅"),
            ("#19", "재고 이동 우선순위큐","priority_queue_score",        "✅"),
            ("#20", "다목적 의사결정",     "multiobjective_score",        "✅"),
            ("#21", "선형/정수계획법",     "lp_allocation_score",         "✅"),
            ("#22", "수송 문제 LP",        "transport_lp_score",          "✅"),
            ("#23", "할당 문제",           "assignment_score",            "✅"),
            ("#24", "TOPSIS",             "topsis_score",                "✅"),
            ("#25", "서비스 수준 재고관리","service_level_score",         "✅"),
            ("#26", "Newsvendor Model",   "newsvendor_score",            "✅"),
            ("#27", "대기행렬 이론",       "queue_capacity_score",        "✅"),
            ("#28", "시뮬레이션 What-if",  None,                          "✅"),
            ("#29", "민감도 분석",         "sensitivity_score",           "✅"),
            ("#30", "병목 분석",           "bottleneck_score",            "✅"),
            ("#31", "Pareto 분석",         "pareto_score",                "✅"),
            ("#32", "Multi-objective",    "multiobjective_score",        "✅"),
        ]

        rows = []
        for num, name, col, status in _ALL32:
            avg_val = f"{float(df[col].mean()):.1f}점" if (col and col in df.columns) else "연동됨"
            active  = "✅ 활성" if (col and col in df.columns) else "🔗 연동"
            rows.append({"번호": num, "알고리즘": name, "평균값": avg_val, "상태": active})

        status_df = pd.DataFrame(rows)
        active_cnt = sum(1 for r in rows if "활성" in r["상태"])
        st.caption(f"전체 {len(_ALL32)}개 · 데이터 연동 {active_cnt}개")
        st.dataframe(status_df, width="stretch", hide_index=True)


# =========================
# 라우터
# =========================
def _show_demo_page():
    """데모 모드 — 샘플 데이터 선택 후 바로 시연."""
    _back_to_dashboard()
    st.header("🎮 데모 모드")
    st.caption("엑셀 없이 내장 샘플 데이터로 Varo를 바로 시연합니다.")

    try:
        from demo_data import DEMO_SCENARIOS, get_demo_sheets, scenario_description
    except ImportError:
        st.error("demo_data.py를 찾을 수 없습니다.")
        return

    selected = st.selectbox("시나리오 선택", list(DEMO_SCENARIOS.keys()), key="demo_scenario_sel")
    scenario_key = DEMO_SCENARIOS[selected]
    desc = scenario_description(scenario_key)
    if desc:
        st.info(f"📌 {desc}")

    if st.button("🚀 이 시나리오로 분석 시작", key="demo_run_btn"):
        with st.spinner("샘플 데이터 생성 중..."):
            sheets = get_demo_sheets(scenario_key)
        st.session_state["demo_sheets"]     = sheets
        st.session_state["demo_active"]     = True
        st.session_state["demo_scenario"]   = selected
        st.success(f"✅ '{selected}' 샘플 준비 완료 — 엑셀 업로드 화면에서 분석 버튼을 누르세요.")
        st.info("💡 또는 엑셀 업로드 화면으로 돌아가 '데모 데이터 사용' 버튼을 클릭하세요.")


def _show_validator_page(sheets: dict = None):
    """샘플 엑셀 검증기 페이지."""
    _back_to_dashboard()
    st.header("🔍 엑셀 데이터 검증")
    st.caption("업로드된 엑셀이 Varo 분석에 적합한지 자동으로 확인합니다.")

    try:
        from sample_validator import validate_excel, render_validation_result
    except ImportError:
        st.error("sample_validator.py를 찾을 수 없습니다.")
        return

    if sheets is None:
        st.info("분석 후 자동으로 검증 결과가 표시됩니다.")
        return

    r = validate_excel(sheets)
    render_validation_result(r)


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
        st.session_state.excel_dashboard_page = "movement"
        st.rerun()

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

    elif page == "algorithms":
        try:
            _show_algorithms_page(
                final_recommendations=final_recommendations,
                inventory=inventory,
            )
        except Exception as _e:
            st.error("📊 분석 화면을 불러오는 중 문제가 발생했습니다.")
            with st.expander("🔧 상세 오류 (관리자용)", expanded=False):
                import traceback as _tb
                st.code(_tb.format_exc())

    elif page == "network":
        _show_network_page()

    elif page == "batch":
        _show_batch_page(final_recommendations)

    elif page == "effect":
        _show_effect_page(final_recommendations)

    elif page == "demo":
        _show_demo_page()

    elif page == "validator":
        _show_validator_page(sheets=st.session_state.get("_uploaded_sheets"))

    elif page == "guide":
        _show_guide_page(final_recommendations)

    elif page == "whatif":
        _show_whatif_page(final_recommendations)

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