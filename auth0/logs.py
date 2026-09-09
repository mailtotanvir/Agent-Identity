"""Pull Auth0 audit log events for the current run window."""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

# Event types that matter for the identity story.
# seccft = successful client-credentials exchange (the real-world code;
# the sca/cls codes appear in older docs but seccft is what the tenant emits).
SURFACED_TYPES = {"seccft", "feccft", "sca", "fca", "mgmt_api_read", "cls"}


def _norm(iso: str) -> str:
    """Normalize ISO timestamps so string comparison works ('+00:00' vs 'Z')."""
    return iso.replace("+00:00", "Z")


def get_run_logs(since_iso: str, until_iso: str) -> list[dict]:
    """Return Auth0 log events for this client within [since_iso, until_iso].

    On any failure returns [] — audit retrieval must never break the run.
    """
    try:
        resp = httpx.get(
            f"https://{os.environ['AUTH0_DOMAIN']}/api/v2/logs",
            headers={"Authorization": f"Bearer {os.environ['AUTH0_MGMT_TOKEN']}"},
            params={"q": f"client_id:{os.environ['AUTH0_CLIENT_ID']}", "take": 50},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[auth0] WARN: logs API returned HTTP {resp.status_code}")
            return []
        events = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[auth0] WARN: logs API failed: {exc}")
        return []

    return [
        e
        for e in events
        if e.get("type") in SURFACED_TYPES
        and _norm(since_iso) <= _norm(e.get("date", "")) <= _norm(until_iso)
    ]
