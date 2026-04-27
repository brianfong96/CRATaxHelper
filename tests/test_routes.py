"""
Integration tests for all FastAPI routes.

Tests every GET and POST endpoint for correct status codes, content types,
and basic response shape.  Auth is bypassed by leaving SESSION_SECRET unset
(the middleware skips when SECRET is empty).
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

# ── Shared async client fixture ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Home / index ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_page_loads(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # Registry forms should be listed
    assert b"T1 General" in r.content


@pytest.mark.asyncio
async def test_index_shows_all_registered_forms(client):
    r = await client.get("/")
    assert r.status_code == 200
    for form_name in (b"T1 General", b"BC428", b"Schedule 9", b"BC479", b"Schedule 3"):
        assert form_name in r.content, f"Form {form_name} missing from homepage"


# ── Form page routes ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("path, expected_text", [
    ("/tax/t1",        b"T1 General"),
    ("/tax/bc428",     b"BC428"),
    ("/tax/schedule9", b"Schedule 9"),
    ("/tax/bc479",     b"BC479"),
    ("/tax/schedule3", b"Schedule 3"),
    ("/tax/compare",   b"compare"),
])
async def test_form_page_loads(client, path, expected_text):
    r = await client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert expected_text.lower() in r.content.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/tax/schedule5",
    "/tax/schedule7",
    "/tax/schedule8",
    "/tax/t777",
    "/tax/t2209",
    "/tax/worksheet-fed",
])
async def test_new_form_pages_load(client, path):
    """New forms added in this sprint must return 200 HTML."""
    r = await client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_unknown_form_path_returns_404(client):
    r = await client.get("/tax/doesnotexist")
    assert r.status_code == 404


# ── Profile page ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profile_page_loads(client):
    r = await client.get("/profile")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


# ── Calculate APIs ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t1_calculate_empty(client):
    r = await client.post("/tax/t1/calculate", json={})
    assert r.status_code == 200
    data = r.json()
    assert "line_15000" in data   # total income line always present


@pytest.mark.asyncio
async def test_t1_calculate_employment_income(client):
    r = await client.post("/tax/t1/calculate", json={
        "line_10100": 80000,
        "age_65_or_over": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert float(data.get("line_15000", 0)) == pytest.approx(80000, abs=1)


@pytest.mark.asyncio
async def test_t1_calculate_age65_age_amount(client):
    r = await client.post("/tax/t1/calculate", json={
        "line_10100": 40000,
        "age_65_or_over": True,
    })
    assert r.status_code == 200
    data = r.json()
    # Age amount should be non-zero for 65+ with low income
    assert float(data.get("line_30100", 0)) > 0


@pytest.mark.asyncio
async def test_bc428_calculate_empty(client):
    r = await client.post("/tax/bc428/calculate", json={})
    assert r.status_code == 200
    data = r.json()
    assert "line_42800" in data


@pytest.mark.asyncio
async def test_bc428_calculate_income(client):
    r = await client.post("/tax/bc428/calculate", json={
        "taxable_income": 75000,
        "age_65_or_over": False,
    })
    assert r.status_code == 200
    data = r.json()
    net = float(data.get("line_42800", 0))
    assert net > 0


# ── Excel export ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_excel_export_returns_xlsx(client):
    r = await client.post("/tax/export/excel", json={
        "t1":    {"10100": 80000, "15000": 80000, "26000": 65000},
        "bc428": {"fTaxableIncome": 65000, "f42800": 3200},
    })
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"   # xlsx is a zip


@pytest.mark.asyncio
async def test_excel_export_empty_body(client):
    r = await client.post("/tax/export/excel", json={"t1": {}, "bc428": {}})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"


@pytest.mark.asyncio
async def test_excel_export_content_disposition(client):
    r = await client.post("/tax/export/excel", json={})
    assert "filename" in r.headers.get("content-disposition", "")
    assert ".xlsx" in r.headers.get("content-disposition", "")


# ── Userdata API ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_userdata_unknown_form_returns_400(client):
    r = await client.get("/api/userdata/doesnotexist")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_userdata_post_unknown_form_returns_400(client):
    r = await client.post("/api/userdata/doesnotexist", json={"x": 1})
    assert r.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["t1", "bc428", "schedule9", "bc479", "schedule3"])
async def test_userdata_allowed_forms_exist(client, form):
    """Allowed form names must not return 400 (may 401/404 without auth)."""
    r = await client.get(f"/api/userdata/{form}")
    assert r.status_code in (200, 401, 404)  # 400 means unknown form — not allowed


# ── Admin routes ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_setup_loads(client):
    r = await client.get("/admin/setup")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_forms_status(client):
    r = await client.get("/admin/forms-status")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


# ── Static assets ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_static_form_screenshots_accessible(client):
    """At least one form screenshot must be reachable via /static."""
    r = await client.get("/static/forms/screenshots/schedule9_page1.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


@pytest.mark.asyncio
async def test_static_missing_file_returns_404(client):
    r = await client.get("/static/forms/screenshots/doesnotexist.png")
    assert r.status_code == 404


# ── Forms registry completeness ───────────────────────────────────────────────

def test_forms_registry_has_required_forms():
    """All forms the user requested must be in the registry."""
    from app.forms_registry import FORMS_BY_YEAR
    forms_2025 = FORMS_BY_YEAR.get("2025", [])
    ids = {f["id"] for f in forms_2025}
    required = {
        "t1-2025", "bc428-2025", "schedule9-2025", "bc479-2025", "schedule3-2025",
        "schedule5-2025", "schedule7-2025", "schedule8-2025",
        "t777-2025", "t2209-2025",
    }
    missing = required - ids
    assert not missing, f"Forms missing from registry: {missing}"


def test_forms_registry_entries_have_required_keys():
    from app.forms_registry import FORMS_BY_YEAR
    required_keys = {"id", "name", "form_num", "category", "description", "url", "cra_url"}
    for year, forms in FORMS_BY_YEAR.items():
        for form in forms:
            missing_keys = required_keys - form.keys()
            assert not missing_keys, f"Form {form.get('id')} missing keys: {missing_keys}"
