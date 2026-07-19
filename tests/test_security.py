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
from app.auth import AETHER_AUD, _derive_app_key

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
) -> str:
    """Create a strict Aether auth v2 token (mirrors auth.py derivation)."""
    payload = json.dumps({
        "auth_version": auth_version,
        "aud": aud,
        "email": email, "name": "Test User",
        "is_admin": is_admin,
        "exp": time.time() + exp_offset,
    })
    key = _derive_app_key(secret, aud)
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


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SECRET = "test-secret-for-security-tests"


def _scoped_hex(secret: str = _SECRET, aud: str = AETHER_AUD) -> str:
    """The audience-scoped signing key a deployment would set as AETHER_AUTH_SECRET_HEX."""
    return _derive_app_key(secret, aud).hex()


@pytest.fixture(autouse=True)
def _local_master_fallback(monkeypatch):
    """Tests/local escape hatch: derive the scoped key from the master SESSION_SECRET.

    Mirrors AETHER_ALLOW_MASTER_KEY_FALLBACK for the existing suite so tokens
    signed with the master-derived key verify. Individual tests override these
    to exercise the production hex path and the fail-closed behaviour.
    """
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)


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
async def test_master_fallback_only_when_flag_enabled(monkeypatch):
    """A master-derived token must verify only when the fallback flag is enabled."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _SECRET)
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(cfg.settings, "ALLOWED_EMAILS", "")
    monkeypatch.setattr(cfg.settings, "AETHER_AUTH_SECRET_HEX", "")
    token = _make_token(_SECRET, "user@test.com")

    # Flag enabled (tests/local) → accepted.
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={_COOKIE: token},
    ) as ac:
        assert (await ac.get("/tax/t1")).status_code == 200

    # Flag disabled (production) → fail closed.
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
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
