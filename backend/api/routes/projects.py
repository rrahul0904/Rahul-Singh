"""
UMA Platform — Projects & Environments Routes
Multi-tenancy scoping: Projects contain Environments (dev/staging/prod),
each with its own Snowflake target defaults.
"""

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import get_current_user, require_admin, require_editor
from models import User, Project, Environment, ProjectMember, UserRole

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name:        str
    slug:        Optional[str] = None
    description: Optional[str] = ""


class EnvironmentCreate(BaseModel):
    name:            str
    description:     Optional[str] = ""
    sf_warehouse:    Optional[str] = "COMPUTE_WH"
    sf_database:     Optional[str] = "ANALYTICS_DB"
    sf_schema:       Optional[str] = "RAW"
    sf_role:         Optional[str] = "SYSADMIN"
    staging_area:    Optional[str] = "s3"
    staging_bucket:  Optional[str] = ""
    is_production:   Optional[bool] = False


class MemberAdd(BaseModel):
    user_id: str
    role:    str  # admin / editor / operator / viewer


# ─── Project routes ───────────────────────────────────────────

@router.get("/projects")
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == UserRole.admin:
        r = await db.execute(select(Project).order_by(Project.created_at.desc()))
    else:
        r = await db.execute(
            select(Project).join(ProjectMember)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.created_at.desc())
        )
    return [_project_dict(p) for p in r.scalars()]


@router.post("/projects")
async def create_project(
    body: ProjectCreate,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    slug = body.slug or _slugify(body.name)
    existing = await db.execute(select(Project).where(Project.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Project slug '{slug}' already exists")

    proj = Project(
        name=body.name, slug=slug,
        description=body.description or "", owner_id=user.id,
    )
    db.add(proj)
    await db.flush()

    # Creator becomes project admin
    db.add(ProjectMember(project_id=proj.id, user_id=user.id, role=UserRole.admin))

    # Create default environments
    for env_name in ("dev", "staging", "prod"):
        db.add(Environment(
            project_id=proj.id,
            name=env_name,
            sf_database=f"ANALYTICS_DB_{env_name.upper()}",
            is_production=(env_name == "prod"),
        ))

    await db.commit()
    await db.refresh(proj)
    return _project_dict(proj)


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proj = await db.get(Project, project_id)
    if not proj:
        raise HTTPException(404, "Project not found")
    await _ensure_access(db, user, project_id)
    return _project_dict(proj)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    proj = await db.get(Project, project_id)
    if not proj:
        raise HTTPException(404, "Project not found")
    await db.delete(proj)
    await db.commit()


# ─── Environment routes ───────────────────────────────────────

@router.get("/projects/{project_id}/environments")
async def list_environments(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, user, project_id)
    r = await db.execute(
        select(Environment).where(Environment.project_id == project_id)
        .order_by(Environment.created_at)
    )
    return [_env_dict(e) for e in r.scalars()]


@router.post("/projects/{project_id}/environments")
async def create_environment(
    project_id: str,
    body: EnvironmentCreate,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, user, project_id)
    env = Environment(
        project_id=project_id,
        name=body.name,
        description=body.description or "",
        sf_warehouse=body.sf_warehouse or "COMPUTE_WH",
        sf_database=body.sf_database or "ANALYTICS_DB",
        sf_schema=body.sf_schema or "RAW",
        sf_role=body.sf_role or "SYSADMIN",
        staging_area=body.staging_area or "s3",
        staging_bucket=body.staging_bucket or "",
        is_production=body.is_production or False,
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return _env_dict(env)


@router.delete("/projects/{project_id}/environments/{env_id}", status_code=204)
async def delete_environment(
    project_id: str, env_id: str,
    user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, user, project_id)
    env = await db.get(Environment, env_id)
    if not env or env.project_id != project_id:
        raise HTTPException(404, "Environment not found")
    await db.delete(env)
    await db.commit()


# ─── Project membership ───────────────────────────────────────

@router.get("/projects/{project_id}/members")
async def list_members(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, user, project_id)
    r = await db.execute(
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
    )
    return [{
        "user_id": pm.user_id, "name": u.name, "email": u.email,
        "role": pm.role.value, "added_at": pm.added_at,
    } for pm, u in r]


@router.post("/projects/{project_id}/members")
async def add_member(
    project_id: str, body: MemberAdd,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_access(db, user, project_id)
    exists = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == body.user_id,
        )
    )
    if exists.scalar_one_or_none():
        raise HTTPException(400, "User already a member")

    pm = ProjectMember(
        project_id=project_id, user_id=body.user_id,
        role=UserRole(body.role),
    )
    db.add(pm)
    await db.commit()
    return {"ok": True}


# ─── Helpers ──────────────────────────────────────────────────

async def _ensure_access(db: AsyncSession, user: User, project_id: str):
    if user.role == UserRole.admin:
        return
    r = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    if not r.scalar_one_or_none():
        raise HTTPException(403, "Not a member of this project")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id, "name": p.name, "slug": p.slug,
        "description": p.description, "owner_id": p.owner_id,
        "created_at": p.created_at,
    }


def _env_dict(e: Environment) -> dict:
    return {
        "id": e.id, "project_id": e.project_id, "name": e.name,
        "description": e.description,
        "sf_warehouse": e.sf_warehouse, "sf_database": e.sf_database,
        "sf_schema": e.sf_schema, "sf_role": e.sf_role,
        "staging_area": e.staging_area, "staging_bucket": e.staging_bucket,
        "is_production": e.is_production, "created_at": e.created_at,
    }
