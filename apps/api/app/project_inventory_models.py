from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=500)
    source_platform: str = Field(min_length=2, max_length=50)
    target_platform: Literal["Snowflake", "Databricks"]
    owner: str = Field(min_length=2, max_length=80)


class Project(BaseModel):
    id: str
    name: str
    description: str
    source_platform: str
    target_platform: str
    owner: str
    status: str
    progress: int
    created_at: datetime

    @staticmethod
    def from_create(payload: ProjectCreate) -> "Project":
        return Project(
            id=f"prj_{uuid4().hex[:10]}",
            name=payload.name,
            description=payload.description,
            source_platform=payload.source_platform,
            target_platform=payload.target_platform,
            owner=payload.owner,
            status="Created",
            progress=0,
            created_at=datetime.utcnow(),
        )


class InventoryItem(BaseModel):
    id: str
    project_id: str
    object_type: str
    schema_name: str
    object_name: str
    status: str
    complexity: Literal["Low", "Medium", "High"]


class ProjectSummary(BaseModel):
    project_id: str
    project_name: str
    total_inventory_items: int
    discovered_tables: int
    discovered_views: int
    items_needing_review: int
