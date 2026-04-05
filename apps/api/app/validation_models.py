from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ValidationRunCreate(BaseModel):
    project_id: str = Field(min_length=3)
    source_env: str = Field(min_length=2, max_length=50)
    target_env: str = Field(min_length=2, max_length=50)
    initiated_by: str = Field(min_length=2, max_length=80)


class ValidationRun(BaseModel):
    id: str
    project_id: str
    source_env: str
    target_env: str
    status: Literal["Created", "Running", "Completed", "Failed"]
    initiated_by: str
    created_at: datetime

    @staticmethod
    def from_create(payload: ValidationRunCreate) -> "ValidationRun":
        return ValidationRun(
            id=f"val_{uuid4().hex[:10]}",
            project_id=payload.project_id,
            source_env=payload.source_env,
            target_env=payload.target_env,
            status="Created",
            initiated_by=payload.initiated_by,
            created_at=datetime.utcnow(),
        )


class ValidationResult(BaseModel):
    id: str
    run_id: str
    object_name: str
    rule_type: str
    severity: Literal["Low", "Medium", "High"]
    result_status: Literal["Passed", "Warning", "Failed"]


class ValidationSummary(BaseModel):
    run_id: str
    passed_count: int
    warning_count: int
    failed_count: int
