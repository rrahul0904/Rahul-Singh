# Unified Data Migration Accelerator

UMA is a self-hosted migration control plane for Snowflake-centered data migration. The current baseline focuses on real migration workflows, conversion tools, validation, replication planning, and admin controls without fake success states.

## Current Status

The primary frontend is the `5174` frontend. The `5175` focused UI experiment is stopped and deprecated unless it is explicitly revived later.

Priority modules:

- Command Center
- Migration Run
- SQL Converter
- dbt Converter
- Data Replication
- Validation Center
- Admin

Product rules for this baseline:

- DBT Package Builder stays inside dbt Converter.
- UMA Brain Review is global, not dbt-only.
- Schema Drift means source-to-target schema comparison.
- No fake/static/demo success states.
- No silent buttons.

## Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

Open `http://localhost:5174`.

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API health check: `http://localhost:8000/api/health`

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Frontend: `http://localhost:5174`

Backend: `http://localhost:8000`

## Required Environment Variables

Copy `.env.example` to `.env` and replace placeholders with environment-specific values. Do not commit `.env` or credential-bearing files.

Required for local startup:

- `SECRET_KEY`
- `UMA_ENCRYPTION_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `CORS_ORIGINS`

Required for real Snowflake execution:

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_PASSWORD`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`
- `SNOWFLAKE_ROLE`

Optional integrations include `OPENAI_API_KEY`, SMTP settings, AWS/S3 settings, Azure storage settings, Slack webhook settings, Ollama, and self-hosted OpenAI-compatible model endpoints.
