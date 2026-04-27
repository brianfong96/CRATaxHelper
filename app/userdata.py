"""CRA Tax Helper — Archive-backed per-user form data persistence.

Uses the Aether Archive internal service to store T1 and BC428 form data
per user with row-level security (RLS).  All user-data operations use the
user's own Aether session cookie so Archive can enforce ownership.  Admin
operations (project/table/role setup) use the internal service token.

If Archive is unreachable, every function silently no-ops — the app
continues to work using localStorage only.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.crypto import decrypt_blob, encrypt_blob

logger = logging.getLogger("taxhelper.userdata")

_PROJECT = "cra-taxhelper"
_TABLE   = "form_saves"


def _base() -> str:
    return f"{settings.ARCHIVE_URL}/api/v1"


def _sys_hdrs() -> dict[str, str]:
    """Internal-service auth header — grants system-level access to Archive."""
    return {"X-Aether-Internal": settings.SESSION_SECRET}


def _cookie_hdrs(cookie: str) -> dict[str, str]:
    if cookie:
        return {"Cookie": f"aether_session={cookie}"}
    # Local mode (AUTH_ENABLED=false): pass the synthetic user as a header.
    # The local Archive sidecar trusts this without validation.
    from app.config import settings  # imported here to avoid circular import at module level
    if not settings.AUTH_ENABLED and settings.LOCAL_USER_EMAIL:
        return {"X-Local-User": settings.LOCAL_USER_EMAIL}
    return {}


# ── Startup initialisation ────────────────────────────────────────────────────

async def ensure_archive_project() -> None:
    """Idempotently create the Archive project, table, and RLS policy on startup.

    Safe to call repeatedly — every step checks for prior existence.
    Errors are logged and swallowed so the app starts even if Archive is down.
    """
    if not settings.ARCHIVE_URL or not settings.SESSION_SECRET:
        logger.info("Archive not configured — using localStorage only")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # ── 1. Ensure project exists ─────────────────────────────────────
            r = await client.get(f"{_base()}/projects", headers=_sys_hdrs())
            if r.status_code != 200:
                logger.warning("Archive unavailable (GET /projects → %s)", r.status_code)
                return

            if _PROJECT not in {p["name"] for p in r.json()}:
                r = await client.post(
                    f"{_base()}/projects",
                    headers=_sys_hdrs(),
                    json={
                        "name": _PROJECT,
                        "display_name": "CRA Tax Helper",
                        "description": "Per-user T1 and BC428 form saves",
                    },
                )
                if r.status_code not in (200, 201, 409):
                    logger.error("Failed to create Archive project: %s", r.text)
                    return
                logger.info("Created Archive project '%s'", _PROJECT)

            # ── 2. Ensure form_saves table exists ────────────────────────────
            r = await client.get(f"{_base()}/{_PROJECT}/tables", headers=_sys_hdrs())
            tables_resp = r.json() if r.status_code == 200 else {}
            existing = {
                t["name"] if isinstance(t, dict) else t
                for t in tables_resp.get("tables", [])
            }

            if _TABLE not in existing:
                r = await client.post(
                    f"{_base()}/{_PROJECT}/tables",
                    headers=_sys_hdrs(),
                    json={
                        "name": _TABLE,
                        "columns": [
                            {"name": "owner_email", "type": "text", "required": True},
                            {"name": "form_name",   "type": "text", "required": True},
                            {"name": "form_data",   "type": "text"},   # JSON string
                            {"name": "saved_at",    "type": "text"},   # ISO-8601 timestamp
                        ],
                    },
                )
                if r.status_code not in (200, 201, 409):
                    logger.error("Failed to create '%s' table: %s", _TABLE, r.text)
                    return
                logger.info("Created '%s' table in Archive project '%s'", _TABLE, _PROJECT)

                # ── 3. Set RLS policy (owner_email column, private visibility) ─
                r = await client.post(
                    f"{_base()}/projects/{_PROJECT}/rls",
                    headers=_sys_hdrs(),
                    json={
                        "table_name": _TABLE,
                        "user_column": "owner_email",
                        "visibility": "private",
                    },
                )
                if r.status_code not in (200, 201, 204):
                    logger.warning("RLS policy setup failed on %s: %s", _TABLE, r.text)
                else:
                    logger.info("RLS policy set: %s.%s private by owner_email", _PROJECT, _TABLE)

    except Exception as exc:
        logger.warning("Archive project setup failed (non-fatal): %s", exc)


# ── Per-user role management ──────────────────────────────────────────────────

# In-memory cache: emails already granted access this process lifetime.
_granted_emails: set[str] = set()


async def grant_user_access(email: str) -> None:
    """Grant rls-editor on the cra-taxhelper project to *email* (idempotent)."""
    if email in _granted_emails:
        return
    if not settings.ARCHIVE_URL or not settings.SESSION_SECRET:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"{_base()}/projects/{_PROJECT}/roles",
                headers=_sys_hdrs(),
                json={"email": email, "role": "rls-editor"},
            )
            if r.status_code in (200, 201, 409):
                _granted_emails.add(email)
                logger.debug("rls-editor granted to %s on '%s'", email, _PROJECT)
            else:
                logger.warning(
                    "Role grant failed for %s → %s: %s", email, r.status_code, r.text
                )
    except Exception as exc:
        logger.debug("Archive role grant skipped for %s (non-fatal): %s", email, exc)


# ── Data CRUD ─────────────────────────────────────────────────────────────────

async def get_form_data(session_cookie: str, form_name: str) -> dict[str, Any] | None:
    """Return the user's saved form data for *form_name*, or None if not found."""
    from app.config import settings
    local_mode = not settings.AUTH_ENABLED and bool(settings.LOCAL_USER_EMAIL)
    if not settings.ARCHIVE_URL:
        return None
    if not session_cookie and not local_mode:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{_base()}/{_PROJECT}/{_TABLE}",
                headers=_cookie_hdrs(session_cookie),
                params={"limit": 10, "order_by": "id", "order": "desc"},
            )
            if r.status_code != 200:
                logger.debug("Archive GET %s → %s", _TABLE, r.status_code)
                return None
            for row in r.json().get("rows", []):
                if row.get("form_name") == form_name:
                    raw = row.get("form_data", "")
                    try:
                        decrypted = decrypt_blob(raw) if isinstance(raw, str) else ""
                        return json.loads(decrypted) if decrypted else (raw or {})
                    except Exception:
                        return {}
    except Exception as exc:
        logger.debug("get_form_data error: %s", exc)
    return None


async def save_form_data(
    session_cookie: str,
    email: str,
    form_name: str,
    data: dict,
) -> bool:
    """Upsert the user's form data in Archive. Returns True on success."""
    from app.config import settings
    local_mode = not settings.AUTH_ENABLED and bool(settings.LOCAL_USER_EMAIL)
    if not settings.ARCHIVE_URL:
        return False
    if not session_cookie and not local_mode:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            # Find the existing row ID (RLS limits results to this user's rows)
            r = await client.get(
                f"{_base()}/{_PROJECT}/{_TABLE}",
                headers=_cookie_hdrs(session_cookie),
                params={"limit": 10, "order_by": "id"},
            )
            existing_id: int | None = None
            if r.status_code == 200:
                for row in r.json().get("rows", []):
                    if row.get("form_name") == form_name:
                        existing_id = row.get("id")
                        break

            payload = {
                "owner_email": email,
                "form_name":   form_name,
                "form_data":   encrypt_blob(json.dumps(data)),
                "saved_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

            if existing_id:
                r = await client.patch(
                    f"{_base()}/{_PROJECT}/{_TABLE}/{existing_id}",
                    headers=_cookie_hdrs(session_cookie),
                    json={"data": payload},
                )
            else:
                r = await client.post(
                    f"{_base()}/{_PROJECT}/{_TABLE}",
                    headers=_cookie_hdrs(session_cookie),
                    json={"data": payload},
                )

            ok = r.status_code in (200, 201)
            if not ok:
                logger.debug(
                    "save_form_data %s/%s → %s: %s",
                    email, form_name, r.status_code, r.text[:200],
                )
            return ok
    except Exception as exc:
        logger.debug("save_form_data error: %s", exc)
    return False
