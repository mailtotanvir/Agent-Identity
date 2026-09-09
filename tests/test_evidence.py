import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")
os.environ.setdefault("AUTH0_APP_ID", "test-client-id")
os.environ.setdefault("AUTH0_CLIENT_SECRET", "test-secret")
os.environ.setdefault("AUTH0_MGMT_AUDIENCE", "https://test.auth0.com/api/v2/")
os.environ.setdefault("AUTH0_MGMT_TOKEN", "test-mgmt-token")

from auth0.lifecycle import ApprovalStatus  # noqa: E402
from graph import nodes  # noqa: E402
from graph.graph import compiled_graph  # noqa: E402
from main import build_initial_state  # noqa: E402

REQUIRED_KEYS = {
    "run_id",
    "started_at",
    "completed_at",
    "task_topic",
    "outcome",
    "auth0_client_id",
    "auth0_domain",
    "security_approved",
    "langfuse_trace_url",
    "total_cost_usd",
    "killswitch_fired",
    "steps",
    "auth0_logs",
}


def _mock_token():
    return {
        "access_token": "tok",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "read:clients",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def _run_happy_path(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(nodes, "EVIDENCE_DIR", tmp_path)
    approval = ApprovalStatus(
        approved=True,
        raw_value="true",
        app_id="test-client-id",
        checked_at=datetime.now(timezone.utc).isoformat(),
        reason="mock",
    )
    with patch.object(nodes.auth, "get_agent_token", _mock_token), patch.object(
        nodes.lifecycle, "check_agent_approved", lambda: approval
    ), patch.object(
        nodes, "_run_llm", lambda node, s, u: (f"out-{node}", 0.0005)
    ), patch.object(
        nodes.logs, "get_run_logs", lambda *a: []
    ):
        compiled_graph.invoke(build_initial_state("evidence test", False))
    return json.loads(next(tmp_path.glob("run_*.json")).read_text())


def test_all_top_level_keys_present(tmp_path, monkeypatch):
    data = _run_happy_path(tmp_path, monkeypatch)
    assert REQUIRED_KEYS.issubset(data.keys())


def test_steps_cover_all_ran_nodes(tmp_path, monkeypatch):
    data = _run_happy_path(tmp_path, monkeypatch)
    ran_nodes = {step["node"] for step in data["steps"]}
    assert ran_nodes == {
        "authenticate",
        "approval_gate",
        "planner",
        "researcher",
        "summariser",
        "evidence_collector",
    }


def test_auth0_logs_is_list(tmp_path, monkeypatch):
    data = _run_happy_path(tmp_path, monkeypatch)
    assert isinstance(data["auth0_logs"], list)


def test_total_cost_is_nonnegative_float(tmp_path, monkeypatch):
    data = _run_happy_path(tmp_path, monkeypatch)
    assert isinstance(data["total_cost_usd"], float)
    assert data["total_cost_usd"] >= 0
