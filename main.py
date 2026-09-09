"""Agent Identity Gateway entry point.

Usage:
  python main.py [--topic "custom topic"]
  python main.py --approve                # print the Auth0 approval URL and exit
  python main.py --status                 # print current security_approved value and exit
  python main.py --simulate-suspicious    # seed token_request_count=11 to demo the kill switch
"""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()


def build_initial_state(topic: str, simulate_suspicious: bool) -> dict:
    return {
        "run_id": uuid.uuid4().hex[:8],
        "access_token": None,
        "token_expires_in": None,
        "token_scope": None,
        "token_issued_at": None,
        "approval_status": None,
        "task_topic": topic,
        "research_query": None,
        "research_result": None,
        "summary": None,
        "langfuse_trace_id": None,
        "langfuse_trace_url": None,
        "token_usage": [],
        "total_cost_usd": 0.0,
        "token_request_count": 11 if simulate_suspicious else 0,
        "killswitch_fired": False,
        "evidence_log": [],
        "auth0_logs": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }


def print_final_panel(state: dict, evidence_path: str) -> None:
    from graph.nodes import derive_outcome

    approval = state.get("approval_status") or {}
    approved = approval.get("approved", False)
    line = "━" * 53
    console.print(f"\n{line}")
    console.print(f"  AGENT IDENTITY GATEWAY — Run {state['run_id']}")
    console.print(line)
    console.print(f"  Auth0 Identity : {os.environ.get('AUTH0_DOMAIN', '?')}")
    console.print(f"  Client ID      : {os.environ.get('AUTH0_CLIENT_ID', '?')}")
    console.print(
        f"  Approved       : {'✓ YES (security_approved=true)' if approved else '✗ NO (security_approved=' + str(approval.get('raw_value', 'missing')) + ')'}"
    )
    console.print(f"  Task           : {state['task_topic']}")
    console.print(f"  Outcome        : {derive_outcome(state)}")
    console.print(f"  Total Cost     : ${state.get('total_cost_usd') or 0.0:.4f}")
    console.print(f"  Langfuse Trace : {state.get('langfuse_trace_url') or 'n/a'}")
    console.print(f"  Evidence File  : {evidence_path}")
    console.print(
        f"  Killswitch     : {'FIRED' if state.get('killswitch_fired') else 'NOT FIRED'}"
    )
    console.print(line)
    if state.get("summary"):
        console.print("\n  Summary:")
        for bullet in state["summary"].splitlines():
            if bullet.strip():
                console.print(f"  {bullet.strip()}")
        console.print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Identity Gateway")
    parser.add_argument(
        "--topic", default=os.environ.get("AGENT_TASK_TOPIC", "enterprise agentic AI governance")
    )
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--simulate-suspicious", action="store_true")
    args = parser.parse_args()

    from auth0 import lifecycle

    if args.approve:
        console.print("Approve the agent here:")
        console.print(lifecycle.approval_dashboard_url())
        console.print("→ Application Metadata → set security_approved = true → Save")
        return 0

    if args.status:
        status = lifecycle.check_agent_approved()
        console.print(f"security_approved = {status.raw_value}")
        console.print(f"approved          = {status.approved}")
        console.print(f"reason            = {status.reason}")
        return 0

    from graph import nodes
    from graph.graph import compiled_graph
    from langfuse_client import tracing

    state = build_initial_state(args.topic, args.simulate_suspicious)

    # Langfuse is best-effort: a tracing failure must never block the run.
    try:
        trace, trace_id, trace_url = tracing.init_trace(
            state["run_id"], state["task_topic"]
        )
        nodes.set_trace(trace)
        state["langfuse_trace_id"] = trace_id
        state["langfuse_trace_url"] = trace_url
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]WARN: Langfuse init failed: {exc}[/yellow]")

    final_state = state
    try:
        final_state = compiled_graph.invoke(state)
    except Exception as exc:  # noqa: BLE001
        final_state = {**state, "error": f"unhandled: {exc}"}
    finally:
        # The evidence file must ALWAYS exist, even on early exits.
        evidence_path = nodes.write_evidence(final_state)
        try:
            tracing.flush()
        except Exception:  # noqa: BLE001
            pass

    print_final_panel(final_state, str(evidence_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
