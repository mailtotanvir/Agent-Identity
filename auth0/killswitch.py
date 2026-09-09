"""Suspicious-behaviour detection and client-grant revocation (kill switch).

Revocation is DRY-RUN by default (KILLSWITCH_DRY_RUN=true): the grant is
located but not deleted, so the demo tenant is never left broken. Set
KILLSWITCH_DRY_RUN=false to make the DELETE + metadata PATCH real.
"""

import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

SUSPICIOUS_THRESHOLD = 10


class RevokeResult(BaseModel):
    success: bool
    revoked_at: str
    reason: str
    grant_id: Optional[str] = None


def check_suspicious(token_request_count: int, window_seconds: int) -> bool:
    return token_request_count > SUSPICIOUS_THRESHOLD and window_seconds <= 60


def _dry_run() -> bool:
    return os.environ.get("KILLSWITCH_DRY_RUN", "true").lower() != "false"


def revoke_agent_grant() -> RevokeResult:
    domain = os.environ["AUTH0_DOMAIN"]
    client_id = os.environ["AUTH0_CLIENT_ID"]
    headers = {"Authorization": f"Bearer {os.environ['AUTH0_MGMT_TOKEN']}"}
    now = datetime.now(timezone.utc).isoformat()

    try:
        resp = httpx.get(
            f"https://{domain}/api/v2/client-grants",
            headers=headers,
            params={"client_id": client_id},
            timeout=30,
        )
        grants = resp.json() if resp.status_code == 200 else []
        grant_id = grants[0]["id"] if grants else None
    except Exception as exc:  # noqa: BLE001
        return RevokeResult(
            success=False, revoked_at=now, reason=f"Grant lookup failed: {exc}"
        )

    if grant_id is None:
        return RevokeResult(
            success=False, revoked_at=now, reason="No client grant found to revoke"
        )

    if _dry_run():
        return RevokeResult(
            success=True,
            revoked_at=now,
            reason="DRY RUN — grant identified but not deleted (KILLSWITCH_DRY_RUN=true)",
            grant_id=grant_id,
        )

    try:
        del_resp = httpx.delete(
            f"https://{domain}/api/v2/client-grants/{grant_id}",
            headers=headers,
            timeout=30,
        )
        if del_resp.status_code not in (200, 204):
            return RevokeResult(
                success=False,
                revoked_at=now,
                reason=f"Grant delete failed: HTTP {del_resp.status_code}",
                grant_id=grant_id,
            )
        # Also flip the approval flag so the gate blocks future runs.
        httpx.patch(
            f"https://{domain}/api/v2/clients/{os.environ['AUTH0_APP_ID']}",
            headers=headers,
            json={"client_metadata": {"security_approved": "false"}},
            timeout=30,
        )
        return RevokeResult(
            success=True,
            revoked_at=now,
            reason="Client grant revoked and security_approved set to false",
            grant_id=grant_id,
        )
    except Exception as exc:  # noqa: BLE001
        return RevokeResult(
            success=False,
            revoked_at=now,
            reason=f"Revocation failed: {exc}",
            grant_id=grant_id,
        )
