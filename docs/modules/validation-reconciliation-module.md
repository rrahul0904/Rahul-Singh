# Validation and Reconciliation Module

## Purpose
The Validation and Reconciliation Module compares migrated outputs against source expectations and highlights mismatches before cutover.

It covers:
- validation runs
- object-level validation results
- severity tagging
- summary metrics for pass/fail status

## Planned API Scope
- `GET /api/v1/validation/runs`
- `POST /api/v1/validation/runs`
- `GET /api/v1/validation/runs/{run_id}`
- `GET /api/v1/validation/runs/{run_id}/results`
- `GET /api/v1/validation/runs/{run_id}/summary`
