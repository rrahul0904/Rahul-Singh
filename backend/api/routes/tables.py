from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from core.auth import get_current_user
from core.database import get_db
from models import JobTask, TaskStatus, User

router = APIRouter()


@router.get("")
async def list_tables(
    dataset: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(JobTask).limit(limit).offset(offset)
    if dataset: q = q.where(JobTask.source_dataset == dataset)
    if status:  q = q.where(JobTask.status == status)
    if search:  q = q.where(JobTask.source_table.ilike(f"%{search}%"))
    result = await db.execute(q)
    tasks = result.scalars().all()
    return [{
        "dataset": t.source_dataset,
        "target_schema": t.target_schema,
        "table": t.source_table,
        "target_table": t.target_table,
        "long_text_columns": t.long_text_columns,
        "rows_exported": t.rows_exported,
        "bytes_exported": t.bytes_exported,
        "size": f"{t.bytes_exported/1e6:.1f} MB" if t.bytes_exported >= 1e6 else f"{t.bytes_exported/1e3:.1f} KB",
        "status": t.status.value,
        "job_id": t.job_id,
    } for t in tasks]


@router.get("/stats")
async def table_stats(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobTask.status, func.count(JobTask.id)).group_by(JobTask.status)
    )
    return {row[0].value: row[1] for row in result}
