from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select

from core.database import AsyncSessionLocal
from models import Job, JobRunLease


@dataclass(frozen=True)
class LeaseSnapshot:
    id: str
    job_id: str
    holder_id: str
    expires_at: datetime


def _lease_seconds() -> int:
    return int(os.getenv("UMA_JOB_RUN_LEASE_SECONDS", "7200"))


def new_holder_id(prefix: str = "uma") -> str:
    return f"{prefix}:{socket.gethostname()}:{os.getpid()}:{uuid4()}"


async def acquire_job_run_lease(job_id: str, holder_id: str | None = None) -> LeaseSnapshot | None:
    """Acquire or refresh an execution lease for a job.

    The job row is locked first so competing API workers serialize before they
    inspect or mutate the unique lease row.
    """
    holder = holder_id or new_holder_id("run")
    now = datetime.utcnow()
    expires = now + timedelta(seconds=_lease_seconds())

    async with AsyncSessionLocal() as db:
        async with db.begin():
            job = (
                await db.execute(select(Job).where(Job.id == job_id).with_for_update())
            ).scalar_one_or_none()
            if not job:
                raise ValueError(f"Job not found: {job_id}")

            lease = (
                await db.execute(
                    select(JobRunLease)
                    .where(JobRunLease.job_id == job_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if lease and lease.expires_at > now and lease.holder_id != holder:
                return None
            if lease is None:
                lease = JobRunLease(job_id=job_id, holder_id=holder, expires_at=expires)
                db.add(lease)
                await db.flush()
            else:
                lease.holder_id = holder
                lease.expires_at = expires
                lease.updated_at = now
            return LeaseSnapshot(
                id=lease.id,
                job_id=lease.job_id,
                holder_id=lease.holder_id,
                expires_at=lease.expires_at,
            )


async def bind_job_run_lease(job_id: str, holder_id: str, run_id: str) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            lease = (
                await db.execute(
                    select(JobRunLease)
                    .where(JobRunLease.job_id == job_id, JobRunLease.holder_id == holder_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if lease:
                lease.run_id = run_id
                lease.updated_at = datetime.utcnow()


async def release_job_run_lease(job_id: str, holder_id: str | None) -> None:
    if not holder_id:
        return
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(
                delete(JobRunLease).where(
                    JobRunLease.job_id == job_id,
                    JobRunLease.holder_id == holder_id,
                )
            )
