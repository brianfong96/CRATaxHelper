#!/usr/bin/env bash
# CRA Tax Helper — Local Startup Script (Mac / Linux)
# No configuration needed — just run:
#   chmod +x scripts/start-local.sh
#   ./scripts/start-local.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "========================================"
echo "  CRA Tax Helper — Local Startup"
echo "========================================"
echo ""

# ── Check Docker is installed ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker is not installed."
    echo ""
    echo "Please install Docker Desktop from:"
    echo "  https://www.docker.com/products/docker-desktop/"
    echo "After installing, run this script again."
    exit 1
fi

# ── Check Docker is running ──────────────────────────────────────────────────
if ! docker info &>/dev/null; then
    echo "ERROR: Docker is installed but not running."
    echo ""
    echo "Please start Docker Desktop, wait for it to fully load,"
    echo "then run this script again."
    exit 1
fi

echo "✔ Docker is running"
echo ""
echo "Building and starting CRA Tax Helper..."
echo "(This may take a few minutes the first time)"
echo ""

# No .env needed — all local defaults are hardcoded in docker-compose.yml
docker compose up --build -d

# ── Wait for health check ────────────────────────────────────────────────────
echo ""
echo "Waiting for app to be ready..."
READY=false
for i in $(seq 1 20); do
    sleep 2
    if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
        READY=true
        break
    fi
    echo "  Waiting... ($i/20)"
done

echo ""
if [ "$READY" = true ]; then
    echo "========================================"
    echo "  ✔ CRA Tax Helper is running!"
    echo "========================================"
    echo ""
    echo "  Open your browser and go to:"
    echo "  http://localhost:8080"
    echo ""
    echo "  To stop:      docker compose down"
    echo "  To restart:   ./scripts/start-local.sh"
    echo "  To view logs: docker compose logs -f"
    echo ""
    command -v open &>/dev/null && open http://localhost:8080 || true
    command -v xdg-open &>/dev/null && xdg-open http://localhost:8080 || true
else
    echo "App may still be starting. Try: http://localhost:8080"
    echo "Logs: docker compose logs taxhelper"
fi
