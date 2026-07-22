"""
Security tests for CRA Tax Helper.

Validates:
- Auth middleware enforcement (redirect/401 when no valid session)
- HMAC token validation (wrong secret, tampered payload, expired token)
- Per-app RBAC (ALLOWED_EMAILS enforcement)
- Input validation (unknown forms, malformed JSON)
- Sensitive data protection (no PII in error bodies)
- Encryption round-trip for stored form data
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.auth import (
    AETHER_AUD,
    _derive_app_key,
    _verify_v2_token,
    session_is_active,
    signing_key_configured,
)
from app.auth_rotation import (
    AUTH_CLOCK_SKEW_SECONDS,
    AUTH_KEY_ROTATION_SECONDS,
    AUTH_TOKEN_MAX_AGE_SECONDS,
    key_id_at,
)

_COOKIE = "aether_session_cra_taxhelper"


# ── Token helpers ─────────────────────────────────────────────────────────────

def _make_token(
    secret: str,
    email: str,
    exp_offset: int = 3600,
    *,
    aud: str = AETHER_AUD,
    auth_version: int = 2,
    is_admin: bool = False,
    typ: str | None = "session",
    issued_at: float | None = None,
    kid: str | None = None,
    signing_kid: str | None = None,
) -> str:
    """Create a strict rotating Aether auth v2 token."""
    issued = time.time() if issued_at is None else issued_at
    token_kid = key_id_at(issued) if kid is None else kid
    claims = {
        "auth_version": auth_version,
        "aud": aud,
        "email": email, "name": "Test User",
        "is_admin": is_admin,
        "kid": token_kid,
        "iat": issued,
        "exp": issued + exp_offset,
    }
    if typ is not None:
        claims["typ"] = typ
    payload = json.dumps(claims)
    key = _derive_app_key(secret, aud, signing_kid or token_kid)
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{sig}.{payload}"


def _make_v1_token(secret: str, email: str, exp_offset: int = 3600) -> str:
    """Create a legacy v1 token signed directly with the master secret."""
    payload = json.dumps({
        "email": email, "name": "Test User",
        "exp": time.time() + exp_offset,
    })
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{sig}.{payload}"


def _tamper_token(token: str) -> str:
    """Flip one char in the payload to invalidate the HMAC."""
    sig, raw = token.split(".", 1)
    raw_list = list(raw)
    raw_list[-5] = "X" if raw_list[-5] != "X" else "Y"
    return f"{sig}.{''.join(raw_list)}"


def _sign_claims(claims: dict, *, signing_kid: str | None = None) -> str:
    raw = json.dumps(claims, separators=(",", ":"), sort_keys=True)
    kid = signing_kid or str(claims["kid"])
    key = _derive_app_key(_SECRET, AETHER_AUD, kid)
    signature = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()
    return f"{signature}.{raw}"


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SECRET = "test-secret-for-security-tests"


def _scoped_hex(
    secret: str = _SECRET, aud: str = AETHER_AUD, kid: str | None = None
) -> str:
    """Return one audience/period key as deployment-ready hex."""
    return _derive_app_key(secret, aud, kid or key_id_at()).hex()


def _set_keyring(monkeypatch, *, current_kid: str | None = None) -> None:
    import app.config as cfg

    current = int(current_kid or key_id_at())
    values = {
        "AETHER_AUTH_PREVIOUS_KEY_ID": str(current - 1),
        "AETHER_AUTH_PREVIOUS_SECRET_HEX": _scoped_hex(kid=str(current - 1)),
        "AETHER_AUTH_KEY_ID": str(current),
        "AETHER_AUTH_SECRET_HEX": _scoped_hex(kid=str(current)),
        "AETHER_AUTH_NEXT_KEY_ID": str(current + 1),
        "AETHER_AUTH_NEXT_SECRET_HEX": _scoped_hex(kid=str(current + 1)),
    }
    for name, value in values.items():
        monkeypatch.setattr(cfg.settings, name, value)


async def _introspect_ok(*_args, **_kwargs):
    """Stand-in for session_is_active that reports the session is active."""
    return True


async def _introspect_revoked(*_args, **_kwargs):
    """Stand-in for session_is_active that reports the session is inactive."""
    return False


@pytest.fixture(autouse=True)
def _rotating_keyring(monkeypatch):
    """Install a production-shaped keyring and isolate live introspection."""
    import app.main as main_mod

    _set_keyring(monkeypatch)
    monkeypatch.setattr(main_mod, "session_is_active", _introspect_ok)


@pytest_asyncio.fixture
async def auth_client(monkeypatch):
    """Client against app with AUTH_ENABLED=True and a known SESSION_SECRET."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def authed_client(monkeypatch):
    """Client with a valid session cookie for allowed@test.com."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    token = _make_token(_SECRET, "allowed@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"aether_session_cra_taxhelper": token},
    ) as ac:
        yield ac


# ── Auth enforcement ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_required_for_form_pages(auth_client):
    """All form pages must redirect/401 when no session is present."""
    for path in ["/tax/t1", "/tax/bc428", "/tax/schedule9", "/", "/profile"]:
        r = await auth_client.get(path, follow_redirects=False)
        assert r.status_code in (302, 401, 403), \
            f"{path} returned {r.status_code} — should require auth"


@pytest.mark.asyncio
async def test_health_endpoint_bypasses_auth(auth_client):
    """Health check must be public (no auth required)."""
    r = await auth_client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_valid_session_grants_access(authed_client):
    r = await authed_client.get("/tax/t1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_redirect_includes_login_url(auth_client):
    """Browser redirect must point to Aether login."""
    r = await auth_client.get("/tax/t1", headers={"Accept": "text/html"},
                               follow_redirects=False)
    assert r.status_code == 302
    assert "login" in r.headers.get("location", "").lower()


@pytest.mark.asyncio
async def test_api_without_accept_html_returns_401(auth_client):
    """API clients (no Accept: text/html) must get JSON 401, not a redirect."""
    r = await auth_client.get("/tax/t1", headers={"Accept": "application/json"},
                               follow_redirects=False)
    assert r.status_code == 401


# ── Token validation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tampered_token_rejected(monkeypatch):
    """Modifying the token payload must invalidate the HMAC and return 302/401."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    token = _make_token(_SECRET, "user@test.com")
    bad_token = _tamper_token(token)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": bad_token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_expired_token_rejected(monkeypatch):
    """Expired tokens (exp in the past) must be rejected."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    expired_token = _make_token(_SECRET, "user@test.com", exp_offset=-1)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": expired_token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_wrong_secret_rejected(monkeypatch):
    """Token signed with a different secret must be rejected."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    wrong_token = _make_token("completely-different-secret", "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": wrong_token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_bearer_token_accepted(monkeypatch):
    """Valid Bearer token in Authorization header must also grant access."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    token = _make_token(_SECRET, "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_internal_header_grants_system_access(monkeypatch):
    """X-Aether-Internal header with correct secret must grant system access."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"X-Aether-Internal": _SECRET},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_wrong_internal_header_rejected(monkeypatch):
    """Wrong X-Aether-Internal value must not grant access."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"X-Aether-Internal": "wrong-secret"},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


# ── RBAC / ALLOWED_EMAILS ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_allowed_emails_blocks_unlisted_user(monkeypatch):
    """User not in ALLOWED_EMAILS must see 403 Forbidden."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "only@allowed.com")
    token = _make_token(_SECRET, "other@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_allowed_emails_permits_listed_user(monkeypatch):
    """User in ALLOWED_EMAILS must get through."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "allowed@test.com,other@test.com")
    token = _make_token(_SECRET, "allowed@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_allowed_emails_case_insensitive(monkeypatch):
    """ALLOWED_EMAILS comparison must be case-insensitive."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "Allowed@Test.COM")
    token = _make_token(_SECRET, "allowed@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


# ── Audience isolation (auth v2) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_for_other_app_rejected(monkeypatch):
    """A v2 token minted for a different app (aud) must be rejected."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    for other_aud in ("stockanalysis", "spellblades", "psyquora", "generic"):
        token = _make_token(_SECRET, "user@test.com", aud=other_aud)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            cookies={_COOKIE: token},
        ) as ac:
            r = await ac.get("/tax/t1", follow_redirects=False)
        assert r.status_code in (302, 401, 403), \
            f"aud={other_aud} token was accepted (status {r.status_code})"


@pytest.mark.asyncio
async def test_correct_audience_token_accepted(monkeypatch):
    """A v2 token with the exact cra-taxhelper audience must be accepted."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    token = _make_token(_SECRET, "user@test.com", aud="cra-taxhelper")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_legacy_v1_token_rejected(monkeypatch):
    """Legacy v1 tokens (no auth_version/aud, signed with master secret) must be rejected."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    token = _make_v1_token(_SECRET, "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_wrong_auth_version_rejected(monkeypatch):
    """A token with the right aud but auth_version != 2 must be rejected."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    token = _make_token(_SECRET, "user@test.com", auth_version=1)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_is_admin_flag_does_not_bypass_allowlist(monkeypatch):
    """A valid token with is_admin=True must NOT bypass ALLOWED_EMAILS."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "only@allowed.com")
    token = _make_token(_SECRET, "intruder@test.com", is_admin=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_login_redirect_includes_app_param(auth_client):
    """The login redirect must pass the exact app audience so the Gateway mints a v2 token."""
    r = await auth_client.get("/tax/t1", headers={"Accept": "text/html"},
                              follow_redirects=False)
    assert r.status_code == 302
    location = r.headers.get("location", "")
    assert "app=cra-taxhelper" in location


# ── Scoped signing key (AETHER_AUTH_SECRET_HEX) ───────────────────────────────

@pytest.mark.asyncio
async def test_hex_secret_verifies_without_master(monkeypatch):
    """Production path: a valid session verifies using only AETHER_AUTH_SECRET_HEX (no master)."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "")            # no master secret
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    token = _make_token(_SECRET, "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_enabled_without_any_secret_fails_closed(monkeypatch):
    """AUTH_ENABLED=true with NO signing key must fail closed — never run open.

    Regression: previously the middleware bypassed auth when both secrets were
    missing. Now only an explicit AUTH_ENABLED=false opens local mode; with auth
    enabled and no usable key, every protected route must deny access and must
    NOT inject the synthetic local user.
    """
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "")
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    for path in ("/tax/t1", "/", "/profile"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.get(path, follow_redirects=False)
        assert r.status_code in (302, 401, 403), \
            f"{path} ran open with no signing key (status {r.status_code})"


@pytest.mark.asyncio
async def test_missing_scoped_secret_fails_closed(monkeypatch):
    """Auth enabled with a master secret but no scoped hex (fallback off) must reject users."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    token = _make_token(_SECRET, "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_malformed_scoped_secret_fails_closed(monkeypatch):
    """A malformed AETHER_AUTH_SECRET_HEX must fail closed, never fall back to the master."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "not-hex-zz")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)
    token = _make_token(_SECRET, "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_wrong_length_scoped_secret_fails_closed(monkeypatch):
    """A hex secret that is not 32 bytes must fail closed."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "abcd")  # 2 bytes
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    token = _make_token(_SECRET, "user@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1", follow_redirects=False)
    assert r.status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_master_fallback_never_authenticates_sessions(monkeypatch):
    """The archive compatibility flag must never enable a user-session fallback."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    token = _make_token(_SECRET, "user@test.com")

    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        assert (await ac.get("/tax/t1", follow_redirects=False)).status_code in (302, 401, 403)


@pytest.mark.asyncio
async def test_internal_header_works_without_scoped_secret(monkeypatch):
    """X-Aether-Internal machine calls keep working via SESSION_SECRET even with no scoped key."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"X-Aether-Internal": _SECRET},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_startup_fails_fast_without_signing_key(monkeypatch):
    """Lifespan must raise at startup when auth is on but no usable key is set."""
    import app.config as cfg
    from app.main import _lifespan
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "")
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    with pytest.raises(RuntimeError):
        async with _lifespan(app):
            pass


@pytest.mark.asyncio
async def test_startup_ok_with_scoped_hex(monkeypatch):
    """Lifespan must start cleanly when a valid scoped hex key is configured."""
    import app.config as cfg
    from app.main import _lifespan
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "")
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    monkeypatch.setattr(cfg.settings, "ARCHIVE_URL", "")  # skip Archive init task
    async with _lifespan(app):
        pass


# ── Input validation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_userdata_rejects_unknown_form():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get("/api/userdata/../../etc/passwd")
        assert r.status_code in (400, 404)

        r = await ac.post("/api/userdata/__proto__", json={})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_calculate_ignores_extra_fields():
    """Calculator endpoints must not error on unexpected input fields."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.post("/tax/t1/calculate", json={
            "employment_income": 50000,
            "evil_field": "<script>alert(1)</script>",
            "injection": "'; DROP TABLE users; --",
        })
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_list_fields_rejects_unknown_form():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get("/admin/list-fields/../../etc/shadow")
        assert r.status_code in (400, 404)


# ── Error bodies must not leak sensitive info ─────────────────────────────────

@pytest.mark.asyncio
async def test_forbidden_page_does_not_leak_secret(monkeypatch):
    """403 page must not include SESSION_SECRET or internal stack traces."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "only@allowed.com")
    token = _make_token(_SECRET, "notallowed@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"aether_session_cra_taxhelper": token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert _SECRET.encode() not in r.content
    assert b"traceback" not in r.content.lower()
    assert b"Traceback" not in r.content


# ── Encryption at rest ────────────────────────────────────────────────────────

def test_encrypt_blob_produces_opaque_string():
    """Encrypted blob must not contain raw field values."""
    from cryptography.fernet import Fernet
    import app.config as cfg
    import app.crypto as crypto

    key = Fernet.generate_key().decode()
    original_key = cfg.settings.FIELD_ENCRYPTION_KEY
    cfg.settings.FIELD_ENCRYPTION_KEY = key
    crypto._fernet = None
    crypto._init_done = False

    try:
        payload = json.dumps({"employment_income": 95000, "sin": "123-456-789"})
        blob = crypto.encrypt_blob(payload)
        assert "95000" not in blob
        assert "123-456-789" not in blob
        assert blob.startswith("enc:v1:")
    finally:
        cfg.settings.FIELD_ENCRYPTION_KEY = original_key
        crypto._fernet = None
        crypto._init_done = False


def test_plaintext_not_stored_when_key_set(monkeypatch):
    """With encryption key set, save_form_data must not store plain JSON."""
    from cryptography.fernet import Fernet
    import app.crypto as crypto
    import app.config as cfg

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(cfg.settings, "FIELD_ENCRYPTION_KEY", key)
    crypto._fernet = None
    crypto._init_done = False

    data = {"employment_income": 85000}
    encrypted = crypto.encrypt_blob(json.dumps(data))
    assert json.dumps(data) not in encrypted   # raw JSON not in blob
    assert crypto.decrypt_blob(encrypted) == json.dumps(data)

    # Cleanup
    crypto._fernet = None
    crypto._init_done = False


def test_decrypt_without_key_raises_for_encrypted_blob(monkeypatch):
    """decrypt_blob must raise ValueError if key is missing for an enc: blob."""
    from cryptography.fernet import Fernet
    import app.crypto as crypto
    import app.config as cfg

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(cfg.settings, "FIELD_ENCRYPTION_KEY", key)
    crypto._fernet = None
    crypto._init_done = False
    blob = crypto.encrypt_blob(json.dumps({"x": 1}))

    monkeypatch.setattr(cfg.settings, "FIELD_ENCRYPTION_KEY", "")
    crypto._fernet = None
    crypto._init_done = False

    with pytest.raises(ValueError):
        crypto.decrypt_blob(blob)


# ── Explicit token purpose (typ == "session") ─────────────────────────────────


def test_exact_six_hour_lifetime_is_accepted(monkeypatch):
    kid = "200"
    issued = int(kid) * AUTH_KEY_ROTATION_SECONDS + 100
    _set_keyring(monkeypatch, current_kid=kid)
    token = _make_token(
        _SECRET,
        "user@test.com",
        exp_offset=AUTH_TOKEN_MAX_AGE_SECONDS,
        issued_at=issued,
        kid=kid,
    )
    assert _verify_v2_token(token, now=issued + 1) is not None


def test_oversized_session_lifetime_is_rejected(monkeypatch):
    kid = "201"
    issued = int(kid) * AUTH_KEY_ROTATION_SECONDS + 100
    _set_keyring(monkeypatch, current_kid=kid)
    token = _make_token(
        _SECRET,
        "user@test.com",
        exp_offset=AUTH_TOKEN_MAX_AGE_SECONDS + 1,
        issued_at=issued,
        kid=kid,
    )
    assert _verify_v2_token(token, now=issued + 1) is None


def test_future_issuance_skew_boundary(monkeypatch):
    kid = "202"
    now = int(kid) * AUTH_KEY_ROTATION_SECONDS + 1000
    _set_keyring(monkeypatch, current_kid=kid)
    at_limit = _make_token(
        _SECRET, "user@test.com", issued_at=now + AUTH_CLOCK_SKEW_SECONDS, kid=kid
    )
    past_limit = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=now + AUTH_CLOCK_SKEW_SECONDS + 1,
        kid=kid,
    )
    assert _verify_v2_token(at_limit, now=now) is not None
    assert _verify_v2_token(past_limit, now=now) is None


def test_kid_period_issuance_boundaries(monkeypatch):
    kid = "203"
    period_start = int(kid) * AUTH_KEY_ROTATION_SECONDS
    period_end = period_start + AUTH_KEY_ROTATION_SECONDS
    _set_keyring(monkeypatch, current_kid=kid)
    lower = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=period_start - AUTH_CLOCK_SKEW_SECONDS,
        kid=kid,
    )
    upper = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=period_end + AUTH_CLOCK_SKEW_SECONDS - 1,
        kid=kid,
    )
    too_early = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=period_start - AUTH_CLOCK_SKEW_SECONDS - 1,
        kid=kid,
    )
    too_late = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=period_end + AUTH_CLOCK_SKEW_SECONDS,
        kid=kid,
    )
    assert _verify_v2_token(lower, now=period_start) is not None
    assert _verify_v2_token(too_early, now=period_start) is None
    _set_keyring(monkeypatch, current_kid=str(int(kid) + 1))
    assert _verify_v2_token(upper, now=period_end) is not None
    assert _verify_v2_token(too_late, now=period_end) is None


def test_previous_key_retires_at_bounded_overlap(monkeypatch):
    kid = "204"
    period_end = (int(kid) + 1) * AUTH_KEY_ROTATION_SECONDS
    issued = period_end + AUTH_CLOCK_SKEW_SECONDS - 1
    retirement = period_end + AUTH_TOKEN_MAX_AGE_SECONDS + AUTH_CLOCK_SKEW_SECONDS
    _set_keyring(monkeypatch, current_kid=str(int(kid) + 1))
    token = _make_token(
        _SECRET,
        "user@test.com",
        exp_offset=AUTH_TOKEN_MAX_AGE_SECONDS,
        issued_at=issued,
        kid=kid,
    )
    assert _verify_v2_token(token, now=retirement - 2) is not None
    assert _verify_v2_token(token, now=retirement + 1) is None


def test_next_key_is_not_accepted_before_skew_window(monkeypatch):
    current_kid = "205"
    next_kid = str(int(current_kid) + 1)
    period_start = int(next_kid) * AUTH_KEY_ROTATION_SECONDS
    _set_keyring(monkeypatch, current_kid=current_kid)
    token = _make_token(
        _SECRET, "user@test.com", issued_at=period_start, kid=next_kid
    )
    assert (
        _verify_v2_token(
            token, now=period_start - AUTH_CLOCK_SKEW_SECONDS - 1
        )
        is None
    )
    assert (
        _verify_v2_token(token, now=period_start - AUTH_CLOCK_SKEW_SECONDS)
        is not None
    )


def test_unknown_and_wrong_period_keys_are_rejected(monkeypatch):
    current_kid = "206"
    unknown_kid = str(int(current_kid) + 2)
    issued = int(unknown_kid) * AUTH_KEY_ROTATION_SECONDS + 100
    _set_keyring(monkeypatch, current_kid=current_kid)
    unknown = _make_token(
        _SECRET, "user@test.com", issued_at=issued, kid=unknown_kid
    )
    wrong_key = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=issued,
        kid=unknown_kid,
        signing_kid=current_kid,
    )
    assert _verify_v2_token(unknown, now=issued + 1) is None
    assert _verify_v2_token(wrong_key, now=issued + 1) is None


def test_malformed_and_oversized_tokens_are_rejected(monkeypatch):
    kid = "207"
    issued = int(kid) * AUTH_KEY_ROTATION_SECONDS + 100
    _set_keyring(monkeypatch, current_kid=kid)
    claims = {
        "auth_version": 2,
        "aud": AETHER_AUD,
        "typ": "session",
        "kid": kid,
        "iat": issued,
        "exp": issued + 3600,
        "email": "user@test.com",
        "padding": "x" * 5000,
    }
    oversized = _sign_claims(claims)
    assert len(oversized.encode()) > 4096
    assert _verify_v2_token(oversized, now=issued + 1) is None
    assert _verify_v2_token("not-a-token", now=issued + 1) is None
    assert _verify_v2_token("0" * 64 + ".[]", now=issued + 1) is None


@pytest.mark.parametrize("bad_kid", ["0208", "-1", "9" * 10000, 208, None])
def test_noncanonical_kids_are_rejected(monkeypatch, bad_kid):
    valid_kid = "208"
    issued = int(valid_kid) * AUTH_KEY_ROTATION_SECONDS + 100
    _set_keyring(monkeypatch, current_kid=valid_kid)
    claims = {
        "auth_version": 2,
        "aud": AETHER_AUD,
        "typ": "session",
        "kid": bad_kid,
        "iat": issued,
        "exp": issued + 3600,
        "email": "user@test.com",
    }
    token = _sign_claims(claims, signing_kid=valid_kid)
    assert _verify_v2_token(token, now=issued + 1) is None


def test_complete_consecutive_keyring_is_required(monkeypatch):
    import app.config as cfg

    assert signing_key_configured() is True
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_PREVIOUS_SECRET_HEX", "")
    assert signing_key_configured() is False
    _set_keyring(monkeypatch)
    monkeypatch.setattr(
        cfg.settings,
        "AETHER_AUTH_NEXT_KEY_ID",
        str(int(cfg.settings.AETHER_AUTH_KEY_ID) + 2),
    )
    assert signing_key_configured() is False


def test_stale_consecutive_keyring_fails_startup_validation(monkeypatch):
    stale_current = str(int(key_id_at()) - 2)
    _set_keyring(monkeypatch, current_kid=stale_current)
    assert signing_key_configured() is False


def test_running_instance_accepts_prestaged_next_key_after_rollover(monkeypatch):
    current_kid = "209"
    next_kid = str(int(current_kid) + 1)
    rollover = int(next_kid) * AUTH_KEY_ROTATION_SECONDS
    _set_keyring(monkeypatch, current_kid=current_kid)
    token = _make_token(
        _SECRET,
        "user@test.com",
        issued_at=rollover + 1,
        kid=next_kid,
    )
    assert _verify_v2_token(token, now=rollover + 2) is not None

def test_missing_typ_rejected(monkeypatch):
    """A token without an explicit typ=session claim must not verify."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    token = _make_token(_SECRET, "user@test.com", typ=None)
    assert _verify_v2_token(token, AETHER_AUD) is None


def test_wrong_typ_rejected(monkeypatch):
    """A non-session token purpose (e.g. an internal token) must not verify."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    for bad_typ in ("internal", "app_invite", "refresh", ""):
        token = _make_token(_SECRET, "user@test.com", typ=bad_typ)
        assert _verify_v2_token(token, AETHER_AUD) is None, \
            f"typ={bad_typ!r} token was accepted"


def test_valid_session_typ_accepted(monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    token = _make_token(_SECRET, "user@test.com")  # typ defaults to "session"
    data = _verify_v2_token(token, AETHER_AUD)
    assert data is not None and data["email"] == "user@test.com"


def test_missing_typ_rejected_without_legacy_grace(monkeypatch):
    """Strict rotation rollout never accepts a token without typ=session."""
    token = _make_token(_SECRET, "user@test.com", typ=None)
    assert _verify_v2_token(token, AETHER_AUD) is None


def test_missing_typ_remains_rejected(monkeypatch):
    token = _make_token(_SECRET, "user@test.com", typ=None)
    assert _verify_v2_token(token, AETHER_AUD) is None


def test_wrong_typ_has_no_grace_window(monkeypatch):
    token = _make_token(_SECRET, "user@test.com", typ="internal")
    assert _verify_v2_token(token, AETHER_AUD) is None


# ── Live session introspection (immediate revocation) ─────────────────────────

def _fake_introspect_client(record, *, status_code=200, payload=None, exc=None):
    """Build a fake httpx.AsyncClient recording the request and returning a result."""

    class _Resp:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            return payload if payload is not None else {}

    class _Client:
        def __init__(self, *a, **k):
            record["timeout"] = k.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            record["url"] = url
            record["json"] = json
            record["headers"] = dict(headers or {})
            if exc is not None:
                raise exc
            return _Resp()

    return _Client


def _introspection_token(kid: str | None = None) -> str:
    return "sig." + json.dumps({"kid": kid or key_id_at()})


@pytest.mark.asyncio
async def test_introspection_active_session_signs_headers(monkeypatch):
    import app.auth as auth_mod
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)

    record: dict = {}
    monkeypatch.setattr(
        auth_mod.httpx, "AsyncClient",
        _fake_introspect_client(record, payload={"active": True}),
    )
    token = _introspection_token()
    assert await session_is_active(token) is True

    assert record["url"].endswith("/auth/session/introspect")
    assert record["json"] == {"token": token, "aud": AETHER_AUD}
    headers = record["headers"]
    assert headers["X-Aether-Audience"] == AETHER_AUD
    assert headers["X-Aether-Key-Id"] == key_id_at()
    ts = headers["X-Aether-Timestamp"]
    digest = hashlib.sha256(token.encode()).hexdigest()
    key = _derive_app_key(_SECRET, AETHER_AUD, key_id_at())
    expected = hmac.new(key, f"{ts}\n{digest}".encode(), hashlib.sha256).hexdigest()
    assert headers["X-Aether-Introspection"] == expected
    assert headers["X-Aether-Introspection"] == expected.lower()
    # The raw token must never travel in the signed headers.
    assert token not in headers.values()


@pytest.mark.asyncio
async def test_introspection_revoked_fails_closed(monkeypatch):
    import app.auth as auth_mod
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    record: dict = {}
    monkeypatch.setattr(
        auth_mod.httpx, "AsyncClient",
        _fake_introspect_client(record, payload={"active": False}),
    )
    assert await session_is_active(_introspection_token()) is False


@pytest.mark.asyncio
async def test_introspection_gateway_unavailable_fails_closed(monkeypatch):
    import app.auth as auth_mod
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    record: dict = {}
    monkeypatch.setattr(
        auth_mod.httpx, "AsyncClient",
        _fake_introspect_client(record, exc=auth_mod.httpx.ConnectError("boom")),
    )
    assert await session_is_active(_introspection_token()) is False


@pytest.mark.asyncio
async def test_introspection_non_200_fails_closed(monkeypatch):
    import app.auth as auth_mod
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", _scoped_hex())
    record: dict = {}
    monkeypatch.setattr(
        auth_mod.httpx, "AsyncClient",
        _fake_introspect_client(record, status_code=503, payload={"active": True}),
    )
    assert await session_is_active(_introspection_token()) is False


@pytest.mark.asyncio
async def test_introspection_no_master_key_fallback(monkeypatch):
    """Without a scoped key (no master fallback) the check fails closed and never
    signs with a master-derived key."""
    import app.auth as auth_mod
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)

    def _boom(*a, **k):
        raise AssertionError("must not contact the Gateway without a scoped key")

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", _boom)
    assert await session_is_active(_introspection_token()) is False


@pytest.mark.asyncio
async def test_middleware_fails_closed_when_session_revoked(monkeypatch):
    """A locally valid, allowlisted session that the Gateway reports as revoked
    must be rejected (fail closed) — browsers get the canonical login redirect."""
    import app.config as cfg
    import app.main as main_mod

    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    monkeypatch.setattr(main_mod, "session_is_active", _introspect_revoked)

    token = _make_token(_SECRET, "allowed@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        html = await ac.get(
            "/tax/t1", headers={"Accept": "text/html"}, follow_redirects=False
        )
        assert html.status_code == 302
        assert "login" in html.headers.get("location", "").lower()
        api = await ac.get(
            "/tax/t1", headers={"Accept": "application/json"}, follow_redirects=False
        )
        assert api.status_code == 401


@pytest.mark.asyncio
async def test_middleware_allows_active_session(monkeypatch):
    """The same session is granted when the Gateway confirms it is active."""
    import app.config as cfg
    import app.main as main_mod

    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    monkeypatch.setattr(main_mod, "session_is_active", _introspect_ok)

    token = _make_token(_SECRET, "allowed@test.com")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        r = await ac.get("/tax/t1")
        assert r.status_code == 200
