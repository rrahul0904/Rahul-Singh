
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_admin, get_current_user
from core.audit import record as audit_record, AuditAction, extract_request_context
from core.database import get_db
from models import PlatformSetting, PlatformSettingAudit, User

router = APIRouter()

DEFAULTS = {
    "feature_flags": {
        "auto_drift": True,
        "schema_auto_add": True,
        "ai_copilot": True,
        "email_alerts": False,
        "slack_alerts": False,
        "telemetry": False,
    },
    "snowflake_defaults": {
        "default_warehouse": "COMPUTE_WH",
        "default_database": "ANALYTICS_DB",
        "default_schema": "RAW",
        "default_role": "SYSADMIN",
        "file_format": "parquet",
        "staging_area": "s3",
    },
    "alerts": {
        "email_provider": "smtp",
        "email_from": "",
        "email_recipients": "",
        "slack_webhook": "",
        "slack_channel": "#uma-alerts",
    },
    "ai": {
        "provider": "offline_deterministic",
        "base_url": "",
        "model": "",
        "fallback_model": "",
        "max_tokens": 8192,
        "temperature": 0.1,
        "structured_output_supported": True,
        "budget_usd_limit": 25,
        "advisory_only": True,
    },
    "rag": {
        "enabled": True,
        "embedding_provider": "offline_keyword",
        "embedding_model": "offline_keyword",
        "vector_store": "keyword",
        "top_k": 8,
        "indexed_artifact_count": 0,
        "last_indexed_time": "",
    },
    "telemetry": {
        "enabled": False,
        "mode": "anonymous",
        "endpoint": "",
    },
}

class SettingsPayload(BaseModel):
    feature_flags: Dict[str, Any]
    snowflake_defaults: Dict[str, Any]
    alerts: Dict[str, Any]
    ai: Dict[str, Any]
    rag: Dict[str, Any] = {}
    telemetry: Dict[str, Any]

async def _ensure_defaults(db: AsyncSession):
    for k, v in DEFAULTS.items():
        row = await db.get(PlatformSetting, k)
        if not row:
            db.add(PlatformSetting(key=k, value=v))
    await db.commit()

@router.get("")
async def get_settings(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_defaults(db)
    out = {}
    for key in DEFAULTS.keys():
        row = await db.get(PlatformSetting, key)
        out[key] = row.value if row else DEFAULTS[key]
    return out

@router.put("")
async def save_settings(
    body: SettingsPayload,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_defaults(db)
    incoming = body.model_dump()
    incoming.setdefault("ai", {})
    incoming["ai"]["advisory_only"] = True
    for key, new_val in incoming.items():
        row = await db.get(PlatformSetting, key)
        old_val = row.value if row else None
        if row:
            row.value = new_val
            row.updated_by = user.id
            row.updated_at = datetime.utcnow()
        else:
            row = PlatformSetting(key=key, value=new_val, updated_by=user.id)
            db.add(row)
        db.add(PlatformSettingAudit(key=key, old_value=old_val, new_value=new_val, changed_by=user.id))
    await db.commit()
    ctx = {k:v for k,v in extract_request_context(request).items() if k in ("ip","user_agent","request_id")}
    await audit_record(action=AuditAction.SETTINGS_UPDATED, user_id=user.id, user_email=user.email,
                       resource="settings", details={"keys": list(incoming.keys())}, **ctx)
    return {"success": True}

@router.get("/history")
async def get_settings_history(
    limit: int = 50,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(PlatformSettingAudit).order_by(PlatformSettingAudit.changed_at.desc()).limit(min(limit,200)))
    return [{
        "id": row.id,
        "key": row.key,
        "old_value": row.old_value,
        "new_value": row.new_value,
        "changed_by": row.changed_by,
        "changed_at": row.changed_at.isoformat(),
    } for row in r.scalars()]

@router.post("/test-email")
async def test_email(
    request: Request,
    user: User = Depends(require_admin),
):
    ctx = {k:v for k,v in extract_request_context(request).items() if k in ("ip","user_agent","request_id")}
    await audit_record(action=AuditAction.SETTINGS_TESTED, user_id=user.id, user_email=user.email,
                       resource="settings:email", details={"provider": "smtp"}, **ctx)
    return {"success": True, "message": "Email settings test endpoint reached. Configure SMTP to send real notifications."}

@router.post("/test-slack")
async def test_slack(
    request: Request,
    user: User = Depends(require_admin),
):
    ctx = {k:v for k,v in extract_request_context(request).items() if k in ("ip","user_agent","request_id")}
    await audit_record(action=AuditAction.SETTINGS_TESTED, user_id=user.id, user_email=user.email,
                       resource="settings:slack", details={"channel": "#uma-alerts"}, **ctx)
    return {"success": True, "message": "Slack settings test endpoint reached. Configure a webhook to send real notifications."}
