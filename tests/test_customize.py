"""
Tests for the Customize routes:
  GET  /customize
  GET  /customize/{form_key}
  GET  /api/customize/{form_key}
  POST /api/customize/{form_key}

Auth is bypassed because SESSION_SECRET is unset in tests.
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch, AsyncMock

from app.main import app, _CUSTOMIZE_FORMS, _CUSTOMIZE_FORMS_BY_KEY


# ── Shared client ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Customize landing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_customize_landing_loads(client):
    r = await client.get("/customize")
    assert r.status_code == 200
    assert b"Customize" in r.content
    assert b"text/html" in r.headers["content-type"].encode()


@pytest.mark.asyncio
async def test_customize_landing_lists_all_forms(client):
    r = await client.get("/customize")
    assert r.status_code == 200
    for form in _CUSTOMIZE_FORMS:
        assert form["number"].encode() in r.content, (
            f"Form {form['number']} missing from /customize landing"
        )


@pytest.mark.asyncio
async def test_customize_landing_has_nav_link(client):
    """Customize link must appear in the nav bar."""
    r = await client.get("/customize")
    assert r.status_code == 200
    assert b"/customize" in r.content


# ── Customize editor ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("form_key", list(_CUSTOMIZE_FORMS_BY_KEY.keys()))
async def test_customize_editor_loads_all_keys(client, form_key):
    r = await client.get(f"/customize/{form_key}")
    assert r.status_code == 200, f"Editor 404 for form_key='{form_key}'"
    assert b"text/html" in r.headers["content-type"].encode()


@pytest.mark.asyncio
async def test_customize_editor_shows_form_number(client):
    r = await client.get("/customize/t1")
    assert r.status_code == 200
    # Form number must appear in editor toolbar
    assert b"T1" in r.content


@pytest.mark.asyncio
async def test_customize_editor_has_add_field_button(client):
    r = await client.get("/customize/bc428")
    assert r.status_code == 200
    assert b"Add Field" in r.content


@pytest.mark.asyncio
async def test_customize_editor_has_formula_reference(client):
    r = await client.get("/customize/t1")
    assert r.status_code == 200
    assert b"Formula reference" in r.content
    assert b"SUM" in r.content


@pytest.mark.asyncio
async def test_customize_editor_has_print_button(client):
    r = await client.get("/customize/t1")
    assert r.status_code == 200
    assert b"Print" in r.content


@pytest.mark.asyncio
async def test_customize_editor_unknown_key_404(client):
    r = await client.get("/customize/not_a_real_form")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_customize_editor_has_pdfjs_script(client):
    """Editor must reference PDF.js CDN for PDF rendering."""
    r = await client.get("/customize/t1")
    assert r.status_code == 200
    assert b"pdfjs-dist" in r.content


@pytest.mark.asyncio
async def test_customize_editor_has_save_endpoint(client):
    """Editor JS must reference the /api/customize/ save endpoint."""
    r = await client.get("/customize/t1")
    assert r.status_code == 200
    assert b"api/customize" in r.content


@pytest.mark.asyncio
async def test_customize_editor_back_link(client):
    """Editor must have a back link to the /customize landing page."""
    r = await client.get("/customize/schedule3")
    assert r.status_code == 200
    assert b"/customize" in r.content


# ── API GET /api/customize/{form_key} ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_customize_get_unknown_key_400(client):
    r = await client.get("/api/customize/nonexistent")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_customize_get_no_data_returns_empty_boxes(client):
    """When no saved layout exists, return {boxes: []}."""
    with patch("app.main.get_form_data", new=AsyncMock(return_value=None)):
        r = await client.get("/api/customize/t1")
    assert r.status_code == 200
    data = r.json()
    assert "boxes" in data
    assert data["boxes"] == []


@pytest.mark.asyncio
async def test_api_customize_get_returns_saved_layout(client):
    saved = {"boxes": [{"id": "f_1", "name": "Income", "page": 1,
                        "xPct": 0.1, "yPct": 0.2, "wPct": 0.15, "hPct": 0.03,
                        "value": "50000", "formula": "", "format": "currency"}]}
    with patch("app.main.get_form_data", new=AsyncMock(return_value=saved)):
        r = await client.get("/api/customize/bc428")
    assert r.status_code == 200
    data = r.json()
    assert len(data["boxes"]) == 1
    assert data["boxes"][0]["name"] == "Income"


# ── API POST /api/customize/{form_key} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_customize_post_unknown_key_400(client):
    r = await client.post("/api/customize/nonexistent", json={"boxes": []})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_customize_post_archive_failure_502(client):
    """When Archive save fails, return 502."""
    with patch("app.main.save_form_data", new=AsyncMock(return_value=False)):
        r = await client.post("/api/customize/t1", json={"boxes": []})
    # In local mode a synthetic user is injected (email = local@localhost), so
    # we reach save_form_data; a False return maps to 502.
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_api_customize_post_saves_layout(client):
    """Authenticated save should call save_form_data with custom__ prefix."""
    payload = {"boxes": [{"id": "f_1", "name": "Tax", "page": 1,
                          "xPct": 0.5, "yPct": 0.5, "wPct": 0.1, "hPct": 0.03,
                          "value": "1234", "formula": "", "format": "number"}]}
    saved_calls = []

    async def mock_save(cookie, email, form_key, body):
        saved_calls.append((form_key, body))
        return True

    # inject a synthetic user the same way the local middleware does
    from app.main import app as the_app
    from starlette.middleware.base import BaseHTTPMiddleware

    class _InjectUser(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = {"email": "test@local.dev", "name": "Test"}
            return await call_next(request)

    the_app.middleware_stack = None  # force rebuild
    the_app.add_middleware(_InjectUser)

    with patch("app.main.save_form_data", new=mock_save):
        async with AsyncClient(
            transport=ASGITransport(app=the_app), base_url="http://test"
        ) as ac:
            r = await ac.post("/api/customize/t1", json=payload)

    assert r.status_code == 200
    assert r.json().get("saved") is True
    assert any(k == "custom__t1" for k, _ in saved_calls)


@pytest.mark.asyncio
async def test_api_customize_post_invalid_json_400(client):
    """Sending non-JSON body should return 400."""
    r = await client.post(
        "/api/customize/t1",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 401)  # 401 if auth check fires first (no user)


# ── Form key completeness ─────────────────────────────────────────────────────

def test_all_customize_form_keys_unique():
    """Each form key in _CUSTOMIZE_FORMS must be unique."""
    keys = [f["key"] for f in _CUSTOMIZE_FORMS]
    assert len(keys) == len(set(keys)), "Duplicate form keys in _CUSTOMIZE_FORMS"


def test_all_customize_forms_have_required_fields():
    """Every entry must have key, number, title, filename."""
    for f in _CUSTOMIZE_FORMS:
        for field in ("key", "number", "title", "filename"):
            assert field in f and f[field], (
                f"Form '{f.get('key', '?')}' missing or empty field '{field}'"
            )


def test_customize_forms_by_key_index_matches():
    """_CUSTOMIZE_FORMS_BY_KEY must index every form in _CUSTOMIZE_FORMS."""
    for f in _CUSTOMIZE_FORMS:
        assert f["key"] in _CUSTOMIZE_FORMS_BY_KEY
        assert _CUSTOMIZE_FORMS_BY_KEY[f["key"]] is f


def test_customize_forms_count():
    """Should have 10 customize forms (same set as PDF.js viewer)."""
    assert len(_CUSTOMIZE_FORMS) == 10
