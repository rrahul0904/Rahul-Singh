from __future__ import annotations


def plan_data_movement(
    *,
    discovered_objects: list[dict],
    migration_type: str,
    data_volume_tb: float,
) -> dict:
    strategy = "chunked_full_load" if data_volume_tb >= 1 else "direct_extract_load"
    if migration_type in {"incremental", "cdc"}:
        strategy = "merge_watermark_incremental"
    return {
        "strategy": strategy,
        "migration_type": migration_type,
        "object_count": len(discovered_objects),
        "estimated_volume_tb": data_volume_tb,
        "snowflake_load_methods": ["internal_stage", "COPY INTO", "MERGE"],
        "future_methods": ["Snowpipe", "Snowpipe Streaming", "Streams + Tasks", "Dynamic Tables"],
        "job_specs_executable": False,
        "blocked_until": "source_metadata_and_ddl_approval",
    }
