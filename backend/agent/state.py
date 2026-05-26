"""
Shared state passed between LangGraph nodes.
Each node reads from and writes to this state.
"""
from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # Inputs
    ticker: str

    # Raw data (populated by data_collector)
    company_data: dict[str, Any]

    # Catalysts & momentum (populated by data_collector or its own node)
    catalysts: list[dict[str, Any]]   # [{date, headline, type, sentiment, interpretation}]
    momentum: dict[str, Any]          # {price_1mo, price_3mo, price_ytd, price_1yr, vs_sector}

    # Generated analyses (populated by researcher)
    business_overview: str
    investment_thesis: str
    risks: str
    competitive_position: str

    # DCF assumptions and outputs (populated by analyst)
    dcf_assumptions: dict[str, Any]
    dcf_valuation: dict[str, Any]

    # Final writeup (populated by writer)
    executive_summary: str
    recommendation: str  # BUY / HOLD / SELL
    target_price: float
    confidence_score: int  # 1-10
    confidence_rationale: str
    what_would_change_mind: str

    # Bookkeeping
    errors: list[str]
    log: list[str]
