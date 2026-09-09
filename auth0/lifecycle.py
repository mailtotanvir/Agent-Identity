"""Approval gate: read client_metadata.security_approved via the Management API."""

import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class ApprovalStatus(BaseModel):
    approved: bool
    raw_value: str
    app_id: str
    checked_at: str
    reason: str


def check_agent_approved() -> ApprovalStatus:
    app_id = os.environ["AUTH0_APP_ID"]
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = httpx.get(
            f"https://{os.environ['AUTH0_DOMAIN']}/api/v2/clients/{app_id}",
            headers={"Authorization": f"Bearer {os.environ['AUTH0_MGMT_TOKEN']}"},
            params={"fields": "client_metadata", "include_fields": "true"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        metadata = resp.json().get("client_metadata") or {}
    except Exception as exc:  # noqa: BLE001 — approval must fail closed
        return ApprovalStatus(
            approved=False,
            raw_value="error",
            app_id=app_id,
            checked_at=checked_at,
            reason=f"Could not verify agent approval status: {exc}",
        )

    if "security_approved" not in metadata:
        return ApprovalStatus(
            approved=False,
            raw_value="missing",
            app_id=app_id,
            checked_at=checked_at,
            reason="Agent has no security_approved metadata — contact your Auth0 admin",
        )

    raw = str(metadata["security_approved"])
    if raw.lower() == "true":
        return ApprovalStatus(
            approved=True,
            raw_value=raw,
            app_id=app_id,
            checked_at=checked_at,
            reason="Agent is approved — security_approved=true in Auth0 metadata",
        )
    return ApprovalStatus(
        approved=False,
        raw_value=raw,
        app_id=app_id,
        checked_at=checked_at,
        reason="Agent is pending approval — set security_approved=true in Auth0 dashboard",
    )


def approval_dashboard_url() -> str:
    tenant = os.environ["AUTH0_DOMAIN"].split(".")[0]
    return (
        f"https://manage.auth0.com/dashboard/us/{tenant}/"
        f"applications/{os.environ['AUTH0_APP_ID']}/settings"
    )
