"""
UMA Platform — Auth Routes (Hardened)
Login with rate limiting, account lockout, audit logging, password policy.
"""

import re
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth import (
    hash_password, verify_password, create_jwt,
    generate_api_token, get_current_user, require_admin,
)
from core.audit import record as audit_record, AuditAction, extract_request_context
from core.lockout import get_lockout
from core.config import settings
from core.email import (
    generate_email_token,
    hash_email_token,
    send_verification_email,
    verification_smtp_missing_fields,
)
from models import User, UserRole, ApiToken, EmailVerificationToken

router = APIRouter()


# ─── Password policy ──────────────────────────────────────────

PASSWORD_MIN_LENGTH = 12


def normalize_email_address(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        raise ValueError("Email address is required")

    # Allow local-development bootstrap identities like `admin@uma.local`
    # outside production while still keeping strict validation elsewhere.
    if settings.ENVIRONMENT != "production":
        if re.fullmatch(r"[^@\s]+@(?:localhost|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.local)", value):
            return value

    try:
        normalized = validate_email(value, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return normalized.email.lower()


def validate_password_strength(password: str) -> None:
    """Raise HTTPException if password doesn't meet complexity requirements."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(400,
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(400, "Password must contain an uppercase letter")
    if not re.search(r"[a-z]", password):
        raise HTTPException(400, "Password must contain a lowercase letter")
    if not re.search(r"\d", password):
        raise HTTPException(400, "Password must contain a digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise HTTPException(400, "Password must contain a special character")


async def _admin_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(User.id)).where(User.role == UserRole.admin))
    return int(result.scalar() or 0)


async def _first_user_id(db: AsyncSession) -> Optional[str]:
    result = await db.execute(select(User.id).order_by(User.created_at.asc(), User.id.asc()).limit(1))
    return result.scalar_one_or_none()


# ─── Schemas ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email:    str
    name:     str
    password: str
    role:     Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        return normalize_email_address(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("Name must be 1-255 characters")
        return v


class LoginRequest(BaseModel):
    email:    str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        return normalize_email_address(v)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        return normalize_email_address(v)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


class AdminPasswordResetRequest(BaseModel):
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    expires_in:   int = 86400
    user:         dict
    email_verification_sent: Optional[bool] = None
    email_verification_skipped: Optional[bool] = None
    email_verification_reason: Optional[str] = None
    email_verification_expires_at: Optional[datetime] = None
    dev_verification_url: Optional[str] = None


class BootstrapStatusResponse(BaseModel):
    bootstrap_available: bool
    user_count: int
    admin_count: int


class UserResponse(BaseModel):
    id:         str
    email:      str
    name:       str
    role:       str
    is_active:  bool
    email_verified: bool = False
    last_login: Optional[datetime]
    created_at: datetime


class UpdateUserRequest(BaseModel):
    name:      Optional[str]  = None
    role:      Optional[str]  = None
    is_active: Optional[bool] = None


class ApiTokenCreate(BaseModel):
    name:            str
    expires_in_days: Optional[int] = None

    @field_validator("expires_in_days")
    @classmethod
    def cap_expiry(cls, v):
        if v is not None and (v < 1 or v > 365):
            raise ValueError("expires_in_days must be 1-365")
        return v




async def _create_and_send_verification(user: User, db: AsyncSession) -> dict:
    """Create a one-time verification token and send the email.

    In development, if SMTP is not configured, the response includes the
    verification_url so local testing can continue without a mail server.
    """
    raw_token = generate_email_token()
    token_hash = hash_email_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(hours=24)

    db.add(EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    await db.commit()

    verification_url = f"{settings.APP_BASE_URL.rstrip('/')}/verify-email?token={raw_token}"
    send_result = await send_verification_email(user.email, user.name, verification_url)
    if send_result.skipped:
        import logging
        logging.getLogger("uma.auth").warning("Email verification URL for %s: %s", user.email, verification_url)

    payload = {
        "email_verification_sent": bool(send_result.sent),
        "email_verification_skipped": bool(send_result.skipped),
        "email_verification_reason": send_result.reason,
        "email_verification_expires_at": expires_at,
    }
    if settings.ENVIRONMENT != "production" and send_result.skipped:
        payload["dev_verification_url"] = verification_url
    return payload


# ─── Routes ───────────────────────────────────────────────────

@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
async def bootstrap_status(db: AsyncSession = Depends(get_db)):
    """Expose whether the unauthenticated first-admin bootstrap path is open."""
    count_r = await db.execute(select(func.count(User.id)))
    user_count = int(count_r.scalar() or 0)
    admin_count = await _admin_count(db)
    return BootstrapStatusResponse(
        bootstrap_available=user_count == 0,
        user_count=user_count,
        admin_count=admin_count,
    )


@router.post("/register", response_model=TokenResponse)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public self-registration. Admin role is assigned separately after verification."""
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    validate_password_strength(body.password)

    missing_smtp_fields = verification_smtp_missing_fields() if settings.REQUIRE_EMAIL_VERIFICATION else []
    if missing_smtp_fields:
        raise HTTPException(
            status_code=503,
            detail="Email delivery is not configured for this environment. Connect a mail provider, then create your account again.",
        )

    user = User(
        email=body.email.lower(),
        name=body.name,
        password_hash=hash_password(body.password),
        role=UserRole.viewer,
        is_active=True,
        email_verified=not settings.REQUIRE_EMAIL_VERIFICATION,
        email_verified_at=datetime.utcnow() if not settings.REQUIRE_EMAIL_VERIFICATION else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await audit_record(
        action=AuditAction.USER_CREATED, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"user:{user.id}",
        details={"role": UserRole.viewer.value, "self_registration": True},
        **{k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")},
    )

    email_info = {}
    if settings.REQUIRE_EMAIL_VERIFICATION:
        email_info = await _create_and_send_verification(user, db)
        if not email_info.get("email_verification_sent"):
            await db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))
            await db.delete(user)
            await db.commit()
            raise HTTPException(
                status_code=502,
                detail="We could not send the verification email. Check the mail provider settings and try again.",
            )
    token = create_jwt(user.id, user.role.value, user.email)
    return TokenResponse(access_token=token, user=_user_dict(user), **email_info)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = body.email.lower()
    lockout = get_lockout()
    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}

    # Check lockout first
    is_locked, seconds_remaining = await lockout.is_locked(email)
    if is_locked:
        await audit_record(
            action=AuditAction.LOGIN_LOCKED, status="denied",
            user_email=email,
            details={"seconds_remaining": seconds_remaining}, **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account locked. Try again in {seconds_remaining // 60 + 1} minutes.",
            headers={"Retry-After": str(seconds_remaining)},
        )

    # Verify credentials
    r = await db.execute(select(User).where(User.email == email))
    user = r.scalar_one_or_none()

    # Use dummy verify for non-existent users to prevent timing-based enumeration
    if not user:
        _ = verify_password(body.password,
            "$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyhash")
        await lockout.record_failure(email)
        await audit_record(
            action=AuditAction.LOGIN_FAILURE, status="failure",
            user_email=email, details={"reason": "user_not_found"}, **ctx,
        )
        raise HTTPException(401, "Invalid email or password")

    if not verify_password(body.password, user.password_hash):
        failure_count = await lockout.record_failure(email)
        await audit_record(
            action=AuditAction.LOGIN_FAILURE, status="failure",
            user_id=user.id, user_email=email,
            details={"reason": "bad_password", "failure_count": failure_count}, **ctx,
        )
        raise HTTPException(401, "Invalid email or password")

    if not user.is_active:
        await audit_record(
            action=AuditAction.LOGIN_FAILURE, status="denied",
            user_id=user.id, user_email=email,
            details={"reason": "account_disabled"}, **ctx,
        )
        raise HTTPException(403, "Account is disabled")

    if settings.REQUIRE_EMAIL_VERIFICATION and not getattr(user, "email_verified", False):
        await audit_record(
            action=AuditAction.LOGIN_FAILURE, status="denied",
            user_id=user.id, user_email=email,
            details={"reason": "email_not_verified"}, **ctx,
        )
        raise HTTPException(403, "Email verification required. Please confirm your email address.")

    # Success
    await lockout.clear_failures(email)
    user.last_login = datetime.utcnow()
    await db.commit()

    await audit_record(
        action=AuditAction.LOGIN_SUCCESS, status="success",
        user_id=user.id, user_email=email, **ctx,
    )

    token = create_jwt(user.id, user.role.value, user.email)
    return TokenResponse(access_token=token, user=_user_dict(user))




@router.get("/verify-email")
async def verify_email_get(token: str, db: AsyncSession = Depends(get_db)):
    return await _verify_email_token(token, db)


@router.post("/verify-email")
async def verify_email_post(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    return await _verify_email_token(body.token, db)


async def _verify_email_token(token: str, db: AsyncSession):
    token_hash = hash_email_token(token)
    r = await db.execute(select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash))
    record = r.scalar_one_or_none()
    if not record or record.consumed_at is not None:
        raise HTTPException(400, "Invalid or already used verification token")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(400, "Verification token has expired")

    user = await db.get(User, record.user_id)
    if not user:
        raise HTTPException(404, "User not found")

    user.email_verified = True
    user.email_verified_at = datetime.utcnow()
    record.consumed_at = datetime.utcnow()
    await db.commit()
    return {
        "verified": True,
        "email": user.email,
        "role": user.role.value,
        "message": "Email verified successfully. Sign in, then open Users to finish administrator setup if no admin exists.",
    }


@router.post("/resend-verification")
async def resend_verification(body: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.email == body.email.lower()))
    user = r.scalar_one_or_none()
    # Avoid account enumeration: return generic success even if the user does not exist.
    if not user:
        return {"sent": True, "message": "If the account exists, a verification email has been sent."}
    if getattr(user, "email_verified", False):
        return {"sent": False, "already_verified": True, "message": "Email is already verified."}
    email_info = await _create_and_send_verification(user, db)
    return {"sent": bool(email_info.get("email_verification_sent")), **email_info}


@router.post("/change-password", status_code=204)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")

    validate_password_strength(body.new_password)

    user.password_hash = hash_password(body.new_password)
    await db.commit()

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.PASSWORD_CHANGED, status="success",
        user_id=user.id, user_email=user.email, **ctx,
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse(**_user_dict(user))


# ─── API Tokens ───────────────────────────────────────────────

@router.get("/tokens")
async def list_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(ApiToken).where(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
    )
    return [{
        "id": t.id, "name": t.name, "prefix": t.prefix,
        "expires_at": t.expires_at, "last_used": t.last_used,
        "created_at": t.created_at,
    } for t in r.scalars()]


@router.post("/tokens")
async def create_token(
    body: ApiTokenCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token, token_hash, prefix = generate_api_token()
    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    api_token = ApiToken(
        user_id=user.id, name=body.name, token_hash=token_hash,
        prefix=prefix, expires_at=expires_at,
    )
    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.TOKEN_CREATED, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"token:{api_token.id}",
        details={"name": body.name, "expires_at": expires_at.isoformat() if expires_at else None},
        **ctx,
    )

    return {
        "id": api_token.id,
        "name": api_token.name,
        "token": token,
        "prefix": prefix,
        "expires_at": expires_at,
        "note": "Store this token securely — it will not be shown again.",
    }


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(ApiToken, token_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Token not found")

    await db.delete(t)
    await db.commit()

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.TOKEN_REVOKED, status="success",
        user_id=user.id, user_email=user.email,
        resource=f"token:{token_id}", **ctx,
    )


# ─── User administration ──────────────────────────────────────

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != UserRole.admin:
        if await _admin_count(db) == 0:
            return [UserResponse(**_user_dict(current_user))]
        raise HTTPException(403, "User management requires admin role")
    r = await db.execute(select(User).order_by(User.created_at.desc()))
    return [UserResponse(**_user_dict(u)) for u in r.scalars()]


@router.post("/users", response_model=UserResponse)
async def create_user(
    body: RegisterRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    validate_password_strength(body.password)

    role = UserRole(body.role) if body.role else UserRole.viewer
    user = User(
        email=body.email.lower(), name=body.name,
        password_hash=hash_password(body.password),
        role=role, is_active=True, email_verified=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.USER_CREATED, status="success",
        user_id=admin.id, user_email=admin.email,
        resource=f"user:{user.id}",
        details={"created_email": user.email, "role": role.value}, **ctx,
    )

    await _create_and_send_verification(user, db)
    return UserResponse(**_user_dict(user))


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    admin_count = await _admin_count(db)
    bootstrap_self_promotion = (
        current_user.role != UserRole.admin
        and admin_count == 0
        and str(current_user.id) == str(user.id) == str(user_id)
        and body.role == UserRole.admin.value
        and body.name is None
        and body.is_active is None
        and getattr(current_user, "email_verified", False)
        and str(await _first_user_id(db)) == str(current_user.id)
    )
    if current_user.role != UserRole.admin and not bootstrap_self_promotion:
        raise HTTPException(403, "User management requires admin role")

    changes = {}
    if body.name is not None:
        changes["name"] = body.name
        user.name = body.name
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
    if body.role is not None:
        changes["role"] = body.role
        old_role = user.role.value
        user.role = UserRole(body.role)

    await db.commit()
    await db.refresh(user)

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}

    if "role" in changes:
        await audit_record(
            action=AuditAction.ROLE_CHANGED, status="success",
            user_id=current_user.id, user_email=current_user.email,
            resource=f"user:{user.id}",
            details={
                "target_user": user.email,
                "old_role": old_role,
                "new_role": user.role.value,
                "bootstrap_self_promotion": bootstrap_self_promotion,
            },
            **ctx,
        )
    else:
        await audit_record(
            action=AuditAction.USER_UPDATED, status="success",
            user_id=current_user.id, user_email=current_user.email,
            resource=f"user:{user.id}", details=changes, **ctx,
        )

    return UserResponse(**_user_dict(user))


@router.post("/users/{user_id}/reset-password", status_code=204)
async def reset_user_password(
    user_id: str,
    body: AdminPasswordResetRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    validate_password_strength(body.new_password)

    user.password_hash = hash_password(body.new_password)
    user.is_active = True
    user.email_verified = True
    if not user.email_verified_at:
        user.email_verified_at = datetime.utcnow()

    await db.commit()

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.PASSWORD_CHANGED, status="success",
        user_id=admin.id, user_email=admin.email,
        resource=f"user:{user.id}",
        details={"target_user": user.email, "admin_reset": True},
        **ctx,
    )


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    request: Request,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current.id:
        raise HTTPException(400, "Cannot delete yourself")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    target_email = user.email
    await db.delete(user)
    await db.commit()

    ctx = {k: v for k, v in extract_request_context(request).items()
           if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.USER_DELETED, status="success",
        user_id=current.id, user_email=current.email,
        resource=f"user:{user_id}",
        details={"deleted_email": target_email}, **ctx,
    )



@router.post("/impersonate/{user_id}", response_model=TokenResponse)
async def impersonate_user(
    user_id: str,
    request: Request,
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if not target.is_active:
        raise HTTPException(400, "Cannot impersonate an inactive user")

    token = create_jwt(target.id, target.role.value, target.email)

    ctx = {k: v for k, v in extract_request_context(request).items() if k in ("ip", "user_agent", "request_id")}
    await audit_record(
        action=AuditAction.USER_IMPERSONATED, status="success",
        user_id=current.id, user_email=current.email,
        resource=f"user:{target.id}",
        details={"target_email": target.email, "target_role": target.role.value}, **ctx
    )
    return TokenResponse(
        access_token=token,
        user=_user_dict(target)
    )


# ─── Audit log access (admin only) ────────────────────────────

@router.get("/audit-log")
async def list_audit(
    limit: int = 100,
    offset: int = 0,
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Browse the audit log (admin only)."""
    from core.audit import AuditLog
    q = select(AuditLog).order_by(AuditLog.timestamp.desc())
    if action:  q = q.where(AuditLog.action == action)
    if user_id: q = q.where(AuditLog.user_id == user_id)
    q = q.limit(min(limit, 1000)).offset(offset)

    r = await db.execute(q)
    return [{
        "id": e.id, "timestamp": e.timestamp.isoformat(),
        "user_id": e.user_id, "user_email": e.user_email,
        "action": e.action, "resource": e.resource,
        "ip": e.ip, "status": e.status,
        "details": e.details, "error": e.error,
    } for e in r.scalars()]


# ─── Helper ───────────────────────────────────────────────────

def _user_dict(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name,
        "role": u.role.value, "is_active": u.is_active,
        "email_verified": bool(getattr(u, "email_verified", False)),
        "last_login": u.last_login, "created_at": u.created_at,
    }
