# CODEX Local Final Report

Run time: 2026-04-28T00:02:45Z

## Actually proven locally

- The real execution path is implemented and connected through `migration_orchestrator` to `RealMigrationEngine` for supported sources to Snowflake.
- Composite incremental extraction is unit-tested across duplicate watermark batch boundaries.
- Composite cursor rerun idempotency from `(last_watermark, last_primary_key)` is unit-tested.
- `last_primary_key_value` persistence in `MigrationState.state_json` is unit-tested.
- `max_watermark()` now has direct unit coverage proving it uses the composite boundary predicate.
- Snowflake query tagging/query ID capture is unit-tested with a fake Snowflake connection.
- Cost estimate calculation is unit-tested.
- Snowpark validation helper SQL/profile/hash behavior is unit-tested with a fake session.
- The golden-path test now skips for missing Snowflake credentials, not for missing async pytest plumbing.

## Not proven yet

- Real Snowflake E2E did not run.
- Full load to real Snowflake is not proven in this run.
- Incremental insert/update/soft-delete against real Snowflake is not proven in this run.
- Rerun safety against real Snowflake is not proven in this run.
- Real-engine validation failure behavior against an actual Snowflake table is not proven in this run.
- Actual Snowflake cost tracking/reconciliation is not complete.
- Snowpark validation is not connected to the real engine path.

## Code changed locally

- `docs/CODEX_LOCAL_ENGINE_AUDIT.md`: refreshed backend audit and feature reality check.
- `tests/test_incremental_cursor.py`: added direct composite-cursor coverage for `max_watermark()`.
- `tests/test_postgres_snowflake_golden_path.py`: converted the async pytest test to a sync wrapper with `asyncio.run()` so credential skips and real E2E attempts are deterministic without `pytest-asyncio`.
- `docs/CODEX_LOCAL_HANDOFF.md`: updated with current run details.
- `docs/CODEX_LOCAL_FINAL_REPORT.md`: updated with final status.

## Passed

- `tests/test_incremental_cursor.py`: 4 passed.
- `tests/test_snowpark_validation.py`: 2 passed.
- Selected sync tests from `tests/test_cost_tracking_and_job_locks.py`: 2 passed.

## Skipped

- `tests/test_postgres_snowflake_golden_path.py`: skipped cleanly because required Snowflake env vars are missing.
- DB-backed async job-lock/chunk-manifest tests were not proven because local Postgres is blocked in this sandbox and the available pytest runner lacks `pytest-asyncio`.

## Failed or blocked

- Host Python test run was blocked by missing `asyncpg`.
- Docker backend test path was blocked by denied Docker socket access.
- Minimal dependency install into `.venv` was blocked by unavailable PyPI/DNS.
- Local Postgres connectivity check failed with sandbox `PermissionError`.

## Snowflake E2E status

Real Snowflake E2E not proven yet.

Exact blocker: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_WAREHOUSE`, and `SNOWFLAKE_DATABASE` are not set in this run, and local Postgres access is blocked by the sandbox.

## Next smallest local step

Run `tests/test_postgres_snowflake_golden_path.py` with reachable local Postgres and real Snowflake env vars. That is the next proof point before adding any new engine features.
