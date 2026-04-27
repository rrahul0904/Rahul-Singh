"""
UMA Platform — Audit Logging
Records security-relevant events: logins, permission changes, credential access, job executions.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, Index
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Base, AsyncSessionLocal

logger = logging.getLogger("uma.audit")


class AuditLog(Base):
    """
    Immutable audit log. Records all security-relevant actions.
    Never updated, never deleted (use retention/archival policy instead).
    """
    __tablename__ = "audit_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id     = Column(String(100), nullable=True, index=True)
    user_email  = Column(String(255), nullable=True)
    action      = Column(String(100), nullable=False, index=True)
    resource    = Column(String(100), nullable=True)     # e.g. "connection:abc123"
    ip          = Column(String(50),  nullable=True)
    user_agent  = Column(String(500), nullable=True)
    request_id  = Column(String(50),  nullable=True)
    status      = Column(String(20),  default="success")  # success / failure / denied
    details     = Column(JSON,        nullable=True)
    error       = Column(Text,        nullable=True)

    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "timestamp"),
        Index("idx_audit_action_time", "action", "timestamp"),
    )


# ═══ Audit actions (enumerated for consistency) ═══════════════

class AuditAction:
    # Auth
    LOGIN_SUCCESS        = "auth.login.success"
    LOGIN_FAILURE        = "auth.login.failure"
    LOGIN_LOCKED         = "auth.login.locked"
    LOGOUT               = "auth.logout"
    PASSWORD_CHANGED     = "auth.password.changed"
    USER_CREATED         = "user.created"
    USER_UPDATED         = "user.updated"
    USER_DELETED         = "user.deleted"
    ROLE_CHANGED         = "user.role.changed"
    TOKEN_CREATED        = "token.created"
    TOKEN_REVOKED        = "token.revoked"
    USER_IMPERSONATED   = "auth.user.impersonated"

    # Connections
    CONNECTION_CREATED   = "connection.created"
    CONNECTION_UPDATED   = "connection.updated"
    CONNECTION_DELETED   = "connection.deleted"
    CONNECTION_TESTED    = "connection.tested"
    CREDENTIAL_ACCESSED  = "connection.credential.accessed"

    # Jobs
    JOB_CREATED          = "job.created"
    JOB_EXECUTED         = "job.executed"
    JOB_DELETED          = "job.deleted"
    JOB_SCHEDULED        = "job.scheduled"

    # Schema drift
    DRIFT_FIX_APPLIED    = "drift.fix.applied"
    SETTINGS_UPDATED    = "settings.updated"
    SETTINGS_TESTED     = "settings.tested"

    # Snowflake
    SNOWFLAKE_QUERY      = "snowflake.query.executed"

    # Access control
    PROJECT_CREATED      = "project.created"
    PROJECT_MEMBER_ADDED = "project.member.added"
    ACCESS_DENIED        = "access.denied"


# ═══ Audit service ════════════════════════════════════════════

async def record(
    action: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    resource: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
    status: str = "success",
    details: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
):
    """Record an audit event. Failures logged but don't raise (audit must not break the app)."""
    try:
        async with AsyncSessionLocal() as db:
            entry = AuditLog(
                action=action,
                user_id=user_id,
                user_email=user_email,
                resource=resource,
                ip=ip,
                user_agent=(user_agent or "")[:500],
                request_id=request_id,
                status=status,
                details=_sanitize(details) if details else None,
                error=error,
            )
            db.add(entry)
            await db.commit()
    except Exception as e:
        logger.exception(f"Audit write failed for action={action}: {e}")


def _sanitize(details: Dict[str, Any]) -> Dict[str, Any]:
    """Strip sensitive keys from audit details."""
    SENSITIVE_KEYS = {
        "password", "token", "secret", "api_key", "access_key",
        "client_secret", "private_key", "credentials",
    }
    result = {}
    for k, v in details.items():
        key_lower = k.lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            result[k] = "[REDACTED]"
        elif isinstance(v, dict):
            result[k] = _sanitize(v)
        else:
            result[k] = v
    return result


def extract_request_context(request) -> Dict[str, Any]:
    """Pull user/IP/request_id from a FastAPI Request."""
    user = getattr(request.state, "user", None)
    return {
        "user_id":    user.id if user else None,
        "user_email": user.email if user else None,
        "ip":         request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent", ""),
        "request_id": getattr(request.state, "request_id", None),
    }
