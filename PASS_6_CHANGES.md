# Pass 6 — Closing Gaps Sprint

## What this pass delivers

Honest scope: not everything you asked for (that's months of work). These are the concrete things that actually ship in this zip.

### 1. Snowflake Connection Diagnostic Wizard (the Prologis-facing feature)
**Before:** Snowflake connection errors were cryptic `250001` strings with no path to resolution.
**After:** When you open the New Connection modal and pick Snowflake, a **Connection Diagnostics** panel appears below the credential fields. Clicking **Run Diagnostic** runs 7 sequential checks:

1. **Account Identifier Format** — validates the `orgname-accountname` or `locator.region` pattern; catches when users paste the full URL by mistake
2. **DNS Resolution** — actually does `socket.gethostbyname()` against the Snowflake hostname, reports resolved IP
3. **TCP Port 443 Reachable** — opens a real TCP socket, so you immediately know if the firewall is blocking it
4. **TLS Handshake** — verifies the cert chain, reports the issuer (detects corp TLS interception)
5. **Authentication** — real Snowflake login with the provided credentials; distinguishes "wrong password" from "user doesn't exist" from "password expired"
6. **Role Access** — verifies the role can be assumed
7. **Warehouse Usage** — verifies USAGE privilege on the warehouse, reports the warehouse state

Each step shows: ✓/✗/!/— status pill, one-line message, duration in ms, and expandable detail panel with actionable hints (e.g., "Install your corp CA cert or set REQUESTS_CA_BUNDLE" for TLS failures).

**Downloadable JSON report** — click "⬇ Report" to get a JSON file you can send to your network/Snowflake admin. Contains timestamps, user, all check results, hostnames, and IPs.

Backend endpoints (from prior pass, now actually wired to UI):
- `POST /api/snowflake/diagnose`
- `POST /api/snowflake/diagnose/download`

### 2. Schema Drift page now works without requiring a job
**Before:** page showed "no jobs" empty state on fresh install — dead end.
**After:** Two tabs:
- **Check from Job** — unchanged behavior, now shows a helpful "no jobs yet, create one or switch to ad-hoc" message when empty
- **Ad-hoc Check** — pick any source connection + source dataset/table, pick any Snowflake target + db/schema/table, click Run. Compares live source schema to Snowflake directly.

New backend endpoint: `POST /api/drift/check-adhoc`

### 3. Minimal but real test suite
Added `tests/test_smoke.py` with 11 tests covering:
- Every core module imports cleanly
- FastAPI app instantiates
- All expected routes are registered
- Password hash + JWT roundtrip
- JWT tamper detection
- API token format
- SQL injection guard classifications (read / write / dangerous)
- Password policy enforcement
- Credential encryption roundtrip (Fernet)
- SQLAlchemy models register correctly

Run: `cd uma-backend && pip install pytest && pytest tests/ -v`

### 4. Honest administrator documentation
New `ADMIN.md` (~200 lines) covering:
- What's real vs stubbed vs missing (no handwaving)
- Verified launch commands
- Common admin tasks (password reset, disable user, backup, restore, audit log)
- Single-VM production notes
- Kubernetes deployment pointers
- Air-gapped mode configuration
- Known issues + workarounds
- Realistic roadmap with timeline estimates

---

## What's changed in code

| File | Change |
|---|---|
| `backend/api/routes/drift.py` | +75 lines: new `/drift/check-adhoc` endpoint |
| `frontend/src/App.jsx` | +200 lines: SnowflakeDiagnosticPanel component + wired into NewConnectionModal |
| `frontend/src/App.jsx` | SchemaDriftPage rewritten with tabs + ad-hoc mode (~100 lines changed) |
| `frontend/src/App.jsx` | 4 new API methods: `diagnoseSnowflake`, `driftCheck`, `driftCheckAdHoc`, `driftApply` |
| `tests/test_smoke.py` | NEW — 11 smoke tests |
| `ADMIN.md` | NEW — honest operations guide |
| `PASS_6_CHANGES.md` | NEW — this file |

---

## What's still missing

Everything I said would be missing in prior passes. Notable:

**Not shipped in this pass:**
- SSO / SAML / OIDC
- MFA
- External secret manager integration
- Real sync run execution (still simulates)
- Connector contract tests (would need live source systems)
- End-to-end browser tests
- Helm chart
- Grafana dashboards
- Multi-tab SQL editor
- CSV export from SQL Workspace

**Shipped but still limited:**
- Cortex benchmark endpoint exists and runs; Cortex path returns an informative error until you configure a semantic model in Snowflake
- Schema drift auto-fix endpoint exists; only handles ADD COLUMN reliably
- All 27 connectors have adapter classes but only Snowflake, BigQuery, S3, and Salesforce have been exercised against live systems

---

## How to upgrade from pass 5

Drop this zip's files on top of your pass-5 folder, or just replace the folder entirely. Then:

```bash
docker compose down
docker compose up -d --build
```

No DB schema changes in this pass — your existing data persists.

---

## Honest assessment

This pass ships the **Snowflake connection wizard** — the single thing I said a week ago was the Prologis-facing differentiator. When Prologis's network team says "Snowflake won't connect," your user can now click Run Diagnostic, download a JSON report in 15 seconds, and email it to the person who can fix it. That's real operational value.

It also closes two other gaps: Schema Drift works standalone, there's an actual test file, and there's a real ops guide.

It does **not** turn UMA into an enterprise migration platform. That's still months of work.

Next highest-impact improvements:
1. SSO via Authlib + OIDC — 1 focused session
2. Real CSV export on SQL Workspace results — 1 hour
3. Multi-tab SQL editor — 1 session
4. Wire sync run executor to JobEngine — 1 session
5. Live Cortex semantic model setup guide + sample YAML — 1 hour

## Pass 7 — Engine Foundation

This pass moves UMA from UI/control-plane only toward a real migration product core.

### Added
- Real migration execution service: `services/real_migration_engine.py`.
- Supported first production-shaped path:
  - BigQuery → Snowflake
  - Postgres → Snowflake
  - Redshift → Snowflake
  - MySQL → Snowflake
- Local Parquet chunk staging under `/tmp/uma_staging`.
- Snowflake internal stage loading with `PUT` + `COPY INTO`.
- Full-refresh loading with truncate + insert.
- Incremental/upsert/CDC-style loading with:
  - primary-key based Snowflake `MERGE`
  - optional `watermark_column`
  - optional `delete_flag_column`
  - durable high-watermark state in `migration_states`
  - immutable execution history in `migration_runs` and `migration_task_runs`
- New job execution APIs:
  - `POST /api/jobs/{job_id}/execute?engine=real`
  - `POST /api/jobs/{job_id}/execute-real`
  - `GET /api/jobs/{job_id}/runs`
  - `GET /api/jobs/{job_id}/state`
- Job task config now supports engine parameters:
  - `primary_key_columns`
  - `watermark_column`
  - `delete_flag_column`
  - `batch_size`

### Still intentionally limited
- SQL Server/Oracle/Teradata source extraction is not wired into the real engine yet.
- S3 external staging is still available in the legacy path, but the real path currently uses Snowflake internal stage to avoid cloud bucket setup during first productization.
- CDC is implemented as watermark + merge + optional soft-delete flag, not log-based CDC yet.
- Schema drift detection is not yet automatically applied during the real engine run.
- Validation is still rule-based and needs direct source-vs-target parity integration.
