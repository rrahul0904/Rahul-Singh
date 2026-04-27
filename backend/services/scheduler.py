"""
UMA Platform — Scheduler Service
Background loop that triggers jobs based on cron schedules.
Uses croniter to evaluate cron expressions and queues jobs via ARQ.
Supports multi-replica leader election via the scheduler_leases table.
"""

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from models import Job, JobStatus, SchedulerLease

logger = logging.getLogger("uma.scheduler")


class SchedulerService:
    """
    Polls the Job table every 60s and enqueues jobs whose cron has elapsed.
    Uses PostgreSQL row-level locking for leader election in multi-replica deployments.
    Only the active lease holder triggers jobs.
    """

    POLL_INTERVAL_SECONDS = 60
    LEASE_DURATION_SECONDS = 90
    LOCK_NAME = "scheduler"

    def __init__(self, redis_pool=None):
        self._redis = redis_pool
        self._running = False
        self._holder_id = f"{socket.gethostname()}-{os.getpid()}"

    async def start(self):
        self._running = True
        logger.info(f"Scheduler started (holder={self._holder_id})")
        while self._running:
            try:
                if await self._acquire_lease():
                    await self._tick()
            except Exception as e:
                logger.exception(f"Scheduler tick failed: {e}")
            await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    def stop(self):
        self._running = False

    async def _acquire_lease(self) -> bool:
        """
        Attempt to acquire or extend the scheduler lease.
        Returns True if this replica is the leader for this tick.
        """
        now = datetime.utcnow()
        expires = now + timedelta(seconds=self.LEASE_DURATION_SECONDS)

        async with AsyncSessionLocal() as db:
            lease = await db.get(SchedulerLease, self.LOCK_NAME)

            if lease is None:
                # First time — try to insert. Race-safe via PK conflict.
                try:
                    db.add(SchedulerLease(
                        lock_name=self.LOCK_NAME,
                        holder_id=self._holder_id,
                        acquired_at=now,
                        expires_at=expires,
                    ))
                    await db.commit()
                    logger.info(f"Scheduler lease acquired: {self._holder_id}")
                    return True
                except Exception:
                    await db.rollback()
                    return False

            # If current holder or expired, take over
            if lease.holder_id == self._holder_id or lease.expires_at < now:
                lease.holder_id   = self._holder_id
                lease.acquired_at = now if lease.holder_id != self._holder_id else lease.acquired_at
                lease.expires_at  = expires
                await db.commit()
                return True

            # Another leader is active
            logger.debug(f"Lease held by {lease.holder_id}, skipping this tick")
            return False

    async def _tick(self):
        from croniter import croniter
        now = datetime.utcnow()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Job).where(
                    Job.schedule_cron.isnot(None),
                    Job.schedule_cron != "",
                    Job.status != JobStatus.running,
                )
            )
            jobs = result.scalars().all()

            for job in jobs:
                if not self._should_run(job, now):
                    continue

                logger.info(f"Scheduler triggering: {job.name} (cron={job.schedule_cron})")
                await self._enqueue_job(job.id)
                job.next_scheduled_run = self._next_run(job.schedule_cron, now)
                await db.commit()

    def _should_run(self, job: Job, now: datetime) -> bool:
        from croniter import croniter
        try:
            if job.next_scheduled_run:
                return now >= job.next_scheduled_run
            base = job.ended_at or job.started_at or job.created_at or (now - timedelta(days=1))
            cron = croniter(job.schedule_cron, base)
            return now >= cron.get_next(datetime)
        except Exception as e:
            logger.error(f"Invalid cron for job {job.name}: {e}")
            return False

    def _next_run(self, cron_expr: str, from_time: datetime) -> Optional[datetime]:
        from croniter import croniter
        try:
            return croniter(cron_expr, from_time).get_next(datetime)
        except Exception:
            return None

    async def _enqueue_job(self, job_id: str):
        if self._redis:
            try:
                await self._redis.enqueue_job("execute_migration_job", job_id)
                return
            except Exception as e:
                logger.error(f"ARQ enqueue failed: {e} — falling back to direct execute")

        from services.migration_orchestrator import execute_job
        asyncio.create_task(execute_job(job_id, "auto"))


_scheduler_instance: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SchedulerService()
    return _scheduler_instance


async def start_scheduler_task():
    scheduler = get_scheduler()
    asyncio.create_task(scheduler.start())
