"""
dqn_stability.py
─────────────────
DQN 학습 결과 안정성 평가 모듈.

- 기존 Varo Hybrid Score / 추천 로직 미수정
- DQN 결과가 불안정할 때 안전하게 제외 또는 참고 처리
- 상태: 정상 / 주의 / 제외 / 데이터 없음
"""

import math
import os
import json
import numpy as np
import pandas as pd

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 안정성 기준값 (한 곳에서 관리)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_default_dqn_stability_rules() -> dict:
    """DQN 안정성 판단 기준값 반환."""
    return {
        "min_episodes":           10,         # 최소 에피소드 수
        "max_final_loss":         1_000_000,  # 최종 loss 상한
        "max_loss_spike_ratio":   200,        # max_loss / final_loss 비율 상한
        "min_valid_reward":      -1_000_000,  # 최소 reward 하한
        "max_single_action_ratio": 0.95,      # 단일 action 집중 비율 상한
        "epsilon_min":             0.0,       # epsilon 최솟값
        "epsilon_max":             1.0,       # epsilon 최댓값
        "min_recommendations":     1,         # 최소 추천 결과 수
    }

_RULES = get_default_dqn_stability_rules()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 안전 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def safe_format_metric(value, decimals: int = 4, large_threshold: float = 1e6) -> str:
    """NaN / inf / 큰 숫자를 안전한 문자열로 변환."""
    try:
        f = float(value)
        if math.isnan(f):   return "이상치"
        if math.isinf(f):   return "이상치"
        if abs(f) > large_threshold:
            return f"{f:.2e} ⚠"
        return f"{f:.{decimals}f}"
    except (TypeError, ValueError):
        return str(value) if value is not None else "-"

def is_valid_loss(value) -> bool:
    """loss 값이 유효한지 확인."""
    try:
        f = float(value)
        return not (math.isnan(f) or math.isinf(f) or f > _RULES["max_final_loss"])
    except (TypeError, ValueError):
        return False

def is_valid_reward(value) -> bool:
    """reward 값이 유효한지 확인."""
    try:
        f = float(value)
        return not (math.isnan(f) or math.isinf(f) or f < _RULES["min_valid_reward"])
    except (TypeError, ValueError):
        return False

def detect_loss_outlier(history_df: pd.DataFrame) -> dict:
    """history CSV에서 loss 이상치 감지."""
    if history_df is None or history_df.empty:
        return {"has_outlier": False, "max_loss": None, "final_loss": None, "spike_ratio": None}
    try:
        loss_col = next((c for c in history_df.columns if "loss" in c.lower()), None)
        if not loss_col:
            return {"has_outlier": False, "max_loss": None, "final_loss": None, "spike_ratio": None}
        losses = pd.to_numeric(history_df[loss_col], errors="coerce").dropna()
        if losses.empty:
            return {"has_outlier": False, "max_loss": None, "final_loss": None, "spike_ratio": None}
        max_l   = float(losses.max())
        final_l = float(losses.iloc[-1])
        spike   = (max_l / final_l) if final_l > 0 else float("inf")
        return {
            "has_outlier": spike > _RULES["max_loss_spike_ratio"],
            "max_loss":    round(max_l, 4),
            "final_loss":  round(final_l, 4),
            "spike_ratio": round(spike, 2),
        }
    except Exception:
        return {"has_outlier": False, "max_loss": None, "final_loss": None, "spike_ratio": None}

def clean_loss_for_chart(history_df: pd.DataFrame,
                         clip_quantile: float = 0.99) -> pd.DataFrame:
    """그래프 렌더링을 위해 이상치 loss 값을 클리핑."""
    if history_df is None or history_df.empty:
        return history_df
    df = history_df.copy()
    loss_col = next((c for c in df.columns if "loss" in c.lower()), None)
    if not loss_col:
        return df
    loss_s = pd.to_numeric(df[loss_col], errors="coerce")
    q99 = float(loss_s.quantile(clip_quantile))
    df[f"{loss_col}_display"] = loss_s.clip(upper=q99)
    return df

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. action 분포 점검
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_dqn_action_distribution(rec_df: pd.DataFrame) -> dict:
    """
    DQN 추천 DataFrame의 action 분포 분석.
    action 컬럼명 자동 감지.
    """
    if rec_df is None or rec_df.empty:
        return {"status": "데이터 없음", "distribution": {}, "dominant_ratio": None}

    action_col = next(
        (c for c in ["dqn_action", "dqn_recommended_action", "dqn_label"]
         if c in rec_df.columns), None
    )
    if not action_col:
        return {"status": "데이터 없음", "distribution": {}, "dominant_ratio": None}

    vc      = rec_df[action_col].value_counts()
    total   = len(rec_df)
    dist    = {str(k): int(v) for k, v in vc.items()}
    dom_r   = float(vc.iloc[0] / total) if not vc.empty else 0.0

    status = "정상"
    if dom_r >= _RULES["max_single_action_ratio"]:
        status = "주의"

    return {
        "status":         status,
        "distribution":   dist,
        "dominant_action":str(vc.index[0]) if not vc.empty else "-",
        "dominant_ratio": round(dom_r, 4),
        "total":          total,
        "action_col":     action_col,
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 안정성 평가
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def evaluate_dqn_training_stability(
    summary:         dict            = None,
    history_df:      pd.DataFrame    = None,
    recommendation_df: pd.DataFrame  = None,
) -> list:
    """
    DQN 안정성 체크 항목 리스트 반환.
    각 항목: {check_name, status, value, threshold, passed, note}
    """
    rules   = get_default_dqn_stability_rules()
    checks  = []
    inner   = {}
    if summary:
        inner = summary.get("summary", summary)

    def _add(name, status, val, thr, passed, note=""):
        checks.append({
            "check_name": name,
            "status":     status,
            "value":      safe_format_metric(val) if isinstance(val, (int, float)) else str(val),
            "threshold":  str(thr),
            "passed":     "✅" if passed else "❌",
            "note":       note,
        })

    # 1. 파일 존재
    has_summary = bool(summary)
    has_history = history_df is not None and not history_df.empty
    has_recs    = recommendation_df is not None and not recommendation_df.empty
    _add("summary 파일", "정상" if has_summary else "제외",
         "존재" if has_summary else "없음", "필수", has_summary)
    _add("history 파일", "정상" if has_history else "주의",
         "존재" if has_history else "없음", "권장", has_history)
    _add("추천 결과 파일", "정상" if has_recs else "제외",
         "존재" if has_recs else "없음", "필수", has_recs)

    # 2. 에피소드 수
    ep = None
    if has_history:
        ep_col = next((c for c in history_df.columns if "episode" in c.lower()), None)
        if ep_col:
            ep = int(history_df[ep_col].max())
        else:
            ep = len(history_df)
    if ep is None and inner:
        ep = inner.get("episodes")
    ep_ok = (ep is not None and ep >= rules["min_episodes"])
    _add("에피소드 수", "정상" if ep_ok else "제외",
         ep if ep is not None else "알 수 없음",
         f">= {rules['min_episodes']}", ep_ok)

    # 3. final_loss
    fl = None
    if inner:
        fl = inner.get("final_loss")
    elif has_history:
        loss_col = next((c for c in history_df.columns if "loss" in c.lower()), None)
        if loss_col:
            fl = pd.to_numeric(history_df[loss_col], errors="coerce").iloc[-1]
    fl_ok = is_valid_loss(fl)
    _add("최종 loss", "정상" if fl_ok else "제외",
         fl if fl is not None else "없음",
         f"< {rules['max_final_loss']:.0e}", fl_ok,
         "" if fl_ok else "NaN/inf/비정상 큰 값")

    # 4. loss spike
    spike_info = detect_loss_outlier(history_df)
    spike_ok = not spike_info["has_outlier"]
    _add("loss 이상치", "정상" if spike_ok else "주의",
         spike_info.get("spike_ratio", "-"),
         f"< {rules['max_loss_spike_ratio']}", spike_ok,
         f"max={spike_info.get('max_loss','-')}" if not spike_ok else "")

    # 5. reward
    rw = None
    if has_history:
        rw_col = next((c for c in history_df.columns if "reward" in c.lower()), None)
        if rw_col:
            rw = float(pd.to_numeric(history_df[rw_col], errors="coerce").mean())
    elif inner:
        rw = inner.get("mean_reward") or inner.get("final_reward")
    rw_ok = (rw is None) or is_valid_reward(rw)  # 없으면 통과
    _add("평균 reward", "정상" if rw_ok else "주의",
         round(rw, 4) if rw is not None else "없음",
         f"> {rules['min_valid_reward']:.0e}", rw_ok)

    # 6. epsilon (있을 때만)
    eps = inner.get("final_epsilon") if inner else None
    if eps is not None:
        eps_ok = (rules["epsilon_min"] <= float(eps) <= rules["epsilon_max"])
        _add("epsilon", "정상" if eps_ok else "주의",
             round(float(eps), 4), f"{rules['epsilon_min']}~{rules['epsilon_max']}", eps_ok)

    # 7. action 분포
    action_info = get_dqn_action_distribution(recommendation_df)
    action_ok = (action_info["status"] != "주의")
    if action_info.get("dominant_ratio") is not None:
        _add("action 집중도", action_info["status"],
             f"{action_info.get('dominant_action','-')} {action_info.get('dominant_ratio',0):.1%}",
             f"< {rules['max_single_action_ratio']:.0%}", action_ok,
             str(action_info.get("distribution", {})))

    return checks


def classify_dqn_status(checks: list) -> str:
    """
    체크 결과 리스트 → DQN 상태 분류.
    정상 / 주의 / 제외 / 데이터 없음
    """
    if not checks:
        return "데이터 없음"
    statuses = [c["status"] for c in checks]
    failed   = [c for c in checks if c["passed"] == "❌"]
    critical = [c for c in failed if c["status"] == "제외"]
    if critical:
        return "제외"
    if failed:
        return "주의"
    if all(s == "정상" for s in statuses):
        return "정상"
    return "주의"


def format_dqn_status_for_display(status: str) -> str:
    """상태 문자열 → UI 표시용 이모지 포함 문자열."""
    return {
        "정상":      "✅ 정상",
        "주의":      "⚠️ 주의",
        "제외":      "🚫 제외",
        "데이터 없음":"⬜ 데이터 없음",
    }.get(status, f"❓ {status}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 전체 평가 통합 함수
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_dqn_stability_check(artifact_dir: str = "dqn_artifacts") -> dict:
    """
    dqn_artifacts 폴더에서 파일 로드 후 안정성 평가.
    반환: {status, status_display, checks, summary, history_df, rec_df, action_info}
    """
    # 파일 로드
    summary = {}
    try:
        p = os.path.join(artifact_dir, "dqn_latest_summary.json")
        if os.path.exists(p):
            raw = json.load(open(p, encoding="utf-8"))
            summary = raw.get("summary", raw)
    except Exception:
        pass

    history_df = pd.DataFrame()
    try:
        p = os.path.join(artifact_dir, "dqn_latest_history.csv")
        if os.path.exists(p):
            history_df = pd.read_csv(p, encoding="utf-8-sig")
    except Exception:
        pass

    rec_df = pd.DataFrame()
    try:
        p = os.path.join(artifact_dir, "dqn_latest_recommendations.csv")
        if os.path.exists(p):
            rec_df = pd.read_csv(p, encoding="utf-8-sig")
    except Exception:
        pass

    if not summary and history_df.empty and rec_df.empty:
        return {
            "status":         "데이터 없음",
            "status_display": format_dqn_status_for_display("데이터 없음"),
            "checks":         [],
            "summary":        {},
            "history_df":     pd.DataFrame(),
            "rec_df":         pd.DataFrame(),
            "action_info":    {},
            "spike_info":     {},
        }

    checks   = evaluate_dqn_training_stability(summary, history_df, rec_df)
    status   = classify_dqn_status(checks)
    action_i = get_dqn_action_distribution(rec_df)
    spike_i  = detect_loss_outlier(history_df)

    return {
        "status":         status,
        "status_display": format_dqn_status_for_display(status),
        "checks":         checks,
        "summary":        summary,
        "history_df":     history_df,
        "rec_df":         rec_df,
        "action_info":    action_i,
        "spike_info":     spike_i,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 다운로드용 요약 DataFrame
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_stability_summary_df(stability_result: dict) -> pd.DataFrame:
    """안정성 체크 결과 → CSV 다운로드용 DataFrame."""
    if not stability_result or not stability_result.get("checks"):
        return pd.DataFrame()
    checks = stability_result["checks"]
    df = pd.DataFrame(checks)
    return df[["check_name","status","value","threshold","passed","note"]]
