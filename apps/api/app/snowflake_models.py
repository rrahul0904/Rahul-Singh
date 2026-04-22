from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class SnowflakeConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    account: str = Field(min_length=2, max_length=120)
    user: str = Field(min_length=2, max_length=120)
    auth_mode: Literal["password", "keypair", "oauth"]
    warehouse: str = Field(min_length=1, max_length=120)
    database: str = Field(min_length=1, max_length=120)
    schema_name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)


class SnowflakeConnection(BaseModel):
    id: str
    name: str
    account: str
    user: str
    auth_mode: str
    warehouse: str
    database: str
    schema_name: str
    role: str
    status: Literal["Created", "Validated", "Failed"]
    created_at: datetime

    @staticmethod
    def from_create(payload: SnowflakeConnectionCreate) -> "SnowflakeConnection":
        return SnowflakeConnection(
            id=f"sfc_{uuid4().hex[:10]}",
            name=payload.name,
            account=payload.account,
            user=payload.user,
            auth_mode=payload.auth_mode,
            warehouse=payload.warehouse,
            database=payload.database,
            schema_name=payload.schema_name,
            role=payload.role,
            status="Created",
            created_at=datetime.utcnow(),
        )


class SnowflakeDestination(BaseModel):
    id: str
    destination_type: Literal[
        "internal_table",
        "external_stage_s3",
        "external_stage_azure",
        "external_stage_gcs",
        "external_table",
        "iceberg_external_volume",
    ]
    name: str
    storage_path: str
    database: str
    schema_name: str


class SnowflakeCapabilitySummary(BaseModel):
    supported_internal_destinations: list[str]
    supported_external_destinations: list[str]
    ai_capabilities: list[str]
