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

from auth0.killswitch import RevokeResult  # noqa: E402
from auth0.lifecycle import ApprovalStatus  # noqa: E402
from graph import nodes  # noqa: E402
from graph.graph import compiled_graph  # noqa: E402
from main import build_initial_state  # noqa: E402


def _mock_token():
    return {
        "access_token": "tok",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "read:clients",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def _approval(approved: bool) -> ApprovalStatus:
    return ApprovalStatus(
        approved=approved,
        raw_value="true" if approved else "false",
        app_id="test-client-id",
        checked_at=datetime.now(timezone.utc).isoformat(),
        reason="mock",
    )


def _mock_llm(node, system, user):
    return f"mock output for {node}", 0.001


def test_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes, "EVIDENCE_DIR", tmp_path)
    with patch.object(nodes.auth, "get_agent_token", _mock_token), patch.object(
        nodes.lifecycle, "check_agent_approved", lambda: _approval(True)
    ), patch.object(nodes, "_run_llm", _mock_llm), patch.object(
        nodes.logs, "get_run_logs", lambda *a: []
    ):
        final = compiled_graph.invoke(build_initial_state("test topic", False))

    assert nodes.derive_outcome(final) == "COMPLETED"
    assert final["summary"] == "mock output for summariser"
    assert final["total_cost_usd"] > 0
    evidence_files = list(tmp_path.glob("run_*.json"))
    assert len(evidence_files) == 1


def test_rejection_path(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes, "EVIDENCE_DIR", tmp_path)
    with patch.object(nodes.auth, "get_agent_token", _mock_token), patch.object(
        nodes.lifecycle, "check_agent_approved", lambda: _approval(False)
    ):
        final = compiled_graph.invoke(build_initial_state("test topic", False))

    assert nodes.derive_outcome(final) == "REJECTED"
    assert final["research_query"] is None  # pipeline never ran
    data = json.loads(next(tmp_path.glob("run_*.json")).read_text())
    assert data["outcome"] == "REJECTED"


def test_killswitch_path(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes, "EVIDENCE_DIR", tmp_path)
    revoke_calls = []

    def _mock_revoke():
        revoke_calls.append(1)
        return RevokeResult(
            success=True, revoked_at="now", reason="mock revoke", grant_id="g1"
        )

    with patch.object(nodes.killswitch, "revoke_agent_grant", _mock_revoke):
        final = compiled_graph.invoke(build_initial_state("test topic", True))

    assert final["killswitch_fired"] is True
    assert final["error"] == "killswitch_fired"
    assert revoke_calls == [1]
    assert nodes.derive_outcome(final) == "KILLSWITCH"
