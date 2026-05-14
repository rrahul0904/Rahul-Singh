from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STATUSES = {"PASS", "FAIL", "WARNING", "NOT_CONFIGURED", "NOT_CHECKED", "REQUIRES_ADMIN_SETUP"}
SECRET_KEYS = ("password", "secret", "token", "private_key", "passcode")


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    label: str
    status: str
    message: str
    requires_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "requires_admin": self.requires_admin,
        }


def _safe_error(exc: Exception | str) -> str:
    text = str(exc)
    for key in SECRET_KEYS:
        text = text.replace(key, "[redacted]")
    return text[:500]


def not_configured_readiness(message: str = "Snowflake connection is not configured.") -> dict[str, Any]:
    checks = [
        ReadinessCheck("connect", "Can connect", "NOT_CONFIGURED", message),
        ReadinessCheck("current_role", "Current role", "NOT_CONFIGURED", "No Snowflake session."),
        ReadinessCheck("current_warehouse", "Current warehouse", "NOT_CONFIGURED", "No Snowflake session."),
        ReadinessCheck("current_database", "Current database", "NOT_CONFIGURED", "No Snowflake session."),
        ReadinessCheck("current_schema", "Current schema", "NOT_CONFIGURED", "No Snowflake session."),
        ReadinessCheck("warehouse_usage", "Warehouse USAGE/running/resumable", "NOT_CONFIGURED", "Warehouse not validated."),
        ReadinessCheck("database_usage", "Database USAGE", "NOT_CONFIGURED", "Database not validated."),
        ReadinessCheck("schema_usage", "Schema USAGE", "NOT_CONFIGURED", "Schema not validated."),
        ReadinessCheck("create_table", "CREATE TABLE", "NOT_CONFIGURED", "Grant not validated."),
        ReadinessCheck("create_stage", "CREATE STAGE", "NOT_CONFIGURED", "Grant not validated."),
        ReadinessCheck("create_file_format", "CREATE FILE FORMAT", "NOT_CONFIGURED", "Grant not validated."),
        ReadinessCheck("create_task", "CREATE TASK readiness", "NOT_CONFIGURED", "Grant not validated."),
        ReadinessCheck("dml_readiness", "SELECT / INSERT / UPDATE / MERGE / COPY INTO readiness", "NOT_CONFIGURED", "DML grants not validated."),
        ReadinessCheck("cortex_user", "CORTEX_USER or equivalent", "NOT_CONFIGURED", "Cortex grants not validated.", True),
        ReadinessCheck("cortex_search", "Cortex Search readiness", "NOT_CONFIGURED", "Cortex Search not validated.", True),
        ReadinessCheck("cortex_analyst", "Cortex Analyst readiness", "NOT_CONFIGURED", "Cortex Analyst not validated.", True),
        ReadinessCheck("semantic_view", "Semantic view readiness", "NOT_CONFIGURED", "Semantic views not validated.", True),
        ReadinessCheck("account_usage", "Account usage view access", "NOT_CONFIGURED", "Account usage access not validated.", True),
        ReadinessCheck("spcs_future", "SPCS future readiness", "NOT_CONFIGURED", "SPCS readiness only; no compute pool creation.", True),
    ]
    return {
        "status": "NOT_CONFIGURED",
        "message": message,
        "missing_permissions": ["SNOWFLAKE_CONNECTION"],
        "safe_error": "",
        "details": {"checks": [c.to_dict() for c in checks], "live_validation": False, "mfa_required": False},
    }


def check_snowflake_readiness_sync(config: dict[str, Any]) -> dict[str, Any]:
    required = ["account", "user"]
    if not config or any(not config.get(k) for k in required) or not (config.get("password") or config.get("private_key")):
        return not_configured_readiness("Snowflake account/user/password or private key is missing; live checks were not attempted.")

    checks: list[ReadinessCheck] = []
    try:
        import snowflake.connector
        from snowflake.connector import DictCursor

        conn = snowflake.connector.connect(
            account=config.get("account"),
            user=config.get("user"),
            password=config.get("password", ""),
            warehouse=config.get("warehouse") or None,
            database=config.get("database") or None,
            schema=config.get("schema") or None,
            role=config.get("role") or None,
            passcode=config.get("mfa_passcode") or None,
            session_parameters={"QUERY_TAG": "UMA_PERMISSION_DIAGNOSTIC_READ_ONLY"},
        )
        try:
            with conn.cursor(DictCursor) as cur:
                cur.execute("SELECT CURRENT_ROLE() ROLE, CURRENT_WAREHOUSE() WAREHOUSE, CURRENT_DATABASE() DATABASE, CURRENT_SCHEMA() SCHEMA")
                row = cur.fetchone() or {}
        finally:
            conn.close()
    except Exception as exc:
        err = _safe_error(exc)
        lowered = err.lower()
        mfa = "mfa" in lowered or "totp" in lowered or "passcode" in lowered
        result = not_configured_readiness("Snowflake connection failed; permission checks were not attempted.")
        result["status"] = "FAIL"
        result["safe_error"] = err
        result["details"]["mfa_required"] = mfa
        if mfa:
            result["message"] = "Snowflake requires MFA/TOTP; provide a current passcode and rerun diagnostics."
        return result

    role = row.get("ROLE")
    warehouse = row.get("WAREHOUSE")
    database = row.get("DATABASE")
    schema = row.get("SCHEMA")
    checks.extend([
        ReadinessCheck("connect", "Can connect", "PASS", "Read-only Snowflake session opened successfully."),
        ReadinessCheck("current_role", "Current role", "PASS" if role else "WARNING", role or "No active role returned."),
        ReadinessCheck("current_warehouse", "Current warehouse", "PASS" if warehouse else "WARNING", warehouse or "No active warehouse returned."),
        ReadinessCheck("current_database", "Current database", "PASS" if database else "WARNING", database or "No active database returned."),
        ReadinessCheck("current_schema", "Current schema", "PASS" if schema else "WARNING", schema or "No active schema returned."),
        ReadinessCheck("warehouse_usage", "Warehouse USAGE/running/resumable", "NOT_CHECKED", "Prepared check; no warehouse mutation or resume was attempted."),
        ReadinessCheck("database_usage", "Database USAGE", "NOT_CHECKED", "Prepared check; database grant probing is staged for admin review."),
        ReadinessCheck("schema_usage", "Schema USAGE", "NOT_CHECKED", "Prepared check; schema grant probing is staged for admin review."),
        ReadinessCheck("create_table", "CREATE TABLE", "NOT_CHECKED", "DDL was not executed; validate via admin grant review."),
        ReadinessCheck("create_stage", "CREATE STAGE", "NOT_CHECKED", "DDL was not executed; validate via admin grant review."),
        ReadinessCheck("create_file_format", "CREATE FILE FORMAT", "NOT_CHECKED", "DDL was not executed; validate via admin grant review."),
        ReadinessCheck("create_task", "CREATE TASK readiness", "REQUIRES_ADMIN_SETUP", "Tasks often require explicit CREATE TASK and EXECUTE TASK setup.", True),
        ReadinessCheck("dml_readiness", "SELECT / INSERT / UPDATE / MERGE / COPY INTO readiness", "NOT_CHECKED", "No target DML was executed; grants must be reviewed."),
        ReadinessCheck("cortex_user", "CORTEX_USER or equivalent", "REQUIRES_ADMIN_SETUP", "Cortex privileges are account/role governed.", True),
        ReadinessCheck("cortex_search", "Cortex Search readiness", "REQUIRES_ADMIN_SETUP", "Requires Cortex Search service privileges and warehouse policy.", True),
        ReadinessCheck("cortex_analyst", "Cortex Analyst readiness", "REQUIRES_ADMIN_SETUP", "Requires semantic model and Cortex Analyst enablement.", True),
        ReadinessCheck("semantic_view", "Semantic view readiness", "REQUIRES_ADMIN_SETUP", "Requires semantic view privileges and reviewed DDL.", True),
        ReadinessCheck("account_usage", "Account usage view access", "WARNING", "Optional for cost reconciliation; requires imported privileges or delegated views.", True),
        ReadinessCheck("spcs_future", "SPCS future readiness", "REQUIRES_ADMIN_SETUP", "Future readiness only; no compute pool creation was attempted.", True),
    ])
    return {
        "status": "WARNING",
        "message": "Snowflake connectivity passed. Grant-level checks are prepared but not fully executed because this diagnostic is non-destructive.",
        "missing_permissions": [c.key for c in checks if c.status in {"REQUIRES_ADMIN_SETUP", "FAIL"}],
        "safe_error": "",
        "details": {
            "checks": [c.to_dict() for c in checks],
            "live_validation": True,
            "mfa_required": False,
            "current": {"role": role, "warehouse": warehouse, "database": database, "schema": schema},
        },
    }


def check_snowflake_readiness_with_connector(connector: Any) -> dict[str, Any]:
    """Run the non-destructive readiness probe on an already authenticated session."""
    try:
        rows = connector.run_query(
            "SELECT CURRENT_ROLE() ROLE, CURRENT_WAREHOUSE() WAREHOUSE, "
            "CURRENT_DATABASE() DATABASE, CURRENT_SCHEMA() SCHEMA"
        )
        row = rows[0] if rows else {}
    except Exception as exc:
        result = not_configured_readiness("Active Snowflake session could not be used for readiness checks.")
        result["status"] = "WARNING"
        result["safe_error"] = _safe_error(exc)
        return result

    role = row.get("ROLE")
    warehouse = row.get("WAREHOUSE")
    database = row.get("DATABASE")
    schema = row.get("SCHEMA")
    checks = [
        ReadinessCheck("connect", "Can connect", "PASS", "Reused active Snowflake MFA session."),
        ReadinessCheck("current_role", "Current role", "PASS" if role else "WARNING", role or "No active role returned."),
        ReadinessCheck("current_warehouse", "Current warehouse", "PASS" if warehouse else "WARNING", warehouse or "No active warehouse returned."),
        ReadinessCheck("current_database", "Current database", "PASS" if database else "WARNING", database or "No active database returned."),
        ReadinessCheck("current_schema", "Current schema", "PASS" if schema else "WARNING", schema or "No active schema returned."),
        ReadinessCheck("warehouse_usage", "Warehouse USAGE/running/resumable", "NOT_CHECKED", "Prepared check; no warehouse mutation or resume was attempted."),
        ReadinessCheck("database_usage", "Database USAGE", "NOT_CHECKED", "Prepared check; database grant probing is staged for admin review."),
        ReadinessCheck("schema_usage", "Schema USAGE", "NOT_CHECKED", "Prepared check; schema grant probing is staged for admin review."),
        ReadinessCheck("create_table", "CREATE TABLE", "NOT_CHECKED", "DDL was not executed; validate via admin grant review."),
        ReadinessCheck("create_stage", "CREATE STAGE", "NOT_CHECKED", "DDL was not executed; validate via admin grant review."),
        ReadinessCheck("create_file_format", "CREATE FILE FORMAT", "NOT_CHECKED", "DDL was not executed; validate via admin grant review."),
        ReadinessCheck("create_task", "CREATE TASK readiness", "REQUIRES_ADMIN_SETUP", "Tasks often require explicit CREATE TASK and EXECUTE TASK setup.", True),
        ReadinessCheck("dml_readiness", "SELECT / INSERT / UPDATE / MERGE / COPY INTO readiness", "NOT_CHECKED", "No target DML was executed; grants must be reviewed."),
        ReadinessCheck("cortex_user", "CORTEX_USER or equivalent", "REQUIRES_ADMIN_SETUP", "Cortex privileges are account/role governed.", True),
        ReadinessCheck("cortex_search", "Cortex Search readiness", "REQUIRES_ADMIN_SETUP", "Requires Cortex Search service privileges and warehouse policy.", True),
        ReadinessCheck("cortex_analyst", "Cortex Analyst readiness", "REQUIRES_ADMIN_SETUP", "Requires semantic model and Cortex Analyst enablement.", True),
        ReadinessCheck("semantic_view", "Semantic view readiness", "REQUIRES_ADMIN_SETUP", "Requires semantic view privileges and reviewed DDL.", True),
        ReadinessCheck("account_usage", "Account usage view access", "WARNING", "Optional for cost reconciliation; requires imported privileges or delegated views.", True),
        ReadinessCheck("spcs_future", "SPCS future readiness", "REQUIRES_ADMIN_SETUP", "Future readiness only; no compute pool creation was attempted.", True),
    ]
    return {
        "status": "WARNING",
        "message": "Snowflake readiness reused the active MFA session. Grant-level checks remain non-destructive.",
        "missing_permissions": [c.key for c in checks if c.status in {"REQUIRES_ADMIN_SETUP", "FAIL"}],
        "safe_error": "",
        "details": {
            "checks": [c.to_dict() for c in checks],
            "live_validation": True,
            "mfa_required": True,
            "session_reused": True,
            "current": {"role": role, "warehouse": warehouse, "database": database, "schema": schema},
        },
    }
