"""
varo_score_config.py
─────────────────────
Varo Hybrid Score 가중치·등급 기준 중앙 관리 모듈.

- 기존 varo_hybrid_score.py / varo_score_v2.py 계산 로직은 유지.
- 이 모듈은 가중치 관리, 정규화 유틸, 등급 기준, config 시트 연동을 담당.
"""

import math
import numpy as np
import pandas as pd

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. VHS v2 기본 가중치 (scenario_detector가 상황별로 조정)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEFAULT_VHS_WEIGHTS: dict = {
    "재고위험":      0.25,
    "판매가능성":    0.20,
    "점포이동적합":  0.15,
    "비용절감":      0.15,
    "폐기회피이익":  0.10,
    "실행가능성":    0.10,
    "이력보정":      0.05,
}
# 합계 검증용
_VHS_WEIGHT_SUM = sum(DEFAULT_VHS_WEIGHTS.values())  # 1.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 추천 등급 기준 (VHS v2 기준)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GRADE_THRESHOLDS: dict = {
    "최적": 80,    # 80점 이상
    "권장": 65,    # 65점 이상
    "검토": 50,    # 50점 이상
    "보류":  0,    # 50점 미만
}

def assign_recommendation_grade(score) -> str:
    """
    VHS 점수 → 추천 등급.
    기존 varo_score_v2.py 등급(최적/권장/검토)에 '보류' 추가.
    """
    try:
        s = float(score)
        if math.isnan(s): return "검토"
    except (TypeError, ValueError):
        return "검토"
    if s >= GRADE_THRESHOLDS["최적"]: return "최적"
    if s >= GRADE_THRESHOLDS["권장"]: return "권장"
    if s >= GRADE_THRESHOLDS["검토"]: return "검토"
    return "보류"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 점수 구성 기준표 (UI 표시용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORE_CRITERIA: list = [
    {
        "항목":     "재고 위험",
        "가중치":   "25%",
        "반영 기준":"과잉·악성재고 가능성 (폐기위험·회전율·ABC·노후화)",
        "점수 방향":"높을수록 위험",
        "관련 알고리즘":"disposal_risk, turnover, abc, aging",
        "계산 가능": True,
    },
    {
        "항목":     "판매 가능성",
        "가중치":   "20%",
        "반영 기준":"수요 예측·판매 추세·Newsvendor",
        "점수 방향":"높을수록 판매 기대",
        "관련 알고리즘":"demand_forecast, trend, newsvendor",
        "계산 가능": True,
    },
    {
        "항목":     "점포 이동 적합",
        "가중치":   "15%",
        "반영 기준":"수신 점포 매칭·서비스 수준·우선순위",
        "점수 방향":"높을수록 이동 적합",
        "관련 알고리즘":"match, service_level, priority_queue, queue_capacity",
        "계산 가능": True,
    },
    {
        "항목":     "비용 절감",
        "가중치":   "15%",
        "반영 기준":"이동비용·LP 수송 비용·EOQ 이탈도",
        "점수 방향":"낮은 비용 = 높은 점수",
        "관련 알고리즘":"heuristic(비용), transport_lp, eoq",
        "계산 가능": True,
    },
    {
        "항목":     "폐기 회피 이익",
        "가중치":   "10%",
        "반영 기준":"폐기 회피 가능성·할인 민감도",
        "점수 방향":"높을수록 폐기 회피 가능",
        "관련 알고리즘":"disposal_avoidance, discount_sensitivity",
        "계산 가능": True,
    },
    {
        "항목":     "실행 가능성",
        "가중치":   "10%",
        "반영 기준":"병목·점포 처리 능력·카테고리 균형",
        "점수 방향":"높을수록 실행 용이",
        "관련 알고리즘":"bottleneck, store_capacity, category_balance",
        "계산 가능": True,
    },
    {
        "항목":     "이력 보정",
        "가중치":   "5%",
        "반영 기준":"DQN reward 기반 ±8점 보정",
        "점수 방향":"누적 데이터 기반 보정",
        "관련 알고리즘":"reward (RL 학습 결과)",
        "계산 가능": True,
    },
]

def get_score_criteria_df() -> pd.DataFrame:
    """점수 기준표 DataFrame 반환."""
    cols = ["항목", "가중치", "반영 기준", "점수 방향", "관련 알고리즘"]
    return pd.DataFrame([{c: r[c] for c in cols} for r in SCORE_CRITERIA])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 정규화 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def safe_number(value, default: float = 0.0) -> float:
    """NaN / None / inf → default 반환."""
    try:
        f = float(value)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def normalize_score(value, min_value: float = 0.0, max_value: float = 100.0,
                    inverse: bool = False, default: float = 50.0) -> float:
    """
    [min_value, max_value] → [0, 100] 정규화.
    inverse=True: 낮을수록 좋은 값(비용 등)은 역방향 처리.
    """
    v = safe_number(value, default)
    mn = safe_number(min_value, 0.0)
    mx = safe_number(max_value, 100.0)
    if mx <= mn:
        return default
    norm = (v - mn) / (mx - mn) * 100.0
    norm = max(0.0, min(100.0, norm))
    return round(100.0 - norm if inverse else norm, 2)

def normalize_weights(weights: dict, default: dict = None) -> dict:
    """
    가중치 dict → 합계 1.0으로 정규화.
    합계 0 또는 잘못된 값 → default 반환.
    """
    default = default or DEFAULT_VHS_WEIGHTS
    try:
        cleaned = {}
        for k, v in weights.items():
            sv = safe_number(v, -1)
            if sv >= 0:
                cleaned[k] = sv
        total = sum(cleaned.values())
        if total <= 0:
            return dict(default)
        return {k: round(v / total, 6) for k, v in cleaned.items()}
    except Exception:
        return dict(default)

def calculate_weighted_score(score_components: dict, weights: dict,
                              default_score: float = 50.0) -> float:
    """
    항목별 점수 dict + 가중치 dict → 가중 합산 점수.
    누락 항목은 default_score 사용.
    """
    total = 0.0
    w_sum = 0.0
    for k, w in weights.items():
        if k == "이력보정":
            continue  # 이력 보정은 별도 처리
        score = safe_number(score_components.get(k, default_score), default_score)
        w_val = safe_number(w, 0.0)
        total += score * w_val
        w_sum += w_val
    if w_sum <= 0:
        return default_score
    return round(total / w_sum, 2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. config 시트 연동
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIG_WEIGHT_KEYS = list(DEFAULT_VHS_WEIGHTS.keys())

def load_weights_from_config(config_df: pd.DataFrame = None) -> dict:
    """
    config DataFrame (key|value 구조)에서 가중치 읽기.
    없거나 유효하지 않으면 DEFAULT_VHS_WEIGHTS 반환.

    config 엑셀 시트 예시:
        key                  | value
        재고위험              | 0.25
        판매가능성            | 0.20
        점포이동적합          | 0.15
        비용절감              | 0.15
        폐기회피이익          | 0.10
        실행가능성            | 0.10
        이력보정              | 0.05
    """
    if config_df is None or config_df.empty:
        return dict(DEFAULT_VHS_WEIGHTS)

    try:
        # key/value 컬럼 자동 감지
        col_key = next((c for c in config_df.columns
                        if str(c).lower() in ("key","항목","가중치항목","name")), None)
        col_val = next((c for c in config_df.columns
                        if str(c).lower() in ("value","값","가중치","weight")), None)
        if col_key is None or col_val is None:
            return dict(DEFAULT_VHS_WEIGHTS)

        raw = {}
        for _, row in config_df.iterrows():
            k = str(row[col_key]).strip()
            if k in CONFIG_WEIGHT_KEYS:
                raw[k] = safe_number(row[col_val], -1)

        # 하나도 없으면 기본값
        valid = {k: v for k, v in raw.items() if v >= 0}
        if not valid:
            return dict(DEFAULT_VHS_WEIGHTS)

        # 누락 키는 DEFAULT로 채움
        merged = dict(DEFAULT_VHS_WEIGHTS)
        merged.update(valid)
        return normalize_weights(merged, DEFAULT_VHS_WEIGHTS)

    except Exception:
        return dict(DEFAULT_VHS_WEIGHTS)


def load_config_sheet(excel_sheets: dict) -> dict:
    """
    업로드된 엑셀 시트 dict에서 'config' 시트를 찾아 가중치 로드.
    없으면 기본값 반환.
    """
    cfg_sheet = None
    for name in excel_sheets:
        if str(name).lower() in ("config", "설정", "가중치", "weight", "weights"):
            cfg_sheet = excel_sheets[name]
            break
    return load_weights_from_config(cfg_sheet)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 검증 정보 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_weight_diagnostics(weights: dict, result_df: pd.DataFrame = None) -> dict:
    """
    현재 사용 중인 가중치 진단 정보 반환.
    접힌 영역에서 표시하기 위한 검증 데이터.
    """
    w_sum = round(sum(safe_number(v, 0) for v in weights.values()), 6)
    is_default = (weights == DEFAULT_VHS_WEIGHTS)
    is_normalized = abs(w_sum - 1.0) < 0.001

    fallback_cols = 0
    computable_count = 0
    if result_df is not None and not result_df.empty:
        score_cols = [col for _, algo_list in [
            ("재고위험",     ["disposal_risk_score","turnover_score","abc_score","aging_score"]),
            ("판매가능성",   ["demand_forecast_score","trend_score","newsvendor_score"]),
            ("점포이동적합", ["match_score","service_level_score","priority_queue_score"]),
            ("비용절감",     ["heuristic_score","transport_lp_score","eoq_score"]),
            ("폐기회피이익", ["disposal_avoidance_score","discount_sensitivity_score"]),
            ("실행가능성",   ["bottleneck_score","store_capacity_score","category_balance_score"]),
        ] for col in algo_list]
        fallback_cols = sum(1 for c in score_cols if c not in result_df.columns)
        computable_count = len(result_df)

    return {
        "가중치_합계":        w_sum,
        "정규화_여부":        "✅" if is_normalized else f"⚠️ {w_sum:.4f}",
        "기본값_사용":        "기본값" if is_default else "사용자 정의",
        "추천_등급_기준":     {k: f"{v}점 이상" if v > 0 else f"{v}점 미만"
                              for k, v in GRADE_THRESHOLDS.items()},
        "계산_가능_후보_수":  computable_count,
        "fallback_컬럼_수":  fallback_cols,
        "가중치_상세":        {k: f"{v:.1%}" for k, v in weights.items()},
    }
