from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .workspace_models import ExecuteQueryRequest, QueryExecutionResult, SavedQuery, SavedQueryCreate
from .workspace_store import store

router = APIRouter(prefix="/api/v1/workspace", tags=["query-workspace"])


@router.get("/queries", response_model=list[SavedQuery])
def list_queries() -> list[SavedQuery]:
    return store.list_queries()


@router.post("/queries", response_model=SavedQuery, status_code=status.HTTP_201_CREATED)
def create_query(payload: SavedQueryCreate) -> SavedQuery:
    return store.create_query(payload)


@router.get("/queries/{query_id}", response_model=SavedQuery)
def get_query(query_id: str) -> SavedQuery:
    query = store.get_query(query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved query not found")
    return query


@router.post("/execute", response_model=QueryExecutionResult)
def execute_query(payload: ExecuteQueryRequest) -> QueryExecutionResult:
    return store.execute(payload)
