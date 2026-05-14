import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.migration_intelligence import StaticProvider, scrub_context  # noqa: E402
from services.schema_drift import additive_alter_statements, compare_schemas  # noqa: E402


def test_schema_drift_detects_add_remove_type_and_nullable_changes():
    source = [
        {"name": "id", "type": "NUMBER(38,0)", "nullable": False},
        {"name": "name", "type": "VARCHAR", "nullable": True},
        {"name": "updated_at", "type": "TIMESTAMP_NTZ", "nullable": False},
        {"name": "new_col", "type": "VARCHAR", "nullable": True},
    ]
    target = [
        {"name": "id", "type": "NUMBER(38,0)", "nullable": False},
        {"name": "name", "type": "NUMBER", "nullable": False},
        {"name": "old_col", "type": "VARCHAR", "nullable": True},
        {"name": "_UMA_BATCH_ID", "type": "VARCHAR", "nullable": True},
    ]

    findings = compare_schemas(source, target)
    by_type = {(f.drift_type, f.column_name) for f in findings}

    assert ("added", "UPDATED_AT") in by_type
    assert ("added", "NEW_COL") in by_type
    assert ("removed", "OLD_COL") in by_type
    assert ("type_changed", "NAME") in by_type
    assert ("nullable_changed", "NAME") in by_type

    alters = additive_alter_statements("DB", "SCHEMA", "T", findings)
    assert all("DROP" not in sql.upper() for sql in alters)
    assert any('ADD COLUMN IF NOT EXISTS "NEW_COL"' in sql for sql in alters)


def test_migration_intelligence_scrubs_sensitive_context():
    payload = {
        "connection": {
            "account": "acct",
            "password": "secret",
            "api_token": "tok",
            "nested": {"private_key": "key"},
        }
    }

    scrubbed = scrub_context(payload)

    assert scrubbed["connection"]["account"] == "acct"
    assert scrubbed["connection"]["password"] == "[REDACTED]"
    assert scrubbed["connection"]["api_token"] == "[REDACTED]"
    assert scrubbed["connection"]["nested"]["private_key"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_static_provider_returns_configured_response():
    provider = StaticProvider("ok")
    assert await provider.complete("system", "prompt") == "ok"
