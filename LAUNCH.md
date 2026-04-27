# UMA Platform — Local Launch Guide

Everything you need to run UMA on your laptop with Docker.

---

## 1. Prerequisites

Install these first:

- **Docker Desktop** — [docker.com/get-started](https://www.docker.com/get-started) (includes Docker Compose)
  - Minimum: 4GB RAM allocated to Docker, 10GB disk
- **Git** — to clone this repo
- Optional: a code editor (VS Code, Cursor) for editing `.env`

Check your install:
```bash
docker --version         # Docker version 24+
docker compose version   # Docker Compose version v2+
```

---

## 2. Get the code

```bash
# If you received this as a folder:
cd uma-backend

# Or if it's in a Git repo:
# git clone <your-repo-url> && cd uma-backend
```

Project layout:
```
uma-backend/
├── backend/              # FastAPI + all connectors + AI services
├── frontend/             # React SPA (Vite)
├── infra/                # K8s manifests + deploy scripts
├── docker-compose.yml    # ← You'll run this
├── .env.example          # ← Copy this to .env
└── README.md
```

---

## 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in the values. **Minimum required to start**:

```bash
# ─── Database (auto-created by Docker) ─────────────────
DATABASE_URL=postgresql+asyncpg://uma:uma_pw@postgres:5432/uma
REDIS_URL=redis://redis:6379/0

# ─── Security ─────────────────────────────────────────
# Generate with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"
SECRET_KEY=your-random-64-char-secret-here-change-me

# ─── CORS (dev) ───────────────────────────────────────
CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]
```

**For actual migrations you also need** (these can be left blank to start, you'll add them via the UI):

```bash
# Snowflake (your target data warehouse)
SNOWFLAKE_ACCOUNT=your-org-account   # e.g. xy12345.us-east-1
SNOWFLAKE_USER=uma_service
SNOWFLAKE_PASSWORD=your-sf-password

# AWS S3 (staging area for Parquet files)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_STAGING_BUCKET=uma-staging-yourname

# Claude AI (for SQL generation, copilot)
ANTHROPIC_API_KEY=sk-ant-...
```

> **No Snowflake yet?** Sign up at [signup.snowflake.com](https://signup.snowflake.com) for a 30-day free trial with $400 credit.
>
> **No Anthropic key?** Get one at [console.anthropic.com](https://console.anthropic.com). The platform works without it — you just won't have AI features.

---

## 4. Launch it

```bash
docker compose up -d
```

Watch it build and start (first time takes 3–5 minutes to download images and install deps):

```bash
docker compose logs -f
```

You'll see:
```
postgres   | database system is ready to accept connections
redis      | Ready to accept connections
uma-api    | 🚀 UMA Platform starting up...
uma-api    | ✅ Database initialized
uma-api    | 🕐 Scheduler started — 60s poll
uma-api    | INFO:     Uvicorn running on http://0.0.0.0:8000
frontend   | ready in 842ms
frontend   |   Local: http://localhost:5173/
```

**Press Ctrl+C to stop following logs (containers keep running).**

---

## 5. Open the app

- **Frontend UI:** [http://localhost:5173](http://localhost:5173)
- **API docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **API health:** [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

## 6. First-time setup (create admin user)

The first time you hit the app, you need to create the admin account. From your terminal:

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@company.com",
    "name": "Your Name",
    "password": "change-me-now"
  }'
```

You'll get back a JWT token — save it, or just log in through the UI.

> After the first user is created, the `/register` endpoint is locked. New users must be created by an admin via `/api/auth/users`.

---

## 7. Use it

### Through the UI (recommended)

1. Go to http://localhost:5173
2. Log in with the email/password from step 6
3. **Connections** → add your first source (BigQuery, Salesforce, whatever) and a Snowflake target
4. **Migration Jobs** → click "New Job" and walk through the 4-step wizard
5. Click **▶ Run** on the job to execute

### Through the API

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@company.com","password":"change-me-now"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# List connections
curl http://localhost:8000/api/connections \
  -H "Authorization: Bearer $TOKEN"

# Create a Snowflake connection
curl -X POST http://localhost:8000/api/connections \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Snowflake Prod",
    "type": "snowflake",
    "config": {
      "account": "xy12345.us-east-1",
      "warehouse": "COMPUTE_WH",
      "database": "ANALYTICS_DB",
      "role": "SYSADMIN"
    },
    "credentials": {
      "user": "uma_service",
      "password": "snowflake-password"
    }
  }'

# Ask Claude a question
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role":"user","content":"Why would a COPY INTO fail?"}]}'
```

---

## 8. Common commands

```bash
# Stop everything (containers stay, state preserved)
docker compose stop

# Start back up
docker compose start

# Rebuild after code changes
docker compose up -d --build

# Wipe everything including database (destructive!)
docker compose down -v

# Watch logs for a specific service
docker compose logs -f uma-api
docker compose logs -f frontend
docker compose logs -f worker

# Shell into the API container to debug
docker compose exec uma-api bash

# Run a one-off Python command
docker compose exec uma-api python3 -c "from models import User; print(User.__table__.columns.keys())"

# Connect to Postgres
docker compose exec postgres psql -U uma -d uma
```

---

## 9. Troubleshooting

### "Port 8000 already in use"
Something else is using that port.
```bash
# Find what's using it (Mac/Linux)
lsof -i :8000
# Or edit docker-compose.yml and change "8000:8000" to "8001:8000"
```

### "Connection refused" when calling the API
API container hasn't started yet (takes ~30s after `docker compose up`).
```bash
docker compose ps        # Check status
docker compose logs uma-api | tail -50   # Look for errors
```

### "401 Unauthorized" on every request
Your token expired (24h lifetime) or is missing.
```bash
# Log in again to get a fresh token
```

### Jobs fail with "ANTHROPIC_API_KEY not configured"
AI features need a key. Either:
- Add `ANTHROPIC_API_KEY=sk-ant-...` to `.env` and restart: `docker compose up -d`
- Or avoid AI features (the platform works without them)

### Jobs fail with "S3 access denied"
Your AWS credentials can't write to the staging bucket.
```bash
# Test your creds from outside Docker:
aws s3 ls s3://$S3_STAGING_BUCKET
# If that fails, fix your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
```

### Frontend shows "API Offline"
API is down, or CORS is misconfigured.
```bash
docker compose logs uma-api | tail -20
# Check CORS_ORIGINS in .env includes http://localhost:5173
```

### "No module named 'oracledb'" (or similar)
The container was built before you added new deps. Rebuild:
```bash
docker compose up -d --build
```

### Database schema is stale (missing columns like `next_scheduled_run`)
```bash
# Wipe and recreate the database
docker compose down
docker volume rm uma-backend_postgres_data  # name may vary — check `docker volume ls`
docker compose up -d
# Then re-register your admin user (step 6)
```

---

## 10. Run without Docker (for development)

If you want to run the backend directly on your laptop (e.g., to attach a debugger):

```bash
# Terminal 1: Postgres + Redis via Docker
docker compose up -d postgres redis

# Terminal 2: Backend
cd backend
python3 -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://uma:uma_pw@localhost:5432/uma"
export REDIS_URL="redis://localhost:6379/0"
export SECRET_KEY="dev-secret-change-me"
export ANTHROPIC_API_KEY="sk-ant-..."
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 3: Worker
cd backend
source venv/bin/activate
arq workers.arq_worker.WorkerSettings

# Terminal 4: Frontend
cd frontend
npm install
npm run dev   # Opens http://localhost:5173
```

---

## 11. Stop and clean up

```bash
# Stop but keep data
docker compose stop

# Stop and remove containers, keep volumes (data persists)
docker compose down

# Full wipe (data gone, start fresh)
docker compose down -v
```

---

## 12. What to do next

1. **Add connections** → UI → Connections → New Connection
2. **Create your first migration job** → Jobs → New Job (wizard)
3. **Try the AI Copilot** → ask it to generate SQL, explain a failure, or suggest validations
4. **Set up a schedule** → edit a job and set a cron expression (e.g., `0 2 * * *` for daily 2am)
5. **Deploy to production** → see `infra/deploy.sh` for EKS / AKS / GKE / air-gapped

---

## Support

- API docs: http://localhost:8000/docs (interactive Swagger UI with "Try it out" buttons)
- Health check: http://localhost:8000/api/health
- Full feature documentation: see `README.md`
