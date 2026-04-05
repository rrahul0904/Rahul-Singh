from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .validation_models import ValidationResult, ValidationRun, ValidationRunCreate, ValidationSummary
from .validation_store import store

router = APIRouter(prefix="/api/v1/validation", tags=["validation-reconciliation"])


@router.get("/runs", response_model=list[ValidationRun])
def list_runs() -> list[ValidationRun]:
    return store.list_runs()


@router.post("/runs", response_model=ValidationRun, status_code=status.HTTP_201_CREATED)
def create_run(payload: ValidationRunCreate) -> ValidationRun:
    return store.create_run(payload)


@router.get("/runs/{run_id}", response_model=ValidationRun)
def get_run(run_id: str) -> ValidationRun:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation run not found")
    return run


@router.get("/runs/{run_id}/results", response_model=list[ValidationResult])
def get_run_results(run_id: str) -> list[ValidationResult]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation run not found")
    return store.list_results(run_id)


@router.get("/runs/{run_id}/summary", response_model=ValidationSummary)
def get_run_summary(run_id: str) -> ValidationSummary:
    summary = store.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation run not found")
    return summary
