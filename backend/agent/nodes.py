"""
14-agent equity research workflow.

Architecture:
    data_collector
        |
        v
    classifier --- decides framework
        |
        v
   [PARALLEL RESEARCH - 5 agents]
    fundamentals_analyst | catalyst_scout | peer_analyst | technical_analyst | macro_strategist
        |
        v
   [VALUATION TRIANGULATION - 3 methods]
    dcf_modeler | comps_modeler | scenarios_modeler
        |
        v
    reality_check --- which models to trust
        |
        v
   [DEBATE]
    bull_advocate | bear_advocate
        |
        v
    chief_strategist (synthesis + final call)
        |
        v
    quality_reviewer (cliche removal, sanity check)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.data import fetch_company_data, fetch_peer_snapshot

from .llm import call_llm
from .state import AgentState

logger = logging.getLogger(__name__)


# ============================================================================
# SHARED HELPERS
# ============================================================================

def _safe_pct(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "N/A"
    try:
        v = float(v)
        return f"{v * 100:.{decimals}f}%" if abs(v) < 5 else f"{v:.{decimals}f}%"
    except (ValueError, TypeError):
        return "N/A"


def _safe_num(v: float | None, fmt: str = ",.0f") -> str:
    if v is None:
        return "N/A"
    try:
        return format(float(v), fmt)
    except (ValueError, TypeError):
        return "N/A"


def _fmt_money_short(v: float | None) -> str:
    """$5.19T / $96.7B / $12.3M format."""
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
    """Remove markdown emphasis the LLM may inject."""
    if not text:
        return text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)([^\n*]+?)(?<!\*)\*(?!\*)", r"\1", text)
    return text


def _split_sections(text: str) -> dict[str, str]:
    """Parse text with ### SECTION ### markers into a dict."""
    if not text:
        return {}
    pattern = re.compile(r"#{2,}\s*([A-Z][A-Z0-9\s\-_/]+?)\s*#{2,}", re.MULTILINE)
    sections: dict[str, str] = {}
    matches = list(pattern.finditer(text))
    if not matches:
        return {"_ALL": text.strip()}
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[name] = _strip_markdown(text[start:end].strip())
    return sections


def _parse_json_safe(text: str) -> dict | None:
    """Robust JSON extraction from LLM output (handles markdown fences)."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.replace("json", "", 1).strip()
            if p.startswith("{"):
                text = p
                break
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


# Voice rules used across multiple prompts
VOICE_RULES = """
VOICE — write like a real analyst, not an AI:
- DO NOT use markdown emphasis (no **bold**, no *italics*).
- Format money compactly: $5.19T, $96.7B, $12.3M.
- Replace abstract praise with specific numbers.
- Forbidden words: "robust", "exceptional", "significant", "substantial", "consistent",
  "tightly integrated", "well-positioned", "comprehensive", "best-in-class", "leverages",
  "industry-leading", "strong fundamentals", "screams", "brutal", "painful disconnect",
  "sci-fi future", "reality bites" (no theatrical phrases either).
- Pattern: "Profit margins held at 27% even as growth slowed to 6%" — not "Robust profitability".
"""


# ============================================================================
# NODE 1: data_collector
# ============================================================================

def data_collector_node(state: AgentState) -> dict[str, Any]:
    """Fetch all company data from FMP."""
    ticker = state["ticker"]
    log = [f"[1/14 data_collector] Fetching {ticker}"]
    try:
        data = fetch_company_data(ticker)
        n_periods = len(data.get("income_statement", []))
        n_news = len(data.get("news", []))
        n_peers = len(data.get("peer_tickers", []))
        log.append(f"[1/14 data_collector] {n_periods}y financials, {n_news} news items, {n_peers} peers")
        return {"company_data": data, "log": log}
    except Exception as e:
        logger.exception("Data collection failed")
        errors = [f"Data collection: {e}"]
        return {"errors": errors, "log": log}


# ============================================================================
# NODE 2: classifier — picks the right valuation framework
# ============================================================================

def classifier_node(state: AgentState) -> dict[str, Any]:
    """Classify the stock and pick a valuation framework."""
    log = ["[2/14 classifier] Classifying stock type"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    anchors = data.get("historical_anchors", {}) or {}

    context = f"""
Company: {profile.get('name')} ({profile.get('ticker')})
Sector: {profile.get('sector')} / {profile.get('industry')}

Financial fingerprint:
- Market Cap: {_fmt_money_short(profile.get('market_cap'))}
- Revenue: {_fmt_money_short(metrics.get('total_revenue'))}
- P/E: {_safe_num(metrics.get('pe_ratio'), ',.1f')}
- Revenue growth (YoY): {_safe_pct(metrics.get('revenue_growth'))}
- Avg 3y revenue growth: {_safe_pct(anchors.get('avg_revenue_growth_3y'))}
- Profit margin: {_safe_pct(metrics.get('profit_margin'))}
- Operating margin: {_safe_pct(metrics.get('operating_margin'))}
- Avg 3y FCF margin: {_safe_pct(anchors.get('avg_fcf_margin_3y'))}
- ROE: {_safe_pct(metrics.get('roe'))}
- Beta: {metrics.get('beta')}
""".strip()

    prompt = f"""
{context}

Classify this stock into ONE category that determines how to value it:

- VALUE: Mature, profitable, low growth. P/E reasonable, stable margins. DCF works well. Examples: KO, JNJ, VZ.
- GROWTH: Rapid revenue growth, margin expansion path clear. DCF + scenarios. Examples: NVDA, CRWD.
- OPTIONALITY: Story stock. Current financials don't justify price. Value depends on uncertain future bets. DCF gives garbage; use scenarios + peer comps. Examples: TSLA, PLTR (early), most pre-revenue biotech.
- CYCLICAL: Earnings swing with macro. Mid-cycle multiples matter. Examples: F, X, CAT.
- DISTRESSED: Negative or barely-positive earnings, balance sheet stress. Asset-based or restructuring lens.
- BALANCED: Strong cash generation + growth, neither pure value nor pure growth. Examples: AAPL, MSFT, V.

Return JSON ONLY, no markdown, this exact schema:
{{
  "stock_type": "VALUE|GROWTH|OPTIONALITY|CYCLICAL|DISTRESSED|BALANCED",
  "rationale": "One sentence explaining why this category.",
  "valuation_framework": "DCF-led|Multiples-led|Scenarios-led|Asset-based"
}}

Guidance on framework selection:
- VALUE / BALANCED: DCF-led (works because cash flows are predictable)
- GROWTH: DCF-led but heavily reliant on assumptions; pair with comps
- OPTIONALITY: Scenarios-led (DCF will give nonsense on current FCF)
- CYCLICAL: Multiples-led (mid-cycle P/E vs current)
- DISTRESSED: Asset-based (book value, liquidation)
"""
    system = "You are a senior portfolio manager who classifies stocks for analytical framework purposes. Output JSON only."
    raw = call_llm(system, prompt, temperature=0.1)
    parsed = _parse_json_safe(raw) or {}

    stock_type = parsed.get("stock_type", "BALANCED").upper()
    if stock_type not in ("VALUE", "GROWTH", "OPTIONALITY", "CYCLICAL", "DISTRESSED", "BALANCED"):
        stock_type = "BALANCED"
    rationale = parsed.get("rationale", "")
    framework = parsed.get("valuation_framework", "DCF-led")

    log.append(f"[2/14 classifier] {stock_type} — {framework}")
    return {
        "stock_type": stock_type,
        "stock_type_rationale": _strip_markdown(rationale),
        "valuation_framework": framework,
        "log": log,
    }


# ============================================================================
# NODE 3: fundamentals_analyst — business model, moat, margin trajectory
# ============================================================================

def fundamentals_analyst_node(state: AgentState) -> dict[str, Any]:
    """Deep dive on business model and unit economics."""
    log = ["[3/14 fundamentals] Analyzing business model"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    anchors = data.get("historical_anchors", {}) or {}
    income = data.get("income_statement", [])
    stock_type = state.get("stock_type", "BALANCED")

    # Build a margin trajectory string if we have data
    margin_trajectory = ""
    if len(income) >= 2:
        latest = income[0]
        prior = income[1]
        if latest.get("Revenue") and prior.get("Revenue"):
            try:
                latest_op_margin = (latest.get("Operating Income") or 0) / latest["Revenue"]
                prior_op_margin = (prior.get("Operating Income") or 0) / prior["Revenue"]
                direction = "expanding" if latest_op_margin > prior_op_margin else "compressing"
                margin_trajectory = (
                    f"Operating margin {direction}: "
                    f"{prior_op_margin * 100:.1f}% → {latest_op_margin * 100:.1f}%"
                )
            except (TypeError, ZeroDivisionError):
                pass

    context = f"""
Company: {profile.get('name')} ({profile.get('ticker')}) | {profile.get('sector')}
Stock type (per classifier): {stock_type}

Business: {(profile.get('summary') or 'N/A')[:1500]}

Numbers:
- Revenue: {_fmt_money_short(metrics.get('total_revenue'))} ({_safe_pct(metrics.get('revenue_growth'))} YoY)
- 3y avg revenue growth: {_safe_pct(anchors.get('avg_revenue_growth_3y'))}
- Operating margin: {_safe_pct(metrics.get('operating_margin'))}
- Profit margin: {_safe_pct(metrics.get('profit_margin'))}
- FCF: {_fmt_money_short(metrics.get('free_cash_flow'))} (3y avg margin: {_safe_pct(anchors.get('avg_fcf_margin_3y'))})
- ROE: {_safe_pct(metrics.get('roe'))} | ROA: {_safe_pct(metrics.get('roa'))}
- {margin_trajectory or 'Margin trajectory unclear'}
""".strip()

    prompt = f"""
{context}

Write three short sections about the BUSINESS, not the stock:

### BUSINESS MODEL ###
2 paragraphs (~150 words). What it sells, who pays, how revenue compounds.
Be specific about segment mix, geographic exposure, customer concentration if relevant.

### MOAT ASSESSMENT ###
1 paragraph (~100 words). Does this company have a real competitive advantage?
What specifically protects it? How durable is it? If there's no moat, say so.
Avoid "tightly integrated ecosystem" — instead: "Switching costs from iCloud + iMessage keep iPhone retention at 92% globally."

### MARGIN & RETURNS TRAJECTORY ###
1 paragraph (~80 words). Are margins expanding, stable, or compressing? Why?
What does the trend imply about the next 2-3 years?

{VOICE_RULES}
"""
    system = "You're a fundamentals analyst. Specific, pointed, numeric. No hedge words."
    raw = call_llm(system, prompt, temperature=0.3)
    sections = _split_sections(raw)

    fundamentals = {
        "business_model": sections.get("BUSINESS MODEL", ""),
        "moat": sections.get("MOAT ASSESSMENT", ""),
        "margin_trajectory": sections.get("MARGIN & RETURNS TRAJECTORY", ""),
    }
    log.append("[3/14 fundamentals] Business model assessed")
    return {"fundamentals": fundamentals, "log": log}


# ============================================================================
# NODE 4: catalyst_scout — near-term catalysts from news + earnings calendar
# ============================================================================

def catalyst_scout_node(state: AgentState) -> dict[str, Any]:
    """Identify real catalysts from news + earnings dates."""
    log = ["[4/14 catalyst_scout] Scanning for catalysts"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    news = data.get("news", []) or []
    upcoming = data.get("upcoming_earnings", []) or []

    # If no news, return empty
    if not news and not upcoming:
        log.append("[4/14 catalyst_scout] No news or earnings data available")
        return {"catalysts": [], "log": log}

    # Build context
    headlines = "\n".join(
        f"{i+1}. ({n.get('date', 'N/A')}) {n['title']}"
        for i, n in enumerate(news[:8])
        if n.get("title")
    ) or "(none)"

    earnings_dates = "\n".join(
        f"- {e.get('date', 'N/A')} (estimated)"
        for e in upcoming[:2]
    ) or "(no upcoming earnings date available)"

    prompt = f"""
Company: {profile.get('name')} ({profile.get('ticker')})

Recent news:
{headlines}

Upcoming earnings:
{earnings_dates}

For each REAL catalyst (events that could move the stock — not filler headlines, not "analyst raises target"),
return one line in this exact format:
HEADLINE | impact | one-sentence-interpretation

Where impact = POSITIVE | NEGATIVE | NEUTRAL | WATCH

Rules:
- Maximum 5 catalysts. If only 2 of these matter, return 2.
- If NONE qualify, return exactly: NONE
- Earnings dates ARE catalysts ("Q3 earnings approx Oct 30 | WATCH | First read on tariff impact on margins").
- Make interpretations specific. "Could lift Services revenue 2-3%" not "good for the company".
- No markdown, no preamble.
"""
    system = "You filter signal from noise. Pointed, terse."

    try:
        raw = call_llm(system, prompt, temperature=0.3)
    except Exception as e:
        log.append(f"[4/14 catalyst_scout] Failed: {e}")
        return {"catalysts": [], "log": log}

    catalysts = []
    if "NONE" not in raw.upper().split("\n")[0]:
        for line in raw.strip().split("\n"):
            line = _strip_markdown(line.strip())
            if not line or "HEADLINE | IMPACT" in line.upper():
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                headline = parts[0].strip().lstrip("0123456789.-) ")
                impact = parts[1].strip().upper()
                interp = "|".join(parts[2:]).strip()
                if impact not in ("POSITIVE", "NEGATIVE", "NEUTRAL", "WATCH"):
                    impact = "WATCH"
                if headline and interp:
                    catalysts.append({
                        "headline": headline,
                        "impact": impact,
                        "interpretation": interp,
                    })
            if len(catalysts) >= 5:
                break

    log.append(f"[4/14 catalyst_scout] {len(catalysts)} catalysts identified")
    return {"catalysts": catalysts, "log": log}


# ============================================================================
# NODE 5: peer_analyst — comp table + interpretation
# ============================================================================

def peer_analyst_node(state: AgentState) -> dict[str, Any]:
    """Build a comparable-companies table and interpret the multiples."""
    log = ["[5/14 peer_analyst] Building comp table"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    peer_tickers = data.get("peer_tickers", []) or []

    if not peer_tickers:
        log.append("[5/14 peer_analyst] No peers available")
        return {"peer_analysis": {"peers": [], "interpretation": "Peer data not available."}, "log": log}

    # Fetch lightweight peer snapshots
    try:
        peers = fetch_peer_snapshot(peer_tickers)
    except Exception as e:
        log.append(f"[5/14 peer_analyst] Peer fetch failed: {e}")
        peers = []

    if not peers:
        return {"peer_analysis": {"peers": [], "interpretation": "Peer data not available."}, "log": log}

    # Add our subject company at top of table
    subject_row = {
        "ticker": profile.get("ticker"),
        "name": profile.get("name"),
        "market_cap": profile.get("market_cap"),
        "price": metrics.get("current_price"),
        "pe": metrics.get("pe_ratio"),
        "ev_ebitda": metrics.get("ev_to_ebitda"),
        "ev_sales": metrics.get("ev_to_revenue"),
        "pb": metrics.get("price_to_book"),
        "is_subject": True,
    }
    all_rows = [subject_row] + [{**p, "is_subject": False} for p in peers]

    # Compute peer medians (excluding subject)
    def _median(values):
        clean = sorted([v for v in values if v is not None])
        if not clean:
            return None
        n = len(clean)
        return clean[n // 2] if n % 2 else (clean[n // 2 - 1] + clean[n // 2]) / 2

    peer_medians = {
        "pe": _median([p["pe"] for p in peers]),
        "ev_ebitda": _median([p["ev_ebitda"] for p in peers]),
        "ev_sales": _median([p["ev_sales"] for p in peers]),
        "pb": _median([p["pb"] for p in peers]),
    }

    # Ask LLM to interpret
    rows_text = "\n".join(
        f"{r['ticker']} ({r['name'][:30]}): mkt cap {_fmt_money_short(r['market_cap'])} | "
        f"P/E {_safe_num(r['pe'], ',.1f')} | EV/EBITDA {_safe_num(r['ev_ebitda'], ',.1f')} | "
        f"EV/Sales {_safe_num(r['ev_sales'], ',.1f')} | P/B {_safe_num(r['pb'], ',.1f')}"
        for r in all_rows
    )

    prompt = f"""
Subject: {profile.get('ticker')} ({profile.get('name')})

Comparable companies (subject is first row):
{rows_text}

Peer medians: P/E {_safe_num(peer_medians['pe'], ',.1f')} | EV/EBITDA {_safe_num(peer_medians['ev_ebitda'], ',.1f')} | EV/Sales {_safe_num(peer_medians['ev_sales'], ',.1f')}

Write ONE paragraph (~120 words):
- Does the subject trade at a premium, discount, or in-line with peers?
- On which specific multiple is the gap biggest?
- Is the premium/discount justified by fundamentals (better margins, growth, returns)?
- What multiple does YOUR analysis suggest is fair?

{VOICE_RULES}
"""
    system = "You're a peer-comps specialist. Reference specific multiples and gaps."
    try:
        interpretation = _strip_markdown(call_llm(system, prompt, temperature=0.3))
    except Exception as e:
        log.append(f"[5/14 peer_analyst] LLM call failed: {e}")
        interpretation = "Peer interpretation unavailable."

    log.append(f"[5/14 peer_analyst] {len(peers)} peers analyzed")
    return {
        "peer_analysis": {
            "rows": all_rows,
            "medians": peer_medians,
            "interpretation": interpretation,
        },
        "log": log,
    }


# ============================================================================
# NODE 6: technical_analyst — momentum, price action, volume context
# ============================================================================

def technical_analyst_node(state: AgentState) -> dict[str, Any]:
    """Read the tape — momentum, vs 52w range, volatility context."""
    log = ["[6/14 technical_analyst] Reading the tape"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    momentum = data.get("momentum", {}) or {}

    current = metrics.get("current_price") or 0
    high_52w = metrics.get("52w_high")
    low_52w = metrics.get("52w_low")
    pct_from_high = ((current - high_52w) / high_52w * 100) if high_52w and current else None
    pct_from_low = ((current - low_52w) / low_52w * 100) if low_52w and current else None

    def _fmt_mom(p):
        return f"{p * 100:+.1f}%" if p is not None else "N/A"

    context = f"""
Ticker: {profile.get('ticker')}
Price: ${current:,.2f} | 52w range: ${low_52w or 'N/A'} - ${high_52w or 'N/A'}
{f'  → {pct_from_high:+.1f}% from 52w high' if pct_from_high is not None else ''}
{f'  → {pct_from_low:+.1f}% from 52w low' if pct_from_low is not None else ''}

Returns:
- 1M: {_fmt_mom(momentum.get('price_1mo_pct'))}
- 3M: {_fmt_mom(momentum.get('price_3mo_pct'))}
- YTD: {_fmt_mom(momentum.get('price_ytd_pct'))}
- 1Y: {_fmt_mom(momentum.get('price_1yr_pct'))}

Beta: {metrics.get('beta')}
""".strip()

    prompt = f"""
{context}

Write ONE paragraph (~120 words) reading this tape:
- What does the recent price action tell us about market sentiment?
- Is the stock in an uptrend, downtrend, or chopping?
- Where is it relative to its 52w range?
- Does momentum support or contradict the fundamental case?

Avoid clichés like "consolidating" or "testing support". Be specific:
"Down 18% in 3 months despite raising guidance — sentiment problem, not business problem."

{VOICE_RULES}
"""
    system = "You're a momentum/technical specialist on a fundamental research team. Pragmatic, not chart-cult."
    try:
        read = _strip_markdown(call_llm(system, prompt, temperature=0.3))
    except Exception as e:
        log.append(f"[6/14 technical_analyst] Failed: {e}")
        read = "Momentum read unavailable."

    log.append("[6/14 technical_analyst] Tape read complete")
    return {
        "technicals": {
            "read": read,
            "pct_from_52w_high": pct_from_high,
            "pct_from_52w_low": pct_from_low,
        },
        "log": log,
    }


# ============================================================================
# NODE 7: macro_strategist — sector dynamics, rate environment
# ============================================================================

def macro_strategist_node(state: AgentState) -> dict[str, Any]:
    """Macro/sector context for the call."""
    log = ["[7/14 macro_strategist] Sector dynamics"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})

    prompt = f"""
Company: {profile.get('name')} ({profile.get('ticker')})
Sector: {profile.get('sector')} / {profile.get('industry')}

Write ONE paragraph (~120 words) of macro/sector context:
- Where is this sector in its cycle (early, mid, late, recession)?
- What macro factor matters most right now (rates, oil, consumer health, AI capex cycle, etc.)?
- Is this company a beneficiary or victim of the current macro setup?
- One specific risk from the macro environment that could affect this name in the next 6 months.

Be concrete. "Fed cuts of 75bps priced in for next year" beats "supportive rate environment".

{VOICE_RULES}
"""
    system = "You're a macro/sector strategist. Top-down view, specific calls, no hedging."
    try:
        view = _strip_markdown(call_llm(system, prompt, temperature=0.3))
    except Exception as e:
        log.append(f"[7/14 macro_strategist] Failed: {e}")
        view = "Macro view unavailable."

    log.append("[7/14 macro_strategist] Macro view complete")
    return {"macro_view": {"view": view}, "log": log}


# ============================================================================
# NODE 8: dcf_modeler — 5-year DCF with anchored assumptions
# ============================================================================

def dcf_modeler_node(state: AgentState) -> dict[str, Any]:
    """Build DCF assumptions (LLM) + compute valuation (deterministic Python)."""
    log = ["[8/14 dcf_modeler] Building DCF"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    anchors = data.get("historical_anchors") or {}

    base_revenue = metrics.get("total_revenue") or 0
    fcf = metrics.get("free_cash_flow") or 0
    growth = metrics.get("revenue_growth") or 0.05
    beta = metrics.get("beta") or 1.0
    hist_fcf_margin = anchors.get("avg_fcf_margin_3y")
    hist_rev_growth = anchors.get("avg_revenue_growth_3y")
    current_fcf_margin = (fcf / base_revenue) if (fcf and base_revenue) else None

    anchors_text = []
    if current_fcf_margin is not None:
        anchors_text.append(f"- Current FCF margin (TTM): {current_fcf_margin * 100:.1f}%")
    if hist_fcf_margin is not None:
        anchors_text.append(f"- Avg FCF margin (3y): {hist_fcf_margin * 100:.1f}%")
    if hist_rev_growth is not None:
        anchors_text.append(f"- Avg revenue growth (3y): {hist_rev_growth * 100:.1f}%")
    anchors_block = "\n".join(anchors_text) or "- (No historical anchors available)"

    prompt = f"""
DCF assumptions for {profile.get('name')} ({profile.get('ticker')}).

Profile:
- Sector: {profile.get('sector')}
- Revenue: {_fmt_money_short(base_revenue)}
- FCF: {_fmt_money_short(fcf)}
- Beta: {beta}

HISTORICAL ANCHORS (your fcf_margin should be close to these):
{anchors_block}

Return JSON ONLY:
{{
  "revenue_growth_y1": 0.08,
  "revenue_growth_y2": 0.07,
  "revenue_growth_y3": 0.06,
  "revenue_growth_y4": 0.05,
  "revenue_growth_y5": 0.04,
  "fcf_margin": 0.15,
  "terminal_growth": 0.025,
  "wacc": 0.09,
  "rationale": "1 sentence."
}}

Constraints:
- growth between -0.10 and 0.40
- fcf_margin between 0.02 and 0.45, within +/- 5pp of historical
- terminal_growth between 0.015 and 0.035 (must be < WACC)
- WACC between 0.06 and 0.14
"""
    system = "DCF assumption builder. Output JSON only."
    raw = call_llm(system, prompt, temperature=0.2)
    assumptions = _parse_json_safe(raw) or _fallback_assumptions(growth, beta)

    valuation = _compute_dcf(
        base_revenue=base_revenue or 1e9,
        net_debt=(metrics.get("total_debt") or 0) - (metrics.get("total_cash") or 0),
        shares=metrics.get("shares_outstanding") or 1,
        current_price=metrics.get("current_price") or 0,
        assumptions=assumptions,
    )
    valuation["assumptions"] = assumptions

    log.append(f"[8/14 dcf_modeler] Implied: ${valuation['implied_share_price']:.2f}")
    return {"dcf_valuation": valuation, "log": log}


def _fallback_assumptions(growth: float, beta: float) -> dict[str, float]:
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
        "rationale": "Default assumptions used.",
    }


def _compute_dcf(base_revenue, net_debt, shares, current_price, assumptions):
    growths = [assumptions[f"revenue_growth_y{i}"] for i in range(1, 6)]
    margin = assumptions["fcf_margin"]
    wacc = assumptions["wacc"]
    tg = assumptions["terminal_growth"]

    revenues, fcfs, pv_fcfs = [], [], []
    rev = base_revenue
    for i, g in enumerate(growths, start=1):
        rev = rev * (1 + g)
        fcf = rev * margin
        pv = fcf / ((1 + wacc) ** i)
        revenues.append(rev)
        fcfs.append(fcf)
        pv_fcfs.append(pv)

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


# ============================================================================
# NODE 9: comps_modeler — peer-multiple valuation
# ============================================================================

def comps_modeler_node(state: AgentState) -> dict[str, Any]:
    """Apply peer median multiples to subject's financials to derive comp-based price."""
    log = ["[9/14 comps_modeler] Comp-based valuation"]
    data = state.get("company_data") or {}
    metrics = data.get("metrics", {})
    peer_analysis = state.get("peer_analysis") or {}
    medians = peer_analysis.get("medians") or {}

    shares = metrics.get("shares_outstanding") or 0
    if not shares:
        log.append("[9/14 comps_modeler] No shares outstanding — skipping")
        return {"comps_valuation": {"implied_price": None, "method": "unavailable"}, "log": log}

    # Build implied prices from each multiple where we have data
    implied_prices = []
    methods = []

    # P/E approach — needs EPS
    eps_ttm = None
    if metrics.get("pe_ratio") and metrics.get("current_price"):
        try:
            eps_ttm = metrics["current_price"] / metrics["pe_ratio"]
        except (ZeroDivisionError, TypeError):
            pass
    if eps_ttm and medians.get("pe"):
        implied_prices.append(("P/E", eps_ttm * medians["pe"]))
        methods.append(f"P/E: EPS ${eps_ttm:.2f} × {medians['pe']:.1f}x = ${eps_ttm * medians['pe']:.2f}")

    # EV/EBITDA approach
    ebitda = metrics.get("ebitda")
    if ebitda and medians.get("ev_ebitda"):
        net_debt = (metrics.get("total_debt") or 0) - (metrics.get("total_cash") or 0)
        implied_ev = ebitda * medians["ev_ebitda"]
        implied_equity = implied_ev - net_debt
        if implied_equity > 0:
            implied_prices.append(("EV/EBITDA", implied_equity / shares))
            methods.append(f"EV/EBITDA: {_fmt_money_short(ebitda)} × {medians['ev_ebitda']:.1f}x = {_fmt_money_short(implied_ev)}")

    # EV/Sales approach
    revenue = metrics.get("total_revenue")
    if revenue and medians.get("ev_sales"):
        net_debt = (metrics.get("total_debt") or 0) - (metrics.get("total_cash") or 0)
        implied_ev = revenue * medians["ev_sales"]
        implied_equity = implied_ev - net_debt
        if implied_equity > 0:
            implied_prices.append(("EV/Sales", implied_equity / shares))
            methods.append(f"EV/Sales: {_fmt_money_short(revenue)} × {medians['ev_sales']:.1f}x = {_fmt_money_short(implied_ev)}")

    if not implied_prices:
        log.append("[9/14 comps_modeler] Insufficient data for comp valuation")
        return {"comps_valuation": {"implied_price": None, "method": "unavailable"}, "log": log}

    # Average across methods
    avg_implied = sum(p[1] for p in implied_prices) / len(implied_prices)
    current = metrics.get("current_price") or 0
    upside = (avg_implied / current - 1) if current else 0

    result = {
        "implied_price": avg_implied,
        "current_price": current,
        "upside_pct": upside,
        "methods": methods,
        "breakdown": [{"method": m, "price": p} for m, p in implied_prices],
    }
    log.append(f"[9/14 comps_modeler] Avg implied ${avg_implied:.2f} across {len(implied_prices)} methods")
    return {"comps_valuation": result, "log": log}


# ============================================================================
# NODE 10: scenarios_modeler — bull/base/bear
# ============================================================================

def scenarios_modeler_node(state: AgentState) -> dict[str, Any]:
    """Build bull/base/bear scenarios with explicit assumption changes."""
    log = ["[10/14 scenarios_modeler] Building scenarios"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    dcf = state.get("dcf_valuation", {})
    base_assumptions = dcf.get("assumptions", {})

    if not base_assumptions:
        log.append("[10/14 scenarios_modeler] No base DCF to flex — skipping")
        return {"scenarios": {}, "log": log}

    base_revenue = metrics.get("total_revenue") or 1e9
    net_debt = (metrics.get("total_debt") or 0) - (metrics.get("total_cash") or 0)
    shares = metrics.get("shares_outstanding") or 1
    current = metrics.get("current_price") or 0

    # Flex assumptions: bull = +50% growth, +5pp margin, -1pp WACC
    #                   bear = -50% growth, -5pp margin, +1pp WACC
    def _flex(base, growth_mult, margin_delta, wacc_delta):
        flexed = dict(base)
        for i in range(1, 6):
            k = f"revenue_growth_y{i}"
            flexed[k] = max(min(base[k] * growth_mult, 0.40), -0.10)
        flexed["fcf_margin"] = max(min(base["fcf_margin"] + margin_delta, 0.45), 0.02)
        flexed["wacc"] = max(min(base["wacc"] + wacc_delta, 0.14), 0.06)
        # Ensure terminal_growth < WACC
        if flexed["terminal_growth"] >= flexed["wacc"]:
            flexed["terminal_growth"] = flexed["wacc"] - 0.01
        return flexed

    bull_assumptions = _flex(base_assumptions, 1.5, 0.05, -0.01)
    bear_assumptions = _flex(base_assumptions, 0.5, -0.05, 0.01)

    def _do_dcf(assumptions):
        return _compute_dcf(base_revenue, net_debt, shares, current, assumptions)

    base_val = _do_dcf(base_assumptions)
    bull_val = _do_dcf(bull_assumptions)
    bear_val = _do_dcf(bear_assumptions)

    scenarios = {
        "bull": {
            "price": bull_val["implied_share_price"],
            "upside_pct": bull_val["upside_pct"],
            "description": f"Higher growth (+50%), margin expansion (+5pp), lower WACC (-1pp)",
        },
        "base": {
            "price": base_val["implied_share_price"],
            "upside_pct": base_val["upside_pct"],
            "description": "Anchored to 3-year historical performance",
        },
        "bear": {
            "price": bear_val["implied_share_price"],
            "upside_pct": bear_val["upside_pct"],
            "description": f"Slower growth (-50%), margin compression (-5pp), higher WACC (+1pp)",
        },
    }
    log.append(
        f"[10/14 scenarios_modeler] Bear ${bear_val['implied_share_price']:.0f} / "
        f"Base ${base_val['implied_share_price']:.0f} / "
        f"Bull ${bull_val['implied_share_price']:.0f}"
    )
    return {"scenarios": scenarios, "log": log}


# ============================================================================
# NODE 11: reality_check — which models do we trust?
# ============================================================================

def reality_check_node(state: AgentState) -> dict[str, Any]:
    """Decide which valuation methods are credible for THIS stock."""
    log = ["[11/14 reality_check] Weighing methods"]
    stock_type = state.get("stock_type", "BALANCED")
    framework = state.get("valuation_framework", "DCF-led")
    dcf = state.get("dcf_valuation", {})
    comps = state.get("comps_valuation", {})
    scenarios = state.get("scenarios", {})

    dcf_upside = dcf.get("upside_pct", 0) or 0
    comps_upside = comps.get("upside_pct", 0) or 0
    has_comps = comps.get("implied_price") is not None
    has_scenarios = bool(scenarios)

    # Determine weights
    weights = {"dcf": 1.0, "comps": 0.0, "scenarios": 0.0}
    reasoning = []

    if stock_type == "OPTIONALITY":
        # DCF will give garbage; lean heavily on scenarios + comps
        weights = {"dcf": 0.1, "comps": 0.4 if has_comps else 0.0, "scenarios": 0.5 if has_scenarios else 0.0}
        reasoning.append("Stock is OPTIONALITY type — DCF on current FCF underweights future scenarios.")
    elif stock_type == "DISTRESSED":
        weights = {"dcf": 0.2, "comps": 0.6 if has_comps else 0.0, "scenarios": 0.2 if has_scenarios else 0.0}
        reasoning.append("Distressed name — DCF unreliable, lean on multiples and scenarios.")
    elif stock_type == "CYCLICAL":
        weights = {"dcf": 0.3, "comps": 0.6 if has_comps else 0.0, "scenarios": 0.1 if has_scenarios else 0.0}
        reasoning.append("Cyclical name — mid-cycle multiples matter more than point-in-time DCF.")
    elif stock_type == "GROWTH":
        weights = {"dcf": 0.5, "comps": 0.3 if has_comps else 0.0, "scenarios": 0.2 if has_scenarios else 0.0}
        reasoning.append("Growth name — DCF + comps + scenarios all matter.")
    else:  # VALUE / BALANCED
        weights = {"dcf": 0.6, "comps": 0.3 if has_comps else 0.0, "scenarios": 0.1 if has_scenarios else 0.0}
        reasoning.append("Mature profile — DCF works well, comps provide a sanity check.")

    # If DCF says >75% off, de-weight regardless
    if abs(dcf_upside) > 0.75 and stock_type != "DISTRESSED":
        old_w = weights["dcf"]
        weights["dcf"] = min(weights["dcf"], 0.15)
        # Reallocate to comps/scenarios
        slack = old_w - weights["dcf"]
        if has_scenarios:
            weights["scenarios"] += slack * 0.6
        if has_comps:
            weights["comps"] += slack * 0.4
        reasoning.append(f"DCF implies {dcf_upside * 100:+.0f}% — likely garbage signal. De-weighting.")

    # Normalize
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {k: v / total_w for k, v in weights.items()}

    # Compute blended target
    blended_target = 0
    if weights["dcf"] > 0 and dcf.get("implied_share_price"):
        blended_target += weights["dcf"] * dcf["implied_share_price"]
    if weights["comps"] > 0 and comps.get("implied_price"):
        blended_target += weights["comps"] * comps["implied_price"]
    if weights["scenarios"] > 0 and scenarios.get("base"):
        blended_target += weights["scenarios"] * scenarios["base"]["price"]

    # Range from scenarios if available
    target_low = scenarios.get("bear", {}).get("price") if scenarios else None
    target_high = scenarios.get("bull", {}).get("price") if scenarios else None

    log.append(
        f"[11/14 reality_check] Weights: DCF {weights['dcf']:.0%} / "
        f"Comps {weights['comps']:.0%} / Scenarios {weights['scenarios']:.0%} → "
        f"Blended target ${blended_target:.2f}"
    )
    return {
        "valuation_reality": {
            "weights": weights,
            "blended_target": blended_target,
            "target_range_low": target_low,
            "target_range_high": target_high,
            "reasoning": " ".join(reasoning),
        },
        "log": log,
    }


# ============================================================================
# NODE 12: bull_advocate — strongest case for owning
# ============================================================================

def bull_advocate_node(state: AgentState) -> dict[str, Any]:
    """Adversarial agent: argue the strongest bull case."""
    log = ["[12/14 bull_advocate] Building bull case"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    fundamentals = state.get("fundamentals", {})
    scenarios = state.get("scenarios", {})

    bull_target = scenarios.get("bull", {}).get("price") if scenarios else None
    bull_upside = scenarios.get("bull", {}).get("upside_pct") if scenarios else None

    prompt = f"""
You are arguing the BULL CASE for {profile.get('name')} ({profile.get('ticker')}).
Your job: make the strongest possible argument for OWNING this stock. Be aggressive.
You can disagree with what the rest of the report says — your job is the upside case.

Context:
- Current price: ${metrics.get('current_price', 0):,.2f}
- Bull scenario implied price: {f'${bull_target:,.2f} ({bull_upside * 100:+.0f}%)' if bull_target else 'N/A'}
- Business model: {(fundamentals.get('business_model') or 'N/A')[:500]}
- Moat: {(fundamentals.get('moat') or 'N/A')[:300]}

Write 3-4 numbered bullets that make the bull case. Each bullet:
- Starts with "1. " (or 2., 3., etc.)
- Identifies a specific revenue/margin/multiple driver
- References a specific number or path to one
- Is what a real bull would say in a meeting

End with one sentence: "The bull case wins if [specific condition]"

{VOICE_RULES}
"""
    system = "You are an aggressive long-only PM making the case to own this. Specific, numeric, no hedging."
    try:
        argument = _strip_markdown(call_llm(system, prompt, temperature=0.4))
    except Exception as e:
        log.append(f"[12/14 bull_advocate] Failed: {e}")
        argument = "Bull case unavailable."

    log.append("[12/14 bull_advocate] Bull case complete")
    return {"bull_case": {"argument": argument, "target": bull_target}, "log": log}


# ============================================================================
# NODE 13: bear_advocate — strongest case against
# ============================================================================

def bear_advocate_node(state: AgentState) -> dict[str, Any]:
    """Adversarial agent: argue the strongest bear case."""
    log = ["[13/14 bear_advocate] Building bear case"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    fundamentals = state.get("fundamentals", {})
    scenarios = state.get("scenarios", {})

    bear_target = scenarios.get("bear", {}).get("price") if scenarios else None
    bear_downside = scenarios.get("bear", {}).get("upside_pct") if scenarios else None

    prompt = f"""
You are arguing the BEAR CASE for {profile.get('name')} ({profile.get('ticker')}).
Your job: make the strongest possible argument for SHORTING or avoiding this stock.

Context:
- Current price: ${metrics.get('current_price', 0):,.2f}
- Bear scenario implied price: {f'${bear_target:,.2f} ({bear_downside * 100:+.0f}%)' if bear_target else 'N/A'}
- Business model: {(fundamentals.get('business_model') or 'N/A')[:500]}
- Margin trajectory: {(fundamentals.get('margin_trajectory') or 'N/A')[:300]}

Write 3-4 numbered bullets making the bear case. Each:
- Starts with "1. " etc.
- Identifies a specific threat (regulatory, competitive, secular, financial)
- References specific data showing the threat is real (not hypothetical)
- Is what a real short-seller would write in their pitch

End with: "The bear case wins if [specific condition]"

{VOICE_RULES}
"""
    system = "You are a short-seller pitching this name. Aggressive, specific, evidence-based."
    try:
        argument = _strip_markdown(call_llm(system, prompt, temperature=0.4))
    except Exception as e:
        log.append(f"[13/14 bear_advocate] Failed: {e}")
        argument = "Bear case unavailable."

    log.append("[13/14 bear_advocate] Bear case complete")
    return {"bear_case": {"argument": argument, "target": bear_target}, "log": log}


# ============================================================================
# NODE 14: chief_strategist — final synthesis
# ============================================================================

def chief_strategist_node(state: AgentState) -> dict[str, Any]:
    """Synthesize everything, make the call."""
    log = ["[14/14 chief_strategist] Final synthesis"]
    data = state.get("company_data") or {}
    profile = data.get("profile", {})
    metrics = data.get("metrics", {})
    stock_type = state.get("stock_type", "BALANCED")
    framework = state.get("valuation_framework", "DCF-led")
    reality = state.get("valuation_reality", {})

    blended_target = reality.get("blended_target", 0) or 0
    current = metrics.get("current_price") or 0
    upside = (blended_target / current - 1) if current and blended_target else 0

    # Rule-based rec from blended target
    if upside > 0.15:
        rec = "BUY"
    elif upside < -0.10:
        rec = "SELL"
    else:
        rec = "HOLD"

    # Confidence score
    weights = reality.get("weights", {})
    abs_upside = abs(upside)
    base_conf = 6
    if abs_upside > 0.5:
        base_conf -= 1  # extreme gaps are suspicious
    elif abs_upside < 0.08:
        base_conf -= 1  # very tight = HOLD with low conviction
    elif abs_upside < 0.25:
        base_conf += 1  # nice clean call

    # Multi-method agreement boosts confidence
    methods_used = sum(1 for w in weights.values() if w > 0.15)
    if methods_used >= 2:
        base_conf += 1
    beta = metrics.get("beta") or 1.0
    if beta and beta > 1.8:
        base_conf -= 1

    confidence_score = max(1, min(10, base_conf))

    bull_case = state.get("bull_case", {}).get("argument", "")
    bear_case = state.get("bear_case", {}).get("argument", "")
    fundamentals = state.get("fundamentals", {})
    technicals = state.get("technicals", {}).get("read", "")
    macro = state.get("macro_view", {}).get("view", "")
    catalysts = state.get("catalysts", [])
    peer_interp = state.get("peer_analysis", {}).get("interpretation", "")

    catalyst_text = "; ".join(f"{c['headline']} ({c['impact']})" for c in catalysts[:3]) or "(none identified)"

    prompt = f"""
You are the CHIEF STRATEGIST. Read what the team produced and write the final call.

STOCK PROFILE:
- {profile.get('name')} ({profile.get('ticker')}) | {profile.get('sector')}
- Stock type: {stock_type} | Framework: {framework}
- Current: ${current:,.2f} | Blended target: ${blended_target:,.2f} ({upside * 100:+.1f}%)
- Recommendation: {rec}

WEIGHTING METHODOLOGY: {reality.get('reasoning', '')}

TEAM OUTPUT:
Business model: {(fundamentals.get('business_model') or '')[:400]}
Moat: {(fundamentals.get('moat') or '')[:300]}
Margin trajectory: {(fundamentals.get('margin_trajectory') or '')[:300]}
Technicals: {technicals[:400]}
Macro: {macro[:400]}
Peer comps: {peer_interp[:400]}
Catalysts: {catalyst_text}

BULL CASE: {bull_case[:600]}

BEAR CASE: {bear_case[:600]}

Write THREE sections using EXACT delimiters:

### EXECUTIVE SUMMARY ###
Three short paragraphs (~275 words total).

P1 (the call): Open with the rating + target in YOUR voice. Examples to emulate:
- "We're SELLERS of TSLA at $433. The DCF gives a nonsense answer because TSLA isn't a DCF stock — that's the call."
- "BUY NVDA at $214 with a $260 target. The bear case has been wrong for 18 months and nothing has changed."
Then 2-3 sentences explaining which framework you used and why, naming the most important number.

P2 (synthesis): The 2-3 strongest arguments combining bull and bear views. Honest about what the bears get right.
Reference specific catalysts, peer multiples, or scenario outcomes.

P3 (risks to OUR call): Where could we be wrong? Specific scenarios that flip the rating.

### WHAT WOULD CHANGE OUR MIND ###
ONE specific, falsifiable sentence. Example:
"We flip to BUY if FCF margin recovers above 22% for two consecutive quarters AND services growth holds >12%."

### CONFIDENCE RATIONALE ###
ONE sentence explaining the confidence level given the framework, data quality, and gap size.

### INVESTMENT THESIS ###
3-4 bullets synthesizing the bull case + fundamentals. Format with "- ". Each bullet ties back to numbers.
Pick the strongest 3-4 — quality over quantity.

### KEY RISKS ###
3-4 bullets synthesizing the bear case + fundamentals. Same format. Honest about real risks.

{VOICE_RULES}
"""
    system = (
        "You are the chief equity strategist. You read your team's work and make a sharp, specific call. "
        "You don't hedge. You acknowledge where you could be wrong. You use the framework that fits the stock. "
        "Voice: like a real PM in a morning meeting, not a textbook."
    )
    raw = call_llm(system, prompt, temperature=0.4)
    sections = _split_sections(raw)

    exec_summary = sections.get("EXECUTIVE SUMMARY", "")
    what_change_mind = sections.get("WHAT WOULD CHANGE OUR MIND", "")
    conf_rationale = sections.get("CONFIDENCE RATIONALE", "")
    thesis = sections.get("INVESTMENT THESIS", "")
    risks = sections.get("KEY RISKS", "")

    if not exec_summary:
        exec_summary = _strip_markdown(raw)

    log.append(f"[14/14 chief_strategist] {rec} @ ${blended_target:.2f} | conf {confidence_score}/10")
    return {
        "recommendation": rec,
        "target_price": blended_target,
        "target_range_low": reality.get("target_range_low"),
        "target_range_high": reality.get("target_range_high"),
        "confidence_score": confidence_score,
        "confidence_rationale": conf_rationale,
        "what_would_change_mind": what_change_mind,
        "executive_summary": exec_summary,
        "investment_thesis": thesis,
        "key_risks": risks,
        "log": log,
    }


# Aliases for backward compat with old code (PDF generator, frontend)
def writer_node(state):
    return chief_strategist_node(state)


def researcher_node(state):
    # New flow uses fundamentals_analyst; keep alias for any stragglers
    return fundamentals_analyst_node(state)


def analyst_node(state):
    return dcf_modeler_node(state)
