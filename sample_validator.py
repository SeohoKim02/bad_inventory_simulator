"""
sample_validator.py — 업로드 엑셀 Varo 분석 가능 여부 검증
────────────────────────────────────────────────────────────
validate_excel(sheets) → ValidationResult
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field

# ── 필수/선택 컬럼 정의 ──────────────────────────────────
_REQUIRED_SHEETS = ['stores', 'products', 'inventory', 'routes']

_ALIAS_MAP = {
    'expiry_days':         ['days_to_expiry', 'expiry'],
    'sales_30d':           ['sales_30', 'monthly_sales'],
    'disposal_cost':       ['disposal_cost_per_unit', 'disposal_unit_cost'],
    'unit_cost':           ['unit_price', 'cost_per_unit'],
    'category':            ['inventory_category', 'product_category'],
    'lead_time_days':      ['lead_time', 'lt_days'],
    'demand_std':          ['demand_stddev', 'std_demand'],
    'distance_km':         ['transport_distance_km', 'dist_km'],
    'store_name':          ['store_nm'],
    'product_name':        ['product_nm', 'item_name'],
}

_INVENTORY_REQUIRED = ['stock_qty', 'avg_daily_sales']
_INVENTORY_NICE     = ['sales_7d', 'sales_30d', 'expiry_days', 'category',
                       'disposal_cost', 'unit_cost', 'demand_std']
_ROUTES_REQUIRED    = ['transport_cost']
_NUMERIC_COLS       = ['stock_qty', 'sales_7d', 'sales_30d', 'distance_km',
                       'transport_cost', 'avg_daily_sales']
_NO_NEGATIVE        = ['stock_qty', 'sales_7d', 'sales_30d', 'distance_km', 'transport_cost']


@dataclass
class ColResult:
    name:    str
    found:   bool
    alias:   str = ""   # 발견된 별칭
    level:   str = "required"   # required / nice / optional


@dataclass
class ValidationResult:
    ok:           bool = True
    level:        str  = "정상"  # 정상 / 주의 / 오류
    messages:     list = field(default_factory=list)   # (level, msg)
    col_results:  list = field(default_factory=list)   # ColResult
    can_analyze:  bool = True
    details:      dict = field(default_factory=dict)


def _find_col(df: pd.DataFrame, name: str) -> str:
    """컬럼 또는 별칭 찾기. 발견된 실제 컬럼명 반환. 없으면 ''."""
    if name in df.columns:
        return name
    for alias in _ALIAS_MAP.get(name, []):
        if alias in df.columns:
            return alias
    return ''


def validate_excel(sheets: dict) -> ValidationResult:
    """
    sheets: {'stores': df, 'inventory': df, ...}
    """
    r = ValidationResult()

    # 1. 시트 존재
    missing_sheets = [s for s in _REQUIRED_SHEETS if s not in sheets or sheets[s].empty]
    if missing_sheets:
        r.ok = False
        r.can_analyze = False
        r.level = "오류"
        r.messages.append(("오류", f"필수 시트 없음: {', '.join(missing_sheets)}"))
        return r

    inv = sheets.get('inventory', pd.DataFrame())
    sto = sheets.get('stores',    pd.DataFrame())
    rte = sheets.get('routes',    pd.DataFrame())
    pro = sheets.get('products',  pd.DataFrame())

    # 2. ID 연결 확인
    if 'store_id' in inv.columns and 'store_id' in sto.columns:
        inv_ids = set(inv['store_id'].dropna().astype(str))
        sto_ids = set(sto['store_id'].dropna().astype(str))
        unmatched = inv_ids - sto_ids
        if len(unmatched) > len(inv_ids) * 0.3:
            r.messages.append(("주의", f"점포 ID 연결 불일치: {len(unmatched)}개"))

    # 3. inventory 필수 컬럼
    for col in _INVENTORY_REQUIRED:
        found = _find_col(inv, col)
        cr = ColResult(col, bool(found), found if found != col else '', 'required')
        r.col_results.append(cr)
        if not found:
            r.ok = False
            r.can_analyze = False
            r.level = "오류"
            r.messages.append(("오류", f"필수 컬럼 없음: {col}"))

    # 4. 선택 컬럼
    nice_missing = []
    for col in _INVENTORY_NICE:
        found = _find_col(inv, col)
        cr = ColResult(col, bool(found), found if found != col else '', 'nice')
        r.col_results.append(cr)
        if not found:
            nice_missing.append(col)
    if nice_missing:
        r.messages.append(("주의", f"선택 컬럼 없음 (정확도 저하 가능): {', '.join(nice_missing)}"))
        if r.level == "정상":
            r.level = "주의"

    # 5. 음수값 검사
    for col in _NO_NEGATIVE:
        real = _find_col(inv, col) or _find_col(rte, col)
        if real:
            df_src = inv if real in inv.columns else rte
            s = pd.to_numeric(df_src[real], errors='coerce').dropna()
            neg_cnt = int((s < 0).sum())
            if neg_cnt:
                r.messages.append(("주의", f"{real}: 음수값 {neg_cnt}건 발견"))
                if r.level == "정상":
                    r.level = "주의"

    # 6. 숫자 컬럼에 문자값
    for col in _NUMERIC_COLS:
        real = _find_col(inv, col)
        if real:
            orig = inv[real]
            numeric = pd.to_numeric(orig, errors='coerce')
            bad = int(orig.notna().sum() - numeric.notna().sum())
            if bad:
                r.messages.append(("주의", f"{real}: 숫자 변환 불가 {bad}건"))

    # 7. Quality_Check 시트
    if 'Quality_Check' in sheets:
        r.messages.append(("정상", "Quality_Check 시트 존재 — 데이터 품질 관리 확인됨"))

    # 8. routes transport_cost
    if 'transport_cost' not in rte.columns:
        r.messages.append(("주의", "routes.transport_cost 없음 — 비용 계산 기본값 사용"))
        if r.level == "정상":
            r.level = "주의"

    # 9. 요약
    r.details = {
        "inventory_rows": len(inv),
        "stores_count":   len(sto),
        "routes_count":   len(rte),
        "products_count": len(pro),
        "missing_nice":   nice_missing,
    }

    if not r.messages:
        r.messages.append(("정상", "모든 필수 컬럼 확인 완료 — Varo 분석 가능"))

    return r


def render_validation_result(r: ValidationResult) -> None:
    """Streamlit UI 렌더링."""
    import streamlit as st

    _COLOR = {"오류": "#c62828", "주의": "#f57c00", "정상": "#2e7d32"}
    _ICON  = {"오류": "❌", "주의": "⚠️", "정상": "✅"}

    col = _COLOR.get(r.level, "#555")
    _can_str = "가능" if r.can_analyze else "불가"
    st.markdown(
        f'<div style="border-left:5px solid {col};padding:10px 16px;'
        f'border-radius:0 10px 10px 0;background:#fafafa;margin-bottom:10px;">'
        f'<strong style="font-size:15px;color:{col};">'
        f'{_ICON[r.level]} Varo 분석 {_can_str} — {r.level}</strong></div>',
        unsafe_allow_html=True,
    )

    for level, msg in r.messages:
        c = _COLOR.get(level, "#555")
        st.markdown(
            f'<div style="font-size:13px;color:{c};margin:3px 0;">'
            f'{_ICON.get(level,"•")} {msg}</div>',
            unsafe_allow_html=True,
        )

    if r.details:
        with st.expander("📋 데이터 상세 정보", expanded=False):
            d = r.details
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("재고 데이터", f'{d.get("inventory_rows",0):,}행')
            c2.metric("점포 수",    f'{d.get("stores_count",0)}개')
            c3.metric("경로 수",    f'{d.get("routes_count",0)}개')
            c4.metric("상품 수",    f'{d.get("products_count",0)}개')

    if r.col_results:
        with st.expander("🔍 컬럼 인식 결과", expanded=False):
            rows = []
            for cr in r.col_results:
                rows.append({
                    "컬럼": cr.name,
                    "인식": "✅" if cr.found else "❌",
                    "별칭 사용": cr.alias or "-",
                    "중요도": "필수" if cr.level == "required" else "권장",
                })
            import pandas as _pd
            st.dataframe(_pd.DataFrame(rows), hide_index=True, width="stretch")
