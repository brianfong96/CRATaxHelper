# CRA Tax Helper — Local Startup Script (Windows PowerShell)
# Run this once to start the app. No configuration needed.
# Double-click or right-click > "Run with PowerShell"

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  CRA Tax Helper — Local Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check Docker is installed ────────────────────────────────────────────────
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Docker is not installed or not on your PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Docker Desktop from https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    Write-Host "After installing, restart this script." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Check Docker is running ──────────────────────────────────────────────────
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is installed but not running." -ForegroundColor Red
    Write-Host ""
    Write-Host "Please start Docker Desktop, wait for it to fully load," -ForegroundColor Yellow
    Write-Host "then run this script again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "✔ Docker is running" -ForegroundColor Green
Write-Host ""
Write-Host "Building and starting CRA Tax Helper..." -ForegroundColor Cyan
Write-Host "(This may take a few minutes the first time)" -ForegroundColor DarkGray
Write-Host ""

# No .env needed — all local defaults are hardcoded in docker-compose.yml
docker compose up --build -d

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Failed to start. See above for details." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Wait for health check ────────────────────────────────────────────────────
Write-Host ""
Write-Host "Waiting for app to be ready..." -ForegroundColor Cyan
$retries = 20
$ready = $false
for ($i = 0; $i -lt $retries; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Write-Host "  Waiting... ($($i+1)/$retries)" -ForegroundColor DarkGray
}

Write-Host ""
if ($ready) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  ✔ CRA Tax Helper is running!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Open your browser and go to:" -ForegroundColor White
    Write-Host "  http://localhost:8080" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  To stop:    docker compose down" -ForegroundColor DarkGray
    Write-Host "  To restart: run this script again" -ForegroundColor DarkGray
    Write-Host "  To view logs: docker compose logs -f" -ForegroundColor DarkGray
    Write-Host ""
    Start-Process "http://localhost:8080"
} else {
    Write-Host "App may still be starting. Try: http://localhost:8080" -ForegroundColor Yellow
    Write-Host "Logs: docker compose logs taxhelper" -ForegroundColor DarkGray
}

Read-Host "Press Enter to exit"
