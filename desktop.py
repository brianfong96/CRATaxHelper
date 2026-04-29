"""
CRA Tax Helper — Desktop entry point.

Sets desktop-mode environment variables BEFORE the app modules are
imported (pydantic-settings reads env vars at class construction time).

Electron spawns this script (dev mode) or the PyInstaller-bundled
executable (production) on localhost:8765 and displays it in a native
BrowserWindow.  The FastAPI app code is unchanged — 100% shared with
the web/Docker deployment.
"""

from __future__ import annotations

import os
import sys

# ── Desktop-mode environment ──────────────────────────────────────────────────
# Must be set BEFORE any app.* imports so pydantic-settings picks them up.

os.environ["AUTH_ENABLED"]         = "false"
os.environ["DESKTOP_MODE"]         = "true"
os.environ["SESSION_SECRET"]       = ""
os.environ["FIELD_ENCRYPTION_KEY"] = ""
os.environ["GATEWAY_URL"]          = ""
# Disable archive — localStorage is the primary store in desktop mode.
os.environ["ARCHIVE_URL"]          = ""

os.environ.setdefault("LOCAL_USER_EMAIL", "local@desktop")
os.environ.setdefault("LOCAL_USER_NAME",  "Local User")
os.environ.setdefault("PORT",             "8765")
os.environ.setdefault("LOG_LEVEL",        "WARNING")

# ── Start server ──────────────────────────────────────────────────────────────

import uvicorn  # noqa: E402  (must come after env setup)


def main() -> None:
    port = int(os.environ.get("PORT", "8765"))
    # Import here so env vars are already set before pydantic-settings builds
    # the Settings() singleton.
    from app.main import app  # noqa: PLC0415

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "warning").lower(),
        # Single worker — desktop apps don't need multiple workers.
        workers=1,
    )


if __name__ == "__main__":
    main()
