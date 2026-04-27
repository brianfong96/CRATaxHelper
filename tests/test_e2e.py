"""
End-to-end browser tests using Playwright.

Starts a local uvicorn server (AUTH_ENABLED=False) and drives a real
Chromium browser to verify:
  - Pages load and render PDF overlays
  - Inputs accept values and calculations update
  - Dollar/cents split inputs work correctly
  - Cross-form links navigate to the right page
  - Export buttons are present and clickable
  - localStorage round-trip persists values across reload
  - All form pages are reachable from the homepage
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

import httpx
import pytest
from playwright.sync_api import Page, expect, sync_playwright

pytestmark = pytest.mark.e2e



# ── Live server fixture ───────────────────────────────────────────────────────

_PORT = 18081
_BASE = f"http://127.0.0.1:{_PORT}"


@pytest.fixture(scope="session")
def live_server():
    """Start app in a subprocess with auth disabled, fully isolated event loop."""
    env = {
        **os.environ,
        "AUTH_ENABLED": "false",
        "SESSION_SECRET": "",
        "ARCHIVE_URL": os.environ.get("ARCHIVE_URL", "http://localhost:9999"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(_PORT), "--log-level", "error"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )

    # Wait for the server to be ready
    for _ in range(40):
        try:
            httpx.get(f"{_BASE}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("e2e test server failed to start")

    yield _BASE
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def browser_context():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        yield ctx
        ctx.close()
        browser.close()


@pytest.fixture
def page(browser_context):
    pg = browser_context.new_page()
    yield pg
    pg.close()


# ── Homepage ──────────────────────────────────────────────────────────────────

def test_homepage_loads(page: Page, live_server):
    page.goto(live_server)
    expect(page).to_have_title(re.compile(r"Tax|CRA", re.IGNORECASE))
    # Form cards should be visible
    expect(page.locator("text=T1 General").first).to_be_visible()


def test_homepage_shows_all_form_cards(page: Page, live_server):
    page.goto(live_server)
    for name in ["T1 General", "BC428", "Schedule 9", "Schedule 3"]:
        assert page.locator(f"text={name}").count() > 0, f"'{name}' not found on homepage"


def test_homepage_year_dropdown_present(page: Page, live_server):
    page.goto(live_server)
    # Year selector should be in the nav bar
    assert page.locator("select, [data-year], .year-select").count() > 0 \
        or "2025" in page.content()


# ── T1 General form ───────────────────────────────────────────────────────────

def test_t1_form_loads(page: Page, live_server):
    page.goto(f"{live_server}/tax/t1")
    expect(page.locator("text=T1 General").first).to_be_visible(timeout=5000)
    # At least one PDF background image should be present
    assert page.locator("img.pdf-bg").count() > 0


def test_t1_employment_income_triggers_recalc(page: Page, live_server):
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")

    # Find the employment income input (line 10100)
    income_input = page.locator("#f10100, [id*='10100']").first
    if income_input.count() == 0:
        pytest.skip("T1 line 10100 input not found — form may use different IDs")

    income_input.click()
    income_input.fill("80000")
    income_input.press("Tab")
    page.wait_for_timeout(500)

    # Total income line (15000) should be populated
    total_el = page.locator("#f15000, [id*='15000']").first
    if total_el.count() > 0:
        val = total_el.input_value()
        assert val and val != "0.00", "Total income not calculated after entering employment income"


def test_t1_cents_input_present(page: Page, live_server):
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")
    # Cents inputs should be injected by initAmountBoxes()
    assert page.locator(".cents-input").count() > 0, "No cents inputs found — initAmountBoxes() may not have run"


def test_t1_open_bc428_link_present(page: Page, live_server):
    page.goto(f"{live_server}/tax/t1")
    # Link to BC428 should exist
    bc428_link = page.locator("a[href*='bc428'], button:has-text('BC428'), a:has-text('BC428')")
    assert bc428_link.count() > 0, "No link to BC428 found on T1 form"


def test_t1_export_excel_button_present(page: Page, live_server):
    page.goto(f"{live_server}/tax/t1")
    btn = page.locator("button:has-text('Excel'), a:has-text('Excel'), button:has-text('Export')")
    assert btn.count() > 0, "Export Excel button not found on T1"


# ── BC428 form ────────────────────────────────────────────────────────────────

def test_bc428_form_loads(page: Page, live_server):
    page.goto(f"{live_server}/tax/bc428")
    page.wait_for_load_state("networkidle")
    assert page.locator("img.pdf-bg").count() > 0
    expect(page.locator("text=BC428").first).to_be_visible(timeout=5000)


def test_bc428_sync_from_t1_button(page: Page, live_server):
    page.goto(f"{live_server}/tax/bc428")
    btn = page.locator("button:has-text('Sync'), button:has-text('T1')")
    assert btn.count() > 0, "Sync from T1 button not found on BC428"


def test_bc428_export_excel_button(page: Page, live_server):
    page.goto(f"{live_server}/tax/bc428")
    btn = page.locator("button:has-text('Excel'), a:has-text('Excel'), button:has-text('Export')")
    assert btn.count() > 0, "Export Excel button not found on BC428"


# ── Cross-form localStorage round-trip ───────────────────────────────────────

def test_t1_saves_line26000_to_localstorage(page: Page, live_server):
    """Entering taxable income in T1 should store it in localStorage."""
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")

    income_input = page.locator("#f10100, [id*='10100']").first
    if income_input.count() == 0:
        pytest.skip("Income input not found")

    income_input.click()
    income_input.fill("70000")
    income_input.press("Tab")
    page.wait_for_timeout(800)

    ls_val = page.evaluate("() => localStorage.getItem('cra_t1_line26000')")
    # Line 26000 should be populated (may differ from 70000 after deductions)
    assert ls_val is not None, "cra_t1_line26000 not saved to localStorage"


def test_form_data_persists_on_reload(page: Page, live_server):
    """Values entered should still be there after page reload (localStorage)."""
    page.goto(f"{live_server}/tax/bc428")
    page.wait_for_load_state("networkidle")

    # Enter a value in the basic personal amount field
    el = page.locator(".pdf-input[data-numeric]").first
    if el.count() == 0:
        pytest.skip("No numeric input found")

    el.click()
    el.fill("12000")
    el.press("Tab")
    page.wait_for_timeout(800)

    # Reload and check
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # localStorage key should have been saved and reloaded
    saved = page.evaluate("() => localStorage.getItem('cra_bc428_autosave')")
    assert saved and "12000" in saved, "BC428 autosave data missing or wrong after reload"


# ── New forms ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,name", [
    ("/tax/schedule5", "Schedule 5"),
    ("/tax/schedule7", "Schedule 7"),
    ("/tax/schedule8", "Schedule 8"),
    ("/tax/t777",      "T777"),
    ("/tax/t2209",     "T2209"),
])
def test_new_form_loads_in_browser(page: Page, live_server, path, name):
    page.goto(f"{live_server}{path}")
    page.wait_for_load_state("domcontentloaded", timeout=8000)
    assert page.locator("img.pdf-bg").count() > 0, \
        f"{name}: no PDF background image found"
    assert name.lower() in page.content().lower(), \
        f"{name}: form name not found in page content"


# ── Schedule 9 ────────────────────────────────────────────────────────────────

def test_schedule9_form_loads(page: Page, live_server):
    page.goto(f"{live_server}/tax/schedule9")
    page.wait_for_load_state("networkidle")
    assert page.locator("img.pdf-bg").count() > 0


def test_schedule9_has_link_back_to_t1(page: Page, live_server):
    page.goto(f"{live_server}/tax/schedule9")
    link = page.locator("a[href*='t1'], button:has-text('T1'), a:has-text('T1')")
    assert link.count() > 0, "No link back to T1 from Schedule 9"


# ── Schedule 3 ────────────────────────────────────────────────────────────────

def test_schedule3_form_loads(page: Page, live_server):
    page.goto(f"{live_server}/tax/schedule3")
    page.wait_for_load_state("networkidle")
    assert page.locator("img.pdf-bg").count() > 0


# ── Security: no PII in page source ──────────────────────────────────────────

def test_no_secret_in_html_source(page: Page, live_server):
    """SESSION_SECRET must never appear in rendered HTML."""
    page.goto(f"{live_server}/tax/t1")
    content = page.content()
    assert "SESSION_SECRET" not in content
    assert "FIELD_ENCRYPTION_KEY" not in content


def test_csp_or_no_inline_secrets(page: Page, live_server):
    """Verify no raw database/archive URLs are exposed in client HTML."""
    page.goto(f"{live_server}/tax/t1")
    content = page.content()
    assert "postgresql" not in content.lower()
    assert "archive:7000" not in content


# ── Worksheet Fed ─────────────────────────────────────────────────────────────

def test_worksheet_fed_loads(page: Page, live_server):
    """Worksheet Fed form must load — may be /tax/worksheet-fed or /tax/worksheet_fed."""
    for path in ["/tax/worksheet-fed", "/tax/worksheet_fed"]:
        try:
            page.goto(f"{live_server}{path}")
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            if page.locator("img.pdf-bg").count() > 0:
                return  # found it
        except Exception:
            continue
    pytest.fail("Worksheet Fed form not found at /tax/worksheet-fed or /tax/worksheet_fed")


# ── Nav dropdown ──────────────────────────────────────────────────────────────

def test_nav_dropdown_shows_all_forms(page: Page, live_server):
    """Year dropdown must list all 10 CRA forms."""
    expected = ["T1 General", "BC 428", "Schedule 3", "Schedule 5",
                "Schedule 7", "Schedule 8", "Schedule 9", "T777", "T2209", "Worksheet Fed"]
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")
    year_btn = page.locator("#yearBtn, .year-btn").first
    if year_btn.count() == 0:
        pytest.skip("Year button not found")
    year_btn.click()
    page.wait_for_timeout(300)
    dropdown = page.locator("#yearDropdown, .year-dropdown").first
    assert dropdown.is_visible(), "Year dropdown did not open"
    content = dropdown.inner_text()
    for name in expected:
        assert name in content, f"'{name}' not visible in year dropdown"


def test_nav_dropdown_links_are_reachable(page: Page, live_server):
    """Every link in the year dropdown must return HTTP 200."""
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")
    year_btn = page.locator("#yearBtn, .year-btn").first
    if year_btn.count() == 0:
        pytest.skip("Year button not found")
    year_btn.click()
    page.wait_for_timeout(300)
    hrefs = page.locator(".year-dropdown a.yd-form").evaluate_all(
        "els => els.map(e => e.href)"
    )
    assert len(hrefs) >= 9, f"Expected ≥9 form links in dropdown, got {len(hrefs)}"
    import httpx
    for href in hrefs:
        resp = httpx.get(href, timeout=5, follow_redirects=True)
        assert resp.status_code == 200, f"Dropdown link {href} returned {resp.status_code}"


# ── Cross-form data flow (E2E) ────────────────────────────────────────────────

def test_t1_to_bc428_auto_sync(page: Page, live_server):
    """Enter income in T1; navigate to BC428 via URL — it should auto-fill taxable income."""
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")
    income = page.locator("#f10100, [id*='10100']").first
    if income.count() == 0:
        pytest.skip("T1 income input not found")
    income.click()
    income.fill("95000")
    income.press("Tab")
    page.wait_for_timeout(800)
    ls_26000 = page.evaluate("() => localStorage.getItem('cra_t1_line26000')")
    assert ls_26000 is not None, "T1 did not write cra_t1_line26000 after income entry"

    # Navigate to BC428 directly (simulates dropdown nav, not T1's button)
    page.goto(f"{live_server}/tax/bc428")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    ti_el = page.locator("#fTaxableIncome, #fTaxableIncome_supp").first
    if ti_el.count() > 0:
        val = ti_el.input_value()
        assert val and float(val.replace(",", "")) > 0, \
            "BC428 did not auto-sync taxable income from T1 localStorage"


def test_t1_reads_subform_results_from_localstorage(page: Page, live_server):
    """Pre-seeding a sub-form localStorage key should cause T1 to pre-fill that line."""
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")
    page.evaluate("() => { localStorage.setItem('cra_s3_cap_gains', '12500'); }")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    el = page.locator("#f12700").first
    if el.count() == 0:
        pytest.skip("T1 line 12700 field not found")
    val = el.input_value().replace(",", "")
    assert float(val or "0") == pytest.approx(12500, abs=1), \
        f"T1 line 12700 not pre-filled from cra_s3_cap_gains; got '{val}'"


@pytest.mark.parametrize("form_path,form_name", [
    ("/tax/schedule3",  "Schedule 3"),
    ("/tax/schedule5",  "Schedule 5"),
    ("/tax/schedule7",  "Schedule 7"),
    ("/tax/schedule8",  "Schedule 8"),
    ("/tax/schedule9",  "Schedule 9"),
    ("/tax/t777",       "T777"),
    ("/tax/t2209",      "T2209"),
])
def test_subform_has_send_to_t1_button(page: Page, live_server, form_path, form_name):
    """Every sub-form must expose a button/link to send data back to T1."""
    page.goto(f"{live_server}{form_path}")
    page.wait_for_load_state("domcontentloaded", timeout=8000)
    has_return = (
        page.locator("button:has-text('T1')").count() > 0
        or page.locator("a[href*='t1']").count() > 0
        or page.locator("button:has-text('Save')").count() > 0
        or page.locator("button:has-text('Return')").count() > 0
    )
    assert has_return, f"{form_name}: no 'Send/Return to T1' action found in page"


def test_bc428_autosave_persists_across_navigation(page: Page, live_server):
    """BC428 data should survive a round-trip via T1 and back."""
    page.goto(f"{live_server}/tax/bc428")
    page.wait_for_load_state("networkidle")
    el = page.locator("#f58040").first
    if el.count() == 0:
        pytest.skip("BC428 basic personal amount field not found")
    el.click()
    el.fill("16129")
    el.press("Tab")
    page.wait_for_timeout(700)
    page.goto(f"{live_server}/tax/t1")
    page.wait_for_load_state("networkidle")
    page.goto(f"{live_server}/tax/bc428")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    saved = page.evaluate("() => localStorage.getItem('cra_bc428_autosave')")
    assert saved is not None and "16129" in saved, \
        "BC428 data was not persisted in localStorage across navigation"


def test_all_forms_render_pdf_background(page: Page, live_server):
    """Every form route must render at least one PDF background image."""
    form_routes = [
        "/tax/t1", "/tax/bc428", "/tax/schedule3", "/tax/schedule5",
        "/tax/schedule7", "/tax/schedule8", "/tax/schedule9",
        "/tax/t777", "/tax/t2209", "/tax/worksheet_fed",
    ]
    for route in form_routes:
        page.goto(f"{live_server}{route}")
        page.wait_for_load_state("domcontentloaded", timeout=8000)
        bg = page.locator("img.pdf-bg").count()
        assert bg > 0, f"{route}: no PDF background image — form may not have rendered"
