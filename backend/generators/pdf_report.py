"""
Generates a multi-page PDF equity research report from agent state.
Uses reportlab platypus for clean, professional output.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand palette
NAVY = colors.HexColor("#1E2761")
ACCENT = colors.HexColor("#C5A572")
LIGHT_GRAY = colors.HexColor("#F4F4F8")
DARK_GRAY = colors.HexColor("#333333")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(
        name="ReportTitle", fontName="Helvetica-Bold", fontSize=22,
        textColor=NAVY, spaceAfter=6, leading=26,
    ))
    s.add(ParagraphStyle(
        name="Subtitle", fontName="Helvetica", fontSize=11,
        textColor=DARK_GRAY, spaceAfter=20,
    ))
    s.add(ParagraphStyle(
        name="SectionHeader", fontName="Helvetica-Bold", fontSize=13,
        textColor=NAVY, spaceBefore=14, spaceAfter=8, leading=16,
    ))
    s.add(ParagraphStyle(
        name="Body", fontName="Helvetica", fontSize=10,
        textColor=DARK_GRAY, leading=14, alignment=TA_JUSTIFY, spaceAfter=8,
    ))
    s.add(ParagraphStyle(
        name="RecBadge", fontName="Helvetica-Bold", fontSize=14,
        textColor=colors.white, alignment=TA_LEFT,
    ))
    return s


def _rec_color(rec: str):
    return {
        "BUY": colors.HexColor("#0F8B5C"),
        "HOLD": colors.HexColor("#C5A572"),
        "SELL": colors.HexColor("#B33A3A"),
    }.get(rec, colors.gray)


def _fmt_money(v, suffix: str = "") -> str:
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


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    try:
        v = float(v)
        return f"{v * 100:.2f}%" if abs(v) < 5 else f"{v:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _bullets_from_text(text: str) -> list[str]:
    """Split LLM-produced bullet text into clean lines."""
    if not text:
        return []
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Strip common bullet prefixes
        for prefix in ("- ", "* ", "• "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        if line and line[0].isdigit() and len(line) > 2 and line[1] in ".)":
            line = line[2:].strip()
        out.append(line)
    return out


def generate_pdf_report(state: dict) -> bytes:
    """Build the full PDF and return its bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    )
    s = _styles()
    story = []

    profile = state["company_data"]["profile"]
    metrics = state["company_data"]["metrics"]
    val = state.get("dcf_valuation", {})
    rec = state.get("recommendation", "HOLD")
    target = state.get("target_price", 0)

    # --- HEADER ---
    story.append(Paragraph(f"{profile['name']} ({profile['ticker']})", s["ReportTitle"]))
    story.append(Paragraph(
        f"Equity Research Report &nbsp;|&nbsp; {profile.get('sector', 'N/A')} &nbsp;|&nbsp; "
        f"Generated {datetime.now().strftime('%B %d, %Y')}",
        s["Subtitle"],
    ))

    # --- RECOMMENDATION BANNER ---
    upside = val.get("upside_pct", 0)
    current = metrics.get("current_price") or 0
    banner_data = [[
        Paragraph(f"<b>{rec}</b>", s["RecBadge"]),
        Paragraph(f"<b>Target:</b> ${target:,.2f}", s["RecBadge"]),
        Paragraph(f"<b>Current:</b> ${current:,.2f}", s["RecBadge"]),
        Paragraph(f"<b>Upside:</b> {upside * 100:+.1f}%", s["RecBadge"]),
    ]]
    banner = Table(banner_data, colWidths=[1.4 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _rec_color(rec)),
        ("BACKGROUND", (1, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(banner)
    story.append(Spacer(1, 0.2 * inch))

    # --- EXECUTIVE SUMMARY ---
    story.append(Paragraph("Executive Summary", s["SectionHeader"]))
    for para in (state.get("executive_summary", "") or "").split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), s["Body"]))

    # --- KEY METRICS TABLE ---
    story.append(Paragraph("Key Financial Metrics", s["SectionHeader"]))
    metrics_data = [
        ["Metric", "Value", "Metric", "Value"],
        ["Market Cap", _fmt_money(profile.get("market_cap")),
         "Revenue (TTM)", _fmt_money(metrics.get("total_revenue"))],
        ["P/E (TTM)", f"{metrics.get('pe_ratio'):.2f}" if metrics.get("pe_ratio") else "N/A",
         "Forward P/E", f"{metrics.get('forward_pe'):.2f}" if metrics.get("forward_pe") else "N/A"],
        ["EV / EBITDA", f"{metrics.get('ev_to_ebitda'):.2f}" if metrics.get("ev_to_ebitda") else "N/A",
         "Price / Book", f"{metrics.get('price_to_book'):.2f}" if metrics.get("price_to_book") else "N/A"],
        ["Profit Margin", _fmt_pct(metrics.get("profit_margin")),
         "Operating Margin", _fmt_pct(metrics.get("operating_margin"))],
        ["ROE", _fmt_pct(metrics.get("roe")),
         "Revenue Growth", _fmt_pct(metrics.get("revenue_growth"))],
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
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(mt)

    story.append(PageBreak())

    # --- BUSINESS OVERVIEW ---
    story.append(Paragraph("Business Overview", s["SectionHeader"]))
    for para in (state.get("business_overview", "") or "").split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), s["Body"]))

    # --- COMPETITIVE POSITION ---
    story.append(Paragraph("Competitive Positioning", s["SectionHeader"]))
    for para in (state.get("competitive_position", "") or "").split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), s["Body"]))

    # --- INVESTMENT THESIS ---
    story.append(Paragraph("Investment Thesis (Bull Case)", s["SectionHeader"]))
    for b in _bullets_from_text(state.get("investment_thesis", "")):
        story.append(Paragraph(f"• {b}", s["Body"]))

    # --- RISKS ---
    story.append(Paragraph("Key Risks (Bear Case)", s["SectionHeader"]))
    for b in _bullets_from_text(state.get("risks", "")):
        story.append(Paragraph(f"• {b}", s["Body"]))

    story.append(PageBreak())

    # --- DCF VALUATION ---
    story.append(Paragraph("DCF Valuation", s["SectionHeader"]))
    assumptions = state.get("dcf_assumptions", {})
    story.append(Paragraph(
        f"<b>Rationale:</b> {assumptions.get('rationale', 'N/A')}", s["Body"],
    ))
    story.append(Paragraph(
        f"<b>Assumptions:</b> WACC {assumptions.get('wacc', 0) * 100:.1f}%, "
        f"Terminal growth {assumptions.get('terminal_growth', 0) * 100:.1f}%, "
        f"FCF margin {assumptions.get('fcf_margin', 0) * 100:.1f}%",
        s["Body"],
    ))

    # 5-year projection table
    rev = val.get("projected_revenues", [])
    fcf = val.get("projected_fcfs", [])
    pv = val.get("pv_fcfs", [])
    if rev:
        proj_header = ["Year"] + [f"Y{i + 1}" for i in range(len(rev))]
        proj_data = [
            proj_header,
            ["Revenue"] + [_fmt_money(r) for r in rev],
            ["FCF"] + [_fmt_money(f) for f in fcf],
            ["PV of FCF"] + [_fmt_money(p) for p in pv],
        ]
        pt = Table(proj_data, colWidths=[1.0 * inch] + [1.0 * inch] * len(rev))
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(Spacer(1, 0.1 * inch))
        story.append(pt)

    # Valuation summary
    val_data = [
        ["Sum of PV of FCF", _fmt_money(sum(pv)) if pv else "N/A"],
        ["PV of Terminal Value", _fmt_money(val.get("pv_terminal"))],
        ["Enterprise Value", _fmt_money(val.get("enterprise_value"))],
        ["Equity Value", _fmt_money(val.get("equity_value"))],
        ["Implied Share Price", f"${val.get('implied_share_price', 0):,.2f}"],
        ["Current Share Price", f"${val.get('current_share_price', 0):,.2f}"],
        ["Implied Upside / (Downside)", f"{val.get('upside_pct', 0) * 100:+.1f}%"],
    ]
    vt = Table(val_data, colWidths=[2.5 * inch, 2.0 * inch])
    vt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, -1), (-1, -1), ACCENT),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(vt)

    # --- DISCLAIMER ---
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "<i>Disclaimer: This report is generated by an AI agent for educational and demonstration purposes "
        "only. It is not investment advice. Data sourced from Yahoo Finance via yfinance. DCF assumptions "
        "are LLM-generated estimates and should not be used for actual investment decisions.</i>",
        ParagraphStyle("Disclaimer", parent=s["Body"], fontSize=8, textColor=colors.gray),
    ))

    doc.build(story)
    return buf.getvalue()
