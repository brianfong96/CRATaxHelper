"""
CRA Tax Helper auth — Aether session cookie / Bearer / internal secret validation.

Hosted sessions accept the transitional static and rotating Aether v2 formats.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import time
from urllib.parse import urlencode

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth_rotation import (
    AUTH_VERSION,
    decode_signing_key,
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


def _configured_keys(
    *, now: float | None = None, require_current_period: bool = False
) -> dict[int | None, bytes] | None:
    """Load the static key and an optional complete rotating keyring."""
    static_key = decode_signing_key(settings.AETHER_AUTH_SECRET_HEX)
    if static_key is None:
        return None
    rotating_values = (
        settings.AETHER_AUTH_PREVIOUS_KEY_ID,
        settings.AETHER_AUTH_PREVIOUS_SECRET_HEX,
        settings.AETHER_AUTH_KEY_ID,
        settings.AETHER_AUTH_ROTATING_SECRET_HEX,
        settings.AETHER_AUTH_NEXT_KEY_ID,
        settings.AETHER_AUTH_NEXT_SECRET_HEX,
    )
    if not any(rotating_values):
        return {None: static_key}
    rotating = load_required_keyring(
        (
            settings.AETHER_AUTH_PREVIOUS_KEY_ID,
            settings.AETHER_AUTH_PREVIOUS_SECRET_HEX,
        ),
        (
            settings.AETHER_AUTH_KEY_ID,
            settings.AETHER_AUTH_ROTATING_SECRET_HEX,
        ),
        (settings.AETHER_AUTH_NEXT_KEY_ID, settings.AETHER_AUTH_NEXT_SECRET_HEX),
        now=now,
        require_current_period=require_current_period,
    )
    if rotating is None:
        return None
    return {None: static_key, **rotating}


def signing_key_configured() -> bool:
    """Whether static auth and any configured rotating keyring are usable."""
    return _configured_keys(require_current_period=True) is not None


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
    keys = _configured_keys()
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

    has_key_id = "kid" in data
    has_issued_at = "iat" in data
    if has_key_id != has_issued_at:
        return None
    key_id = data.get("kid") if has_key_id else None
    if has_key_id:
        if (
            isinstance(key_id, bool)
            or not isinstance(key_id, int)
            or not token_window_valid(
                data, now=verification_time, expected_key_id=key_id
            )
        ):
            return None
    else:
        expires_at = data.get("exp")
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
            or not math.isfinite(float(expires_at))
            or expires_at <= verification_time
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
    keys = _configured_keys()
    if keys is None:
        return False
    try:
        _sig, raw = token.split(".", 1)
        claims = json.loads(raw)
    except (ValueError, TypeError, AttributeError):
        return False
    if not isinstance(claims, dict):
        return False
    has_key_id = "kid" in claims
    has_issued_at = "iat" in claims
    if has_key_id != has_issued_at:
        return False
    key_id = claims.get("kid") if has_key_id else None
    if has_key_id and (
        isinstance(key_id, bool) or not isinstance(key_id, int)
    ):
        return False
    key = keys.get(key_id)
    if key is None:
        return False
    ts = str(int(time.time()))
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    signature = hmac.new(
        key, f"{ts}\n{token_digest}".encode(), hashlib.sha256
    ).hexdigest()
    headers: dict[str, str] = {
        "X-Aether-Audience": aud,
        "X-Aether-Timestamp": ts,
        "X-Aether-Introspection": signature,
    }
    if key_id is not None:
        headers["X-Aether-Key-Id"] = str(key_id)
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
    query = urlencode({"app": AETHER_AUD, "next": current_url})
    login_url = f"https://api.{settings.DOMAIN}/login?{query}"
    accepted_types = {
        item.split(";", 1)[0].strip()
        for item in request.headers.get("Accept", "").lower().split(",")
    }
    is_api_route = (
        path == "/api"
        or path.startswith("/api/")
        or path == "/admin/forms-status"
        or path.startswith("/admin/list-fields/")
    )
    accepts_json = any(
        item == "application/json"
        or (item.startswith("application/") and item.endswith("+json"))
        for item in accepted_types
    )
    accepts_html = "text/html" in accepted_types or (
        "*/*" in accepted_types and not accepts_json
    )
    if request.method in {"GET", "HEAD"} and not is_api_route and accepts_html:
        return RedirectResponse(login_url, status_code=302)
    return JSONResponse(status_code=401, content={"detail": "Authentication required"})
