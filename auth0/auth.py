"""OAuth 2.0 Client Credentials token exchange with Auth0 (raw httpx, no SDK)."""

import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()


class Auth0AuthError(Exception):
    """Raised when the Auth0 token endpoint returns a non-200 response."""


def get_agent_token() -> dict:
    """Exchange client credentials for an access token.

    Returns a dict with access_token, token_type, expires_in, scope, issued_at.
    The access_token value is NEVER logged.
    """
    domain = os.environ["AUTH0_DOMAIN"]
    resp = httpx.post(
        f"https://{domain}/oauth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": os.environ["AUTH0_CLIENT_ID"],
            "client_secret": os.environ["AUTH0_CLIENT_SECRET"],
            "audience": os.environ["AUTH0_MGMT_AUDIENCE"],
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise Auth0AuthError(
            f"Auth0 token exchange failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    body = resp.json()
    token = {
        "access_token": body["access_token"],
        "token_type": body.get("token_type", "Bearer"),
        "expires_in": body.get("expires_in", 0),
        "scope": body.get("scope", ""),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    # Log metadata only — never the token itself.
    print(
        f"[auth0] token acquired: type={token['token_type']} "
        f"expires_in={token['expires_in']}s scope='{token['scope'][:80]}'"
    )
    return token
