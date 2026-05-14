from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ConnectorHealthCheck,
    ReplicationConnection,
    ReplicationError,
    ReplicationJob,
    ReplicationJobTable,
    ReplicationPlan,
    ReplicationRun,
    SnowflakePermissionCheck,
    Job,
    JobLog,
    JobTask,
    MigrationCostActual,
    MigrationCostEstimate,
    MigrationRun,
    MigrationRunEvent,
    MigrationSchemaDriftResult,
    MigrationValidationResult,
)
from mcp.tools import registry_summary


class AIProvider(Protocol):
    async def complete(self, system: str, prompt: str) -> str:
        ...


@dataclass
class StaticProvider:
    response: str = "Migration intelligence provider is not configured."

    async def complete(self, system: str, prompt: str) -> str:
        return self.response


PROMPTS = {
    "failure_explanation": "Explain the migration failure using only provided run facts.",
    "cost_explanation": "Explain estimated versus actual migration cost using only provided cost facts.",
    "validation_mismatch": "Explain validation mismatches and likely remediation steps.",
    "cutover_readiness": "Summarize whether the migration is ready for cutover.",
    "sql_conversion": "Explain SQL conversion considerations for Snowflake.",
    "warehouse_sizing": "Recommend Snowflake warehouse sizing from migration metadata.",
}


def scrub_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if any(s in str(k).lower() for s in ("password", "secret", "token", "key", "credential")) else scrub_context(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub_context(v) for v in value]
    return value


class MigrationIntelligenceService:
    def __init__(self, db: AsyncSession, provider: AIProvider | None = None):
        self.db = db
        self.provider = provider or StaticProvider()

    async def build_context(self, job_id: str, run_id: str | None = None) -> dict[str, Any]:
        job = await self.db.get(Job, job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        tasks = (await self.db.execute(select(JobTask).where(JobTask.job_id == job_id))).scalars().all()
        runs_query = select(MigrationRun).where(MigrationRun.job_id == job_id).order_by(MigrationRun.created_at.desc()).limit(5)
        if run_id:
            runs_query = select(MigrationRun).where(MigrationRun.id == run_id, MigrationRun.job_id == job_id)
        runs = (await self.db.execute(runs_query)).scalars().all()
        run_ids = [r.id for r in runs]
        logs = (await self.db.execute(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.created_at.desc()).limit(20))).scalars().all()
        validations = []
        drift = []
        events = []
        estimates = []
        actuals = []
        if run_ids:
            validations = (await self.db.execute(select(MigrationValidationResult).where(MigrationValidationResult.run_id.in_(run_ids)))).scalars().all()
            drift = (await self.db.execute(select(MigrationSchemaDriftResult).where(MigrationSchemaDriftResult.run_id.in_(run_ids)))).scalars().all()
            events = (await self.db.execute(select(MigrationRunEvent).where(MigrationRunEvent.run_id.in_(run_ids)).order_by(MigrationRunEvent.created_at.desc()).limit(50))).scalars().all()
            estimates = (await self.db.execute(select(MigrationCostEstimate).where(MigrationCostEstimate.run_id.in_(run_ids)))).scalars().all()
            actuals = (await self.db.execute(select(MigrationCostActual).where(MigrationCostActual.run_id.in_(run_ids)))).scalars().all()
        return scrub_context({
            "job": {"id": job.id, "name": job.name, "status": job.status.value, "phase": job.phase, "load_strategy": job.load_strategy.value},
            "tasks": [{"id": t.id, "source": f"{t.source_dataset}.{t.source_table}", "target": f"{t.target_schema}.{t.target_table}", "status": t.status.value} for t in tasks],
            "runs": [{"id": r.id, "status": r.status, "rows_loaded": r.rows_loaded, "rows_merged": r.rows_merged, "error": r.error_message} for r in runs],
            "logs": [{"event": l.event, "level": l.level.value, "message": l.message} for l in logs],
            "validation_results": [{"rule_type": v.rule_type, "status": v.status, "message": v.message, "delta": v.delta} for v in validations],
            "schema_drift": [{"drift_type": d.drift_type, "column": d.column_name, "severity": d.severity} for d in drift],
            "events": [{"phase": e.phase, "event": e.event, "level": e.level, "message": e.message} for e in events],
            "cost_estimates": [{"table": e.table_name, "credits": e.estimated_credits, "cost": e.estimated_cost} for e in estimates],
            "cost_actuals": [{"status": a.status, "actual": a.total_actual_cost, "estimated": a.total_estimated_cost} for a in actuals],
        })

    async def answer(self, job_id: str, question: str, run_id: str | None = None, prompt_type: str = "cutover_readiness") -> dict[str, Any]:
        context = await self.build_context(job_id, run_id)
        system = PROMPTS.get(prompt_type, PROMPTS["cutover_readiness"])
        prompt = f"Question: {question}\n\nMigration context:\n{context}"
        text = await self.provider.complete(system, prompt)
        return {"answer": text, "context": context, "prompt_type": prompt_type}

    async def build_replication_context(self) -> dict[str, Any]:
        connections = list((await self.db.execute(select(ReplicationConnection))).scalars().all())
        jobs = list((await self.db.execute(select(ReplicationJob))).scalars().all())
        tables = list((await self.db.execute(select(ReplicationJobTable))).scalars().all())
        runs = list((await self.db.execute(select(ReplicationRun).order_by(ReplicationRun.created_at.desc()).limit(20))).scalars().all())
        plans = list((await self.db.execute(select(ReplicationPlan))).scalars().all())
        errors = list((await self.db.execute(select(ReplicationError).order_by(ReplicationError.created_at.desc()).limit(10))).scalars().all())
        health = list((await self.db.execute(select(ConnectorHealthCheck).order_by(ConnectorHealthCheck.checked_at.desc()).limit(50))).scalars().all())
        readiness = (
            await self.db.execute(select(SnowflakePermissionCheck).order_by(SnowflakePermissionCheck.checked_at.desc()).limit(1))
        ).scalars().first()

        latest_health: dict[str, ConnectorHealthCheck] = {}
        for row in health:
            latest_health.setdefault(row.connection_id, row)

        selected_tables = [t for t in tables if t.selected]
        missing_pk = [f"{t.schema_name}.{t.table_name}" for t in selected_tables if not (t.primary_key_columns or [])]
        missing_watermark = [f"{t.schema_name}.{t.table_name}" for t in selected_tables if not t.watermark_column]
        plan_by_table = {p.job_table_id: p for p in plans}
        ready_tables = [
            f"{t.schema_name}.{t.table_name}"
            for t in selected_tables
            if plan_by_table.get(t.id) and plan_by_table[t.id].incremental_supported and plan_by_table[t.id].risk_level in {"LOW", "MEDIUM"}
        ]

        return scrub_context({
            "connections": [
                {
                    "id": c.id,
                    "name": c.name,
                    "connector_type": c.connector_type,
                    "role": c.role,
                    "status": c.status,
                    "health": latest_health.get(c.id).status if latest_health.get(c.id) else c.status,
                    "latest_error": c.latest_error,
                }
                for c in connections
            ],
            "jobs": [
                {"id": j.id, "name": j.name, "sync_mode": j.sync_mode, "status": j.status, "latest_error": j.latest_error}
                for j in jobs
            ],
            "runs": [
                {"id": r.id, "job_id": r.job_id, "status": r.status, "planned_tables": r.planned_tables, "latest_error": r.latest_error}
                for r in runs
            ],
            "tables": [
                {
                    "id": t.id,
                    "job_id": t.job_id,
                    "name": f"{t.schema_name}.{t.table_name}",
                    "selected": t.selected,
                    "primary_key_columns": t.primary_key_columns or [],
                    "watermark_column": t.watermark_column,
                    "status": t.status,
                }
                for t in selected_tables
            ],
            "plans": [
                {
                    "job_table_id": p.job_table_id,
                    "table": f"{p.source_schema}.{p.source_object}",
                    "load_mode": p.load_mode,
                    "write_mode": p.write_mode,
                    "risk_level": p.risk_level,
                    "incremental_supported": p.incremental_supported,
                }
                for p in plans
            ],
            "ready_tables": ready_tables,
            "missing_primary_keys": missing_pk,
            "missing_watermarks": missing_watermark,
            "errors": [{"category": e.category, "message": e.message, "safe_detail": e.safe_detail} for e in errors],
            "snowflake_readiness": {
                "status": readiness.status if readiness else "NOT_CHECKED",
                "message": readiness.message if readiness else "No Snowflake permission check has been recorded.",
                "missing_permissions": readiness.missing_permissions if readiness else [],
                "checks": (readiness.details or {}).get("checks", []) if readiness else [],
            },
            "mcp_registry": registry_summary(),
        })

    async def answer_local(self, question: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = await self.build_replication_context()
        if context:
            ctx["request_context"] = scrub_context(context)
        return deterministic_migration_answer(question, ctx)


def deterministic_migration_answer(question: str, ctx: dict[str, Any]) -> dict[str, Any]:
    text = (question or "").lower()
    jobs = ctx.get("jobs", [])
    runs = ctx.get("runs", [])
    connections = ctx.get("connections", [])
    failing_jobs = [j for j in jobs if str(j.get("status")).upper() in {"FAILED", "READY_WITH_ERRORS"} or j.get("latest_error")]
    failing_runs = [r for r in runs if str(r.get("status")).upper() == "FAILED" or r.get("latest_error")]
    ready_tables = ctx.get("ready_tables", [])
    missing_pk = ctx.get("missing_primary_keys", [])
    missing_wm = ctx.get("missing_watermarks", [])
    readiness = ctx.get("snowflake_readiness", {})
    blocked_items: list[str] = []
    if not connections:
        blocked_items.append("No replication connections are configured.")
    if not any(c.get("connector_type") == "snowflake" for c in connections):
        blocked_items.append("No Snowflake replication connection is configured.")
    if readiness.get("status") in {"NOT_CONFIGURED", "FAIL", "NOT_CHECKED", None}:
        blocked_items.append(f"Snowflake readiness is {readiness.get('status', 'NOT_CHECKED')}.")
    if missing_pk:
        blocked_items.append(f"{len(missing_pk)} selected table(s) need primary key metadata.")
    if missing_wm:
        blocked_items.append(f"{len(missing_wm)} selected table(s) need watermark metadata for incremental sync.")

    evidence = [
        f"{len(connections)} connection(s) configured.",
        f"{len(jobs)} replication job(s), {len(runs)} recent run(s).",
        f"{len(ready_tables)} table(s) ready according to persisted replication plans.",
        f"Snowflake readiness: {readiness.get('status', 'NOT_CHECKED')}.",
    ]
    if failing_jobs or failing_runs:
        evidence.append(f"{len(failing_jobs)} failing job(s), {len(failing_runs)} failing recent run(s).")

    if "connection" in text:
        answer = "Configured connections: " + (", ".join(f"{c.get('name')} ({c.get('connector_type')}/{c.get('role')}: {c.get('health')})" for c in connections) or "none.")
    elif "fail" in text:
        answer = "Failing jobs/runs: " + (", ".join(j.get("name") for j in failing_jobs) or "none in persisted replication metadata.")
    elif "ready" in text and "snowflake" not in text:
        answer = "Tables ready to sync: " + (", ".join(ready_tables[:20]) or "none yet; create a replication plan and fill key/watermark metadata.")
    elif "primary" in text or "watermark" in text:
        answer = f"Tables missing keys: {', '.join(missing_pk[:20]) or 'none'}. Tables missing watermarks: {', '.join(missing_wm[:20]) or 'none'}."
    elif "permission" in text:
        answer = f"Snowflake readiness is {readiness.get('status', 'NOT_CHECKED')}: {readiness.get('message', '')}"
    elif "cost" in text or "risk" in text:
        high_risk = [p for p in ctx.get("plans", []) if p.get("risk_level") == "HIGH"]
        answer = f"Estimated risk is metadata-only: {len(high_risk)} high-risk planned table(s). Cost is unavailable until table row/byte estimates and Snowflake warehouse telemetry are present."
    elif "execute" in text or "blocked" in text:
        answer = "Snowflake execution is not ready until connection health, permission diagnostics, table plans, and approval gates are complete."
    else:
        answer = f"Current replication status: {len(jobs)} job(s), {len(ready_tables)} ready planned table(s), Snowflake readiness {readiness.get('status', 'NOT_CHECKED')}."

    recommended_actions = []
    if not ctx.get("plans"):
        recommended_actions.append("Create replication plans for selected job tables.")
    if missing_pk:
        recommended_actions.append("Add primary key metadata for MERGE/UPSERT tables.")
    if missing_wm:
        recommended_actions.append("Add watermark columns for incremental tables or choose full load.")
    if readiness.get("status") != "PASS":
        recommended_actions.append("Run or review Snowflake permission diagnostics with a configured connection.")
    if failing_jobs or failing_runs:
        recommended_actions.append("Review latest replication errors before starting another run.")
    if not recommended_actions:
        recommended_actions.append("Stage the next run for operator approval.")

    return {
        "answer": answer,
        "confidence": 0.86 if connections or jobs else 0.62,
        "evidence": evidence,
        "recommended_actions": recommended_actions,
        "blocked_items": blocked_items,
        "snowflake_readiness": readiness,
        "input_metadata_used": [
            "replication connections",
            "replication jobs",
            "replication runs",
            "replication table metadata",
            "persisted replication plans",
            "Snowflake readiness checks",
            "internal UMA tool registry",
        ],
        "actions_performed": [
            "Read persisted UMA metadata",
            "Classified blockers from job/table/readiness state",
            "Produced deterministic local recommendations",
        ],
        "actions_not_performed": [
            "No OpenAI request",
            "No Snowflake Cortex request",
            "No Snowflake SQL execution",
            "No generated code execution",
            "No secrets inspection or disclosure",
        ],
        "openai_called": False,
        "snowflake_cortex_called": False,
        "snowflake_sql_executed": False,
        "generated_code_executed": False,
        "token_credit_note": "Local deterministic mode. OpenAI and Snowflake Cortex were not called.",
        "internal_tool_plan": {
            "provider": ctx.get("mcp_registry", {}).get("provider", "internal_tool_registry"),
            "next_tools": [
                "get_replication_jobs",
                "create_replication_plan",
                "get_snowflake_readiness",
                "identify_missing_keys_or_watermarks",
            ],
            "execution_gated": True,
            "arbitrary_sql_allowed": False,
        },
    }
