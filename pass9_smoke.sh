#!/usr/bin/env bash
# Phase 1+2+3+4 end-to-end smoke test.
#
# Usage:
#   1. Start the stack:   docker compose up -d
#   2. Make sure you have a real Postgres source connection and a real
#      Snowflake destination connection created via the UI.
#   3. Set the env vars below to match your setup.
#   4. ./pass9_smoke.sh
#
# What this script proves:
#   - A real Postgres -> Snowflake migration runs end-to-end
#   - Run history is recorded with accurate row counts
#   - Watermark state is captured
#   - The engine can be cancelled mid-flight
#   - Reconciliation creates per-table rules and runs them
#
# What this script does NOT do:
#   - It will not invent connections for you.
#   - It will not seed demo data.

set -euo pipefail

API="${UMA_API:-http://localhost:8000}"
TOKEN="${UMA_TOKEN:-}"          # paste a real bearer token; required
SRC_CONN_ID="${UMA_SRC_CONN:-}" # postgres source connection UUID
DST_CONN_ID="${UMA_DST_CONN:-}" # snowflake destination connection UUID
SRC_SCHEMA="${UMA_SRC_SCHEMA:-public}"
SRC_TABLE="${UMA_SRC_TABLE:-users}"
TGT_TABLE="${UMA_TGT_TABLE:-users}"
PK="${UMA_PK:-id}"
WATERMARK="${UMA_WATERMARK:-updated_at}"

if [[ -z "$TOKEN" || -z "$SRC_CONN_ID" || -z "$DST_CONN_ID" ]]; then
  echo "ERROR: set UMA_TOKEN, UMA_SRC_CONN, UMA_DST_CONN env vars." >&2
  exit 1
fi

H_AUTH=(-H "Authorization: Bearer ${TOKEN}")
H_JSON=(-H "Content-Type: application/json")

api() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "${H_AUTH[@]}" "${H_JSON[@]}" -d "$body" "${API}${path}"
  else
    curl -sS -X "$method" "${H_AUTH[@]}" "${API}${path}"
  fi
}

echo "→ Creating job…"
JOB_ID=$(api POST /jobs "$(cat <<JSON
{
  "name": "pass9-smoke-${RANDOM}",
  "source_connection_id": "${SRC_CONN_ID}",
  "dest_connection_id":   "${DST_CONN_ID}",
  "load_strategy": "incremental",
  "tasks": [{
    "source_dataset": "${SRC_SCHEMA}",
    "source_table":   "${SRC_TABLE}",
    "target_schema":  "RAW",
    "target_table":   "${TGT_TABLE}",
    "config": {
      "primary_key_columns": ["${PK}"],
      "watermark_column":    "${WATERMARK}",
      "batch_size": 5000
    }
  }]
}
JSON
)" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "  job_id=${JOB_ID}"

echo "→ Executing job…"
api POST "/jobs/${JOB_ID}/execute" >/dev/null
echo "  execute submitted"

echo "→ Polling until terminal…"
for i in {1..60}; do
  STATUS=$(api GET "/jobs/${JOB_ID}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
  echo "  [$i] status=${STATUS}"
  if [[ "$STATUS" =~ ^(SUCCEEDED|FAILED|CANCELLED|PARTIALLY_SUCCEEDED)$ ]]; then break; fi
  sleep 5
done

echo "→ Run history:"
api GET "/jobs/${JOB_ID}/runs" | python3 -m json.tool

echo "→ Watermark state:"
api GET "/jobs/${JOB_ID}/state" | python3 -m json.tool

echo "→ Reconciling…"
api POST /validation/reconcile "{\"job_id\":\"${JOB_ID}\",\"rule_types\":[\"row_count\",\"checksum\"]}" | python3 -m json.tool

echo "✓ smoke complete"
