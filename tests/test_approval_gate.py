import os

import httpx

os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")
os.environ.setdefault("AUTH0_APP_ID", "test-client-id")
os.environ.setdefault("AUTH0_MGMT_TOKEN", "test-mgmt-token")

from auth0.lifecycle import check_agent_approved  # noqa: E402


def _response(status_code: int, body) -> httpx.Response:
    return httpx.Response(
        status_code, json=body, request=httpx.Request("GET", "https://x")
    )


def test_approved_true(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _response(200, {"client_metadata": {"security_approved": "true"}}),
    )
    status = check_agent_approved()
    assert status.approved is True
    assert status.raw_value == "true"
    assert "approved" in status.reason


def test_approved_false(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _response(200, {"client_metadata": {"security_approved": "false"}}),
    )
    status = check_agent_approved()
    assert status.approved is False
    assert status.raw_value == "false"
    assert "pending approval" in status.reason


def test_metadata_key_missing(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _response(200, {"client_metadata": {}})
    )
    status = check_agent_approved()
    assert status.approved is False
    assert status.raw_value == "missing"
    assert "no security_approved metadata" in status.reason


def test_api_error_fails_closed(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _response(500, {"error": "boom"})
    )
    status = check_agent_approved()
    assert status.approved is False
    assert "Could not verify" in status.reason
