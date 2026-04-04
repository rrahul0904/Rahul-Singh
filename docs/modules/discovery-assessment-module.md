# Discovery and Assessment Module

## Purpose
The Discovery and Assessment Module is the Phase 2 foundation for scanning source systems and turning them into actionable migration scope.

It is responsible for:
- discovery run tracking
- connector-aware metadata collection
- complexity scoring
- dependency mapping
- assessment summary generation

## Planned API Scope
- `GET /api/v1/discovery/runs`
- `POST /api/v1/discovery/runs`
- `GET /api/v1/discovery/runs/{run_id}`
- `GET /api/v1/discovery/runs/{run_id}/results`

## Initial Phase 2 Strategy
This first scaffold introduces the data model and route shape with an in-memory store so later connector work can attach to a stable API contract.
