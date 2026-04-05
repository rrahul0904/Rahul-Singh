from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ConversionItemCreate(BaseModel):
    project_id: str = Field(min_length=3)
    source_object_name: str = Field(min_length=2, max_length=120)
    source_type: str = Field(min_length=2, max_length=50)
    target_type: str = Field(min_length=2, max_length=50)
    created_by: str = Field(min_length=2, max_length=80)


class ConversionItem(BaseModel):
    id: str
    project_id: str
    source_object_name: str
    source_type: str
    target_type: str
    status: Literal["Draft", "Review", "Approved", "Blocked"]
    risk: Literal["Low", "Medium", "High"]
    created_by: str
    created_at: datetime

    @staticmethod
    def from_create(payload: ConversionItemCreate) -> "ConversionItem":
        return ConversionItem(
            id=f"cnv_{uuid4().hex[:10]}",
            project_id=payload.project_id,
            source_object_name=payload.source_object_name,
            source_type=payload.source_type,
            target_type=payload.target_type,
            status="Draft",
            risk="Medium",
            created_by=payload.created_by,
            created_at=datetime.utcnow(),
        )


class ConversionSummary(BaseModel):
    item_id: str
    source_object_name: str
    status: str
    risk: str
    source_type: str
    target_type: str
