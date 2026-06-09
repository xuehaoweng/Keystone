#!/usr/bin/env bash
set -euo pipefail

# Keystone LLM Gateway — 5-minute Quick Start
# Usage: ./scripts/quickstart.sh

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------
log_info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    echo "Docker is required but not installed. Please install Docker first:"
    echo "  https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &>/dev/null && ! docker-compose version &>/dev/null; then
    echo "Docker Compose is required but not installed."
    exit 1
fi

log_ok "Docker and Docker Compose are available."

# ---------------------------------------------------------------------------
# 2. Prepare .env
# ---------------------------------------------------------------------------
log_info "Preparing environment..."

if [ ! -f .env ]; then
    cp .env.example .env
    log_warn ".env created from .env.example. You may edit it later for production use."
else
    log_info ".env already exists, skipping."
fi

# Ensure at least one provider key placeholder is noted
if grep -q 'OPENAI_API_KEY=sk-\.\.\.' .env; then
    log_warn "No provider API keys configured in .env. Gateway will start but models won't work."
    log_warn "Edit .env and add at least one provider key (e.g., DEEPSEEK_API_KEY)."
fi

# ---------------------------------------------------------------------------
# 3. Build and start
# ---------------------------------------------------------------------------
log_info "Building and starting services (this may take a few minutes)..."

if docker compose version &>/dev/null; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

$COMPOSE up -d --build --force-recreate

# Wait for gateway health
log_info "Waiting for gateway to be ready..."
for i in {1..30}; do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    log_warn "Gateway health check timed out. Check logs with: docker compose logs gateway"
    exit 1
fi

log_ok "Gateway is up and running."

# ---------------------------------------------------------------------------
# 4. Create demo key
# ---------------------------------------------------------------------------
log_info "Creating demo Gateway API Key..."

DEMO_KEY_OUTPUT=$($COMPOSE exec -T gateway python scripts/setup_test_key.py 2>/dev/null || true)

if echo "$DEMO_KEY_OUTPUT" | grep -q "lgw_test_key"; then
    log_ok "Demo key created."
else
    log_warn "Demo key may already exist or setup failed (non-critical)."
fi

# ---------------------------------------------------------------------------
# 5. Print access info
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo -e "  ${GREEN}Keystone LLM Gateway is ready!${NC}"
echo "============================================================"
echo ""
echo "  Admin UI:     http://localhost:8000/login"
echo "  Health:       http://localhost:8000/health"
echo "  OpenAI API:   http://localhost:8000/v1/chat/completions"
echo "  Anthropic:    http://localhost:8000/v1/anthropic"
echo ""
echo "  Demo Key:     lgw_test_key_2026"
echo "  (Enter this in the top-right corner of the Admin UI)"
echo ""
echo "  Next steps:"
echo "    1. Open http://localhost:8000/login"
echo "    2. Enter demo key: lgw_test_key_2026"
echo "    3. Go to 'Test Console' and send your first request"
echo ""
echo "  To add real providers, edit .env and restart:"
echo "    docker compose up -d --force-recreate gateway"
echo ""
echo "============================================================"
