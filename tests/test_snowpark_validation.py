import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.snowpark_validation import SnowparkTableRef, SnowparkValidationService  # noqa: E402


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def collect(self):
        return self.rows


class FakeSession:
    def __init__(self):
        self.sqls = []

    def sql(self, sql):
        self.sqls.append(sql)
        if "DESCRIBE TABLE" in sql:
            return FakeResult([{"name": "ID"}, {"name": "UPDATED_AT"}])
        if "DUPLICATE_COUNT" in sql:
            return FakeResult([{"DUPLICATE_COUNT": 2}])
        if "MIN_WATERMARK" in sql:
            return FakeResult([{"MIN_WATERMARK": "2026-01-01", "MAX_WATERMARK": "2026-01-02"}])
        if "SOFT_DELETE_COUNT" in sql:
            return FakeResult([{"SOFT_DELETE_COUNT": 1}])
        if "HASH_AGG" in sql:
            return FakeResult([{"ROW_HASH": "12345"}])
        return FakeResult([{"ROW_COUNT": 10}])


def test_snowpark_profile_runs_aggregate_sql_in_snowflake():
    session = FakeSession()
    service = SnowparkValidationService(session)
    ref = SnowparkTableRef(database="ANALYTICS", schema="PUBLIC", table="CUSTOMERS")

    profile = service.profile_table(
        ref,
        primary_key_columns=["ID"],
        watermark_column="UPDATED_AT",
        soft_delete_column="IS_DELETED",
    )

    assert profile["row_count"] == 10
    assert profile["column_count"] == 2
    assert profile["duplicate_primary_key_count"] == 2
    assert profile["soft_delete_count"] == 1
    assert any("GROUP BY" in sql and "HAVING COUNT(*) > 1" in sql for sql in session.sqls)
    assert all("SELECT *" not in sql.upper() for sql in session.sqls)


def test_snowpark_sample_hash_validation_uses_hash_aggregate():
    session = FakeSession()
    service = SnowparkValidationService(session)
    ref = SnowparkTableRef(database="ANALYTICS", schema="PUBLIC", table="CUSTOMERS")

    result = service.validate_sample_hash("expected", ref, ["ID", "UPDATED_AT"])

    assert result["status"] == "FAILED"
    assert result["target_value"] == "12345"
    assert any("HASH_AGG(HASH" in sql for sql in session.sqls)
