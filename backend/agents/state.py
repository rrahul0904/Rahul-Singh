from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class MigrationState(BaseModel):
    project_id: Optional[str] = None
    run_id: str
    user_id: Optional[str] = None
    request_text: str = ""
    source_connection_id: Optional[str] = None
    target_connection_id: Optional[str] = None
    source_type: str = ""
    target_type: str = "snowflake"
    schemas: list[str] = Field(default_factory=list)
    migration_type: str = "full_load"
    sla: Optional[str] = None
    data_volume_tb: float = 0.0

    discovered_objects: list[dict[str, Any]] = Field(default_factory=list)
    source_profile: dict[str, Any] = Field(default_factory=dict)
    complexity_report: dict[str, Any] = Field(default_factory=dict)
    ddl_conversions: list[dict[str, Any]] = Field(default_factory=list)
    sql_conversions: list[dict[str, Any]] = Field(default_factory=list)
    load_plan: dict[str, Any] = Field(default_factory=dict)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)
    cost_estimate: dict[str, Any] = Field(default_factory=dict)
    cutover_plan: dict[str, Any] = Field(default_factory=dict)
    snowflake_services: dict[str, Any] = Field(default_factory=dict)

    current_step: str = "not_started"
    status: str = "PENDING"
    errors: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    approved: bool = False


class AgentRunStart(BaseModel):
    request_text: str = (
        "Migrate selected source schemas to Snowflake, estimate cost, create migration plan, "
        "convert DDL, validate parity, and generate cutover checklist."
    )
    project_id: Optional[str] = None
    source_connection_id: Optional[str] = None
    target_connection_id: Optional[str] = None
    source_type: str = "teradata"
    target_type: str = "snowflake"
    schemas: list[str] = Field(default_factory=list)
    migration_type: str = "full_load"
    sla: Optional[str] = None
    data_volume_tb: float = 0.0


class ApprovalRequest(BaseModel):
    approved: bool = True
    comment: str = ""


ConversionJobStatus = Literal[
    "uploaded",
    "analyzing",
    "converting",
    "ai_reviewing",
    "judging",
    "repairing",
    "converted",
    "converted_with_warnings",
    "requires_review",
    "failed",
]


class ConversionJobState(BaseModel):
    job_id: str
    status: ConversionJobStatus
    source_dialect: str = "auto_detect"
    target_dialect: str = "snowflake"
    input_type: str = "sql_file"
    total_files: int = 0
    converted_files_count: int = 0
    failed_files_count: int = 0
    requires_review_count: int = 0
    rules_applied_count: int = 0
    judge_status: str = "not_run"
    snowflake_ready: bool = False
    manual_review_required: bool = False
    source_residue: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)
    readiness_reasons: list[dict[str, Any]] = Field(default_factory=list)
    ai_provider_configured: bool = False
    ai_provider_name: str = "offline"
    ai_model_name: str = "offline"
    ai_review_available: bool = False
    ai_patch_available: bool = False
    validation_status: str = "not_run"
    validation_required: bool = True
    artifacts: dict[str, Any] = Field(default_factory=dict)
    diff_summary: dict[str, Any] = Field(default_factory=dict)
