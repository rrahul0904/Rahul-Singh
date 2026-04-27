"""
UMA Platform — Authentication & Authorization
JWT tokens · bcrypt password hashing · role-based access control
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from models import User, UserRole, ApiToken


bearer = HTTPBearer(auto_error=False)
JWT_ALG = "HS256"
JWT_EXPIRY_HOURS = 24


# ═══ Password & token helpers ══════════════════════════════════

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def create_jwt(user_id: str, role: str, email: str) -> str:
    now = datetime.utcnow()
    return pyjwt.encode({
        "sub": user_id, "role": role, "email": email,
        "iat": now, "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }, settings.SECRET_KEY, algorithm=JWT_ALG)


def decode_jwt(token: str) -> Optional[dict]:
    try:
        return pyjwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALG])
    except pyjwt.PyJWTError:
        return None


def generate_api_token() -> tuple[str, str, str]:
    """Returns (token, sha256_hash, display_prefix)."""
    token = "uma_" + secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest(), token[:12]


# ═══ Dependencies ══════════════════════════════════════════════

async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Return User if a valid token is present. Supports JWT and API tokens."""
    if not creds or not creds.credentials:
        return None
    token = creds.credentials

    # API token (long-lived programmatic access)
    if token.startswith("uma_"):
        h = hashlib.sha256(token.encode()).hexdigest()
        r = await db.execute(select(ApiToken).where(ApiToken.token_hash == h))
        api_token = r.scalar_one_or_none()
        if not api_token:
            return None
        if api_token.expires_at and api_token.expires_at < datetime.utcnow():
            return None
        api_token.last_used = datetime.utcnow()
        await db.commit()
        return await db.get(User, api_token.user_id)

    # JWT
    payload = decode_jwt(token)
    if not payload:
        return None
    user = await db.get(User, payload.get("sub"))
    return user if user and user.is_active else None


async def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed: UserRole):
    """Require the user to have one of the listed roles."""
    allowed_values = {r.value if isinstance(r, UserRole) else r for r in allowed}

    async def check(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(allowed_values)}",
            )
        return user
    return check


# Convenience role dependencies
require_admin    = require_role(UserRole.admin)
require_editor   = require_role(UserRole.admin, UserRole.editor)
require_operator = require_role(UserRole.admin, UserRole.editor, UserRole.operator)
# Any authenticated user (viewer+) — just use get_current_user
