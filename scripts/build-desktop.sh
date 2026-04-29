#!/usr/bin/env bash
# CRA Tax Helper — Desktop Build Script (macOS / Linux)
#
# Prerequisites:
#   pip install pyinstaller
#   Node.js + npm installed
#
# Run from the repo root:
#   ./scripts/build-desktop.sh [mac|linux|all]   (default: auto-detect)
#
# Output:
#   macOS:  dist-desktop/CRA Tax Helper-x.x.x.dmg
#   Linux:  dist-desktop/CRA Tax Helper-x.x.x.AppImage

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Determine target platform
TARGET="${1:-auto}"
if [ "$TARGET" = "auto" ]; then
    case "$(uname -s)" in
        Darwin) TARGET="mac"   ;;
        Linux)  TARGET="linux" ;;
        *)      TARGET="all"   ;;
    esac
fi

echo ""
echo "========================================"
echo "  CRA Tax Helper — Desktop Build ($TARGET)"
echo "========================================"
echo ""

# ── 1. Bundle Python server with PyInstaller ─────────────────────────────────
echo "==> [1/3] Bundling Python server with PyInstaller..."

if ! command -v pyinstaller &>/dev/null; then
    echo "     PyInstaller not found — installing..."
    pip install pyinstaller --quiet
fi

rm -rf dist-server build-pyinstaller

pyinstaller cra-taxhelper-server.spec \
    --distpath dist-server \
    --workpath build-pyinstaller \
    --noconfirm

if [ ! -f "dist-server/cra-taxhelper-server" ]; then
    echo "ERROR: PyInstaller build failed — cra-taxhelper-server not found" >&2
    exit 1
fi

chmod +x dist-server/cra-taxhelper-server
echo "     Server bundled → dist-server/cra-taxhelper-server"

# ── 2. Install Electron dependencies ─────────────────────────────────────────
echo ""
echo "==> [2/3] Installing Electron dependencies..."
cd "$ROOT/electron"
npm install --prefer-offline --loglevel error
cd "$ROOT"
echo "     Electron deps ready"

# ── 3. Build Electron package ─────────────────────────────────────────────────
echo ""
echo "==> [3/3] Building Electron package ($TARGET)..."
cd "$ROOT/electron"
npm run "build:$TARGET"
cd "$ROOT"

echo ""
echo "========================================"
echo "  Build complete! Output in dist-desktop/"
ls -lh dist-desktop/ 2>/dev/null || true
echo "========================================"
