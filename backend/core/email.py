"""
UMA Platform — Email delivery helpers.

Uses standard-library SMTP so the platform can send account verification
emails without adding another runtime dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from core.config import settings

logger = logging.getLogger("uma.email")


def generate_email_token() -> str:
    """Generate a URL-safe verification token."""
    return secrets.token_urlsafe(40)


def hash_email_token(token: str) -> str:
    """Hash verification token before storing it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class EmailSendResult:
    sent: bool
    skipped: bool = False
    reason: Optional[str] = None


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and (settings.SMTP_FROM_EMAIL or settings.SMTP_FROM))


def _send_email_sync(to_email: str, subject: str, text_body: str, html_body: Optional[str] = None) -> EmailSendResult:
    if not _smtp_configured():
        logger.warning("SMTP is not configured; skipping outbound email to %s", to_email)
        return EmailSendResult(sent=False, skipped=True, reason="smtp_not_configured")

    from_email = settings.SMTP_FROM_EMAIL or settings.SMTP_FROM
    from_name = settings.SMTP_FROM_NAME or "UMA Platform"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if settings.SMTP_USE_TLS:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        return EmailSendResult(sent=True)
    except Exception as exc:  # pragma: no cover - depends on external SMTP
        logger.exception("Failed to send email to %s", to_email)
        return EmailSendResult(sent=False, skipped=False, reason=str(exc))


async def send_email(to_email: str, subject: str, text_body: str, html_body: Optional[str] = None) -> EmailSendResult:
    """Async wrapper around SMTP send."""
    return await asyncio.to_thread(_send_email_sync, to_email, subject, text_body, html_body)


async def send_verification_email(to_email: str, name: str, verification_url: str) -> EmailSendResult:
    subject = "Confirm your UMA Platform account"
    safe_name = name or to_email
    text_body = f"""Hi {safe_name},

Welcome to UMA Platform.

Please confirm your email address by opening this link:
{verification_url}

If you did not create this account, you can ignore this email.

Thanks,
UMA Platform
"""
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.5; color: #111827;">
        <h2>Confirm your UMA Platform account</h2>
        <p>Hi {safe_name},</p>
        <p>Welcome to UMA Platform. Please confirm your email address to finish setting up your account.</p>
        <p><a href="{verification_url}" style="display:inline-block;padding:10px 14px;background:#111827;color:#ffffff;text-decoration:none;border-radius:6px;">Confirm email</a></p>
        <p>If the button does not work, copy and paste this link into your browser:</p>
        <p>{verification_url}</p>
        <p>If you did not create this account, you can ignore this email.</p>
      </body>
    </html>
    """
    return await send_email(to_email, subject, text_body, html_body)
