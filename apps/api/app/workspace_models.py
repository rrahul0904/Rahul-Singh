from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SavedQueryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    sql_text: str = Field(min_length=2)
    owner: str = Field(min_length=2, max_length=80)


class SavedQuery(BaseModel):
    id: str
    name: str
    sql_text: str
    owner: str
    created_at: datetime

    @staticmethod
    def from_create(payload: SavedQueryCreate) -> "SavedQuery":
        return SavedQuery(
            id=f"qry_{uuid4().hex[:10]}",
            name=payload.name,
            sql_text=payload.sql_text,
            owner=payload.owner,
            created_at=datetime.utcnow(),
        )


class ExecuteQueryRequest(BaseModel):
    sql_text: str = Field(min_length=2)


class QueryExecutionResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
