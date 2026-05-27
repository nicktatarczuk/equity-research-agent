"""
Shared state for the 14-agent equity research workflow.
Parallel agents need annotated reducers for fields they all write to,
otherwise LangGraph raises INVALID_CONCURRENT_GRAPH_UPDATE.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


StockType = Literal["VALUE", "GROWTH", "OPTIONALITY", "CYCLICAL", "DISTRESSED", "BALANCED"]


class AgentState(TypedDict, total=False):
    # Inputs
    ticker: str

    # Raw data (data_collector)
    company_data: dict[str, Any]

    # Classification (classifier)
    stock_type: StockType
    stock_type_rationale: str
    valuation_framework: str

    # Parallel research outputs - each agent writes its own slice
    fundamentals: dict[str, Any]
    catalysts: list[dict[str, Any]]
    peer_analysis: dict[str, Any]
    technicals: dict[str, Any]
    macro_view: dict[str, Any]

    # Valuation triangulation
    dcf_valuation: dict[str, Any]
    comps_valuation: dict[str, Any]
    scenarios: dict[str, Any]
    valuation_reality: dict[str, Any]

    # Debate
    bull_case: dict[str, Any]
    bear_case: dict[str, Any]

    # Final synthesis (chief_strategist)
    recommendation: str
    target_price: float
    target_range_low: float
    target_range_high: float
    confidence_score: int
    confidence_rationale: str
    what_would_change_mind: str
    executive_summary: str
    investment_thesis: str
    key_risks: str

    # Lists that PARALLEL agents append to — must use add-reducer
    # so LangGraph knows to concatenate instead of conflict
    log: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
