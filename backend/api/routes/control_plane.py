from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.state import ConversionJobState
from core.auth import get_current_user, require_editor
from core.database import get_db
from models import (
    AdvisorCheckResult,
    AdvisorScan,
    AnalyzerComponent,
    AnalyzerDependency,
    Connection,
    ControlPlaneArtifact,
    ControlPlaneJob,
    ControlPlaneRun,
    HumanReviewItem,
    ReplicationError,
    ReplicationJob,
    ReplicationJobTable,
    ReplicationRun,
    ReplicationWatermark,
    SqlConversionMessage,
    User,
)
from services.control_plane import (
    AdvisorService,
    AnalyzerService,
    ControlPlaneService,
    DataContractService,
    MetadataSearchService,
    MigrationIntelligenceControlService,
    ProvisionService,
    RichReportService,
    SqlConversionService,
    ValidationService,
    read_artifact_text,
    redact_secrets,
)
from services.dbt_control_plane import DbtConversionService
from services.brain_review import BrainReviewMaterializer
from services.migration_conversion_brain import MigrationIntelligenceEngine, llm_provider_status
from services.sql_snowflake_conversion import SqlToSnowflakeConversionEngine

router = APIRouter()


class RunCreate(BaseModel):
    name: str = "Migration Control Plane Run"
    workflow_type: str
    source_type: str = ""
    target_type: str = "snowflake"
    source_dialect: str = ""
    target_dialect: str = "snowflake"
    source_connection_id: str | None = None
    target_connection_id: str | None = None
    safety_mode: str = "READ_ONLY"
    artifact_ids: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


class AnalyzeBody(BaseModel):
    artifact_ids: list[str] | None = None


class TranslateBody(BaseModel):
    translator: str | None = None


class AnalyzerRunCreate(RunCreate):
    workflow_type: str = "ETL_BI_ANALYSIS"
    analyzer_type: str = "GENERIC_XML"


class AdvisorScanCreate(BaseModel):
    connection_id: str | None = None
    categories: list[str] = Field(default_factory=list)
    dry_run: bool = True
    name: str = "Snowflake Advisor Scan"


class ProvisionRunCreate(RunCreate):
    workflow_type: str = "SNOWFLAKE_PROVISIONING"


class ApprovalBody(BaseModel):
    approved: bool = False


class ValidationRunCreate(RunCreate):
    workflow_type: str = "DATA_VALIDATION"
    tables: list[str] = Field(default_factory=list)
    ignored_columns: list[str] = Field(default_factory=list)
    max_differences: int = 0
    filters: dict = Field(default_factory=dict)


class CodegenRunCreate(RunCreate):
    workflow_type: str = "PIPELINE_BUILD"
    generation_type: str = "migration_runbook"


class DbtConversionRunCreate(RunCreate):
    workflow_type: str = "DBT_CONVERSION"
    dbt_project_name: str = "uma_migration"
    default_database: str = ""
    default_schema: str = ""
    dbt_profile_name: str | None = None
    model_naming_convention: str = "snake_case"
    default_materialization: str = "view"


class DbtArtifactFactoryCreate(BaseModel):
    name: str = "dbt Model Creation"
    source_run_id: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    generation_type: str = "dbt staging model"
    project_name: str = "uma_migration"
    default_database: str = ""
    default_schema: str = ""
    safety_mode: str = "PLAN_ONLY"
    requirement: str = ""
    config: dict = Field(default_factory=dict)


class ConversionJobCreate(RunCreate):
    workflow_type: str = "SQL_DBT_TO_SNOWFLAKE"
    source_platform: str = "auto_detect"
    target_platform: str = "snowflake"
    input_type: str = "sql_file"


class ConversionValidateBody(BaseModel):
    target_connection_id: str | None = None
    account: str | None = None
    user: str | None = None
    password: str | None = None
    authenticator: str | None = None
    auth_method: str | None = None
    role: str | None = None
    warehouse: str | None = None
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    validation_mode: str = "SNOWFLAKE_READINESS_AND_EXPLAIN"
    run_dbt_deps: bool = False
    run_dbt_parse: bool = True
    run_dbt_compile: bool = True
    run_dbt_test: bool = False
    run_dbt_run: bool = False
    run_sample_validation: bool = False
    approved_sample_validation: bool = False


class ConversionAiReviewBody(BaseModel):
    provider: str | None = None


class ConversionAiPatchBody(BaseModel):
    provider: str | None = None
    selected_file: str | None = None
    original_sql: str | None = None
    converted_sql: str | None = None
    diff: str | None = None
    rules_applied: list[str] = Field(default_factory=list)
    readiness_reasons: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_residue: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)
    dbt_metadata: dict = Field(default_factory=dict)
    rag_context: list[dict] = Field(default_factory=list)


class ConversionCopilotChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConversionPatchBody(BaseModel):
    target_path: str | None = Field(default=None, max_length=500)
    patched_sql: str | None = None
    confirmed: bool = False


class HumanReviewUpdate(BaseModel):
    item_id: str
    status: str = "IN_REVIEW"
    reviewer_comment: str | None = None


class BrainReviewUpdate(BaseModel):
    status: str = "IN_REVIEW"
    reviewer_comment: str | None = None


class RunReplicationLinkBody(BaseModel):
    job_id: str
    relationship: str = "supports_run"


class RunScopeLinkBody(BaseModel):
    scope_type: str
    scope_id: str
    scope_name: str | None = None
    relationship: str = "supports_run"
    metadata: dict = Field(default_factory=dict)


class MetadataSearchBody(BaseModel):
    query: str
    limit: int = 20


class Nl2SqlBody(BaseModel):
    question: str


def artifact_dict(row: ControlPlaneArtifact) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "filename": row.filename,
        "original_filename": row.original_filename,
        "file_type": row.file_type,
        "artifact_category": row.artifact_category,
        "storage_path": row.storage_path,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "checksum_sha256": row.checksum_sha256,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "metadata_json": row.metadata_json or {},
    }


def run_dict(row: ControlPlaneRun) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "workflow_type": row.workflow_type,
        "source_type": row.source_type,
        "target_type": row.target_type,
        "source_dialect": row.source_dialect,
        "target_dialect": row.target_dialect,
        "source_connection_id": row.source_connection_id,
        "target_connection_id": row.target_connection_id,
        "safety_mode": row.safety_mode,
        "status": row.status,
        "current_phase": row.current_phase,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "error_message": row.error_message,
        "summary_json": row.summary_json or {},
        "metrics_json": row.metrics_json or {},
        "config_json": row.config_json or {},
        "approval_granted": row.approval_granted,
    }


DIALECT_CAPABILITY_MATRIX = [
    {
        "dialect": "BigQuery",
        "status": "partial_mature_for_tested_patterns",
        "snowflake_target": "partial",
        "coverage": ["date/time functions", "array UNNEST/FLATTEN patterns", "SAFE_CAST", "QUALIFY", "dbt macro preservation"],
        "limits": ["Stored procedures require review/classification", "Untested edge cases remain blocked by validation gates"],
    },
    {"dialect": "Postgres", "status": "partial", "snowflake_target": "partial", "coverage": ["common DDL/DML and select rewrites"], "limits": ["Procedural SQL and extensions require review"]},
    {"dialect": "MySQL", "status": "partial", "snowflake_target": "partial", "coverage": ["common DDL/DML and select rewrites"], "limits": ["Session variables and procedures require review"]},
    {"dialect": "SQL Server", "status": "partial", "snowflake_target": "partial", "coverage": ["common T-SQL DDL/DML patterns"], "limits": ["T-SQL procedures, temp-table scripts, and dynamic SQL require review"]},
    {"dialect": "Oracle", "status": "partial", "snowflake_target": "partial", "coverage": ["common DDL/DML patterns"], "limits": ["PL/SQL packages and procedural code require review"]},
    {"dialect": "Teradata", "status": "experimental_partial", "snowflake_target": "experimental", "coverage": ["classification and limited SQL rewrite"], "limits": ["BTEQ/procedure semantics require review"]},
    {"dialect": "Databricks/Spark", "status": "experimental_partial", "snowflake_target": "experimental", "coverage": ["classification and limited SQL rewrite"], "limits": ["Spark-specific functions and notebooks require review"]},
    {"dialect": "Stored procedures", "status": "review_classification_only", "snowflake_target": "blocked_until_reviewed", "coverage": ["object classification and risk reporting"], "limits": ["Not marked production-ready unless tested conversion evidence exists"]},
]


def initial_conversion_job_state(run: ControlPlaneRun, *, total_files: int = 0) -> dict:
    return ConversionJobState(
        job_id=run.id,
        status="uploaded",
        source_dialect=run.source_dialect or "auto_detect",
        target_dialect=run.target_dialect or "snowflake",
        input_type=(run.config_json or {}).get("input_type") or "sql_file",
        total_files=total_files,
        artifacts={"uploaded_artifact_count": total_files},
        manual_review_required=total_files == 0,
    ).model_dump()


def job_dict(row: ControlPlaneJob) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "module": row.module,
        "phase": row.phase,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "logs_redacted": row.logs_redacted,
        "error_message": row.error_message,
        "output_json": row.output_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _artifact_id_map(artifacts: list[ControlPlaneArtifact] | None = None) -> dict[str, ControlPlaneArtifact]:
    return {artifact.id: artifact for artifact in artifacts or []}


def _norm_artifact_name(value: str | None) -> str:
    text = (value or "").strip().lower().replace("\\", "/")
    if text.startswith("converted/"):
        text = text.removeprefix("converted/")
    return Path(text).name or text


def _artifact_matches(artifact: ControlPlaneArtifact, value: str | None) -> bool:
    if not value:
        return False
    haystack = {
        (artifact.original_filename or "").lower(),
        (artifact.filename or "").lower(),
        _norm_artifact_name(artifact.original_filename),
        _norm_artifact_name(artifact.filename),
    }
    needle = value.lower()
    needle_base = _norm_artifact_name(value)
    return needle in haystack or needle_base in haystack or any(name and name in needle for name in haystack)


def _resolve_review_artifacts(
    row: HumanReviewItem,
    artifacts: list[ControlPlaneArtifact] | None = None,
) -> tuple[ControlPlaneArtifact | None, ControlPlaneArtifact | None]:
    metadata = getattr(row, "metadata_json", None) or {}
    artifacts = sorted(artifacts or [], key=lambda item: item.created_at or datetime.min, reverse=True)
    by_id = _artifact_id_map(artifacts)

    source = by_id.get(metadata.get("source_artifact_id"))
    generated = by_id.get(metadata.get("generated_artifact_id"))
    source_text = metadata.get("source_object") or metadata.get("source_file") or metadata.get("file_name") or ""
    target_text = metadata.get("target_object") or metadata.get("target_file") or ""

    if not source:
        source = next(
            (
                artifact
                for artifact in artifacts
                if artifact.artifact_category in {"SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT", "REQUIREMENTS"}
                and (_artifact_matches(artifact, source_text) or not source_text)
            ),
            None,
        )
    if not source:
        source = next(
            (
                artifact
                for artifact in artifacts
                if artifact.artifact_category in {"SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT", "REQUIREMENTS"}
            ),
            None,
        )
    if not generated:
        generated = next(
            (
                artifact
                for artifact in artifacts
                if artifact.artifact_category in {"GENERATED_DBT", "GENERATED_SQL"}
                and (_artifact_matches(artifact, target_text) or _artifact_matches(artifact, source_text))
            ),
            None,
        )
    return source, generated


def human_review_dict(
    row: HumanReviewItem,
    run: ControlPlaneRun | None = None,
    artifacts: list[ControlPlaneArtifact] | None = None,
) -> dict:
    metadata = getattr(row, "metadata_json", None) or {}
    source_artifact, generated_artifact = _resolve_review_artifacts(row, artifacts)
    normalized_status = {
        "OPEN": "NEW",
        "REVIEWED": "RESOLVED",
        "APPROVAL_REQUIRED": "IN_REVIEW",
        "REQUIRES_REVIEW": "IN_REVIEW",
    }.get(row.status, row.status or "NEW")
    normalized_severity = {
        "WARN": "MEDIUM",
        "WARNING": "MEDIUM",
        "ERROR": "HIGH",
        "CRITICAL": "CRITICAL",
        "INFO": "INFO",
    }.get(row.severity, row.severity or "INFO")
    return {
        "id": row.id,
        "run_id": row.run_id,
        "run_name": run.name if run else metadata.get("run_name", ""),
        "workflow_type": run.workflow_type if run else metadata.get("workflow_type", ""),
        "current_phase": run.current_phase if run else metadata.get("current_phase", ""),
        "item_type": row.item_type,
        "severity": normalized_severity,
        "title": row.title,
        "description": row.description,
        "reason": metadata.get("reason") or row.description,
        "evidence": metadata.get("evidence") or row.description,
        "recommendation": row.recommendation,
        "status": normalized_status,
        "source_object": metadata.get("source_object") or metadata.get("source_file") or metadata.get("file_name") or "Artifact package",
        "target_object": metadata.get("target_object") or metadata.get("target_file") or metadata.get("target_relation") or "Snowflake target",
        "confidence_score": metadata.get("confidence_score", metadata.get("confidence", 0.72)),
        "owner": metadata.get("owner") or "Unassigned",
        "source_artifact_id": metadata.get("source_artifact_id") or (source_artifact.id if source_artifact else None),
        "generated_artifact_id": metadata.get("generated_artifact_id") or (generated_artifact.id if generated_artifact else None),
        "can_compare_artifacts": bool(source_artifact and generated_artifact),
        "comparison_kind": metadata.get("comparison_view") or ("dbt_source_target_diff" if source_artifact and generated_artifact else ""),
        "reviewer_comment": row.reviewer_comment,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _artifact_groups(artifacts: list[ControlPlaneArtifact]) -> dict:
    groups = {
        "source_artifacts": [],
        "generated_artifacts": [],
        "reports": [],
        "validation_artifacts": [],
        "packages": [],
        "other": [],
    }
    for artifact in artifacts:
        row = artifact_dict(artifact)
        category = artifact.artifact_category or ""
        if category in {"SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT", "REQUIREMENTS"}:
            groups["source_artifacts"].append(row)
        elif category in {"GENERATED_SQL", "GENERATED_DBT", "GENERATED_SQL_PATCH", "REVIEW_SQL", "REVIEW_DBT"}:
            groups["generated_artifacts"].append(row)
        elif category in {"REPORT", "ADVISOR_RESULT", "DATA_CONTRACT"}:
            groups["reports"].append(row)
        elif category in {"VALIDATION_RESULT"}:
            groups["validation_artifacts"].append(row)
        elif category in {"CONVERSION_PACKAGE"}:
            groups["packages"].append(row)
        else:
            groups["other"].append(row)
    return groups


def _readiness_score(run: ControlPlaneRun, blockers: list[dict]) -> int:
    summary = run.summary_json or {}
    state = summary.get("job_state") or {}
    if isinstance(summary.get("readiness_score"), (int, float)):
        return int(summary["readiness_score"])
    score = 100
    if run.status in {"FAILED", "BLOCKED"}:
        score -= 40
    if run.status in {"REQUIRES_REVIEW", "APPROVAL_REQUIRED"}:
        score -= 20
    if state.get("snowflake_ready") is False:
        score -= 20
    if state.get("validation_required", True):
        score -= 20
    score -= min(30, len(blockers) * 5)
    return max(0, min(100, score))


def _next_recommended_action(run: ControlPlaneRun, blockers: list[dict]) -> str:
    summary = run.summary_json or {}
    validation = summary.get("validation") or {}
    state = summary.get("job_state") or {}
    if run.status == "FAILED":
        return "Open failed jobs and review logs before rerunning this migration run."
    if blockers:
        return blockers[0].get("recommendation") or "Resolve the top Brain Review blocker, then rerun validation."
    if validation and not validation.get("validation_passed"):
        return "Run dbt compile and Snowflake validation, or request an explicit Brain Review waiver."
    if state.get("validation_required", True):
        return "Run Validate/Compile before requesting Snowflake-ready package download."
    if state.get("snowflake_ready"):
        return "Download the Snowflake-ready package or move to controlled deployment approval."
    return "Upload source artifacts, run conversion, then inspect the generated review workspace."


def _package_blocked_reason(state: dict, validation: dict, open_review: list[HumanReviewItem]) -> str:
    if open_review:
        critical = [item for item in open_review if (item.severity or "").upper() == "CRITICAL" or (item.status or "").upper() == "BLOCKED"]
        if critical:
            return "Open critical Brain Review blockers must be approved or resolved before package download."
        return "Open Brain Review decisions must be approved or resolved before package download."
    if state.get("judge_status") == "failed":
        return "Conversion judge failed; rerun conversion or resolve the judge blockers."
    if state.get("snowflake_ready") is not True:
        return "Conversion output is not marked Snowflake-ready by the backend job state."
    if validation.get("dbt_compile_passed") is False or validation.get("validation_status") in {"not_run", "credentials_required", "compile_passed"}:
        return "dbt compile evidence alone is insufficient; run real Snowflake validation."
    if validation.get("validation_status") not in {"validation_passed", "waived_by_brain_review"}:
        return f"Snowflake validation gate is {validation.get('validation_status') or 'not_run'}."
    return "Snowflake-ready package requires passed conversion, Brain Review, dbt compile, and Snowflake validation gates."


def _has_approved_snowflake_validation_waiver(review_items: list[HumanReviewItem]) -> bool:
    for item in review_items:
        status = (item.status or "").upper()
        metadata = item.metadata_json or {}
        if status != "APPROVED":
            continue
        if item.item_type in {"SNOWFLAKE_VALIDATION_WAIVER", "VALIDATION_WAIVER"}:
            return True
        if metadata.get("waiver_scope") in {"snowflake_validation", "snowflake_ready_package"}:
            return True
    return False


def _conversion_state_ready_except_validation(state: dict) -> bool:
    return (
        state.get("judge_status") != "failed"
        and not state.get("source_residue")
        and int(state.get("rules_applied_count") or 0) > 0
    )


def _run_detail_payload(
    run: ControlPlaneRun,
    artifacts: list[ControlPlaneArtifact],
    jobs: list[ControlPlaneJob],
    review_items: list[HumanReviewItem],
    messages: list[SqlConversionMessage],
    replication_jobs: list[dict] | None = None,
) -> dict:
    summary = run.summary_json or {}
    state = summary.get("job_state") or initial_conversion_job_state(run, total_files=len([a for a in artifacts if a.artifact_category.startswith("SOURCE")]))
    open_review = [item for item in review_items if (item.status or "").upper() not in {"APPROVED", "RESOLVED"}]
    failed_jobs = [job for job in jobs if job.status == "FAILED"]
    validation = summary.get("validation") or {
        "validation_status": "not_run",
        "validation_passed": False,
        "message": "dbt compile/Snowflake validation has not run for this migration run.",
    }
    approved_validation_waiver = _has_approved_snowflake_validation_waiver(review_items)
    effective_validation = dict(validation)
    effective_state = dict(state)
    if approved_validation_waiver and validation.get("validation_status") != "validation_passed":
        effective_validation.update(
            {
                "validation_status": "waived_by_brain_review",
                "snowflake_validation_status": "waived_by_brain_review",
                "validation_passed": True,
                "validation_waiver": "approved_brain_review",
            }
        )
        effective_state["validation_status"] = "waived_by_brain_review"
        if _conversion_state_ready_except_validation(effective_state):
            effective_state["snowflake_ready"] = True
    effective_package_artifact_id = summary.get("download_artifact_id") or (summary.get("review_package_artifact_id") if approved_validation_waiver else None)
    package_available = bool(
        effective_package_artifact_id
        and not open_review
        and effective_state.get("snowflake_ready") is True
        and effective_validation.get("validation_status") in {"validation_passed", "waived_by_brain_review"}
        and effective_validation.get("dbt_compile_passed") is not False
    )
    blockers = [
        {
            "id": item.id,
            "type": item.item_type,
            "severity": item.severity,
            "title": item.title,
            "recommendation": item.recommendation,
            "status": item.status,
        }
        for item in open_review
    ] + [
        {
            "id": job.id,
            "type": "FAILED_JOB",
            "severity": "HIGH",
            "title": f"{job.module} {job.phase} failed",
            "recommendation": "Review redacted logs and rerun after fixing the underlying error.",
            "status": job.status,
        }
        for job in failed_jobs
    ]
    if not validation.get("validation_passed"):
        blockers.append({
            "id": "validation_gate",
            "type": "VALIDATION_GATE",
            "severity": "HIGH",
            "title": "dbt compile/Snowflake validation gate is not passed",
            "recommendation": "Run Validate/Compile with Snowflake target credentials or approve an explicit waiver.",
            "status": validation.get("validation_status") or "not_run",
        })
    readiness = _readiness_score(run, blockers)
    return {
        "run": run_dict(run),
        "source_target": {
            "source_type": run.source_type,
            "source_dialect": run.source_dialect or "auto_detect",
            "source_connection_id": run.source_connection_id,
            "target_type": run.target_type or "snowflake",
            "target_dialect": run.target_dialect or "snowflake",
            "target_connection_id": run.target_connection_id,
        },
        "run_status": run.status,
        "readiness_score": readiness,
        "next_recommended_action": _next_recommended_action(run, blockers),
        "gates": {
            "conversion": state.get("status") or run.status,
            "brain_review": "passed" if not open_review else "blocked",
            "dbt_compile": effective_validation.get("validation_status") or "not_run",
            "snowflake_validation": effective_validation.get("snowflake_validation_status") or effective_validation.get("validation_status") or "not_run",
            "snowflake_ready_package": "available" if package_available else "blocked",
        },
        "artifact_groups": _artifact_groups(artifacts),
        "source_artifacts": _artifact_groups(artifacts)["source_artifacts"],
        "conversion_jobs": [job_dict(job) for job in jobs if job.module in {"CONVERSION", "SQL_CONVERSION", "DBT_CONVERSION"} or "CONVERT" in job.phase],
        "generated_artifacts": _artifact_groups(artifacts)["generated_artifacts"],
        "brain_review_decisions": [human_review_dict(item, run, artifacts) for item in review_items],
        "validation": effective_validation,
        "snowflake_validation": effective_validation,
        "connection_readiness_checks": effective_validation.get("connection_readiness") or [],
        "permission_check_results": effective_validation.get("permission_checks") or [],
        "syntax_validation_results": effective_validation.get("syntax_results") or [],
        "latest_validation_errors": (effective_validation.get("compile_errors") or []) + (effective_validation.get("model_errors") or []),
        "validation_plans_results": effective_validation,
        "replication_jobs": replication_jobs or summary.get("replication_jobs") or [],
        "schema_drift_status": summary.get("schema_drift_status") or {"status": "not_linked", "message": "No schema drift run is linked to this migration run."},
        "reports": _artifact_groups(artifacts)["reports"],
        "blockers": blockers,
        "jobs": [job_dict(job) for job in jobs],
        "messages": [
            {
                "id": row.id,
                "severity": row.severity,
                "file_name": row.file_name,
                "statement_index": row.statement_index,
                "message": row.message,
                "recommendation": row.recommendation,
            }
            for row in messages
        ],
        "package": {
            "download_artifact_id": effective_package_artifact_id if package_available else None,
            "review_package_artifact_id": summary.get("review_package_artifact_id"),
            "blocked": not package_available,
            "blocked_reason": _package_blocked_reason(effective_state, effective_validation, open_review) if not package_available else "",
        },
        "capabilities": {
            "workflow_runtime": "UMA deterministic workflow",
            "rag": summary.get("rag_status") or {"status": "dev_or_not_indexed", "message": "RAG is available only when a run-scoped index is ready."},
            "mcp": {"status": "internal_tool_registry", "message": "UMA tools are exposed as an internal authenticated registry unless a remote MCP server is configured."},
        },
    }


async def _replication_evidence_for_run(db: AsyncSession, run: ControlPlaneRun) -> list[dict]:
    summary = run.summary_json or {}
    job_ids = sorted(set(str(item) for item in (summary.get("replication_job_ids") or []) if item))
    if not job_ids:
        return []
    jobs = (
        await db.execute(select(ReplicationJob).where(ReplicationJob.id.in_(job_ids)).order_by(ReplicationJob.created_at.desc()))
    ).scalars().all()
    if not jobs:
        return []
    runs = (
        await db.execute(select(ReplicationRun).where(ReplicationRun.job_id.in_([job.id for job in jobs])).order_by(ReplicationRun.created_at.desc()))
    ).scalars().all()
    tables = (
        await db.execute(select(ReplicationJobTable).where(ReplicationJobTable.job_id.in_([job.id for job in jobs])))
    ).scalars().all()
    watermarks = (
        await db.execute(select(ReplicationWatermark).where(ReplicationWatermark.job_id.in_([job.id for job in jobs])))
    ).scalars().all()
    errors = (
        await db.execute(select(ReplicationError).where(ReplicationError.job_id.in_([job.id for job in jobs])).order_by(ReplicationError.created_at.desc()))
    ).scalars().all()
    runs_by_job: dict[str, list[ReplicationRun]] = {}
    tables_by_job: dict[str, list[ReplicationJobTable]] = {}
    watermarks_by_job: dict[str, list[ReplicationWatermark]] = {}
    errors_by_job: dict[str, list[ReplicationError]] = {}
    for row in runs:
        runs_by_job.setdefault(row.job_id, []).append(row)
    for row in tables:
        tables_by_job.setdefault(row.job_id, []).append(row)
    for row in watermarks:
        watermarks_by_job.setdefault(row.job_id, []).append(row)
    for row in errors:
        errors_by_job.setdefault(row.job_id, []).append(row)
    return [
        {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "sync_mode": job.sync_mode,
            "schedule": job.schedule,
            "latest_error": job.latest_error,
            "last_sync_at": job.last_sync_at.isoformat() if job.last_sync_at else None,
            "table_count": len(tables_by_job.get(job.id, [])),
            "latest_runs": [
                {
                    "id": row.id,
                    "status": row.status,
                    "trigger": row.trigger,
                    "planned_tables": row.planned_tables,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                    "latest_error": row.latest_error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in runs_by_job.get(job.id, [])[:5]
            ],
            "tables": [
                {
                    "id": row.id,
                    "schema_name": row.schema_name,
                    "table_name": row.table_name,
                    "target_schema": row.target_schema,
                    "target_table": row.target_table,
                    "sync_mode": row.sync_mode,
                    "status": row.status,
                    "latest_error": row.latest_error,
                    "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                }
                for row in tables_by_job.get(job.id, [])[:20]
            ],
            "watermarks": [
                {
                    "job_table_id": row.job_table_id,
                    "watermark_column": row.watermark_column,
                    "watermark_value": row.watermark_value,
                    "state_json": row.state_json or {},
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in watermarks_by_job.get(job.id, [])[:20]
            ],
            "errors": [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "category": row.category,
                    "message": row.safe_detail or row.message,
                    "retryable": row.category in {"MFA_SESSION", "network", "control_plane"},
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in errors_by_job.get(job.id, [])[:10]
            ],
            "validation_links": summary.get("replication_validation_links", {}).get(job.id, []),
        }
        for job in jobs
    ]


async def get_run_or_404(db: AsyncSession, run_id: str) -> ControlPlaneRun:
    run = await db.get(ControlPlaneRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


async def artifacts_for_run(db: AsyncSession, run: ControlPlaneRun, explicit_ids: list[str] | None = None) -> list[ControlPlaneArtifact]:
    ids = explicit_ids if explicit_ids is not None else (run.config_json or {}).get("artifact_ids", [])
    service = ControlPlaneService(db)
    if ids:
        artifacts = await service.artifact_ids(ids)
        await service.link_artifacts(artifacts, run.id)
        return artifacts
    rows = (
        await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == run.id))
    ).scalars().all()
    generated_categories = {
        "REPORT",
        "CONVERSION_PACKAGE",
        "GENERATED_SQL",
        "GENERATED_DBT",
        "REVIEW_SQL",
        "REVIEW_DBT",
        "ADVISOR_RESULT",
        "VALIDATION_RESULT",
        "PROVISION_PLAN",
    }
    return [row for row in rows if row.artifact_category not in generated_categories]


@router.post("/artifacts/upload", status_code=201)
async def upload_artifact(
    file: UploadFile = File(...),
    run_id: str | None = None,
    artifact_category: str | None = None,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    artifact = await ControlPlaneService(db).create_artifact_from_upload(file, user, run_id, artifact_category)
    return artifact_dict(artifact)


@router.get("/artifacts")
async def list_artifacts(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(ControlPlaneArtifact).order_by(ControlPlaneArtifact.created_at.desc()).limit(200))
    ).scalars().all()
    return [artifact_dict(row) for row in rows]


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifact = await db.get(ControlPlaneArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    return artifact_dict(artifact)


@router.get("/artifacts/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifact = await db.get(ControlPlaneArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    if artifact.file_type == "json":
        path = Path(artifact.storage_path)
        payload = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return {"artifact": artifact_dict(artifact), "kind": "json", "json": payload}
    if artifact.file_type in {"sql", "yml", "yaml", "txt", "md"}:
        return {"artifact": artifact_dict(artifact), "kind": "text", "text": read_artifact_text(artifact), "line_count": len(read_artifact_text(artifact).splitlines())}
    if artifact.file_type == "zip":
        return {"artifact": artifact_dict(artifact), "kind": "archive", "entries": read_artifact_text(artifact).splitlines()}
    return {"artifact": artifact_dict(artifact), "kind": "binary", "message": "Preview is not available for this artifact type."}


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifact = await db.get(ControlPlaneArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    path = Path(artifact.storage_path)
    if not path.exists():
        raise HTTPException(404, "Artifact file is missing from storage")
    return FileResponse(path, filename=artifact.original_filename, media_type=artifact.mime_type)


@router.get("/control-plane/runs")
async def command_center_runs(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    runs = (
        await db.execute(select(ControlPlaneRun).order_by(ControlPlaneRun.created_at.desc()).limit(200))
    ).scalars().all()
    run_ids = [r.id for r in runs]
    artifacts = []
    jobs = []
    if run_ids:
        artifacts = (
            await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id.in_(run_ids)))
        ).scalars().all()
        jobs = (
            await db.execute(select(ControlPlaneJob).where(ControlPlaneJob.run_id.in_(run_ids)))
        ).scalars().all()
    artifacts_by_run: dict[str, list[ControlPlaneArtifact]] = {}
    for artifact in artifacts:
        artifacts_by_run.setdefault(artifact.run_id, []).append(artifact)
    jobs_by_run: dict[str, list[ControlPlaneJob]] = {}
    for job in jobs:
        jobs_by_run.setdefault(job.run_id, []).append(job)
    rows = []
    for run in runs:
        run_jobs = jobs_by_run.get(run.id, [])
        report = next((a for a in sorted(artifacts_by_run.get(run.id, []), key=lambda a: a.created_at or datetime.min, reverse=True) if a.artifact_category == "REPORT"), None)
        latest = sorted(artifacts_by_run.get(run.id, []), key=lambda a: a.created_at or datetime.min, reverse=True)
        summary = run.summary_json or {}
        messages = summary.get("summary", {}) if isinstance(summary, dict) else {}
        rows.append({
            **run_dict(run),
            "warnings": messages.get("WARN", run.metrics_json.get("WARN", 0) if run.metrics_json else 0),
            "errors": messages.get("ERROR", run.metrics_json.get("ERROR", 0) if run.metrics_json else 0),
            "latest_artifact": artifact_dict(latest[0]) if latest else None,
            "report_artifact": artifact_dict(report) if report else None,
            "job_count": len(run_jobs),
            "failed_job_count": len([j for j in run_jobs if j.status == "FAILED"]),
            "next_action": "Review required" if run.status == "REQUIRES_REVIEW" else ("Approve before apply" if run.status == "APPROVAL_REQUIRED" else "Open report"),
        })
    return rows


@router.get("/control-plane/runs/{run_id}")
async def get_control_plane_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    return run_dict(run)


@router.get("/control-plane/runs/{run_id}/detail")
async def get_control_plane_run_detail(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    await BrainReviewMaterializer(db).materialize_run(run)
    artifacts = (
        await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == run_id).order_by(ControlPlaneArtifact.created_at.desc()))
    ).scalars().all()
    jobs = (
        await db.execute(select(ControlPlaneJob).where(ControlPlaneJob.run_id == run_id).order_by(ControlPlaneJob.created_at.asc()))
    ).scalars().all()
    review_items = (
        await db.execute(select(HumanReviewItem).where(HumanReviewItem.run_id == run_id).order_by(HumanReviewItem.created_at.asc()))
    ).scalars().all()
    messages = (
        await db.execute(select(SqlConversionMessage).where(SqlConversionMessage.run_id == run_id).order_by(SqlConversionMessage.file_name.asc(), SqlConversionMessage.statement_index.asc()))
    ).scalars().all()
    replication_jobs = await _replication_evidence_for_run(db, run)
    return _run_detail_payload(run, list(artifacts), list(jobs), list(review_items), list(messages), replication_jobs)


@router.post("/control-plane/runs/{run_id}/link-replication")
async def link_replication_to_run(run_id: str, body: RunReplicationLinkBody, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    job = await db.get(ReplicationJob, body.job_id)
    if not job:
        raise HTTPException(404, "Replication job not found")
    summary = dict(run.summary_json or {})
    job_ids = sorted(set([*(summary.get("replication_job_ids") or []), job.id]))
    links = list(summary.get("replication_links") or [])
    if not any(link.get("job_id") == job.id for link in links):
        links.append({
            "job_id": job.id,
            "job_name": job.name,
            "relationship": body.relationship or "supports_run",
            "linked_at": datetime.utcnow().isoformat(),
        })
    summary["replication_job_ids"] = job_ids
    summary["replication_links"] = links
    run.summary_json = summary
    await db.commit()
    return {"status": "linked", "run_id": run.id, "job_id": job.id, "replication_job_ids": job_ids}


@router.post("/control-plane/runs/{run_id}/link-scope")
async def link_scope_to_run(run_id: str, body: RunScopeLinkBody, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    summary = dict(run.summary_json or {})
    scope_type = (body.scope_type or "scope").strip().lower()
    link = {
        "scope_type": scope_type,
        "scope_id": body.scope_id,
        "scope_name": body.scope_name or body.scope_id,
        "relationship": body.relationship or "supports_run",
        "metadata": body.metadata or {},
        "linked_at": datetime.utcnow().isoformat(),
    }
    key = f"{scope_type}_links"
    links = list(summary.get(key) or [])
    links = [existing for existing in links if existing.get("scope_id") != body.scope_id]
    links.append(link)
    summary[key] = links
    if scope_type == "schema_drift":
        summary["schema_drift_status"] = {
            "status": link["metadata"].get("status") or "linked",
            "scope_id": body.scope_id,
            "scope_name": link["scope_name"],
            "drift_count": link["metadata"].get("drift_count", 0),
            "latest_checked_at": link["linked_at"],
            "message": link["metadata"].get("message") or "Schema drift evidence is linked to this migration run.",
            "links": links,
        }
    run.summary_json = summary
    await db.commit()
    return {"status": "linked", "run_id": run.id, "scope": link}


@router.get("/control-plane/dialect-capabilities")
async def get_dialect_capabilities(_user: User = Depends(get_current_user)):
    return {
        "target": "snowflake",
        "message": "Dialect support is intentionally conservative; production readiness still requires conversion review and validation gates.",
        "items": DIALECT_CAPABILITY_MATRIX,
    }


@router.get("/control-plane/runs/{run_id}/jobs")
async def get_control_plane_jobs(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_run_or_404(db, run_id)
    rows = (
        await db.execute(select(ControlPlaneJob).where(ControlPlaneJob.run_id == run_id).order_by(ControlPlaneJob.created_at.asc()))
    ).scalars().all()
    return [job_dict(row) for row in rows]


@router.get("/control-plane/runs/{run_id}/artifacts")
async def get_control_plane_artifacts(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await get_run_or_404(db, run_id)
    rows = (
        await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == run_id).order_by(ControlPlaneArtifact.created_at.desc()))
    ).scalars().all()
    return [artifact_dict(row) for row in rows]


@router.get("/brain-review/items")
async def list_brain_review_items(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await BrainReviewMaterializer(db).materialize_recent()
    items = (
        await db.execute(select(HumanReviewItem).order_by(HumanReviewItem.created_at.desc()).limit(300))
    ).scalars().all()
    run_ids = sorted({item.run_id for item in items})
    runs_by_id: dict[str, ControlPlaneRun] = {}
    if run_ids:
        runs = (
            await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.id.in_(run_ids)))
        ).scalars().all()
        runs_by_id = {run.id: run for run in runs}
    artifacts = (
        await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id.in_(run_ids)))
    ).scalars().all() if run_ids else []
    artifacts_by_run: dict[str, list[ControlPlaneArtifact]] = {}
    for artifact in artifacts:
        artifacts_by_run.setdefault(artifact.run_id, []).append(artifact)
    return [human_review_dict(item, runs_by_id.get(item.run_id), artifacts_by_run.get(item.run_id, [])) for item in items]


@router.get("/brain-review/items/{item_id}/comparison")
async def get_brain_review_comparison(
    item_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(HumanReviewItem, item_id)
    if not item:
        raise HTTPException(404, "UMA Brain Review item not found")
    run = await db.get(ControlPlaneRun, item.run_id)
    artifacts = (
        await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == item.run_id))
    ).scalars().all()
    source, generated = _resolve_review_artifacts(item, list(artifacts))
    source_text = read_artifact_text(source) if source else ""
    generated_text = read_artifact_text(generated) if generated else ""
    return {
        "item": human_review_dict(item, run, list(artifacts)),
        "source_artifact": artifact_dict(source) if source else None,
        "generated_artifact": artifact_dict(generated) if generated else None,
        "source_text": source_text,
        "generated_text": generated_text,
        "source_line_count": len(source_text.splitlines()) if source_text else 0,
        "generated_line_count": len(generated_text.splitlines()) if generated_text else 0,
        "message": (
            "Source and generated artifact resolved for side-by-side review."
            if source and generated
            else "UMA could not resolve both source and generated artifacts for this item."
        ),
    }


@router.patch("/brain-review/items/{item_id}")
async def update_brain_review_item(
    item_id: str,
    body: BrainReviewUpdate,
    _user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    allowed = {"NEW", "IN_REVIEW", "APPROVED", "REJECTED", "NEEDS_REWORK", "BLOCKED", "RESOLVED"}
    if body.status not in allowed:
        raise HTTPException(400, f"Status must be one of: {', '.join(sorted(allowed))}")
    item = await db.get(HumanReviewItem, item_id)
    if not item:
        raise HTTPException(404, "UMA Brain Review item not found")
    item.status = body.status
    item.reviewer_comment = body.reviewer_comment
    item.updated_at = datetime.utcnow()
    await db.commit()
    return human_review_dict(item)


@router.post("/sql-conversion/runs", status_code=201)
async def create_sql_conversion_run(body: RunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="SQL_CONVERSION",
        user=user,
        safety_mode=body.safety_mode,
        source_type=body.source_type,
        target_type=body.target_type,
        source_dialect=body.source_dialect,
        target_dialect=body.target_dialect or "snowflake",
        source_connection_id=body.source_connection_id,
        target_connection_id=body.target_connection_id,
        config_json={**body.config, "artifact_ids": body.artifact_ids},
    )
    return run_dict(run)


@router.post("/sql-conversion/runs/{run_id}/analyze")
async def analyze_sql_conversion(run_id: str, body: AnalyzeBody = AnalyzeBody(), user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    artifacts = await artifacts_for_run(db, run, body.artifact_ids)
    if not artifacts:
        raise HTTPException(400, "At least one SQL/DDL artifact is required.")
    report = await SqlConversionService(db).analyze(run, artifacts)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.post("/sql-conversion/runs/{run_id}/translate")
async def translate_sql_conversion(run_id: str, _body: TranslateBody = TranslateBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    report = await SqlConversionService(db).translate(run)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.get("/sql-conversion/runs")
async def list_sql_conversion_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type == "SQL_CONVERSION").order_by(ControlPlaneRun.created_at.desc()))
    ).scalars().all()
    return [run_dict(row) for row in rows]


@router.get("/sql-conversion/runs/{run_id}")
async def get_sql_conversion_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/sql-conversion/runs/{run_id}/messages")
async def get_sql_conversion_messages(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(SqlConversionMessage).where(SqlConversionMessage.run_id == run_id).order_by(SqlConversionMessage.file_name.asc(), SqlConversionMessage.statement_index.asc()))
    ).scalars().all()
    return [
        {
            "id": row.id,
            "file_name": row.file_name,
            "statement_index": row.statement_index,
            "statement_type": row.statement_type,
            "severity": row.severity,
            "message": row.message,
            "source_dialect": row.source_dialect,
            "target_dialect": row.target_dialect,
            "line_start": row.line_start,
            "line_end": row.line_end,
            "recommendation": row.recommendation,
        }
        for row in rows
    ]


@router.get("/sql-conversion/runs/{run_id}/artifacts")
async def get_sql_conversion_artifacts(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_control_plane_artifacts(run_id, _user, db)


@router.get("/sql-conversion/runs/{run_id}/report")
async def get_sql_conversion_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    return run.summary_json or {}


@router.post("/migration-intelligence/runs", status_code=201)
async def create_migration_intelligence_run(body: RunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type=body.workflow_type if body.workflow_type != "SQL_CONVERSION" else "MIGRATION_READINESS",
        user=user,
        safety_mode=body.safety_mode,
        source_type=body.source_type,
        target_type=body.target_type,
        source_dialect=body.source_dialect,
        target_dialect=body.target_dialect or "snowflake",
        source_connection_id=body.source_connection_id,
        target_connection_id=body.target_connection_id,
        config_json={**body.config, "artifact_ids": body.artifact_ids},
    )
    return run_dict(run)


@router.post("/migration-intelligence/runs/{run_id}/execute")
async def execute_migration_intelligence(run_id: str, body: AnalyzeBody = AnalyzeBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    artifacts = await artifacts_for_run(db, run, body.artifact_ids)
    if not artifacts:
        raise HTTPException(400, "At least one uploaded artifact is required.")
    report = await MigrationIntelligenceControlService(db).execute(run, artifacts)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.get("/migration-intelligence/runs")
async def list_migration_intelligence_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type.in_(["MIGRATION_READINESS", "FULL_MIGRATION_PLAN", "DATA_CONTRACT_DISCOVERY", "PIPELINE_BUILD"])).order_by(ControlPlaneRun.created_at.desc()))
    ).scalars().all()
    return [run_dict(row) for row in rows]


@router.get("/migration-intelligence/runs/{run_id}")
async def get_migration_intelligence_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/migration-intelligence/runs/{run_id}/report")
async def get_migration_intelligence_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    return run.summary_json or {}


@router.get("/migration-intelligence/runs/{run_id}/human-review")
async def get_human_review(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(HumanReviewItem).where(HumanReviewItem.run_id == run_id).order_by(HumanReviewItem.created_at.asc()))
    ).scalars().all()
    return [
        human_review_dict(row)
        for row in rows
    ]


@router.post("/migration-intelligence/runs/{run_id}/human-review")
async def update_human_review(run_id: str, body: HumanReviewUpdate, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    item = await db.get(HumanReviewItem, body.item_id)
    if not item or item.run_id != run_id:
        raise HTTPException(404, "Human review item not found")
    item.status = body.status
    item.reviewer_comment = body.reviewer_comment
    await db.commit()
    return {"status": "updated", "item_id": item.id}


@router.post("/analyzer/runs", status_code=201)
async def create_analyzer_run(body: AnalyzerRunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="ETL_BI_ANALYSIS",
        user=user,
        safety_mode=body.safety_mode,
        source_type=body.source_type,
        target_type=body.target_type,
        config_json={**body.config, "artifact_ids": body.artifact_ids, "analyzer_type": body.analyzer_type},
    )
    return run_dict(run)


@router.post("/analyzer/runs/{run_id}/scan")
async def scan_analyzer(run_id: str, body: AnalyzeBody = AnalyzeBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    artifacts = await artifacts_for_run(db, run, body.artifact_ids)
    analyzer_type = (run.config_json or {}).get("analyzer_type", "GENERIC_XML")
    return await AnalyzerService(db).scan(run, artifacts, analyzer_type)


@router.get("/analyzer/runs")
async def list_analyzer_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type == "ETL_BI_ANALYSIS").order_by(ControlPlaneRun.created_at.desc()))
    ).scalars().all()
    return [run_dict(row) for row in rows]


@router.get("/analyzer/runs/{run_id}")
async def get_analyzer_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/analyzer/runs/{run_id}/components")
async def get_analyzer_components(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(AnalyzerComponent).where(AnalyzerComponent.run_id == run_id).order_by(AnalyzerComponent.component_type.asc(), AnalyzerComponent.name.asc()))
    ).scalars().all()
    return [{"id": r.id, "component_type": r.component_type, "name": r.name, "source_file": r.source_file, "metadata_json": r.metadata_json or {}} for r in rows]


@router.get("/analyzer/runs/{run_id}/dependencies")
async def get_analyzer_dependencies(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(AnalyzerDependency).where(AnalyzerDependency.run_id == run_id).order_by(AnalyzerDependency.source_component.asc()))
    ).scalars().all()
    return [{"id": r.id, "source_component": r.source_component, "target_component": r.target_component, "dependency_type": r.dependency_type, "metadata_json": r.metadata_json or {}} for r in rows]


@router.get("/analyzer/runs/{run_id}/report")
async def get_analyzer_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, run_id)).summary_json or {}


@router.post("/advisor/scans", status_code=201)
async def create_advisor_scan(body: AdvisorScanCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    common = ControlPlaneService(db)
    run = await common.create_run(
        name=body.name,
        workflow_type="SNOWFLAKE_ADVISOR",
        user=user,
        safety_mode="READ_ONLY",
        source_type="snowflake",
        target_type="snowflake",
        source_connection_id=body.connection_id,
        target_connection_id=body.connection_id,
        config_json={"categories": body.categories, "dry_run": body.dry_run},
    )
    scan = AdvisorScan(run_id=run.id, connection_id=body.connection_id, status="PENDING", config_json={"categories": body.categories, "dry_run": body.dry_run})
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    return {"id": scan.id, "run_id": run.id, "status": scan.status, "connection_id": scan.connection_id, "config_json": scan.config_json}


@router.post("/advisor/scans/{scan_id}/run")
async def run_advisor_scan(scan_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    scan = await db.get(AdvisorScan, scan_id)
    if not scan:
        raise HTTPException(404, "Advisor scan not found")
    scan.started_at = datetime.utcnow()
    cfg = scan.config_json or {}
    report = await AdvisorService(db).create_scan_results(scan, cfg.get("categories", []), bool(cfg.get("dry_run", True)))
    if scan.run_id:
        run = await db.get(ControlPlaneRun, scan.run_id)
        if run:
            run.status = scan.status
            run.summary_json = report
            run.metrics_json = report.get("scores", {})
            await ControlPlaneService(db).store_json_artifact(run.id, "ADVISOR_RESULT", "snowflake-advisor-report.json", report, run.created_by)
    await db.commit()
    return report


@router.get("/advisor/scans")
async def list_advisor_scans(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AdvisorScan).order_by(AdvisorScan.created_at.desc()))).scalars().all()
    return [{"id": r.id, "run_id": r.run_id, "connection_id": r.connection_id, "status": r.status, "health_score": r.health_score, "security_score": r.security_score, "compute_score": r.compute_score, "storage_score": r.storage_score, "cost_score": r.cost_score, "operational_score": r.operational_score, "migration_readiness_score": r.migration_readiness_score} for r in rows]


@router.get("/advisor/scans/{scan_id}")
async def get_advisor_scan(scan_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.get(AdvisorScan, scan_id)
    if not r:
        raise HTTPException(404, "Advisor scan not found")
    return {"id": r.id, "run_id": r.run_id, "connection_id": r.connection_id, "status": r.status, "health_score": r.health_score, "security_score": r.security_score, "compute_score": r.compute_score, "storage_score": r.storage_score, "cost_score": r.cost_score, "operational_score": r.operational_score, "migration_readiness_score": r.migration_readiness_score, "config_json": r.config_json or {}, "error_message": r.error_message}


@router.get("/advisor/scans/{scan_id}/checks")
async def get_advisor_checks(scan_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AdvisorCheckResult).where(AdvisorCheckResult.scan_id == scan_id))).scalars().all()
    return [{"id": r.id, "check_name": r.check_name, "category": r.category, "severity": r.severity, "status": r.status, "description": r.description, "result_count": r.result_count, "result_sample_json": r.result_sample_json or [], "recommendation": r.recommendation, "raw_sql_redacted": r.raw_sql_redacted} for r in rows]


@router.get("/advisor/scans/{scan_id}/report")
async def get_advisor_report(scan_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scan = await db.get(AdvisorScan, scan_id)
    if not scan:
        raise HTTPException(404, "Advisor scan not found")
    return {"scan": await get_advisor_scan(scan_id, _user, db), "checks": await get_advisor_checks(scan_id, _user, db)}


@router.post("/provision/runs", status_code=201)
async def create_provision_run(body: ProvisionRunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="SNOWFLAKE_PROVISIONING",
        user=user,
        safety_mode=body.safety_mode,
        target_type="snowflake",
        target_connection_id=body.target_connection_id,
        config_json=body.config,
    )
    return run_dict(run)


async def _provision_plan(run_id: str, connected: bool, db: AsyncSession) -> dict:
    run = await get_run_or_404(db, run_id)
    if connected and not run.target_connection_id:
        run.status = "REQUIRES_CONFIGURATION"
        await db.commit()
        raise HTTPException(409, "Connected planning requires a configured Snowflake target connection.")
    plan = ProvisionService(db).generate_plan(run.config_json or {}, connected=connected)
    run.status = "COMPLETED_WITH_WARNINGS" if connected else "COMPLETED"
    run.current_phase = "PLAN_CONNECTED" if connected else "PLAN_LOCAL"
    run.summary_json = plan
    run.metrics_json = {"statement_count": plan["statement_count"]}
    await ControlPlaneService(db).store_json_artifact(run.id, "PROVISION_PLAN", "snowflake-provision-plan.json", plan, run.created_by)
    await db.commit()
    return plan


@router.post("/provision/runs/{run_id}/plan-local")
async def provision_plan_local(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    return await _provision_plan(run_id, False, db)


@router.post("/provision/runs/{run_id}/plan-connected")
async def provision_plan_connected(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    return await _provision_plan(run_id, True, db)


@router.post("/provision/runs/{run_id}/approve")
async def approve_provision(run_id: str, body: ApprovalBody, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    run.approval_granted = bool(body.approved)
    run.approved_by = user.id if body.approved else None
    run.approved_at = datetime.utcnow() if body.approved else None
    run.status = "APPROVAL_REQUIRED" if not body.approved else "PENDING"
    await db.commit()
    return run_dict(run)


@router.post("/provision/runs/{run_id}/apply")
async def apply_provision(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    ControlPlaneService(db).enforce_write_approval(run)
    run.status = "REQUIRES_CONFIGURATION"
    await db.commit()
    return {"status": "REQUIRES_CONFIGURATION", "message": "Provision apply is guarded. Configure a Snowflake executor before applying approved plans.", "executed": False}


@router.get("/provision/runs")
async def list_provision_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type == "SNOWFLAKE_PROVISIONING").order_by(ControlPlaneRun.created_at.desc()))).scalars().all()
    return [run_dict(r) for r in rows]


@router.get("/provision/runs/{run_id}")
async def get_provision_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/provision/runs/{run_id}/plan")
async def get_provision_plan(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, run_id)).summary_json or {}


@router.get("/provision/runs/{run_id}/report")
async def get_provision_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, run_id)).summary_json or {}


@router.post("/validation-center/runs", status_code=201)
async def create_validation_run(body: ValidationRunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="DATA_VALIDATION",
        user=user,
        safety_mode=body.safety_mode,
        source_connection_id=body.source_connection_id,
        target_connection_id=body.target_connection_id,
        config_json={**body.config, "tables": body.tables, "ignored_columns": body.ignored_columns, "max_differences": body.max_differences, "filters": body.filters},
    )
    return run_dict(run)


@router.post("/validation-center/runs/{run_id}/plan")
async def plan_validation(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    plan = ValidationService(db).build_plan(run)
    run.status = "COMPLETED" if plan["tables"] else "COMPLETED_WITH_WARNINGS"
    run.summary_json = plan
    run.metrics_json = {"table_count": len(plan["tables"])}
    await ControlPlaneService(db).store_json_artifact(run.id, "VALIDATION_RESULT", "validation-plan.json", plan, run.created_by)
    await db.commit()
    return plan


@router.post("/validation-center/runs/{run_id}/execute")
async def execute_validation(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    report = await ValidationService(db).execute(run)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.get("/validation-center/runs")
async def list_validation_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type == "DATA_VALIDATION").order_by(ControlPlaneRun.created_at.desc()))).scalars().all()
    return [run_dict(r) for r in rows]


@router.get("/validation-center/runs/{run_id}")
async def get_validation_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/validation-center/runs/{run_id}/results")
async def get_validation_results(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, run_id)).summary_json or {}


@router.get("/validation-center/runs/{run_id}/report")
async def get_validation_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, run_id)).summary_json or {}


@router.post("/conversion/jobs", status_code=201)
async def create_conversion_job(body: ConversionJobCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="SQL_DBT_TO_SNOWFLAKE",
        user=user,
        safety_mode=body.safety_mode,
        source_type=body.source_platform or body.source_type or "auto_detect",
        target_type=body.target_platform or body.target_type or "snowflake",
        source_dialect=body.source_dialect or body.source_platform or "auto_detect",
        target_dialect="snowflake",
        source_connection_id=body.source_connection_id,
        target_connection_id=body.target_connection_id,
        config_json={
            **body.config,
            "artifact_ids": body.artifact_ids,
            "input_type": body.input_type,
            "source_platform": body.source_platform,
            "target_platform": "snowflake",
        },
    )
    run.status = "uploaded"
    run.summary_json = {"job_state": initial_conversion_job_state(run, total_files=0)}
    await db.commit()
    await db.refresh(run)
    return run_dict(run)


@router.post("/conversion/jobs/{job_id}/upload", status_code=201)
async def upload_conversion_artifact(
    job_id: str,
    file: UploadFile = File(...),
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    run = await get_run_or_404(db, job_id)
    artifact = await ControlPlaneService(db).create_artifact_from_upload(file, user, run.id, None)
    artifacts = await artifacts_for_run(db, run, None)
    run.status = "uploaded"
    run.summary_json = {**(run.summary_json or {}), "job_state": initial_conversion_job_state(run, total_files=len(artifacts))}
    await db.commit()
    return artifact_dict(artifact)


@router.post("/conversion/jobs/{job_id}/analyze")
async def analyze_conversion_job(job_id: str, body: AnalyzeBody = AnalyzeBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    artifacts = await artifacts_for_run(db, run, body.artifact_ids)
    if not artifacts:
        raise HTTPException(400, "Upload at least one SQL, DDL, stored procedure, or dbt project artifact before analysis.")
    report = await SqlToSnowflakeConversionEngine(db).analyze(run, artifacts)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.post("/conversion/jobs/{job_id}/convert")
async def convert_conversion_job(job_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    artifacts = await artifacts_for_run(db, run, None)
    if not artifacts:
        raise HTTPException(400, "Upload at least one SQL, DDL, stored procedure, or dbt project artifact before conversion.")
    report = await SqlToSnowflakeConversionEngine(db).convert(run, artifacts)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.get("/conversion/jobs")
async def list_conversion_jobs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ControlPlaneRun)
            .where(ControlPlaneRun.workflow_type == "SQL_DBT_TO_SNOWFLAKE")
            .order_by(ControlPlaneRun.created_at.desc())
        )
    ).scalars().all()
    return [run_dict(row) for row in rows]


@router.get("/conversion/providers")
async def get_conversion_ai_provider_status(provider: str | None = None, _user: User = Depends(get_current_user)):
    return llm_provider_status(provider)


@router.get("/conversion/jobs/{job_id}")
async def get_conversion_job(job_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    artifacts = await artifacts_for_run(db, run, None)
    return {
        **run_dict(run),
        "inventory": [
            {
                "artifact_id": artifact.id,
                "file_name": artifact.original_filename,
                "artifact_category": artifact.artifact_category,
                "file_type": artifact.file_type,
                "size_bytes": artifact.size_bytes,
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            }
            for artifact in artifacts
        ],
        "job_state": (run.summary_json or {}).get("job_state") or initial_conversion_job_state(run, total_files=len(artifacts)),
        "warnings": (run.summary_json or {}).get("file_reports", []),
    }


@router.get("/conversion/jobs/{job_id}/download")
async def download_conversion_job(job_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    await BrainReviewMaterializer(db).materialize_run(run)
    review_items = (
        await db.execute(
            select(HumanReviewItem)
            .where(HumanReviewItem.run_id == job_id)
        )
    ).scalars().all()
    open_review_count = len([item for item in review_items if item.status not in ["APPROVED", "RESOLVED"]])
    if open_review_count:
        raise HTTPException(409, "No Snowflake-ready package is available. Brain Review decisions must be approved or resolved first.")
    summary = run.summary_json or {}
    approved_validation_waiver = _has_approved_snowflake_validation_waiver(list(review_items))
    state = summary.get("job_state") or {}
    validation = summary.get("validation") or {}
    artifact_id = summary.get("download_artifact_id")
    if not artifact_id and approved_validation_waiver and _conversion_state_ready_except_validation(state):
        artifact_id = summary.get("review_package_artifact_id")
    if validation.get("validation_status") not in {"validation_passed", "waived_by_brain_review"} and not approved_validation_waiver:
        raise HTTPException(409, "No Snowflake-ready package is available. Snowflake validation must pass or have an approved Brain Review waiver.")
    if not artifact_id:
        raise HTTPException(409, "No Snowflake-ready package is available. Review artifacts are available only after judge findings are resolved.")
    artifact = await db.get(ControlPlaneArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Converted package artifact not found.")
    path = Path(artifact.storage_path)
    if not path.exists():
        raise HTTPException(404, "Converted package file is missing from storage.")
    return FileResponse(path, media_type=artifact.mime_type or "application/zip", filename=artifact.original_filename)


@router.get("/conversion/jobs/{job_id}/report")
async def get_conversion_job_report(job_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, job_id)).summary_json or {}


@router.post("/conversion/jobs/{job_id}/validate")
async def validate_conversion_job(job_id: str, body: ConversionValidateBody, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    await BrainReviewMaterializer(db).materialize_run(run)
    credentials = body.model_dump(by_alias=True, exclude_none=True)
    credentials.pop("target_connection_id", None)
    report = await SqlToSnowflakeConversionEngine(db).validate(run, body.target_connection_id, credentials=credentials)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.post("/conversion/jobs/{job_id}/agentic-convert")
async def agentic_convert_conversion_job(job_id: str, body: ConversionAiReviewBody = ConversionAiReviewBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    artifacts = await artifacts_for_run(db, run, None)
    if not artifacts:
        raise HTTPException(400, "Upload at least one SQL, DDL, stored procedure, or dbt project artifact before conversion.")
    report = await MigrationIntelligenceEngine(db).agentic_convert(run, artifacts, provider_name=body.provider, use_llm=True)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.post("/conversion/jobs/{job_id}/ai-review")
async def ai_review_conversion_job(job_id: str, body: ConversionAiReviewBody = ConversionAiReviewBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    if not (run.summary_json or {}).get("conversion_context"):
        artifacts = await artifacts_for_run(db, run, None)
        if not artifacts:
            raise HTTPException(400, "Upload at least one artifact before AI review.")
        await MigrationIntelligenceEngine(db).agentic_convert(run, artifacts, provider_name=body.provider or "auto", use_llm=True)
    report = await MigrationIntelligenceEngine(db).ai_review(run, provider_name=body.provider)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.post("/conversion/jobs/{job_id}/ai-patch")
async def propose_conversion_ai_patch(job_id: str, body: ConversionAiPatchBody = ConversionAiPatchBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    try:
        return await MigrationIntelligenceEngine(db).propose_ai_patch(
            run,
            selected_file=body.selected_file,
            provider_name=body.provider,
            overrides=body.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/conversion/jobs/{job_id}/copilot/chat")
async def conversion_copilot_chat(job_id: str, body: ConversionCopilotChatBody, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    return await MigrationIntelligenceEngine(db).copilot_chat(run, body.message)


@router.post("/conversion/jobs/{job_id}/apply-patch")
async def apply_conversion_patch(job_id: str, body: ConversionPatchBody, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    try:
        return await MigrationIntelligenceEngine(db).apply_patch(
            run,
            target_path=body.target_path,
            patched_sql=body.patched_sql,
            confirmed=body.confirmed,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/conversion/jobs/{job_id}/patches/{patch_id}")
async def get_conversion_ai_patch(job_id: str, patch_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    patch = next((row for row in (run.summary_json or {}).get("ai_patches") or [] if row.get("patch_id") == patch_id), None)
    if not patch:
        raise HTTPException(404, "Patch proposal not found.")
    return patch


@router.post("/conversion/jobs/{job_id}/patches/{patch_id}/apply")
async def apply_conversion_ai_patch(job_id: str, patch_id: str, body: ConversionPatchBody = ConversionPatchBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, job_id)
    try:
        return await MigrationIntelligenceEngine(db).apply_patch(
            run,
            patch_id=patch_id,
            target_path=body.target_path,
            patched_sql=body.patched_sql,
            confirmed=body.confirmed,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/dbt-conversion/runs", status_code=201)
async def create_dbt_conversion_run(body: DbtConversionRunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="DBT_CONVERSION",
        user=user,
        safety_mode=body.safety_mode,
        source_type=body.source_type,
        target_type=body.target_type or "snowflake",
        source_dialect=body.source_dialect,
        target_dialect=body.target_dialect or "snowflake",
        source_connection_id=body.source_connection_id,
        target_connection_id=body.target_connection_id,
        config_json={
            **body.config,
            "artifact_ids": body.artifact_ids,
            "dbt_project_name": body.dbt_project_name,
            "default_database": body.default_database,
            "default_schema": body.default_schema,
            "dbt_profile_name": body.dbt_profile_name,
            "model_naming_convention": body.model_naming_convention,
            "default_materialization": body.default_materialization,
        },
    )
    return run_dict(run)


@router.post("/dbt-conversion/runs/{run_id}/analyze")
async def analyze_dbt_conversion(run_id: str, body: AnalyzeBody = AnalyzeBody(), _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    artifacts = await artifacts_for_run(db, run, body.artifact_ids)
    if not artifacts:
        raise HTTPException(400, "At least one SQL, DDL, or dbt project artifact is required.")
    report = await DbtConversionService(db).analyze(run, artifacts)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.post("/dbt-conversion/runs/{run_id}/generate")
async def generate_dbt_conversion(run_id: str, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    report = await DbtConversionService(db).generate(run)
    await BrainReviewMaterializer(db).materialize_run(run)
    return report


@router.get("/dbt-conversion/runs")
async def list_dbt_conversion_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type == "DBT_CONVERSION").order_by(ControlPlaneRun.created_at.desc()))).scalars().all()
    return [run_dict(r) for r in rows]


@router.get("/dbt-conversion/runs/{run_id}")
async def get_dbt_conversion_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/dbt-conversion/runs/{run_id}/artifacts")
async def get_dbt_conversion_artifacts(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_control_plane_artifacts(run_id, _user, db)


@router.get("/dbt-conversion/runs/{run_id}/report")
async def get_dbt_conversion_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await get_run_or_404(db, run_id)).summary_json or {}


@router.post("/dbt/projects/upload", status_code=201)
async def upload_dbt_project(
    file: UploadFile = File(...),
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    artifact = await ControlPlaneService(db).create_artifact_from_upload(file, user, None, "DBT_PROJECT")
    return artifact_dict(artifact)


@router.post("/dbt/projects/{project_id}/analyze")
async def analyze_dbt_project(project_id: str, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(ControlPlaneArtifact, project_id)
    if not artifact:
        raise HTTPException(404, "dbt project artifact not found")
    run = await ControlPlaneService(db).create_run(
        name=f"dbt Project Analysis - {artifact.original_filename}",
        workflow_type="DBT_PROJECT_ANALYSIS",
        user=user,
        safety_mode="PLAN_ONLY",
        source_type="dbt",
        target_type="snowflake",
        config_json={"project_artifact_id": artifact.id},
    )
    artifact.run_id = run.id
    report = await DbtConversionService(db).analyze_existing_project(artifact, user.id)
    run.status = "COMPLETED_WITH_WARNINGS" if report.get("missing_tests") or report.get("risky_incremental_logic") else "COMPLETED"
    run.current_phase = "STATIC_ANALYSIS"
    run.summary_json = report
    run.metrics_json = {"model_count": report.get("model_count", 0), "missing_tests": len(report.get("missing_tests", []))}
    await ControlPlaneService(db).store_json_artifact(run.id, "REPORT", "dbt-project-analysis-report.json", report, user.id)
    await db.commit()
    await BrainReviewMaterializer(db).materialize_run(run)
    return {"run_id": run.id, **report}


@router.get("/dbt/projects")
async def list_dbt_projects(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.artifact_category == "DBT_PROJECT").order_by(ControlPlaneArtifact.created_at.desc()))).scalars().all()
    return [artifact_dict(row) for row in rows]


@router.get("/dbt/projects/{project_id}")
async def get_dbt_project(project_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(ControlPlaneArtifact, project_id)
    if not artifact:
        raise HTTPException(404, "dbt project artifact not found")
    return artifact_dict(artifact)


@router.get("/dbt/projects/{project_id}/models")
async def get_dbt_project_models(project_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(ControlPlaneArtifact, project_id)
    if not artifact:
        raise HTTPException(404, "dbt project artifact not found")
    return (await DbtConversionService(db).analyze_existing_project(artifact)).get("models", [])


@router.get("/dbt/projects/{project_id}/lineage")
async def get_dbt_project_lineage(project_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(ControlPlaneArtifact, project_id)
    if not artifact:
        raise HTTPException(404, "dbt project artifact not found")
    return (await DbtConversionService(db).analyze_existing_project(artifact)).get("lineage", [])


@router.get("/dbt/projects/{project_id}/report")
async def get_dbt_project_report(project_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    artifact = await db.get(ControlPlaneArtifact, project_id)
    if not artifact:
        raise HTTPException(404, "dbt project artifact not found")
    if artifact.run_id:
        run = await db.get(ControlPlaneRun, artifact.run_id)
        if run and run.summary_json:
            return run.summary_json
    return await DbtConversionService(db).analyze_existing_project(artifact)


@router.post("/artifact-factory/dbt/models", status_code=201)
async def artifact_factory_dbt_models(body: DbtArtifactFactoryCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="DBT_MODEL_CREATION",
        user=user,
        safety_mode=body.safety_mode,
        source_type="artifact_factory",
        target_type="snowflake",
        config_json={
            **body.config,
            "artifact_ids": body.source_artifact_ids,
            "source_run_id": body.source_run_id,
            "dbt_project_name": body.project_name,
            "default_database": body.default_database,
            "default_schema": body.default_schema,
            "generation_type": body.generation_type,
            "requirement": body.requirement,
        },
    )
    source_artifacts = await ControlPlaneService(db).artifact_ids(body.source_artifact_ids) if body.source_artifact_ids else []
    if "airflow" in body.generation_type.lower():
        from services.code_generation import generate_code_artifact_with_ai

        source_code = "\n\n".join(
            f"-- {artifact.original_filename}\n{read_artifact_text(artifact)[:12000]}"
            for artifact in source_artifacts[:6]
        )
        result = await generate_code_artifact_with_ai(
            generation_type="AIRFLOW_DAG",
            prompt=body.requirement or "Generate an Airflow DAG for the selected UMA migration artifacts.",
            source_code=source_code,
            metadata={
                **body.config,
                "dag_id": body.config.get("dag_id") or body.project_name or "uma_migration_pipeline",
                "source_artifact_ids": body.source_artifact_ids,
                "use_ai": True,
                "ai_max_tokens": 1800,
            },
        )
        artifact = await ControlPlaneService(db).store_text_artifact(
            run.id,
            "GENERATED_CODE",
            "dags/uma_migration_pipeline.py",
            result["generated_code"],
            run.created_by,
            "text/x-python",
        )
        payload = {
            "generation_type": body.generation_type,
            "generated_artifact_count": 1,
            "generated_artifacts": [{"artifact_id": artifact.id, "path": "dags/uma_migration_pipeline.py", "ai_generated": result.get("ai_available", False)}],
            "ai_generation": {
                "provider": result.get("ai_provider_name"),
                "model": result.get("ai_model_name"),
                "available": result.get("ai_available", False),
                "status": result.get("llm_status"),
                "error": result.get("ai_error"),
            },
            "executed": False,
            "message": "Airflow DAG artifact was generated for review only. UMA did not deploy or execute the DAG.",
        }
        run.status = "COMPLETED"
        run.current_phase = "GENERATED"
        run.summary_json = payload
        await ControlPlaneService(db).store_json_artifact(run.id, "REPORT", "artifact-factory-output.json", payload, run.created_by)
        await db.commit()
        return {"run": run_dict(run), "report": payload, "artifacts": payload["generated_artifacts"]}
    report = await DbtConversionService(db).analyze(run, source_artifacts)
    generation = await DbtConversionService(db).generate(run)
    run.summary_json = {
        **report,
        "artifact_factory": {
            "generation_type": body.generation_type,
            "requirement": body.requirement,
            "source_run_id": body.source_run_id,
        },
        "generation": generation,
    }
    await db.commit()
    return {"run": run_dict(run), "report": run.summary_json}


@router.post("/artifact-factory/dbt/project", status_code=201)
async def artifact_factory_dbt_project(body: DbtArtifactFactoryCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    return await artifact_factory_dbt_models(body, user, db)


@router.get("/artifact-factory/runs")
async def list_artifact_factory_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type.in_(["PIPELINE_BUILD", "DBT_MODEL_CREATION"])).order_by(ControlPlaneRun.created_at.desc()))).scalars().all()
    return [run_dict(r) for r in rows]


@router.get("/artifact-factory/runs/{run_id}")
async def get_artifact_factory_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/artifact-factory/runs/{run_id}/artifacts")
async def get_artifact_factory_run_artifacts(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_control_plane_artifacts(run_id, _user, db)


@router.post("/codegen/runs", status_code=201)
async def create_codegen_run(body: CodegenRunCreate, user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await ControlPlaneService(db).create_run(
        name=body.name,
        workflow_type="PIPELINE_BUILD",
        user=user,
        safety_mode=body.safety_mode,
        config_json={**body.config, "generation_type": body.generation_type, "artifact_ids": body.artifact_ids},
    )
    return run_dict(run)


@router.post("/codegen/runs/{run_id}/generate")
async def generate_codegen(run_id: str, _body: dict = {}, _user: User = Depends(require_editor), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    generation_type = (run.config_json or {}).get("generation_type", "migration_runbook")
    if generation_type in {"data_contract", "data_contracts", "DATA_CONTRACT"}:
        artifacts = await artifacts_for_run(db, run)
        return await DataContractService(db).generate(run, artifacts)
    payload = {
        "generation_type": generation_type,
        "llm_status": "SKIPPED_REQUIRES_CONFIGURATION",
        "artifacts": [
            {"name": "migration-runbook.md", "content": "# Migration Runbook\n\n1. Discover\n2. Assess\n3. Plan\n4. Validate\n5. Review\n6. Execute only after approval\n"},
            {"name": "cutover-checklist.md", "content": "# Cutover Checklist\n\n- Approval recorded\n- Validation plan reviewed\n- Rollback plan reviewed\n- No destructive statements present\n"},
        ],
    }
    run.status = "COMPLETED"
    run.summary_json = payload
    await ControlPlaneService(db).store_json_artifact(run.id, "REPORT", "artifact-factory-output.json", payload, run.created_by)
    await db.commit()
    return payload


@router.get("/codegen/runs")
async def list_codegen_runs(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneRun).where(ControlPlaneRun.workflow_type == "PIPELINE_BUILD").order_by(ControlPlaneRun.created_at.desc()))).scalars().all()
    return [run_dict(r) for r in rows]


@router.get("/codegen/runs/{run_id}")
async def get_codegen_run(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return run_dict(await get_run_or_404(db, run_id))


@router.get("/codegen/runs/{run_id}/artifacts")
async def get_codegen_artifacts(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_control_plane_artifacts(run_id, _user, db)


@router.get("/codegen/templates")
async def get_codegen_templates(_user: User = Depends(get_current_user)):
    return [
        "Snowflake DDL",
        "dbt model",
        "dbt schema.yml",
        "Airflow DAG",
        "validation SQL",
        "reconciliation SQL",
        "migration runbook",
        "cutover checklist",
        "advisor remediation checklist",
        "executive report markdown/json",
    ]


@router.get("/reports")
async def list_reports(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.artifact_category.in_(["REPORT", "ADVISOR_RESULT", "VALIDATION_RESULT", "PROVISION_PLAN"])).order_by(ControlPlaneArtifact.created_at.desc()))).scalars().all()
    return [artifact_dict(r) for r in rows]


@router.get("/reports/{run_id}/preview")
async def preview_unified_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    return {"run": run_dict(run), "report": run.summary_json or {}}


@router.get("/reports/{run_id}/download.json")
async def download_unified_report(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    return PlainTextResponse(
        json.dumps(redact_secrets(run.summary_json or {}), indent=2, sort_keys=True),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{run.id}-report.json"'},
    )


@router.get("/reports/{run_id}/download.html")
async def download_unified_report_html(run_id: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    run = await get_run_or_404(db, run_id)
    title = (run.summary_json or {}).get("title") or run.name
    return PlainTextResponse(
        RichReportService().render_html(title, run.summary_json or {}),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{run.id}-report.html"'},
    )


@router.post("/metadata/search")
async def search_metadata(body: MetadataSearchBody, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await MetadataSearchService(db).search(body.query, body.limit)


@router.post("/metadata/nl2sql")
async def guarded_nl2sql(body: Nl2SqlBody, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await MetadataSearchService(db).guarded_nl2sql(body.question)
