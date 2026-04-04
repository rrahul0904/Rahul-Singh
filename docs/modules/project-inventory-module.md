# Project and Inventory Module

## Purpose
The Project and Inventory Module is the first real product module after demo packaging. It introduces the foundational control-plane concept for the Unified Data Migration Accelerator.

Every later capability depends on it:
- discovery results belong to a project
- conversion artifacts belong to a project
- validation runs belong to a project
- query history belongs to a project

## API Scope

### Project APIs
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/summary`

### Inventory APIs
- `GET /api/v1/projects/{project_id}/inventory`

## Initial Data Strategy
For the first implementation pass, the module uses an in-memory store with seeded sample data so the API can be exercised without a database.

## Next Integration Step
The next code step after this module lands is to register the router in the main FastAPI application and then connect the web layer to these APIs.
