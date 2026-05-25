"""
Excel DCF model generator. Builds a workbook with LIVE formulas so a user
can override assumptions and watch the valuation update — like a real model.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = "1E2761"
GOLD = "C5A572"
LIGHT = "F4F4F8"
WHITE = "FFFFFF"


def _border():
    s = Side(border_style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


def _header_style(cell):
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.font = Font(name="Calibri", size=11, bold=True, color=WHITE)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = _border()


def _label_style(cell):
    cell.font = Font(name="Calibri", size=11, bold=True, color="222233")
    cell.alignment = Alignment(horizontal="left", vertical="center")
    cell.border = _border()


def _value_style(cell, fmt: str = "#,##0"):
    cell.font = Font(name="Calibri", size=11)
    cell.alignment = Alignment(horizontal="right", vertical="center")
    cell.number_format = fmt
    cell.border = _border()


def _input_style(cell, fmt: str = "0.0%"):
    """Input cells the user can override — pale gold highlight."""
    cell.fill = PatternFill("solid", fgColor=GOLD)
    cell.font = Font(name="Calibri", size=11, bold=True, color="222233")
    cell.alignment = Alignment(horizontal="right", vertical="center")
    cell.number_format = fmt
    cell.border = _border()


def _highlight_style(cell, fmt: str = "$#,##0.00"):
    cell.fill = PatternFill("solid", fgColor=GOLD)
    cell.font = Font(name="Calibri", size=12, bold=True, color="FFFFFF")
    cell.alignment = Alignment(horizontal="right", vertical="center")
    cell.number_format = fmt
    cell.border = _border()


def generate_dcf_model(state: dict) -> bytes:
    """Build the workbook and return bytes."""
    wb = Workbook()

    profile = state["company_data"]["profile"]
    metrics = state["company_data"]["metrics"]
    assumptions = state.get("dcf_assumptions", {})
    val = state.get("dcf_valuation", {})

    # ============================================================
    # Sheet 1: DCF Model
    # ============================================================
    ws = wb.active
    ws.title = "DCF Model"
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 22
    for col in range(3, 8):
        ws.column_dimensions[get_column_letter(col)].width = 18

    # --- Title ---
    ws["A1"] = f"DCF Valuation Model — {profile['name']} ({profile['ticker']})"
    ws["A1"].font = Font(name="Georgia", size=16, bold=True, color=NAVY)
    ws.merge_cells("A1:G1")
    ws.row_dimensions[1].height = 28

    ws["A2"] = "Inputs in gold are editable. Outputs update automatically."
    ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="666666")
    ws.merge_cells("A2:G2")

    # --- Assumptions section ---
    row = 4
    ws[f"A{row}"] = "ASSUMPTIONS"
    _header_style(ws[f"A{row}"])
    ws.merge_cells(f"A{row}:G{row}")

    row += 1
    ws[f"A{row}"] = "Base Year Revenue"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = metrics.get("total_revenue") or 1e9
    _input_style(ws[f"B{row}"], fmt="$#,##0")
    base_rev_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "FCF Margin"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = assumptions.get("fcf_margin", 0.12)
    _input_style(ws[f"B{row}"])
    margin_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "WACC (Discount Rate)"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = assumptions.get("wacc", 0.09)
    _input_style(ws[f"B{row}"])
    wacc_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Terminal Growth Rate"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = assumptions.get("terminal_growth", 0.025)
    _input_style(ws[f"B{row}"])
    tg_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Net Debt"
    _label_style(ws[f"A{row}"])
    net_debt = (metrics.get("total_debt") or 0) - (metrics.get("total_cash") or 0)
    ws[f"B{row}"] = net_debt
    _input_style(ws[f"B{row}"], fmt="$#,##0")
    nd_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Shares Outstanding"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = metrics.get("shares_outstanding") or 1
    _input_style(ws[f"B{row}"], fmt="#,##0")
    shares_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Current Share Price"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = metrics.get("current_price") or 0
    _input_style(ws[f"B{row}"], fmt="$#,##0.00")
    current_price_cell = f"B{row}"

    # --- 5-Year Projection table ---
    row += 2
    proj_start_row = row
    ws[f"A{row}"] = "5-YEAR PROJECTION"
    _header_style(ws[f"A{row}"])
    ws.merge_cells(f"A{row}:G{row}")

    row += 1
    ws[f"A{row}"] = ""
    _label_style(ws[f"A{row}"])
    for i in range(1, 6):
        ws.cell(row=row, column=1 + i, value=f"Year {i}")
        _header_style(ws.cell(row=row, column=1 + i))
    ws.cell(row=row, column=7, value="Terminal")
    _header_style(ws.cell(row=row, column=7))

    # Growth rate row
    row += 1
    ws[f"A{row}"] = "Revenue Growth Rate"
    _label_style(ws[f"A{row}"])
    growth_row = row
    for i in range(1, 6):
        c = ws.cell(row=row, column=1 + i)
        c.value = assumptions.get(f"revenue_growth_y{i}", 0.05)
        _input_style(c)
    ws.cell(row=row, column=7, value=f"={tg_cell}")
    _value_style(ws.cell(row=row, column=7), fmt="0.0%")

    # Revenue row (formula-driven)
    row += 1
    ws[f"A{row}"] = "Revenue"
    _label_style(ws[f"A{row}"])
    rev_row = row
    ws.cell(row=row, column=2, value=f"={base_rev_cell}*(1+{get_column_letter(2)}{growth_row})")
    _value_style(ws.cell(row=row, column=2), fmt="$#,##0")
    for i in range(2, 6):
        col = 1 + i
        prev_col = get_column_letter(col - 1)
        cur_col = get_column_letter(col)
        ws.cell(row=row, column=col,
                value=f"={prev_col}{rev_row}*(1+{cur_col}{growth_row})")
        _value_style(ws.cell(row=row, column=col), fmt="$#,##0")

    # Free Cash Flow row
    row += 1
    ws[f"A{row}"] = "Free Cash Flow"
    _label_style(ws[f"A{row}"])
    fcf_row = row
    for i in range(1, 6):
        col = 1 + i
        col_letter = get_column_letter(col)
        ws.cell(row=row, column=col,
                value=f"={col_letter}{rev_row}*{margin_cell}")
        _value_style(ws.cell(row=row, column=col), fmt="$#,##0")
    # Terminal FCF
    ws.cell(row=row, column=7,
            value=f"={get_column_letter(6)}{fcf_row}*(1+{tg_cell})")
    _value_style(ws.cell(row=row, column=7), fmt="$#,##0")

    # Discount factor row
    row += 1
    ws[f"A{row}"] = "Discount Factor"
    _label_style(ws[f"A{row}"])
    disc_row = row
    for i in range(1, 6):
        col = 1 + i
        ws.cell(row=row, column=col,
                value=f"=1/(1+{wacc_cell})^{i}")
        _value_style(ws.cell(row=row, column=col), fmt="0.0000")

    # PV of FCF row
    row += 1
    ws[f"A{row}"] = "PV of FCF"
    _label_style(ws[f"A{row}"])
    pv_row = row
    for i in range(1, 6):
        col = 1 + i
        col_letter = get_column_letter(col)
        ws.cell(row=row, column=col,
                value=f"={col_letter}{fcf_row}*{col_letter}{disc_row}")
        _value_style(ws.cell(row=row, column=col), fmt="$#,##0")

    # Terminal Value
    row += 1
    ws[f"A{row}"] = "Terminal Value (Gordon Growth)"
    _label_style(ws[f"A{row}"])
    tv_row = row
    ws.cell(row=row, column=7,
            value=f"={get_column_letter(7)}{fcf_row}/({wacc_cell}-{tg_cell})")
    _value_style(ws.cell(row=row, column=7), fmt="$#,##0")

    # PV of Terminal Value
    row += 1
    ws[f"A{row}"] = "PV of Terminal Value"
    _label_style(ws[f"A{row}"])
    pv_tv_row = row
    ws.cell(row=row, column=7,
            value=f"=G{tv_row}/(1+{wacc_cell})^5")
    _value_style(ws.cell(row=row, column=7), fmt="$#,##0")

    # --- Valuation summary ---
    row += 2
    ws[f"A{row}"] = "VALUATION OUTPUT"
    _header_style(ws[f"A{row}"])
    ws.merge_cells(f"A{row}:G{row}")

    row += 1
    ws[f"A{row}"] = "Sum of PV of FCF"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"=SUM(B{pv_row}:F{pv_row})"
    _value_style(ws[f"B{row}"], fmt="$#,##0")
    sum_pv_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "PV of Terminal Value"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"=G{pv_tv_row}"
    _value_style(ws[f"B{row}"], fmt="$#,##0")
    pv_tv_summary_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Enterprise Value"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={sum_pv_cell}+{pv_tv_summary_cell}"
    _value_style(ws[f"B{row}"], fmt="$#,##0")
    ev_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "(-) Net Debt"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={nd_cell}"
    _value_style(ws[f"B{row}"], fmt="$#,##0")

    row += 1
    ws[f"A{row}"] = "Equity Value"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={ev_cell}-{nd_cell}"
    _value_style(ws[f"B{row}"], fmt="$#,##0")
    eq_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Shares Outstanding"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={shares_cell}"
    _value_style(ws[f"B{row}"], fmt="#,##0")

    row += 1
    ws[f"A{row}"] = "Implied Share Price"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={eq_cell}/{shares_cell}"
    _highlight_style(ws[f"B{row}"])
    implied_cell = f"B{row}"

    row += 1
    ws[f"A{row}"] = "Current Share Price"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={current_price_cell}"
    _value_style(ws[f"B{row}"], fmt="$#,##0.00")

    row += 1
    ws[f"A{row}"] = "Implied Upside / (Downside)"
    _label_style(ws[f"A{row}"])
    ws[f"B{row}"] = f"={implied_cell}/{current_price_cell}-1"
    cell = ws[f"B{row}"]
    cell.fill = PatternFill("solid", fgColor=GOLD)
    cell.font = Font(name="Calibri", size=12, bold=True, color="FFFFFF")
    cell.alignment = Alignment(horizontal="right", vertical="center")
    cell.number_format = "+0.0%;-0.0%"
    cell.border = _border()

    # --- Sensitivity Table ---
    row += 3
    ws[f"A{row}"] = "SENSITIVITY: Implied Price ~ WACC vs Terminal Growth"
    _header_style(ws[f"A{row}"])
    ws.merge_cells(f"A{row}:G{row}")

    sens_header_row = row + 1
    ws.cell(row=sens_header_row, column=1, value="WACC \\ TG").font = Font(bold=True)
    _label_style(ws.cell(row=sens_header_row, column=1))

    tg_values = [0.015, 0.020, 0.025, 0.030, 0.035]
    wacc_values = [0.07, 0.08, 0.09, 0.10, 0.11]

    for j, tg_v in enumerate(tg_values):
        c = ws.cell(row=sens_header_row, column=2 + j, value=tg_v)
        _header_style(c)
        c.number_format = "0.0%"

    # Use precomputed FCF projections from state for the sensitivity table
    base_fcfs = val.get("projected_fcfs", [])
    if not base_fcfs:
        # If we don't have projections, derive simple ones
        rev_proj = (metrics.get("total_revenue") or 1e9)
        margin_v = assumptions.get("fcf_margin", 0.12)
        g_list = [assumptions.get(f"revenue_growth_y{i}", 0.05) for i in range(1, 6)]
        base_fcfs = []
        for g in g_list:
            rev_proj *= (1 + g)
            base_fcfs.append(rev_proj * margin_v)

    shares_v = metrics.get("shares_outstanding") or 1

    for i, wv in enumerate(wacc_values):
        r = sens_header_row + 1 + i
        wc = ws.cell(row=r, column=1, value=wv)
        _label_style(wc)
        wc.number_format = "0.0%"
        wc.alignment = Alignment(horizontal="center")
        for j, tg_v in enumerate(tg_values):
            # Calculate implied price under this WACC/TG combo
            if tg_v >= wv:
                implied = "—"
            else:
                pv_fcf_sum = sum(f / ((1 + wv) ** (k + 1)) for k, f in enumerate(base_fcfs))
                tv = base_fcfs[-1] * (1 + tg_v) / (wv - tg_v)
                pv_tv = tv / ((1 + wv) ** 5)
                ev = pv_fcf_sum + pv_tv
                equity = ev - net_debt
                implied = equity / shares_v
            c = ws.cell(row=r, column=2 + j, value=implied)
            if isinstance(implied, (int, float)):
                c.number_format = "$#,##0.00"
            c.fill = PatternFill("solid", fgColor=LIGHT)
            c.alignment = Alignment(horizontal="right")
            c.font = Font(name="Calibri", size=10)
            c.border = _border()

    # ============================================================
    # Sheet 2: Assumptions & Notes
    # ============================================================
    ws2 = wb.create_sheet("Assumptions & Notes")
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 80

    ws2["A1"] = "Assumption Rationale & Notes"
    ws2["A1"].font = Font(name="Georgia", size=14, bold=True, color=NAVY)
    ws2.merge_cells("A1:B1")

    notes = [
        ("Source", "yfinance (Yahoo Finance). Forward assumptions generated by Gemini-powered AI agent."),
        ("Rationale", assumptions.get("rationale", "N/A")),
        ("Method", "5-year explicit DCF + Gordon Growth terminal value."),
        ("Recommendation", state.get("recommendation", "HOLD")),
        ("Disclaimer", "This model is for educational use only. Not investment advice."),
    ]
    for i, (label, value) in enumerate(notes, start=3):
        ws2.cell(row=i, column=1, value=label).font = Font(bold=True, color=NAVY)
        c = ws2.cell(row=i, column=2, value=value)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws2.row_dimensions[i].height = 60

    # ============================================================
    # Sheet 3: Raw Metrics
    # ============================================================
    ws3 = wb.create_sheet("Raw Metrics")
    ws3.column_dimensions["A"].width = 30
    ws3.column_dimensions["B"].width = 20

    ws3["A1"] = "Raw Company Metrics (from yfinance)"
    ws3["A1"].font = Font(name="Georgia", size=14, bold=True, color=NAVY)
    ws3.merge_cells("A1:B1")

    metric_rows = [
        ("Market Cap", metrics.get("market_cap")),
        ("Enterprise Value", profile.get("enterprise_value")),
        ("Revenue (TTM)", metrics.get("total_revenue")),
        ("EBITDA", metrics.get("ebitda")),
        ("Free Cash Flow", metrics.get("free_cash_flow")),
        ("Operating Cash Flow", metrics.get("operating_cash_flow")),
        ("Total Debt", metrics.get("total_debt")),
        ("Total Cash", metrics.get("total_cash")),
        ("Shares Outstanding", metrics.get("shares_outstanding")),
        ("P/E Ratio", metrics.get("pe_ratio")),
        ("Forward P/E", metrics.get("forward_pe")),
        ("Price / Book", metrics.get("price_to_book")),
        ("EV / EBITDA", metrics.get("ev_to_ebitda")),
        ("Profit Margin", metrics.get("profit_margin")),
        ("Operating Margin", metrics.get("operating_margin")),
        ("ROE", metrics.get("roe")),
        ("ROA", metrics.get("roa")),
        ("Revenue Growth", metrics.get("revenue_growth")),
        ("Beta", metrics.get("beta")),
        ("52W High", metrics.get("52w_high")),
        ("52W Low", metrics.get("52w_low")),
    ]
    for i, (label, value) in enumerate(metric_rows, start=3):
        ws3.cell(row=i, column=1, value=label).font = Font(bold=True)
        c = ws3.cell(row=i, column=2, value=value if value is not None else "N/A")
        if isinstance(value, (int, float)):
            if "Margin" in label or "ROE" in label or "ROA" in label or "Growth" in label:
                c.number_format = "0.00%"
            elif "Ratio" in label or "P/E" in label or "Book" in label or "Beta" in label or "EBITDA" in label:
                c.number_format = "0.00"
            else:
                c.number_format = "$#,##0"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
