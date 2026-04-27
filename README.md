# UMA Data Migration Accelerator

Self-hosted migration control plane for moving source data into Snowflake, with connection management, job orchestration, validation, email verification, and OpenAI-backed copilot features.

## Prerequisites

- Docker Desktop with Compose support
- `curl`
- A free local port for:
  - `5173` frontend
  - `8000` API
  - `5432` PostgreSQL
  - `6379` Redis
- Optional for full product testing:
  - Snowflake account and credentials
  - SMTP credentials for real verification emails
  - OpenAI API key

## Repository Setup

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Generate a strong `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

3. Set the generated value in `.env`:

```env
SECRET_KEY=replace-with-generated-value
```

4. If you want a dedicated application encryption key, generate one:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

5. Add it to `.env`:

```env
UMA_ENCRYPTION_KEY=replace-with-generated-value
```

## Docker Compose

Start the full stack:

```bash
docker compose build
docker compose up -d
```

Open:

- Frontend: [http://localhost:5173](http://localhost:5173)
- API health: [http://localhost:8000/api/health](http://localhost:8000/api/health)

Stop everything:

```bash
docker compose down
```

Reset local data:

```bash
docker compose down -v
```

## SMTP Configuration

SMTP is optional for local development. If SMTP is not configured:

- registration still works
- verification tokens are still created
- the API returns a `dev_verification_url`
- the backend logs the verification URL

To enable real verification emails, set:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your_smtp_user
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_EMAIL=noreply@example.com
SMTP_FROM_NAME=UMA Platform
SMTP_USE_TLS=true
REQUIRE_EMAIL_VERIFICATION=true
```

## Snowflake Configuration

Global Snowflake defaults can be provided through `.env`:

```env
SNOWFLAKE_ACCOUNT=org-account
SNOWFLAKE_USER=your_snowflake_user
SNOWFLAKE_PASSWORD=your_snowflake_password
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=ANALYTICS_DB
SNOWFLAKE_SCHEMA=RAW
SNOWFLAKE_ROLE=SYSADMIN
```

For TLS troubleshooting:

```env
SNOWFLAKE_CA_BUNDLE=/path/to/ca-bundle.crt
SNOWFLAKE_INSECURE_MODE=false
```

`SNOWFLAKE_INSECURE_MODE=true` should be used only for local development when you need to bypass TLS validation temporarily.

## Local Smoke Checks

Basic API health:

```bash
curl http://localhost:8000/api/health
```

Backend smoke test:

```bash
docker compose run --rm api pytest tests/test_smoke.py
```

Existing helper scripts:

```bash
./quick-test.sh
./golden-path-smoke.sh
```

## Product Flow

1. Start the stack with `docker compose up -d`
2. Open the frontend
3. Register the first admin account
4. Verify email through SMTP or `dev_verification_url`
5. Create source and target connections
6. Create a migration job
7. Execute the job
8. Review logs, validation, and run status

## Notes

- Do not commit `.env`, secrets, logs, staging files, or build output.
- OpenAI-backed features require a valid `OPENAI_API_KEY`.
- Snowflake connectivity depends on your account, role, warehouse, and TLS environment.
