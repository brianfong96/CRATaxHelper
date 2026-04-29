# CRA Tax Helper — Desktop Build Script (Windows)
#
# Prerequisites:
#   pip install pyinstaller
#   npm (Node.js) installed and on PATH
#
# Run from the repo root:
#   .\scripts\build-desktop.ps1
#
# Output: dist-desktop\CRA Tax Helper Setup x.x.x.exe

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  CRA Tax Helper — Desktop Build (Win)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $root

# ── 1. Bundle Python server with PyInstaller ─────────────────────────────────
Write-Host "==> [1/3] Bundling Python server with PyInstaller..." -ForegroundColor Yellow

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "     PyInstaller not found — installing..." -ForegroundColor Gray
    pip install pyinstaller --quiet
}

# Clean previous build
if (Test-Path "dist-server") { Remove-Item "dist-server" -Recurse -Force }
if (Test-Path "build")       { Remove-Item "build"       -Recurse -Force }

pyinstaller cra-taxhelper-server.spec `
    --distpath dist-server `
    --workpath build-pyinstaller `
    --noconfirm

if (-not (Test-Path "dist-server\cra-taxhelper-server.exe")) {
    Write-Error "PyInstaller build failed — cra-taxhelper-server.exe not found"
    exit 1
}
Write-Host "     Server bundled → dist-server\cra-taxhelper-server.exe" -ForegroundColor Green

# ── 2. Install Electron dependencies ─────────────────────────────────────────
Write-Host ""
Write-Host "==> [2/3] Installing Electron dependencies..." -ForegroundColor Yellow
Set-Location "$root\electron"
npm install --prefer-offline --loglevel error
Set-Location $root
Write-Host "     Electron deps ready" -ForegroundColor Green

# ── 3. Build Electron installer ───────────────────────────────────────────────
Write-Host ""
Write-Host "==> [3/3] Building Electron installer (Windows NSIS)..." -ForegroundColor Yellow
Set-Location "$root\electron"
npm run build:win
Set-Location $root

$installer = Get-ChildItem "dist-desktop\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($installer) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Build complete!" -ForegroundColor Green
    Write-Host "  Installer: $($installer.FullName)" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Error "Installer not found in dist-desktop\ — check electron-builder output above"
}
