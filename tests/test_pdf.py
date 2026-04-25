"""
Tests for PDF export endpoints.

Verifies that /tax/t1/pdf and /tax/bc428/pdf return valid PDF bytes
given a range of inputs (empty, minimal, full scenario).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

PDF_MAGIC = b"%PDF"   # every valid PDF starts with %PDF


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── T1 PDF ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t1_pdf_empty_body(client):
    """PDF endpoint must accept an empty body (all zeros)."""
    resp = await client.post("/tax/t1/pdf", json={})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == PDF_MAGIC


@pytest.mark.asyncio
async def test_t1_pdf_with_income(client):
    """T1 PDF with common employment-income scenario."""
    resp = await client.post("/tax/t1/pdf", json={
        "lines": {
            "10100": 85000,
            "30000": 16129,
            "43700": 18000,
            "40424": 9500,
            "42000": 3200,
            "48200": 12700,
            "48400": 5300,
        },
        "age_65": False,
    })
    assert resp.status_code == 200
    assert resp.content[:4] == PDF_MAGIC
    # Must be a meaningful file (not trivially empty)
    assert len(resp.content) > 1024


@pytest.mark.asyncio
async def test_t1_pdf_content_disposition(client):
    """Response must include Content-Disposition with expected filename."""
    resp = await client.post("/tax/t1/pdf", json={})
    cd = resp.headers.get("content-disposition", "")
    assert "T1-2025.pdf" in cd


@pytest.mark.asyncio
async def test_t1_pdf_age65_flag(client):
    """PDF endpoint should accept the age_65 flag without error."""
    resp = await client.post("/tax/t1/pdf", json={"lines": {"10100": 40000}, "age_65": True})
    assert resp.status_code == 200
    assert resp.content[:4] == PDF_MAGIC


# ── BC428 PDF ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bc428_pdf_empty_body(client):
    """BC428 PDF endpoint must accept an empty body."""
    resp = await client.post("/tax/bc428/pdf", json={})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == PDF_MAGIC


@pytest.mark.asyncio
async def test_bc428_pdf_with_values(client):
    """BC428 PDF with a typical scenario."""
    resp = await client.post("/tax/bc428/pdf", json={
        "lines": {
            "TaxableIncome": 75000,
            "bcTax": 3200,
            "58040": 12932,
            "bcCredits": 654,
            "42800": 2546,
        },
        "age_65": False,
    })
    assert resp.status_code == 200
    assert resp.content[:4] == PDF_MAGIC
    assert len(resp.content) > 1024


@pytest.mark.asyncio
async def test_bc428_pdf_content_disposition(client):
    """BC428 response must name the file BC428-2025.pdf."""
    resp = await client.post("/tax/bc428/pdf", json={})
    cd = resp.headers.get("content-disposition", "")
    assert "BC428-2025.pdf" in cd


# ── Combined round-trip ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_round_trip_pdf(client):
    """
    Simulate filling T1 + BC428 and exporting both PDFs.
    Both endpoints return valid non-trivial PDFs.
    """
    t1_lines = {
        "10100": 95000, "30000": 16129, "31000": 3356, "31200": 1077,
        "43700": 20000, "40424": 11000, "42000": 4500,
        "48200": 15500, "48400": 4500,
    }
    bc428_lines = {
        "TaxableIncome": 95000, "58040": 12932, "bcTax": 5200,
        "bcCredits": 654, "42800": 4546,
    }

    t1_resp   = await client.post("/tax/t1/pdf",   json={"lines": t1_lines})
    bc428_resp = await client.post("/tax/bc428/pdf", json={"lines": bc428_lines})

    assert t1_resp.status_code   == 200
    assert bc428_resp.status_code == 200
    assert t1_resp.content[:4]   == PDF_MAGIC
    assert bc428_resp.content[:4] == PDF_MAGIC
    assert len(t1_resp.content)   > 2048
    assert len(bc428_resp.content) > 1024
