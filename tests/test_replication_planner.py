import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from models import ReplicationDestination, ReplicationJob, ReplicationJobTable  # noqa: E402
from services.replication_planner import plan_table  # noqa: E402


def test_replication_planner_chooses_merge_upsert_from_key_and_watermark():
    job = ReplicationJob(id="job-1", name="CRM", source_connection_id="src", destination_connection_id="dst", sync_mode="incremental", schedule="0 2 * * *")
    table = ReplicationJobTable(
        id="table-1",
        job_id="job-1",
        schema_name="public",
        table_name="customers",
        target_schema="RAW",
        target_table="CUSTOMERS",
        selected=True,
        sync_mode="incremental",
        columns=[
            {"name": "id", "type": "NUMBER"},
            {"name": "updated_at", "type": "TIMESTAMP_NTZ"},
            {"name": "is_deleted", "type": "BOOLEAN"},
            {"name": "name", "type": "VARCHAR"},
        ],
        primary_key_columns=["id"],
        watermark_column="updated_at",
    )
    destination = ReplicationDestination(database="ANALYTICS", schema="RAW", warehouse="WH")

    plan = plan_table(table, job, destination)

    assert plan.load_mode == "SOFT_DELETE_AWARE"
    assert plan.write_mode == "STAGE_AND_MERGE"
    assert plan.target_database == "ANALYTICS"
    assert plan.primary_key_columns == ["id"]
    assert plan.watermark_column == "updated_at"
    assert plan.incremental_supported is True
    assert plan.risk_level == "LOW"


def test_replication_planner_stays_conservative_without_columns():
    job = ReplicationJob(id="job-1", name="CRM", source_connection_id="src", destination_connection_id="dst", sync_mode="incremental")
    table = ReplicationJobTable(
        id="table-1",
        job_id="job-1",
        schema_name="public",
        table_name="events",
        selected=True,
        sync_mode="incremental",
        columns=[],
        primary_key_columns=[],
    )

    plan = plan_table(table, job, None)

    assert plan.load_mode == "FULL_LOAD"
    assert plan.write_mode == "CREATE_OR_REPLACE"
    assert plan.incremental_supported is False
    assert plan.risk_level == "MEDIUM"
    assert "Column metadata is missing" in plan.reasoning
