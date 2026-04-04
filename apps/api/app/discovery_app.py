from __future__ import annotations

from fastapi import FastAPI

from .discovery_router import router

app = FastAPI(title="Unified Migration Accelerator - Discovery and Assessment Module")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "module": "discovery-assessment"}
