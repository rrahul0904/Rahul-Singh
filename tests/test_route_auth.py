import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")
os.environ["REDIS_URL"] = ""

from main import app  # noqa: E402
from api.routes.auth import LoginRequest, RegisterRequest  # noqa: E402


client = TestClient(app, raise_server_exceptions=False)


def assert_auth_required(method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code in {401, 403}


def test_job_endpoints_reject_unauthenticated_requests():
    job_body = {
        "name": "secure-route-test",
        "source_connection_id": "src",
        "dest_connection_id": "dst",
        "tasks": [],
    }
    assert_auth_required("GET", "/api/jobs")
    assert_auth_required("GET", "/api/jobs/stats/summary")
    assert_auth_required("POST", "/api/jobs", json=job_body)
    assert_auth_required("GET", "/api/jobs/job-1")
    assert_auth_required("POST", "/api/jobs/job-1/execute")
    assert_auth_required("POST", "/api/jobs/job-1/execute-real")
    assert_auth_required("POST", "/api/jobs/job-1/cancel")
    assert_auth_required("PUT", "/api/jobs/job-1/schedule", json={"schedule_cron": None})
    assert_auth_required("GET", "/api/jobs/job-1/runs")
    assert_auth_required("GET", "/api/jobs/job-1/runs/run-1")
    assert_auth_required("GET", "/api/jobs/job-1/state")
    assert_auth_required("GET", "/api/jobs/job-1/tasks")
    assert_auth_required(
        "POST",
        "/api/jobs/job-1/tasks",
        json={
            "source_dataset": "public",
            "source_table": "t",
            "target_schema": "RAW",
            "target_table": "T",
            "config": {},
        },
    )
    assert_auth_required("DELETE", "/api/jobs/job-1/tasks/task-1")
    assert_auth_required("GET", "/api/jobs/job-1/logs")
    assert_auth_required("DELETE", "/api/jobs/job-1")


def test_replication_endpoints_reject_unauthenticated_requests():
    assert_auth_required("GET", "/api/replication/overview")
    assert_auth_required("GET", "/api/replication/connections")
    assert_auth_required(
        "POST",
        "/api/replication/connections",
        json={"name": "pg", "connector_type": "postgres", "role": "source"},
    )
    assert_auth_required("POST", "/api/replication/connections/conn-1/test")
    assert_auth_required("GET", "/api/replication/sources")
    assert_auth_required("POST", "/api/replication/sources/discover", json={"connection_id": "conn-1"})
    assert_auth_required("GET", "/api/replication/jobs")
    assert_auth_required(
        "POST",
        "/api/replication/jobs",
        json={"name": "job", "source_connection_id": "src", "destination_connection_id": "dst"},
    )
    assert_auth_required("GET", "/api/replication/jobs/job-1")
    assert_auth_required("POST", "/api/replication/jobs/job-1/start")
    assert_auth_required("POST", "/api/replication/jobs/job-1/pause")
    assert_auth_required("POST", "/api/replication/jobs/job-1/resume")
    assert_auth_required("POST", "/api/replication/jobs/job-1/cancel")
    assert_auth_required("POST", "/api/replication/jobs/job-1/retry")
    assert_auth_required("GET", "/api/replication/jobs/job-1/tables")
    assert_auth_required("PUT", "/api/replication/jobs/job-1/tables", json={"tables": []})
    assert_auth_required("GET", "/api/replication/runs")
    assert_auth_required("GET", "/api/replication/runs/run-1")
    assert_auth_required("GET", "/api/replication/runs/run-1/events")
    assert_auth_required("GET", "/api/replication/runs/run-1/tables")
    assert_auth_required("GET", "/api/replication/snowflake/readiness")
    assert_auth_required("POST", "/api/replication/snowflake/check-permissions", json={})


def test_metadata_validation_and_ai_reject_unauthenticated_requests():
    assert_auth_required("GET", "/api/tables")
    assert_auth_required("GET", "/api/tables/stats")

    assert_auth_required("GET", "/api/validation")
    assert_auth_required(
        "POST",
        "/api/validation",
        json={"name": "row parity", "rule_type": "row_count", "target_table": "RAW.T"},
    )
    assert_auth_required("GET", "/api/validation/rule-1")
    assert_auth_required("POST", "/api/validation/rule-1/run")
    assert_auth_required("POST", "/api/validation/reconcile", json={"job_id": "job-1"})

    assert_auth_required("POST", "/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert_auth_required("POST", "/api/ai/sql", json={"question": "count rows"})
    assert_auth_required("POST", "/api/ai/agent", json={"message": "status"})
    assert_auth_required("POST", "/api/ai/cortex-agent", json={"message": "status"})
    assert_auth_required("GET", "/api/ai/cortex-agent/architecture")
    assert_auth_required("POST", "/api/ai/summarize", json={"job_id": "job-1"})
    assert_auth_required("POST", "/api/ai/document", json={"table_name": "T", "schema": []})
    assert_auth_required("POST", "/api/ai/validate-suggest", json={"table_name": "T", "schema": []})
    assert_auth_required("POST", "/api/ai/explain-sql", json={"sql": "select 1"})
    assert_auth_required("POST", "/api/ai/dbt-model", json={"source_table": "T", "schema": []})
    assert_auth_required("POST", "/api/ai/search", json={"query": "orders"})
    assert_auth_required("GET", "/api/ai/lineage/RAW.T")
    assert_auth_required("GET", "/api/copilot/providers")
    assert_auth_required("GET", "/api/copilot/snowflake-services")
    assert_auth_required("POST", "/api/copilot/ask", json={"message": "status"})
    assert_auth_required("POST", "/api/copilot/actions/preview", json={"action_type": "get_validation_summary"})
    assert_auth_required("POST", "/api/copilot/snowflake-services/query", json={"service": "health"})
    assert_auth_required("POST", "/api/copilot/actions/execute", json={"action_type": "cancel_run", "confirmed": True})
    assert_auth_required("GET", "/api/internal-tools/status")
    assert_auth_required("GET", "/api/internal-tools/tools")
    assert_auth_required("POST", "/api/internal-tools/call", json={"name": "uma.list_runs", "arguments": {}})


def test_migration_intelligence_endpoints_reject_unauthenticated_requests():
    assert_auth_required("GET", "/api/intelligence/artifacts")
    assert_auth_required("POST", "/api/intelligence/artifacts/upload", files={"file": ("orders.sql", b"select 1;", "text/plain")})
    assert_auth_required("GET", "/api/intelligence/artifacts/artifact-1")
    assert_auth_required("POST", "/api/intelligence/runs", json={"selected_artifact_ids": ["artifact-1"]})
    assert_auth_required("GET", "/api/intelligence/runs")
    assert_auth_required("GET", "/api/intelligence/runs/run-1")
    assert_auth_required("GET", "/api/intelligence/runs/run-1/steps")
    assert_auth_required("GET", "/api/intelligence/runs/run-1/findings")
    assert_auth_required("GET", "/api/intelligence/reports/report-1")
    assert_auth_required("GET", "/api/intelligence/reports/report-1/preview")
    assert_auth_required("GET", "/api/intelligence/reports/report-1/download.md")
    assert_auth_required("GET", "/api/intelligence/reports/report-1/download.pdf")
    assert_auth_required("GET", "/api/intelligence/reports/report-1/download.docx")


def test_auth_models_accept_local_bootstrap_email_in_non_production():
    register = RegisterRequest(email="admin@uma.local", name="Admin", password="Admin123!Secure")
    login = LoginRequest(email="admin@uma.local", password="Admin123!Secure")

    assert register.email == "admin@uma.local"
    assert login.email == "admin@uma.local"
