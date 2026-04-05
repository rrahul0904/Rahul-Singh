# Integrated Product Runbook

## Unified API entrypoint

Use the integrated API app when you want all current product modules available in one process:

```bash
uvicorn apps.api.app.main_integrated:app --host 0.0.0.0 --port 8001
```

## Available module routes

- Project and Inventory: `/api/v1/projects`
- Discovery and Assessment: `/api/v1/discovery/runs`
- Conversion Workbench: `/api/v1/conversion/items`
- Validation and Reconciliation: `/api/v1/validation/runs`
- Query Workspace: `/api/v1/workspace/queries`

## Web routes

- `/project-control-plane`
- `/project-control-plane/new`
- `/project-control-plane/[projectId]`
- `/discovery`
- `/conversion`
- `/validation`
- `/workspace`
- `/operating-center`

## Current nature of the build

This is a unified product shell with module APIs and frontend surfaces. Some flows still rely on seeded in-memory data and fallback behavior while persistence and fuller execution logic are added.
