"""Archive internal-secret purpose separation for CRA Tax Helper.

Hosted CRA must never receive the platform master ``SESSION_SECRET``. Outbound
Archive admin calls (project/table/RLS provisioning and role grants) and the
"archive enabled" checks authenticate with a dedicated ``ARCHIVE_INTERNAL_SECRET``
sent as ``X-Aether-Internal``. A ``SESSION_SECRET`` fallback exists only for
local/tests, gated by ``AETHER_ALLOW_MASTER_KEY_FALLBACK``; production fails
closed when the dedicated secret is missing.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import app.config as cfg
from app import userdata
from app.main import app


# ── Resolver: settings.archive_internal_secret ───────────────────────────────

def test_dedicated_secret_takes_precedence(monkeypatch):
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "archive-only")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "master-should-not-leak")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)
    assert cfg.settings.archive_internal_secret == "archive-only"


def test_missing_dedicated_secret_fails_closed_in_production(monkeypatch):
    """No ARCHIVE_INTERNAL_SECRET and fallback off ⇒ empty (production fail closed)."""
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "master-present")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    assert cfg.settings.archive_internal_secret == ""


def test_master_fallback_only_for_local_tests(monkeypatch):
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "master-present")

    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)
    assert cfg.settings.archive_internal_secret == "master-present"

    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    assert cfg.settings.archive_internal_secret == ""


# ── Outbound Archive admin headers ───────────────────────────────────────────

def test_sys_hdrs_sends_dedicated_secret_not_master(monkeypatch):
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "dedicated-archive-secret")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "master-should-not-leak")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", True)
    headers = userdata._sys_hdrs()
    assert headers == {"X-Aether-Internal": "dedicated-archive-secret"}
    assert "master-should-not-leak" not in headers.values()


def test_sys_hdrs_local_mode_uses_local_admin(monkeypatch):
    """With no dedicated secret and no fallback, admin calls use the local header."""
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    assert userdata._sys_hdrs() == {"X-Local-Admin": "local"}


def test_grant_user_access_skipped_without_dedicated_secret(monkeypatch):
    """Role grants must no-op when the dedicated Archive secret is absent (fail closed)."""
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "master-present")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    called = False

    class _Boom:  # pragma: no cover - must never be constructed
        def __init__(self, *a, **k):
            nonlocal called
            called = True

    monkeypatch.setattr(userdata.httpx, "AsyncClient", _Boom)
    import asyncio
    asyncio.run(userdata.grant_user_access("someone@example.com"))
    assert called is False


# ── /profile archive_enabled flag ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profile_archive_enabled_reflects_dedicated_secret(monkeypatch):
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", False)  # local open mode for page access
    monkeypatch.setattr(cfg.settings, "ARCHIVE_URL", "http://archive:7000")
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", "master-present")
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "")
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        # No dedicated secret ⇒ archive disabled even though SESSION_SECRET is set.
        r = await ac.get("/profile")
    assert r.status_code == 200
    assert b"Browser-only storage" in r.content
    assert b"Server sync enabled" not in r.content

    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", "dedicated")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        r2 = await ac.get("/profile")
    assert r2.status_code == 200
    assert b"Server sync enabled" in r2.content


# ── Delegated identity: per-user Archive CRUD headers ────────────────────────

_MASTER = "master-should-never-be-sent"
_ARCHIVE_SECRET = "dedicated-archive-secret"
_OWNER = "owner@test.com"


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"rows": []}
        self.text = ""

    def json(self):
        return self._payload


def _capturing_client(calls: list):
    """Return a fake httpx.AsyncClient class that records every call's headers."""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append(("GET", url, dict(headers or {})))
            return _FakeResp(200, {"rows": []})

        async def post(self, url, headers=None, json=None):
            calls.append(("POST", url, dict(headers or {})))
            return _FakeResp(201, {})

        async def patch(self, url, headers=None, json=None):
            calls.append(("PATCH", url, dict(headers or {})))
            return _FakeResp(200, {})

    return _Client


def _assert_delegated_and_no_leak(calls: list):
    assert calls, "expected at least one Archive call"
    for method, url, headers in calls:
        assert headers.get("X-Aether-Internal") == _ARCHIVE_SECRET, (method, url, headers)
        assert headers.get("X-Aether-Owner") == _OWNER, (method, url, headers)
        # No browser cookie forwarded.
        assert "Cookie" not in headers
        assert not any("aether_session" in k.lower() for k in headers)
        # The platform master secret must never appear anywhere in the headers.
        assert _MASTER not in headers.values()
        assert all(_MASTER not in v for v in headers.values())


def _configure_archive(monkeypatch):
    monkeypatch.setattr(cfg.settings, "ARCHIVE_URL", "http://archive:7000")
    monkeypatch.setattr(cfg.settings, "ARCHIVE_INTERNAL_SECRET", _ARCHIVE_SECRET)
    monkeypatch.setattr(cfg.settings, "SESSION_SECRET", _MASTER)
    monkeypatch.setattr(cfg.settings, "AETHER_ALLOW_MASTER_KEY_FALLBACK", False)


def test_save_form_data_sends_delegated_identity(monkeypatch):
    _configure_archive(monkeypatch)
    calls: list = []
    monkeypatch.setattr(userdata.httpx, "AsyncClient", _capturing_client(calls))

    import asyncio
    ok = asyncio.run(userdata.save_form_data(_OWNER, "t1", {"10100": "50000"}))
    assert ok is True
    # A find-GET followed by an insert-POST, all delegated, none leaking master.
    assert [m for m, _u, _h in calls] == ["GET", "POST"]
    _assert_delegated_and_no_leak(calls)


def test_get_form_data_sends_delegated_identity(monkeypatch):
    _configure_archive(monkeypatch)
    calls: list = []
    monkeypatch.setattr(userdata.httpx, "AsyncClient", _capturing_client(calls))

    import asyncio
    asyncio.run(userdata.get_form_data(_OWNER, "t1"))
    _assert_delegated_and_no_leak(calls)


def test_userdata_functions_noop_without_owner(monkeypatch):
    """No authenticated owner ⇒ no Archive call at all (fail closed)."""
    _configure_archive(monkeypatch)
    calls: list = []
    monkeypatch.setattr(userdata.httpx, "AsyncClient", _capturing_client(calls))

    import asyncio
    assert asyncio.run(userdata.get_form_data("", "t1")) is None
    assert asyncio.run(userdata.save_form_data("", "t1", {"x": 1})) is False
    assert calls == []


@pytest.mark.asyncio
async def test_userdata_get_route_delegates_authenticated_email(monkeypatch):
    """The /api/userdata GET route must delegate the middleware-authenticated email."""
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", False)  # inject local user
    _configure_archive(monkeypatch)
    seen = {}

    async def _fake_get(owner_email, form_name):
        seen["email"] = owner_email
        seen["form"] = form_name
        return {"10100": "1"}

    monkeypatch.setattr("app.main.get_form_data", _fake_get)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        r = await ac.get("/api/userdata/t1")
    assert r.status_code == 200
    assert seen["email"] == cfg.settings.LOCAL_USER_EMAIL
    assert seen["form"] == "t1"

