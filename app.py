import html as html_lib
import io
import warnings
from datetime import time
from numbers import Number

import pandas as pd
import streamlit as st


# =========================
# Streamlit 표 출력 안전 패치
# =========================
# st.dataframe()이 object 컬럼 안의 문자/숫자 혼합 때문에
# pyarrow 경고(Expected bytes, got int object)를 길게 출력하는 문제를 막음.
_ORIGINAL_ST_DATAFRAME = st.dataframe


def _prepare_dataframe_for_display(data):
    """화면 표시용 DataFrame을 안전하게 정리한다."""
    if data is None:
        return pd.DataFrame()

    if isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        try:
            df = pd.DataFrame(data)
        except Exception:
            return data

    # 컬럼명을 문자열로 통일
    df.columns = [str(col) for col in df.columns]

    # object/category 컬럼은 문자열로 통일해서 Arrow 변환 오류 방지
    for col in df.columns:
        try:
            dtype_name = str(df[col].dtype)
            if pd.api.types.is_object_dtype(df[col]) or dtype_name == "category":
                df[col] = df[col].map(lambda x: "" if pd.isna(x) else str(x))
        except Exception:
            try:
                df[col] = df[col].astype(str)
            except Exception:
                pass

    return df


def _safe_streamlit_dataframe(data=None, *args, **kwargs):
    """기존 st.dataframe 대신 안전하게 표를 표시한다."""
    safe_data = _prepare_dataframe_for_display(data)
    return _ORIGINAL_ST_DATAFRAME(safe_data, *args, **kwargs)


# app.py뿐 아니라 dashboard_pages.py, dashboard_view.py에서 쓰는 st.dataframe도 같이 안전 처리됨.
st.dataframe = _safe_streamlit_dataframe

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

try:
    from kakao_map_viewer import show_kakao_map, show_kakao_map_with_highlights, show_store_matching_map
except ImportError:
    show_kakao_map = None
    show_kakao_map_with_highlights = None
    show_store_matching_map = None

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

try:
    from varo_score import run_all_algorithms
except ImportError:
    run_all_algorithms = None


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
    # 구글 번역 차단 + 다크모드 강제 고정
    st.markdown(
        """
        <meta name="google" content="notranslate">
        <meta http-equiv="Content-Language" content="ko">
        <style>
            /* 다크모드 완전 차단 */
            :root { color-scheme: light only !important; }
            @media (prefers-color-scheme: dark) {
                :root { color-scheme: light only !important; }
                html, body, [data-testid="stApp"],
                [data-testid="stAppViewContainer"], .main {
                    background-color: #ffffff !important;
                    color: #2b2d36 !important;
                }
            }
            /* 구글 번역 UI 제거 */
            .goog-te-banner-frame, .goog-te-balloon-frame,
            #goog-gt-tt, .goog-tooltip, .goog-tooltip-container,
            .skiptranslate { display: none !important; }
            body { top: 0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
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
        
/* =========================
   배포/모바일 글자색 고정
   =========================
   Streamlit Cloud, 모바일, 브라우저 다크모드에서
   글씨가 흰색으로 잡혀 안 보이는 문제를 방지한다.
*/
html, body, [class*="stApp"], .stApp {
    color: #222222 !important;
    background-color: #fffdf5 !important;
}

.main, .block-container, section.main, div[data-testid="stAppViewContainer"] {
    color: #222222 !important;
    background-color: #fffdf5 !important;
}

div[data-testid="stSidebar"], section[data-testid="stSidebar"] {
    color: #222222 !important;
    background: #fff8d8 !important;
}

div[data-testid="stSidebar"] *,
section[data-testid="stSidebar"] * {
    color: #222222 !important;
}

h1, h2, h3, h4, h5, h6, p, span, label, div, small, strong, b, li {
    color: #222222 !important;
}

.stMarkdown, .stMarkdown *, .stText, .stText *, .stCaptionContainer, .stCaptionContainer * {
    color: #222222 !important;
}

div[data-testid="stMetric"] *,
div[data-testid="stDataFrame"] *,
div[data-testid="stTable"] * {
    color: #222222 !important;
}

input, textarea, select {
    color: #222222 !important;
    background-color: #ffffff !important;
}

button {
    color: #222222 !important;
}

.main-hero,
.mode-header,
.mode-card,
.section-card,
.dash-page-box {
    color: #222222 !important;
}

.main-hero *,
.mode-header *,
.mode-card *,
.section-card *,
.dash-page-box * {
    color: #222222 !important;
}

/* 입력창 placeholder는 너무 진하지 않게 */
input::placeholder,
textarea::placeholder {
    color: #777777 !important;
    opacity: 1 !important;
}

/* 파일 업로더 내부도 밝은 배경 기준으로 고정 */
div[data-testid="stFileUploader"] *,
div[data-testid="stFileUploaderDropzone"] * {
    color: #222222 !important;
}

/* selectbox, multiselect 내부 텍스트 */
div[data-baseweb="select"] *,
div[data-baseweb="popover"] * {
    color: #222222 !important;
}

/* 탭/라디오/체크박스 */
div[role="tab"] *,
div[role="radiogroup"] *,
label[data-baseweb="checkbox"] * {
    color: #222222 !important;
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


def apply_heuristic_and_greedy(final_recommendations, inventory=None, stores=None, routes=None):
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

    if run_all_algorithms is not None:
        inventory_df = inventory
        scored = run_all_algorithms(inventory_df, scored)

    # ── 점포 클러스터링 ──────────────────────────────────
    try:
        from store_clustering import analyze_store_clustering, add_cluster_to_recommendations
        if stores is not None and inventory is not None:
            _, _, cluster_map = _cached_clustering(stores, inventory)
            scored = add_cluster_to_recommendations(scored, cluster_map)
    except Exception:
        pass

    # ── 최소비용 네트워크 분석 ────────────────────────────
    try:
        from min_cost_network import analyze_min_cost_network, add_network_score_to_recommendations
        if stores is not None and inventory is not None and routes is not None:
            flow_df, node_df, net_summary = _cached_network(inventory, stores, routes)
            scored = add_network_score_to_recommendations(scored, flow_df)
            # session_state 저장은 캐시 밖(호출 측)에서 처리
    except Exception:
        pass

    greedy_best = select_greedy_best_candidate(scored)

    return scored, greedy_best


@st.cache_data(show_spinner=False)
def _cached_clustering(_stores, _inventory):
    """클러스터링 결과 캐시 — 데이터 변경 시 자동 갱신."""
    from store_clustering import analyze_store_clustering
    return analyze_store_clustering(_stores, _inventory)


@st.cache_data(show_spinner=False)
def _cached_network(_inventory, _stores, _routes):
    """최소비용 네트워크 캐시 — 데이터 변경 시 자동 갱신."""
    from min_cost_network import analyze_min_cost_network
    return analyze_min_cost_network(_inventory, _stores, _routes)


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
                AI 기반으로 재고 데이터를 자동 분석해 악성재고 판단, 재고 이동 추천,
                비용 비교, 최적 경로 계산, 강화학습 비교까지 지원하는
                <b>재고관리 의사결정 시스템.</b>
            </p>
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


def show_mode_header(title, description=None, badges=None):
    html = (
        '<div class="mode-header">'
        f"<h2>{escape_text(title)}</h2>"
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

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🧮 개별 입력 계산", width="stretch", type="primary"):
            st.session_state.selected_mode = "single"
            st.rerun()

    with col2:
        if st.button("📊 엑셀 기반 분석", width="stretch", type="primary"):
            st.session_state.selected_mode = "excel"
            st.rerun()


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


def _parse_time_value(value, default=time(9, 0)):
    try:
        if isinstance(value, time):
            return value

        if pd.isna(value):
            return default

        if isinstance(value, (int, float)):
            numeric = float(value)

            # 엑셀 시간값: 0.3333 = 08:00, 0.9166 = 22:00
            if 0 <= numeric < 1:
                total_minutes = int(round(numeric * 24 * 60))
                return time((total_minutes // 60) % 24, total_minutes % 60)

            # 8.5 같은 값은 08:30으로 처리
            if 1 <= numeric < 24:
                hour = int(numeric)
                minute = int(round((numeric - hour) * 60))
                return time(hour % 24, minute % 60)

            # 이미 분 단위로 들어온 값
            if 24 <= numeric < 24 * 60:
                total_minutes = int(round(numeric))
                return time((total_minutes // 60) % 24, total_minutes % 60)

        text = str(value).strip()

        if not text:
            return default

        if ":" in text:
            parts = text.split(":")
            hour = int(float(parts[0]))
            minute = int(float(parts[1])) if len(parts) > 1 else 0
            return time(hour % 24, minute % 60)

        numeric = float(text)

        if 0 <= numeric < 1:
            total_minutes = int(round(numeric * 24 * 60))
            return time((total_minutes // 60) % 24, total_minutes % 60)

        hour = int(numeric)
        minute = int(round((numeric - hour) * 60))
        return time(hour % 24, minute % 60)
    except Exception:
        return default


def _read_config_value(excel_data, key, default=None):
    """
    엑셀에 config 시트가 있으면 key/value 구조에서 값을 읽는다.
    config 시트가 없거나 key가 없으면 default를 반환한다.
    """
    config = excel_data.get("config")

    if config is None or config.empty:
        return default

    config_df = config.copy()
    config_df.columns = [str(c).strip().lower() for c in config_df.columns]

    key_col = None
    value_col = None

    for candidate in ["key", "항목", "setting", "name"]:
        if candidate in config_df.columns:
            key_col = candidate
            break

    for candidate in ["value", "값", "setting_value"]:
        if candidate in config_df.columns:
            value_col = candidate
            break

    if key_col is None or value_col is None:
        return default

    matched = config_df[config_df[key_col].astype(str).str.strip().str.lower() == str(key).strip().lower()]

    if matched.empty:
        return default

    value = matched.iloc[0][value_col]

    if pd.isna(value):
        return default

    if str(value).strip().upper() == "AUTO":
        return default

    return value


def auto_determine_analysis_conditions(excel_data, stores, products, inventory):
    """
    사용자가 직접 분석 조건을 입력하지 않아도 되도록
    config 시트 또는 데이터 특성을 기준으로 분석 조건을 자동 결정한다.
    """
    # 1) 출발 시간
    config_departure = _read_config_value(excel_data, "departure_time", None)
    departure_time = _parse_time_value(config_departure, default=time(9, 0))

    if config_departure is None and stores is not None and not stores.empty and "available_start" in stores.columns:
        try:
            start_hours = []

            for raw_value in stores["available_start"].dropna().tolist():
                parsed_time = _parse_time_value(raw_value, default=None)
                if parsed_time is not None:
                    start_hours.append(parsed_time.hour)

            if start_hours:
                # 가장 흔한 오픈 시간보다 1시간 뒤를 출발 시간으로 설정
                common_start = int(pd.Series(start_hours).mode().iloc[0])
                departure_time = time(min(common_start + 1, 23), 0)
        except Exception:
            departure_time = time(9, 0)

    # 2) 재고/폐기 위험 기반 지표
    inv = inventory.copy() if inventory is not None else pd.DataFrame()

    dead_ratio = 0.0
    avg_expiry_risk = 0.0
    urgent_ratio = 0.0

    try:
        quantity_col = None

        for col in ["quantity", "stock_qty", "current_stock"]:
            if col in inv.columns:
                quantity_col = col
                break

        if quantity_col and "dead_stock_qty" in inv.columns:
            total_qty = pd.to_numeric(inv[quantity_col], errors="coerce").fillna(0).sum()
            dead_qty = pd.to_numeric(inv["dead_stock_qty"], errors="coerce").fillna(0).sum()
            dead_ratio = float(dead_qty / total_qty) if total_qty > 0 else 0.0

        if "expiry_risk_score" in inv.columns:
            avg_expiry_risk = float(pd.to_numeric(inv["expiry_risk_score"], errors="coerce").fillna(0).mean())

        if "days_to_expiry" in inv.columns:
            days = pd.to_numeric(inv["days_to_expiry"], errors="coerce")
            urgent_ratio = float((days <= 3).mean())
    except Exception:
        dead_ratio = 0.0
        avg_expiry_risk = 0.0
        urgent_ratio = 0.0

    # 3) 프로모션 유형 자동 결정
    config_promo_type = _read_config_value(excel_data, "promotion_type", None)

    if config_promo_type is not None:
        promotion_type = str(config_promo_type)
    else:
        if avg_expiry_risk >= 60 or urgent_ratio >= 0.35 or dead_ratio >= 0.25:
            promotion_type = "할인 프로모션"
        else:
            promotion_type = "1+1 프로모션"

    # 4) 할인율 자동 결정
    config_discount = _read_config_value(excel_data, "promotion_discount_rate", None)

    if config_discount is not None:
        try:
            promotion_discount_rate = float(config_discount)
        except Exception:
            promotion_discount_rate = 20.0
    else:
        if avg_expiry_risk >= 75 or urgent_ratio >= 0.45:
            promotion_discount_rate = 30.0
        elif avg_expiry_risk >= 45 or dead_ratio >= 0.20:
            promotion_discount_rate = 20.0
        else:
            promotion_discount_rate = 10.0

    # 5) 판매 증가율 자동 추정
    config_sales_increase = _read_config_value(excel_data, "promotion_sales_increase_rate", None)

    if config_sales_increase is not None:
        try:
            promotion_sales_increase_rate = float(config_sales_increase)
        except Exception:
            promotion_sales_increase_rate = 80.0
    else:
        promotion_sales_increase_rate = min(150.0, max(30.0, 40.0 + promotion_discount_rate * 2.0 + urgent_ratio * 30.0))

    # 6) 프로모션 고정비
    config_fixed_cost = _read_config_value(excel_data, "promotion_fixed_cost", 0)

    try:
        promotion_fixed_cost = int(float(config_fixed_cost))
    except Exception:
        promotion_fixed_cost = 0

    analysis_condition_summary = {
        "departure_time": departure_time.strftime("%H:%M"),
        "promotion_type": promotion_type,
        "promotion_discount_rate": promotion_discount_rate,
        "promotion_sales_increase_rate": round(promotion_sales_increase_rate, 1),
        "promotion_fixed_cost": promotion_fixed_cost,
        "dead_stock_ratio": round(dead_ratio * 100, 1),
        "avg_expiry_risk": round(avg_expiry_risk, 1),
        "urgent_expiry_ratio": round(urgent_ratio * 100, 1),
        "source": "config 시트" if excel_data.get("config") is not None else "데이터 기반 자동 추정",
    }

    return (
        departure_time,
        promotion_type,
        promotion_discount_rate,
        promotion_sales_increase_rate,
        promotion_fixed_cost,
        analysis_condition_summary,
    )



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
        inventory=analysis_inventory,
        stores=analysis_stores,
        routes=analysis_routes,
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
    # "방식 선택 화면으로 돌아가기"는 홈(대시보드)에서만 표시
    if st.session_state.get("excel_dashboard_page", "dashboard") == "dashboard":
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

    # ── 데모 모드 버튼 ─────────────────────────────────
    with st.sidebar.expander("🎮 데모 모드 (엑셀 없이 시연)", expanded=False):
        try:
            from demo_data import DEMO_SCENARIOS, get_demo_sheets
            demo_choice = st.selectbox(
                "샘플 시나리오", ["선택 안 함"] + list(DEMO_SCENARIOS.keys()),
                key="sidebar_demo_sel"
            )
            if st.button("이 샘플로 분석", key="sidebar_demo_btn") and demo_choice != "선택 안 함":
                key = DEMO_SCENARIOS[demo_choice]
                demo_sheets = get_demo_sheets(key)
                st.session_state["demo_active"]   = True
                st.session_state["demo_sheets"]   = demo_sheets
                st.session_state["demo_scenario"] = demo_choice
                st.rerun()
        except ImportError:
            st.caption("demo_data.py 없음")

    uploaded_file = st.sidebar.file_uploader(
        "편의점 재고 데이터 엑셀 파일 업로드",
        type=["xlsx"],
    )

    # ── 데모 데이터 사용 ───────────────────────────────
    _using_demo = st.session_state.get("demo_active") and "demo_sheets" in st.session_state
    if uploaded_file is None and not _using_demo:
        st.markdown(
            """
            <div class="section-card">
                <h2>📊 최적 경로 추천 대시보드</h2>
                <p>왼쪽 사이드바에서 엑셀 파일을 업로드하거나
                   <strong>데모 모드</strong>를 선택하면 결과가 표시됩니다.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # 데이터 로드 (업로드 or 데모)
    if _using_demo:
        excel_data = st.session_state["demo_sheets"]
        st.sidebar.info(f"🎮 데모: {st.session_state.get('demo_scenario','')}")
        if st.sidebar.button("❌ 데모 종료 (엑셀 입력으로)", key="exit_demo_btn", type="secondary"):
            for k in ["demo_active","demo_sheets","demo_scenario",
                      "_analysis_result","_analysis_file_hash","_validation_warning"]:
                st.session_state.pop(k, None)
            st.rerun()
        missing_sheets = []
    else:
        excel_data, missing_sheets = cached_load_excel_file(uploaded_file.getvalue())

    if missing_sheets:
        st.error(f"⚠️ 필수 시트가 없습니다: {', '.join(missing_sheets)}")
        st.info("stores, products, inventory, routes 시트가 모두 필요합니다.")
        return

    st.sidebar.success("엑셀 파일 불러옴")

    # ── config 시트 가중치 연동 ──────────────────────────
    try:
        from varo_score_config import load_config_sheet
        _cfg_weights = load_config_sheet(excel_data)
        st.session_state["_vhs_weights"] = _cfg_weights
    except Exception:
        pass

    # ── 검증기 자동 실행 ────────────────────────────────
    st.session_state["_uploaded_sheets"] = excel_data
    try:
        from sample_validator import validate_excel
        _vr = validate_excel(excel_data)
        if _vr.level == "오류":
            from dashboard_pages import show_friendly_error
            st.error("⚠️ " + "; ".join(m for l,m in _vr.messages if l=="오류"))
            with st.expander("상세 검증 결과"):
                from sample_validator import render_validation_result
                render_validation_result(_vr)
            return
        elif _vr.level == "주의":
            st.session_state["_validation_warning"] = _vr   # 대시보드 하단에 표시
    except Exception:
        pass

    stores = excel_data["stores"]
    products = excel_data["products"]
    inventory = excel_data["inventory"]
    routes = excel_data["routes"]

    # 수요 분석용 products_df 세션 저장
    st.session_state["_products_df"] = products

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
    # 자동 분석 조건
    # =========================
    (
        departure_time,
        promotion_type,
        promotion_discount_rate,
        promotion_sales_increase_rate,
        promotion_fixed_cost,
        analysis_condition_summary,
    ) = auto_determine_analysis_conditions(
        excel_data,
        stores,
        products,
        inventory,
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("자동 분석")
    st.sidebar.success("분석 조건 자동 적용")

    with st.sidebar.expander("자동 적용값 보기", expanded=False):
        st.write(f"출발 시간: **{analysis_condition_summary['departure_time']}**")
        st.write(f"프로모션 유형: **{analysis_condition_summary['promotion_type']}**")
        st.write(f"할인율: **{analysis_condition_summary['promotion_discount_rate']}%**")
        st.write(f"예상 판매 증가율: **{analysis_condition_summary['promotion_sales_increase_rate']}%**")
        st.write(f"고정비: **{analysis_condition_summary['promotion_fixed_cost']:,}원**")

    st.sidebar.markdown("---")
    st.sidebar.subheader("속도 최적화")

    fast_mode_default = len(inventory) > 3000 or len(routes) > 1500

    fast_mode = st.sidebar.checkbox(
        "빠른 분석 모드",
        value=fast_mode_default,
        key="fast_mode_excel",
    )

    _inv_max = max(len(inventory), 301)   # min_value=300 보다 항상 크게
    _rte_max = max(len(routes),    301)

    max_inventory_rows = st.sidebar.slider(
        "분석할 재고 후보 수",
        min_value=300,
        max_value=min(_inv_max, 6000),
        value=min(1500, _inv_max),
        step=100,
        key="fast_inventory_limit",
        disabled=not fast_mode,
    )

    max_routes = st.sidebar.slider(
        "분석할 경로 후보 수",
        min_value=300,
        max_value=min(_rte_max, 4000),
        value=min(1200, _rte_max),
        step=100,
        key="fast_route_limit",
        disabled=not fast_mode,
    )

    # =========================
    # 분석 계산 (session_state 우선 — 버튼 클릭 시 재계산 불필요)
    # =========================
    import hashlib as _hl

    # 파일 변경 감지용 빠른 해시 (DataFrame 전체 해싱보다 20배 빠름)
    def _quick_hash(*dfs):
        key = "|".join(
            f"{len(d)}{list(d.columns)[:3]}"
            for d in dfs if d is not None and not d.empty
        )
        return _hl.md5(key.encode()).hexdigest()[:12]

    _file_hash = _quick_hash(stores, products, inventory, routes)
    _state_key  = "_analysis_result"
    _hash_key   = "_analysis_file_hash"

    _need_recompute = (
        _state_key not in st.session_state
        or st.session_state.get(_hash_key) != _file_hash
    )

    if _need_recompute:
        with st.spinner("📊 Varo 분석 중… (첫 실행, 잠시만 기다려주세요)"):
            _result = cached_excel_analysis(
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
        st.session_state[_state_key] = _result
        st.session_state[_hash_key]  = _file_hash
        # 새 분석 결과 → 선택 후보를 1순위로 리셋
        st.session_state.pop("dashboard_selected_candidate_index", None)

    analysis_result = st.session_state[_state_key]

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

    # ── 캐시 밖에서 session_state 복원 ─────────────────
    st.session_state["_routes"] = analysis_routes
    try:
        from min_cost_network import analyze_min_cost_network
        if analysis_inventory is not None and analysis_stores is not None and analysis_routes is not None:
            flow_df, node_df, net_summary = _cached_network(
                analysis_inventory, analysis_stores, analysis_routes
            )
            st.session_state["_network_flow_df"] = flow_df
            st.session_state["_network_node_df"] = node_df
            st.session_state["_network_summary"] = net_summary
    except Exception:
        pass
    try:
        from store_clustering import add_cluster_to_recommendations
        _, _, cluster_map = _cached_clustering(analysis_stores, analysis_inventory)
        st.session_state["_cluster_map"] = cluster_map
    except Exception:
        pass

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
