"""
CRA Tax Helper auth — Aether session cookie / Bearer / internal secret validation.

Shared pattern across all Aether services. Validates HMAC-signed
session tokens against the platform SESSION_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings

logger = logging.getLogger(__name__)

# Audience this service accepts, and the app-specific session cookie name.
AETHER_AUD = "cra-taxhelper"
COOKIE_NAME = "aether_session_cra_taxhelper"
_COOKIE_NAME = COOKIE_NAME


def _derive_app_key(master_secret: str, aud: str) -> bytes:
    """Per-app signing key: HMAC-SHA256(master SESSION_SECRET, 'aether-auth:v2:<aud>')."""
    return hmac.new(
        master_secret.encode(), f"aether-auth:v2:{aud}".encode(), hashlib.sha256
    ).digest()


def _app_signing_key(aud: str = AETHER_AUD) -> bytes | None:
    """Resolve the audience-scoped HMAC key used to verify user session cookies.

    Production supplies ``AETHER_AUTH_SECRET_HEX`` (64 hex chars = 32 bytes),
    which the Gateway computed as
    ``HMAC-SHA256(SESSION_SECRET, "aether-auth:v2:<aud>")`` — so this service
    never needs the master secret to verify user sessions.

    Fails closed (returns ``None``) when the scoped secret is missing or
    malformed. A master-derived fallback is only used when explicitly enabled
    via ``AETHER_ALLOW_MASTER_KEY_FALLBACK`` for tests / local development, and
    is never intended for production.
    """
    hex_secret = (settings.AETHER_AUTH_SECRET_HEX or "").strip()
    if hex_secret:
        try:
            key = bytes.fromhex(hex_secret)
        except ValueError:
            return None
        return key if len(key) == 32 else None

    if settings.AETHER_ALLOW_MASTER_KEY_FALLBACK and settings.SESSION_SECRET:
        return _derive_app_key(settings.SESSION_SECRET, aud)

    return None


def signing_key_configured() -> bool:
    """Whether a usable audience-scoped signing key is available (for startup checks)."""
    return _app_signing_key() is not None


def _verify_v2_token(token: str, aud: str = AETHER_AUD) -> dict | None:
    """Validate a strict Aether auth v2 token for exactly ``aud``.

    Verification uses the audience-scoped key (see :func:`_app_signing_key`);
    the master ``SESSION_SECRET`` is not required. Returns the decoded payload,
    or ``None`` if there is no usable scoped key, or the token is missing,
    malformed, signed with the wrong key, not a v2 token, not a ``session``
    token, addressed to a different audience, missing an identity, or expired.
    During the bounded migration window
    (``AETHER_LEGACY_SESSION_GRACE_UNTIL``), a legacy token that predates the
    ``typ`` claim (typ absent) is still accepted; a present-but-wrong ``typ`` is
    always rejected.
    """
    if not token:
        return None
    key = _app_signing_key(aud)
    if key is None:
        return None
    try:
        sig, raw = token.split(".", 1)
    except ValueError:
        return None

    expected = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    # Strict v2 claims — reject legacy/generic/other-app tokens.
    if data.get("auth_version") != 2:
        return None
    if data.get("aud") != aud:
        return None
    # Explicit token purpose: only browser session tokens are accepted here.
    # A missing typ is tolerated only during the bounded migration window.
    typ = data.get("typ")
    if typ != "session":
        legacy_ok = (
            typ is None
            and time.time() < settings.AETHER_LEGACY_SESSION_GRACE_UNTIL
        )
        if not legacy_ok:
            return None

    identity = str(data.get("email") or data.get("identity") or "").strip()
    if not identity:
        return None
    data.setdefault("email", identity)

    try:
        if float(data.get("exp", 0)) < time.time():
            return None
    except (TypeError, ValueError):
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
    key = _app_signing_key(aud)
    if not token or key is None:
        return False
    ts = str(int(time.time()))
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    signature = hmac.new(
        key, f"{ts}\n{token_digest}".encode(), hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Aether-Audience": aud,
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
    return isinstance(data, dict) and data.get("active") is True


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
    query = urlencode({"next": current_url, "app": AETHER_AUD})
    login_url = f"{settings.GATEWAY_URL}/login?{query}"
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        return RedirectResponse(login_url, status_code=302)
    return JSONResponse(status_code=401, content={"detail": "Authentication required"})
