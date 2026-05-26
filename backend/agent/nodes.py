"""
LangGraph nodes. Each node is a discrete step in the agent's reasoning:
  data_collector -> researcher -> analyst -> writer

Every node takes AgentState and returns a partial dict to merge back into state.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from backend.data import fetch_company_data

from .llm import call_llm
from .state import AgentState

logger = logging.getLogger(__name__)


def _safe_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.1f}%" if abs(v) < 5 else f"{v:.1f}%"


def _safe_num(v: float | None, fmt: str = ",.0f") -> str:
    if v is None:
        return "N/A"
    try:
        return format(float(v), fmt)
    except (ValueError, TypeError):
        return "N/A"


def _fmt_money_short(v: float | None) -> str:
    """Format a dollar value compactly: $5.19T, $96.7B, $12.3M."""
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "N/A"
    abs_v = abs(v)
    if abs_v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs_v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def _strip_markdown(text: str) -> str:
    """Remove markdown emphasis markers (**bold**, *italic*) the LLM sometimes injects."""
    if not text:
        return text
    import re
    # Convert **bold** to just the text (no emphasis in plain output)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Remove stray single asterisks used for italics
    text = re.sub(r"(?<!\*)\*(?!\*)([^\n*]+?)(?<!\*)\*(?!\*)", r"\1", text)
    return text


def _split_research_sections(text: str) -> dict[str, str]:
    """
    Parse the researcher's combined output into a dict keyed by section name.
    Looks for '### SECTION NAME ###' markers and captures everything between them.
    Robust to small formatting variations from the LLM.
    """
    import re

    if not text:
        return {}

    # Match '### NAME ###' (with flexible whitespace and trailing ### optional)
    pattern = re.compile(r"#{2,}\s*([A-Z][A-Z\s]+?)\s*#{2,}", re.MULTILINE)

    sections: dict[str, str] = {}
    matches = list(pattern.finditer(text))
    if not matches:
        # No section markers found — return the whole thing as one blob so we at least
        # don't lose the analysis. The caller will see empty individual sections.
        return {"BUSINESS OVERVIEW": text.strip()}

    for i, m in enumerate(matches):
        section_name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[section_name] = text[start:end].strip()

    return sections


# ---------------------------------------------------------------------------
# Node 1: Data Collector
# ---------------------------------------------------------------------------
def data_collector_node(state: AgentState) -> dict[str, Any]:
    """Fetch all company data from yfinance."""
    ticker = state["ticker"]
    log = state.get("log", []) + [f"[data_collector] Fetching data for {ticker}"]
    try:
        data = fetch_company_data(ticker)
        log.append(f"[data_collector] Retrieved {len(data.get('income_statement', []))} years of financials")
        return {"company_data": data, "log": log}
    except Exception as e:
        logger.exception("Data collection failed")
        errors = state.get("errors", []) + [f"Data collection: {e}"]
        return {"errors": errors, "log": log}


# ---------------------------------------------------------------------------
# Node 2: Researcher — qualitative analysis
# ---------------------------------------------------------------------------
def researcher_node(state: AgentState) -> dict[str, Any]:
    """Use Gemini to produce business overview, thesis, risks, competitive position."""
    log = state.get("log", []) + ["[researcher] Generating qualitative analysis"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    news = data.get("news", [])
    momentum = data.get("momentum") or {}
    anchors = data.get("historical_anchors") or {}

    # Format momentum compactly
    def _fmt_mom(p):
        return f"{p * 100:+.1f}%" if p is not None else "N/A"

    momentum_text = (
        f"1mo: {_fmt_mom(momentum.get('price_1mo_pct'))} | "
        f"3mo: {_fmt_mom(momentum.get('price_3mo_pct'))} | "
        f"YTD: {_fmt_mom(momentum.get('price_ytd_pct'))} | "
        f"1yr: {_fmt_mom(momentum.get('price_1yr_pct'))}"
    )

    context = f"""
Company: {profile.get('name')} ({profile.get('ticker')})
Sector: {profile.get('sector')} / {profile.get('industry')}
Market Cap: {_fmt_money_short(profile.get('market_cap'))}
Employees: {_safe_num(profile.get('employees'))}

Business Summary:
{profile.get('summary', 'N/A')[:2000]}

Key Metrics:
- Current Price: ${_safe_num(metrics.get('current_price'), ',.2f')}
- P/E: {_safe_num(metrics.get('pe_ratio'), ',.2f')} | Forward P/E: {_safe_num(metrics.get('forward_pe'), ',.2f')}
- Revenue Growth (YoY): {_safe_pct(metrics.get('revenue_growth'))}
- Profit Margin: {_safe_pct(metrics.get('profit_margin'))}
- Operating Margin: {_safe_pct(metrics.get('operating_margin'))}
- ROE: {_safe_pct(metrics.get('roe'))}
- Debt-to-Equity: {_safe_num(metrics.get('debt_to_equity'), ',.2f')}
- Total Revenue (TTM): {_fmt_money_short(metrics.get('total_revenue'))}
- Free Cash Flow: {_fmt_money_short(metrics.get('free_cash_flow'))}
- EBITDA: {_fmt_money_short(metrics.get('ebitda'))}

Historical context:
- 3-year avg FCF margin: {_safe_pct(anchors.get('avg_fcf_margin_3y'))}
- 3-year avg revenue growth: {_safe_pct(anchors.get('avg_revenue_growth_3y'))}

Price momentum (vs current): {momentum_text}

Recent News Headlines:
{chr(10).join(f"- {n['title']}" for n in news[:5]) or "No recent news."}
""".strip()

    system = (
        "You are a senior equity research analyst at a top-tier investment bank "
        "(think Goldman Sachs / Morgan Stanley level). Your voice is sharp, specific, opinionated. "
        "Reference real numbers. Take positions. The portfolio manager reading this is paying for "
        "your judgment, not a textbook restatement."
        "\n\nFORMATTING RULES (critical):\n"
        "- DO NOT use markdown emphasis (no **bold**, no *italics*). Write in plain prose.\n"
        "- Format large dollar amounts compactly: $5.19T, $96.7B, $12.3M — never as raw digits.\n"
        "- Format percentages as 65.5% or 63.0%, not 0.655.\n"
        "- For bullet points, just use '- ' at the start of each line."
        "\n\nFORBIDDEN VOICE (using these makes you sound like AI):\n"
        "- 'robust', 'exceptional', 'significant', 'substantial', 'consistent'\n"
        "- 'strong fundamentals', 'leverages', 'well-positioned', 'comprehensive', 'best-in-class'\n"
        "- 'demonstrates strong', 'enables continued', 'positions itself'\n"
        "Write around these. Use specific verbs and concrete claims instead."
    )

    # Single combined call — returns all 4 sections at once.
    # Uses explicit section delimiters so we can split the response cleanly.
    combined_prompt = f"""{context}

Produce a complete qualitative analysis with FOUR sections.
Use these EXACT section headers verbatim, each on its own line, with the content immediately after:

### BUSINESS OVERVIEW ###
Two paragraphs (~150 words total). Cover:
- What the company does and how it actually makes money (revenue model, segments)
- Its market position, scale, and any distinctive operating characteristics
Reference real numbers from the data.

### INVESTMENT THESIS ###
3-5 bullet points (the bull case). Each bullet must be a specific, defensible reason to own this stock.
Format each as "- " followed by the point. Reference actual numbers where possible.
NO generic language like "strong brand" — be specific about WHY.

### KEY RISKS ###
3-5 bullet points (the bear case). Each must be specific to this company or its industry,
not generic macro concerns. Reference financial data where relevant.
Format each as "- " followed by the risk.

### COMPETITIVE POSITION ###
One paragraph (~120 words). Cover:
- Main competitors (name them)
- The moat (if any) and what specifically protects it
- Where the company sits on the value chain

Do not add any text before the first section header or after the final section's content.
"""

    raw_research = call_llm(system, combined_prompt, temperature=0.3)

    # Parse the combined response by splitting on the section markers,
    # then strip any markdown emphasis the LLM may still include.
    sections = _split_research_sections(raw_research)
    business_overview = _strip_markdown(sections.get("BUSINESS OVERVIEW", ""))
    investment_thesis = _strip_markdown(sections.get("INVESTMENT THESIS", ""))
    risks = _strip_markdown(sections.get("KEY RISKS", ""))
    competitive_position = _strip_markdown(sections.get("COMPETITIVE POSITION", ""))

    log.append("[researcher] Completed 4 analytical sections in 1 combined LLM call")
    return {
        "business_overview": business_overview,
        "investment_thesis": investment_thesis,
        "risks": risks,
        "competitive_position": competitive_position,
        "log": log,
    }


# ---------------------------------------------------------------------------
# Node 3: Analyst — DCF model
# ---------------------------------------------------------------------------
def analyst_node(state: AgentState) -> dict[str, Any]:
    """
    Build DCF assumptions using Gemini's judgment + real financials,
    then compute the valuation deterministically in Python.
    """
    log = state.get("log", []) + ["[analyst] Building DCF model"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})

    # --- Step A: ask the LLM for assumptions (judgment), constrained to JSON ---
    base_revenue = metrics.get("total_revenue") or 0
    fcf = metrics.get("free_cash_flow") or 0
    growth = metrics.get("revenue_growth") or 0.05
    beta = metrics.get("beta") or 1.0

    # Historical anchors fight the model's tendency to randomly under-margin mature businesses
    anchors = data.get("historical_anchors") or {}
    hist_fcf_margin = anchors.get("avg_fcf_margin_3y")
    hist_rev_growth = anchors.get("avg_revenue_growth_3y")

    # Current FCF margin from latest year (if computable)
    current_fcf_margin = (fcf / base_revenue) if (fcf and base_revenue) else None

    anchors_text = []
    if current_fcf_margin is not None:
        anchors_text.append(f"- Current FCF margin (TTM): {current_fcf_margin * 100:.1f}%")
    if hist_fcf_margin is not None:
        anchors_text.append(f"- Avg FCF margin (last 3 years): {hist_fcf_margin * 100:.1f}%")
    if hist_rev_growth is not None:
        anchors_text.append(f"- Avg revenue growth (last 3 years): {hist_rev_growth * 100:.1f}%")
    anchors_block = "\n".join(anchors_text) or "- (No historical anchor data available)"

    assumption_prompt = f"""
You are a sell-side equity analyst building a 5-year DCF for {profile.get('name')} ({profile.get('ticker')}).

Current financial profile:
- Sector: {profile.get('sector')}
- Latest Revenue: ${_safe_num(base_revenue)}
- Latest Free Cash Flow: ${_safe_num(fcf)}
- Recent Revenue Growth (YoY): {_safe_pct(growth)}
- Operating Margin: {_safe_pct(metrics.get('operating_margin'))}
- Profit Margin: {_safe_pct(metrics.get('profit_margin'))}
- Beta: {beta}
- Net Debt: ${_safe_num((metrics.get('total_debt') or 0) - (metrics.get('total_cash') or 0))}

HISTORICAL ANCHORS (use these — don't drift far without good reason):
{anchors_block}

CRITICAL: Your fcf_margin assumption should be CLOSE to the company's historical FCF margin.
For mature cash machines like Apple, NVDA, MSFT this is often 20-35%. Don't default to 12-18%
unless the company actually runs at those levels. If historical margins are 25%+, your assumption
should reflect that.

Provide reasonable forward-looking DCF assumptions. Respond ONLY with valid JSON, no markdown,
matching exactly this schema:

{{
  "revenue_growth_y1": 0.08,
  "revenue_growth_y2": 0.07,
  "revenue_growth_y3": 0.06,
  "revenue_growth_y4": 0.05,
  "revenue_growth_y5": 0.04,
  "fcf_margin": 0.15,
  "terminal_growth": 0.025,
  "wacc": 0.09,
  "rationale": "1-sentence justification grounded in the actual numbers."
}}

Constraints:
- Growth rates between -0.10 and 0.40 (decimals, not percentages)
- fcf_margin between 0.02 and 0.45 — should be within ±5pp of the historical FCF margin above
- terminal_growth between 0.015 and 0.035 (must be < WACC)
- WACC between 0.06 and 0.14, scaled to beta and sector risk
"""
    system = "You are a financial analyst. Output only valid JSON, no explanation, no markdown fences."
    raw = call_llm(system, assumption_prompt, temperature=0.2)

    # Robust JSON extraction (Gemini sometimes still wraps in ```json)
    assumptions = _parse_json_safe(raw) or _fallback_assumptions(growth, beta)

    # --- Step B: deterministic DCF calculation ---
    valuation = _compute_dcf(
        base_revenue=base_revenue or 1e9,  # avoid div-by-zero on weird tickers
        net_debt=(metrics.get("total_debt") or 0) - (metrics.get("total_cash") or 0),
        shares=metrics.get("shares_outstanding") or 1,
        current_price=metrics.get("current_price") or 0,
        assumptions=assumptions,
    )

    log.append(f"[analyst] DCF complete. Implied price: ${valuation['implied_share_price']:.2f}")
    return {
        "dcf_assumptions": assumptions,
        "dcf_valuation": valuation,
        "log": log,
    }


def _parse_json_safe(text: str) -> dict | None:
    """Extract JSON even if the model wrapped it in markdown fences."""
    text = text.strip()
    if "```" in text:
        # Pull out the largest JSON-looking block
        parts = text.split("```")
        for p in parts:
            p = p.replace("json", "", 1).strip()
            if p.startswith("{"):
                text = p
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _fallback_assumptions(growth: float, beta: float) -> dict[str, float]:
    """Reasonable defaults if the LLM JSON parse fails."""
    g = max(min(growth or 0.05, 0.20), 0.0)
    return {
        "revenue_growth_y1": g,
        "revenue_growth_y2": g * 0.9,
        "revenue_growth_y3": g * 0.8,
        "revenue_growth_y4": g * 0.7,
        "revenue_growth_y5": g * 0.6,
        "fcf_margin": 0.12,
        "terminal_growth": 0.025,
        "wacc": min(max(0.07 + (beta - 1) * 0.02, 0.07), 0.13),
        "rationale": "Default assumptions used (LLM output not parseable).",
    }


def _compute_dcf(
    base_revenue: float,
    net_debt: float,
    shares: float,
    current_price: float,
    assumptions: dict,
) -> dict[str, Any]:
    """Five-year DCF + Gordon growth terminal value."""
    growths = [assumptions[f"revenue_growth_y{i}"] for i in range(1, 6)]
    margin = assumptions["fcf_margin"]
    wacc = assumptions["wacc"]
    tg = assumptions["terminal_growth"]

    # Project revenue and FCF for 5 years
    revenues, fcfs, pv_fcfs = [], [], []
    rev = base_revenue
    for i, g in enumerate(growths, start=1):
        rev = rev * (1 + g)
        fcf = rev * margin
        pv = fcf / ((1 + wacc) ** i)
        revenues.append(rev)
        fcfs.append(fcf)
        pv_fcfs.append(pv)

    # Terminal value (Gordon growth)
    terminal_fcf = fcfs[-1] * (1 + tg)
    terminal_value = terminal_fcf / (wacc - tg)
    pv_terminal = terminal_value / ((1 + wacc) ** 5)

    enterprise_value = sum(pv_fcfs) + pv_terminal
    equity_value = enterprise_value - net_debt
    implied_price = equity_value / shares if shares else 0
    upside = (implied_price / current_price - 1) if current_price else 0

    return {
        "projected_revenues": revenues,
        "projected_fcfs": fcfs,
        "pv_fcfs": pv_fcfs,
        "terminal_value": terminal_value,
        "pv_terminal": pv_terminal,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "implied_share_price": implied_price,
        "current_share_price": current_price,
        "upside_pct": upside,
    }


# ---------------------------------------------------------------------------
# Node 4: Writer — synthesizes into final recommendation
# ---------------------------------------------------------------------------
def writer_node(state: AgentState) -> dict[str, Any]:
    """Produce executive summary, recommendation, confidence score, and 'what would change my mind'."""
    log = state.get("log", []) + ["[writer] Synthesizing final recommendation"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    val = state.get("dcf_valuation") or {}
    momentum = data.get("momentum") or {}

    upside = val.get("upside_pct", 0)

    # Rule-based recommendation grounded in DCF + sanity checks
    if upside > 0.15:
        rec = "BUY"
    elif upside < -0.10:
        rec = "SELL"
    else:
        rec = "HOLD"

    target = val.get("implied_share_price", 0)

    # Compute a quantitative confidence score (1-10)
    # Inputs: valuation gap, data completeness, beta, news availability
    base_conf = 6  # neutral starting point
    # Larger valuation gaps reduce confidence (more uncertainty)
    abs_upside = abs(upside)
    if abs_upside > 0.6:
        base_conf -= 2  # huge gap = high uncertainty in the DCF
    elif abs_upside > 0.3:
        base_conf -= 1
    elif abs_upside < 0.1:
        base_conf += 1
    # High beta = more volatility = lower confidence
    beta = metrics.get("beta") or 1.0
    if beta and beta > 1.8:
        base_conf -= 1
    elif beta and beta < 0.9:
        base_conf += 1
    # Data completeness
    if metrics.get("pe_ratio") and metrics.get("roe") and metrics.get("free_cash_flow"):
        base_conf += 1
    # Clamp 1-10
    confidence_score = max(1, min(10, base_conf))

    # Build momentum context for the prompt
    def _fmt_mom(p):
        if p is None:
            return "N/A"
        return f"{p * 100:+.1f}%"

    momentum_text = (
        f"1mo: {_fmt_mom(momentum.get('price_1mo_pct'))} | "
        f"3mo: {_fmt_mom(momentum.get('price_3mo_pct'))} | "
        f"YTD: {_fmt_mom(momentum.get('price_ytd_pct'))} | "
        f"1yr: {_fmt_mom(momentum.get('price_1yr_pct'))}"
    )

    summary_prompt = f"""
You are writing the analyst's CALL on {profile.get('name')} ({profile.get('ticker')}) — the part that goes
on the cover page of the report. This is YOUR view, not a textbook summary. Be pointed, direct, and specific.

Key inputs:
- Sector: {profile.get('sector')}
- Current price: ${_safe_num(metrics.get('current_price'), ',.2f')}
- DCF implied target: ${target:,.2f}
- Implied upside/downside: {upside * 100:+.1f}%
- Recommendation (derived from DCF): {rec}
- Price momentum: {momentum_text}
- Beta: {beta}

Bull case bullets (from researcher):
{state.get('investment_thesis', 'N/A')[:600]}

Bear case bullets (from researcher):
{state.get('risks', 'N/A')[:600]}

Write THREE sections using these EXACT delimiters:

### EXECUTIVE SUMMARY ###
Three short paragraphs (~250 words total):

Paragraph 1 (the call): Open with the recommendation framed as YOUR view, not a textbook restatement.
Example openings to emulate:
- "We rate AAPL a SELL at $311 — the multiple, not the business, is the problem."
- "NVDA is a BUY at $214, though the easy money has already been made."
- "META is a HOLD here. The bull case is too consensus, the bear case is too lazy."
Then 2-3 sentences explaining the core thesis in your own framing. Reference the ACTUAL price and target.

Paragraph 2 (why we're right): The 2-3 strongest specific arguments for our call. Reference real numbers.
Use verbs that take a position ("we argue", "the market is missing", "consensus underweights").
NOT generic phrases like "robust profitability" or "exceptional fundamentals".

Paragraph 3 (what could go wrong): The 1-2 risks that genuinely threaten our thesis. Be honest about
where we could be wrong — this builds credibility.

### WHAT WOULD CHANGE OUR MIND ###
ONE sentence. Specific and falsifiable. Example:
"We would flip to BUY if FCF margin re-expands above 28% for two consecutive quarters."
Or: "A pullback below $180 with services growth holding above 12% would change the call to BUY."

### CONFIDENCE RATIONALE ###
ONE sentence explaining what drives our conviction level (or lack of it). Example:
"High confidence — large valuation gap, stable cash generation, clean balance sheet."
Or: "Moderate confidence — strong fundamentals but high beta and a one-product concentration risk."

CRITICAL VOICE RULES:
- Forbidden words/phrases (using these makes you sound robotic): "robust", "exceptional", "significant",
  "substantial", "consistent", "strong fundamentals", "leverages", "well-positioned", "comprehensive",
  "best-in-class". Write around them.
- Take a position. "The market is mispricing X" beats "X may face challenges".
- Be specific. "Services revenue grew 12.4%" beats "services showed growth".
- DO NOT use markdown emphasis (no **bold**, no *italics*).
- Format dollar amounts compactly: $5.19T, $96.7B, $416B.
"""
    system = (
        "You are a senior buy-side analyst writing for a portfolio manager who is paying you to have an opinion. "
        "Sharp, specific, opinionated — but grounded in the numbers. No textbook prose."
    )

    raw = call_llm(system, summary_prompt, temperature=0.4)
    sections = _split_research_sections(raw)
    exec_summary = _strip_markdown(sections.get("EXECUTIVE SUMMARY", "")).strip()
    what_would_change_mind = _strip_markdown(sections.get("WHAT WOULD CHANGE OUR MIND", "")).strip()
    confidence_rationale = _strip_markdown(sections.get("CONFIDENCE RATIONALE", "")).strip()

    # Fallback: if parsing failed, use the whole raw text as the summary
    if not exec_summary:
        exec_summary = _strip_markdown(raw)

    log.append(f"[writer] Final: {rec} | Target ${target:.2f} | Confidence {confidence_score}/10")
    return {
        "executive_summary": exec_summary,
        "recommendation": rec,
        "target_price": target,
        "confidence_score": confidence_score,
        "confidence_rationale": confidence_rationale,
        "what_would_change_mind": what_would_change_mind,
        "log": log,
    }
