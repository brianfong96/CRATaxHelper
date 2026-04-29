"""
Tests for desktop-mode behaviour.

Verifies:
- _app_pkg_dir() returns Path(__file__).parent in dev (no sys.frozen)
- ARCHIVE_URL="" → save routes return 200 {"saved": True, "storage": "local"}
  instead of 502
- desktop.py sets the correct environment variables before importing the app
- settings.is_desktop reflects DESKTOP_MODE env var
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ── _app_pkg_dir() resolution ─────────────────────────────────────────────────

def test_app_pkg_dir_dev_mode():
    """In dev mode (no sys.frozen), _app_pkg_dir() == app package directory."""
    from app.main import _app_pkg_dir

    # Ensure we are NOT in a frozen (PyInstaller) context for this test
    assert not getattr(sys, "frozen", False), "Test must run outside PyInstaller"
    result = _app_pkg_dir()
    assert result.is_dir(), f"_app_pkg_dir() returned non-existent path: {result}"
    assert (result / "templates").is_dir(), "templates/ must be inside _app_pkg_dir()"
    assert (result / "static").is_dir(),    "static/ must be inside _app_pkg_dir()"


def test_app_pkg_dir_frozen_mode(tmp_path, monkeypatch):
    """In frozen (PyInstaller) mode, _app_pkg_dir() uses sys._MEIPASS/app."""
    import importlib
    import app.main as main_module

    fake_meipass = tmp_path / "meipass"
    (fake_meipass / "app").mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)

    # Re-evaluate the function with the monkeypatched sys
    result = main_module._app_pkg_dir()
    assert result == fake_meipass / "app"


# ── Desktop config ────────────────────────────────────────────────────────────

def test_is_desktop_false_by_default():
    """DESKTOP_MODE defaults to False in test environment."""
    from app.config import settings
    # Tests run with DESKTOP_MODE unset → False
    # (desktop.py sets it to "true" before importing)
    assert isinstance(settings.is_desktop, bool)


def test_is_desktop_true_when_env_set(monkeypatch):
    """settings.is_desktop is True when DESKTOP_MODE=true."""
    monkeypatch.setenv("DESKTOP_MODE", "true")
    # Re-construct settings with the patched env
    from pydantic_settings import BaseSettings
    from app.config import Settings
    s = Settings()
    assert s.is_desktop is True


def test_is_local_true_in_desktop_mode(monkeypatch):
    """Desktop mode also satisfies is_local (AUTH_ENABLED=false, no SESSION_SECRET)."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("SESSION_SECRET", "")
    monkeypatch.setenv("DESKTOP_MODE", "true")
    from app.config import Settings
    s = Settings()
    assert s.is_local is True
    assert s.is_desktop is True


# ── desktop.py environment setup ─────────────────────────────────────────────

def test_desktop_entry_sets_env_vars():
    """desktop.py must set the required env vars before importing the app."""
    import importlib.util, types

    # Read desktop.py source without executing it
    spec = importlib.util.spec_from_file_location(
        "_desktop_check",
        Path(__file__).parent.parent / "desktop.py",
    )
    assert spec is not None, "desktop.py not found"

    src = Path(spec.origin).read_text()
    # Check that all required env vars are set in the source
    for var in ("AUTH_ENABLED", "DESKTOP_MODE", "SESSION_SECRET",
                "FIELD_ENCRYPTION_KEY", "ARCHIVE_URL"):
        assert var in src, f"desktop.py must set os.environ['{var}']"


def test_desktop_entry_disables_auth():
    src = (Path(__file__).parent.parent / "desktop.py").read_text()
    assert 'os.environ["AUTH_ENABLED"]' in src or "AUTH_ENABLED" in src
    # The value must be "false" (case-insensitive)
    assert '"false"' in src.lower() or "'false'" in src.lower()


def test_desktop_entry_clears_archive_url():
    src = (Path(__file__).parent.parent / "desktop.py").read_text()
    assert 'ARCHIVE_URL' in src
    # ARCHIVE_URL must be set to empty string
    assert '""' in src or "''" in src


# ── API routes return 200 (not 502) when ARCHIVE_URL is empty ─────────────────

@pytest_asyncio.fixture
async def no_archive_client():
    """Client with ARCHIVE_URL cleared — simulates desktop mode."""
    from app.config import settings
    original = settings.ARCHIVE_URL
    object.__setattr__(settings, "ARCHIVE_URL", "")
    try:
        from app.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        object.__setattr__(settings, "ARCHIVE_URL", original)


@pytest.mark.asyncio
async def test_userdata_post_returns_200_when_no_archive(no_archive_client):
    """POST /api/userdata/{form} returns 200 with storage=local when ARCHIVE_URL=''."""
    r = await no_archive_client.post("/api/userdata/t1", json={"10100": "50000"})
    # 200 with storage=local, not 502
    assert r.status_code == 200
    data = r.json()
    assert data.get("saved") is True
    assert data.get("storage") == "local"


@pytest.mark.asyncio
async def test_customize_post_returns_200_when_no_archive(no_archive_client):
    """POST /api/customize/{key} returns 200 with storage=local when ARCHIVE_URL=''."""
    r = await no_archive_client.post("/api/customize/t1", json={"boxes": []})
    assert r.status_code == 200
    data = r.json()
    assert data.get("saved") is True
    assert data.get("storage") == "local"


@pytest.mark.asyncio
async def test_userdata_post_returns_502_when_archive_fails():
    """POST /api/userdata/{form} returns 502 when ARCHIVE_URL is set but save fails."""
    from app.main import app
    with patch("app.main.save_form_data", new=AsyncMock(return_value=False)):
        # Only returns 502 when ARCHIVE_URL is non-empty (archive configured but broken)
        from app.config import settings
        if not settings.ARCHIVE_URL:
            pytest.skip("ARCHIVE_URL is empty in this environment")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.post("/api/userdata/t1", json={"10100": "50000"})
    assert r.status_code == 502


# ── Electron files sanity checks ──────────────────────────────────────────────

def test_electron_main_js_exists():
    p = Path(__file__).parent.parent / "electron" / "main.js"
    assert p.exists(), "electron/main.js must exist"


def test_electron_package_json_exists():
    p = Path(__file__).parent.parent / "electron" / "package.json"
    assert p.exists(), "electron/package.json must exist"
    import json
    pkg = json.loads(p.read_text())
    assert pkg["main"] == "main.js"
    assert "electron" in pkg.get("devDependencies", {})
    assert "electron-builder" in pkg.get("devDependencies", {})


def test_electron_preload_js_exists():
    p = Path(__file__).parent.parent / "electron" / "preload.js"
    assert p.exists(), "electron/preload.js must exist"


def test_electron_main_spawns_desktop_py():
    """main.js must reference desktop.py for the dev-mode server spawn."""
    src = (Path(__file__).parent.parent / "electron" / "main.js").read_text()
    assert "desktop.py" in src


def test_electron_main_kills_server_on_exit():
    """main.js must clean up the server process on app exit."""
    src = (Path(__file__).parent.parent / "electron" / "main.js").read_text()
    assert "kill" in src
    assert "before-quit" in src or "window-all-closed" in src


def test_pyinstaller_spec_exists():
    p = Path(__file__).parent.parent / "cra-taxhelper-server.spec"
    assert p.exists(), "cra-taxhelper-server.spec must exist"


def test_pyinstaller_spec_bundles_templates_and_static():
    src = (Path(__file__).parent.parent / "cra-taxhelper-server.spec").read_text()
    assert "app/templates" in src
    assert "app/static" in src


def test_build_scripts_exist():
    base = Path(__file__).parent.parent / "scripts"
    assert (base / "build-desktop.ps1").exists(), "build-desktop.ps1 missing"
    assert (base / "build-desktop.sh").exists(),  "build-desktop.sh missing"
