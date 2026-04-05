from __future__ import annotations

from fastapi import FastAPI

from .conversion_persistent_router import router as conversion_stateful_router
from .discovery_persistent_router import router as discovery_stateful_router
from .project_inventory_persistent_router import router as project_inventory_stateful_router
from .validation_persistent_router import router as validation_stateful_router
from .workspace_persistent_router import router as workspace_stateful_router

app = FastAPI(title="Unified Migration Accelerator API - Stateful Phase 2")

app.include_router(project_inventory_stateful_router)
app.include_router(discovery_stateful_router)
app.include_router(conversion_stateful_router)
app.include_router(validation_stateful_router)
app.include_router(workspace_stateful_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "Unified Migration Accelerator API",
        "mode": "stateful-phase2",
        "storage": "json-file",
        "routes": {
            "projects": "/api/stateful/v1/projects",
            "discovery": "/api/stateful/v1/discovery/runs",
            "conversion": "/api/stateful/v1/conversion/items",
            "validation": "/api/stateful/v1/validation/runs",
            "workspace": "/api/stateful/v1/workspace/queries",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "stateful-phase2"}
