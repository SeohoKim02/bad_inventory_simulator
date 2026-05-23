
"""
rl_data_logger.py — 강화학습 학습 데이터 생성
═══════════════════════════════════════════════
1단계 고도화: Reward 함수를 7개 컴포넌트 기반으로 개선.

기존 호환성 유지:
  - build_rl_training_log() 함수 시그니처 동일
  - action 컬럼명 동일
  - reward 컬럼명 동일 (값만 개선)
  - state_* 컬럼 전부 동일
  - NaN/None 안전 처리 강화

신규 추가 컬럼:
  reward_disposal_saving     — 폐기비용 절감
  reward_holding_saving      — 보관비 절감
  reward_sales_opportunity   — 예상 판매기회 증가
  reward_balance_effect      — 재고 불균형 완화
  reward_transport_penalty   — 이동비용 패널티
  reward_promotion_penalty   — 프로모션 손실 패널티
  reward_time_penalty        — 시간 위반 패널티
"""

import pandas as pd


# ── 헬퍼 유틸 ────────────────────────────────────────────

def _safe_float(value, default=0.0):
    try:
        if pd.isna(value):
            return float(default) if default is not None else 0.0
        return float(value)
    except Exception:
        return float(default) if default is not None else 0.0


def _safe_int(value, default=0):
    try:
        if pd.isna(value):
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _first_existing(row, columns, default=None):
    """row에서 columns 순서로 처음 유효한 값을 반환."""
    for col in columns:
        if col in row.index:
            value = row.get(col)
            try:
                if not pd.isna(value):
                    return value
            except Exception:
                if value is not None:
                    return value
    return default


# ── 점포/상품/재고 조회 ──────────────────────────────────

def _get_store_id(stores, store_name):
    if stores is None or stores.empty:
        return None
    if "store_name" not in stores.columns or "store_id" not in stores.columns:
        return None
    matched = stores[stores["store_name"] == store_name]
    return matched.iloc[0]["store_id"] if not matched.empty else None


def _get_product_id(products, product_name):
    if products is None or products.empty:
        return None
    if "product_name" not in products.columns or "product_id" not in products.columns:
        return None
    matched = products[products["product_name"] == product_name]
    return matched.iloc[0]["product_id"] if not matched.empty else None


def _get_inventory_row(inventory, store_id, product_id):
    if inventory is None or inventory.empty:
        return None
    if "store_id" not in inventory.columns or "product_id" not in inventory.columns:
        return None
    matched = inventory[
        (inventory["store_id"] == store_id)
        & (inventory["product_id"] == product_id)
    ]
    return matched.iloc[0] if not matched.empty else None


def _get_product_row(products, product_id):
    if products is None or products.empty:
        return None
    if "product_id" not in products.columns:
        return None
    matched = products[products["product_id"] == product_id]
    return matched.iloc[0] if not matched.empty else None


# ── Action 추정 (기존 유지) ──────────────────────────────

def _estimate_action(row):
    """
    추천 텍스트 기반 Action 분류.
    기존 action 컬럼값과 동일하게 유지.
    """
    text = (str(row.get("final_recommendation", ""))
            + " " + str(row.get("recommended_transfer_path", "")))

    if "직접" in text:
        return "direct_transfer"
    if "DC" in text or "경유" in text:
        return "via_dc_transfer"
    if "다중" in text:
        return "multi_store_transfer"
    if "프로모션" in text or "할인" in text or "1+1" in text:
        return "promotion"
    if "폐기" in text:
        return "dispose"
    if "유지" in text:
        return "keep"
    if "재배치" in text or "이동" in text:
        return "transfer"
    return "unknown"


# ── Reward 함수 고도화 (1단계 핵심) ─────────────────────

def _calculate_reward_detailed(row):
    """
    7개 컴포넌트 기반 Reward 계산.

    입력: build_rl_training_log 내부에서 구성된 row dict
    출력: {reward_*, reward} dict

    각 컴포넌트:
    1. disposal_saving    — 폐기 위험 재고 해소 이익
    2. holding_saving     — 과잉재고 보관비 절감
    3. sales_opportunity  — 타 점포 판매기회 증대
    4. balance_effect     — 점포 간 재고 불균형 완화
    5. transport_penalty  — 이동 물류비
    6. promotion_penalty  — 프로모션 비용 손실
    7. time_penalty       — 오래된 재고 패널티
    """
    unit_cost      = _safe_float(row.get("state_unit_cost", 1000), 1000)
    source_stock   = _safe_float(row.get("state_source_stock", 0), 0)
    target_stock   = _safe_float(row.get("state_target_stock", 0), 0)
    source_sales   = max(_safe_float(row.get("state_source_sales_30d", 1), 1), 0.1)
    target_sales   = max(_safe_float(row.get("state_target_sales_30d", 1), 1), 0.1)
    inbound_days   = _safe_float(row.get("state_inbound_days", 0), 0)
    transfer_cost  = _safe_float(row.get("state_transfer_cost", 0), 0)
    promo_cost     = _safe_float(row.get("state_promotion_net_cost", 0), 0)
    suggested_qty  = _safe_float(row.get("suggested_qty", 0), 0)

    # ── 1. 폐기비용 절감 ──────────────────────────────────
    # source 재고 소진 예상일수가 길수록 폐기 위험 증가
    daily_sales = source_sales / 30.0
    days_to_stockout = source_stock / max(daily_sales, 0.01)
    disposal_risk = min(days_to_stockout / 60.0, 1.0)   # 60일 이상 → MAX
    disposal_saving = unit_cost * suggested_qty * disposal_risk * 0.15

    # ── 2. 보관비 절감 ────────────────────────────────────
    # 판매량 대비 초과 재고에 대한 보관비 절감 효과
    excess_stock = max(source_stock - source_sales, 0.0)
    holding_saving = excess_stock * unit_cost * 0.005   # 일 0.5% 보관비

    # ── 3. 예상 판매기회 증가 ─────────────────────────────
    # target 점포 수요 부족분만큼 판매기회 창출
    target_demand_gap = max(target_sales - target_stock, 0.0)
    filled_qty = min(suggested_qty, target_demand_gap)
    sales_opportunity = filled_qty * unit_cost * 0.10   # 마진 10%

    # ── 4. 재고 불균형 완화 ───────────────────────────────
    # source 과잉 + target 부족 구조가 해소될수록 보상 증가
    source_ratio = source_stock / max(source_sales, 1.0)
    target_ratio = target_stock / max(target_sales, 1.0)
    balance_effect = max(source_ratio - target_ratio, 0.0) * 0.5

    # ── 5. 이동비용 패널티 ────────────────────────────────
    transport_penalty = transfer_cost / 10000.0

    # ── 6. 프로모션 손실 패널티 ──────────────────────────
    promotion_penalty = promo_cost / 10000.0

    # ── 7. 시간 위반 패널티 ───────────────────────────────
    # 30일 이상 재고 방치 시 점진적 패널티
    time_penalty = max(inbound_days - 30.0, 0.0) * 0.02

    total = (
        disposal_saving
        + holding_saving
        + sales_opportunity
        + balance_effect
        - transport_penalty
        - promotion_penalty
        - time_penalty
    )

    return {
        "reward_disposal_saving":   round(disposal_saving,   3),
        "reward_holding_saving":    round(holding_saving,    3),
        "reward_sales_opportunity": round(sales_opportunity, 3),
        "reward_balance_effect":    round(balance_effect,    3),
        "reward_transport_penalty": round(transport_penalty, 3),
        "reward_promotion_penalty": round(promotion_penalty, 3),
        "reward_time_penalty":      round(time_penalty,      3),
        "reward":                   round(total,             3),
    }


# ── 메인 함수 (기존 시그니처 완전 유지) ─────────────────

def build_rl_training_log(
    stores,
    products,
    inventory,
    final_recommendations,
    transfer_path_result=None,
    promotion_result=None,
):
    """
    현재 앱의 추천 결과를 강화학습 학습용 로그 형태로 변환한다.

    출력 컬럼 구조 (기존 호환):
    - state_*:   상태 변수 (기존 그대로)
    - action:    선택 행동 (기존 그대로)
    - reward:    총 보상 (값만 개선, 컬럼명 유지)
    - reward_*:  보상 세부 분해 (신규 추가)
    - heuristic/greedy: 현재 알고리즘 결과 (기존 그대로)
    """
    if final_recommendations is None or final_recommendations.empty:
        return pd.DataFrame()

    records = []

    for _, rec in final_recommendations.iterrows():
        product_name  = rec.get("product_name",  "-")
        source_store  = rec.get("source_store",  "-")
        target_store  = rec.get("target_store",  "-")

        product_id       = _get_product_id(products, product_name)
        source_store_id  = _get_store_id(stores, source_store)
        target_store_id  = _get_store_id(stores, target_store)

        source_inv  = _get_inventory_row(inventory, source_store_id, product_id)
        target_inv  = _get_inventory_row(inventory, target_store_id, product_id)
        product_row = _get_product_row(products, product_id)

        source_stock = (
            _safe_float(source_inv.get("stock_qty", 0), 0) if source_inv is not None else 0
        )
        target_stock = (
            _safe_float(target_inv.get("stock_qty", 0), 0) if target_inv is not None else 0
        )
        source_sales_30d = (
            _safe_float(
                _first_existing(source_inv, ["sales_30d", "recent_sales_30d", "monthly_sales"], 0), 0
            ) if source_inv is not None else 0
        )
        target_sales_30d = (
            _safe_float(
                _first_existing(target_inv, ["sales_30d", "recent_sales_30d", "monthly_sales"], 0), 0
            ) if target_inv is not None else 0
        )
        inbound_days = (
            _safe_float(
                _first_existing(source_inv, ["inbound_days", "days_since_inbound", "stock_age_days"], 0), 0
            ) if source_inv is not None else 0
        )

        # unit_cost: inventory → products 순서로 fallback
        unit_cost = (
            _safe_float(
                _first_existing(source_inv, ["unit_cost", "cost", "unit_price"], None), None
            ) if source_inv is not None else None
        )
        if unit_cost is None and product_row is not None:
            unit_cost = _safe_float(
                _first_existing(product_row, ["unit_cost", "cost", "unit_price", "price"], 1000), 1000
            )
        if unit_cost is None:
            unit_cost = 1000.0

        # 이동경로 정보
        distance_km   = 0.0
        transfer_cost = _safe_float(rec.get("estimated_cost", 0), 0)

        if transfer_path_result is not None and not transfer_path_result.empty:
            matched_t = transfer_path_result[
                (transfer_path_result["product_name"] == product_name)
                & (transfer_path_result["source_store"] == source_store)
                & (transfer_path_result["target_store"] == target_store)
            ]
            if not matched_t.empty:
                trow = matched_t.iloc[0]
                distance_km = _safe_float(
                    _first_existing(trow, ["direct_distance_km", "distance_km", "network_distance_km"], 0), 0
                )
                direct_cost = _safe_float(trow.get("direct_cost", 0), 0)
                via_cost    = _safe_float(trow.get("via_cost", 0), 0)
                if direct_cost > 0:
                    transfer_cost = direct_cost
                elif via_cost > 0:
                    transfer_cost = via_cost

        # 프로모션 정보
        promotion_net_cost = 0.0
        if promotion_result is not None and not promotion_result.empty:
            matched_p = promotion_result[
                (promotion_result["product_name"] == product_name)
                & (promotion_result["source_store"] == source_store)
                & (promotion_result["target_store"] == target_store)
            ]
            if not matched_p.empty:
                promotion_net_cost = _safe_float(
                    matched_p.iloc[0].get("promotion_net_cost", 0), 0
                )

        # ── row 구성 (state_* 컬럼 기존과 동일) ─────────
        row = {
            "product_name": product_name,
            "source_store": source_store,
            "target_store": target_store,

            # state_* (기존 컬럼명 100% 유지)
            "state_source_stock":        source_stock,
            "state_target_stock":        target_stock,
            "state_source_sales_30d":    source_sales_30d,
            "state_target_sales_30d":    target_sales_30d,
            "state_inbound_days":        inbound_days,
            "state_unit_cost":           unit_cost,
            "state_distance_km":         distance_km,
            "state_transfer_cost":       transfer_cost,
            "state_promotion_net_cost":  promotion_net_cost,

            # 추천 정보 (기존 그대로)
            "suggested_qty":        _safe_float(rec.get("suggested_qty", 0), 0),
            "estimated_cost":       _safe_float(rec.get("estimated_cost", 0), 0),
            "final_recommendation": rec.get("final_recommendation", "-"),
            "heuristic_score":      _safe_float(rec.get("heuristic_score", 0), 0),
            "heuristic_grade":      rec.get("heuristic_grade", "-"),
            "greedy_rank":          _safe_int(rec.get("greedy_rank", 9999), 9999),
            "is_greedy_selected":   bool(rec.get("is_greedy_selected", False)),
        }

        # action (기존 컬럼명 유지)
        row["action"] = _estimate_action(rec)

        # reward 상세 계산 (7 컴포넌트) + 총합 reward
        reward_detail = _calculate_reward_detailed(row)
        row.update(reward_detail)   # reward_* + reward 모두 포함

        records.append(row)

    result = pd.DataFrame(records)

    if result.empty:
        return result

    # NaN → 타입별 기본값으로 안전 처리
    numeric_cols = [c for c in result.columns
                    if c.startswith("state_") or c.startswith("reward")
                    or c in ("suggested_qty", "estimated_cost", "heuristic_score", "greedy_rank")]
    for col in numeric_cols:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0.0)

    result = result.sort_values(
        by=["greedy_rank", "reward"],
        ascending=[True, False],
    ).reset_index(drop=True)

    return result


# ── Master CSV 누적 관리 (4·5단계) ──────────────────────

import os
from datetime import datetime as _dt
import hashlib as _hl

MASTER_CSV   = "rl_training_log_master.csv"
SCENARIO_CSV = "rl_training_log.csv"


def _gen_scenario_id(scenario_name: str, created_at: str) -> str:
    """scenario_name + timestamp 기반 8자리 ID."""
    raw = f"{scenario_name}_{created_at}"
    return _hl.md5(raw.encode()).hexdigest()[:8]


def save_rl_log(
    log: "pd.DataFrame",
    scenario_name: str = "",
    uploaded_excel_name: str = "",
    output_dir: str = ".",
) -> dict:
    """
    rl_training_log.csv 저장 + master에 누적 append.

    반환: {log_file, master_file, scenario_id, rows_added}
    """
    if log is None or log.empty:
        return {}

    log = log.copy()
    created_at  = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    scenario_id = _gen_scenario_id(scenario_name, created_at)

    log["scenario_id"]          = scenario_id
    log["scenario_name"]        = scenario_name if scenario_name else "default"
    log["created_at"]           = created_at
    log["uploaded_excel_name"]  = uploaded_excel_name if uploaded_excel_name else ""

    os.makedirs(output_dir, exist_ok=True)
    log_path    = os.path.join(output_dir, SCENARIO_CSV)
    master_path = os.path.join(output_dir, MASTER_CSV)

    # 현재 로그 저장 (덮어쓰기)
    log.to_csv(log_path, index=False, encoding="utf-8-sig")

    # master에 누적 append
    if os.path.exists(master_path):
        existing = pd.read_csv(master_path, encoding="utf-8-sig")
        # 중복 제거: product_name + source_store + target_store + scenario_id
        dedup_keys = [c for c in ["product_name","source_store","target_store","scenario_id"]
                      if c in existing.columns and c in log.columns]
        if dedup_keys:
            combined = pd.concat([existing, log], ignore_index=True)
            combined = combined.drop_duplicates(subset=dedup_keys, keep="last")
        else:
            combined = pd.concat([existing, log], ignore_index=True)
    else:
        combined = log

    combined.to_csv(master_path, index=False, encoding="utf-8-sig")

    return {
        "log_file":    log_path,
        "master_file": master_path,
        "scenario_id": scenario_id,
        "rows_added":  len(log),
        "master_rows": len(combined),
    }


def load_master(output_dir: str = ".") -> "pd.DataFrame":
    """master CSV 로드. 없으면 빈 DataFrame."""
    path = os.path.join(output_dir, MASTER_CSV)
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


# ── Action 체계 정리 (8단계) ────────────────────────────

ACTION_ID_MAP = {
    "keep":                 0,
    "discount_promotion":   1,
    "one_plus_one":         2,
    "direct_transfer":      3,
    "via_dc_transfer":      4,
    "multi_store_transfer": 5,
    "dispose":              6,
    # 기존 별칭 매핑
    "promotion":            1,
    "transfer":             3,
    "unknown":              0,
}

ACTION_LABEL_KO = {
    0: "유지",
    1: "할인 프로모션",
    2: "1+1 프로모션",
    3: "직접 이동",
    4: "DC 경유 이동",
    5: "다중 점포 이동",
    6: "폐기",
}


def get_action_id(action_str: str) -> int:
    """action 문자열 → action_id (int)"""
    return ACTION_ID_MAP.get(str(action_str).strip().lower(), 0)


def get_action_label_ko(action_str: str) -> str:
    """action 문자열 → 한글 레이블"""
    aid = get_action_id(action_str)
    return ACTION_LABEL_KO.get(aid, "유지")


def add_action_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    """
    기존 action 컬럼 유지 + action_id / action_label 추가.
    train_rl_agent.py 호환: action 컬럼은 그대로 유지.
    """
    if df is None or df.empty or "action" not in df.columns:
        return df
    df = df.copy()
    df["action_id"]    = df["action"].apply(get_action_id)
    df["action_label"] = df["action"].apply(get_action_label_ko)
    return df