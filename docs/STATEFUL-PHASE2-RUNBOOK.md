# Stateful Phase 2 Runbook

## Purpose
This runbook covers the expanded persistence-backed shell for the core product modules.

## Run the expanded stateful API

```bash
uvicorn apps.api.app.main_stateful_phase2:app --host 0.0.0.0 --port 8003
```

## Stateful routes
- `/api/stateful/v1/projects`
- `/api/stateful/v1/projects/{project_id}`
- `/api/stateful/v1/projects/{project_id}/summary`
- `/api/stateful/v1/projects/{project_id}/inventory`
- `/api/stateful/v1/discovery/runs`
- `/api/stateful/v1/conversion/items`
- `/api/stateful/v1/validation/runs`
- `/api/stateful/v1/workspace/queries`
- `/api/stateful/v1/workspace/execute`

## Current persistence model
JSON files stored in the API data directory back the current stateful shell. This is still an intermediate persistence layer, but it provides durable behavior across more modules than the earlier in-memory-only scaffolds.
