
import html as html_lib
import io
import warnings
from datetime import time
from numbers import Number

import pandas as pd
import streamlit as st

warnings.filterwarnings(
    "ignore",
    message=".*extension is not supported and will be removed.*",
)

warnings.filterwarnings(
    "ignore",
    message=".*Conditional Formatting extension is not supported.*",
)



from calculator import calculate_inventory_analysis
from discount_analyzer import analyze_discount_options
from excel_loader import load_excel_file
from route_analyzer import analyze_dc_retailer_routes
from cutline_analyzer import analyze_product_distance_cutline
from time_window_analyzer import analyze_trade_time_windows
from transfer_path_analyzer import analyze_direct_vs_dc_transfer
from promotion_analyzer import analyze_promotion_vs_transfer
from network_path_analyzer import analyze_multi_store_network_paths
from final_summary import build_final_recommendations
from dashboard_pages import show_dashboard_router

from kakao_map_viewer import show_kakao_map, show_kakao_map_with_highlights

try:
    from kakao_map_viewer import show_kakao_map_with_truck
except ImportError:
    show_kakao_map_with_truck = None

try:
    from kakao_map_viewer import show_kakao_map_with_multi_trucks
except ImportError:
    show_kakao_map_with_multi_trucks = None

try:
    from heuristic_optimizer import add_heuristic_scores, select_greedy_best_candidate
except ImportError:
    add_heuristic_scores = None
    select_greedy_best_candidate = None


# =========================
# 기본 설정
# =========================
st.set_page_config(
    page_title="Varo",
    page_icon="📦",
    layout="wide",
)


# =========================
# 전역 스타일
# =========================
def apply_global_style():
    st.markdown(
        """
        <style>
            .stApp {
                background: linear-gradient(180deg, #fffdf4 0%, #ffffff 42%, #f8f9fa 100%);
            }

            section[data-testid="stSidebar"] {
                background: linear-gradient(180deg, #fff8d6 0%, #ffffff 100%);
                border-right: 1px solid #f1e4a8;
            }

            .stButton > button {
                border-radius: 14px;
                border: 1px solid #ffd43b;
                background: linear-gradient(135deg, #fff3bf, #ffd43b);
                color: #222;
                font-weight: 800;
                box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            }

            .stButton > button:hover {
                border: 1px solid #fab005;
                background: linear-gradient(135deg, #ffe066, #fcc419);
                color: #111;
            }

            .main-hero {
                padding: 30px 36px;
                border-radius: 26px;
                background:
                    radial-gradient(circle at top left, rgba(255, 212, 59, 0.45), transparent 32%),
                    linear-gradient(135deg, #fff3bf 0%, #fff9db 45%, #ffffff 100%);
                border: 1px solid #f6e58d;
                box-shadow: 0 12px 34px rgba(0,0,0,0.07);
                margin-bottom: 20px;
            }

            .main-hero h1 {
                font-size: 42px;
                margin-bottom: 8px;
                color: #222;
                letter-spacing: -1px;
            }

            .main-hero p {
                font-size: 16px;
                color: #555;
                margin-bottom: 0;
                line-height: 1.55;
            }

            .hero-sub {
                max-width: 900px;
                margin-top: 10px;
            }

            .badge {
                display: inline-block;
                padding: 7px 11px;
                border-radius: 999px;
                background: #fff3bf;
                border: 1px solid #ffd43b;
                font-weight: 700;
                font-size: 12px;
                margin-right: 6px;
                margin-bottom: 6px;
            }

            .blue-badge {
                background: #e7f5ff;
                border: 1px solid #74c0fc;
            }

            .green-badge {
                background: #ebfbee;
                border: 1px solid #8ce99a;
            }

            .pink-badge {
                background: #fff0f6;
                border: 1px solid #faa2c1;
            }

            .mode-card {
                padding: 26px;
                border-radius: 28px;
                border: 1px solid #eee;
                background: #ffffff;
                box-shadow: 0 10px 28px rgba(0,0,0,0.055);
                min-height: 300px;
                margin-bottom: 12px;
            }

            .mode-card-yellow {
                background:
                    radial-gradient(circle at top right, rgba(255, 212, 59, 0.28), transparent 30%),
                    linear-gradient(135deg, #fffbea 0%, #fff3bf 100%);
                border: 1px solid #ffe066;
            }

            .mode-card-blue {
                background:
                    radial-gradient(circle at top right, rgba(116, 192, 252, 0.25), transparent 30%),
                    linear-gradient(135deg, #eef7ff 0%, #e7f5ff 100%);
                border: 1px solid #a5d8ff;
            }

            .mode-card h3 {
                font-size: 24px;
                margin-bottom: 12px;
            }

            .mode-card p {
                font-size: 14px;
                color: #444;
                line-height: 1.7;
            }

            .mode-card ul {
                margin-top: 12px;
                padding-left: 20px;
                color: #555;
                line-height: 1.8;
            }

            .mode-mini {
                margin-top: 16px;
                padding: 12px 14px;
                border-radius: 16px;
                background: rgba(255, 255, 255, 0.72);
                border: 1px solid rgba(255, 255, 255, 0.9);
                font-size: 14px;
                color: #444;
            }

            .workflow-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 16px;
                margin-top: 22px;
                margin-bottom: 20px;
            }

            .workflow-card {
                padding: 22px;
                border-radius: 24px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                box-shadow: 0 8px 22px rgba(0,0,0,0.045);
            }

            .workflow-number {
                width: 36px;
                height: 36px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                background: #ffd43b;
                font-weight: 900;
                margin-bottom: 12px;
            }

            .workflow-title {
                font-size: 18px;
                font-weight: 800;
                margin-bottom: 8px;
            }

            .workflow-text {
                color: #555;
                line-height: 1.6;
                font-size: 14px;
            }

            .mode-header {
                padding: 30px 36px;
                border-radius: 28px;
                background:
                    radial-gradient(circle at top left, rgba(255, 212, 59, 0.30), transparent 30%),
                    linear-gradient(135deg, #fff3bf 0%, #fff9db 55%, #ffffff 100%);
                border: 1px solid #f6e58d;
                box-shadow: 0 10px 26px rgba(0,0,0,0.055);
                margin-top: 18px;
                margin-bottom: 18px;
            }

            .mode-header h2 {
                font-size: 34px;
                margin-bottom: 8px;
                letter-spacing: -0.5px;
            }

            .mode-header p {
                font-size: 16px;
                color: #555;
                margin-bottom: 0;
                line-height: 1.55;
            }

            .feature-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 14px;
                margin-top: 16px;
                margin-bottom: 18px;
            }

            .feature-card {
                padding: 18px;
                border-radius: 20px;
                background: #ffffff;
                border: 1px solid #eeeeee;
                box-shadow: 0 6px 18px rgba(0,0,0,0.04);
            }

            .feature-icon {
                font-size: 25px;
                margin-bottom: 6px;
            }

            .feature-title {
                font-weight: 800;
                margin-bottom: 6px;
            }

            .feature-desc {
                color: #666;
                font-size: 13.5px;
                line-height: 1.55;
            }

            .section-card {
                padding: 24px 28px;
                border-radius: 22px;
                border: 1px solid #eeeeee;
                background: #ffffff;
                box-shadow: 0 6px 18px rgba(0,0,0,0.04);
                margin-top: 18px;
                margin-bottom: 18px;
            }

            .best-card {
                padding: 26px 30px;
                border-radius: 26px;
                background:
                    radial-gradient(circle at top right, rgba(255, 212, 59, 0.34), transparent 32%),
                    linear-gradient(135deg, #fffbea 0%, #fff3bf 48%, #ffffff 100%);
                border: 2px solid #ffd43b;
                box-shadow: 0 10px 28px rgba(0,0,0,0.07);
                margin-top: 16px;
                margin-bottom: 22px;
            }

            .best-title {
                font-size: 25px;
                font-weight: 900;
                margin-bottom: 14px;
                color: #222;
            }

            .best-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 14px;
                margin-top: 12px;
                margin-bottom: 16px;
            }

            .best-mini {
                padding: 14px;
                border-radius: 18px;
                background: rgba(255,255,255,0.78);
                border: 1px solid rgba(255,255,255,0.9);
            }

            .best-label {
                color: #666;
                font-size: 12px;
                margin-bottom: 5px;
            }

            .best-value {
                font-size: 18px;
                font-weight: 900;
                color: #222;
            }

            .best-reason {
                padding: 16px 18px;
                border-radius: 18px;
                background: rgba(255,255,255,0.84);
                border: 1px solid rgba(255,255,255,0.95);
                line-height: 1.7;
                color: #444;
            }

            .algorithm-box {
                padding: 18px 20px;
                border-radius: 20px;
                background: linear-gradient(135deg, #eef7ff, #ffffff);
                border: 1px solid #a5d8ff;
                margin-top: 14px;
                margin-bottom: 16px;
                line-height: 1.7;
                color: #333;
            }

            div[data-testid="stMetric"] {
                background: #ffffff;
                border: 1px solid #eeeeee;
                padding: 16px;
                border-radius: 18px;
                box-shadow: 0 4px 14px rgba(0,0,0,0.035);
            }

            .footer-note {
                text-align: center;
                color: #777;
                font-size: 12px;
                padding-top: 18px;
            }

            @media (max-width: 900px) {
                .workflow-grid {
                    grid-template-columns: 1fr;
                }

                .feature-grid {
                    grid-template-columns: 1fr 1fr;
                }

                .best-grid {
                    grid-template-columns: 1fr 1fr;
                }

                .main-hero h1 {
                    font-size: 40px;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_global_style()


# =========================
# 상태 초기화
# =========================
if "selected_mode" not in st.session_state:
    st.session_state.selected_mode = None

if "cart" not in st.session_state:
    st.session_state.cart = []


# =========================
# 공통 함수
# =========================
def escape_text(value):
    return html_lib.escape(str(value))


def format_money(value):
    if isinstance(value, Number):
        return f"{value:,.0f}원"

    try:
        numeric_value = float(value)
        return f"{numeric_value:,.0f}원"
    except Exception:
        return str(value)


def apply_heuristic_and_greedy(final_recommendations):
    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame(), None

    if add_heuristic_scores is None or select_greedy_best_candidate is None:
        temp = final_recommendations.copy()

        if "estimated_cost" in temp.columns:
            temp["_estimated_cost_numeric"] = pd.to_numeric(temp["estimated_cost"], errors="coerce")
            if temp["_estimated_cost_numeric"].notna().any():
                temp = temp.sort_values("_estimated_cost_numeric", ascending=True)

        temp = temp.reset_index(drop=True)
        temp["greedy_rank"] = temp.index + 1
        temp["is_greedy_selected"] = temp["greedy_rank"] == 1
        temp["heuristic_score"] = 0
        temp["heuristic_grade"] = "-"
        temp["greedy_reason"] = "휴리스틱 모듈이 없어 비용 기준으로 임시 선택"
        return temp, temp.iloc[0]

    scored = add_heuristic_scores(final_recommendations)
    greedy_best = select_greedy_best_candidate(scored)

    return scored, greedy_best


def render_best_recommendation(greedy_best_candidate):
    if greedy_best_candidate is None:
        return

    product_name = escape_text(greedy_best_candidate.get("product_name", "-"))
    source_store = escape_text(greedy_best_candidate.get("source_store", "-"))
    target_store = escape_text(greedy_best_candidate.get("target_store", "-"))
    suggested_qty = escape_text(greedy_best_candidate.get("suggested_qty", "-"))
    final_recommendation = escape_text(greedy_best_candidate.get("final_recommendation", "-"))
    estimated_cost = greedy_best_candidate.get("estimated_cost", "-")
    reason = escape_text(greedy_best_candidate.get("reason", "-"))

    heuristic_score = greedy_best_candidate.get("heuristic_score", "-")
    heuristic_grade = greedy_best_candidate.get("heuristic_grade", "-")

    html = (
        '<div class="best-card">'
        '<div class="best-title">✅ Greedy 기반 최적 추천 경로</div>'
        '<div class="best-grid">'
        '<div class="best-mini">'
        '<div class="best-label">상품명</div>'
        f'<div class="best-value">{product_name}</div>'
        "</div>"
        '<div class="best-mini">'
        '<div class="best-label">추천 경로</div>'
        f'<div class="best-value">{source_store} → {target_store}</div>'
        "</div>"
        '<div class="best-mini">'
        '<div class="best-label">추천 수량</div>'
        f'<div class="best-value">{suggested_qty}개</div>'
        "</div>"
        '<div class="best-mini">'
        '<div class="best-label">예상 비용</div>'
        f'<div class="best-value">{format_money(estimated_cost)}</div>'
        "</div>"
        "</div>"
        '<div class="best-reason">'
        f"<b>추천 전략:</b> {final_recommendation}<br>"
        f"<b>휴리스틱 점수:</b> {heuristic_score}점 / {heuristic_grade}<br>"
        f"<b>추천 이유:</b> {reason}<br>"
        "<b>Greedy 선택 근거:</b> 휴리스틱 점수가 가장 높은 후보를 현재 조건의 최적 추천으로 선택했습니다."
        "</div>"
        "</div>"
    )

    st.markdown(html, unsafe_allow_html=True)


def show_algorithm_explanation():
    st.markdown(
        """
        <div class="algorithm-box">
            <b>알고리즘 구조</b><br>
            1. 기존 악성재고 위험점수는 상품이 악성재고인지 판단하는 데 사용합니다.<br>
            2. 추천 후보에는 별도의 휴리스틱 점수를 부여합니다. 이 점수는 비용, 이동 수량, 추천 전략, 추천 이유를 반영합니다.<br>
            3. Greedy 알고리즘은 현재 후보 중 휴리스틱 점수가 가장 높은 후보를 최적 추천 경로로 선택합니다.<br>
            4. 강화학습 준비 데이터는 State / Action / Reward 구조로 변환되어 정책 학습에 사용됩니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_matching_transfer_row(transfer_path_result, greedy_best_candidate):
    if transfer_path_result is None or transfer_path_result.empty or greedy_best_candidate is None:
        return None

    product_name = greedy_best_candidate.get("product_name", None)
    source_store = greedy_best_candidate.get("source_store", None)
    target_store = greedy_best_candidate.get("target_store", None)

    required_cols = {"product_name", "source_store", "target_store", "recommended_path"}
    if not required_cols.issubset(set(transfer_path_result.columns)):
        return None

    matched = transfer_path_result[
        (transfer_path_result["product_name"] == product_name)
        & (transfer_path_result["source_store"] == source_store)
        & (transfer_path_result["target_store"] == target_store)
        & (transfer_path_result["recommended_path"] != "이동 비추천")
    ]

    if not matched.empty:
        return matched.iloc[0]

    candidates = transfer_path_result[transfer_path_result["recommended_path"] != "이동 비추천"]

    if not candidates.empty:
        return candidates.iloc[0]

    return None


def show_main_hero():
    st.markdown(
        """
        <div class="main-hero">
            <h1>📦 Varo</h1>
            <p class="hero-sub">
                편의점 악성재고를 줄이기 위해 재고 상태, 이동 비용, 프로모션 효과, 최적 경로를 함께 분석하는
                <b>재고 공유 및 의사결정 지원 시스템</b>입니다.
            </p>
            <div style="margin-top:20px;">
                <span class="badge">악성재고 판단</span>
                <span class="badge">휴리스틱 점수</span>
                <span class="badge blue-badge">Greedy 선택</span>
                <span class="badge green-badge">강화학습 확장</span>
                <span class="badge pink-badge">재고 이동</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_workflow():
    st.markdown(
        """
        <div class="workflow-grid">
            <div class="workflow-card">
                <div class="workflow-number">1</div>
                <div class="workflow-title">데이터 입력</div>
                <div class="workflow-text">
                    단일 상품을 직접 입력하거나, 여러 점포의 재고·상품·경로 데이터를 엑셀로 업로드합니다.
                </div>
            </div>
            <div class="workflow-card">
                <div class="workflow-number">2</div>
                <div class="workflow-title">후보 평가</div>
                <div class="workflow-text">
                    기존 위험점수는 악성재고를 판단하고, 휴리스틱 점수는 추천 후보의 우선순위를 평가합니다.
                </div>
            </div>
            <div class="workflow-card">
                <div class="workflow-number">3</div>
                <div class="workflow-title">Greedy/RL 비교</div>
                <div class="workflow-text">
                    Greedy 추천과 강화학습 정책 추천을 비교하고, 지도에서 이동수단 흐름과 재고 변화를 확인합니다.
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_mode_header(title, description, badges=None):
    badge_html = ""

    if badges:
        for badge in badges:
            badge_html += f'<span class="badge">{escape_text(badge)}</span>'

    html = (
        '<div class="mode-header">'
        f"<h2>{escape_text(title)}</h2>"
        f"<p>{escape_text(description)}</p>"
        f'<div style="margin-top:14px;">{badge_html}</div>'
        "</div>"
    )

    st.markdown(html, unsafe_allow_html=True)


def show_back_button():
    if st.button("← 방식 선택 화면으로 돌아가기"):
        st.session_state.selected_mode = None
        st.rerun()


def show_excel_feature_cards():
    st.markdown(
        """
        <div class="feature-grid">
            <div class="feature-card">
                <div class="feature-icon">🧠</div>
                <div class="feature-title">휴리스틱 점수</div>
                <div class="feature-desc">비용, 이동 수량, 전략 유형, 추천 이유를 반영해 후보를 점수화합니다.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">⚡</div>
                <div class="feature-title">Greedy 선택</div>
                <div class="feature-desc">현재 조건에서 휴리스틱 점수가 가장 높은 후보를 최적 경로로 선택합니다.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🤖</div>
                <div class="feature-title">강화학습 정책</div>
                <div class="feature-desc">State/Action/Reward 데이터를 만들고 학습된 정책과 추천 결과를 비교합니다.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🚚</div>
                <div class="feature-title">다중 이동수단</div>
                <div class="feature-desc">지도에서 경로를 클릭해 선택하고 여러 Truck을 동시에 이동시킵니다.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================
# 첫 화면
# =========================
def show_mode_selector():
    show_main_hero()

    st.markdown("### 사용할 방식을 선택하세요")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
            <div class="mode-card mode-card-yellow">
                <h3>🧮 개별 입력 계산</h3>
                <p>
                점포명, 상품명, 재고 수량, 판매량, 할인율, 이동 가능 여부를 직접 입력해서
                악성재고 여부와 처리 전략을 빠르게 계산합니다.
                </p>
                <p><b>추천 상황</b></p>
                <ul>
                    <li>단일 상품을 빠르게 테스트할 때</li>
                    <li>계산 원리를 설명할 때</li>
                    <li>발표에서 기본 구조를 시연할 때</li>
                </ul>
                <div class="mode-mini">
                    현재 점수제도는 악성재고 위험을 판단하는 데 사용됩니다.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("🧮 개별 입력 계산 시작", width="stretch", type="primary"):
            st.session_state.selected_mode = "single"
            st.rerun()

    with col2:
        st.markdown(
            """
            <div class="mode-card mode-card-blue">
                <h3>📊 엑셀 기반 최적 경로 추천</h3>
                <p>
                여러 점포, 상품, 재고, 경로 데이터를 기반으로
                <b>휴리스틱 점수, Greedy 알고리즘, 강화학습 정책 비교</b>를 적용합니다.
                </p>
                <div style="margin-top:14px; margin-bottom:12px;">
                    <span class="badge blue-badge">엑셀 업로드</span>
                    <span class="badge">휴리스틱 점수</span>
                    <span class="badge">Greedy 알고리즘</span>
                    <span class="badge green-badge">강화학습 정책</span>
                    <span class="badge pink-badge">다중 이동수단</span>
                </div>
                <p><b>추천 상황</b></p>
                <ul>
                    <li>여러 점포를 동시에 분석할 때</li>
                    <li>최적 이동 경로를 추천받고 싶을 때</li>
                    <li>지도에서 경로를 클릭해 재고 이동과 Inventory 변화를 확인할 때</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("📊 엑셀 기반 분석 시작", width="stretch", type="primary"):
            st.session_state.selected_mode = "excel"
            st.rerun()

    show_workflow()


# =========================
# 1. 개별 입력 계산 모드
# =========================
def show_single_calculator():
    show_back_button()

    show_mode_header(
        "🧮 개별 입력 기반 악성재고 계산",
        "단일 점포와 단일 상품을 기준으로 악성재고 여부, 비용 비교, 최종 처리 전략을 계산합니다.",
        ["기존 점수제도 유지", "악성재고 위험 판단", "비용 비교", "계산식 확인"],
    )

    st.sidebar.header("개별 입력값 설정")

    store_name = st.sidebar.text_input("점포명", "강남점")
    product_name = st.sidebar.text_input("상품명", "삼각김밥")

    stock_qty = st.sidebar.number_input("현재 재고 수량", min_value=0, value=100)
    sales_30d = st.sidebar.number_input("최근 30일 판매량", min_value=0, value=5)
    inbound_days = st.sidebar.number_input("입고 후 지난 일수", min_value=0, value=50)

    unit_cost = st.sidebar.number_input("상품 1개당 원가(원)", min_value=0, value=1500)
    daily_holding_cost = st.sidebar.number_input("하루 보관비(원)", min_value=0, value=20)
    disposal_cost_per_unit = st.sidebar.number_input("상품 1개당 폐기비용(원)", min_value=0, value=300)

    discount_rate = st.sidebar.number_input(
        "할인율(%)",
        min_value=0.0,
        max_value=100.0,
        value=20.0,
    )

    expected_sales_increase_rate = st.sidebar.number_input(
        "할인 시 판매 증가율(%)",
        min_value=0.0,
        value=50.0,
    )

    transfer_possible = st.sidebar.selectbox("타점포 이동 가능 여부", ["가능", "불가능"])
    distance_km = st.sidebar.number_input("점포 간 거리(km)", min_value=0.0, value=10.0)
    cost_per_km = st.sidebar.number_input("km당 운송비(원)", min_value=0.0, value=500.0)
    target_store_sales_30d = st.sidebar.number_input("이동 대상 점포 최근 30일 판매량", min_value=0, value=20)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("입력 정보")

    col_a, col_b = st.columns(2)
    col_a.write(f"점포명: **{store_name}**")
    col_b.write(f"상품명: **{product_name}**")

    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("계산 시작", type="primary", width="stretch"):
        result = calculate_inventory_analysis(
            stock_qty=stock_qty,
            sales_30d=sales_30d,
            inbound_days=inbound_days,
            unit_cost=unit_cost,
            daily_holding_cost=daily_holding_cost,
            discount_rate=discount_rate,
            expected_sales_increase_rate=expected_sales_increase_rate,
            transfer_possible=(transfer_possible == "가능"),
            distance_km=distance_km,
            cost_per_km=cost_per_km,
            target_store_sales_30d=target_store_sales_30d,
            disposal_cost_per_unit=disposal_cost_per_unit,
        )

        discount_comparison = analyze_discount_options(
            stock_qty=stock_qty,
            sales_30d=sales_30d,
            unit_cost=unit_cost,
            daily_holding_cost=daily_holding_cost,
            discount_rates=[10, 20, 30, 40],
            expected_sales_increase_rate=expected_sales_increase_rate,
        )

        st.success("계산이 완료되었습니다.")

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("악성재고 판단 결과")

        col1, col2, col3 = st.columns(3)

        col1.metric("재고소진 예상일수", f"{result['stock_cover_days']}일")
        col2.metric("위험점수", f"{result['risk_score']}점")
        col3.metric("악성재고 여부", "예" if result["is_bad_stock"] else "아니오")

        st.subheader("판단 이유")

        if result["reasons"]:
            for reason in result["reasons"]:
                st.write(f"- {reason}")
        else:
            st.write("위험 요소가 크지 않습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("비용 비교")

        if result["transfer_net_cost"] is not None:
            cost_df = pd.DataFrame(
                {
                    "전략": ["유지", "할인", "타점포 이동", "폐기"],
                    "비용": [
                        result["keep_cost"],
                        result["discount_net_cost"],
                        result["transfer_net_cost"],
                        result["disposal_cost"],
                    ],
                }
            )
        else:
            cost_df = pd.DataFrame(
                {
                    "전략": ["유지", "할인", "폐기"],
                    "비용": [
                        result["keep_cost"],
                        result["discount_net_cost"],
                        result["disposal_cost"],
                    ],
                }
            )

        st.dataframe(cost_df, width="stretch")
        st.bar_chart(cost_df, x="전략", y="비용")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("최종 추천")

        st.success(f"추천 전략: {result['best_action']}")
        st.write(f"추천 이유: {result['recommendation_reason']}")
        st.write(f"발주 조언: **{result['order_advice']}**")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("할인율별 비교")

        st.dataframe(discount_comparison)

        discount_chart_data = pd.DataFrame(
            {
                "할인율": [f"{item['discount_rate']}%" for item in discount_comparison],
                "순비용": [item["net_cost"] for item in discount_comparison],
            }
        )

        st.bar_chart(discount_chart_data, x="할인율", y="순비용")
        st.markdown("</div>", unsafe_allow_html=True)

        with st.expander("계산 방식 보기"):
            st.write(result["formula_text"]["stock_cover_days_formula"])
            st.write(result["formula_text"]["risk_formula"])
            st.write(result["formula_text"]["keep_cost_formula"])
            st.write(result["formula_text"]["discount_formula"])
            st.write(result["formula_text"]["transfer_formula"])
            st.write(result["formula_text"]["disposal_formula"])


# =========================
# 2. 엑셀 기반 최적 경로 추천 모드
# =========================

# =========================
# 대형 엑셀 속도 최적화 유틸
# =========================
@st.cache_data(show_spinner=False)
def cached_load_excel_file(file_bytes):
    return load_excel_file(io.BytesIO(file_bytes))


def build_fast_analysis_dataset(stores, products, inventory, routes, max_inventory_rows=1500, max_routes=1200):
    """
    대형 샘플을 빠르게 테스트하기 위해 분석에 필요한 후보만 우선 추린다.
    원본 데이터는 그대로 두고, 분석 계산에만 축소본을 사용한다.
    """
    stores_fast = stores.copy()
    products_fast = products.copy()
    inventory_fast = inventory.copy()
    routes_fast = routes.copy()

    if inventory_fast.empty:
        return stores_fast, products_fast, inventory_fast, routes_fast

    score = pd.Series([0] * len(inventory_fast), index=inventory_fast.index, dtype="float64")

    for col, weight in [
        ("dead_stock_qty", 4.0),
        ("current_stock", 1.5),
        ("stock_qty", 1.5),
        ("quantity", 1.0),
        ("expiry_risk_score", 2.0),
        ("days_to_expiry", -0.8),
    ]:
        if col in inventory_fast.columns:
            values = pd.to_numeric(inventory_fast[col], errors="coerce").fillna(0)
            if col == "days_to_expiry":
                values = values.max() - values
            score += values * weight

    inventory_fast = inventory_fast.assign(_fast_score=score)
    inventory_fast = inventory_fast.sort_values("_fast_score", ascending=False).head(int(max_inventory_rows))
    inventory_fast = inventory_fast.drop(columns=["_fast_score"], errors="ignore")

    if "product_id" in inventory_fast.columns and "product_id" in products_fast.columns:
        selected_products = set(inventory_fast["product_id"].astype(str))
        products_fast = products_fast[products_fast["product_id"].astype(str).isin(selected_products)].copy()

    selected_store_ids = set()

    if "store_id" in inventory_fast.columns:
        selected_store_ids |= set(inventory_fast["store_id"].astype(str))

    if "type" in stores_fast.columns and "store_id" in stores_fast.columns:
        dc_ids = set(
            stores_fast[
                stores_fast["type"].astype(str).str.upper().str.contains("DC", na=False)
            ]["store_id"].astype(str)
        )
        selected_store_ids |= dc_ids

    if selected_store_ids and "store_id" in stores_fast.columns:
        stores_fast = stores_fast[stores_fast["store_id"].astype(str).isin(selected_store_ids)].copy()

    if selected_store_ids and not routes_fast.empty:
        route_mask = pd.Series([True] * len(routes_fast), index=routes_fast.index)

        if "from_id" in routes_fast.columns and "to_id" in routes_fast.columns:
            route_mask = (
                routes_fast["from_id"].astype(str).isin(selected_store_ids)
                & routes_fast["to_id"].astype(str).isin(selected_store_ids)
            )

        routes_fast = routes_fast[route_mask].copy()

        if len(routes_fast) > int(max_routes):
            dc_route_mask = pd.Series([False] * len(routes_fast), index=routes_fast.index)

            if "route_type" in routes_fast.columns:
                dc_route_mask = routes_fast["route_type"].astype(str).str.contains("DC", case=False, na=False)

            priority_routes = routes_fast[dc_route_mask].copy()
            other_routes = routes_fast[~dc_route_mask].copy()

            sort_col = None
            for candidate in ["distance_km", "transport_cost", "travel_time_min"]:
                if candidate in other_routes.columns:
                    sort_col = candidate
                    break

            if sort_col:
                other_routes = other_routes.sort_values(sort_col, ascending=True, na_position="last")

            remain = max(int(max_routes) - len(priority_routes), 0)
            routes_fast = pd.concat([priority_routes, other_routes.head(remain)], ignore_index=True)

    return stores_fast, products_fast, inventory_fast, routes_fast


@st.cache_data(show_spinner="분석 결과를 계산하는 중입니다. 대형 파일은 첫 계산에 시간이 걸릴 수 있습니다.")
def cached_excel_analysis(
    stores,
    products,
    inventory,
    routes,
    departure_time_text,
    promotion_type,
    promotion_discount_rate,
    promotion_sales_increase_rate,
    promotion_fixed_cost,
    fast_mode,
    max_inventory_rows,
    max_routes,
):
    departure_time = time.fromisoformat(departure_time_text)

    if fast_mode:
        analysis_stores, analysis_products, analysis_inventory, analysis_routes = build_fast_analysis_dataset(
            stores,
            products,
            inventory,
            routes,
            max_inventory_rows=max_inventory_rows,
            max_routes=max_routes,
        )
    else:
        analysis_stores, analysis_products, analysis_inventory, analysis_routes = (
            stores,
            products,
            inventory,
            routes,
        )

    dc_routes, best_dc_by_retailer = analyze_dc_retailer_routes(analysis_stores, analysis_routes)

    if dc_routes.empty:
        cutline_result = None
        best_valid_routes = None
        no_valid_items = None
        time_result = None
        time_error = "DC와 점포를 연결하는 route 데이터가 없어 컷라인/시간 분석을 할 수 없습니다."
    else:
        cutline_result, best_valid_routes, no_valid_items = analyze_product_distance_cutline(
            analysis_products,
            analysis_inventory,
            dc_routes,
        )

        time_result, time_error = analyze_trade_time_windows(
            cutline_result,
            analysis_stores,
            departure_time,
        )

    transfer_path_result = analyze_direct_vs_dc_transfer(
        analysis_stores,
        analysis_products,
        analysis_inventory,
        analysis_routes,
        departure_time,
    )

    promotion_result = analyze_promotion_vs_transfer(
        analysis_stores,
        analysis_inventory,
        transfer_path_result,
        promotion_type,
        promotion_discount_rate,
        promotion_sales_increase_rate,
        promotion_fixed_cost,
    )

    network_path_result, network_error = analyze_multi_store_network_paths(
        analysis_stores,
        analysis_products,
        analysis_routes,
        transfer_path_result,
        departure_time,
    )

    final_recommendations, final_rec_summary = build_final_recommendations(
        promotion_result,
        network_path_result,
    )

    final_recommendations, greedy_best_candidate = apply_heuristic_and_greedy(
        final_recommendations,
    )

    greedy_transfer_row = get_matching_transfer_row(
        transfer_path_result,
        greedy_best_candidate,
    )

    return {
        "analysis_stores": analysis_stores,
        "analysis_products": analysis_products,
        "analysis_inventory": analysis_inventory,
        "analysis_routes": analysis_routes,
        "dc_routes": dc_routes,
        "best_dc_by_retailer": best_dc_by_retailer,
        "cutline_result": cutline_result,
        "best_valid_routes": best_valid_routes,
        "no_valid_items": no_valid_items,
        "time_result": time_result,
        "time_error": time_error,
        "transfer_path_result": transfer_path_result,
        "promotion_result": promotion_result,
        "network_path_result": network_path_result,
        "network_error": network_error,
        "final_recommendations": final_recommendations,
        "final_rec_summary": final_rec_summary,
        "greedy_best_candidate": greedy_best_candidate,
        "greedy_transfer_row": greedy_transfer_row,
    }



def show_excel_optimizer():
    show_back_button()

    # 엑셀 분석 화면에서는 메인에 대시보드만 보이도록 상단 설명 헤더와 기능 카드는 숨김 처리
    # show_mode_header(
    #     "📊 엑셀 기반 최적 경로 추천",
    #     "여러 점포, 상품, 재고, 경로 데이터를 기반으로 휴리스틱 점수, Greedy 알고리즘, 강화학습 정책 비교를 적용합니다.",
    #     ["엑셀 업로드", "휴리스틱 점수", "Greedy 알고리즘", "강화학습 정책", "다중 이동수단"],
    # )
    # show_excel_feature_cards()

    if add_heuristic_scores is None or select_greedy_best_candidate is None:
        st.warning(
            "heuristic_optimizer.py 파일을 찾지 못했습니다. "
            "앱은 실행되지만 휴리스틱 점수 기능은 제한됩니다."
        )

    st.sidebar.header("입력 및 설정")

    kakao_js_key = st.sidebar.text_input(
        "카카오맵 JavaScript 키 입력",
        type="password",
        help="카카오 개발자 사이트에서 복사한 JavaScript 키를 입력하세요.",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("엑셀 데이터 입력")

    uploaded_file = st.sidebar.file_uploader(
        "편의점 재고 데이터 엑셀 파일 업로드",
        type=["xlsx"],
    )

    if uploaded_file is None:
        st.markdown(
            """
            <div class="section-card">
                <h2>📊 최적 경로 추천 대시보드</h2>
                <p>
                    왼쪽 사이드바에서 엑셀 파일을 업로드하면 최적 의사결정 결과가 이 화면에 표시됩니다.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    excel_data, missing_sheets = cached_load_excel_file(uploaded_file.getvalue())

    if missing_sheets:
        st.error(f"엑셀 파일에 필요한 시트가 없습니다: {missing_sheets}")
        return

    st.sidebar.success("엑셀 파일 불러옴")

    stores = excel_data["stores"]
    products = excel_data["products"]
    inventory = excel_data["inventory"]
    routes = excel_data["routes"]

    # =========================
    # 사이드바 데이터 요약
    # =========================
    st.sidebar.markdown("---")
    st.sidebar.subheader("데이터 요약")
    st.sidebar.write(f"점포/DC 수: **{len(stores)}개**")
    st.sidebar.write(f"상품 수: **{len(products)}개**")
    st.sidebar.write(f"재고 데이터: **{len(inventory)}건**")
    st.sidebar.write(f"경로 데이터: **{len(routes)}건**")

    with st.sidebar.expander("원본 엑셀 데이터 미리보기"):
        preview_rows = st.slider(
            "미리보기 행 수",
            min_value=20,
            max_value=300,
            value=80,
            step=20,
            key="excel_preview_rows",
        )

        st.caption("속도 보호를 위해 전체 데이터가 아니라 일부 행만 미리보기로 보여줍니다.")

        st.write("stores 시트")
        st.dataframe(stores.head(preview_rows), width="stretch")

        st.write("products 시트")
        st.dataframe(products.head(preview_rows), width="stretch")

        st.write("inventory 시트")
        st.dataframe(inventory.head(preview_rows), width="stretch")

        st.write("routes 시트")
        st.dataframe(routes.head(preview_rows), width="stretch")

        extra_sheet_names = [
            name for name in excel_data.keys()
            if name not in ["stores", "products", "inventory", "routes"]
        ]

        for sheet_name in extra_sheet_names:
            st.write(f"{sheet_name} 시트")
            st.dataframe(excel_data[sheet_name].head(preview_rows), width="stretch")

    # =========================
    # 사이드바 분석 조건
    # =========================
    st.sidebar.markdown("---")
    st.sidebar.subheader("분석 조건 설정")

    departure_time = st.sidebar.time_input(
        "DC/점포 출발 예정 시간",
        value=time(9, 0),
        key="departure_time_excel",
    )

    promotion_type = st.sidebar.selectbox(
        "프로모션 유형",
        ["할인 프로모션", "1+1 프로모션"],
        key="promotion_type_excel",
    )

    promotion_discount_rate = st.sidebar.number_input(
        "프로모션 할인율(%)",
        min_value=0.0,
        max_value=100.0,
        value=20.0,
        key="promotion_discount_rate_excel",
    )

    promotion_sales_increase_rate = st.sidebar.number_input(
        "프로모션 예상 판매 증가율(%)",
        min_value=0.0,
        max_value=500.0,
        value=80.0,
        key="promotion_sales_increase_rate_excel",
    )

    promotion_fixed_cost = st.sidebar.number_input(
        "프로모션 고정비(원)",
        min_value=0,
        value=0,
        key="promotion_fixed_cost_excel",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("속도 최적화")

    fast_mode_default = len(inventory) > 3000 or len(routes) > 1500

    fast_mode = st.sidebar.checkbox(
        "빠른 분석 모드",
        value=fast_mode_default,
        help="대형 파일에서는 악성재고 가능성이 높은 후보와 핵심 경로만 우선 분석해서 속도를 높입니다.",
        key="fast_mode_excel",
    )

    max_inventory_rows = st.sidebar.slider(
        "분석할 재고 후보 수",
        min_value=300,
        max_value=min(max(len(inventory), 300), 6000),
        value=min(1500, max(len(inventory), 300)),
        step=100,
        key="fast_inventory_limit",
        disabled=not fast_mode,
    )

    max_routes = st.sidebar.slider(
        "분석할 경로 후보 수",
        min_value=300,
        max_value=min(max(len(routes), 300), 4000),
        value=min(1200, max(len(routes), 300)),
        step=100,
        key="fast_route_limit",
        disabled=not fast_mode,
    )

    if fast_mode:
        st.sidebar.info(
            f"빠른 분석 모드: 재고 {max_inventory_rows:,}건, 경로 {max_routes:,}건 이내로 우선 분석합니다."
        )
    else:
        st.sidebar.warning("전체 분석 모드는 대형 파일에서 오래 걸릴 수 있습니다.")


    # =========================
    # 분석 계산
    # =========================
    analysis_result = cached_excel_analysis(
        stores=stores,
        products=products,
        inventory=inventory,
        routes=routes,
        departure_time_text=departure_time.isoformat(),
        promotion_type=promotion_type,
        promotion_discount_rate=promotion_discount_rate,
        promotion_sales_increase_rate=promotion_sales_increase_rate,
        promotion_fixed_cost=promotion_fixed_cost,
        fast_mode=fast_mode,
        max_inventory_rows=max_inventory_rows,
        max_routes=max_routes,
    )

    analysis_stores = analysis_result["analysis_stores"]
    analysis_products = analysis_result["analysis_products"]
    analysis_inventory = analysis_result["analysis_inventory"]
    analysis_routes = analysis_result["analysis_routes"]
    dc_routes = analysis_result["dc_routes"]
    best_dc_by_retailer = analysis_result["best_dc_by_retailer"]
    cutline_result = analysis_result["cutline_result"]
    best_valid_routes = analysis_result["best_valid_routes"]
    no_valid_items = analysis_result["no_valid_items"]
    time_result = analysis_result["time_result"]
    time_error = analysis_result["time_error"]
    transfer_path_result = analysis_result["transfer_path_result"]
    promotion_result = analysis_result["promotion_result"]
    network_path_result = analysis_result["network_path_result"]
    network_error = analysis_result["network_error"]
    final_recommendations = analysis_result["final_recommendations"]
    final_rec_summary = analysis_result["final_rec_summary"]
    greedy_best_candidate = analysis_result["greedy_best_candidate"]
    greedy_transfer_row = analysis_result["greedy_transfer_row"]

    if fast_mode:
        st.sidebar.success(
            f"분석 축소 적용: 재고 {len(analysis_inventory):,}건 / 경로 {len(analysis_routes):,}건"
        )

    # =========================
    # 대시보드 라우터
    # =========================
    show_dashboard_router(
        stores=analysis_stores,
        products=analysis_products,
        inventory=analysis_inventory,
        routes=analysis_routes,
        kakao_js_key=kakao_js_key,
        final_recommendations=final_recommendations,
        final_rec_summary=final_rec_summary,
        promotion_result=promotion_result,
        transfer_path_result=transfer_path_result,
        network_path_result=network_path_result,
        dc_routes=dc_routes,
        cutline_result=cutline_result,
        time_result=time_result,
    )

    # 대시보드 라우터가 화면을 관리하므로 아래 기존 상세 섹션은 실행하지 않음
    return

    # =========================
    # 최종 추천
    # =========================
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("최종 추천 모아보기")

    if final_recommendations.empty:
        st.info("최종 추천으로 정리할 결과가 없습니다.")
    else:
        render_best_recommendation(greedy_best_candidate)
        show_algorithm_explanation()

        summary_col1, summary_col2 = st.columns(2)

        summary_col1.metric("최종 추천 건수", f"{len(final_recommendations)}건")
        summary_col2.metric("추천 유형 수", f"{len(final_rec_summary)}개")

        st.write("추천 유형 요약")
        st.dataframe(final_rec_summary, width="stretch")

        if not final_rec_summary.empty and "final_recommendation" in final_rec_summary.columns:
            st.bar_chart(final_rec_summary.set_index("final_recommendation")["count"])

        st.write("최종 추천 상세")
        display_cols = [
            "product_name",
            "source_store",
            "target_store",
            "suggested_qty",
            "final_recommendation",
            "estimated_cost",
            "reason",
        ]

        st.dataframe(
            final_recommendations[[c for c in display_cols if c in final_recommendations.columns]],
            width="stretch",
        )

        if "heuristic_score" in final_recommendations.columns:
            st.markdown("---")
            st.subheader("🧠 휴리스틱 점수 + Greedy 선택 결과")

            heuristic_cols = [
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

            heuristic_view = final_recommendations[
                [c for c in heuristic_cols if c in final_recommendations.columns]
            ].rename(
                columns={
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
            )

            st.dataframe(heuristic_view, width="stretch")

            # =========================
            # 강화학습 준비 데이터 생성 + RL 정책 비교
            # =========================
            st.markdown("---")
            st.subheader("🤖 강화학습 준비 데이터 생성")

            st.info(
                "현재 추천 후보들을 강화학습 학습용 데이터 형태로 변환합니다. "
                "State는 재고·판매량·비용·거리 정보, Action은 추천 행동, "
                "Reward는 비용 절감과 휴리스틱 점수를 반영한 임시 보상입니다."
            )

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
                    rl_col1, rl_col2, rl_col3 = st.columns(3)

                    rl_col1.metric("RL 학습 샘플 수", f"{len(rl_training_log)}개")
                    rl_col2.metric("평균 Reward", f"{rl_training_log['reward'].mean():.2f}")
                    rl_col3.metric("최대 Reward", f"{rl_training_log['reward'].max():.2f}")

                    with st.expander("강화학습 학습 데이터 미리보기"):
                        st.dataframe(rl_training_log, width="stretch")

                    csv_data = rl_training_log.to_csv(index=False).encode("utf-8-sig")

                    st.download_button(
                        label="📥 RL 학습 데이터 CSV 다운로드",
                        data=csv_data,
                        file_name="rl_training_log.csv",
                        mime="text/csv",
                        key="download_rl_training_log",
                    )

                    st.markdown("---")
                    st.subheader("🧩 Greedy 추천 vs 강화학습 추천 비교")

                    try:
                        from rl_policy_helper import recommend_action_for_rl_log

                        rl_compare_result = recommend_action_for_rl_log(
                            rl_training_log,
                            policy_file="rl_policy_table.csv",
                        )

                        if rl_compare_result.empty:
                            st.warning(
                                "강화학습 정책 비교 결과가 없습니다. "
                                "rl_policy_table.csv 파일이 프로젝트 폴더에 있는지 확인해 주세요."
                            )
                        else:
                            matched_count = int(
                                (rl_compare_result["rl_match_status"] == "정책 매칭됨").sum()
                            )

                            compare_col1, compare_col2, compare_col3 = st.columns(3)

                            compare_col1.metric("비교 후보 수", f"{len(rl_compare_result)}개")
                            compare_col2.metric("RL 정책 매칭 수", f"{matched_count}개")

                            if rl_compare_result["expected_reward"].notna().any():
                                avg_expected_reward = rl_compare_result["expected_reward"].dropna().mean()
                                compare_col3.metric("평균 기대 Reward", f"{avg_expected_reward:.2f}")
                            else:
                                compare_col3.metric("평균 기대 Reward", "-")

                            rl_compare_cols = [
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

                            rl_compare_view = rl_compare_result[
                                [c for c in rl_compare_cols if c in rl_compare_result.columns]
                            ].rename(
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

                            st.dataframe(rl_compare_view, width="stretch")

                            with st.expander("강화학습 정책 근거 보기"):
                                policy_reason_cols = [
                                    "product_name",
                                    "source_store",
                                    "target_store",
                                    "state_key",
                                    "policy_reason",
                                ]

                                policy_reason_view = rl_compare_result[
                                    [c for c in policy_reason_cols if c in rl_compare_result.columns]
                                ].rename(
                                    columns={
                                        "product_name": "상품명",
                                        "source_store": "보내는 점포",
                                        "target_store": "받는 점포",
                                        "state_key": "상태 Key",
                                        "policy_reason": "정책 선택 근거",
                                    }
                                )

                                st.dataframe(policy_reason_view, width="stretch")

                    except FileNotFoundError:
                        st.warning("rl_policy_table.csv 파일을 찾지 못했습니다. 먼저 py train_rl_agent.py를 실행해 주세요.")
                    except ImportError:
                        st.warning("rl_policy_helper.py 파일을 찾지 못했습니다. 먼저 프로젝트 폴더에 추가해 주세요.")
                    except Exception as e:
                        st.warning(f"강화학습 정책 비교 중 오류가 발생했습니다: {e}")

            except ImportError:
                st.warning("rl_data_logger.py 파일을 찾지 못했습니다. 먼저 rl_data_logger.py를 프로젝트 폴더에 추가해 주세요.")
            except Exception as e:
                st.warning(f"강화학습 학습 데이터 생성 중 오류가 발생했습니다: {e}")

        st.subheader("🧺 Inventory 장바구니 담기")

        final_recommendations_view = final_recommendations.reset_index(drop=True)

        selected_index = st.selectbox(
            "장바구니에 담을 추천 항목 선택",
            final_recommendations_view.index,
            format_func=lambda i: (
                f"{final_recommendations_view.loc[i, 'product_name']} | "
                f"{final_recommendations_view.loc[i, 'source_store']} → "
                f"{final_recommendations_view.loc[i, 'target_store']} | "
                f"{final_recommendations_view.loc[i, 'final_recommendation']}"
            ),
            key="cart_select_recommendation",
        )

        if st.button("🛒 Inventory에 담기", key="add_to_inventory_cart"):
            selected_row = final_recommendations_view.loc[selected_index]

            cart_item = {
                "상품명": selected_row["product_name"],
                "보내는 점포": selected_row["source_store"],
                "받는 점포": selected_row["target_store"],
                "수량": selected_row["suggested_qty"],
                "추천 전략": selected_row["final_recommendation"],
                "예상 비용": selected_row["estimated_cost"],
                "추천 이유": selected_row["reason"],
            }

            st.session_state.cart.append(cart_item)
            st.success("Inventory 장바구니에 담았습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # Inventory 장바구니
    # =========================
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("🧾 Inventory 장바구니")

    if len(st.session_state.cart) == 0:
        st.info("장바구니가 비어있습니다.")
    else:
        for i, item in enumerate(st.session_state.cart):
            c1, c2, c3, c4 = st.columns([4, 2, 2, 1])

            with c1:
                st.write(
                    f"**{item['상품명']}** / "
                    f"{item['보내는 점포']} → {item['받는 점포']}"
                )
                st.caption(f"추천 이유: {item['추천 이유']}")

            with c2:
                st.write(f"수량: {item['수량']}개")

            with c3:
                st.write(f"전략: {item['추천 전략']}")

                cost_value = item["예상 비용"]
                if isinstance(cost_value, Number):
                    st.write(f"예상 비용: {cost_value:,.0f}원")
                else:
                    st.write(f"예상 비용: {cost_value}")

            with c4:
                if st.button("삭제", key=f"delete_cart_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()

        total_cost = sum(
            item["예상 비용"]
            for item in st.session_state.cart
            if isinstance(item["예상 비용"], Number)
        )

        cart_col1, cart_col2 = st.columns(2)

        cart_col1.metric("담긴 추천 항목 수", f"{len(st.session_state.cart)}건")
        cart_col2.metric("총 예상 비용", f"{total_cost:,.0f}원")

        if st.button("장바구니 전체 비우기", key="clear_inventory_cart"):
            st.session_state.cart = []
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # 카카오맵
    # =========================
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("카카오맵 기반 점포 및 경로 시각화")

    if kakao_js_key:
        show_kakao_map(stores, routes, kakao_js_key)
    else:
        st.info("카카오맵을 보려면 왼쪽 사이드바에 JavaScript 키를 입력하세요.")

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # 추천 경로 강조 지도
    # =========================
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("추천 경로 강조 지도")

    highlight_paths = []

    if greedy_transfer_row is not None:
        if greedy_transfer_row["recommended_path"] == "직접 이동 추천":
            best_path_names = [
                greedy_transfer_row["source_store"],
                greedy_transfer_row["target_store"],
            ]

        elif greedy_transfer_row["recommended_path"] == "DC 경유 이동 추천":
            best_path_names = [
                greedy_transfer_row["source_store"],
                greedy_transfer_row["via_dc"],
                greedy_transfer_row["target_store"],
            ]

        else:
            best_path_names = [
                greedy_transfer_row["source_store"],
                greedy_transfer_row["target_store"],
            ]

        highlight_paths.append(
            {
                "path_names": best_path_names,
                "label": f"{greedy_transfer_row['product_name']} - Greedy 최적 추천",
            }
        )

    if not transfer_path_result.empty:
        recommended_transfer_paths = transfer_path_result[
            transfer_path_result["recommended_path"] != "이동 비추천"
        ]

        for _, path_row in recommended_transfer_paths.iterrows():
            if greedy_transfer_row is not None:
                same_candidate = (
                    path_row["product_name"] == greedy_transfer_row["product_name"]
                    and path_row["source_store"] == greedy_transfer_row["source_store"]
                    and path_row["target_store"] == greedy_transfer_row["target_store"]
                )

                if same_candidate:
                    continue

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

    if not network_path_result.empty and "network_recommendation" in network_path_result.columns:
        network_recommended_paths = network_path_result[
            network_path_result["network_recommendation"] == "다중 경로 추천"
        ]

        for _, network_row in network_recommended_paths.iterrows():
            if "network_path" not in network_row.index:
                continue

            path_names = str(network_row["network_path"]).split(" → ")

            highlight_paths.append(
                {
                    "path_names": path_names,
                    "label": f"{network_row.get('product_name', '-') } - 다중 경로 추천",
                }
            )

    if kakao_js_key and highlight_paths:
        show_kakao_map_with_highlights(
            stores,
            routes,
            kakao_js_key,
            highlight_paths,
        )
    elif not kakao_js_key:
        st.info("추천 경로 지도를 보려면 왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하세요.")
    else:
        st.info("강조 표시할 추천 경로가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # 재고 이동 + Inventory 변화
    # =========================
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("🚚 지도 클릭 기반 Multi-재고 이동 시뮬레이션")

    truck_speed = st.slider(
        "재고 이동 배속",
        min_value=0.5,
        max_value=10.0,
        value=1.0,
        step=0.5,
        key="truck_speed_slider",
    )

    max_truck_routes = st.slider(
        "지도에 표시할 추천 경로 후보 수",
        min_value=3,
        max_value=20,
        value=8,
        step=1,
        key="max_truck_routes_slider",
    )

    default_selected_count = st.slider(
        "처음 자동 선택할 Truck 수",
        min_value=1,
        max_value=5,
        value=3,
        step=1,
        key="default_selected_truck_count",
    )

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

    def build_scenario(path_row, scenario_rank):
        selected_product_name = path_row["product_name"]
        source_store_name = path_row["source_store"]
        target_store_name = path_row["target_store"]
        recommended_path = path_row["recommended_path"]

        try:
            move_qty = int(path_row["suggested_transfer_qty"])
        except Exception:
            move_qty = 0

        if recommended_path == "DC 경유 이동 추천":
            via_dc_name = path_row.get("via_dc", None)

            if via_dc_name and pd.notna(via_dc_name):
                path_names = [source_store_name, via_dc_name, target_store_name]
            else:
                path_names = [source_store_name, target_store_name]
        else:
            via_dc_name = None
            path_names = [source_store_name, target_store_name]

        truck_path = []

        for name in path_names:
            if name in store_location_map:
                truck_path.append(store_location_map[name])

        source_store_id = store_name_to_id.get(source_store_name)
        target_store_id = store_name_to_id.get(target_store_name)
        product_id = product_name_to_id.get(selected_product_name)

        source_before = get_current_stock(source_store_id, product_id)
        target_before = get_current_stock(target_store_id, product_id)

        source_after = max(source_before - move_qty, 0)
        target_after = target_before + move_qty

        store_inventory = {
            source_store_name: {
                "role": "보내는 점포",
                "product_name": selected_product_name,
                "before": source_before,
                "after": source_after,
                "change": -move_qty,
            },
            target_store_name: {
                "role": "받는 점포",
                "product_name": selected_product_name,
                "before": target_before,
                "after": target_after,
                "change": move_qty,
            },
        }

        if recommended_path == "DC 경유 이동 추천" and via_dc_name:
            via_dc_id = store_name_to_id.get(via_dc_name)
            via_before = get_current_stock(via_dc_id, product_id)

            store_inventory[via_dc_name] = {
                "role": "경유 DC",
                "product_name": selected_product_name,
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

        return {
            "label": f"{scenario_rank}. {selected_product_name} / {source_store_name} → {target_store_name}",
            "product_name": selected_product_name,
            "source_store": source_store_name,
            "target_store": target_store_name,
            "move_qty": move_qty,
            "recommended_path": recommended_path,
            "estimated_cost": str(estimated_cost),
            "heuristic_score": str(heuristic_score),
            "reason": str(reason),
            "path_names": path_names,
            "path": truck_path,
            "store_inventory": store_inventory,
        }

    if not transfer_path_result.empty:
        truck_candidates = transfer_path_result[
            transfer_path_result["recommended_path"] != "이동 비추천"
        ].copy()
    else:
        truck_candidates = pd.DataFrame()

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

    if truck_candidates.empty:
        st.info("재고 이동을 표시할 추천 경로가 없습니다.")

    elif not kakao_js_key:
        st.info("재고 이동 시뮬레이션을 보려면 왼쪽 사이드바에 카카오맵 JavaScript 키를 입력하세요.")

    elif show_kakao_map_with_multi_trucks is None:
        st.warning("kakao_map_viewer.py에 show_kakao_map_with_multi_trucks 함수가 없습니다.")

    else:
        truck_scenarios = []

        for scenario_rank, (_, candidate_row) in enumerate(truck_candidates.iterrows(), start=1):
            scenario = build_scenario(candidate_row, scenario_rank)

            if len(scenario["path"]) >= 2:
                truck_scenarios.append(scenario)

        if not truck_scenarios:
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
                truck_scenarios,
                speed_multiplier=truck_speed,
                default_selected_count=default_selected_count,
            )

    st.markdown("</div>", unsafe_allow_html=True)

    # =========================
    # 상세 분석 결과
    # =========================
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("상세 분석 결과")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "DC-점포",
            "거리 컷라인",
            "거래가능시간",
            "직접 vs DC 경유",
            "프로모션 비교",
            "다중 경로",
        ]
    )

    with tab1:
        st.subheader("DC-점포 거리 및 운송비 계산")

        if dc_routes.empty:
            st.warning("DC와 점포를 연결하는 route 데이터가 없습니다.")
        else:
            st.write("DC-점포 전체 경로 계산 결과")
            st.dataframe(dc_routes, width="stretch")

            st.write("점포별 최적 DC 추천")
            st.dataframe(best_dc_by_retailer, width="stretch")

            if not best_dc_by_retailer.empty and "retailer_name" in best_dc_by_retailer.columns:
                st.write("점포별 최저 운송비 그래프")
                chart_data = best_dc_by_retailer.set_index("retailer_name")["transport_cost"]
                st.bar_chart(chart_data)

    with tab2:
        st.subheader("제품별 거리 컷라인 판별")

        if cutline_result is None or cutline_result.empty:
            st.warning("제품별 거리 컷라인 분석 결과가 없습니다.")
        else:
            st.write("제품별 DC-점포 이동 가능 여부")
            st.dataframe(cutline_result, width="stretch")

            st.write("제품별/점포별 컷라인 내 최적 DC")
            if best_valid_routes is None or best_valid_routes.empty:
                st.warning("거리 컷라인을 만족하는 이동 가능 경로가 없습니다.")
            else:
                st.dataframe(best_valid_routes, width="stretch")

            st.write("거리 컷라인 때문에 이동 불가능한 품목")
            if no_valid_items is None or no_valid_items.empty:
                st.success("모든 품목이 최소 1개 이상의 이동 가능 경로를 가지고 있습니다.")
            else:
                st.dataframe(no_valid_items, width="stretch")

    with tab3:
        st.subheader("거래가능시간 판별")

        if time_error:
            st.warning(time_error)
        elif time_result is None or time_result.empty:
            st.warning("거래가능시간 분석 결과가 없습니다.")
        else:
            st.write("거리 컷라인 + 거래가능시간 판별 결과")
            st.dataframe(time_result, width="stretch")

            time_summary = (
                time_result.groupby("final_status")
                .size()
                .reset_index(name="count")
            )

            st.write("최종 이동 가능 여부 요약")
            st.dataframe(time_summary, width="stretch")
            st.bar_chart(time_summary.set_index("final_status")["count"])

    with tab4:
        st.subheader("점포 간 직접 이동 vs DC 경유 이동 비교")

        if transfer_path_result.empty:
            st.warning("점포 간 이동 비교가 가능한 후보가 없습니다.")
        else:
            st.dataframe(transfer_path_result, width="stretch")

            if "recommended_path" in transfer_path_result.columns:
                path_summary = (
                    transfer_path_result.groupby("recommended_path")
                    .size()
                    .reset_index(name="count")
                )

                st.write("추천 경로 요약")
                st.dataframe(path_summary, width="stretch")
                st.bar_chart(path_summary.set_index("recommended_path")["count"])

    with tab5:
        st.subheader("프로모션 vs 재배치 비교")

        if promotion_result.empty:
            st.warning("프로모션과 비교할 수 있는 이동 후보가 없습니다.")
        else:
            st.dataframe(promotion_result, width="stretch")

            if "final_decision" in promotion_result.columns:
                promo_summary = (
                    promotion_result.groupby("final_decision")
                    .size()
                    .reset_index(name="count")
                )

                st.write("최종 처리 방식 요약")
                st.dataframe(promo_summary, width="stretch")
                st.bar_chart(promo_summary.set_index("final_decision")["count"])

            if "promotion_formula" in promotion_result.columns:
                with st.expander("프로모션 계산식 보기"):
                    for _, promo_row in promotion_result.iterrows():
                        st.write(
                            f"{promo_row['product_name']} / "
                            f"{promo_row['source_store']} → {promo_row['target_store']}: "
                            f"{promo_row['promotion_formula']}"
                        )

    with tab6:
        st.subheader("여러 점포 연결 최저비용 경로 계산")

        if network_error:
            st.warning(network_error)
        elif network_path_result.empty:
            st.warning("계산 가능한 다중 연결 경로가 없습니다.")
        else:
            st.dataframe(network_path_result, width="stretch")

            if "network_recommendation" in network_path_result.columns:
                network_summary = (
                    network_path_result.groupby("network_recommendation")
                    .size()
                    .reset_index(name="count")
                )

                st.write("다중 경로 추천 요약")
                st.dataframe(network_summary, width="stretch")
                st.bar_chart(network_summary.set_index("network_recommendation")["count"])

    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# 실행 분기
# =========================
if st.session_state.selected_mode is None:
    show_mode_selector()
elif st.session_state.selected_mode == "single":
    show_single_calculator()
elif st.session_state.selected_mode == "excel":
    show_excel_optimizer()


st.markdown("---")
st.markdown(
    """
    <div class="footer-note">
        © 2026 김서호. All rights reserved. | Varo 편의점 재고 공유 및 최적 의사결정 시스템
    </div>
    """,
    unsafe_allow_html=True,
)
