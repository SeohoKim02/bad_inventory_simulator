
import os
import pandas as pd


POLICY_FILE = "rl_policy_table.csv"


def _safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _bin_value(value, bins):
    value = _safe_float(value, 0)

    for label, low, high in bins:
        if low <= value < high:
            return label

    return bins[-1][0]


def make_state_key_from_row(row):
    source_stock_bin = _bin_value(
        row.get("state_source_stock", 0),
        [
            ("src_stock_low", 0, 30),
            ("src_stock_mid", 30, 80),
            ("src_stock_high", 80, 999999),
        ],
    )

    target_stock_bin = _bin_value(
        row.get("state_target_stock", 0),
        [
            ("tgt_stock_low", 0, 30),
            ("tgt_stock_mid", 30, 80),
            ("tgt_stock_high", 80, 999999),
        ],
    )

    source_sales_bin = _bin_value(
        row.get("state_source_sales_30d", 0),
        [
            ("src_sales_low", 0, 20),
            ("src_sales_mid", 20, 60),
            ("src_sales_high", 60, 999999),
        ],
    )

    target_sales_bin = _bin_value(
        row.get("state_target_sales_30d", 0),
        [
            ("tgt_sales_low", 0, 20),
            ("tgt_sales_mid", 20, 60),
            ("tgt_sales_high", 60, 999999),
        ],
    )

    inbound_bin = _bin_value(
        row.get("state_inbound_days", 0),
        [
            ("age_new", 0, 15),
            ("age_mid", 15, 40),
            ("age_old", 40, 999999),
        ],
    )

    distance_bin = _bin_value(
        row.get("state_distance_km", 0),
        [
            ("dist_short", 0, 5),
            ("dist_mid", 5, 15),
            ("dist_long", 15, 999999),
        ],
    )

    transfer_cost_bin = _bin_value(
        row.get("state_transfer_cost", 0),
        [
            ("transfer_cost_low", 0, 5000),
            ("transfer_cost_mid", 5000, 20000),
            ("transfer_cost_high", 20000, 999999999),
        ],
    )

    promotion_cost_bin = _bin_value(
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


def load_rl_policy(policy_file=POLICY_FILE):
    if not os.path.exists(policy_file):
        return pd.DataFrame()

    return pd.read_csv(policy_file)


def recommend_action_for_rl_log(rl_training_log, policy_file=POLICY_FILE):
    policy = load_rl_policy(policy_file)

    if policy.empty or rl_training_log is None or rl_training_log.empty:
        return pd.DataFrame()

    result = rl_training_log.copy()
    result["state_key"] = result.apply(make_state_key_from_row, axis=1)

    merged = result.merge(
        policy[
            [
                "state_key",
                "rl_recommended_action",
                "expected_reward",
                "policy_reason",
            ]
        ],
        on="state_key",
        how="left",
    )

    merged["rl_match_status"] = merged["rl_recommended_action"].apply(
        lambda value: "정책 매칭됨" if pd.notna(value) else "학습된 유사 상태 없음"
    )

    return merged
