# UMA Email Verification

This pass adds real account confirmation email support.

## What happens now

- `POST /api/auth/register` creates the first admin user and generates a verification token.
- `POST /api/auth/users` creates a user from the admin screen/API and generates a verification token.
- If SMTP is configured, UMA sends an email with a confirmation link.
- If SMTP is not configured and `ENVIRONMENT != production`, UMA returns `dev_verification_url` in the API response for local testing.
- `GET /api/auth/verify-email?token=...` confirms the account.
- `POST /api/auth/resend-verification` sends a new verification link.

## Required `.env` settings

```env
APP_BASE_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_EMAIL=your_email@gmail.com
SMTP_FROM_NAME=UMA Platform
SMTP_USE_TLS=true
REQUIRE_EMAIL_VERIFICATION=false
```

Set `REQUIRE_EMAIL_VERIFICATION=true` only when you want login blocked until the user verifies email.

## Local test without SMTP

Register a user and check the JSON response. In development, it will include `dev_verification_url` if SMTP is blank. Open that URL in the browser or curl it.

```bash
curl "http://localhost:8000/api/auth/verify-email?token=<token>"
```

## Resend

```bash
curl -X POST http://localhost:8000/api/auth/resend-verification \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com"}'
```
