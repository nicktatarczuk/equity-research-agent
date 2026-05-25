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

    context = f"""
Company: {profile.get('name')} ({profile.get('ticker')})
Sector: {profile.get('sector')} / {profile.get('industry')}
Market Cap: ${_safe_num(profile.get('market_cap'))}
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
- Free Cash Flow: ${_safe_num(metrics.get('free_cash_flow'))}

Recent News Headlines:
{chr(10).join(f"- {n['title']}" for n in news[:5]) or "No recent news."}
""".strip()

    system = (
        "You are a senior equity research analyst at a top-tier investment bank. "
        "Write clear, professional, fact-based analysis. Use the data provided. "
        "Avoid generic platitudes. Be specific and reference the numbers."
    )

    # 1. Business overview
    overview_prompt = f"""{context}

Write a concise 2-paragraph business overview. Cover:
- What the company actually does and how it makes money (revenue model)
- Its market position and scale
Avoid filler. Be specific. ~150 words.
"""
    business_overview = call_llm(system, overview_prompt, temperature=0.2)

    # 2. Investment thesis
    thesis_prompt = f"""{context}

Write the bull case — the investment thesis — in 3-5 bullet points.
Each bullet should be a specific, defensible reason to own this stock.
Reference actual numbers from the data. Avoid generic language like "strong brand."
"""
    investment_thesis = call_llm(system, thesis_prompt, temperature=0.3)

    # 3. Risks
    risks_prompt = f"""{context}

Write the bear case — key risks — in 3-5 bullet points.
Be specific to this company and industry. Reference the financial data where relevant.
Avoid generic risks like "macro conditions" unless they specifically apply.
"""
    risks = call_llm(system, risks_prompt, temperature=0.3)

    # 4. Competitive position
    comp_prompt = f"""{context}

In one paragraph (~120 words), describe this company's competitive positioning:
- Who are its main competitors?
- What is its moat (if any)?
- Where does it sit on the value chain?
Be specific and concrete.
"""
    competitive_position = call_llm(system, comp_prompt, temperature=0.3)

    log.append("[researcher] Completed 4 analytical sections")
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

    assumption_prompt = f"""
You are a sell-side equity analyst building a 5-year DCF for {profile.get('name')} ({profile.get('ticker')}).

Current financial profile:
- Sector: {profile.get('sector')}
- Latest Revenue: ${_safe_num(base_revenue)}
- Latest Free Cash Flow: ${_safe_num(fcf)}
- Recent Revenue Growth: {_safe_pct(growth)}
- Operating Margin: {_safe_pct(metrics.get('operating_margin'))}
- Beta: {beta}
- Net Debt: ${_safe_num((metrics.get('total_debt') or 0) - (metrics.get('total_cash') or 0))}

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
  "rationale": "Brief 1-sentence justification."
}}

Constraints:
- Growth rates between -0.10 and 0.40 (decimals, not percentages)
- fcf_margin between 0.02 and 0.40
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
    """Produce executive summary + BUY/HOLD/SELL recommendation."""
    log = state.get("log", []) + ["[writer] Synthesizing final recommendation"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    val = state.get("dcf_valuation") or {}

    upside = val.get("upside_pct", 0)

    # Rule-based recommendation grounded in DCF + sanity checks
    if upside > 0.15:
        rec = "BUY"
    elif upside < -0.10:
        rec = "SELL"
    else:
        rec = "HOLD"

    target = val.get("implied_share_price", 0)

    summary_prompt = f"""
You are writing the executive summary of an equity research report on {profile.get('name')} ({profile.get('ticker')}).

Key inputs to reference:
- Current price: ${_safe_num(metrics.get('current_price'), ',.2f')}
- DCF implied price target: ${target:,.2f}
- Implied upside/downside: {upside * 100:+.1f}%
- Recommendation: {rec}
- Sector: {profile.get('sector')}

Investment thesis highlights:
{state.get('investment_thesis', 'N/A')[:600]}

Key risks:
{state.get('risks', 'N/A')[:600]}

Write a tight 3-paragraph executive summary. Paragraph 1: what the company does and the recommendation
with target price. Paragraph 2: top 2-3 reasons supporting it. Paragraph 3: top 2 risks that could
derail the thesis. ~250 words total. Professional, sell-side tone.
"""
    system = "You are a sell-side analyst writing for institutional investors. Concise, specific, no fluff."
    exec_summary = call_llm(system, summary_prompt, temperature=0.3)

    log.append(f"[writer] Final recommendation: {rec} | Target: ${target:.2f}")
    return {
        "executive_summary": exec_summary,
        "recommendation": rec,
        "target_price": target,
        "log": log,
    }
