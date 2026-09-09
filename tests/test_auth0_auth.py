import os

import httpx
import pytest

os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")
os.environ.setdefault("AUTH0_APP_ID", "test-client-id")
os.environ.setdefault("AUTH0_CLIENT_SECRET", "test-secret")
os.environ.setdefault("AUTH0_MGMT_AUDIENCE", "https://test.auth0.com/api/v2/")
os.environ.setdefault("AUTH0_MGMT_TOKEN", "test-mgmt-token")

from auth0.auth import Auth0AuthError, get_agent_token  # noqa: E402


def _response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code, json=body, request=httpx.Request("POST", "https://x")
    )


def test_token_success(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _response(
            200,
            {
                "access_token": "SECRET-TOKEN-VALUE",
                "token_type": "Bearer",
                "expires_in": 86400,
                "scope": "read:clients",
            },
        ),
    )
    token = get_agent_token()
    assert token["access_token"] == "SECRET-TOKEN-VALUE"
    assert token["token_type"] == "Bearer"
    assert token["expires_in"] == 86400
    assert token["scope"] == "read:clients"
    assert "issued_at" in token


def test_token_failure_raises(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _response(401, {"error": "access_denied"})
    )
    with pytest.raises(Auth0AuthError):
        get_agent_token()


def test_token_value_never_printed(monkeypatch, capsys):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _response(
            200,
            {
                "access_token": "SUPER-SECRET-DO-NOT-LOG",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read:clients",
            },
        ),
    )
    get_agent_token()
    out = capsys.readouterr().out
    assert "SUPER-SECRET-DO-NOT-LOG" not in out
