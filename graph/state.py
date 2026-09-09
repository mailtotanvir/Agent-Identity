"""Shared LangGraph state for the Agent Identity Gateway run."""

from typing import List, Optional, TypedDict


class AgentState(TypedDict):
    # Identity
    run_id: str
    access_token: Optional[str]
    token_expires_in: Optional[int]
    token_scope: Optional[str]
    token_issued_at: Optional[str]

    # Approval
    approval_status: Optional[dict]  # ApprovalStatus.model_dump()

    # Task
    task_topic: str
    research_query: Optional[str]
    research_result: Optional[str]
    summary: Optional[str]

    # Observability
    langfuse_trace_id: Optional[str]
    langfuse_trace_url: Optional[str]

    # Cost
    token_usage: List[dict]  # {node, model, prompt_tokens, completion_tokens, cost_usd}
    total_cost_usd: float

    # Suspicious behaviour
    token_request_count: int
    killswitch_fired: bool

    # Evidence
    evidence_log: List[dict]
    auth0_logs: Optional[List[dict]]
    error: Optional[str]
    started_at: str
    completed_at: Optional[str]
