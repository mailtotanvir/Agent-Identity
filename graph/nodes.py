"""The seven graph nodes plus evidence writing and outcome derivation."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from auth0 import auth, killswitch, lifecycle, logs
from graph.state import AgentState
from langfuse_client import tracing

load_dotenv()
console = Console()

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"

# Set by main.py after init_trace; a _NoopTrace keeps nodes testable without keys.
_trace = None


class _NoopSpanCtx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _NoopTrace:
    def span(self, *a, **k):
        return _NoopSpanCtx()

    def generation(self, *a, **k):
        return None


def set_trace(trace) -> None:
    global _trace
    _trace = trace


def get_trace():
    return _trace if _trace is not None else _NoopTrace()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _span(node_name: str):
    trace = get_trace()
    if isinstance(trace, _NoopTrace):
        return _NoopSpanCtx()
    return tracing.node_span(trace, node_name)


def _model_name() -> str:
    return os.environ.get("VERTEX_MODEL", "gemini-3.7-flash")


def _llm():
    from langchain_google_vertexai import ChatVertexAI

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set. Export your GCP project id and "
            "run `gcloud auth application-default login` first."
        )
    location = os.environ.get("VERTEX_LOCATION", "global")
    kwargs = {}
    if location == "global":
        # The global endpoint 404s over gRPC; force REST against the base host.
        kwargs = {"api_endpoint": "aiplatform.googleapis.com", "api_transport": "rest"}
    return ChatVertexAI(
        model_name=_model_name(),
        project=project,
        location=location,
        temperature=0.2,
        max_retries=2,
        **kwargs,
    )


def _run_llm(node: str, system: str, user: str) -> tuple[str, float]:
    """Invoke the LLM, record the generation in Langfuse, return (text, cost)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    resp = _llm().invoke([SystemMessage(content=system), HumanMessage(content=user)])
    usage = resp.usage_metadata or {}
    prompt_toks = usage.get("input_tokens", 0)
    completion_toks = usage.get("output_tokens", 0)
    trace = get_trace()
    if isinstance(trace, _NoopTrace):
        cost = 0.0
    else:
        cost = tracing.record_llm_call(
            trace, node, _model_name(), prompt_toks, completion_toks, user, resp.content
        )
    return resp.content, cost


# ── Node 1 ───────────────────────────────────────────────────────────────────
def authenticate(state: AgentState) -> dict:
    with _span("authenticate"):
        try:
            count = state["token_request_count"] + 1
            if killswitch.check_suspicious(count, 60):
                result = killswitch.revoke_agent_grant()
                evidence = {
                    "node": "authenticate",
                    "killswitch": True,
                    "revoke_result": result.model_dump(),
                    "at": _now(),
                }
                console.print(
                    Panel(
                        f"KILL SWITCH FIRED\n{result.reason}",
                        title="suspicious behaviour",
                        border_style="red",
                    )
                )
                return {
                    "token_request_count": count,
                    "killswitch_fired": True,
                    "error": "killswitch_fired",
                    "evidence_log": state["evidence_log"] + [evidence],
                }

            token = auth.get_agent_token()
            evidence = {
                "node": "authenticate",
                "token_scope": token["scope"],
                "token_expires_in": token["expires_in"],
                "issued_at": token["issued_at"],
            }
            return {
                "access_token": token["access_token"],
                "token_expires_in": token["expires_in"],
                "token_scope": token["scope"],
                "token_issued_at": token["issued_at"],
                "token_request_count": count,
                "evidence_log": state["evidence_log"] + [evidence],
            }
        except auth.Auth0AuthError as exc:
            return {
                "error": f"auth_failed: {exc}",
                "evidence_log": state["evidence_log"]
                + [{"node": "authenticate", "error": str(exc), "at": _now()}],
            }


# ── Node 2 ───────────────────────────────────────────────────────────────────
def approval_gate(state: AgentState) -> dict:
    with _span("approval_gate"):
        status = lifecycle.check_agent_approved()
        if status.approved:
            console.print(
                Panel(
                    f"[green]APPROVED[/green] — {status.reason}",
                    title="approval gate",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    f"[red]BLOCKED[/red]\n"
                    f"security_approved = {status.raw_value}\n"
                    f"{status.reason}\n\n"
                    f"Approve here:\n{lifecycle.approval_dashboard_url()}\n"
                    f"→ Application Metadata → security_approved = true",
                    title="approval gate",
                    border_style="red",
                )
            )
        evidence = {
            "node": "approval_gate",
            "approved": status.approved,
            "raw_value": status.raw_value,
            "checked_at": status.checked_at,
            "reason": status.reason,
        }
        return {
            "approval_status": status.model_dump(),
            "evidence_log": state["evidence_log"] + [evidence],
        }


# ── Nodes 3-5: LLM nodes ─────────────────────────────────────────────────────
def planner(state: AgentState) -> dict:
    with _span("planner"):
        try:
            query, cost = _run_llm(
                "planner",
                "Given a topic, produce a precise 1-sentence research query. "
                "Return only the query.",
                state["task_topic"],
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"planner_failed: {exc}"}
        usage = {"node": "planner", "model": _model_name(), "cost_usd": cost}
        return {
            "research_query": query.strip(),
            "token_usage": state["token_usage"] + [usage],
            "total_cost_usd": state["total_cost_usd"] + cost,
            "evidence_log": state["evidence_log"]
            + [
                {
                    "node": "planner",
                    "task_topic": state["task_topic"],
                    "research_query": query.strip(),
                    "cost_usd": round(cost, 6),
                }
            ],
        }


def researcher(state: AgentState) -> dict:
    with _span("researcher"):
        try:
            result, cost = _run_llm(
                "researcher",
                "You are a research assistant. Produce a factual 300-400 word "
                "briefing on the topic. Cite specific organisations, figures, or "
                "examples. If uncertain, say so.",
                state["research_query"] or state["task_topic"],
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"researcher_failed: {exc}"}
        usage = {"node": "researcher", "model": _model_name(), "cost_usd": cost}
        return {
            "research_result": result,
            "token_usage": state["token_usage"] + [usage],
            "total_cost_usd": state["total_cost_usd"] + cost,
            "evidence_log": state["evidence_log"]
            + [
                {
                    "node": "researcher",
                    "query": state["research_query"],
                    "result_preview": result[:200],
                    "cost_usd": round(cost, 6),
                }
            ],
        }


def summariser(state: AgentState) -> dict:
    with _span("summariser"):
        try:
            summary, cost = _run_llm(
                "summariser",
                "Condense the research into 3 crisp executive bullets. "
                "Max 25 words each. Start each with '•'.",
                state["research_result"] or "",
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"summariser_failed: {exc}"}
        usage = {"node": "summariser", "model": _model_name(), "cost_usd": cost}
        return {
            "summary": summary.strip(),
            "token_usage": state["token_usage"] + [usage],
            "total_cost_usd": state["total_cost_usd"] + cost,
            "evidence_log": state["evidence_log"]
            + [
                {
                    "node": "summariser",
                    "summary": summary.strip(),
                    "cost_usd": round(cost, 6),
                }
            ],
        }


# ── Node 6 ───────────────────────────────────────────────────────────────────
def evidence_collector(state: AgentState) -> dict:
    with _span("evidence_collector"):
        completed_at = _now()
        auth0_logs = logs.get_run_logs(state["started_at"], completed_at)
        step = {
            "node": "evidence_collector",
            "auth0_log_count": len(auth0_logs),
            "at": completed_at,
        }
        new_log = state["evidence_log"] + [step]
        new_state = {
            **state,
            "auth0_logs": auth0_logs,
            "completed_at": completed_at,
            "evidence_log": new_log,
        }
        path = write_evidence(new_state)
        step["evidence_file"] = str(path)
        console.print(f"[cyan]Evidence file  :[/cyan] {path}")
        if state.get("langfuse_trace_url"):
            console.print(
                f"[cyan]Langfuse trace :[/cyan] {state['langfuse_trace_url']}"
            )
        return {
            "auth0_logs": auth0_logs,
            "completed_at": completed_at,
            "evidence_log": new_log,
        }


# ── Node 7 ───────────────────────────────────────────────────────────────────
def rejected(state: AgentState) -> dict:
    with _span("rejected"):
        raw = (state.get("approval_status") or {}).get("raw_value", "missing")
        console.print(
            Panel(
                "AGENT RUN BLOCKED\n"
                f"Reason  : security_approved = {raw}\n"
                "Action  : Set security_approved=true in Auth0\n"
                f"URL     : {lifecycle.approval_dashboard_url()}\n"
                "          → Application Metadata",
                title="rejected",
                border_style="red",
            )
        )
        completed_at = _now()
        new_state = {**state, "completed_at": completed_at}
        path = write_evidence(new_state)
        console.print(f"[cyan]Evidence file  :[/cyan] {path}")
        return {
            "completed_at": completed_at,
            "evidence_log": state["evidence_log"]
            + [{"node": "rejected", "at": completed_at, "evidence_file": str(path)}],
        }


# ── Evidence helpers ─────────────────────────────────────────────────────────
def derive_outcome(state: dict) -> str:
    if state.get("killswitch_fired"):
        return "KILLSWITCH"
    approval = state.get("approval_status") or {}
    if approval and not approval.get("approved", False):
        return "REJECTED"
    if state.get("error"):
        return "ERROR"
    return "COMPLETED"


def write_evidence(state: dict) -> Path:
    EVIDENCE_DIR.mkdir(exist_ok=True)
    record = {
        "run_id": state["run_id"],
        "started_at": state["started_at"],
        "completed_at": state.get("completed_at") or _now(),
        "task_topic": state["task_topic"],
        "outcome": derive_outcome(state),
        "auth0_client_id": os.environ.get("AUTH0_CLIENT_ID", ""),
        "auth0_domain": os.environ.get("AUTH0_DOMAIN", ""),
        "security_approved": (state.get("approval_status") or {}).get(
            "approved", False
        ),
        "langfuse_trace_url": state.get("langfuse_trace_url"),
        "total_cost_usd": round(float(state.get("total_cost_usd") or 0.0), 6),
        "killswitch_fired": bool(state.get("killswitch_fired")),
        "steps": state.get("evidence_log", []),
        "auth0_logs": state.get("auth0_logs") or [],
    }
    if state.get("error"):
        record["error"] = state["error"]
    path = EVIDENCE_DIR / f"run_{state['run_id']}.json"
    path.write_text(json.dumps(record, indent=2, default=str))
    return path
