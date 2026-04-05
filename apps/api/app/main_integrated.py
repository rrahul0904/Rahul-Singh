from __future__ import annotations

from fastapi import FastAPI

from .conversion_router import router as conversion_router
from .discovery_router import router as discovery_router
from .project_inventory_router import router as project_inventory_router
from .validation_router import router as validation_router
from .workspace_router import router as workspace_router

app = FastAPI(title="Unified Migration Accelerator API - Integrated")

app.include_router(project_inventory_router)
app.include_router(discovery_router)
app.include_router(conversion_router)
app.include_router(validation_router)
app.include_router(workspace_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "Unified Migration Accelerator API",
        "mode": "integrated",
        "modules": [
            "project-inventory",
            "discovery-assessment",
            "conversion-workbench",
            "validation-reconciliation",
            "query-workspace",
        ],
        "routes": {
            "projects": "/api/v1/projects",
            "discovery": "/api/v1/discovery/runs",
            "conversion": "/api/v1/conversion/items",
            "validation": "/api/v1/validation/runs",
            "workspace": "/api/v1/workspace/queries",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "integrated"}
