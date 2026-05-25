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

    # Bookkeeping
    errors: list[str]
    log: list[str]
