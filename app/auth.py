"""
CRA Tax Helper auth — Aether session cookie / Bearer / internal secret validation.

Hosted sessions use a mandatory previous/current/next audience keyring.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from urllib.parse import urlencode

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth_rotation import (
    AUTH_VERSION,
    load_required_keyring,
    token_window_valid,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Audience this service accepts, and the app-specific session cookie name.
AETHER_AUD = "cra-taxhelper"
COOKIE_NAME = "aether_session_cra_taxhelper"
_COOKIE_NAME = COOKIE_NAME
_MAX_TOKEN_BYTES = 4096
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")


def _app_keyring(
    *, now: float | None = None, require_current_period: bool = False
) -> dict[str, bytes] | None:
    """Load the complete deployment keyring without any static fallback."""
    return load_required_keyring(
        (
            settings.AETHER_AUTH_PREVIOUS_KEY_ID,
            settings.AETHER_AUTH_PREVIOUS_SECRET_HEX,
        ),
        (settings.AETHER_AUTH_KEY_ID, settings.AETHER_AUTH_SECRET_HEX),
        (settings.AETHER_AUTH_NEXT_KEY_ID, settings.AETHER_AUTH_NEXT_SECRET_HEX),
        now=now,
        require_current_period=require_current_period,
    )


def signing_key_configured() -> bool:
    """Whether a complete consecutive rotating keyring is configured."""
    return _app_keyring(require_current_period=True) is not None


def _verify_v2_token(
    token: str, aud: str = AETHER_AUD, *, now: float | None = None
) -> dict | None:
    """Validate a strict, period-bound Aether session for this exact audience."""
    if (
        not isinstance(token, str)
        or not token
        or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES
        or aud != AETHER_AUD
    ):
        return None
    verification_time = time.time() if now is None else now
    keys = _app_keyring()
    if keys is None:
        return None
    try:
        sig, raw = token.split(".", 1)
    except ValueError:
        return None
    if not _SIGNATURE_RE.fullmatch(sig):
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    canonical_raw = json.dumps(data, separators=(",", ":"), sort_keys=True)
    if raw != canonical_raw:
        return None

    key_id = data.get("kid")
    if not isinstance(key_id, str) or not token_window_valid(
        data, now=verification_time, expected_key_id=key_id
    ):
        return None
    key = keys.get(key_id)
    if key is None:
        return None
    expected = hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None

    version = data.get("auth_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != AUTH_VERSION
    ):
        return None
    if data.get("aud") != aud:
        return None
    if data.get("typ") != "session":
        return None
    if not isinstance(data.get("email"), str) or not data["email"].strip():
        return None
    return data


def get_current_user(request: Request) -> dict | None:
    """Extract authenticated user from session cookie, Bearer token, or internal header."""
    # Internal service calls
    internal_key = request.headers.get("X-Aether-Internal", "")
    if internal_key and settings.SESSION_SECRET:
        if hmac.compare_digest(internal_key, settings.SESSION_SECRET):
            return {"email": "system@aether.internal", "name": "Aether System",
                    "is_admin": True, "_internal": True}

    # Session cookie or Bearer token
    token = request.cookies.get(_COOKIE_NAME, "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        return None

    return _verify_v2_token(token, AETHER_AUD)


# ── Live session introspection (immediate revocation) ─────────────────────────

# Tight timeout so a slow/unreachable Gateway cannot hang a request; we fail
# closed instead.
_INTROSPECT_TIMEOUT = 2.5


def _extract_token(request: Request) -> str:
    """Return the raw session token from the app cookie or bearer header."""
    token = request.cookies.get(_COOKIE_NAME, "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    return token


async def session_is_active(token: str, aud: str = AETHER_AUD) -> bool:
    """Confirm with the Gateway that ``token`` is still an active session.

    Performed after local cryptographic validation succeeds. Calls
    ``POST {GATEWAY_URL}/auth/session/introspect`` with ``{token, aud}`` and the
    signed introspection headers, keyed by the raw audience-scoped signing key
    (never the master secret). Fails closed (returns ``False``) on any
    inactive/malformed/timeout/unavailable condition. Never logs token material.
    """
    if aud != AETHER_AUD or not isinstance(token, str) or not token:
        return False
    keys = _app_keyring()
    if keys is None:
        return False
    try:
        _sig, raw = token.split(".", 1)
        claims = json.loads(raw)
    except (ValueError, TypeError, AttributeError):
        return False
    key_id = claims.get("kid") if isinstance(claims, dict) else None
    key = keys.get(key_id) if isinstance(key_id, str) else None
    if key is None:
        return False
    ts = str(int(time.time()))
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    signature = hmac.new(
        key, f"{ts}\n{token_digest}".encode(), hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Aether-Audience": aud,
        "X-Aether-Key-Id": key_id,
        "X-Aether-Timestamp": ts,
        "X-Aether-Introspection": signature,
    }
    url = f"{settings.GATEWAY_URL.rstrip('/')}/auth/session/introspect"
    try:
        async with httpx.AsyncClient(timeout=_INTROSPECT_TIMEOUT) as client:
            resp = await client.post(
                url, json={"token": token, "aud": aud}, headers=headers
            )
        if resp.status_code != 200:
            logger.warning(
                "Session introspection returned HTTP %s", resp.status_code
            )
            return False
        data = resp.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Session introspection unavailable: %s", type(exc).__name__)
        return False
    return data == {"active": True}


def require_auth_response(request: Request) -> RedirectResponse | JSONResponse:
    """Return appropriate 401 response — redirect browsers to Aether login."""
    # Build the full public URL using forwarded headers (set by Caddy/Cloudflare)
    host = (request.headers.get("X-Forwarded-Host")
            or request.headers.get("Host")
            or "localhost")
    proto = request.headers.get("X-Forwarded-Proto", "https")
    path = request.url.path
    qs = f"?{request.url.query}" if request.url.query else ""
    root = settings.ROOT_PATH.rstrip("/")
    current_url = f"{proto}://{host}{root}{path}{qs}"

    # Pass the exact app audience and the public return URL to the Gateway login.
    # Always target the PUBLIC api.<DOMAIN> host here — never settings.GATEWAY_URL,
    # which production sets to the internal http://gateway:8000 address for
    # server-to-server introspection only; a user's browser can never resolve it.
    query = urlencode({"next": current_url, "app": AETHER_AUD})
    login_url = f"https://api.{settings.DOMAIN}/login?{query}"
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        return RedirectResponse(login_url, status_code=302)
    return JSONResponse(status_code=401, content={"detail": "Authentication required"})
