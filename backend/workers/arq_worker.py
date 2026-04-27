"""
UMA Platform — ARQ Background Worker
- execute_job: on-demand job execution (triggered by API)
- run_validation: on-demand validation rule execution
- scheduled_job_runner: cron task that polls DB for due scheduled jobs
"""

from arq import cron
from arq.connections import RedisSettings
from core.config import settings
import logging
from datetime import datetime, timezone

logger = logging.getLogger("uma.worker")


# ── On-demand tasks ───────────────────────────────────────────

async def execute_job(ctx, job_id: str):
    """Execute a migration job by ID."""
    logger.info(f"Worker executing job: {job_id}")
    from services.migration_orchestrator import execute_job as execute_migration_job
    result = await execute_migration_job(job_id, "auto")
    return {"job_id": job_id, "status": "complete", **result}


async def execute_migration_job(ctx, job_id: str):
    """Compatibility queue entrypoint used by the scheduler."""
    return await execute_job(ctx, job_id)


async def retry_task(ctx, job_id: str, task_id: str, attempt: int = 1):
    """Retry support currently replays the owning job through the orchestrator."""
    logger.info(f"Retrying task {task_id} for job {job_id} (attempt {attempt})")
    return await execute_job(ctx, job_id)


async def run_validation(ctx, rule_id: str):
    """Run a validation rule by ID."""
    logger.info(f"Worker running validation: {rule_id}")
    from api.routes.validation import _execute_rule
    await _execute_rule(rule_id)
    return {"rule_id": rule_id}


# ── Scheduled job runner (cron) ───────────────────────────────

async def scheduled_job_runner(ctx):
    """
    Runs every minute. Checks for jobs whose cron schedule is due
    and haven't been run since their last scheduled slot.
    Uses croniter to evaluate schedule expressions.
    """
    try:
        from croniter import croniter
    except ImportError:
        logger.warning("croniter not installed — cron scheduling disabled. Run: pip install croniter")
        return

    from core.database import AsyncSessionLocal
    from models import Job, JobStatus
    from sqlalchemy import select

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Job).where(
                Job.schedule_cron.isnot(None),
                Job.status != JobStatus.running,
            )
        )
        jobs = result.scalars().all()

        triggered = 0
        for job in jobs:
            try:
                cron_expr = job.schedule_cron
                if not croniter.is_valid(cron_expr):
                    logger.warning(f"Invalid cron expression for job {job.name}: {cron_expr}")
                    continue

                it = croniter(cron_expr, now)
                # Last scheduled time
                last_scheduled = it.get_prev(datetime)

                # If job has never run, or ended before the last scheduled slot → trigger
                last_run = job.ended_at
                if last_run and last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)

                should_run = last_run is None or last_run < last_scheduled

                if should_run:
                    logger.info(f"Triggering scheduled job: {job.name} (cron: {cron_expr})")
                    from services.migration_orchestrator import execute_job as execute_migration_job
                    import asyncio
                    asyncio.create_task(execute_migration_job(job.id, "auto"))
                    triggered += 1

            except Exception as e:
                logger.error(f"Scheduler error for job {job.name}: {e}")

        if triggered:
            logger.info(f"Scheduled {triggered} job(s) this tick")


# ── Worker lifecycle ──────────────────────────────────────────

async def startup(ctx):
    logger.info("UMA Worker started ✓")


async def shutdown(ctx):
    logger.info("UMA Worker shutting down")


class WorkerSettings:
    functions     = [execute_job, execute_migration_job, retry_task, run_validation]
    cron_jobs     = [
        cron(scheduled_job_runner, minute={i for i in range(60)})  # every minute
    ]
    on_startup    = startup
    on_shutdown   = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs       = settings.MAX_CONCURRENT_JOBS
    job_timeout    = settings.JOB_TIMEOUT_SECONDS
