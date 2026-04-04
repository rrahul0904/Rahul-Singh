from __future__ import annotations

from fastapi import FastAPI

from .project_inventory_router import router as project_inventory_router

app = FastAPI(title="Unified Migration Accelerator API - Phase 1")
app.include_router(project_inventory_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "Unified Migration Accelerator API",
        "phase": "phase-1",
        "modules": ["project-inventory"],
        "available_routes": [
            "/health",
            "/api/v1/projects",
            "/api/v1/projects/{project_id}",
            "/api/v1/projects/{project_id}/summary",
            "/api/v1/projects/{project_id}/inventory",
        ],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "phase-1"}
