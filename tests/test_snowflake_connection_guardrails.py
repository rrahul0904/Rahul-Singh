import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.managed_syncs import build_job_defaults  # noqa: E402
from services.snowflake_connection import normalize_snowflake_config, snowflake_execution_readiness  # noqa: E402


def test_normalize_snowflake_config_maps_common_aliases():
    normalized = normalize_snowflake_config(
        {
            "username": "uma_user",
            "schema_name": "RAW",
            "dbname": "OPENFLOW",
            "account_identifier": "org-account",
        }
    )

    assert normalized["user"] == "uma_user"
    assert normalized["schema"] == "RAW"
    assert normalized["database"] == "OPENFLOW"
    assert normalized["account"] == "org-account"


def test_snowflake_execution_readiness_flags_interactive_mfa_connections():
    readiness = snowflake_execution_readiness(
        {
            "account": "acct",
            "user": "user",
            "password": "secret",
            "warehouse": "WH",
            "database": "DB",
            "schema": "RAW",
            "auth_method": "password_mfa",
        },
        session_active=False,
    )

    assert readiness["status"] == "REQUIRES_MFA_SESSION"
    assert readiness["can_execute_jobs"] is False
    assert readiness["requires_mfa_session"] is True


def test_build_job_defaults_accepts_schema_name_alias():
    defaults = build_job_defaults(
        {
            "warehouse": "WH",
            "database": "DB",
            "schema_name": "RAW",
            "role": "ACCOUNTADMIN",
        }
    )

    assert defaults["sf_schema"] == "RAW"
