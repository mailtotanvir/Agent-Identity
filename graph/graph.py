"""StateGraph wiring: authenticate -> approval_gate -> (pipeline | rejected)."""

from langgraph.graph import END, StateGraph

from graph import nodes
from graph.state import AgentState


def _after_authenticate(state: AgentState) -> str:
    if state.get("error"):
        return "end"
    return "approval_gate"


def _after_approval(state: AgentState) -> str:
    approval = state.get("approval_status") or {}
    return "planner" if approval.get("approved") else "rejected"


def _after_llm_node(next_node: str):
    def router(state: AgentState) -> str:
        return "end" if state.get("error") else next_node

    return router


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("authenticate", nodes.authenticate)
    g.add_node("approval_gate", nodes.approval_gate)
    g.add_node("planner", nodes.planner)
    g.add_node("researcher", nodes.researcher)
    g.add_node("summariser", nodes.summariser)
    g.add_node("evidence_collector", nodes.evidence_collector)
    g.add_node("rejected", nodes.rejected)

    g.set_entry_point("authenticate")
    g.add_conditional_edges(
        "authenticate",
        _after_authenticate,
        {"approval_gate": "approval_gate", "end": END},
    )
    g.add_conditional_edges(
        "approval_gate",
        _after_approval,
        {"planner": "planner", "rejected": "rejected"},
    )
    g.add_conditional_edges(
        "planner",
        _after_llm_node("researcher"),
        {"researcher": "researcher", "end": END},
    )
    g.add_conditional_edges(
        "researcher",
        _after_llm_node("summariser"),
        {"summariser": "summariser", "end": END},
    )
    g.add_conditional_edges(
        "summariser",
        _after_llm_node("evidence_collector"),
        {"evidence_collector": "evidence_collector", "end": END},
    )
    g.add_edge("evidence_collector", END)
    g.add_edge("rejected", END)
    return g.compile()


compiled_graph = build_graph()
