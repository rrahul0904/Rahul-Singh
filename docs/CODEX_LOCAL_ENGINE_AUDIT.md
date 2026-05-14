# CODEX Local Engine Audit

Run time: 2026-04-27T23:58:12Z

Scope: focused local audit for the backend migration engine path only. No GitHub, commit, branch, pull request, README, repo hygiene, UI polish, or feature-roadmap work.

## 1. What is actually implemented locally?

- The canonical execution path is connected: `backend/services/migration_orchestrator.py` selects `RealMigrationEngine` for supported source types to Snowflake, and `backend/api/routes/jobs.py` calls that orchestrator from `/execute` and `/execute-real`.
- `backend/services/real_migration_engine.py` is a real local engine path, not just a scaffold. It creates `MigrationRun` and `MigrationTaskRun` rows, extracts source chunks to local Parquet, creates Snowflake database/schema/table objects, stages data, runs `PUT`, `COPY INTO`, full-load insert or incremental `MERGE`, validates, persists checkpoint state, and records run events.
- Postgres extraction is implemented through `SqlSourceAdapter` for `ConnectionType.postgres`. It reads schema from `information_schema`, counts rows, computes min/max, and extracts chunks with keyset pagination.
- Snowflake loading is implemented in `SnowflakeTargetAdapter`: connection setup, JSON query tags, query ID capture, DDL, internal stage table creation, `PUT`, explicit-column `COPY INTO`, full load, incremental merge, target row counts, target min/max, and duplicate primary key checks.
- Full load is implemented as `TRUNCATE TABLE` followed by insert from the stage table.
- Incremental/upsert load is implemented as Snowflake `MERGE` by configured primary key columns.
- Soft delete handling is implemented when `delete_flag_column` is configured: `_UMA_IS_DELETED` is populated during `COPY`, matched rows are marked deleted during merge, and deleted new rows are not inserted.
- Job locking is implemented through `services/job_run_locks.py` and is used by the orchestrator and engine.
- Chunk manifests are implemented and connected to the real engine.
- Query tag and query ID capture are connected to the real engine and persisted to `migration_snowflake_queries`.
- Cost estimation records are created before execution, and actual cost rows are created with `pending` status.

## 2. What is partially implemented?

- Validation is connected for row count, duplicate active primary key count, and active-row watermark min/max. It is not complete for schema match, null counts, sample/hash/content validation, or explicit soft-delete count validation in the real engine path.
- Cost tracking captures estimates and Snowflake query IDs/query tags, but actual Snowflake usage/credit reconciliation is not implemented as a proven connected path.
- Snowpark validation exists in `backend/services/snowpark_validation.py` with unit tests, but it is not called by `RealMigrationEngine`.
- Schema drift models/services/tests exist, but schema drift is not a blocking preflight or validation step in the canonical Postgres to Snowflake execution path.
- Migration intelligence/AI services exist, but they are not proven as an execution layer grounded in real migration run metadata, validation results, and cost results.

## 3. What is fake/demo/static-only?

- Demo workspace seeding has been removed; local static data should not be used as proof of engine behavior.
- UI/control-plane cards, Cortex/Snowflake intelligence UI-oriented paths, and broad connector catalog entries are not part of this backend proof.
- `backend/services/job_engine.py` remains a legacy fallback path. It is not the canonical Postgres to Snowflake milestone path.
- Agentic DDL/cost/load planning tool files are useful scaffolds but are not wired into the proven real migration execution path.

## 4. What is broken or unproven?

- Real Snowflake E2E is not proven until `tests/test_postgres_snowflake_golden_path.py` runs against real Snowflake credentials and passes.
- The golden-path test skips if Snowflake environment variables are missing or placeholder values; this is correct behavior but means real Snowflake E2E remains unproven in that case.
- Actual Snowflake cost reconciliation is not proven.
- Snowpark validation is not connected to real engine execution.
- Full load uses `TRUNCATE TABLE`, which is expected for the current full-load design but should remain gated by load strategy.

## 5. What backend migration-engine pieces are missing?

- Real-engine schema match validation.
- Real-engine null count validation.
- Real-engine sample/hash/content validation.
- Real-engine soft delete count validation.
- Actual Snowflake cost reconciliation from account/query history into `MigrationCostActual`.
- Snowpark validation wired into the canonical engine path.
- Approval-gated agent orchestration for generated DDL/DML execution.

## 6. What Snowflake integration pieces are actually connected?

- Connected: Snowflake connection, database/schema creation, table creation, internal user stage usage, local Parquet `PUT`, `COPY INTO`, full-load insert, incremental `MERGE`, query tag setup, query ID capture, active row count, target min/max, duplicate primary key query, stage cleanup, and query-event persistence.
- Not connected/proven: actual usage credit reconciliation, Snowpark validation execution, and Snowflake intelligence grounded in real engine outputs.

## 7. What validation pieces are actually connected?

- Connected and hard-failing on mismatch: row count validation.
- Connected and hard-failing on mismatch: duplicate primary key validation for active target rows when primary keys are configured.
- Connected and hard-failing on mismatch: watermark min/max validation for active source and target rows when a watermark column is configured.
- Missing from real engine path: schema match, null counts, sample/hash/content validation, explicit soft-delete count validation, and Snowpark-backed validation.

## 8. What tests exist?

- `tests/test_incremental_cursor.py`: unit tests for composite cursor extraction across duplicate watermarks, rerun idempotency from persisted cursor, and `last_primary_key_value` persistence.
- `tests/test_postgres_snowflake_golden_path.py`: real Postgres to Snowflake E2E test for full load, incremental insert/update/soft-delete, rerun safety, and row-count validation mismatch handling. It skips cleanly when Snowflake env vars are missing/placeholders.
- `tests/test_cost_tracking_and_job_locks.py`: tests query tag/query ID capture, cost estimate math, job leases, and chunk manifest state transitions.
- `tests/test_snowpark_validation.py`: unit tests Snowpark helper SQL/profile/hash behavior with a fake session.
- `tests/test_schema_drift_and_intelligence.py`: service-level tests outside the immediate engine milestone.

## 9. What can be safely completed in this local session?

- Run focused tests for composite cursor, cost/query capture/job locks/chunk manifests, and the golden-path test.
- If Snowflake env vars are present and non-placeholder, attempt real Postgres to Snowflake E2E and fail loudly on migration failure.
- If Snowflake env vars are absent/placeholders, record that real Snowflake E2E is not proven yet and keep changes local.

## Feature reality check

- `backend/services/real_migration_engine.py`: real and connected.
- Postgres source extraction: real and connected.
- Snowflake target loading: real and connected; real account behavior depends on E2E credentials.
- Full load: implemented and connected; real E2E proof depends on Snowflake test execution.
- Incremental load: implemented and connected; real E2E proof depends on Snowflake test execution.
- Composite cursor: implemented, connected, and covered by local unit tests.
- Soft delete handling: implemented and connected when `delete_flag_column` is configured; real E2E proof depends on Snowflake test execution.
- Validation: row count, duplicate active primary key, and active watermark min/max are connected; other validation types are missing or helper-only.
- Rerun/idempotency: composite cursor and merge behavior are implemented; cursor idempotency is unit-tested; real Snowflake rerun proof depends on E2E execution.
- Cost tracking: estimates plus query tags/query IDs are connected; actual cost reconciliation is pending.
- Job locking: implemented and tested.
- Chunk manifest: implemented and tested.
- Snowpark validation: helper/unit-tested only, not connected to the real engine.
- Schema drift: scaffold/service-level only, not connected to the real engine path.
- Migration intelligence / AI: scaffold/service-level only, not proven against real migration metadata in the canonical path.
