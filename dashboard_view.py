import pandas as pd
import streamlit as st
from numbers import Number


def _safe_value(row, key, default="-"):
    try:
        value = row.get(key, default)
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default


def _format_money(value):
    if isinstance(value, Number):
        return f"{value:,.0f}원"

    try:
        return f"{float(value):,.0f}원"
    except Exception:
        return str(value)


def _get_best_row(final_recommendations):
    if final_recommendations is None or final_recommendations.empty:
        return None

    df = final_recommendations.copy()

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


def _make_metric_cards(best_row):
    product_name = _safe_value(best_row, "product_name")
    source_store = _safe_value(best_row, "source_store")
    target_store = _safe_value(best_row, "target_store")
    suggested_qty = _safe_value(best_row, "suggested_qty", 0)
    final_recommendation = _safe_value(best_row, "final_recommendation")
    estimated_cost = _safe_value(best_row, "estimated_cost", 0)
    heuristic_score = _safe_value(best_row, "heuristic_score", "-")
    heuristic_grade = _safe_value(best_row, "heuristic_grade", "-")
    reason = _safe_value(best_row, "reason", "-")

    st.markdown(
        f"""
        <div style="
            padding: 28px 30px;
            border-radius: 26px;
            border: 2px solid #ffd43b;
            background: linear-gradient(135deg, #fffbea 0%, #fff3bf 55%, #ffffff 100%);
            box-shadow: 0 10px 28px rgba(0,0,0,0.07);
            margin-bottom: 18px;
        ">
            <div style="font-size: 15px; color: #666; font-weight: 800; margin-bottom: 8px;">
                최적 의사결정 결과
            </div>
            <div style="font-size: 34px; font-weight: 950; color: #222; margin-bottom: 8px;">
                {product_name} · {source_store} → {target_store}
            </div>
            <div style="font-size: 18px; color: #333; line-height: 1.65;">
                추천 전략: <b>{final_recommendation}</b><br>
                추천 이유: {reason}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("추천 수량", f"{suggested_qty}개")
    c2.metric("예상 비용", _format_money(estimated_cost))
    c3.metric("휴리스틱 점수", f"{heuristic_score}점")
    c4.metric("추천 등급", str(heuristic_grade))


def _show_decision_flow():
    st.markdown(
        """
        <div style="
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 12px;
            margin: 18px 0 8px 0;
        ">
            <div style="padding:16px;border-radius:18px;background:#ffffff;border:1px solid #eee;text-align:center;">
                <div style="font-size:24px;">📥</div><b>1. 데이터 입력</b><br><span style="font-size:13px;color:#666;">엑셀 업로드</span>
            </div>
            <div style="padding:16px;border-radius:18px;background:#ffffff;border:1px solid #eee;text-align:center;">
                <div style="font-size:24px;">🔎</div><b>2. 후보 생성</b><br><span style="font-size:13px;color:#666;">재배치/프로모션</span>
            </div>
            <div style="padding:16px;border-radius:18px;background:#ffffff;border:1px solid #eee;text-align:center;">
                <div style="font-size:24px;">🧠</div><b>3. 휴리스틱</b><br><span style="font-size:13px;color:#666;">후보 점수화</span>
            </div>
            <div style="padding:16px;border-radius:18px;background:#ffffff;border:1px solid #eee;text-align:center;">
                <div style="font-size:24px;">⚡</div><b>4. Greedy</b><br><span style="font-size:13px;color:#666;">최고 점수 선택</span>
            </div>
            <div style="padding:16px;border-radius:18px;background:#ffffff;border:1px solid #eee;text-align:center;">
                <div style="font-size:24px;">🚚</div><b>5. 실행 확인</b><br><span style="font-size:13px;color:#666;">지도/Inventory</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _show_score_tab(final_recommendations):
    st.subheader("🧠 점수 기반 후보 순위")

    if final_recommendations is None or final_recommendations.empty:
        st.info("표시할 추천 후보가 없습니다.")
        return

    view_cols = [
        "greedy_rank", "product_name", "source_store", "target_store",
        "suggested_qty", "estimated_cost", "final_recommendation",
        "heuristic_score", "heuristic_grade", "greedy_reason",
    ]

    rename_map = {
        "greedy_rank": "Greedy 순위",
        "product_name": "상품명",
        "source_store": "보내는 점포",
        "target_store": "받는 점포",
        "suggested_qty": "추천 수량",
        "estimated_cost": "예상 비용",
        "final_recommendation": "추천 전략",
        "heuristic_score": "휴리스틱 점수",
        "heuristic_grade": "휴리스틱 등급",
        "greedy_reason": "Greedy 선택 근거",
    }

    visible_cols = [c for c in view_cols if c in final_recommendations.columns]
    score_view = final_recommendations[visible_cols].rename(columns=rename_map)

    st.dataframe(score_view, width="stretch")

    if "heuristic_score" in final_recommendations.columns:
        chart_df = final_recommendations.copy()
        chart_df["label"] = (
            chart_df["product_name"].astype(str)
            + " | "
            + chart_df["source_store"].astype(str)
            + "→"
            + chart_df["target_store"].astype(str)
        )
        chart_df["heuristic_score"] = pd.to_numeric(chart_df["heuristic_score"], errors="coerce")
        chart_df = chart_df.dropna(subset=["heuristic_score"]).head(10)

        if not chart_df.empty:
            st.write("상위 추천 후보 휴리스틱 점수")
            st.bar_chart(chart_df.set_index("label")["heuristic_score"])


def _show_graph_tab(final_recommendations, final_rec_summary, promotion_result, transfer_path_result):
    st.subheader("📊 그래프 요약")

    if final_rec_summary is not None and not final_rec_summary.empty:
        st.write("추천 유형별 건수")
        if "final_recommendation" in final_rec_summary.columns and "count" in final_rec_summary.columns:
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
            cost_df = cost_df.dropna(subset=["estimated_cost"]).sort_values("estimated_cost").head(10)

            if not cost_df.empty:
                st.write("예상 비용이 낮은 추천 후보 Top 10")
                st.bar_chart(cost_df.set_index("label")["estimated_cost"])

    if promotion_result is not None and not promotion_result.empty:
        st.write("프로모션 vs 재배치 비교 데이터")
        promo_cols = [
            "product_name", "source_store", "target_store",
            "transfer_cost", "promotion_net_cost", "final_decision",
        ]
        st.dataframe(
            promotion_result[[c for c in promo_cols if c in promotion_result.columns]],
            width="stretch",
        )

    if transfer_path_result is not None and not transfer_path_result.empty:
        if "recommended_path" in transfer_path_result.columns:
            st.write("이동 방식별 후보 수")
            path_summary = (
                transfer_path_result.groupby("recommended_path")
                .size()
                .reset_index(name="count")
            )
            st.bar_chart(path_summary.set_index("recommended_path")["count"])


def _show_explanation_tab():
    st.subheader("📘 설명")

    st.markdown(
        """
        ### 현재 화면을 보는 방법

        **최적 의사결정 결과**는 현재 추천 후보 중 가장 우선순위가 높은 결과입니다.  
        이 결과는 기존 악성재고 위험점수와는 별도로, 추천 후보를 평가하는 휴리스틱 점수와 Greedy 알고리즘을 이용해 선택됩니다.

        #### 1. 기존 위험점수
        상품이 악성재고인지 판단하는 점수입니다.  
        재고량, 판매량, 입고 후 경과일 등을 바탕으로 위험도를 판단합니다.

        #### 2. 휴리스틱 점수
        추천 후보를 평가하는 점수입니다.  
        예상 비용, 추천 수량, 추천 전략, 추천 이유를 반영해 후보별 우선순위를 계산합니다.

        #### 3. Greedy 알고리즘
        휴리스틱 점수가 가장 높은 후보를 현재 조건에서 가장 좋은 추천으로 선택합니다.

        #### 4. 강화학습 확장
        추천 후보를 State / Action / Reward 구조로 변환하여, 향후 더 많은 데이터를 학습해 상황별 추천 정책을 개선할 수 있습니다.
        """
    )


def _show_data_tab(final_recommendations, promotion_result, transfer_path_result, network_path_result):
    st.subheader("🧾 데이터 상세")

    with st.expander("최종 추천 후보 데이터", expanded=True):
        if final_recommendations is None or final_recommendations.empty:
            st.info("최종 추천 후보가 없습니다.")
        else:
            st.dataframe(final_recommendations, width="stretch")

    with st.expander("프로모션 비교 데이터"):
        if promotion_result is None or promotion_result.empty:
            st.info("프로모션 비교 데이터가 없습니다.")
        else:
            st.dataframe(promotion_result, width="stretch")

    with st.expander("직접 이동 vs DC 경유 데이터"):
        if transfer_path_result is None or transfer_path_result.empty:
            st.info("점포 간 이동 비교 데이터가 없습니다.")
        else:
            st.dataframe(transfer_path_result, width="stretch")

    with st.expander("다중 경로 데이터"):
        if network_path_result is None or network_path_result.empty:
            st.info("다중 경로 데이터가 없습니다.")
        else:
            st.dataframe(network_path_result, width="stretch")


def show_decision_dashboard(
    final_recommendations,
    final_rec_summary=None,
    promotion_result=None,
    transfer_path_result=None,
    network_path_result=None,
):
    st.markdown("---")
    st.header("📌 의사결정 대시보드")

    best_row = _get_best_row(final_recommendations)

    if best_row is None:
        st.info("대시보드에 표시할 최종 추천 결과가 없습니다.")
        return

    _make_metric_cards(best_row)
    _show_decision_flow()

    st.caption("아래 탭을 클릭하면 점수, 그래프, 설명, 상세 데이터를 각각 확인할 수 있습니다.")

    tab_score, tab_graph, tab_explain, tab_data = st.tabs(
        ["🧠 점수", "📊 그래프", "📘 설명", "🧾 상세 데이터"]
    )

    with tab_score:
        _show_score_tab(final_recommendations)

    with tab_graph:
        _show_graph_tab(final_recommendations, final_rec_summary, promotion_result, transfer_path_result)

    with tab_explain:
        _show_explanation_tab()

    with tab_data:
        _show_data_tab(final_recommendations, promotion_result, transfer_path_result, network_path_result)
