# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for CRA Tax Helper desktop server.
#
# Usage (from repo root):
#   pyinstaller cra-taxhelper-server.spec
#
# Output: dist-server/cra-taxhelper-server(.exe)
#
# The Electron shell (electron/) then bundles this executable as a resource
# and spawns it on startup.

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ["desktop.py"],
    pathex=[str(Path(".").resolve())],
    binaries=[],
    datas=[
        # Jinja2 templates and static assets must travel with the bundle.
        ("app/templates", "app/templates"),
        ("app/static",    "app/static"),
    ],
    hiddenimports=[
        # uvicorn internals not detected by static analysis
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.uvloop",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        # FastAPI / Starlette internals
        "starlette.templating",
        "starlette.staticfiles",
        "jinja2",
        "jinja2.ext",
        # Pydantic
        "pydantic_settings",
        "pydantic.v1",
        # HTTP + crypto
        "httpx",
        "cryptography.fernet",
        "cryptography.hazmat.backends.openssl",
        "multipart",
        "email.mime.text",
        # Excel export (optional — app handles ImportError gracefully)
        # "openpyxl",
        # PDF filling (optional)
        # "pypdf",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages that are not needed at runtime
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "pytest",
        "IPython",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="cra-taxhelper-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # No terminal window in the packaged app
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="electron/build/icon.ico",  # Uncomment after adding an icon
)
