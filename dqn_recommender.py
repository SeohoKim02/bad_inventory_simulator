"""
dqn_recommender.py
──────────────────
DQN 추론 결과를 Varo 최종 추천 후보와 연결하는 모듈.

- DQN 모델 로딩 (dqn_artifacts/dqn_latest_*)
- 후보별 per-candidate inference
- Heuristic / Greedy / DQN / Varo 비교 테이블 생성
- agreement_status 계산
"""

import os
import json
import numpy as np
import pandas as pd

# ── 경로 상수 ────────────────────────────────────────────────
DQN_ARTIFACT_DIR = "dqn_artifacts"
LATEST_MODEL_NPZ = os.path.join(DQN_ARTIFACT_DIR, "dqn_latest_model.npz")
LATEST_SUMMARY   = os.path.join(DQN_ARTIFACT_DIR, "dqn_latest_summary.json")
LATEST_RECS      = os.path.join(DQN_ARTIFACT_DIR, "dqn_latest_recommendations.csv")
LATEST_HISTORY   = os.path.join(DQN_ARTIFACT_DIR, "dqn_latest_history.csv")

# ── DQN Action ↔ Varo 전략 매핑 ─────────────────────────────
DQN_ACTION_MAP = {
    "keep_inventory":     {"label": "재고 유지",    "varo": "보류"},
    "discount_sale":      {"label": "할인 판매",    "varo": "할인 판매"},
    "one_plus_one":       {"label": "1+1 프로모션", "varo": "1+1 프로모션"},
    "direct_transfer":    {"label": "직접 이동",    "varo": "재배치"},
    "dc_transfer":        {"label": "DC 경유 이동", "varo": "재배치"},
    "emergency_discount": {"label": "긴급 할인",    "varo": "할인 판매"},
    "dispose":            {"label": "폐기",         "varo": "폐기"},
}

DQN_ACTION_SPACE = [
    "keep_inventory", "discount_sale", "one_plus_one",
    "direct_transfer", "dc_transfer", "emergency_discount", "dispose",
]

STATE_COLS = [
    "state_source_stock", "state_target_stock",
    "state_source_sales_30d", "state_target_sales_30d",
    "state_inbound_days", "state_unit_cost",
    "state_distance_km", "state_transfer_cost",
    "state_promotion_net_cost",
]

SCALE = {
    "state_source_stock":       500.0,
    "state_target_stock":       500.0,
    "state_source_sales_30d":  1000.0,
    "state_target_sales_30d":  1000.0,
    "state_inbound_days":        90.0,
    "state_unit_cost":         5000.0,
    "state_distance_km":         20.0,
    "state_transfer_cost":    10000.0,
    "state_promotion_net_cost": 5000.0,
}


# ── 유틸 ──────────────────────────────────────────────────────
def _dqn_label(action_str: str) -> str:
    return DQN_ACTION_MAP.get(str(action_str), {}).get("label", str(action_str))

def _dqn_varo(action_str: str) -> str:
    return DQN_ACTION_MAP.get(str(action_str), {}).get("varo", "기타")

def _safe_loss(val) -> str:
    """비정상 loss 값을 안전한 문자열로 변환."""
    try:
        f = float(val)
        if f != f or f in (float("inf"), float("-inf")):
            return "이상치"
        if abs(f) > 1_000_000:
            return f"{f:.2e} ⚠"
        return f"{f:.5f}"
    except Exception:
        return str(val)


# ── DQN 모델 로딩 ─────────────────────────────────────────────
def load_latest_summary() -> dict:
    try:
        if not os.path.exists(LATEST_SUMMARY):
            return {}
        with open(LATEST_SUMMARY, "r", encoding="utf-8") as f:
            raw = json.load(f)
        inner = raw.get("summary", raw)
        if "final_loss" in inner:
            inner["final_loss_display"] = _safe_loss(inner["final_loss"])
        return inner
    except Exception:
        return {}

def load_latest_history() -> pd.DataFrame:
    try:
        if not os.path.exists(LATEST_HISTORY):
            return pd.DataFrame()
        return pd.read_csv(LATEST_HISTORY, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()

def load_latest_dqn_recs() -> pd.DataFrame:
    try:
        if not os.path.exists(LATEST_RECS):
            return pd.DataFrame()
        return pd.read_csv(LATEST_RECS, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()

def _load_model_bundle() -> dict:
    """
    dqn_latest_model.npz 로딩.
    dqn_agent.py 기반 (W1,b1,W2,b2) 또는
    torch_dqn_agent.py 기반 (W1,b1,W2,b2,W3,b3) 모두 지원.
    반환: {weights, action_labels, feature_names, n_features, n_actions}
    """
    try:
        if not os.path.exists(LATEST_MODEL_NPZ):
            return {}
        data = np.load(LATEST_MODEL_NPZ, allow_pickle=True)
        keys = list(data.files)

        # metadata에서 action_labels / feature_names 파싱
        action_labels, feature_names = [], []
        if "metadata" in keys:
            try:
                meta = json.loads(str(data["metadata"]))
                action_labels  = meta.get("action_labels",  [])
                feature_names  = meta.get("feature_names",  [])
            except Exception:
                pass

        # weights 추출
        if all(k in keys for k in ["W1","b1","W2","b2","W3","b3"]):
            w = {k: data[k].astype(np.float32)
                 for k in ["W1","b1","W2","b2","W3","b3"]}
            n_features = w["W1"].shape[0]
            n_actions  = w["W3"].shape[1]
        elif all(k in keys for k in ["W1","b1","W2","b2"]):
            w = {k: data[k].astype(np.float32)
                 for k in ["W1","b1","W2","b2"]}
            n_features = w["W1"].shape[0]
            n_actions  = w["W2"].shape[1]
        else:
            return {}

        return {
            "weights":       w,
            "action_labels": action_labels or [str(i) for i in range(n_actions)],
            "feature_names": feature_names,
            "n_features":    n_features,
            "n_actions":     n_actions,
        }
    except Exception:
        return {}

def _forward(weights: dict, x: np.ndarray) -> np.ndarray:
    """W1,b1,W2,b2 (2-layer) or W1..W3,b1..b3 (3-layer) 자동 전환."""
    h = np.maximum(0, x @ weights["W1"] + weights["b1"])
    if "W3" in weights:
        h = np.maximum(0, h @ weights["W2"] + weights["b2"])
        return h @ weights["W3"] + weights["b3"]
    return h @ weights["W2"] + weights["b2"]


# ── 후보별 DQN 추론 ───────────────────────────────────────────
def infer_dqn_per_candidate(df: pd.DataFrame) -> pd.DataFrame:
    """
    최종 추천 후보 DataFrame에 대해 per-candidate DQN 추론.
    dqn_agent.py 기반 8-feature/4-action 모델을 _make_state_features로 입력.
    """
    df = df.copy()
    bundle = _load_model_bundle()

    if not bundle:
        df["dqn_action"]   = "비교 불가"
        df["dqn_label"]    = "-"
        df["dqn_strategy"] = "-"
        df["dqn_max_q"]    = None
        df["dqn_infer_ok"] = False
        return df

    weights       = bundle["weights"]
    action_labels = bundle["action_labels"]   # 예: ["재고 이동","할인","폐기","보류"]
    n_features    = bundle["n_features"]      # 8 or 9

    # state feature 행렬 빌드 (dqn_agent._make_state_features 재사용)
    try:
        from dqn_agent import _make_state_features
        X, _ = _make_state_features(df)
        if X.shape[1] != n_features:
            # feature 수 불일치: 앞 n_features 열 사용 or zero-pad
            if X.shape[1] > n_features:
                X = X[:, :n_features]
            else:
                pad = np.zeros((len(df), n_features - X.shape[1]), dtype=np.float32)
                X = np.hstack([X, pad])
        X = X.astype(np.float32)
    except Exception:
        df["dqn_action"]   = "비교 불가"
        df["dqn_label"]    = "-"
        df["dqn_strategy"] = "-"
        df["dqn_max_q"]    = None
        df["dqn_infer_ok"] = False
        return df

    dqn_actions, dqn_labels, dqn_strategies, dqn_qs, dqn_ok = [], [], [], [], []

    for i in range(len(X)):
        try:
            q  = _forward(weights, X[i])
            ai = int(np.argmax(q))
            label = action_labels[ai] if ai < len(action_labels) else str(ai)
            # 4-action 모델 레이블 → DQN_ACTION_MAP varo 전략 매핑
            label_to_action = {
                "재고 이동": "direct_transfer",
                "할인":     "discount_sale",
                "폐기":     "dispose",
                "보류":     "keep_inventory",
            }
            action_key = label_to_action.get(label, label)
            dqn_actions.append(action_key)
            dqn_labels.append(label)
            dqn_strategies.append(_dqn_varo(action_key))
            dqn_qs.append(round(float(q.max()), 4))
            dqn_ok.append(True)
        except Exception:
            dqn_actions.append("비교 불가")
            dqn_labels.append("-")
            dqn_strategies.append("-")
            dqn_qs.append(None)
            dqn_ok.append(False)

    df["dqn_action"]   = dqn_actions
    df["dqn_label"]    = dqn_labels
    df["dqn_strategy"] = dqn_strategies
    df["dqn_max_q"]    = dqn_qs
    df["dqn_infer_ok"] = dqn_ok
    return df


# ── agreement 계산 ────────────────────────────────────────────
def _normalize_strategy(s: str) -> str:
    """전략 문자열을 비교용 그룹으로 정규화."""
    s = str(s).lower()
    if any(k in s for k in ["이동", "재배치", "transfer", "direct", "dc"]):
        return "재배치"
    if any(k in s for k in ["할인", "discount", "1+1", "one_plus", "promo"]):
        return "할인"
    if any(k in s for k in ["폐기", "dispose"]):
        return "폐기"
    if any(k in s for k in ["보류", "유지", "keep"]):
        return "보류"
    return "기타"

def _get_agreement_status(varo_strategy: str, dqn_strategy: str,
                          heuristic_strategy: str, greedy_strategy: str) -> str:
    if dqn_strategy in ("-", "비교 불가", "기타"):
        return "비교 불가"
    v = _normalize_strategy(varo_strategy)
    d = _normalize_strategy(dqn_strategy)
    h = _normalize_strategy(heuristic_strategy)
    g = _normalize_strategy(greedy_strategy)
    if v == d == h == g:
        return "전방위 일치"
    if v == d:
        return "DQN-Varo 일치"
    if d == h or d == g:
        return "DQN 부분 일치"
    return "불일치"


# ── 비교 테이블 생성 ──────────────────────────────────────────
def build_comparison_table(final_recommendations: pd.DataFrame) -> pd.DataFrame:
    """
    Heuristic / Greedy / DQN / Varo 비교 테이블 생성.
    DQN per-candidate 추론 + agreement_status 포함.
    """
    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame()

    df = final_recommendations.copy()

    # DQN inference
    df = infer_dqn_per_candidate(df)

    # Heuristic 전략 컬럼
    def _heuristic_strategy(row):
        fr = str(row.get("final_recommendation", ""))
        if any(k in fr for k in ["이동", "재배치"]): return "직접 이동"
        if any(k in fr for k in ["할인", "프로모션", "1+1"]): return "할인/프로모션"
        if "폐기" in fr: return "폐기"
        if "보류" in fr: return "보류"
        return str(row.get("heuristic_grade", fr))[:10] if fr else "-"

    df["heuristic_strategy"] = df.apply(_heuristic_strategy, axis=1)

    # Greedy 전략
    df["greedy_strategy"] = df.apply(
        lambda r: "선택" if bool(r.get("is_greedy_selected", False)) else "미선택", axis=1
    )

    # Varo (vhs2_action 우선, 없으면 final_recommendation)
    def _varo_strategy(row):
        a = str(row.get("vhs2_action", "") or "")
        if a and a not in ("nan", "-", ""):
            return a
        return _heuristic_strategy(row)
    df["varo_strategy"] = df.apply(_varo_strategy, axis=1)

    # agreement
    df["agreement_status"] = df.apply(
        lambda r: _get_agreement_status(
            r["varo_strategy"], r["dqn_strategy"],
            r["heuristic_strategy"], r["greedy_strategy"]
        ), axis=1
    )

    # dqn_agreement_bonus: Varo와 DQN이 일치하면 +1 (옵션 컬럼)
    df["dqn_agreement_bonus"] = df["agreement_status"].apply(
        lambda s: 1 if "일치" in s else 0
    )

    return df


def make_comparison_view(df: pd.DataFrame) -> pd.DataFrame:
    """비교 테이블의 화면 표시용 컬럼 선택 및 이름 변환."""
    col_map = {
        "product_name":      "상품명",
        "source_store":      "보내는 점포",
        "target_store":      "받는 점포",
        "suggested_qty":     "추천 수량",
        "estimated_cost":    "예상 비용",
        "heuristic_strategy":"Heuristic",
        "greedy_strategy":   "Greedy",
        "dqn_label":         "DQN",
        "varo_strategy":     "Varo 최종",
        "heuristic_score":   "총점",
        "heuristic_grade":   "등급",
        "agreement_status":  "일치 여부",
    }
    cols = [c for c in col_map if c in df.columns]
    view = df[cols].rename(columns=col_map).copy()

    if "예상 비용" in view.columns:
        def _fmt(v):
            try:
                n = float(str(v).replace(",", "").replace("원", ""))
                return f"{n:,.0f}원"
            except Exception:
                return str(v)
        view["예상 비용"] = view["예상 비용"].apply(_fmt)

    if "총점" in view.columns:
        view["총점"] = pd.to_numeric(view["총점"], errors="coerce").round(1).fillna(0)

    return view


def get_agreement_summary(comp_df: pd.DataFrame) -> dict:
    """agreement_status 집계."""
    if comp_df.empty or "agreement_status" not in comp_df.columns:
        return {}
    vc = comp_df["agreement_status"].value_counts().to_dict()
    total = len(comp_df)
    ok = sum(v for k, v in vc.items() if "일치" in k and k != "불일치" and "불일치" not in k)
    return {
        "total":        total,
        "agree_count":  ok,
        "agree_rate":   round(ok / total * 100, 1) if total else 0,
        "by_status":    vc,
    }
