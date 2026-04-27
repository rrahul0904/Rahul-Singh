#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# UMA Platform — Quick Test Script
# Verifies the platform boots and responds to API calls.
# ═══════════════════════════════════════════════════════════════

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
info() { echo -e "${BLUE}→${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }

echo "═══════════════════════════════════════════════════════════════"
echo "   UMA PLATFORM — QUICK TEST"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Prerequisites ───────────────────────────────────────
info "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || fail "Docker not installed. Get it at https://docker.com"
command -v curl   >/dev/null 2>&1 || fail "curl not installed"
docker compose version >/dev/null 2>&1 || fail "Docker Compose not available"
pass "Docker + Compose + curl available"
echo ""

# ── Step 2: .env file ────────────────────────────────────────────
info "Checking .env file..."
if [ ! -f .env ]; then
  warn ".env not found — creating from .env.example"
  cp .env.example .env
  # Generate a random SECRET_KEY
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || \
           openssl rand -base64 48 | tr -d '\n' | tr '/+' '_-' | head -c 64)
  if grep -q "SECRET_KEY=" .env; then
    sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env && rm .env.bak 2>/dev/null || true
  fi
  pass ".env created with auto-generated SECRET_KEY"
else
  pass ".env exists"
fi
echo ""

# ── Step 3: Build and start ──────────────────────────────────────
info "Starting containers (this may take 3-5 minutes on first run)..."
docker compose up -d --build
echo ""
pass "Containers started"

# ── Step 4: Wait for API ─────────────────────────────────────────
info "Waiting for API to become ready (up to 90 seconds)..."
for i in $(seq 1 90); do
  if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    pass "API is up (took ${i}s)"
    break
  fi
  if [ $i -eq 90 ]; then
    fail "API didn't respond within 90s. Check logs: docker compose logs api"
  fi
  sleep 1
done
echo ""

# ── Step 5: Health check ─────────────────────────────────────────
info "Testing /api/health..."
HEALTH=$(curl -s http://localhost:8000/api/health)
if echo "$HEALTH" | grep -q '"status":"ok"'; then
  pass "Health endpoint responds"
  echo "   $HEALTH"
else
  fail "Health check failed: $HEALTH"
fi
echo ""

# ── Step 6: Readiness probe ──────────────────────────────────────
info "Testing readiness probe (checks DB connectivity)..."
READY=$(curl -s http://localhost:8000/api/health/ready)
if echo "$READY" | grep -q '"status":"ready"'; then
  pass "Readiness OK — database is reachable"
else
  warn "Readiness degraded: $READY"
fi
echo ""

# ── Step 7: Create admin user ────────────────────────────────────
info "Creating admin user..."
EMAIL="admin@uma.local"
PASSWORD="Admin123!SecureTest"

RESPONSE=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"name\":\"Test Admin\",\"password\":\"$PASSWORD\"}" 2>&1)

if echo "$RESPONSE" | grep -q "access_token"; then
  pass "Admin user created: $EMAIL (password: $PASSWORD)"
  TOKEN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)
elif echo "$RESPONSE" | grep -q "Registration disabled"; then
  warn "Admin already exists — logging in instead"
  RESPONSE=$(curl -s -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
  TOKEN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
  if [ -n "$TOKEN" ]; then
    pass "Logged in successfully"
  else
    warn "Couldn't log in with default credentials — user exists with a different password"
    echo "   Delete the database to reset: docker compose down -v"
  fi
else
  fail "Registration failed: $RESPONSE"
fi
echo ""

# ── Step 8: Authenticated API call ───────────────────────────────
if [ -n "$TOKEN" ]; then
  info "Testing authenticated /api/auth/me..."
  ME=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/me)
  if echo "$ME" | grep -q '"role":"admin"'; then
    pass "Auth works — logged in as admin"
    echo "   $ME"
  else
    fail "Auth check failed: $ME"
  fi
  echo ""

  info "Testing /api/connections (should return empty list)..."
  CONNS=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/connections)
  if echo "$CONNS" | grep -q '^\['; then
    pass "Connections endpoint works"
  else
    warn "Connections endpoint returned: $CONNS"
  fi
  echo ""
fi

# ── Step 9: Frontend ─────────────────────────────────────────────
info "Testing frontend..."
if curl -sf http://localhost:5173 >/dev/null 2>&1; then
  pass "Frontend is serving on http://localhost:5173"
elif curl -sf http://localhost:3000 >/dev/null 2>&1; then
  pass "Frontend is serving on http://localhost:3000"
else
  warn "Frontend not responding — give it 30s more and check: docker compose logs frontend"
fi
echo ""

# ── Done ─────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo -e "   ${GREEN}✅ UMA IS RUNNING${NC}"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Open in your browser:"
echo "   ${BLUE}Frontend UI:${NC}      http://localhost:5173"
echo "   ${BLUE}API docs (Swagger):${NC} http://localhost:8000/docs"
echo "   ${BLUE}Health:${NC}           http://localhost:8000/api/health"
echo ""
echo "Login credentials:"
echo "   ${BLUE}Email:${NC}    $EMAIL"
echo "   ${BLUE}Password:${NC} $PASSWORD"
echo ""
echo "Useful commands:"
echo "   docker compose logs -f api        # Watch backend logs"
echo "   docker compose logs -f frontend   # Watch frontend logs"
echo "   docker compose ps                 # Check status"
echo "   docker compose stop               # Pause everything"
echo "   docker compose down -v            # Wipe everything (data gone)"
echo ""
