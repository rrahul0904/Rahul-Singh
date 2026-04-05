from __future__ import annotations

from fastapi import FastAPI

from .project_inventory_persistent_router import router as project_inventory_stateful_router
from .workspace_persistent_router import router as workspace_stateful_router

app = FastAPI(title="Unified Migration Accelerator API - Stateful")

app.include_router(project_inventory_stateful_router)
app.include_router(workspace_stateful_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "Unified Migration Accelerator API",
        "mode": "stateful",
        "routes": {
            "projects": "/api/stateful/v1/projects",
            "workspace_queries": "/api/stateful/v1/workspace/queries",
            "workspace_execute": "/api/stateful/v1/workspace/execute",
        },
        "storage": "json-file",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "stateful"}
