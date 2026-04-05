from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .discovery_models import DiscoveryResult, DiscoveryRun, DiscoveryRunCreate, DiscoveryRunSummary
from .discovery_persistent_store import store

router = APIRouter(prefix="/api/stateful/v1/discovery", tags=["discovery-assessment-stateful"])


@router.get("/runs", response_model=list[DiscoveryRun])
def list_runs() -> list[DiscoveryRun]:
    return store.list_runs()


@router.post("/runs", response_model=DiscoveryRun, status_code=status.HTTP_201_CREATED)
def create_run(payload: DiscoveryRunCreate) -> DiscoveryRun:
    return store.create_run(payload)


@router.get("/runs/{run_id}", response_model=DiscoveryRun)
def get_run(run_id: str) -> DiscoveryRun:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery run not found")
    return run


@router.get("/runs/{run_id}/results", response_model=list[DiscoveryResult])
def get_run_results(run_id: str) -> list[DiscoveryResult]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery run not found")
    return store.list_results(run_id)


@router.get("/runs/{run_id}/summary", response_model=DiscoveryRunSummary)
def get_run_summary(run_id: str) -> DiscoveryRunSummary:
    summary = store.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discovery run not found")
    return summary
