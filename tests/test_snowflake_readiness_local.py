import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.snowflake_readiness import check_snowflake_readiness_sync, not_configured_readiness  # noqa: E402


def test_snowflake_readiness_not_configured_has_required_checks():
    result = not_configured_readiness()

    assert result["status"] == "NOT_CONFIGURED"
    keys = {check["key"] for check in result["details"]["checks"]}
    assert "create_table" in keys
    assert "cortex_search" in keys
    assert "spcs_future" in keys


def test_snowflake_readiness_missing_credentials_does_not_connect():
    result = check_snowflake_readiness_sync({"account": "acct", "user": "user"})

    assert result["status"] == "NOT_CONFIGURED"
    assert result["details"]["live_validation"] is False
