"""
Shared state for the 14-agent equity research workflow.
Each agent reads what it needs, writes its own slice.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


StockType = Literal["VALUE", "GROWTH", "OPTIONALITY", "CYCLICAL", "DISTRESSED", "BALANCED"]


class AgentState(TypedDict, total=False):
    # Inputs
    ticker: str

    # Raw data (data_collector)
    company_data: dict[str, Any]

    # Classification (classifier)
    stock_type: StockType
    stock_type_rationale: str
    valuation_framework: str  # "DCF-led", "Multiples-led", "Scenarios-led", "Asset-based"

    # Parallel research outputs
    fundamentals: dict[str, Any]      # fundamentals_analyst
    catalysts: list[dict[str, Any]]   # catalyst_scout
    peer_analysis: dict[str, Any]     # peer_analyst — comp table + interpretation
    technicals: dict[str, Any]        # technical_analyst — momentum read
    macro_view: dict[str, Any]        # macro_strategist — sector dynamics

    # Valuation triangulation
    dcf_valuation: dict[str, Any]     # dcf_modeler
    comps_valuation: dict[str, Any]   # comps_modeler
    scenarios: dict[str, Any]         # scenarios_modeler — bull/base/bear

    # Reality check
    valuation_reality: dict[str, Any] # which methods are reliable, which to weight

    # Debate
    bull_case: dict[str, Any]         # bull_advocate
    bear_case: dict[str, Any]         # bear_advocate

    # Final synthesis (chief_strategist)
    recommendation: str  # BUY / HOLD / SELL
    target_price: float
    target_range_low: float
    target_range_high: float
    confidence_score: int  # 1-10
    confidence_rationale: str
    what_would_change_mind: str
    executive_summary: str
    investment_thesis: str   # synthesized from bull case + fundamentals
    key_risks: str           # synthesized from bear case + fundamentals

    # Quality pass
    quality_issues: list[str]
    quality_passed: bool

    # Bookkeeping
    errors: list[str]
    log: list[str]
