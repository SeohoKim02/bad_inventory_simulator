
import os
import json
import pandas as pd


INPUT_FILE = "rl_training_log.csv"
POLICY_FILE = "rl_policy_table.csv"
Q_TABLE_FILE = "rl_q_table.csv"
SUMMARY_FILE = "rl_training_summary.json"


STATE_COLUMNS = [
    "state_source_stock",
    "state_target_stock",
    "state_source_sales_30d",
    "state_target_sales_30d",
    "state_inbound_days",
    "state_unit_cost",
    "state_distance_km",
    "state_transfer_cost",
    "state_promotion_net_cost",
]

ACTION_COLUMN = "action"
REWARD_COLUMN = "reward"


def safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def bin_value(value, bins):
    value = safe_float(value, 0)

    for label, low, high in bins:
        if low <= value < high:
            return label

    return bins[-1][0]


def make_state_key(row):
    """
    연속형 숫자 상태를 구간화해서 강화학습용 상태 키로 만든다.
    너무 세밀하게 나누면 학습 데이터가 부족해지므로 발표/시연용으로 적당히 단순화한다.
    """

    source_stock_bin = bin_value(
        row.get("state_source_stock", 0),
        [
            ("src_stock_low", 0, 30),
            ("src_stock_mid", 30, 80),
            ("src_stock_high", 80, 999999),
        ],
    )

    target_stock_bin = bin_value(
        row.get("state_target_stock", 0),
        [
            ("tgt_stock_low", 0, 30),
            ("tgt_stock_mid", 30, 80),
            ("tgt_stock_high", 80, 999999),
        ],
    )

    source_sales_bin = bin_value(
        row.get("state_source_sales_30d", 0),
        [
            ("src_sales_low", 0, 20),
            ("src_sales_mid", 20, 60),
            ("src_sales_high", 60, 999999),
        ],
    )

    target_sales_bin = bin_value(
        row.get("state_target_sales_30d", 0),
        [
            ("tgt_sales_low", 0, 20),
            ("tgt_sales_mid", 20, 60),
            ("tgt_sales_high", 60, 999999),
        ],
    )

    inbound_bin = bin_value(
        row.get("state_inbound_days", 0),
        [
            ("age_new", 0, 15),
            ("age_mid", 15, 40),
            ("age_old", 40, 999999),
        ],
    )

    distance_bin = bin_value(
        row.get("state_distance_km", 0),
        [
            ("dist_short", 0, 5),
            ("dist_mid", 5, 15),
            ("dist_long", 15, 999999),
        ],
    )

    transfer_cost_bin = bin_value(
        row.get("state_transfer_cost", 0),
        [
            ("transfer_cost_low", 0, 5000),
            ("transfer_cost_mid", 5000, 20000),
            ("transfer_cost_high", 20000, 999999999),
        ],
    )

    promotion_cost_bin = bin_value(
        row.get("state_promotion_net_cost", 0),
        [
            ("promo_cost_low", 0, 5000),
            ("promo_cost_mid", 5000, 20000),
            ("promo_cost_high", 20000, 999999999),
        ],
    )

    return "|".join(
        [
            source_stock_bin,
            target_stock_bin,
            source_sales_bin,
            target_sales_bin,
            inbound_bin,
            distance_bin,
            transfer_cost_bin,
            promotion_cost_bin,
        ]
    )


def train_contextual_q_learning(data, epochs=80, learning_rate=0.25):
    """
    현재 데이터는 다음 상태(next_state)가 없는 추천 후보 데이터이므로,
    여러 단계 환경이 아니라 one-step RL/contextual bandit 방식으로 학습한다.

    Q(state, action) <- Q(state, action) + alpha * (reward - Q(state, action))
    """

    q_values = {}
    visit_counts = {}

    train_data = data.copy()
    train_data["state_key"] = train_data.apply(make_state_key, axis=1)

    for _ in range(epochs):
        shuffled = train_data.sample(frac=1, random_state=None).reset_index(drop=True)

        for _, row in shuffled.iterrows():
            state_key = row["state_key"]
            action = str(row[ACTION_COLUMN])
            reward = safe_float(row[REWARD_COLUMN], 0)

            key = (state_key, action)

            old_q = q_values.get(key, 0.0)
            new_q = old_q + learning_rate * (reward - old_q)

            q_values[key] = new_q
            visit_counts[key] = visit_counts.get(key, 0) + 1

    q_rows = []

    for (state_key, action), q_value in q_values.items():
        q_rows.append(
            {
                "state_key": state_key,
                "action": action,
                "q_value": round(q_value, 4),
                "visit_count": visit_counts.get((state_key, action), 0),
            }
        )

    q_table = pd.DataFrame(q_rows)

    if q_table.empty:
        return q_table, pd.DataFrame()

    q_table = q_table.sort_values(
        by=["state_key", "q_value", "visit_count"],
        ascending=[True, False, False],
    ).reset_index(drop=True)

    policy_table = (
        q_table.sort_values(["state_key", "q_value", "visit_count"], ascending=[True, False, False])
        .groupby("state_key")
        .head(1)
        .reset_index(drop=True)
        .rename(columns={"action": "rl_recommended_action", "q_value": "expected_reward"})
    )

    policy_table["policy_reason"] = policy_table.apply(
        lambda row: (
            f"상태 {row['state_key']}에서 과거 후보 데이터 기준 "
            f"{row['rl_recommended_action']} 행동의 기대 보상(Q={row['expected_reward']})이 가장 높음"
        ),
        axis=1,
    )

    return q_table, policy_table


def main():
    if not os.path.exists(INPUT_FILE):
        print("=" * 70)
        print("rl_training_log.csv 파일을 찾지 못했습니다.")
        print("먼저 Streamlit 앱에서 'RL 학습 데이터 CSV 다운로드' 버튼으로 파일을 받은 뒤,")
        print("그 파일을 app.py와 같은 프로젝트 폴더에 넣어 주세요.")
        print("=" * 70)
        return

    data = pd.read_csv(INPUT_FILE)

    required_columns = [ACTION_COLUMN, REWARD_COLUMN]

    missing = [col for col in required_columns if col not in data.columns]

    if missing:
        print(f"필수 열이 없습니다: {missing}")
        return

    for col in STATE_COLUMNS:
        if col not in data.columns:
            data[col] = 0

    data[ACTION_COLUMN] = data[ACTION_COLUMN].fillna("unknown").astype(str)
    data[REWARD_COLUMN] = pd.to_numeric(data[REWARD_COLUMN], errors="coerce").fillna(0)

    q_table, policy_table = train_contextual_q_learning(
        data,
        epochs=100,
        learning_rate=0.25,
    )

    if q_table.empty or policy_table.empty:
        print("학습 결과가 비어 있습니다.")
        return

    q_table.to_csv(Q_TABLE_FILE, index=False, encoding="utf-8-sig")
    policy_table.to_csv(POLICY_FILE, index=False, encoding="utf-8-sig")

    summary = {
        "input_file": INPUT_FILE,
        "training_samples": int(len(data)),
        "state_count": int(policy_table["state_key"].nunique()),
        "action_count": int(data[ACTION_COLUMN].nunique()),
        "average_reward": round(float(data[REWARD_COLUMN].mean()), 4),
        "max_reward": round(float(data[REWARD_COLUMN].max()), 4),
        "policy_file": POLICY_FILE,
        "q_table_file": Q_TABLE_FILE,
    }

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("강화학습 기반 정책 학습 완료")
    print("=" * 70)
    print(f"학습 샘플 수: {summary['training_samples']}")
    print(f"상태 개수: {summary['state_count']}")
    print(f"행동 개수: {summary['action_count']}")
    print(f"평균 Reward: {summary['average_reward']}")
    print(f"최대 Reward: {summary['max_reward']}")
    print("-" * 70)
    print(f"저장 파일 1: {POLICY_FILE}")
    print(f"저장 파일 2: {Q_TABLE_FILE}")
    print(f"저장 파일 3: {SUMMARY_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
