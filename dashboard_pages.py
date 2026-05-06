
from numbers import Number
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


def _safe_get(row, key, default="-"):
    try:
        value = row.get(key, default)
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default


def _safe_dataframe(df, **kwargs):
    """
    Streamlit/pyarrow가 object 컬럼 안에 숫자와 문자가 섞인 경우 오류를 낼 수 있어서,
    화면 표시용 데이터프레임은 문자열로 통일해서 안전하게 보여준다.
    """
    if df is None:
        st.info("표시할 데이터가 없습니다.")
        return

    try:
        display_df = df.copy()
        display_df = display_df.astype(str)
        st.dataframe(display_df, **kwargs)
    except Exception:
        st.dataframe(df.astype(str), **kwargs)


def _best_row(final_recommendations):
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


def _go(page_name):
    st.session_state.excel_dashboard_page = page_name
    st.rerun()


def _back_to_dashboard():
    if st.button("← 대시보드로 돌아가기", use_container_width=True):
        _go("dashboard")


def _apply_page_style():
    st.markdown(
        """
        <style>
            .dash-hero {
                padding: 30px 34px;
                border-radius: 30px;
                background:
                    radial-gradient(circle at top right, rgba(255, 212, 59, 0.35), transparent 32%),
                    linear-gradient(135deg, #fffbea 0%, #fff3bf 55%, #ffffff 100%);
                border: 2px solid #ffd43b;
                box-shadow: 0 12px 30px rgba(0,0,0,0.07);
                margin: 18px 0;
            }

            .dash-small-title {
                font-size: 14px;
                color: #666;
                font-weight: 800;
                margin-bottom: 8px;
            }

            .dash-main-title {
                font-size: 36px;
                font-weight: 950;
                letter-spacing: -0.7px;
                color: #222;
                margin-bottom: 10px;
            }

            .dash-desc {
                font-size: 17px;
                line-height: 1.65;
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
                font-size: 24px;
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
                padding: 20px;
                border-radius: 22px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                box-shadow: 0 8px 22px rgba(0,0,0,0.05);
                min-height: 150px;
                margin-bottom: 10px;
            }
            .dash-menu-title {
                font-size: 19px;
                font-weight: 900;
                margin-bottom: 8px;
            }

            .dash-menu-desc {
                color: #666;
                font-size: 14px;
                line-height: 1.55;
                min-height: 44px;
            }

            .dash-page-box {
                padding: 24px 28px;
                border-radius: 24px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                box-shadow: 0 8px 22px rgba(0,0,0,0.045);
                margin: 18px 0;
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
def _show_dashboard_home(final_recommendations, final_rec_summary):
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
    reason = _safe_get(best, "reason", "-")

    st.markdown(
        f"""
        <div class="dash-hero">
            <div class="dash-small-title">최적 의사결정 결과</div>
            <div class="dash-main-title">{product_name} · {source_store} → {target_store}</div>
            <div class="dash-desc">
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

    with st.expander("📈 추천 후보 더보기", expanded=False):
        st.caption("Greedy 순위 또는 휴리스틱 점수를 기준으로 실행 가치가 높은 후보를 최대 5개까지 보여줍니다.")

        top_candidates = final_recommendations.copy()

        if "greedy_rank" in top_candidates.columns:
            top_candidates["_rank"] = pd.to_numeric(top_candidates["greedy_rank"], errors="coerce")
            top_candidates = top_candidates.sort_values("_rank", na_position="last")
        elif "heuristic_score" in top_candidates.columns:
            top_candidates["_score"] = pd.to_numeric(top_candidates["heuristic_score"], errors="coerce")
            top_candidates = top_candidates.sort_values("_score", ascending=False, na_position="last")
        elif "estimated_cost" in top_candidates.columns:
            top_candidates["_cost"] = pd.to_numeric(top_candidates["estimated_cost"], errors="coerce")
            top_candidates = top_candidates.sort_values("_cost", na_position="last")

        top_candidates = top_candidates.head(5).reset_index(drop=True)

        if top_candidates.empty:
            st.info("표시할 추천 후보가 없습니다.")
        else:
            candidate_cols = [
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

            candidate_view = top_candidates[
                [c for c in candidate_cols if c in top_candidates.columns]
            ].rename(
                columns={
                    "greedy_rank": "순위",
                    "product_name": "상품명",
                    "source_store": "보내는 점포",
                    "target_store": "받는 점포",
                    "suggested_qty": "추천 수량",
                    "estimated_cost": "예상 비용",
                    "final_recommendation": "추천 전략",
                    "heuristic_score": "휴리스틱 점수",
                    "heuristic_grade": "추천 등급",
                }
            )

            _safe_dataframe(candidate_view, width="stretch")

            for i, candidate in top_candidates.iterrows():
                rank = _safe_get(candidate, "greedy_rank", i + 1)
                product = _safe_get(candidate, "product_name")
                source = _safe_get(candidate, "source_store")
                target = _safe_get(candidate, "target_store")
                qty = _safe_get(candidate, "suggested_qty", 0)
                score = _safe_get(candidate, "heuristic_score", "-")
                cost = _safe_get(candidate, "estimated_cost", 0)
                strategy = _safe_get(candidate, "final_recommendation", "-")
                grade = _safe_get(candidate, "heuristic_grade", "-")

                st.markdown(f"#### {rank}. {product}")
                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"**경로**  \n{source} → {target}")
                c2.write(f"**전략**  \n{strategy}")
                c3.write(f"**수량/비용**  \n{qty}개 / {_format_money(cost)}")
                c4.write(f"**점수/등급**  \n{score}점 / {grade}")

                if i < len(top_candidates) - 1:
                    st.divider()

    st.markdown("### 자세히 보기")
    row1_col1, row1_col2, row1_col3 = st.columns(3)

    with row1_col1:
        st.markdown(
            """
            <div class="dash-menu-card">
                <div class="dash-menu-title">🧠 점수 보기</div>
                <div class="dash-menu-desc">휴리스틱 점수, Greedy 순위, 선택 근거를 확인합니다.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("점수 페이지 열기", use_container_width=True, key="go_score"):
            _go("score")

    with row1_col2:
        st.markdown(
            """
            <div class="dash-menu-card">
                <div class="dash-menu-title">📊 그래프 보기</div>
                <div class="dash-menu-desc">추천 유형, 비용, 이동 방식, 프로모션 결과를 그래프로 봅니다.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("그래프 페이지 열기", use_container_width=True, key="go_graph"):
            _go("graph")

    with row1_col3:
        st.markdown(
            """
            <div class="dash-menu-card">
                <div class="dash-menu-title">🗺 지도 보기</div>
                <div class="dash-menu-desc">카카오맵에서 점포와 추천 경로를 확인합니다.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("지도 페이지 열기", use_container_width=True, key="go_map"):
            _go("map")

    row2_col1, row2_col2, row2_col3 = st.columns(3)

    with row2_col1:
        st.markdown(
            """
            <div class="dash-menu-card">
                <div class="dash-menu-title">🚚 Truck 시뮬레이션</div>
                <div class="dash-menu-desc">지도에서 경로를 클릭하고 여러 Truck 이동을 확인합니다.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Truck 페이지 열기", use_container_width=True, key="go_truck"):
            _go("truck")

    with row2_col2:
        st.markdown(
            """
            <div class="dash-menu-card">
                <div class="dash-menu-title">🤖 강화학습 비교</div>
                <div class="dash-menu-desc">Greedy 추천과 강화학습 정책 추천을 비교합니다.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("강화학습 페이지 열기", use_container_width=True, key="go_rl"):
            _go("rl")

    with row2_col3:
        st.markdown(
            """
            <div class="dash-menu-card">
                <div class="dash-menu-title">📘 설명/상세 데이터</div>
                <div class="dash-menu-desc">알고리즘 설명과 원본 상세 결과를 확인합니다.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        btn1, btn2 = st.columns(2)
        with btn1:
            if st.button("설명", use_container_width=True, key="go_explain"):
                _go("explain")
        with btn2:
            if st.button("데이터", use_container_width=True, key="go_data"):
                _go("data")


    st.markdown("---")
    st.markdown("### 분석 진행 흐름")

    st.markdown(
        """
        <div class="dash-step-grid">
            <div class="dash-step">
                <div class="dash-step-icon">📥</div>
                <div class="dash-step-title">1. 데이터 입력</div>
                <div class="dash-step-desc">엑셀 업로드</div>
            </div>
            <div class="dash-step">
                <div class="dash-step-icon">🔎</div>
                <div class="dash-step-title">2. 후보 생성</div>
                <div class="dash-step-desc">재배치/프로모션 비교</div>
            </div>
            <div class="dash-step">
                <div class="dash-step-icon">🧠</div>
                <div class="dash-step-title">3. 휴리스틱</div>
                <div class="dash-step-desc">후보 점수화</div>
            </div>
            <div class="dash-step">
                <div class="dash-step-icon">⚡</div>
                <div class="dash-step-title">4. Greedy</div>
                <div class="dash-step-desc">최고 점수 선택</div>
            </div>
            <div class="dash-step">
                <div class="dash-step-icon">🚚</div>
                <div class="dash-step-title">5. 실행 확인</div>
                <div class="dash-step-desc">지도/Inventory</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )




# =========================
# 개별 페이지
# =========================
def _show_score_page(final_recommendations):
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("🧠 점수 페이지")

    if final_recommendations is None or final_recommendations.empty:
        st.info("표시할 추천 후보가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

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
        "greedy_reason",
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

    score_view = final_recommendations[
        [c for c in view_cols if c in final_recommendations.columns]
    ].rename(columns=rename_map)

    _safe_dataframe(score_view, width="stretch")

    if "heuristic_score" in final_recommendations.columns:
        chart_df = final_recommendations.copy()
        chart_df["heuristic_score"] = pd.to_numeric(chart_df["heuristic_score"], errors="coerce")
        chart_df["label"] = (
            chart_df["product_name"].astype(str)
            + " | "
            + chart_df["source_store"].astype(str)
            + "→"
            + chart_df["target_store"].astype(str)
        )
        chart_df = chart_df.dropna(subset=["heuristic_score"]).head(10)

        if not chart_df.empty:
            st.subheader("상위 추천 후보 휴리스틱 점수")
            st.bar_chart(chart_df.set_index("label")["heuristic_score"])

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
            cost_df = cost_df.dropna(subset=["estimated_cost"]).sort_values("estimated_cost").head(10)

            if not cost_df.empty:
                st.subheader("예상 비용이 낮은 추천 후보 Top 10")
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


def _show_explain_page():
    _back_to_dashboard()
    st.markdown('<div class="dash-page-box">', unsafe_allow_html=True)
    st.header("📘 설명 페이지")

    st.markdown(
        """
        ## 화면 구성

        이 앱은 처음 보는 사람도 쉽게 이해할 수 있도록 **대시보드 중심 구조**로 구성되어 있습니다.  
        첫 화면에서는 최적 추천 결과만 간단히 보여주고, 점수·그래프·지도·Truck·강화학습·상세 데이터는 각각 별도 페이지로 분리했습니다.

        ## 알고리즘 구조

        ### 1. 기존 악성재고 위험점수
        상품이 악성재고인지 판단하는 점수입니다.  
        재고량, 판매량, 입고 후 경과일 등을 기준으로 위험도를 계산합니다.

        ### 2. 휴리스틱 점수
        추천 후보를 평가하는 점수입니다.  
        예상 비용, 추천 수량, 추천 전략, 추천 이유를 반영하여 후보별 우선순위를 계산합니다.

        ### 3. Greedy 알고리즘
        휴리스틱 점수가 가장 높은 후보를 현재 조건에서의 최적 추천으로 선택합니다.

        ### 4. 강화학습 확장
        추천 후보를 State / Action / Reward 구조로 변환하여 학습 데이터로 만들고,  
        학습된 정책과 Greedy 추천을 비교할 수 있게 했습니다.

        ### 5. 지도 기반 시뮬레이션
        선택된 경로를 카카오맵 위에서 확인하고, Truck 이동 및 Inventory 변화를 시각화합니다.
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
            st.markdown("</div>", unsafe_allow_html=True)
            return

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

        st.markdown("---")
        st.subheader("Greedy 추천 vs 강화학습 추천 비교")

        try:
            from rl_policy_helper import recommend_action_for_rl_log

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
                rc2.metric("RL 정책 매칭 수", f"{matched_count}개")

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
                        "rl_recommended_action": "강화학습 추천 Action",
                        "reward": "현재 Reward",
                        "expected_reward": "RL 기대 Reward",
                        "heuristic_score": "휴리스틱 점수",
                        "greedy_rank": "Greedy 순위",
                        "rl_match_status": "RL 매칭 상태",
                    }
                )

                _safe_dataframe(view, width="stretch")

                with st.expander("강화학습 정책 근거 보기"):
                    reason_cols = [
                        "product_name",
                        "source_store",
                        "target_store",
                        "state_key",
                        "policy_reason",
                    ]
                    reason_view = rl_compare_result[
                        [c for c in reason_cols if c in rl_compare_result.columns]
                    ].rename(
                        columns={
                            "product_name": "상품명",
                            "source_store": "보내는 점포",
                            "target_store": "받는 점포",
                            "state_key": "상태 Key",
                            "policy_reason": "정책 선택 근거",
                        }
                    )
                    _safe_dataframe(reason_view, width="stretch")

        except FileNotFoundError:
            st.warning("rl_policy_table.csv 파일을 찾지 못했습니다. 먼저 py train_rl_agent.py를 실행해 주세요.")
        except ImportError:
            st.warning("rl_policy_helper.py 파일을 찾지 못했습니다.")
        except Exception as e:
            st.warning(f"강화학습 정책 비교 중 오류가 발생했습니다: {e}")

    except ImportError:
        st.warning("rl_data_logger.py 파일을 찾지 못했습니다.")
    except Exception as e:
        st.warning(f"강화학습 데이터 생성 중 오류가 발생했습니다: {e}")

    st.markdown("</div>", unsafe_allow_html=True)


def _build_truck_scenarios(
    stores,
    products,
    inventory,
    final_recommendations,
    transfer_path_result,
    max_truck_routes,
):
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
    st.header("🚚 Truck 시뮬레이션 페이지")

    if not kakao_js_key:
        st.info("왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하면 Truck 시뮬레이션이 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if show_kakao_map_with_multi_trucks is None:
        st.warning("kakao_map_viewer.py에 show_kakao_map_with_multi_trucks 함수가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    col1, col2, col3 = st.columns(3)

    with col1:
        truck_speed = st.slider(
            "Truck 이동 배속",
            min_value=0.5,
            max_value=10.0,
            value=1.0,
            step=0.5,
            key="truck_page_speed",
        )

    with col2:
        max_truck_routes = st.slider(
            "지도에 표시할 추천 경로 후보 수",
            min_value=3,
            max_value=20,
            value=8,
            step=1,
            key="truck_page_max_routes",
        )

    with col3:
        default_selected_count = st.slider(
            "처음 자동 선택할 Truck 수",
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
        st.info("지도에 표시 가능한 Truck 경로가 없습니다.")
    else:
        st.info(
            "지도 위 색깔 경로선을 클릭하면 선택/해제됩니다. "
            "여러 경로를 선택한 뒤 지도 아래의 '선택 경로 Truck 재생' 버튼을 누르면 여러 Truck이 동시에 이동합니다."
        )

        show_kakao_map_with_multi_trucks(
            stores,
            routes,
            kakao_js_key,
            scenarios,
            speed_multiplier=truck_speed,
            default_selected_count=default_selected_count,
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
        _show_dashboard_home(final_recommendations, final_rec_summary)

    elif page == "score":
        _show_score_page(final_recommendations)

    elif page == "graph":
        _show_graph_page(
            final_recommendations,
            final_rec_summary,
            promotion_result,
            transfer_path_result,
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
