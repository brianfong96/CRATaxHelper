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


# ── Token helpers ─────────────────────────────────────────────────────────────

def _make_token(secret: str, email: str, exp_offset: int = 3600) -> str:
    """Create a valid HMAC-signed session token (mirrors auth.py logic)."""
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
        cookies={"aether_session": token},
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
        cookies={"aether_session": bad_token},
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
        cookies={"aether_session": expired_token},
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
        cookies={"aether_session": wrong_token},
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
        cookies={"aether_session": token},
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
        cookies={"aether_session": token},
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
        cookies={"aether_session": token},
    ) as ac:
        r = await ac.get("/tax/t1")
    assert r.status_code == 200


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
        cookies={"aether_session": token},
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
