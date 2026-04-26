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

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings

_COOKIE_NAME = "aether_session"


def get_current_user(request: Request) -> dict | None:
    """Extract authenticated user from session cookie, Bearer token, or internal header."""
    # Internal service calls
    internal_key = request.headers.get("X-Aether-Internal", "")
    if internal_key and settings.SESSION_SECRET:
        if hmac.compare_digest(internal_key, settings.SESSION_SECRET):
            return {"email": "system@aether.internal", "name": "Aether System",
                    "is_admin": True, "_internal": True}

    if not settings.SESSION_SECRET:
        return None

    # Session cookie or Bearer token
    token = request.cookies.get(_COOKIE_NAME, "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        return None

    try:
        sig, raw = token.split(".", 1)
        expected = hmac.new(
            settings.SESSION_SECRET.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(raw)
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


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

    login_url = f"{settings.GATEWAY_URL}/login?next={current_url}"
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        return RedirectResponse(login_url, status_code=302)
    return JSONResponse(status_code=401, content={"detail": "Authentication required"})
