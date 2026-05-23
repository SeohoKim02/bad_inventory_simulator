"""
vhs_reason.py — VHS 추천 이유 분해
──────────────────────────────────────
각 추천 후보마다 구성 점수 + 자동 생성 이유 문장 반환.
"""
import pandas as pd

_GROUPS = {
    "재고 위험":     "vhs2_group_재고위험",
    "판매 가능성":   "vhs2_group_판매가능성",
    "이동 적합도":   "vhs2_group_점포이동적합",
    "비용 절감":     "vhs2_group_비용절감",
    "폐기 회피 이익":"vhs2_group_폐기회피이익",
    "실행 가능성":   "vhs2_group_실행가능성",
    "이력 보정":     "vhs2_history_correction",
}


def get_score_breakdown(row: pd.Series) -> dict:
    """구성 점수 dict 반환."""
    result = {}
    for label, col in _GROUPS.items():
        val = row.get(col)
        try:
            result[label] = round(float(val), 1) if val is not None else None
        except (TypeError, ValueError):
            result[label] = None
    return result


def get_reason_sentences(row: pd.Series) -> list:
    """자동 추천 이유 문장 리스트 (최대 4개)."""
    sentences = []

    g_inv   = float(row.get("vhs2_group_재고위험",   50) or 50)
    g_sale  = float(row.get("vhs2_group_판매가능성", 50) or 50)
    g_move  = float(row.get("vhs2_group_점포이동적합",50) or 50)
    g_cost  = float(row.get("vhs2_group_비용절감",   50) or 50)
    g_avoid = float(row.get("vhs2_group_폐기회피이익",50) or 50)
    g_exec  = float(row.get("vhs2_group_실행가능성", 50) or 50)
    corr    = float(row.get("vhs2_history_correction", 0) or 0)
    expiry  = row.get("expiry_days") or row.get("days_to_expiry") or 999
    action  = str(row.get("vhs2_action") or row.get("vhs_action") or "보류")

    try: expiry = float(expiry)
    except: expiry = 999

    if g_inv >= 70:
        if expiry <= 7:
            sentences.append(f"⏰ 유통기한 {int(expiry)}일 — 폐기 위험이 매우 높습니다.")
        else:
            sentences.append("⚠️ 재고 위험 점수가 높아 우선 처리 대상입니다.")

    if g_sale >= 65 and g_move >= 60:
        sentences.append("📈 받는 점포의 판매 가능성과 이동 적합도가 높아 재배치 성공 가능성이 높습니다.")
    elif g_sale < 40:
        sentences.append("📉 판매 가능성이 낮아 할인 또는 폐기 전략을 검토하세요.")

    if g_avoid >= 65:
        sentences.append(f"💰 운송비 대비 폐기 회피 이익이 커서 우선 처리 대상입니다.")

    reloc_fail = float(row.get("relocation_failure_score", 0) or 0)
    if reloc_fail >= 60:
        sentences.append("🚨 재배치 실패 위험이 높아 할인 또는 보류 전략을 함께 검토하세요.")

    if g_exec < 35:
        sentences.append("🔧 실행 가능성이 낮습니다. 점포 처리 능력이나 거리를 확인하세요.")

    if corr > 4:
        sentences.append(f"🤖 이력 보정 +{corr:.1f}점 — 과거 유사 상황에서 긍정적 결과.")
    elif corr < -4:
        sentences.append(f"🤖 이력 보정 {corr:.1f}점 — 과거 유사 상황에서 주의 필요.")

    if not sentences:
        sentences.append(f"📋 VHS 종합 점수 기준 {action} 전략이 추천됩니다.")

    return sentences[:4]


def render_reason_expander(row: pd.Series, idx: int = 0) -> None:
    """Streamlit expander로 추천 근거 표시."""
    import streamlit as st

    with st.expander("📊 추천 근거 보기", expanded=False):
        breakdown = get_score_breakdown(row)
        sentences = get_reason_sentences(row)

        # 이유 문장
        st.markdown("**추천 이유**")
        for s in sentences:
            st.markdown(f"- {s}")

        # 구성 점수 바 차트
        st.markdown("---")
        st.markdown("**VHS 구성 점수**")
        _COLORS = {
            "재고 위험":     "#ef5350",
            "판매 가능성":   "#ab47bc",
            "이동 적합도":   "#42a5f5",
            "비용 절감":     "#26a69a",
            "폐기 회피 이익":"#ffa726",
            "실행 가능성":   "#66bb6a",
            "이력 보정":     "#78909c",
        }
        for label, val in breakdown.items():
            if val is None:
                continue
            color = _COLORS.get(label, "#aaa")
            pct = min(100, max(0, val if label != "이력 보정" else 50 + val*6))
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0;">'
                f'<div style="width:110px;font-size:12px;color:#555;">{label}</div>'
                f'<div style="flex:1;background:#eee;border-radius:3px;height:12px;">'
                f'<div style="width:{pct:.0f}%;background:{color};height:100%;border-radius:3px;"></div></div>'
                f'<div style="width:40px;text-align:right;font-size:12px;font-weight:700;">'
                f'{val:.0f}{"점" if label != "이력 보정" else ""}</div></div>',
                unsafe_allow_html=True,
            )
