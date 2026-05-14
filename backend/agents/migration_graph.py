from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.state import AgentRunStart, MigrationState
from agents.tools.approval_tools import approval_payload
from agents.tools.cost_tools import estimate_snowflake_cost, snowflake_intelligence_plan
from agents.tools.ddl_tools import generate_snowflake_ddl, stage_ddl_for_review
from agents.tools.discovery_tools import inspect_source_schema
from agents.tools.load_tools import plan_data_movement
from agents.tools.safety import safe_log_payload
from agents.tools.validation_tools import build_validation_strategy
from models import (
    AgentApproval,
    AgentRun,
    AgentStep,
    AgentToolCall,
    DDLConversionResult,
    User,
)


GraphNode = Callable[[AsyncSession, AgentRun, MigrationState], Awaitable[MigrationState]]

PRE_APPROVAL_STEPS: list[str] = [
    "discover_metadata",
    "profile_source",
    "assess_complexity",
    "convert_ddl",
    "convert_sql",
    "plan_data_movement",
    "human_review_gate",
]

POST_APPROVAL_STEPS: list[str] = [
    "execute_approved_ddl",
    "run_validation",
    "estimate_cost",
    "cutover_readiness",
    "generate_report",
]


def _blank_to_none(value: str | None) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def run_to_state(run: AgentRun) -> MigrationState:
    data = dict(run.state_json or {})
    data.update({
        "project_id": run.project_id,
        "run_id": run.id,
        "user_id": run.user_id,
        "request_text": run.request_text or "",
        "source_connection_id": run.source_connection_id,
        "target_connection_id": run.target_connection_id,
        "source_type": run.source_type or "",
        "target_type": run.target_type or "snowflake",
        "schemas": run.schemas or [],
        "migration_type": run.migration_type or "full_load",
        "current_step": run.current_step or data.get("current_step", "not_started"),
        "status": run.status,
        "requires_approval": bool(run.requires_approval),
        "approved": bool(run.approved),
    })
    return MigrationState(**data)


def serialize_run(run: AgentRun) -> dict[str, Any]:
    state = run.state_json or {}
    return {
        "id": run.id,
        "project_id": run.project_id,
        "user_id": run.user_id,
        "run_type": run.run_type,
        "status": run.status,
        "request_text": run.request_text,
        "source_connection_id": run.source_connection_id,
        "target_connection_id": run.target_connection_id,
        "source_type": run.source_type,
        "target_type": run.target_type,
        "migration_type": run.migration_type,
        "schemas": run.schemas or [],
        "current_step": run.current_step,
        "requires_approval": run.requires_approval,
        "approved": run.approved,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "summary": {
            "discovered_objects": len(state.get("discovered_objects") or []),
            "ddl_conversions": len(state.get("ddl_conversions") or []),
            "validation_results": len(state.get("validation_results") or []),
            "estimated_credits": (state.get("cost_estimate") or {}).get("estimated_credits"),
            "warehouse_recommendation": (state.get("cost_estimate") or {}).get("warehouse_recommendation"),
        },
    }


def serialize_step(step: AgentStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "step_name": step.step_name,
        "status": step.status,
        "sequence": step.sequence,
        "input": step.input_json or {},
        "output": step.output_json or {},
        "error_message": step.error_message,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
    }


async def create_agent_run(db: AsyncSession, body: AgentRunStart, user: User) -> AgentRun:
    run = AgentRun(
        project_id=_blank_to_none(body.project_id),
        user_id=user.id,
        request_text=body.request_text,
        source_connection_id=_blank_to_none(body.source_connection_id),
        target_connection_id=_blank_to_none(body.target_connection_id),
        source_type=body.source_type,
        target_type=body.target_type,
        migration_type=body.migration_type,
        schemas=body.schemas,
        status="RUNNING",
        current_step="discover_metadata",
        started_at=datetime.utcnow(),
        state_json={
            "sla": body.sla,
            "data_volume_tb": body.data_volume_tb,
            "snowflake_services": snowflake_intelligence_plan(),
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await run_until_approval(db, run)
    await db.refresh(run)
    return run


async def run_until_approval(db: AsyncSession, run: AgentRun) -> None:
    state = run_to_state(run)
    for sequence, step_name in enumerate(PRE_APPROVAL_STEPS, start=1):
        state = await _run_step(db, run, state, step_name, sequence)
        if state.status in {"FAILED", "WAITING_FOR_APPROVAL"}:
            break
    await _save_run_state(db, run, state)


async def continue_after_approval(db: AsyncSession, run: AgentRun, user: User) -> AgentRun:
    approval = (
        await db.execute(
            select(AgentApproval)
            .where(AgentApproval.run_id == run.id, AgentApproval.status == "PENDING")
            .order_by(AgentApproval.created_at.desc())
        )
    ).scalars().first()
    if approval:
        approval.status = "APPROVED"
        approval.approved_by = user.id
        approval.approved_at = datetime.utcnow()
    gate_step = (
        await db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run.id, AgentStep.step_name == "human_review_gate")
            .order_by(AgentStep.created_at.desc())
        )
    ).scalars().first()
    if gate_step and gate_step.status == "WAITING_FOR_APPROVAL":
        gate_step.status = "SUCCEEDED"
        gate_step.completed_at = datetime.utcnow()
    run.approved = True
    run.requires_approval = False
    run.status = "RUNNING"
    await db.commit()

    state = run_to_state(run)
    state.approved = True
    state.requires_approval = False
    state.status = "RUNNING"
    existing = (
        await db.execute(select(AgentStep).where(AgentStep.run_id == run.id))
    ).scalars().all()
    next_sequence = len(existing) + 1
    for offset, step_name in enumerate(POST_APPROVAL_STEPS):
        state = await _run_step(db, run, state, step_name, next_sequence + offset)
        if state.status == "FAILED":
            break
    state.status = "SUCCEEDED" if not state.errors else "FAILED"
    run.completed_at = datetime.utcnow()
    await _save_run_state(db, run, state)
    await db.refresh(run)
    return run


async def retry_agent_run(db: AsyncSession, run: AgentRun) -> AgentRun:
    run.status = "RUNNING"
    run.error_message = ""
    run.completed_at = None
    await db.commit()
    if run.approved:
        user = await db.get(User, run.user_id)
        if not user:
            raise ValueError("Cannot continue approved run without original user")
        return await continue_after_approval(db, run, user)
    await run_until_approval(db, run)
    await db.refresh(run)
    return run


async def _run_step(
    db: AsyncSession,
    run: AgentRun,
    state: MigrationState,
    step_name: str,
    sequence: int,
) -> MigrationState:
    step = AgentStep(
        run_id=run.id,
        step_name=step_name,
        status="RUNNING",
        sequence=sequence,
        input_json=safe_log_payload(state.model_dump()),
        started_at=datetime.utcnow(),
    )
    db.add(step)
    run.current_step = step_name
    await db.commit()
    await db.refresh(step)

    try:
        handler = _HANDLERS[step_name]
        next_state = await handler(db, run, state)
        step.status = "WAITING_FOR_APPROVAL" if next_state.status == "WAITING_FOR_APPROVAL" else "SUCCEEDED"
        step.output_json = safe_log_payload(next_state.model_dump())
        step.completed_at = datetime.utcnow()
        await db.commit()
        return next_state
    except Exception as exc:
        state.status = "FAILED"
        state.errors.append(str(exc))
        step.status = "FAILED"
        step.error_message = str(exc)[:2000]
        step.completed_at = datetime.utcnow()
        run.status = "FAILED"
        run.error_message = str(exc)[:2000]
        await db.commit()
        return state


async def _save_run_state(db: AsyncSession, run: AgentRun, state: MigrationState) -> None:
    run.state_json = state.model_dump()
    run.status = state.status
    run.current_step = state.current_step
    run.requires_approval = state.requires_approval
    run.approved = state.approved
    run.error_message = "; ".join(state.errors)[-2000:] if state.errors else ""
    run.updated_at = datetime.utcnow()
    await db.commit()


async def _record_tool(
    db: AsyncSession,
    run: AgentRun,
    *,
    tool_name: str,
    permission: str,
    input_json: dict,
    output_json: dict,
) -> None:
    db.add(AgentToolCall(
        run_id=run.id,
        tool_name=tool_name,
        permission=permission,
        input_json=safe_log_payload(input_json),
        output_json=safe_log_payload(output_json),
        status="SUCCEEDED",
    ))
    await db.commit()


async def discover_metadata(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    result = await inspect_source_schema(
        db,
        connection_id=state.source_connection_id,
        schemas=state.schemas,
        source_type=state.source_type,
    )
    await _record_tool(db, run, tool_name="inspect_source_schema", permission="READ_ONLY", input_json=state.model_dump(), output_json=result)
    state.discovered_objects = result.get("objects", [])
    state.current_step = "discover_metadata"
    state.status = "RUNNING"
    return state


async def profile_source(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    profile = {
        "object_count": len(state.discovered_objects),
        "schemas": state.schemas or ["PUBLIC"],
        "large_tables": [],
        "change_tracking_candidates": ["updated_at", "modified_at", "_sdc_batched_at"],
        "procedures_and_views": "pending_live_source_scan",
    }
    await _record_tool(db, run, tool_name="profile_source", permission="READ_ONLY", input_json={}, output_json=profile)
    state.current_step = "profile_source"
    state.source_profile = profile
    return state


async def assess_complexity(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    score = min(100, 20 + len(state.discovered_objects) * 8 + int(max(state.data_volume_tb, 0) * 4))
    report = {
        "complexity_score": score,
        "risk_score": min(100, score + (10 if state.source_type in {"teradata", "oracle"} else 0)),
        "migration_waves": [
            {"wave": 1, "name": "Foundation objects", "objects": len(state.discovered_objects), "requires_approval": True},
            {"wave": 2, "name": "Data movement and validation", "objects": len(state.discovered_objects), "requires_approval": True},
        ],
        "timeline": "1-2 days for fixture-sized MVP; calibrate after live discovery.",
    }
    await _record_tool(db, run, tool_name="assess_complexity", permission="PLANNING", input_json={}, output_json=report)
    state.complexity_report = report
    state.current_step = "assess_complexity"
    return state


async def convert_ddl(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    conversions = [generate_snowflake_ddl(obj, state.source_type) for obj in state.discovered_objects]
    for item in conversions:
        db.add(DDLConversionResult(run_id=run.id, **item))
    staged = stage_ddl_for_review(conversions)
    await db.commit()
    await _record_tool(db, run, tool_name="stage_ddl_for_review", permission="STAGING", input_json={}, output_json=staged)
    state.ddl_conversions = conversions
    state.current_step = "convert_ddl"
    return state


async def convert_sql(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    result = [{
        "source_type": state.source_type,
        "object_type": "views_procedures",
        "status": "STAGED",
        "manual_review_required": True,
        "unsupported_functions": [],
        "message": "SQL/procedure conversion needs captured source object text; workflow step is now visible and auditable.",
    }]
    await _record_tool(db, run, tool_name="convert_sql", permission="STAGING", input_json={}, output_json={"items": result})
    state.sql_conversions = result
    state.current_step = "convert_sql"
    return state


async def plan_movement(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    result = plan_data_movement(
        discovered_objects=state.discovered_objects,
        migration_type=state.migration_type,
        data_volume_tb=state.data_volume_tb,
    )
    await _record_tool(db, run, tool_name="plan_data_movement", permission="PLANNING", input_json={}, output_json=result)
    state.load_plan = result
    state.current_step = "plan_data_movement"
    return state


async def human_review_gate(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    payload = approval_payload(ddl_count=len(state.ddl_conversions), load_strategy=state.load_plan.get("strategy", "unknown"))
    approval = AgentApproval(
        run_id=run.id,
        approval_type="ddl_execution",
        requested_by=run.user_id,
        status="PENDING",
        approval_payload=payload,
    )
    db.add(approval)
    await db.commit()
    state.current_step = "human_review_gate"
    state.status = "WAITING_FOR_APPROVAL"
    state.requires_approval = True
    return state


async def execute_approved_ddl(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    result = {
        "status": "STAGED_ONLY",
        "executed": False,
        "ddl_count": len(state.ddl_conversions),
        "message": "Approval was captured. Real Snowflake execution remains gated behind configured target credentials.",
    }
    await _record_tool(db, run, tool_name="execute_approved_ddl", permission="EXECUTION", input_json={"approved": state.approved}, output_json=result)
    state.current_step = "execute_approved_ddl"
    return state


async def run_validation(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    state.validation_results = build_validation_strategy(state.discovered_objects)
    await _record_tool(db, run, tool_name="run_validation", permission="EXECUTION", input_json={}, output_json={"items": state.validation_results})
    state.current_step = "run_validation"
    return state


async def estimate_cost(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    state.cost_estimate = estimate_snowflake_cost(
        data_volume_tb=state.data_volume_tb,
        migration_type=state.migration_type,
        object_count=len(state.discovered_objects),
    )
    await _record_tool(db, run, tool_name="estimate_snowflake_cost", permission="READ_ONLY", input_json={}, output_json=state.cost_estimate)
    state.current_step = "estimate_cost"
    return state


async def cutover_readiness(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    state.cutover_plan = {
        "status": "DRAFT",
        "items": [
            "Confirm DDL review approval",
            "Run final incremental sync",
            "Run row count, checksum, null, duplicate, and business-rule validation",
            "Confirm rollback owner and freeze window",
            "Switch BI/reporting endpoints",
            "Monitor Snowflake cost and failed queries after cutover",
        ],
    }
    await _record_tool(db, run, tool_name="generate_cutover_plan", permission="PLANNING", input_json={}, output_json=state.cutover_plan)
    state.current_step = "cutover_readiness"
    return state


async def generate_report(db: AsyncSession, run: AgentRun, state: MigrationState) -> MigrationState:
    state.current_step = "generate_report"
    state.status = "SUCCEEDED"
    return state


_HANDLERS: dict[str, GraphNode] = {
    "discover_metadata": discover_metadata,
    "profile_source": profile_source,
    "assess_complexity": assess_complexity,
    "convert_ddl": convert_ddl,
    "convert_sql": convert_sql,
    "plan_data_movement": plan_movement,
    "human_review_gate": human_review_gate,
    "execute_approved_ddl": execute_approved_ddl,
    "run_validation": run_validation,
    "estimate_cost": estimate_cost,
    "cutover_readiness": cutover_readiness,
    "generate_report": generate_report,
}
