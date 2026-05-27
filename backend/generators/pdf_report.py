"""
Multi-page PDF research report.
Uses reportlab platypus with KeepTogether/KeepInFrame to prevent layout bugs.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Palette
NAVY = colors.HexColor("#1E2761")
NAVY_DARK = colors.HexColor("#0F1538")
ACCENT = colors.HexColor("#C5A572")
LIGHT_GRAY = colors.HexColor("#F4F4F8")
DARK_GRAY = colors.HexColor("#333333")
MID_GRAY = colors.HexColor("#6B7280")
GREEN = colors.HexColor("#0F8B5C")
RED = colors.HexColor("#B33A3A")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=24, textColor=NAVY, leading=28, spaceAfter=4))
    s.add(ParagraphStyle(name="Subtitle", fontName="Helvetica", fontSize=11, textColor=DARK_GRAY, spaceAfter=14))
    s.add(ParagraphStyle(name="SectionHeader", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, spaceBefore=16, spaceAfter=10, leading=17))
    s.add(ParagraphStyle(name="SubHeader", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, spaceBefore=10, spaceAfter=6, leading=14))
    s.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=10, textColor=DARK_GRAY, leading=14, alignment=TA_JUSTIFY, spaceAfter=8))
    s.add(ParagraphStyle(name="BodyLeft", fontName="Helvetica", fontSize=10, textColor=DARK_GRAY, leading=14, alignment=TA_LEFT, spaceAfter=6))
    s.add(ParagraphStyle(name="Caption", fontName="Helvetica-Oblique", fontSize=9, textColor=MID_GRAY, leading=12))
    s.add(ParagraphStyle(name="WhiteBoldCenter", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, alignment=TA_CENTER, leading=14))
    s.add(ParagraphStyle(name="WhiteBold", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white, leading=14))
    return s


def _rec_color(rec):
    return {"BUY": GREEN, "HOLD": ACCENT, "SELL": RED}.get(rec, MID_GRAY)


def _impact_color(impact):
    return {
        "POSITIVE": GREEN,
        "NEGATIVE": RED,
        "NEUTRAL": MID_GRAY,
        "WATCH": ACCENT,
    }.get(impact, MID_GRAY)


def _fmt_money(v, suffix=""):
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "N/A"
    abs_v = abs(v)
    if abs_v >= 1e12:
        return f"${v / 1e12:.2f}T{suffix}"
    if abs_v >= 1e9:
        return f"${v / 1e9:.2f}B{suffix}"
    if abs_v >= 1e6:
        return f"${v / 1e6:.2f}M{suffix}"
    return f"${v:,.2f}{suffix}"


def _fmt_pct(v, decimals=1):
    if v is None:
        return "N/A"
    try:
        v = float(v)
        return f"{v * 100:.{decimals}f}%" if abs(v) < 5 else f"{v:.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_signed_pct(v):
    if v is None:
        return "N/A"
    n = float(v) * 100
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.1f}%"


def _bullets_from_text(text):
    if not text:
        return []
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for prefix in ("- ", "* ", "• "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        if line and line[0].isdigit() and len(line) > 2 and line[1] in ".)":
            line = line[2:].strip()
        out.append(line)
    return out


def generate_pdf_report(state):
    """Build the full multi-section PDF report."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.6 * inch,
        title="Equity Research Report",
    )
    s = _styles()
    story = []

    profile = state["company_data"]["profile"]
    metrics = state["company_data"]["metrics"]
    val = state.get("dcf_valuation", {})
    rec = state.get("recommendation", "HOLD")
    target = state.get("target_price", 0)
    current = metrics.get("current_price") or 0
    upside = (target / current - 1) if current and target else 0
    confidence = state.get("confidence_score", 5)
    target_low = state.get("target_range_low")
    target_high = state.get("target_range_high")
    stock_type = state.get("stock_type", "BALANCED")
    framework = state.get("valuation_framework", "DCF-led")

    # ============================================================
    # HEADER
    # ============================================================
    story.append(Paragraph(f"{profile['name']} ({profile['ticker']})", s["ReportTitle"]))
    story.append(Paragraph(
        f"Equity Research  |  {profile.get('sector', 'N/A')}  |  "
        f"{datetime.now().strftime('%B %d, %Y')}",
        s["Subtitle"],
    ))

    # ============================================================
    # RECOMMENDATION BANNER
    # ============================================================
    banner_data = [[
        Paragraph(rec, ParagraphStyle("RecBig", parent=s["WhiteBoldCenter"], fontSize=20)),
        Paragraph(
            f"<font size=8>TARGET</font><br/><b>${target:,.2f}</b>",
            s["WhiteBold"],
        ),
        Paragraph(
            f"<font size=8>CURRENT</font><br/><b>${current:,.2f}</b>",
            s["WhiteBold"],
        ),
        Paragraph(
            f"<font size=8>UPSIDE</font><br/><b>{upside * 100:+.1f}%</b>",
            s["WhiteBold"],
        ),
        Paragraph(
            f"<font size=8>CONFIDENCE</font><br/><b>{confidence}/10</b>",
            s["WhiteBold"],
        ),
    ]]
    banner = Table(banner_data, colWidths=[1.4 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch], rowHeights=[0.65 * inch])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _rec_color(rec)),
        ("BACKGROUND", (1, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(banner)
    story.append(Spacer(1, 0.05 * inch))

    # Stock type + framework strip
    type_strip = Table(
        [[Paragraph(
            f"<font color='#6B7280'>Stock type:</font> <b>{stock_type}</b>  &nbsp;  "
            f"<font color='#6B7280'>Framework:</font> <b>{framework}</b>  &nbsp;  "
            + (f"<font color='#6B7280'>Range:</font> <b>${target_low:,.0f} – ${target_high:,.0f}</b>"
               if target_low and target_high else ""),
            ParagraphStyle("TypeStrip", parent=s["BodyLeft"], fontSize=9, textColor=DARK_GRAY),
        )]],
        colWidths=[7 * inch],
    )
    type_strip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(type_strip)
    story.append(Spacer(1, 0.2 * inch))

    # ============================================================
    # EXECUTIVE SUMMARY
    # ============================================================
    story.append(Paragraph("Executive Summary", s["SectionHeader"]))
    summary_text = state.get("executive_summary", "") or ""
    for para in summary_text.split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), s["Body"]))

    # ============================================================
    # THE CALL CALLOUT (confidence, what would change mind, momentum)
    # ============================================================
    conf_rationale = state.get("confidence_rationale", "")
    change_mind = state.get("what_would_change_mind", "")
    momentum_data = (state.get("company_data") or {}).get("momentum", {}) or {}

    call_rows = []
    if conf_rationale:
        call_rows.append([
            Paragraph(f"<b>Confidence: {confidence}/10</b>", s["BodyLeft"]),
            Paragraph(conf_rationale, s["BodyLeft"]),
        ])
    if change_mind:
        call_rows.append([
            Paragraph("<b>What would change our mind</b>", s["BodyLeft"]),
            Paragraph(change_mind, s["BodyLeft"]),
        ])
    if any(momentum_data.values()):
        mom_str = (
            f"1M: {_fmt_signed_pct(momentum_data.get('price_1mo_pct'))}  |  "
            f"3M: {_fmt_signed_pct(momentum_data.get('price_3mo_pct'))}  |  "
            f"YTD: {_fmt_signed_pct(momentum_data.get('price_ytd_pct'))}  |  "
            f"1Y: {_fmt_signed_pct(momentum_data.get('price_1yr_pct'))}"
        )
        call_rows.append([
            Paragraph("<b>Price momentum</b>", s["BodyLeft"]),
            Paragraph(mom_str, s["BodyLeft"]),
        ])

    if call_rows:
        story.append(Spacer(1, 0.1 * inch))
        call_box = Table(call_rows, colWidths=[1.7 * inch, 5.3 * inch])
        call_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LINEABOVE", (0, 0), (-1, 0), 2, ACCENT),
            ("LINEBELOW", (0, -1), (-1, -1), 2, ACCENT),
        ]))
        story.append(call_box)

    story.append(Spacer(1, 0.2 * inch))

    # ============================================================
    # KEY FINANCIAL METRICS
    # ============================================================
    story.append(Paragraph("Key Financial Metrics", s["SectionHeader"]))
    metrics_data = [
        ["Metric", "Value", "Metric", "Value"],
        ["Market Cap", _fmt_money(profile.get("market_cap")), "Revenue (TTM)", _fmt_money(metrics.get("total_revenue"))],
        ["P/E (TTM)", f"{metrics.get('pe_ratio'):.2f}" if metrics.get("pe_ratio") else "N/A",
         "EV / EBITDA", f"{metrics.get('ev_to_ebitda'):.2f}" if metrics.get("ev_to_ebitda") else "N/A"],
        ["Profit Margin", _fmt_pct(metrics.get("profit_margin")),
         "Operating Margin", _fmt_pct(metrics.get("operating_margin"))],
        ["ROE", _fmt_pct(metrics.get("roe")), "Revenue Growth", _fmt_pct(metrics.get("revenue_growth"))],
        ["Free Cash Flow", _fmt_money(metrics.get("free_cash_flow")),
         "Total Debt", _fmt_money(metrics.get("total_debt"))],
        ["52W High", f"${metrics.get('52w_high'):,.2f}" if metrics.get("52w_high") else "N/A",
         "52W Low", f"${metrics.get('52w_low'):,.2f}" if metrics.get("52w_low") else "N/A"],
        ["Beta", f"{metrics.get('beta'):.2f}" if metrics.get("beta") else "N/A",
         "Dividend Yield", _fmt_pct(metrics.get("dividend_yield"))],
    ]
    mt = Table(metrics_data, colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(mt)

    story.append(PageBreak())

    # ============================================================
    # BUSINESS MODEL & MOAT
    # ============================================================
    if state.get("business_overview") or state.get("moat"):
        story.append(Paragraph("Business Model", s["SectionHeader"]))
        for para in (state.get("business_overview", "") or "").split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), s["Body"]))

    if state.get("moat"):
        story.append(Paragraph("Competitive Moat", s["SubHeader"]))
        for para in (state.get("moat", "") or "").split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), s["Body"]))

    if state.get("margin_trajectory"):
        story.append(Paragraph("Margin & Returns Trajectory", s["SubHeader"]))
        for para in (state.get("margin_trajectory", "") or "").split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), s["Body"]))

    # ============================================================
    # INVESTMENT THESIS (BULL CASE)
    # ============================================================
    if state.get("investment_thesis"):
        story.append(Paragraph("Investment Thesis", s["SectionHeader"]))
        for b in _bullets_from_text(state.get("investment_thesis", "")):
            story.append(Paragraph(f"•&nbsp;&nbsp;{b}", s["Body"]))

    # ============================================================
    # KEY RISKS (BEAR CASE)
    # ============================================================
    risks = state.get("key_risks") or state.get("risks") or ""
    if risks:
        story.append(Paragraph("Key Risks", s["SectionHeader"]))
        for b in _bullets_from_text(risks):
            story.append(Paragraph(f"•&nbsp;&nbsp;{b}", s["Body"]))

    # ============================================================
    # NEAR-TERM CATALYSTS
    # ============================================================
    catalysts = state.get("catalysts", []) or []
    if catalysts:
        story.append(Paragraph("Near-Term Catalysts", s["SectionHeader"]))
        cat_rows = []
        for c in catalysts:
            impact = (c.get("impact") or "WATCH").upper()
            cat_rows.append([
                Paragraph(impact, ParagraphStyle(
                    "ImpactCell", fontName="Helvetica-Bold", fontSize=9,
                    textColor=colors.white, alignment=TA_CENTER, leading=11,
                )),
                Paragraph(
                    f"<b>{c.get('headline', '')}</b><br/>"
                    f"<font size=9 color='#6B7280'>{c.get('interpretation', '')}</font>",
                    s["BodyLeft"]
                ),
            ])
        cat_table = Table(cat_rows, colWidths=[0.9 * inch, 6.1 * inch])
        style_rows = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
        ]
        for i, c in enumerate(catalysts):
            impact = (c.get("impact") or "WATCH").upper()
            style_rows.append(("BACKGROUND", (0, i), (0, i), _impact_color(impact)))
        cat_table.setStyle(TableStyle(style_rows))
        story.append(cat_table)

    story.append(PageBreak())

    # ============================================================
    # MARKET POSITIONING (technicals + macro)
    # ============================================================
    if state.get("technicals_read"):
        story.append(Paragraph("Market Positioning", s["SectionHeader"]))
        story.append(Paragraph(state["technicals_read"], s["Body"]))

    if state.get("macro_view"):
        story.append(Paragraph("Sector & Macro Context", s["SubHeader"]))
        story.append(Paragraph(state["macro_view"], s["Body"]))

    # ============================================================
    # PEER COMPARISON
    # ============================================================
    peer_table = state.get("peer_table", []) or []
    peer_interp = state.get("peer_interpretation", "")
    if peer_table or peer_interp:
        story.append(Paragraph("Peer Comparison", s["SectionHeader"]))
        if peer_table:
            comp_data = [["Ticker", "Mkt Cap", "P/E", "EV/EBITDA", "EV/Sales", "P/B"]]
            subj_row_idx = None
            for i, p in enumerate(peer_table):
                if p.get("is_subject"):
                    subj_row_idx = i + 1
                comp_data.append([
                    p.get("ticker", ""),
                    _fmt_money(p.get("market_cap")),
                    f"{p['pe']:.1f}" if p.get("pe") else "—",
                    f"{p['ev_ebitda']:.1f}" if p.get("ev_ebitda") else "—",
                    f"{p['ev_sales']:.1f}" if p.get("ev_sales") else "—",
                    f"{p['pb']:.1f}" if p.get("pb") else "—",
                ])
            ct = Table(comp_data, colWidths=[0.9 * inch, 1.4 * inch, 0.9 * inch, 1.1 * inch, 1.1 * inch, 0.9 * inch])
            style_rows = [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            if subj_row_idx is not None:
                style_rows.append(("BACKGROUND", (0, subj_row_idx), (-1, subj_row_idx), ACCENT))
                style_rows.append(("TEXTCOLOR", (0, subj_row_idx), (-1, subj_row_idx), colors.white))
                style_rows.append(("FONTNAME", (0, subj_row_idx), (-1, subj_row_idx), "Helvetica-Bold"))
            ct.setStyle(TableStyle(style_rows))
            story.append(ct)
            story.append(Spacer(1, 0.1 * inch))

        if peer_interp:
            story.append(Paragraph(peer_interp, s["Body"]))

    # ============================================================
    # BULL vs BEAR DEBATE
    # ============================================================
    bull = state.get("bull_case", "")
    bear = state.get("bear_case", "")
    if bull or bear:
        story.append(PageBreak())
        story.append(Paragraph("Bull vs Bear Debate", s["SectionHeader"]))

        debate_rows = [[
            Paragraph("THE BULL", ParagraphStyle("BullHead", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, alignment=TA_CENTER)),
            Paragraph("THE BEAR", ParagraphStyle("BearHead", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, alignment=TA_CENTER)),
        ], [
            Paragraph(bull.replace("\n", "<br/>") if bull else "—", s["BodyLeft"]),
            Paragraph(bear.replace("\n", "<br/>") if bear else "—", s["BodyLeft"]),
        ]]
        dt = Table(debate_rows, colWidths=[3.4 * inch, 3.4 * inch])
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), GREEN),
            ("BACKGROUND", (1, 0), (1, 0), RED),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#F5FAF7")),
            ("BACKGROUND", (1, 1), (1, 1), colors.HexColor("#FBF5F5")),
        ]))
        story.append(dt)

    # ============================================================
    # VALUATION SECTION
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("Valuation", s["SectionHeader"]))

    # Methodology weights
    weights = state.get("valuation_weights", {}) or {}
    if weights:
        weight_text = (
            f"<b>Weighting:</b> DCF {weights.get('dcf', 0) * 100:.0f}% / "
            f"Comps {weights.get('comps', 0) * 100:.0f}% / "
            f"Scenarios {weights.get('scenarios', 0) * 100:.0f}%"
        )
        story.append(Paragraph(weight_text, s["BodyLeft"]))
        story.append(Spacer(1, 0.08 * inch))

    # Scenarios table (bull/base/bear)
    scenarios = state.get("scenarios", {}) or {}
    if scenarios:
        story.append(Paragraph("Scenarios", s["SubHeader"]))
        sc_rows = [["Scenario", "Implied Price", "Upside", "Description"]]
        for label, key, color in [("Bull", "bull", GREEN), ("Base", "base", NAVY), ("Bear", "bear", RED)]:
            sc = scenarios.get(key, {})
            if not sc:
                continue
            sc_rows.append([
                label,
                f"${sc.get('price', 0):,.2f}",
                f"{sc.get('upside_pct', 0) * 100:+.1f}%",
                sc.get("description", ""),
            ])
        if len(sc_rows) > 1:
            sc_table = Table(sc_rows, colWidths=[0.7 * inch, 1.1 * inch, 0.9 * inch, 4.3 * inch])
            sc_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ALIGN", (1, 0), (2, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TEXTCOLOR", (0, 1), (0, 1), GREEN),
                ("TEXTCOLOR", (0, 3), (0, 3), RED) if len(sc_rows) >= 4 else (),
            ]))
            story.append(sc_table)
            story.append(Spacer(1, 0.15 * inch))

    # DCF details
    if val and val.get("projected_revenues"):
        story.append(Paragraph("DCF Detail", s["SubHeader"]))
        assumptions = val.get("assumptions") or state.get("dcf_assumptions", {})
        if assumptions:
            story.append(Paragraph(
                f"<b>Assumptions:</b> WACC {assumptions.get('wacc', 0) * 100:.1f}% | "
                f"Terminal growth {assumptions.get('terminal_growth', 0) * 100:.1f}% | "
                f"FCF margin {assumptions.get('fcf_margin', 0) * 100:.1f}%",
                s["BodyLeft"],
            ))
            if assumptions.get("rationale"):
                story.append(Paragraph(f"<i>{assumptions['rationale']}</i>", s["Caption"]))
            story.append(Spacer(1, 0.08 * inch))

        rev = val.get("projected_revenues", [])
        fcf = val.get("projected_fcfs", [])
        pv = val.get("pv_fcfs", [])
        if rev:
            proj_data = [["Year"] + [f"Y{i + 1}" for i in range(len(rev))]]
            proj_data.append(["Revenue"] + [_fmt_money(r) for r in rev])
            proj_data.append(["FCF"] + [_fmt_money(f) for f in fcf])
            proj_data.append(["PV(FCF)"] + [_fmt_money(p) for p in pv])
            col_w = (7 * inch) / (len(rev) + 1)
            pt = Table(proj_data, colWidths=[col_w] * (len(rev) + 1))
            pt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(pt)

    # ============================================================
    # FINAL: Stock type rationale + disclaimer
    # ============================================================
    if state.get("stock_type_rationale"):
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph(
            f"<b>Classification:</b> {state['stock_type_rationale']}",
            s["Caption"],
        ))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "<i>Disclaimer: Generated by an AI multi-agent research system for educational and demonstration "
        "purposes only. Not investment advice. Financial data sourced from Financial Modeling Prep. "
        "DCF and scenario assumptions are LLM-generated estimates. Past performance does not predict "
        "future returns. Do your own research.</i>",
        s["Caption"],
    ))

    doc.build(story)
    return buf.getvalue()
