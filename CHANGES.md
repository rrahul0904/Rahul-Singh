# UMA Platform — Stabilization Sprint Changelog

## Pass 5 — operational polish / pending UX gaps

### Added
- **Managed Sync control plane upgrades**
  - New backend endpoints:
    - `GET /api/syncs/overview`
    - `GET /api/syncs/profiles/{id}`
    - `PATCH /api/syncs/profiles/{id}`
    - `DELETE /api/syncs/profiles/{id}`
  - Profile payloads now include:
    - source/destination connection names
    - next run time derived from cron cadence
    - last run summary
    - run counts, failed counts, total rows/bytes synced

- **Managed Syncs page upgraded**
  - Search and active/paused filters
  - Overview cards for active profiles, run counts, rows synced, and next run
  - Rich profile detail panel with cadence, drift policy, run history, and pause/resume controls
  - Template-assisted sync profile creation

- **Connections page upgraded**
  - Search/type/health filtering now works
  - Summary cards show total, healthy, failed, and unknown/warn connections
  - Connection detail modal surfaces masked credential hints and non-sensitive config
  - Stored connection tests now open a structured result modal instead of a simple alert

- **Frontend build validation fixed**
  - Added `frontend/src/vite-env.d.ts` so the Vite TypeScript build passes cleanly

- **Deployment metadata polish**
  - Settings → Deployment now shows actual version, environment, build SHA, demo mode, build time, and uptime from `/api/health`
  - Sidebar and topbar now display environment-aware build metadata

### Fixed
- `quick-test.sh` now references the correct Docker Compose service name for backend logs (`api`)

## Validation performed
- `python -m compileall backend`
- `npm run build` in `frontend/`

## Pass 4 — visible progress / first-launch experience

### Added
- **One-click Demo Workspace bootstrap**
  - New backend endpoints:
    - `GET /api/demo/status`
    - `POST /api/demo/bootstrap`
  - Seeds realistic sample data for a fresh install:
    - connections
    - migration jobs
    - job tasks and logs
    - validation rules
    - managed sync profiles and runs
  - Admin-only and intended for local/demo environments.

- **Fresh-install CTA on Dashboard**
  - When the app has zero jobs and zero connections, the dashboard now surfaces a clear prompt to load demo data instead of looking empty.
  - This directly addresses the “I don’t see the progress” issue on first launch.

- **Build/version visibility in UI**
  - Sidebar footer now shows the live API version.
  - Topbar subtitle now includes the API version and optional build SHA.

- **Health payload enriched**
  - `/api/health` now returns:
    - `version`
    - `environment`
    - `build_sha`
    - `build_time`
    - `demo_mode`

## Why this pass matters
Previously, even when the codebase had meaningful features, a clean install still looked mostly empty because there were no connections, jobs, syncs, or validation objects yet. This pass makes the product feel substantially more complete immediately after launch.

## Files added
- `backend/api/routes/demo.py`
- `backend/services/demo_seed.py`

## Files updated
- `backend/main.py`
- `backend/api/routes/health.py`
- `backend/core/config.py`
- `frontend/src/App.jsx`

## Validation performed
- Backend Python modules compile successfully with `python -m compileall backend`.
- Frontend build was not validated in this environment because package installation/build tooling could not be executed here.
