"""
LangGraph workflow definition. Wires together the four nodes:
  data_collector -> researcher -> analyst -> writer

This is what makes it a real "agent" in the resume sense:
multi-step, stateful reasoning with explicit control flow.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import analyst_node, data_collector_node, researcher_node, writer_node
from .state import AgentState


def build_agent():
    """Construct and compile the LangGraph workflow."""
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("data_collector", data_collector_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)

    # Define the flow
    graph.set_entry_point("data_collector")
    graph.add_edge("data_collector", "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", END)

    return graph.compile()


def run_agent(ticker: str) -> AgentState:
    """Run the full agent for a ticker. Returns final state."""
    agent = build_agent()
    initial: AgentState = {"ticker": ticker.upper().strip(), "log": [], "errors": []}
    final_state = agent.invoke(initial)
    return final_state
