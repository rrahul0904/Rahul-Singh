from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.migration_graph import (
    continue_after_approval,
    create_agent_run,
    retry_agent_run,
    serialize_run,
    serialize_step,
)
from agents.state import AgentRunStart, ApprovalRequest
from core.auth import get_current_user, require_editor, require_operator
from core.database import get_db
from models import AgentApproval, AgentRun, AgentStep, AgentToolCall, DDLConversionResult, User

router = APIRouter()


def _approval_dict(row: AgentApproval) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "step_id": row.step_id,
        "approval_type": row.approval_type,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by,
        "status": row.status,
        "approval_payload": row.approval_payload or {},
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
    }


def _tool_call_dict(row: AgentToolCall) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "step_id": row.step_id,
        "tool_name": row.tool_name,
        "permission": row.permission,
        "input": row.input_json or {},
        "output": row.output_json or {},
        "status": row.status,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _ddl_dict(row: DDLConversionResult) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "source_object_name": row.source_object_name,
        "source_object_type": row.source_object_type,
        "source_dialect": row.source_dialect,
        "target_dialect": row.target_dialect,
        "original_ddl": row.original_ddl,
        "converted_ddl": row.converted_ddl,
        "conversion_confidence": row.conversion_confidence,
        "unsupported_features": row.unsupported_features or [],
        "manual_review_required": row.manual_review_required,
        "review_status": row.review_status,
        "execution_status": row.execution_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_agent_runs(
    limit: int = 25,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [serialize_run(row) for row in rows]


@router.post("/start", status_code=201)
async def start_agent_run(
    body: AgentRunStart,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    run = await create_agent_run(db, body, user)
    return serialize_run(run)


@router.get("/{run_id}")
async def get_agent_run(
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    approvals = (
        await db.execute(select(AgentApproval).where(AgentApproval.run_id == run_id).order_by(AgentApproval.created_at.desc()))
    ).scalars().all()
    ddl = (
        await db.execute(select(DDLConversionResult).where(DDLConversionResult.run_id == run_id).order_by(DDLConversionResult.created_at.asc()))
    ).scalars().all()
    return {
        **serialize_run(run),
        "state": run.state_json or {},
        "approvals": [_approval_dict(row) for row in approvals],
        "ddl_conversions": [_ddl_dict(row) for row in ddl],
    }


@router.get("/{run_id}/steps")
async def get_agent_steps(
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    rows = (
        await db.execute(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.sequence.asc(), AgentStep.created_at.asc())
        )
    ).scalars().all()
    return [serialize_step(row) for row in rows]


@router.get("/{run_id}/tool-calls")
async def get_agent_tool_calls(
    run_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AgentToolCall).where(AgentToolCall.run_id == run_id).order_by(AgentToolCall.created_at.asc())
        )
    ).scalars().all()
    return [_tool_call_dict(row) for row in rows]


@router.post("/{run_id}/approve")
async def approve_agent_run(
    run_id: str,
    body: ApprovalRequest,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if not body.approved:
        run.status = "APPROVAL_REJECTED"
        run.requires_approval = False
        run.error_message = body.comment or "Approval rejected"
        await db.commit()
        await db.refresh(run)
        return serialize_run(run)
    run = await continue_after_approval(db, run, user)
    return serialize_run(run)


@router.post("/{run_id}/retry")
async def retry_run(
    run_id: str,
    _user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    run = await retry_agent_run(db, run)
    return serialize_run(run)
