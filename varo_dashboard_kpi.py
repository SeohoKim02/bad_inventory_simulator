"""
varo_dashboard_kpi.py
──────────────────────
모니터링 대시보드 KPI 계산 helpers.
기존 추천 로직 미수정. 표시 전용.
"""

import math
import pandas as pd

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 공통 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def safe_parse_number(value, default=0.0) -> float:
    try:
        if value is None: return default
        f = float(str(value).replace(",","").replace("원","").replace("%","").strip())
        return default if (math.isnan(f) or math.isinf(f)) else f
    except: return default

def safe_format_currency(value) -> str:
    v = safe_parse_number(value, None)
    if v is None: return "-"
    return f"{v:,.0f}원"

def safe_format_percent(value, digits=1) -> str:
    v = safe_parse_number(value, None)
    if v is None: return "-"
    return f"{v:.{digits}f}%"

def _col(df, *names, default=0.0):
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce").fillna(0)
    return pd.Series([default]*len(df), index=df.index)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Before / After 비용 계산
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_before_after_costs(df: pd.DataFrame) -> dict:
    """
    Before: 폐기비용(disposal_cost, disposal_cost_per_unit×qty) + estimated_cost(처리 없이 방치 기준)
    After:  이동비 + 할인손실 + 프로모션비 - 폐기회피효과
    """
    empty = {"before": None, "after": None, "savings": None, "savings_rate": None}
    if df is None or df.empty:
        return empty

    qty_s = _col(df, "suggested_qty","move_qty","recommended_qty")

    # Before: 처리 전 예상 손실
    # disposal_avoidance_profit (폐기 회피 이익) = 처리 전 예상 폐기 손실
    if "disposal_avoidance_profit" in df.columns:
        before = float(_col(df,"disposal_avoidance_profit").sum())
    elif "disposal_cost" in df.columns:
        before = float(_col(df,"disposal_cost").sum())
    elif "disposal_cost_per_unit" in df.columns:
        before = float((_col(df,"disposal_cost_per_unit") * qty_s).sum())
    elif "estimated_cost" in df.columns:
        # fallback: estimated_cost를 Before로 간주
        before = float(_col(df,"estimated_cost").sum())
    else:
        return empty

    # After: Varo 추천 실행 비용
    after_comps = []
    if "estimated_cost" in df.columns:
        after_comps.append(_col(df,"estimated_cost"))
    if "discount_loss_cost" in df.columns:
        after_comps.append(_col(df,"discount_loss_cost"))
    if "promotion_fixed_cost" in df.columns:
        after_comps.append(_col(df,"promotion_fixed_cost"))
    if "avoided_disposal_cost" in df.columns:
        after_comps.append(-_col(df,"avoided_disposal_cost"))
    if "promotion_net_benefit" in df.columns:
        nb = pd.to_numeric(df["promotion_net_benefit"], errors="coerce").fillna(0)
        after_comps.append(-nb.clip(lower=0))

    if not after_comps:
        return empty

    after = float(sum(s for s in after_comps).sum())
    savings = before - after
    savings_rate = (savings / before * 100) if before > 0 else None

    return {
        "before":       round(before, 0),
        "after":        round(after,  0),
        "savings":      round(savings, 0),
        "savings_rate": round(savings_rate, 1) if savings_rate is not None else None,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VHS 점수 요약
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_vhs_kpi(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"avg_score": None, "top_grade": "-", "top_strategy": "-"}
    sc_col = next((c for c in ["vhs2","heuristic_score","total_score"] if c in df.columns), None)
    avg_sc = round(float(pd.to_numeric(df[sc_col], errors="coerce").mean()), 1) if sc_col else None
    gr_col = next((c for c in ["vhs2_grade","heuristic_grade"] if c in df.columns), None)
    top_gr = df[gr_col].value_counts().index[0] if gr_col and not df[gr_col].empty else "-"
    st_col = next((c for c in ["vhs2_action","final_recommendation"] if c in df.columns), None)
    top_st = str(df[st_col].value_counts().index[0])[:10] if st_col and not df[st_col].empty else "-"
    return {"avg_score": avg_sc, "top_grade": str(top_gr), "top_strategy": top_st}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 액션 현황
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_action_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    rc = next((c for c in ["final_recommendation","vhs2_action"] if c in df.columns), None)
    if not rc:
        return {"total": len(df)}
    def _cnt(kws):
        return int(df[rc].astype(str).apply(lambda x: any(k in x for k in kws)).sum())
    return {
        "total":    len(df),
        "이동":     _cnt(["이동","재배치","transfer"]),
        "할인":     _cnt(["할인","discount","1+1","프로모션"]),
        "폐기":     _cnt(["폐기","dispose"]),
        "보류":     _cnt(["보류","검토","hold"]),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 모니터링 카드 CSS (최소 색상)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONITOR_CSS = """
<style>
.mcard {
    background: #fff;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 16px 18px 14px 18px;
    margin-bottom: 8px;
}
.mcard-label {
    font-size: 11px;
    color: #6B7280;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.mcard-value {
    font-size: 22px;
    font-weight: 800;
    color: #111827;
    line-height: 1.2;
    word-break: break-word;
    white-space: normal;
}
.mcard-sub {
    font-size: 11px;
    color: #6B7280;
    margin-top: 3px;
    word-break: break-word;
}
.mcard-badge {
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 12px;
    margin-top: 4px;
    background: #F3F4F6;
    color: #374151;
}
.mcard-badge.green { background: #DCFCE7; color: #166534; }
.mcard-badge.blue  { background: #DBEAFE; color: #1E40AF; }
.mcard-badge.yellow{ background: #FEF9C3; color: #854D0E; }
.mcard-badge.gray  { background: #F3F4F6; color: #374151; }
.mbar-bg {
    background: #F3F4F6;
    border-radius: 4px;
    height: 5px;
    margin-top: 8px;
    overflow: hidden;
}
.mbar-fill {
    height: 5px;
    border-radius: 4px;
    background: #2F8F57;
}
.maction-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 6px;
}
.maction-item {
    font-size: 12px;
    color: #374151;
}
.maction-num {
    font-size: 18px;
    font-weight: 800;
    color: #111827;
    display: block;
}
</style>
"""

def _mcard(label: str, value: str, sub: str = "", badge: str = "",
           badge_cls: str = "gray", bar_pct: float = None) -> str:
    bar_html = ""
    if bar_pct is not None:
        pct = max(0.0, min(100.0, bar_pct))
        bar_html = f'<div class="mbar-bg"><div class="mbar-fill" style="width:{pct}%"></div></div>'
    badge_html = f'<span class="mcard-badge {badge_cls}">{badge}</span>' if badge else ""
    sub_html   = f'<div class="mcard-sub">{sub}</div>' if sub else ""
    return f"""<div class="mcard">
  <div class="mcard-label">{label}</div>
  <div class="mcard-value">{value}</div>
  {badge_html}{sub_html}{bar_html}
</div>"""
