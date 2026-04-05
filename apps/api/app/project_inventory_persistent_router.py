from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .project_inventory_models import InventoryItem, Project, ProjectCreate, ProjectSummary
from .project_inventory_persistent_store import store

router = APIRouter(prefix="/api/stateful/v1", tags=["project-inventory-stateful"])


@router.get("/projects", response_model=list[Project])
def list_projects() -> list[Project]:
    return store.list_projects()


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate) -> Project:
    return store.create_project(payload)


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("/projects/{project_id}/summary", response_model=ProjectSummary)
def get_project_summary(project_id: str) -> ProjectSummary:
    summary = store.get_summary(project_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return summary


@router.get("/projects/{project_id}/inventory", response_model=list[InventoryItem])
def list_project_inventory(project_id: str) -> list[InventoryItem]:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return store.list_inventory_for_project(project_id)
