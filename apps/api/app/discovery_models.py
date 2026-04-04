from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class DiscoveryRunCreate(BaseModel):
    project_id: str = Field(min_length=3)
    source_platform: str = Field(min_length=2, max_length=50)
    connector_type: str = Field(min_length=2, max_length=50)
    initiated_by: str = Field(min_length=2, max_length=80)


class DiscoveryRun(BaseModel):
    id: str
    project_id: str
    source_platform: str
    connector_type: str
    status: Literal["Created", "Running", "Completed", "Failed"]
    initiated_by: str
    created_at: datetime

    @staticmethod
    def from_create(payload: DiscoveryRunCreate) -> "DiscoveryRun":
        return DiscoveryRun(
            id=f"run_{uuid4().hex[:10]}",
            project_id=payload.project_id,
            source_platform=payload.source_platform,
            connector_type=payload.connector_type,
            status="Created",
            initiated_by=payload.initiated_by,
            created_at=datetime.utcnow(),
        )


class DiscoveryResult(BaseModel):
    id: str
    run_id: str
    object_type: str
    schema_name: str
    object_name: str
    complexity: Literal["Low", "Medium", "High"]
    dependency_count: int


class DiscoveryRunSummary(BaseModel):
    run_id: str
    object_count: int
    high_complexity_count: int
    dependency_edges: int
