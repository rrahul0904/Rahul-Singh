from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.migration_intelligence_orchestrator import MigrationIntelligenceOrchestrator
from core.auth import get_current_user, require_editor
from core.database import get_db
from models import (
    ArtifactChunk,
    ArtifactExtraction,
    MigrationIntelligenceFinding,
    MigrationIntelligenceReport,
    MigrationIntelligenceRun,
    MigrationIntelligenceRunStep,
    UploadedArtifact,
    User,
)
from services.migration_intelligence_backend import (
    MigrationIntelligenceArtifactService,
    render_docx_bytes,
    render_pdf_bytes,
)

router = APIRouter()


class IntelligenceRunCreate(BaseModel):
    selected_artifact_ids: list[str] = Field(default_factory=list)
    source_connection_id: str | None = None
    target_connection_id: str | None = None
    agent_mode: str = "deterministic_local"


def artifact_dict(artifact: UploadedArtifact) -> dict:
    return {
        "id": artifact.id,
        "file_name": artifact.file_name,
        "file_type": artifact.file_type,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "sha256_hash": artifact.sha256_hash,
        "storage_path": artifact.storage_path,
        "uploaded_by": artifact.uploaded_by,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "extraction_status": artifact.extraction_status,
        "extracted_text_preview": artifact.extracted_text_preview,
        "classification": artifact.classification,
        "language_guess": artifact.language_guess,
        "source_system_guess": artifact.source_system_guess,
        "error_message": artifact.error_message,
    }


def extraction_dict(extraction: ArtifactExtraction | None) -> dict | None:
    if not extraction:
        return None
    return {
        "id": extraction.id,
        "artifact_id": extraction.artifact_id,
        "extraction_status": extraction.extraction_status,
        "extracted_text_preview": extraction.extracted_text_preview,
        "metadata": extraction.metadata_json or {},
        "error_message": extraction.error_message,
    }


def chunk_dict(chunk: ArtifactChunk) -> dict:
    return {
        "id": chunk.id,
        "artifact_id": chunk.artifact_id,
        "chunk_index": chunk.chunk_index,
        "chunk_type": chunk.chunk_type,
        "heading": chunk.heading,
        "statement_type": chunk.statement_type,
        "object_name": chunk.object_name,
        "metadata": chunk.metadata_json or {},
    }


def run_dict(run: MigrationIntelligenceRun) -> dict:
    return {
        "id": run.id,
        "selected_artifact_ids": run.selected_artifact_ids or [],
        "source_connection_id": run.source_connection_id,
        "target_connection_id": run.target_connection_id,
        "status": run.status,
        "started_by": run.started_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "agent_mode": run.agent_mode,
        "openai_called": run.openai_called,
        "snowflake_cortex_called": run.snowflake_cortex_called,
        "snowflake_sql_executed": run.snowflake_sql_executed,
        "uploaded_sql_executed": run.uploaded_sql_executed,
        "generated_code_executed": run.generated_code_executed,
        "ddl_executed": run.ddl_executed,
        "data_moved": run.data_moved,
        "token_credit_note": run.token_credit_note,
        "latest_error": run.latest_error,
    }


def step_dict(step: MigrationIntelligenceRunStep) -> dict:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "step_name": step.step_name,
        "sequence": step.sequence,
        "status": step.status,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "details": step.details_json or {},
        "error_message": step.error_message,
    }


def finding_dict(finding: MigrationIntelligenceFinding) -> dict:
    return {
        "id": finding.id,
        "run_id": finding.run_id,
        "severity": finding.severity,
        "finding_type": finding.finding_type,
        "title": finding.title,
        "description": finding.description,
        "evidence": finding.evidence or [],
        "source_artifact_id": finding.source_artifact_id,
        "recommended_action": finding.recommended_action,
        "status": finding.status,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }


def report_dict(report: MigrationIntelligenceReport) -> dict:
    return {
        "id": report.id,
        "run_id": report.run_id,
        "title": report.title,
        "report_json": report.report_json,
        "report_markdown": report.report_markdown,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


@router.post("/artifacts/upload", status_code=201)
async def upload_artifact(
    file: UploadFile = File(...),
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    service = MigrationIntelligenceArtifactService(db)
    artifact = await service.upload_artifact(file, user)
    extraction = await service.get_extraction(artifact.id)
    chunks = await service.get_chunks(artifact.id)
    return {**artifact_dict(artifact), "extraction": extraction_dict(extraction), "chunks": [chunk_dict(chunk) for chunk in chunks]}


@router.get("/artifacts")
async def list_artifacts(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MigrationIntelligenceArtifactService(db)
    rows = await service.list_artifacts()
    return [artifact_dict(row) for row in rows]


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MigrationIntelligenceArtifactService(db)
    artifact = await service.get_artifact(artifact_id)
    extraction = await service.get_extraction(artifact.id)
    chunks = await service.get_chunks(artifact.id)
    return {**artifact_dict(artifact), "extraction": extraction_dict(extraction), "chunks": [chunk_dict(chunk) for chunk in chunks]}


@router.post("/runs", status_code=201)
async def create_run(
    body: IntelligenceRunCreate,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    if not body.selected_artifact_ids:
        raise HTTPException(400, "selected_artifact_ids is required")
    artifacts = (
        await db.execute(select(UploadedArtifact).where(UploadedArtifact.id.in_(body.selected_artifact_ids)))
    ).scalars().all()
    if len(artifacts) != len(body.selected_artifact_ids):
        raise HTTPException(404, "One or more selected artifacts were not found")

    run = MigrationIntelligenceRun(
        selected_artifact_ids=body.selected_artifact_ids,
        source_connection_id=body.source_connection_id,
        target_connection_id=body.target_connection_id,
        status="QUEUED",
        started_by=user.id,
        agent_mode=body.agent_mode,
        openai_called=False,
        snowflake_cortex_called=False,
        snowflake_sql_executed=False,
        uploaded_sql_executed=False,
        generated_code_executed=False,
        ddl_executed=False,
        data_moved=False,
    )
    db.add(run)
    await db.flush()
    report = await MigrationIntelligenceOrchestrator(db).run(run)
    return {**run_dict(run), "report_id": report.id}


@router.get("/runs")
async def list_runs(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(MigrationIntelligenceRun).order_by(MigrationIntelligenceRun.started_at.desc()))
    ).scalars().all()
    if not rows:
        return []
    report_rows = (
        await db.execute(
            select(MigrationIntelligenceReport).where(
                MigrationIntelligenceReport.run_id.in_([row.id for row in rows])
            )
        )
    ).scalars().all()
    report_ids = {report.run_id: report.id for report in report_rows}
    return [{**run_dict(row), "report_id": report_ids.get(row.id)} for row in rows]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(MigrationIntelligenceRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    report = (
        await db.execute(select(MigrationIntelligenceReport).where(MigrationIntelligenceReport.run_id == run.id))
    ).scalar_one_or_none()
    return {**run_dict(run), "report_id": report.id if report else None}


@router.get("/runs/{run_id}/steps")
async def get_run_steps(
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(MigrationIntelligenceRunStep)
            .where(MigrationIntelligenceRunStep.run_id == run_id)
            .order_by(MigrationIntelligenceRunStep.sequence.asc())
        )
    ).scalars().all()
    return [step_dict(row) for row in rows]


@router.get("/runs/{run_id}/findings")
async def get_run_findings(
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(MigrationIntelligenceFinding)
            .where(MigrationIntelligenceFinding.run_id == run_id)
            .order_by(MigrationIntelligenceFinding.created_at.asc())
        )
    ).scalars().all()
    return [finding_dict(row) for row in rows]


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(MigrationIntelligenceReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report_dict(report)


@router.get("/reports/{report_id}/preview")
async def preview_report(
    report_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(MigrationIntelligenceReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return {
        "id": report.id,
        "run_id": report.run_id,
        "title": report.title,
        "report_markdown": report.report_markdown,
        "flags": report.report_json.get("flags", {}),
    }


@router.get("/reports/{report_id}/download.md")
async def download_markdown(
    report_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(MigrationIntelligenceReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return PlainTextResponse(
        report.report_markdown,
        headers={"Content-Disposition": f'attachment; filename="{report.id}.md"'},
    )


@router.get("/reports/{report_id}/download.pdf")
async def download_pdf(
    report_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(MigrationIntelligenceReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    payload = render_pdf_bytes(report.title, report.report_markdown, report.report_json.get("flags", {}))
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.pdf"'},
    )


@router.get("/reports/{report_id}/download.docx")
async def download_docx(
    report_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await db.get(MigrationIntelligenceReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    payload = render_docx_bytes(report.title, report.report_markdown, report.report_json.get("flags", {}))
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{report.id}.docx"'},
    )
