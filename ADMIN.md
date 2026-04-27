# UMA Platform — Administration & Deployment Guide

This is the **honest operational reality** of UMA as of this release. It covers what works, what's partial, what's missing, and exact commands for the things that do work.

---

## 1. What this product actually is (right now)

**Classification: Strong prototype with real components. Not yet enterprise-production-ready.**

### What's real code (not stubs):
- FastAPI backend with 13 route modules, JWT auth, bcrypt, RBAC (admin/editor/operator/viewer)
- PostgreSQL schema for users, projects, connections, jobs, tasks, validation rules, sync profiles, sync runs, audit logs
- Credential encryption at rest (Fernet, rotation-capable)
- Rate limiting (Redis-backed, with in-memory fallback)
- Account lockout after 5 failed logins
- Per-user audit logging (25+ action types)
- Structured Snowflake diagnostics (DNS → TCP → TLS → auth → role → warehouse)
- Text-to-SQL benchmark endpoint (Claude vs OpenAI vs Cortex)
- Schema drift detection + auto-fix endpoint
- Ad-hoc drift checking (no job required)
- Managed sync profiles with cron scheduling + run history
- Dark/light theme with proper tokenized palette
- Demo workspace seeder for empty-state handling

### What's real but limited:
- **Connectors** — all 27 adapter classes exist with `test_connection()`, `list_tables()`, `get_schema()`, `export_to_s3()` methods. They'll work if you have the right system libraries and credentials. Not all have been exercised against live production systems.
- **Job execution engine** — 3-phase pipeline (Export → Stage → Load) exists. Real execution depends on connector maturity.
- **Scheduler** — polls every 60s, uses DB-lease leader election, handles cron. Works in single-instance deployments.

### What's stubbed or synthetic:
- **Sync run execution** — the async `_execute_sync_run` simulates phases with sleep + hardcoded metrics. Wire to `JobEngine` to make it real.
- **Cortex Analyst integration** — the endpoint shape is there; requires a real Snowflake semantic model YAML in a stage to produce real output.
- **CDC / Debezium** — the flag exists in `SyncProfile.mode`; actual Debezium Kafka Connect config is not included.
- **Connection health auto-monitoring** — only runs on demand. No background health-check worker.

### What's missing entirely:
- SSO / SAML / OIDC
- MFA
- Secret manager integrations (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, Vault)
- Backup/restore automation
- Multi-tenant isolation
- Full operational dashboards (there is a Prometheus `/metrics` endpoint but no pre-built Grafana)
- End-to-end browser test suite (Playwright/Cypress)
- Connector contract tests

---

## 2. How to run it (verified commands)

### Prerequisites
- Docker Desktop 24+ with Compose v2
- 4 GB RAM, 10 GB disk allocated to Docker
- Optional: Python 3.11+ for running the smoke tests

### First launch

```bash
unzip uma-platform.zip
cd uma-backend

# Generate a secret key and put it in .env
cp .env.example .env
python3 -c "import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(48)}')" >> .env

# (Optional but recommended for production)
python3 -c "from cryptography.fernet import Fernet; print(f'UMA_ENCRYPTION_KEY={Fernet.generate_key().decode()}')" >> .env

# Build and start (first time is 3–5 min)
docker compose up -d --build

# Wait ~60 seconds for containers to come up, then:
curl http://localhost:8000/api/health
```

### Create the first admin

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourcompany.com","name":"Admin","password":"Admin123!Secure"}'
```

Password must be 12+ chars with upper, lower, digit, special.

### Seed demo data so the UI isn't empty

After you log in the first time (web or API):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourcompany.com","password":"Admin123!Secure"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/api/demo/bootstrap \
  -H "Authorization: Bearer $TOKEN"
```

This creates 4 sample connections, 3 migration jobs with task-level metrics, 4 validation rules, 2 sync profiles with 3 run records, and demo job logs. The Schema Drift, Lineage, Scheduler, and Tables pages will all have something to show.

---

## 3. Running the smoke test suite

```bash
cd uma-backend
python3 -m pip install pytest
python3 -m pytest tests/ -v
```

What this validates:
- Every route module imports
- FastAPI app builds with all expected paths
- Password hashing and verification roundtrip
- JWT creation, decoding, tamper detection
- API token format
- SQL injection guard classifications
- Password policy rejects weak passwords
- Credential encryption roundtrip

What it does **not** validate:
- Real database operations (needs live Postgres)
- Real connector behavior (needs live source systems)
- Actual HTTP request flow (use `quick-test.sh` for that)

---

## 4. Common admin tasks

### Reset admin password

```bash
# Connect to Postgres
docker compose exec postgres psql -U uma -d uma

# Inside psql:
UPDATE users SET password_hash = '<new-bcrypt-hash>' WHERE email = 'admin@yourcompany.com';
\q
```

To generate a bcrypt hash:
```bash
docker compose exec uma-api python3 -c "from core.auth import hash_password; print(hash_password('NewAdminPwd123!'))"
```

### Disable a user without deleting

```bash
curl -X PATCH http://localhost:8000/api/auth/users/<user_id> \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

### View the audit log

```bash
curl "http://localhost:8000/api/auth/audit-log?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Admin-only. Filter by `action=auth.login.failure` or `user_id=...`.

### Back up the metadata database

```bash
docker compose exec postgres pg_dump -U uma uma > uma-backup-$(date +%Y%m%d).sql
```

### Restore

```bash
docker compose exec -T postgres psql -U uma -d uma < uma-backup-20260423.sql
```

### Check real-time logs

```bash
docker compose logs -f uma-api      # Backend logs
docker compose logs -f worker       # Background worker logs
docker compose logs -f postgres     # DB logs
```

### Prometheus metrics

```bash
curl http://localhost:8000/api/metrics
```

Exposes standard FastAPI request metrics. Wire to a Prometheus server / Grafana for dashboards.

---

## 5. Deployment notes

### Development (Docker Compose on laptop)
Current `docker-compose.yml` is tuned for this. Use as shipped.

### Single-VM production (AWS EC2, Azure VM, GCP Compute)
1. Use `docker-compose.yml` but change:
   - `environment: ENVIRONMENT=production`
   - Add `UMA_ENCRYPTION_KEY=<generated-fernet-key>`
   - Use a proper SMTP host for alerts
   - Point `DATABASE_URL` at a managed Postgres (RDS, Azure Database for PostgreSQL, Cloud SQL)
2. Put UMA behind a reverse proxy (Nginx, Caddy, ALB) with TLS termination
3. Restrict Postgres and Redis to the internal network; do not expose them publicly

### Kubernetes
Base manifests in `infra/k8s/base/deployment.yaml` — use these as a reference. They include:
- API Deployment with HPA (2-10 replicas)
- Worker Deployment with HPA (2-20 replicas)
- Frontend Deployment
- PostgreSQL StatefulSet (replace with managed DB for prod)
- Redis Deployment
- NGINX Ingress

```bash
./infra/deploy.sh eks <cluster-name> <region>
```

### Air-gapped / restricted
Set `AIRGAPPED_MODE=true` and point `INTERNAL_LLM_ENDPOINT` at your internal LLM. UMA will skip external Anthropic API calls.

---

## 6. Known issues and workarounds

### "Cannot connect to Snowflake: 250001"
Your network blocks outbound TLS to `<account>.snowflakecomputing.com`. Use the **Diagnose** flow (in the Snowflake connection wizard) to run DNS/TCP/TLS checks. Share the downloadable diagnostic with your network team.

### "Authentication required" and "Connection successful" shown simultaneously
Known bug from pre-pass-4 that's fixed in this release. If you still see it, you're running stale frontend code — `docker compose up -d --build --force-recreate frontend` to force a rebuild.

### Migration jobs appear empty even after creating connections
- Check that your JWT is valid: `curl http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"`
- Tokens expire after 24h. Re-login.
- Open browser devtools → Network tab → verify Authorization header is being sent on `/api/connections`

### Corporate SSL proxy blocks Microsoft ODBC install
The shipped Dockerfile already skips MS ODBC. SQL Server / Synapse / DB2 / SAP HANA connectors are disabled by default. To re-enable, follow comments in `backend/Dockerfile`.

### Docker compose "database is uninitialized" after pulling new version
Schema changes sometimes require a fresh DB:
```bash
docker compose down -v  # WIPES DATA
docker compose up -d
# Re-register admin
```

---

## 7. Roadmap beyond this release

To take this from pilot-ready to enterprise-production-ready, the order of priority:

1. **SSO via OIDC** (Okta / Azure AD / Google Workspace) — biggest enterprise gate
2. **External secret manager integration** — AWS Secrets Manager as MVP
3. **Real sync run execution wired to JobEngine** — eliminates the simulated metrics
4. **Connector contract test suite** — catches connector regressions
5. **Connection health auto-monitoring worker** — background task every 5 min
6. **Cortex Analyst live integration** — requires a tested semantic model YAML pipeline
7. **MFA (TOTP)** — second-factor login
8. **End-to-end browser tests (Playwright)** — prove the UI actually works per build
9. **Helm chart with Kustomize overlays** — replace raw YAML manifests
10. **Observability stack** — ship with Grafana dashboards + OpenTelemetry traces

Realistic timeline for a focused 2-engineer team: 3-4 months to item 5, 6-9 months to all 10.

---

## 8. Honest summary

**What you can demo today:** Full workflow from login → create connection → create job → run job → view logs → check drift → query Snowflake → SQL benchmark → user management → settings → audit log.

**What you should not claim today:** "Production-ready enterprise migration platform." The marketing gap closes with: SSO, MFA, secret manager integration, real CDC, validated connector coverage in prod systems, and at least one reference customer running real workloads.

**Realistic pitch framing:** "Working prototype with production-shaped architecture. Demonstrates the full control plane. Connector and execution depth varies by source system and needs validation against your specific environment."
