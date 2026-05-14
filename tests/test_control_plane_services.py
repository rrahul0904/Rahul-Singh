import os
import sys
import asyncio
import csv
import io
from datetime import datetime
from pathlib import Path
import zipfile
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.sql import operators
from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.selectable import Select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import services.control_plane as control_plane_module  # noqa: E402
import services.migration_conversion_brain as brain_module  # noqa: E402
import services.sql_snowflake_conversion as snowflake_conversion_module  # noqa: E402
from models import (  # noqa: E402
    AnalyzerComponent,
    AnalyzerDependency,
    ControlPlaneArtifact,
    ControlPlaneJob,
    ControlPlaneRun,
    Connection,
    HumanReviewItem,
    SqlConversionMessage,
    User,
    UserRole,
)
from services.control_plane import (  # noqa: E402
    AnalyzerService,
    ControlPlaneService,
    DataContractService,
    MetadataSearchService,
    MigrationIntelligenceControlService,
    ProvisionService,
    SqlConversionService,
    redact_secrets,
    split_sql_statements,
    statement_type,
    validate_upload,
)
from services.brain_review import BrainReviewMaterializer  # noqa: E402
from services.migration_conversion_brain import MigrationIntelligenceEngine  # noqa: E402
from services.sql_snowflake_conversion import SqlToSnowflakeConversionEngine  # noqa: E402


class FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return list(self._items)

    def scalar_one_or_none(self):
        if not self._items:
            return None
        if len(self._items) > 1:
            raise AssertionError("Expected one or zero rows")
        return self._items[0]


class FakeControlPlaneSession:
    MODELS = (
        ControlPlaneArtifact,
        ControlPlaneRun,
        ControlPlaneJob,
        SqlConversionMessage,
        HumanReviewItem,
        AnalyzerComponent,
        AnalyzerDependency,
        Connection,
    )

    def __init__(self):
        self.storage = {}
        self.commits = 0

    def add(self, obj):
        self._apply_defaults(obj)
        self.storage.setdefault(type(obj), [])
        if obj not in self.storage[type(obj)]:
            self.storage[type(obj)].append(obj)

    def _apply_defaults(self, obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = str(uuid4())
        now = datetime.utcnow()
        for attr in ("created_at", "started_at"):
            if hasattr(obj, attr) and getattr(obj, attr, None) is None:
                setattr(obj, attr, now)
        for attr in ("metadata_json", "summary_json", "metrics_json", "config_json", "output_json"):
            if hasattr(obj, attr) and getattr(obj, attr, None) is None:
                setattr(obj, attr, {})

    async def flush(self):
        for rows in self.storage.values():
            for obj in rows:
                self._apply_defaults(obj)

    async def commit(self):
        self.commits += 1
        await self.flush()

    async def refresh(self, obj):
        self._apply_defaults(obj)

    async def get(self, model, obj_id):
        for obj in self.storage.get(model, []):
            if getattr(obj, "id", None) == obj_id:
                return obj
        return None

    async def execute(self, stmt):
        if isinstance(stmt, Delete):
            model = self._model_for_table(stmt.table.name)
            rows = self.storage.get(model, [])
            self.storage[model] = [obj for obj in rows if not self._matches_where(obj, stmt._where_criteria)]
            return FakeResult([])
        if not isinstance(stmt, Select):
            raise AssertionError(f"Unsupported statement type: {type(stmt)}")
        model = stmt.column_descriptions[0]["entity"]
        rows = [obj for obj in self.storage.get(model, []) if self._matches_where(obj, stmt._where_criteria)]
        return FakeResult(rows)

    def _model_for_table(self, table_name):
        for model in self.MODELS:
            if model.__tablename__ == table_name:
                return model
        raise AssertionError(f"Unknown table {table_name}")

    def _matches_where(self, obj, criteria):
        if not criteria:
            return True
        return all(self._eval_criterion(obj, criterion) for criterion in criteria)

    def _eval_criterion(self, obj, criterion):
        left_name = getattr(getattr(criterion, "left", None), "name", None)
        if not left_name:
            return True
        left_value = getattr(obj, left_name)
        right = getattr(criterion, "right", None)
        right_value = getattr(right, "value", right)
        if criterion.operator == operators.eq:
            return left_value == right_value
        if criterion.operator == operators.in_op:
            return left_value in list(right_value)
        raise AssertionError(f"Unsupported operator {criterion.operator}")


def make_upload(filename: str, payload: bytes, content_type: str = "text/plain") -> UploadFile:
    return UploadFile(file=io.BytesIO(payload), filename=filename, headers={"content-type": content_type})


def make_user() -> User:
    return User(id="user-1", email="cp@example.com", name="CP", password_hash="x", role=UserRole.admin, is_active=True)


def test_secret_redaction_covers_common_credentials():
    text = "password=abc token: xyz api_key=\"k\" private_key_file=/tmp/key snowflake://user:pass@acct"
    redacted = redact_secrets(text)
    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "/tmp/key" not in redacted
    assert "pass@acct" not in redacted
    assert redacted.count("[REDACTED]") >= 4


def test_upload_validation_rejects_unsupported_file_type():
    with pytest.raises(HTTPException) as exc:
        validate_upload("unsafe.exe", b"payload")
    assert exc.value.status_code == 415
    assert ".sql" in exc.value.detail


def test_sql_statement_split_and_type_detection():
    sql = "CREATE TABLE t(id INT);\nMERGE INTO t USING s ON t.id=s.id WHEN MATCHED THEN UPDATE SET id=s.id;"
    statements = split_sql_statements(sql)
    assert len(statements) == 2
    assert statement_type(statements[0][1]) == "DDL"
    assert statement_type(statements[1][1]) == "MERGE"


def test_provision_plan_is_plan_only_and_blocks_drop():
    plan = ProvisionService(None).generate_plan(
        {
            "project_name": "UMA",
            "target_database": "UMA_DB",
            "raw_schema": "RAW",
            "staging_schema": "STAGING",
            "curated_schema": "CURATED",
            "reporting_schema": "REPORTING",
        }
    )
    assert plan["status"] == "PLANNED_NOT_EXECUTED"
    assert plan["destructive_operations_blocked"] is True
    assert all(not stmt.lower().lstrip().startswith("drop ") for stmt in plan["statements"])


def test_analyzer_extracts_xml_components_and_dependencies(tmp_path):
    xml = "<workflow><source name='src_orders'/><transform name='clean_orders' source='src_orders' target='tgt_orders'/></workflow>"
    path = tmp_path / "flow.xml"
    path.write_text(xml)
    artifact = type(
        "Artifact",
        (),
        {
            "storage_path": str(path),
            "file_type": "xml",
            "original_filename": "flow.xml",
        },
    )()
    components, dependencies, metadata = AnalyzerService(None).extract_components(artifact, "GENERIC_XML")
    assert metadata["xml_root"] == "workflow"
    assert any(component["name"] == "src_orders" for component in components)
    assert dependencies[0]["source_component"] == "src_orders"
    assert dependencies[0]["target_component"] == "tgt_orders"


def test_control_plane_artifact_upload_and_sql_analysis_persist_real_records(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload(
                "orders.sql",
                b"CREATE TABLE orders (id NUMBER(38), updated_at TIMESTAMP);\nMERGE INTO orders USING stage_orders ON orders.id = stage_orders.id;",
                "text/sql",
            ),
            user,
        )
        run_row = await common.create_run(
            name="SQL Readiness",
            workflow_type="SQL_CONVERSION",
            user=user,
            source_dialect="oracle",
            target_dialect="snowflake",
            config_json={"artifact_ids": [artifact.id]},
        )
        report = await SqlConversionService(db).analyze(run_row, [artifact])
        messages = db.storage.get(SqlConversionMessage, [])
        jobs = db.storage.get(ControlPlaneJob, [])
        artifacts = db.storage.get(ControlPlaneArtifact, [])

        assert artifact.artifact_category == "SOURCE_DDL"
        assert artifact.storage_path
        assert report["summary"]["files"] == 1
        assert report["summary"]["statements"] == 2
        assert report["analysis_engine"] == "sqlglot"
        assert report["readiness_score"] < 100
        assert any(msg.severity == "WARN" for msg in messages)
        assert any(msg.statement_type == "MERGE" for msg in messages)
        assert any(job.module == "SQL_CONVERSION" and job.status == "COMPLETED" for job in jobs)
        assert any(row.artifact_category == "REPORT" and row.run_id == run_row.id for row in artifacts)

    asyncio.run(run())


def test_snowflake_validation_unlocks_package_only_after_explain_passes(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        run_row = await common.create_run(
            name="full validation",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
        )
        package = await common.store_binary_artifact(run_row.id, "CONVERSION_PACKAGE", "review.zip", b"zip", user.id, "application/zip")
        await common.store_text_artifact(run_row.id, "GENERATED_DBT", "models/orders.sql", "select 1 as order_id", user.id, "text/sql")
        run_row.summary_json = {
            "review_package_artifact_id": package.id,
            "download_artifact_id": None,
            "job_state": {
                "snowflake_ready": False,
                "judge_status": "passed",
                "rules_applied_count": 1,
                "source_residue": [],
                "readiness_reasons": [{"category": "snowflake_validation", "message": "Snowflake validation has not run."}],
            },
            "file_reports": [
                {
                    "source_path": "orders.sql",
                    "target_path": "models/orders.sql",
                    "converted_sql": "select 1 as order_id",
                    "rules_applied": ["deterministic_rewrite"],
                    "warnings": [],
                    "unsupported_features": [],
                    "errors": [],
                    "readiness_reasons": [],
                    "source_residue": [],
                    "judge_status": "passed",
                    "snowflake_ready": True,
                }
            ],
        }

        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
            if "compile" in cmd:
                compiled = Path(cwd) / "target" / "compiled" / "uma_conversion" / "models"
                compiled.mkdir(parents=True, exist_ok=True)
                (compiled / "orders.sql").write_text("select 1 as order_id", encoding="utf-8")
            return Completed()

        async def fake_readiness(self, cfg):
            return {
                "status": "passed",
                "validation_status": "connection_ready",
                "checks": [{"check": "account_reachable", "status": "passed", "evidence": {}, "error": ""}],
                "permission_checks": [{"check": "create_permission", "status": "passed", "evidence": {}, "error": ""}],
                "errors": [],
                "warnings": [],
                "message": "ready",
            }

        async def fake_explain(self, cfg, entries):
            return {
                "status": "passed",
                "results": [{"model": "models/orders.sql", "status": "passed", "explained_statements": 1, "errors": [], "warnings": []}],
                "errors": [],
                "warnings": [],
            }

        monkeypatch.setattr(snowflake_conversion_module.shutil, "which", lambda name: "/usr/local/bin/dbt" if name == "dbt" else None)
        monkeypatch.setattr(snowflake_conversion_module.subprocess, "run", fake_run)
        monkeypatch.setattr(SqlToSnowflakeConversionEngine, "_run_snowflake_readiness_checks", fake_readiness)
        monkeypatch.setattr(SqlToSnowflakeConversionEngine, "_run_snowflake_explain_validation", fake_explain)

        payload = await SqlToSnowflakeConversionEngine(db).validate(
            run_row,
            None,
            credentials={"account": "acct", "user": "svc", "password": "pw", "role": "TRANSFORMER", "warehouse": "WH", "database": "DB", "schema": "PUBLIC"},
        )

        assert payload["validation_status"] == "validation_passed"
        assert payload["validation_passed"] is True
        assert payload["snowflake_validation_status"] == "explain_passed"
        assert run_row.summary_json["job_state"]["snowflake_ready"] is True
        assert run_row.summary_json["download_artifact_id"] == package.id
        assert run_row.summary_json["review_package_artifact_id"] is None

    asyncio.run(run())


def test_validation_failure_materializes_brain_review_explain_blocker(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        run_row = await common.create_run(
            name="explain blocker",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
        )
        run_row.summary_json = {
            "validation": {
                "validation_job_id": "validation-1",
                "validation_status": "validation_failed",
                "validation_passed": False,
                "syntax_results": [
                    {"model": "models/orders.sql", "status": "failed", "errors": ["SQL compilation error"], "warnings": []}
                ],
                "model_errors": ["models/orders.sql: SQL compilation error"],
            }
        }

        created = await BrainReviewMaterializer(db).materialize_run(run_row)
        items = db.storage.get(HumanReviewItem, [])
        assert created >= 2
        assert any(item.item_type == "SNOWFLAKE_EXPLAIN_FAILURE" and item.status == "BLOCKED" for item in items)
        assert any(item.item_type == "SNOWFLAKE_VALIDATION_FAILURE" for item in items)

    asyncio.run(run())


def test_sql_translation_generates_safe_sql_and_marks_unsupported(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload("mixed.sql", b"SELECT TOP 5 * FROM dbo.orders;\nCREATE PROCEDURE p AS BEGIN SELECT 1; END;", "text/sql"),
            user,
        )
        run_row = await common.create_run(
            name="Translate",
            workflow_type="SQL_CONVERSION",
            user=user,
            source_dialect="mssql",
            target_dialect="snowflake",
            config_json={"artifact_ids": [artifact.id]},
        )
        payload = await SqlConversionService(db).translate(run_row)
        assert payload["translation_engine"] == "sqlglot"
        assert payload["translated_files"]
        assert payload["unsupported_items"]
        assert payload["executed"] is False
        generated = [row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category == "GENERATED_SQL"]
        assert generated

    asyncio.run(run())


def test_sql_translation_generates_separate_snowflake_sql_and_dbt_artifacts(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload(
                "profiles_model.sql",
                (
                    b"{{ config(materialized='table') }}\n"
                    b"with profile_ids as (\n"
                    b"  select id merged_id, pp raw_id\n"
                    b"  from {{ source('inguest', 'property_profile') }}\n"
                    b"  left join unnest(profileIds) pp\n"
                    b")\n"
                    b"select DATE_DIFF(current_date(), created_at, DAY) as profile_age_days\n"
                    b"from profile_ids\n"
                ),
                "text/sql",
            ),
            user,
        )
        run_row = await common.create_run(
            name="Translate dbt BigQuery model",
            workflow_type="SQL_CONVERSION",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
            config_json={"artifact_ids": [artifact.id]},
        )

        payload = await SqlConversionService(db).translate(run_row)
        generated_sql = [row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category == "GENERATED_SQL"]
        generated_dbt = [row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category == "GENERATED_DBT"]
        sql_text = Path(generated_sql[0].storage_path).read_text()
        dbt_text = Path(generated_dbt[0].storage_path).read_text()

        assert payload["translated_files"]
        assert generated_sql
        assert generated_dbt
        assert "{{" not in sql_text
        assert '"inguest"."property_profile"' in sql_text
        assert "pp.value raw_id" in sql_text
        assert "DATEDIFF('DAY', created_at, current_date())" in sql_text
        assert "{{ config(materialized='table') }}" in dbt_text
        assert "{{ source('inguest', 'property_profile') }}" in dbt_text
        assert "pp.value raw_id" in dbt_text
        assert "DATE_DIFF" not in dbt_text
        assert "UNNEST" not in dbt_text

    asyncio.run(run())


def test_migration_intelligence_end_to_end_generates_review_items_and_report(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        sql_artifact = await common.create_artifact_from_upload(
            make_upload("legacy.sql", b"CREATE PROCEDURE p AS BEGIN EXECUTE IMMEDIATE 'select 1'; END;", "text/sql"),
            user,
        )
        xml_artifact = await common.create_artifact_from_upload(
            make_upload("flow.xml", b"<workflow><transform name='x' source='a' target='b'/></workflow>", "application/xml"),
            user,
        )
        run_row = await common.create_run(
            name="Readiness",
            workflow_type="MIGRATION_READINESS",
            user=user,
            source_dialect="oracle",
            target_dialect="snowflake",
            config_json={"artifact_ids": [sql_artifact.id, xml_artifact.id]},
        )
        report = await MigrationIntelligenceControlService(db).execute(run_row, [sql_artifact, xml_artifact])

        assert report["migration_summary"]["artifact_count"] == 2
        assert report["migration_summary"]["llm_status"] == "SKIPPED_REQUIRES_CONFIGURATION"
        assert report["readiness_score"] < 100
        assert report["risk_register"]
        assert report["validation_plan"]["execution_status"] == "PLANNED"
        await BrainReviewMaterializer(db).materialize_run(run_row)
        assert db.storage.get(HumanReviewItem)
        assert any(row.artifact_category == "REPORT" and row.run_id == run_row.id for row in db.storage.get(ControlPlaneArtifact, []))
        assert run_row.status == "REQUIRES_REVIEW"

    asyncio.run(run())


def test_provision_apply_is_blocked_without_approval():
    db = FakeControlPlaneSession()
    run = ControlPlaneRun(
        id="run-1",
        name="Provision",
        workflow_type="SNOWFLAKE_PROVISIONING",
        safety_mode="PLAN_ONLY",
        status="PENDING",
        approval_granted=False,
    )
    with pytest.raises(HTTPException) as exc:
        ControlPlaneService(db).enforce_write_approval(run)
    assert exc.value.status_code == 409
    assert run.status == "APPROVAL_REQUIRED"


def test_data_contract_and_metadata_search_are_deterministic(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload("contract.sql", b"CREATE TABLE customer_dim (customer_id NUMBER, email VARCHAR);", "text/sql"),
            user,
        )
        run_row = await common.create_run(
            name="Contracts",
            workflow_type="DATA_CONTRACT_DISCOVERY",
            user=user,
            config_json={"artifact_ids": [artifact.id]},
        )
        contract = await DataContractService(db).generate(run_row, [artifact])
        search = await MetadataSearchService(db).search("customer email", 5)
        nl2sql = await MetadataSearchService(db).guarded_nl2sql("show customer rows")

        assert contract["contracts"][0]["columns"]
        assert contract["review_required"] is True
        assert search["results"]
        assert nl2sql["status"] == "DRAFT_NOT_EXECUTED"
        assert nl2sql["execution_allowed"] is False
        with pytest.raises(HTTPException):
            await MetadataSearchService(db).guarded_nl2sql("drop customer table")

    asyncio.run(run())


def test_multi_dialect_detection_scores_bigquery_signatures():
    engine = SqlToSnowflakeConversionEngine(None)
    detection = engine.detect_dialect(
        "select SAFE_CAST(id as INT64) from `proj.dataset.orders`, unnest(items) as item",
        None,
    )
    assert detection.dialect == "bigquery"
    assert detection.confidence >= 50
    assert detection.reasons


def test_offline_conversion_preserves_dbt_jinja_and_generates_downloadable_package(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload(
                "orders_model.sql",
                (
                    b"{{ config(materialized='view') }}\n"
                    b"select SAFE_CAST(order_id as INT64) as order_id\n"
                    b"from {{ source('raw', 'orders') }}\n"
                    b"where created_at >= {{ var('cutoff_date') }}\n"
                ),
                "text/sql",
            ),
            user,
        )
        run_row = await common.create_run(
            name="dbt offline conversion",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
            safety_mode="PLAN_ONLY",
            config_json={"artifact_ids": [artifact.id], "input_type": "sql_file"},
        )

        payload = await SqlToSnowflakeConversionEngine(db).convert(run_row, [artifact])
        generated_sql = [row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category in {"GENERATED_SQL", "GENERATED_DBT"}]
        package = next(row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category == "CONVERSION_PACKAGE")
        sql_text = Path(generated_sql[0].storage_path).read_text()

        assert "{{ config(materialized='view') }}" in sql_text
        assert "{{ source('raw', 'orders') }}" in sql_text
        assert "{{ var('cutoff_date') }}" in sql_text
        assert "TRY_CAST" in sql_text
        assert payload["executed"] is False
        assert package.storage_path

        with zipfile.ZipFile(package.storage_path, "r") as zf:
            names = set(zf.namelist())
            assert "conversion_report.json" in names
            assert "dialect_detection_report.json" in names
            assert "unsupported_features.json" in names
            assert "model_conversion_report.csv" in names
            assert "conversion_warnings.md" in names

    asyncio.run(run())


def test_dbt_project_zip_conversion_preserves_structure_and_converts_model_sql(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dbt_project.yml", "name: demo\nversion: '1.0'\n")
            zf.writestr("models/staging/orders.sql", "select SAFE_CAST(order_id as INT64) as order_id from `proj.ds.orders`")
            zf.writestr("models/schema.yml", "version: 2\nmodels: []\n")
            zf.writestr("macros/keep.sql", "{% macro my_macro() %}select 1{% endmacro %}")

        artifact = await common.create_artifact_from_upload(
            make_upload("demo_dbt.zip", buffer.getvalue(), "application/zip"),
            user,
        )
        run_row = await common.create_run(
            name="project conversion",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
            safety_mode="PLAN_ONLY",
            config_json={"artifact_ids": [artifact.id], "input_type": "dbt_project"},
        )

        payload = await SqlToSnowflakeConversionEngine(db).convert(run_row, [artifact])
        package = next(row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category == "CONVERSION_PACKAGE")

        with zipfile.ZipFile(package.storage_path, "r") as zf:
            assert "dbt_project.yml" in zf.namelist()
            assert "models/staging/orders.sql" in zf.namelist()
            assert "models/schema.yml" in zf.namelist()
            assert "macros/keep.sql" in zf.namelist()
            converted_sql = zf.read("models/staging/orders.sql").decode("utf-8")
            assert "TRY_CAST" in converted_sql
            assert '"proj"."ds"."orders"' in converted_sql or '"proj"."ds"."orders"' in converted_sql.replace("\n", " ")
            assert "{% macro my_macro() %}select 1{% endmacro %}" == zf.read("macros/keep.sql").decode("utf-8")

        assert payload["file_count"] == 1
        assert payload["executed"] is False

    asyncio.run(run())


def test_bigquery_dbt_conversion_rewrites_dates_preserves_jinja_and_flags_incremental_risk():
    engine = SqlToSnowflakeConversionEngine(None)
    source = (
        "{{ config(materialized='incremental') }}\n"
        "with base as (\n"
        "  select\n"
        "    TIMESTAMP_TRUNC(event_ts, DAY) as event_day,\n"
        "    TIMESTAMP_TRUNC(event_ts, QUARTER) as event_quarter,\n"
        "    DATE_TRUNC(order_date, MONTH) as order_month,\n"
        "    DATE_TRUNC(order_date, QUARTER) as order_quarter,\n"
        "    DATETIME_ADD(DATETIME(order_date), INTERVAL 2 MONTH) as plus_two_months,\n"
        "    DATE_SUB(order_date, INTERVAL 7 DAY) as minus_week,\n"
        "    LAST_DAY(order_date, month) as month_end,\n"
        "    TIME(12, 10, 00) as noonish,\n"
        "    DATE(order_ts) as order_date_cast\n"
        "  from {{ source('raw', 'orders') }}\n"
        ")\n"
        "select * from base\n"
    )

    converted = engine._convert_sql_text(source, "bigquery", "dbt_project")
    sql = converted["sql"]

    assert sql.startswith("{{ config(materialized='incremental') }}")
    assert "{{ source('raw', 'orders') }}" in sql
    assert "DATE_TRUNC('DAY', event_ts)" in sql
    assert "DATE_TRUNC('QUARTER', event_ts)" in sql
    assert "DATE_TRUNC('MONTH', order_date)" in sql
    assert "DATEADD(MONTH, 2, order_date)" in sql
    assert "DATEADD(DAY, -7, order_date)" in sql
    assert "LAST_DAY(order_date, 'MONTH')" in sql
    assert "TIME_FROM_PARTS(12, 10, 0)" in sql
    assert "TO_DATE(order_ts)" in sql
    assert "TIMESTAMP_TRUNC" not in sql
    assert "DATETIME_ADD" not in sql
    assert "DATE_SUB" not in sql
    assert converted["rules_applied"]
    assert any("unique_key was not confirmed" in warning for warning in converted["warnings"])
    assert any(reason["category"] == "dbt_incremental" for reason in converted["readiness_reasons"])
    assert any("is_incremental" in reason["message"] for reason in converted["readiness_reasons"])
    assert converted["judge_status"] in {"passed", "passed_with_warnings"}
    assert converted["source_residue"] == []


def test_bigquery_conversion_rewrites_nested_dates_raw_strings_and_split_ordinal():
    engine = SqlToSnowflakeConversionEngine(None)
    source = (
        "select\n"
        "  DATE_DIFF(coalesce(actual_checkin_date, checkin_date), booking_date, DAY) as lead_days,\n"
        "  PARSE_TIMESTAMP('%m/%d/%y %H:%M:%S', created_at) as created_at_ts,\n"
        "  TIMESTAMP(DATE_TRUNC(current_date(), MONTH)) as month_start_ts,\n"
        "  split(trim(zipcode, r'\\'#`\"& '), '-')[ordinal(1)] as zip_prefix\n"
        "from `dbt_dev.usa_zip_code_db`\n"
    )

    converted = engine._convert_sql_text(source, "bigquery", "sql_file")
    sql = converted["sql"]

    assert "DATEDIFF('DAY', booking_date, coalesce(actual_checkin_date, checkin_date))" in sql
    assert "TO_TIMESTAMP_NTZ(created_at, 'MM/DD/YY HH24:MI:SS')" in sql
    assert "TO_TIMESTAMP(DATE_TRUNC('MONTH', current_date()))" in sql
    assert "SPLIT_PART(trim(zipcode, '''#`\"& '), '-', 1)" in sql
    assert 'from "dbt_dev"."usa_zip_code_db"' in sql
    assert 'bk"."state' not in sql
    assert "ordinal(" not in sql.lower()
    assert "PARSE_TIMESTAMP" not in sql
    assert "DATE_DIFF" not in sql
    assert converted["source_residue"] == []


def test_bigquery_conversion_rewrites_flatten_alias_access():
    engine = SqlToSnowflakeConversionEngine(None)
    source = (
        "with profile_ids as (\n"
        "  select id merged_id, pp raw_id\n"
        "  from `inguest.property_profile`\n"
        "  left join unnest(profileIds) pp\n"
        "), prop_post as (\n"
        "  select coalesce(address.gCountryShort, trim(address.country)) country\n"
        "  from `inguest.property_profile` pp\n"
        "  left join unnest(pp.postalAddresses) address\n"
        "  where address.isPrimary = true\n"
        ")\n"
        "select count(distinct profiles) profile_count from `inguest.property_profile`, unnest(profileIds) profiles\n"
    )

    converted = engine._convert_sql_text(source, "bigquery", "sql_file")
    sql = converted["sql"]

    assert "pp.value raw_id" in sql
    assert "address.value:gCountryShort" in sql
    assert "trim(address.value:country)" in sql
    assert "address.value:isPrimary = true" in sql
    assert "count(distinct profiles.value)" in sql
    assert "UNNEST" not in sql
    assert converted["source_residue"] == []


def test_conversion_judge_rejects_copied_bigquery_sql():
    engine = SqlToSnowflakeConversionEngine(None)
    source = (
        "{{ config(materialized='incremental') }}\n"
        "select TIMESTAMP_TRUNC(event_ts, DAY) as event_day,\n"
        "       DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day\n"
        "from {{ source('raw', 'orders') }}\n"
    )
    judge = engine.judge_conversion(
        source_sql=source,
        converted_sql=source,
        detected_dialect="bigquery",
        rules_applied=[],
        warnings=[],
        unsupported_features=[],
    )

    assert judge["judge_status"] == "failed"
    assert judge["snowflake_ready"] is False
    assert judge["copied_source_sql"] is True
    assert "TIMESTAMP_TRUNC" in judge["source_residue"]
    assert "DATE_SUB" in judge["source_residue"]


def test_dbt_semantic_readiness_reasons_for_incremental_models():
    engine = SqlToSnowflakeConversionEngine(None)
    missing_unique_key = (
        "{{ config(materialized='incremental') }}\n"
        "select * from {{ source('raw', 'orders') }}\n"
        "{% if is_incremental() %} where updated_at > (select max(updated_at) from {{ this }}) {% endif %}\n"
    )
    missing_filter = (
        "{{ config(materialized='incremental', unique_key='order_id') }}\n"
        "select * from {{ source('raw', 'orders') }}\n"
    )

    unique_key_result = engine._convert_sql_text(missing_unique_key, "bigquery", "dbt_project")
    filter_result = engine._convert_sql_text(missing_filter, "bigquery", "dbt_project")

    assert unique_key_result["snowflake_ready"] is False
    assert any("unique_key was not confirmed" in reason["message"] for reason in unique_key_result["readiness_reasons"])
    assert any(reason["category"] == "dbt_mapping" for reason in unique_key_result["readiness_reasons"])

    assert filter_result["snowflake_ready"] is False
    assert any("is_incremental" in reason["message"] for reason in filter_result["readiness_reasons"])
    assert any(reason["category"] == "snowflake_validation" for reason in filter_result["readiness_reasons"])


def test_conversion_judge_rejects_zero_rules_parser_errors_and_residue():
    engine = SqlToSnowflakeConversionEngine(None)

    zero_rules = engine.judge_conversion(
        source_sql="select 1 as id",
        converted_sql="select 1 as id",
        detected_dialect="bigquery",
        rules_applied=[],
        warnings=[],
        unsupported_features=[],
    )
    assert zero_rules["judge_status"] == "failed"
    assert zero_rules["snowflake_ready"] is False
    assert zero_rules["rules_applied_count"] == 0
    assert any("No deterministic" in error for error in zero_rules["errors"])

    parser_failed = engine.judge_conversion(
        source_sql="select a from t",
        converted_sql="select a::variant from t",
        detected_dialect="bigquery",
        rules_applied=["manual_type_review"],
        warnings=[],
        unsupported_features=["Parser-backed translation failed: Invalid expression"],
    )
    assert parser_failed["judge_status"] == "failed"
    assert parser_failed["parser_failed"] is True
    assert parser_failed["snowflake_ready"] is False

    residue = engine.judge_conversion(
        source_sql="select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
        converted_sql="select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
        detected_dialect="bigquery",
        rules_applied=["some_rule"],
        warnings=[],
        unsupported_features=[],
    )
    assert residue["judge_status"] == "failed"
    assert residue["snowflake_ready"] is False
    assert "DATE_SUB" in residue["source_residue"]


def test_repair_loop_applies_fallback_rules_and_preserves_failure_when_residue_remains():
    engine = SqlToSnowflakeConversionEngine(None)
    copied_source = (
        "select TIMESTAMP_TRUNC(event_ts, DAY) as event_day,\n"
        "       DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day\n"
        "from orders\n"
    )

    first_judge = engine.judge_conversion(
        source_sql=copied_source,
        converted_sql=copied_source,
        detected_dialect="bigquery",
        rules_applied=[],
        warnings=[],
        unsupported_features=[],
    )
    repair = engine.repair_sql_once(
        source_sql=copied_source,
        converted_sql=copied_source,
        detected_dialect="bigquery",
        input_type="sql_file",
    )
    second_judge = engine.judge_conversion(
        source_sql=copied_source,
        converted_sql=repair["sql"],
        detected_dialect="bigquery",
        rules_applied=repair["rules_applied"],
        warnings=repair["warnings"],
        unsupported_features=repair["unsupported_features"],
    )

    assert first_judge["judge_status"] == "failed"
    assert repair["changed"] is True
    assert "TIMESTAMP_TRUNC->DATE_TRUNC" in repair["rules_applied"]
    assert "DATE_SUB_INTERVAL_DAY->DATEADD" in repair["rules_applied"]
    assert second_judge["judge_status"] == "passed"
    assert second_judge["snowflake_ready"] is True

    unsupported_source = "select STRUCT(1 as a) as s"
    unsupported = engine._convert_sql_text(unsupported_source, "bigquery", "dbt_project")
    assert len(unsupported["repair_attempts"]) <= 2
    assert unsupported["judge_status"] == "failed"
    assert unsupported["snowflake_ready"] is False
    assert "STRUCT" in unsupported["source_residue"]


def test_tracking_changes_bigquery_model_runs_judge_once_and_dedupes_report_rows(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload(
                "tracking_changes_css_carr_dashboard.sql",
                (
                    b"{{ config(materialized='incremental') }}\n"
                    b"with base as (\n"
                    b"  select TIMESTAMP_TRUNC(event_ts, DAY) as event_day,\n"
                    b"         DATETIME_ADD(DATETIME(order_date), INTERVAL 2 MONTH) as plus_two_months,\n"
                    b"         DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day,\n"
                    b"         SAFE_CAST(order_id as INT64) as order_id\n"
                    b"  from {{ source('raw', 'orders') }}\n"
                    b")\n"
                    b"select * from base\n"
                ),
                "text/sql",
            ),
            user,
        )
        run_row = await common.create_run(
            name="tracking dashboard conversion",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
            safety_mode="PLAN_ONLY",
            config_json={"artifact_ids": [artifact.id], "input_type": "dbt_project"},
        )

        payload = await SqlToSnowflakeConversionEngine(db).convert(run_row, [artifact])
        package = next(row for row in db.storage.get(ControlPlaneArtifact, []) if row.artifact_category == "CONVERSION_PACKAGE")
        file_report = payload["file_reports"][0]

        assert payload["file_count"] == 1
        assert payload["job_state"]["total_files"] == 1
        assert payload["job_state"]["rules_applied_count"] > 0
        assert payload["job_state"]["status"] == "requires_review"
        assert payload["job_state"]["requires_review_count"] == 1
        assert payload["job_state"]["judge_status"] == "passed_with_warnings"
        assert any(reason["category"] == "dbt_incremental" for reason in payload["job_state"]["readiness_reasons"])
        assert file_report["source_residue"] == []
        assert file_report["snowflake_ready"] is False
        assert file_report["conversion_status"] == "REQUIRES_REVIEW"
        assert any("unique_key was not confirmed" in reason["message"] for reason in file_report["readiness_reasons"])
        assert any("is_incremental" in reason["message"] for reason in file_report["readiness_reasons"])
        assert "TIMESTAMP_TRUNC" not in file_report["converted_sql"]
        assert "DATETIME_ADD" not in file_report["converted_sql"]
        assert "DATE_SUB" not in file_report["converted_sql"]
        assert "DATEADD(MONTH, 2, order_date)" in file_report["converted_sql"]
        assert "DATEADD(DAY, -1, order_date)" in file_report["converted_sql"]

        with zipfile.ZipFile(package.storage_path, "r") as zf:
            csv_rows = list(csv.DictReader(io.StringIO(zf.read("model_conversion_report.csv").decode("utf-8"))))
            rows = zf.read("conversion_warnings.md").decode("utf-8").split("## ")
            rows = [row for row in rows if "tracking_changes_css_carr_dashboard.sql" in row]
            assert len(csv_rows) == 1
            assert csv_rows[0]["source_path"] == "tracking_changes_css_carr_dashboard.sql"
            assert csv_rows[0]["target_path"] == "models/tracking_dashboard_conversion/tracking_changes_css_carr_dashboard.sql"
            assert "converted/tracking_changes_css_carr_dashboard.sql" in zf.namelist()
            assert len(rows) == 1

    asyncio.run(run())


def test_migration_intelligence_engine_registers_graph_rag_and_copilot_context(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        artifact = await common.create_artifact_from_upload(
            make_upload(
                "tracking_changes_css_carr_dashboard.sql",
                (
                    b"{{ config(materialized='incremental') }}\n"
                    b"with base as (\n"
                    b"  select TIMESTAMP_TRUNC(event_ts, DAY) as event_day,\n"
                    b"         DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day\n"
                    b"  from {{ source('raw', 'orders') }}\n"
                    b")\n"
                    b"select * from base\n"
                ),
                "text/sql",
            ),
            user,
        )
        run_row = await common.create_run(
            name="agentic conversion",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
            safety_mode="PLAN_ONLY",
            config_json={"artifact_ids": [artifact.id], "input_type": "dbt_project"},
        )

        payload = await MigrationIntelligenceEngine(db).agentic_convert(run_row, [artifact], provider_name="offline", use_llm=False)
        chat = await MigrationIntelligenceEngine(db).copilot_chat(run_row, "what changed and is it Snowflake-ready?")

        node_names = {node["node"] for node in payload["graph"]}
        ordered_nodes = [node["node"] for node in payload["graph"]]
        for left, right in [
            ("DbtProjectAnalysisNode", "StaticRuleConversionNode"),
            ("StaticRuleConversionNode", "ConversionJudgeNode"),
            ("ConversionJudgeNode", "RepairNode"),
            ("RepairNode", "SecondJudgePassNode"),
            ("SecondJudgePassNode", "FinalQualityGateNode"),
        ]:
            assert ordered_nodes.index(left) < ordered_nodes.index(right)
        assert "UploadInventoryNode" in node_names
        assert "StaticRuleConversionNode" in node_names
        assert "RagRetrievalNode" in node_names
        assert "ConversionJudgeNode" in node_names
        assert "RepairNode" in node_names
        assert "SecondJudgePassNode" in node_names
        assert "FinalQualityGateNode" in node_names
        assert "DeepAgentReviewNode" in node_names
        assert "CopilotContextNode" in node_names
        assert payload["engine"] == "MigrationIntelligenceEngine"
        assert payload["conversion_context"]["files"][0]["rag_results"]
        assert payload["conversion_context"]["files"][0]["agent_review_results"]["findings"]
        assert "TIMESTAMP_TRUNC->DATE_TRUNC" in payload["conversion_context"]["files"][0]["rules_applied"]
        assert "Snowflake-ready" in chat["answer"] or "changed" in chat["answer"]
        assert payload["executed"] is False

    asyncio.run(run())


def test_copilot_answers_from_conversion_job_context():
    async def run():
        run_row = ControlPlaneRun(
            id=str(uuid4()),
            name="contextual copilot",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            source_dialect="bigquery",
            target_dialect="snowflake",
            safety_mode="PLAN_ONLY",
            status="requires_review",
            created_by="user-1",
            config_json={},
            summary_json={
                "job_state": {
                    "judge_status": "failed",
                    "snowflake_ready": False,
                    "source_residue": ["DATE_SUB"],
                    "warnings": ["AI review unavailable because no LLM provider is configured."],
                    "readiness_reasons": [
                        {
                            "category": "dbt_incremental",
                            "severity": "warning",
                            "message": "Incremental model requires review because unique_key was not confirmed.",
                            "recommended_action": "Add or confirm unique_key and incremental_strategy before Snowflake-ready approval.",
                        }
                    ],
                    "errors": ["Source-dialect residue remains after conversion."],
                    "unsupported_features": ["Source-dialect residue remains: DATE_SUB."],
                },
                "conversion_context": {
                    "files": [
                        {
                            "source_path": "tracking_changes_css_carr_dashboard.sql",
                            "original_sql": "{{ config(materialized='incremental') }} select DATE_SUB(order_date, INTERVAL 1 DAY)",
                            "converted_sql": "{{ config(materialized='incremental') }} select DATE_SUB(order_date, INTERVAL 1 DAY)",
                            "diff": "",
                            "rules_applied": ["TIMESTAMP_TRUNC->DATE_TRUNC"],
                            "judge_status": "failed",
                            "snowflake_ready": False,
                            "source_residue": ["DATE_SUB"],
                            "warnings": ["AI review unavailable because no LLM provider is configured."],
                            "readiness_reasons": [
                                {
                                    "category": "dbt_incremental",
                                    "severity": "warning",
                                    "message": "Incremental model requires review because unique_key was not confirmed.",
                                    "recommended_action": "Add or confirm unique_key and incremental_strategy before Snowflake-ready approval.",
                                }
                            ],
                            "errors": ["Source-dialect residue remains after conversion."],
                            "unsupported_features": ["Source-dialect residue remains: DATE_SUB."],
                        }
                    ]
                },
            },
        )
        engine = MigrationIntelligenceEngine(FakeControlPlaneSession())

        why = await engine.copilot_chat(run_row, "Why did this conversion fail?")
        remains = await engine.copilot_chat(run_row, "What BigQuery syntax remains?")
        rules = await engine.copilot_chat(run_row, "What rules were applied?")
        ready = await engine.copilot_chat(run_row, "Is this Snowflake-ready?")
        dbt = await engine.copilot_chat(run_row, "What dbt risks exist?")

        assert "Source-dialect residue remains" in why["answer"]
        assert "DATE_SUB" in remains["answer"]
        assert "TIMESTAMP_TRUNC->DATE_TRUNC" in rules["answer"]
        assert "Snowflake-ready: no" in ready["answer"]
        review = await engine.copilot_chat(run_row, "Why is this still Requires Review?")

        assert "Incremental model requires review" in dbt["answer"]
        assert "still not Snowflake-ready" in review["answer"]

    asyncio.run(run())


def test_ai_patch_unavailable_state_and_structured_provider_response(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        run_row = ControlPlaneRun(
            id=str(uuid4()),
            name="ai patch",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            source_dialect="bigquery",
            target_dialect="snowflake",
            safety_mode="PLAN_ONLY",
            status="requires_review",
            created_by="user-1",
            config_json={"input_type": "sql_file"},
            summary_json={
                "job_state": {"snowflake_ready": False, "validation_status": "not_run"},
                "conversion_context": {
                    "files": [
                        {
                            "source_path": "orders.sql",
                            "target_path": "converted/orders.sql",
                            "detected_dialect": "bigquery",
                            "original_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
                            "converted_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
                            "rules_applied": [],
                            "warnings": [],
                            "unsupported_features": [],
                            "source_residue": ["DATE_SUB"],
                        }
                    ]
                },
            },
        )
        engine = MigrationIntelligenceEngine(db)
        unavailable = await engine.propose_ai_patch(run_row, selected_file="orders.sql", provider_name="offline")
        assert unavailable["status"] == "AI_UNAVAILABLE"
        assert unavailable["auto_applied"] is False
        assert unavailable["provider_status"]["ai_patch_available"] is False

        class FakeProvider:
            name = "openai"
            model = "test-model"

            async def propose_patch(self, payload):
                return {
                    "available": True,
                    "provider": "openai",
                    "model": "test-model",
                    "proposed_sql": "select DATEADD(DAY, -1, order_date) as prior_day from orders",
                    "explanation": "Replaced BigQuery DATE_SUB with Snowflake DATEADD.",
                    "assumptions": ["Column types are date-compatible."],
                    "risks": ["Manual review still required."],
                    "readiness_changes_expected": ["DATE_SUB residue removed."],
                    "patch_confidence": 0.82,
                    "manual_review_required": True,
                }

        monkeypatch.setattr(brain_module, "llm_provider_status", lambda provider=None: {
            "provider_configured": True,
            "provider_name": "openai",
            "model_name": "test-model",
            "ai_review_available": True,
            "ai_patch_available": True,
            "status": "configured",
            "message": "available",
        })
        monkeypatch.setattr(brain_module, "llm_provider", lambda provider=None: FakeProvider())
        proposed = await engine.propose_ai_patch(run_row, selected_file="orders.sql", provider_name="openai")

        assert proposed["status"] == "PROPOSED"
        assert proposed["proposal"]["patch_confidence"] == 0.82
        assert "DATEADD" in proposed["proposed_sql"]
        assert proposed["auto_applied"] is False
        assert "DATE_SUB" in proposed["proposal"]["structured_diff"]

    asyncio.run(run())


def test_patch_apply_reruns_judge_and_keeps_package_blocked_without_validation(tmp_path):
    async def run():
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        run_row = await common.create_run(
            name="patch apply",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
            config_json={"input_type": "sql_file"},
        )
        run_row.summary_json = {
            "job_state": {"snowflake_ready": False, "validation_status": "not_run", "rules_applied_count": 0},
            "conversion_context": {
                "files": [
                    {
                        "source_path": "orders.sql",
                        "target_path": "converted/orders.sql",
                        "detected_dialect": "bigquery",
                        "original_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
                        "converted_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
                        "conversion_status": "FAILED",
                        "rules_applied": [],
                        "warnings": [],
                        "unsupported_features": [],
                        "source_residue": ["DATE_SUB"],
                        "judge_status": "failed",
                        "snowflake_ready": False,
                    }
                ]
            },
            "ai_patches": [
                {
                    "patch_id": "patch_test",
                    "target_path": "converted/orders.sql",
                    "source_path": "orders.sql",
                    "detected_dialect": "bigquery",
                    "input_type": "sql_file",
                    "original_sql": "select DATE_SUB(order_date, INTERVAL 1 DAY) as prior_day from orders",
                    "proposed_sql": "select DATEADD(DAY, -1, order_date) as prior_day from orders",
                }
            ],
        }
        result = await MigrationIntelligenceEngine(db).apply_patch(run_row, patch_id="patch_test", confirmed=True)

        assert result["status"] == "PATCH_APPLIED"
        assert result["assessment"]["source_residue"] == []
        assert result["assessment"]["judge_status"] == "passed"
        assert run_row.summary_json["job_state"]["snowflake_ready"] is False
        assert run_row.summary_json["download_artifact_id"] is None

    asyncio.run(run())


def test_validation_requires_credentials_and_passed_validation_updates_readiness(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        run_row = await common.create_run(
            name="validation",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
        )
        run_row.summary_json = {
            "job_state": {
                "snowflake_ready": False,
                "judge_status": "passed",
                "rules_applied_count": 1,
                "source_residue": [],
                "readiness_reasons": [
                    {
                        "category": "snowflake_validation",
                        "severity": "warning",
                        "message": "Snowflake compile validation has not run.",
                        "recommended_action": "Run dbt compile.",
                    }
                ],
            },
            "file_reports": [
                {
                    "source_path": "orders.sql",
                    "target_path": "converted/orders.sql",
                    "converted_sql": "select DATEADD(DAY, -1, order_date) from orders",
                    "rules_applied": ["DATE_SUB_INTERVAL_DAY->DATEADD"],
                    "warnings": ["Snowflake compile validation has not run."],
                    "unsupported_features": [],
                    "errors": [],
                    "readiness_reasons": [
                        {
                            "category": "snowflake_validation",
                            "severity": "warning",
                            "message": "Snowflake compile validation has not run.",
                            "recommended_action": "Run dbt compile.",
                        }
                    ],
                    "source_residue": [],
                    "judge_status": "passed",
                    "snowflake_ready": False,
                }
            ],
        }
        engine = SqlToSnowflakeConversionEngine(db)
        blocked = await engine.validate(run_row, None, credentials={})
        assert blocked["validation_status"] == "credentials_required"
        assert blocked["blocked_reason"] == "credentials_required"
        assert run_row.summary_json["job_state"]["snowflake_ready"] is False

        merged = engine._merge_validation(run_row.summary_json, {
            "validation_status": "validation_passed",
            "validation_passed": True,
            "dbt_compile_passed": True,
            "compile_errors": [],
            "model_errors": [],
            "warnings": [],
        })
        assert merged["job_state"]["validation_status"] == "validation_passed"
        assert not any(reason.get("category") == "snowflake_validation" for reason in merged["job_state"]["readiness_reasons"])

    asyncio.run(run())


def test_dbt_compile_validation_runs_and_keeps_snowflake_package_blocked(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(control_plane_module, "ARTIFACT_ROOT", tmp_path)
        db = FakeControlPlaneSession()
        user = make_user()
        common = ControlPlaneService(db)
        run_row = await common.create_run(
            name="compile validation",
            workflow_type="SQL_DBT_TO_SNOWFLAKE",
            user=user,
            source_dialect="bigquery",
            target_dialect="snowflake",
        )
        package = await common.store_binary_artifact(run_row.id, "CONVERSION_PACKAGE", "review.zip", b"zip", user.id, "application/zip")
        await common.store_text_artifact(run_row.id, "GENERATED_DBT", "models/orders.sql", "select 1 as order_id", user.id, "text/sql")
        run_row.summary_json = {
            "review_package_artifact_id": package.id,
            "download_artifact_id": None,
            "job_state": {
                "snowflake_ready": False,
                "judge_status": "passed",
                "rules_applied_count": 1,
                "source_residue": [],
                "readiness_reasons": [
                    {
                        "category": "snowflake_validation",
                        "severity": "warning",
                        "message": "Snowflake compile validation has not run.",
                        "recommended_action": "Run dbt compile.",
                    }
                ],
            },
            "file_reports": [
                {
                    "source_path": "orders.sql",
                    "target_path": "models/orders.sql",
                    "converted_sql": "select 1 as order_id",
                    "rules_applied": ["deterministic_rewrite"],
                    "warnings": ["Snowflake compile validation has not run."],
                    "unsupported_features": [],
                    "errors": [],
                    "readiness_reasons": [
                        {
                            "category": "snowflake_validation",
                            "severity": "warning",
                            "message": "Snowflake compile validation has not run.",
                            "recommended_action": "Run dbt compile.",
                        }
                    ],
                    "source_residue": [],
                    "judge_status": "passed",
                    "snowflake_ready": False,
                }
            ],
        }

        class Completed:
            def __init__(self, returncode=0):
                self.returncode = returncode
                self.stdout = "ok"
                self.stderr = ""

        calls = []

        def fake_run(cmd, cwd, env, capture_output, text, timeout, check):
            calls.append(cmd)
            if "compile" in cmd:
                compiled = Path(cwd) / "target" / "compiled" / "uma_conversion" / "models"
                compiled.mkdir(parents=True, exist_ok=True)
                (compiled / "orders.sql").write_text("select 1 as order_id", encoding="utf-8")
            return Completed(0)

        monkeypatch.setattr(snowflake_conversion_module.shutil, "which", lambda name: "/usr/local/bin/dbt" if name == "dbt" else None)
        monkeypatch.setattr(snowflake_conversion_module.subprocess, "run", fake_run)
        async def fake_readiness(self, cfg):
            return {
                "status": "passed",
                "validation_status": "connection_ready",
                "checks": [{"check": "account_reachable", "status": "passed", "evidence": {}, "error": ""}],
                "permission_checks": [{"check": "create_permission", "status": "passed", "evidence": {}, "error": ""}],
                "errors": [],
                "warnings": [],
                "message": "ready",
            }

        async def fake_explain(self, cfg, entries):
            return {
                "status": "validation_failed",
                "results": [{"model": "models/orders.sql", "status": "failed", "errors": ["syntax error"], "warnings": []}],
                "errors": ["models/orders.sql: syntax error"],
                "warnings": [],
            }

        monkeypatch.setattr(SqlToSnowflakeConversionEngine, "_run_snowflake_readiness_checks", fake_readiness)
        monkeypatch.setattr(SqlToSnowflakeConversionEngine, "_run_snowflake_explain_validation", fake_explain)

        payload = await SqlToSnowflakeConversionEngine(db).validate(
            run_row,
            None,
            credentials={
                "account": "acct",
                "user": "svc",
                "password": "pw",
                "role": "TRANSFORMER",
                "warehouse": "WH",
                "database": "DB",
                "schema": "PUBLIC",
            },
        )
        assert payload["validation_status"] == "validation_failed"
        assert payload["dbt_compile_passed"] is True
        assert payload["validation_passed"] is False
        assert payload["snowflake_validation_status"] == "validation_failed"
        assert payload["model_errors"]
        assert any("parse" in call for call in calls)
        assert any("compile" in call for call in calls)
        assert run_row.summary_json["job_state"]["snowflake_ready"] is False
        assert run_row.summary_json["download_artifact_id"] is None
        assert run_row.summary_json["review_package_artifact_id"] == package.id
        assert any(row.artifact_category == "VALIDATION_RESULT" and row.original_filename == "dbt_compile.log" for row in db.storage[ControlPlaneArtifact])

    asyncio.run(run())
