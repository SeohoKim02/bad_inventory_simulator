
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ACTION_LABELS = ["재고 이동", "할인", "폐기", "보류"]


def _safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_str(value, default=""):
    try:
        if pd.isna(value):
            return default
        return str(value)
    except Exception:
        return default


def _classify_action(text):
    text = _safe_str(text)

    if any(k in text for k in ["이동", "재배치", "경유", "직접", "경로", "transfer"]):
        return "재고 이동"

    if any(k in text for k in ["할인", "프로모션", "1+1", "promotion", "discount"]):
        return "할인"

    if "폐기" in text or "disposal" in text or "waste" in text:
        return "폐기"

    return "보류"


def _merge_transfer_features(final_recommendations, transfer_path_result):
    df = final_recommendations.copy()

    if transfer_path_result is None or transfer_path_result.empty:
        return df

    t = transfer_path_result.copy()

    key_cols = ["product_name", "source_store", "target_store"]

    if not all(c in df.columns for c in key_cols) or not all(c in t.columns for c in key_cols):
        return df

    keep_cols = key_cols + [
        c for c in [
            "direct_cost",
            "via_cost",
            "estimated_cost",
            "direct_distance_km",
            "via_distance_km",
            "recommended_distance_km",
            "recommended_time_min",
            "sales_30d",
            "source_dead_stock_qty",
            "target_shortage_qty",
        ]
        if c in t.columns
    ]

    t = t[keep_cols].drop_duplicates(key_cols)

    return df.merge(t, on=key_cols, how="left", suffixes=("", "_transfer"))


def _normalize_series(series, default=0.0):
    s = pd.to_numeric(series, errors="coerce").fillna(default)

    if len(s) == 0:
        return s

    min_v = s.min()
    max_v = s.max()

    if pd.isna(min_v) or pd.isna(max_v) or max_v == min_v:
        return pd.Series([0.0] * len(s), index=s.index)

    return (s - min_v) / (max_v - min_v)


def _prepare_candidate_table(final_recommendations, transfer_path_result=None, sample_limit=500):
    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame()

    df = final_recommendations.copy()
    df = _merge_transfer_features(df, transfer_path_result)

    if "final_recommendation" not in df.columns:
        if "recommended_path" in df.columns:
            df["final_recommendation"] = df["recommended_path"]
        else:
            df["final_recommendation"] = "보류"

    if "heuristic_score" not in df.columns:
        df["heuristic_score"] = 50.0

    if "suggested_qty" not in df.columns:
        if "suggested_transfer_qty" in df.columns:
            df["suggested_qty"] = df["suggested_transfer_qty"]
        else:
            df["suggested_qty"] = 0

    if "estimated_cost" not in df.columns:
        if "estimated_cost_transfer" in df.columns:
            df["estimated_cost"] = df["estimated_cost_transfer"]
        elif "direct_cost" in df.columns:
            df["estimated_cost"] = df["direct_cost"]
        else:
            df["estimated_cost"] = 0

    for col in [
        "heuristic_score",
        "suggested_qty",
        "estimated_cost",
        "direct_cost",
        "via_cost",
        "direct_distance_km",
        "via_distance_km",
        "recommended_distance_km",
        "recommended_time_min",
        "sales_30d",
        "source_dead_stock_qty",
        "target_shortage_qty",
    ]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["greedy_action"] = df["final_recommendation"].apply(_classify_action)

    if "greedy_rank" in df.columns:
        df["_sort_rank"] = pd.to_numeric(df["greedy_rank"], errors="coerce").fillna(999999)
        df = df.sort_values(["_sort_rank", "heuristic_score"], ascending=[True, False])
    else:
        df = df.sort_values("heuristic_score", ascending=False)

    if sample_limit is not None and len(df) > int(sample_limit):
        df = df.head(int(sample_limit))

    return df.reset_index(drop=True)


def _make_state_features(df):
    if df.empty:
        return np.empty((0, 8), dtype=np.float64), []

    feature_frame = pd.DataFrame(index=df.index)

    feature_frame["score_norm"] = pd.to_numeric(df["heuristic_score"], errors="coerce").fillna(0) / 100.0
    feature_frame["qty_norm"] = _normalize_series(df["suggested_qty"])
    feature_frame["cost_norm"] = _normalize_series(df["estimated_cost"])
    feature_frame["direct_cost_norm"] = _normalize_series(df["direct_cost"])
    feature_frame["via_cost_norm"] = _normalize_series(df["via_cost"])
    feature_frame["distance_norm"] = _normalize_series(
        df[["direct_distance_km", "via_distance_km", "recommended_distance_km"]].max(axis=1)
    )
    feature_frame["time_norm"] = _normalize_series(df["recommended_time_min"])
    feature_frame["demand_gap_norm"] = _normalize_series(
        pd.to_numeric(df["source_dead_stock_qty"], errors="coerce").fillna(0)
        + pd.to_numeric(df["target_shortage_qty"], errors="coerce").fillna(0)
    )

    X = feature_frame.fillna(0).clip(0, 1).values.astype(np.float64)
    return X, list(feature_frame.columns)


def _build_reward_matrix(df):
    """
    각 후보 상태마다 4개 행동의 보상을 모두 만든다.
    이 보상은 실제 매출 데이터가 없을 때 사용하는 시뮬레이션 보상식이다.
    """
    if df.empty:
        return np.empty((0, len(ACTION_LABELS)), dtype=np.float64)

    score = pd.to_numeric(df["heuristic_score"], errors="coerce").fillna(50).clip(0, 100)
    qty_n = _normalize_series(df["suggested_qty"]).clip(0, 1)
    cost_n = _normalize_series(df["estimated_cost"]).clip(0, 1)
    dist_n = _normalize_series(
        df[["direct_distance_km", "via_distance_km", "recommended_distance_km"]].max(axis=1)
    ).clip(0, 1)
    demand_gap_n = _normalize_series(
        pd.to_numeric(df["source_dead_stock_qty"], errors="coerce").fillna(0)
        + pd.to_numeric(df["target_shortage_qty"], errors="coerce").fillna(0)
    ).clip(0, 1)

    base = score

    move_reward = (
        base * 0.60
        + qty_n * 25
        + demand_gap_n * 20
        - cost_n * 25
        - dist_n * 12
        + 10
    )

    discount_reward = (
        base * 0.45
        + qty_n * 18
        + demand_gap_n * 8
        - cost_n * 8
        + 8
    )

    disposal_reward = (
        35
        + qty_n * 10
        - base * 0.20
        - demand_gap_n * 5
        - cost_n * 2
    )

    hold_reward = (
        55
        - qty_n * 25
        - demand_gap_n * 20
        - (score / 100.0) * 15
    )

    reward = np.vstack([
        move_reward.values,
        discount_reward.values,
        disposal_reward.values,
        hold_reward.values,
    ]).T

    # Greedy가 선택한 action에는 실제 휴리스틱 추천을 반영하는 보정값을 준다.
    for row_idx, action in enumerate(df["greedy_action"].tolist()):
        if action in ACTION_LABELS:
            action_idx = ACTION_LABELS.index(action)
            reward[row_idx, action_idx] += 8

    return np.clip(reward, -100, 120).astype(np.float64)


@dataclass
class DQNModel:
    W1: np.ndarray
    b1: np.ndarray
    W2: np.ndarray
    b2: np.ndarray
    feature_names: list


def _relu(x):
    return np.maximum(0, x)


def _forward(model, X):
    z1 = X @ model.W1 + model.b1
    h1 = _relu(z1)
    q = h1 @ model.W2 + model.b2
    return z1, h1, q


def _train_numpy_dqn(X, reward_matrix, episodes=120, lr=0.01, hidden_dim=32, batch_size=64, seed=42):
    """
    NumPy 기반의 작은 DQN.
    현재 앱에서는 한 후보 상태에서 한 번의 의사결정을 하는 구조이므로 done=True인 one-step DQN으로 학습한다.
    """
    rng = np.random.default_rng(seed)

    n_samples, state_dim = X.shape
    n_actions = reward_matrix.shape[1]

    W1 = rng.normal(0, 0.15, size=(state_dim, hidden_dim))
    b1 = np.zeros(hidden_dim)
    W2 = rng.normal(0, 0.15, size=(hidden_dim, n_actions))
    b2 = np.zeros(n_actions)

    model = DQNModel(W1=W1, b1=b1, W2=W2, b2=b2, feature_names=[])

    # replay buffer: 모든 후보에 대해 모든 action을 경험으로 만든다.
    states = []
    actions = []
    rewards = []

    for i in range(n_samples):
        for a in range(n_actions):
            states.append(X[i])
            actions.append(a)
            rewards.append(reward_matrix[i, a])

    states = np.array(states, dtype=np.float64)
    actions = np.array(actions, dtype=np.int64)
    rewards = np.array(rewards, dtype=np.float64)

    history = []

    if len(states) == 0:
        return model, pd.DataFrame(history)

    batch_size = max(8, min(int(batch_size), len(states)))
    episodes = max(10, int(episodes))

    for ep in range(episodes):
        idx = rng.choice(len(states), size=batch_size, replace=True)
        xb = states[idx]
        ab = actions[idx]
        rb = rewards[idx]

        z1, h1, q = _forward(model, xb)
        pred = q[np.arange(batch_size), ab]
        error = pred - rb
        loss = float(np.mean(error ** 2))

        # dL/dQ
        dq = np.zeros_like(q)
        dq[np.arange(batch_size), ab] = (2.0 / batch_size) * error

        dW2 = h1.T @ dq
        db2 = dq.sum(axis=0)

        dh1 = dq @ model.W2.T
        dz1 = dh1 * (z1 > 0)

        dW1 = xb.T @ dz1
        db1 = dz1.sum(axis=0)

        # gradient clipping
        for grad in [dW1, db1, dW2, db2]:
            np.clip(grad, -5, 5, out=grad)

        model.W1 -= lr * dW1
        model.b1 -= lr * db1
        model.W2 -= lr * dW2
        model.b2 -= lr * db2

        if ep == 0 or (ep + 1) % max(1, episodes // 10) == 0 or ep == episodes - 1:
            history.append(
                {
                    "episode": ep + 1,
                    "loss": loss,
                    "mean_reward_sample": float(np.mean(rb)),
                }
            )

    return model, pd.DataFrame(history)


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        return float(value)

    if isinstance(value, (np.ndarray,)):
        return value.tolist()

    try:
        if not isinstance(value, (list, dict, tuple, str)) and pd.isna(value):
            return None
    except Exception:
        pass

    return str(value)


def save_dqn_training_artifacts(
    model,
    compare,
    history,
    summary,
    output_dir="dqn_artifacts",
    prefix="dqn_latest",
):
    """
    DQN 학습 결과를 파일로 저장한다.

    저장 파일:
    - dqn_model_latest.npz: 신경망 가중치와 메타데이터
    - dqn_recommendations_latest.csv: 후보별 DQN 추천 결과
    - dqn_training_history_latest.csv: episode별 loss 변화
    - dqn_summary_latest.json: 요약 지표
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    model_file = output_path / f"{prefix}_model.npz"
    compare_file = output_path / f"{prefix}_recommendations.csv"
    history_file = output_path / f"{prefix}_history.csv"
    summary_file = output_path / f"{prefix}_summary.json"

    timestamp_model_file = output_path / f"dqn_{timestamp}_model.npz"
    timestamp_compare_file = output_path / f"dqn_{timestamp}_recommendations.csv"
    timestamp_history_file = output_path / f"dqn_{timestamp}_history.csv"
    timestamp_summary_file = output_path / f"dqn_{timestamp}_summary.json"

    metadata = {
        "created_at": timestamp,
        "action_labels": ACTION_LABELS,
        "feature_names": model.feature_names,
        "summary": summary,
    }

    # 최신 파일 저장
    np.savez(
        model_file,
        W1=model.W1,
        b1=model.b1,
        W2=model.W2,
        b2=model.b2,
        metadata=json.dumps(metadata, ensure_ascii=False, default=_json_default),
    )

    compare.to_csv(compare_file, index=False, encoding="utf-8-sig")
    history.to_csv(history_file, index=False, encoding="utf-8-sig")

    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, default=_json_default)

    # 타임스탬프 백업 저장
    np.savez(
        timestamp_model_file,
        W1=model.W1,
        b1=model.b1,
        W2=model.W2,
        b2=model.b2,
        metadata=json.dumps(metadata, ensure_ascii=False, default=_json_default),
    )

    compare.to_csv(timestamp_compare_file, index=False, encoding="utf-8-sig")
    history.to_csv(timestamp_history_file, index=False, encoding="utf-8-sig")

    with open(timestamp_summary_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, default=_json_default)

    return {
        "output_dir": str(output_path),
        "model_file": str(model_file),
        "compare_file": str(compare_file),
        "history_file": str(history_file),
        "summary_file": str(summary_file),
        "timestamp_model_file": str(timestamp_model_file),
        "timestamp_compare_file": str(timestamp_compare_file),
        "timestamp_history_file": str(timestamp_history_file),
        "timestamp_summary_file": str(timestamp_summary_file),
        "created_at": timestamp,
    }


def load_dqn_model(model_path="dqn_artifacts/dqn_latest_model.npz"):
    """
    저장된 DQN 모델 가중치를 불러온다.
    다음 단계에서 이어서 학습하거나 예측 전용으로 사용할 수 있다.
    """
    model_file = Path(model_path)

    if not model_file.exists():
        raise FileNotFoundError(f"저장된 DQN 모델을 찾을 수 없습니다: {model_file}")

    data = np.load(model_file, allow_pickle=True)

    metadata_raw = data["metadata"].item() if data["metadata"].shape == () else str(data["metadata"])
    metadata = json.loads(metadata_raw)

    model = DQNModel(
        W1=data["W1"],
        b1=data["b1"],
        W2=data["W2"],
        b2=data["b2"],
        feature_names=metadata.get("feature_names", []),
    )

    return model, metadata



def train_dqn_policy(
    final_recommendations,
    transfer_path_result=None,
    inventory=None,
    episodes=120,
    lr=0.01,
    hidden_dim=32,
    batch_size=64,
    sample_limit=500,
    seed=42,
    save_artifacts=True,
    output_dir="dqn_artifacts",
):
    candidate_df = _prepare_candidate_table(
        final_recommendations,
        transfer_path_result=transfer_path_result,
        sample_limit=sample_limit,
    )

    if candidate_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "message": "DQN 학습에 사용할 후보 데이터가 없습니다."
        }

    X, feature_names = _make_state_features(candidate_df)
    reward_matrix = _build_reward_matrix(candidate_df)

    model, history = _train_numpy_dqn(
        X,
        reward_matrix,
        episodes=episodes,
        lr=lr,
        hidden_dim=hidden_dim,
        batch_size=batch_size,
        seed=seed,
    )

    model.feature_names = feature_names

    _, _, q_values = _forward(model, X)
    dqn_action_idx = np.argmax(q_values, axis=1)
    dqn_actions = [ACTION_LABELS[i] for i in dqn_action_idx]
    dqn_q_values = q_values[np.arange(len(q_values)), dqn_action_idx]

    compare = candidate_df.copy()
    compare["dqn_recommended_action"] = dqn_actions
    compare["dqn_expected_q"] = dqn_q_values.round(3)
    compare["greedy_action"] = compare["greedy_action"].astype(str)
    compare["dqn_match_greedy"] = np.where(
        compare["dqn_recommended_action"] == compare["greedy_action"],
        "일치",
        "다름",
    )

    # 행동별 Q값도 표시
    for i, action in enumerate(ACTION_LABELS):
        compare[f"Q_{action}"] = q_values[:, i].round(3)

    if "greedy_rank" in compare.columns:
        compare["_sort_rank"] = pd.to_numeric(compare["greedy_rank"], errors="coerce").fillna(999999)
        compare = compare.sort_values(["_sort_rank", "dqn_expected_q"], ascending=[True, False])
        compare = compare.drop(columns=["_sort_rank"], errors="ignore")
    else:
        compare = compare.sort_values("dqn_expected_q", ascending=False)

    top = compare.iloc[0]

    compare = compare.reset_index(drop=True)

    summary = {
        "training_samples": int(len(candidate_df)),
        "transition_count": int(len(candidate_df) * len(ACTION_LABELS)),
        "final_loss": float(history["loss"].iloc[-1]) if not history.empty else None,
        "dqn_top_action": str(top["dqn_recommended_action"]),
        "dqn_top_product": str(top.get("product_name", "-")),
        "dqn_top_route": f"{top.get('source_store', '-')} → {top.get('target_store', '-')}",
        "greedy_top_action": str(compare.iloc[0].get("greedy_action", "-")),
        "match_count": int((compare["dqn_match_greedy"] == "일치").sum()),
        "match_rate": float((compare["dqn_match_greedy"] == "일치").mean() * 100),
        "feature_names": feature_names,
        "action_labels": ACTION_LABELS,
        "model_saved": False,
    }

    if save_artifacts:
        saved_paths = save_dqn_training_artifacts(
            model=model,
            compare=compare,
            history=history,
            summary=summary,
            output_dir=output_dir,
            prefix="dqn_latest",
        )

        summary["model_saved"] = True
        summary["saved_paths"] = saved_paths

        try:
            from github_dqn_uploader import (
                is_github_upload_configured,
                upload_dqn_artifacts_to_github,
            )

            if is_github_upload_configured():
                github_upload = upload_dqn_artifacts_to_github(
                    saved_paths,
                    commit_message="Save DQN training artifacts",
                )
            else:
                github_upload = {
                    "configured": False,
                    "ok_count": 0,
                    "fail_count": 0,
                    "message": "GitHub upload is not configured.",
                }

            summary["github_upload"] = github_upload

            # GitHub 업로드 결과까지 summary json에 다시 기록
            try:
                summary_file = saved_paths.get("summary_file")

                if summary_file:
                    metadata = {
                        "created_at": saved_paths.get("created_at"),
                        "action_labels": ACTION_LABELS,
                        "feature_names": model.feature_names,
                        "summary": summary,
                    }

                    with open(summary_file, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, ensure_ascii=False, indent=2, default=_json_default)
            except Exception:
                pass

        except Exception as e:
            summary["github_upload"] = {
                "configured": False,
                "ok_count": 0,
                "fail_count": 1,
                "message": str(e),
            }

    return compare, history, summary
