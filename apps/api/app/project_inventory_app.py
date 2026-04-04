from __future__ import annotations

from fastapi import FastAPI

from .project_inventory_router import router

app = FastAPI(title="Unified Migration Accelerator - Project Inventory Module")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "module": "project-inventory"}
