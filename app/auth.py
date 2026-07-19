"""
CRA Tax Helper auth — Aether session cookie / Bearer / internal secret validation.

Shared pattern across all Aether services. Validates HMAC-signed
session tokens against the platform SESSION_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings

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
    malformed, signed with the wrong key, not a v2 token, addressed to a
    different audience, missing an identity, or expired.
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
