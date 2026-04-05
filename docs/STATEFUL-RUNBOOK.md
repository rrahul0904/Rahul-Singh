# Stateful Product Runbook

## Purpose
This runbook describes the persistence-backed shell that reduces reliance on in-memory-only demo stores.

## Run the stateful API

```bash
uvicorn apps.api.app.main_stateful:app --host 0.0.0.0 --port 8002
```

## Stateful routes

- `GET /api/stateful/v1/projects`
- `POST /api/stateful/v1/projects`
- `GET /api/stateful/v1/projects/{project_id}`
- `GET /api/stateful/v1/projects/{project_id}/summary`
- `GET /api/stateful/v1/projects/{project_id}/inventory`
- `GET /api/stateful/v1/workspace/queries`
- `POST /api/stateful/v1/workspace/queries`
- `GET /api/stateful/v1/workspace/queries/{query_id}`
- `POST /api/stateful/v1/workspace/execute`

## Storage model

The persistence shell writes JSON files into the API data directory. This is not the final persistence approach, but it gives the product a concrete persistent behavior instead of resetting all state on every process start.
