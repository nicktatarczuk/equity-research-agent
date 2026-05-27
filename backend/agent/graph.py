"""
LangGraph workflow for the 14-agent research pipeline.

Flow:
    data_collector
        ↓
    classifier
        ↓
    [parallel research: fundamentals, catalysts, peers, technicals, macro]
        ↓ (all converge)
    dcf_modeler  (needs none of the parallel research)
        ↓
    [parallel: comps_modeler, scenarios_modeler]
        ↓ (converge)
    reality_check
        ↓
    [parallel: bull_advocate, bear_advocate]
        ↓ (converge)
    chief_strategist
        ↓
    END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import (
    bear_advocate_node,
    bull_advocate_node,
    catalyst_scout_node,
    chief_strategist_node,
    classifier_node,
    comps_modeler_node,
    data_collector_node,
    dcf_modeler_node,
    fundamentals_analyst_node,
    macro_strategist_node,
    peer_analyst_node,
    reality_check_node,
    scenarios_modeler_node,
    technical_analyst_node,
)
from .state import AgentState


def build_agent():
    """Construct and compile the 14-agent LangGraph workflow."""
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("data_collector", data_collector_node)
    graph.add_node("classifier", classifier_node)

    # Parallel research layer
    graph.add_node("research_fundamentals", fundamentals_analyst_node)
    graph.add_node("research_catalysts", catalyst_scout_node)
    graph.add_node("research_peers", peer_analyst_node)
    graph.add_node("research_technicals", technical_analyst_node)
    graph.add_node("research_macro", macro_strategist_node)

    # Valuation triangulation
    graph.add_node("val_dcf", dcf_modeler_node)
    graph.add_node("val_comps", comps_modeler_node)
    graph.add_node("val_scenarios", scenarios_modeler_node)
    graph.add_node("reality_check", reality_check_node)

    # Debate
    graph.add_node("debate_bull", bull_advocate_node)
    graph.add_node("debate_bear", bear_advocate_node)

    # Synthesis
    graph.add_node("synth_chief", chief_strategist_node)

    # ENTRY
    graph.set_entry_point("data_collector")
    graph.add_edge("data_collector", "classifier")

    # Fan out to 5 parallel research nodes
    for parallel in ("research_fundamentals", "research_catalysts", "research_peers", "research_technicals", "research_macro"):
        graph.add_edge("classifier", parallel)

    # All 5 must converge before DCF
    # LangGraph handles fan-in implicitly when multiple edges point to same node
    for parallel in ("research_fundamentals", "research_catalysts", "research_peers", "research_technicals", "research_macro"):
        graph.add_edge(parallel, "val_dcf")

    # Comps and scenarios depend on DCF (scenarios flexes DCF base; comps uses peers via state)
    graph.add_edge("val_dcf", "val_comps")
    graph.add_edge("val_dcf", "val_scenarios")

    # Reality check awaits both
    graph.add_edge("val_comps", "reality_check")
    graph.add_edge("val_scenarios", "reality_check")

    # Bull + bear in parallel after reality_check
    graph.add_edge("reality_check", "debate_bull")
    graph.add_edge("reality_check", "debate_bear")

    # Chief strategist synthesizes
    graph.add_edge("debate_bull", "synth_chief")
    graph.add_edge("debate_bear", "synth_chief")

    # End
    graph.add_edge("synth_chief", END)

    return graph.compile()


def run_agent(ticker: str) -> AgentState:
    """Run the full agent for a ticker. Returns final state."""
    agent = build_agent()
    initial: AgentState = {"ticker": ticker.upper().strip(), "log": [], "errors": []}
    final_state = agent.invoke(initial)
    return final_state
