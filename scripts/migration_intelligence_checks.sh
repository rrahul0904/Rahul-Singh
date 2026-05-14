#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

./.venv/bin/pytest tests/test_migration_intelligence_backend.py tests/test_route_auth.py -q
./.venv/bin/python -m compileall backend

if command -v docker >/dev/null 2>&1; then
  docker run --rm \
    -v "$ROOT_DIR/frontend:/app" \
    -w /app \
    node:20-alpine \
    sh -lc "corepack enable && corepack prepare pnpm@9.12.3 --activate && pnpm install && pnpm exec vitest run src/pages/MigrationIntelligencePage.test.jsx"
  docker compose build frontend
  docker compose up -d --build api frontend worker
else
  echo "docker is required for frontend checks and live stack verification." >&2
  exit 1
fi

curl -fsS http://127.0.0.1:8000/api/health >/dev/null
curl -fsS http://127.0.0.1:5173 >/dev/null
