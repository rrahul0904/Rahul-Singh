# UMA Real Migration Engine — First Product Core

This build adds the first real table movement path. The goal is not to support every source yet; it is to prove one reliable product loop:

`Source table -> chunked Parquet files -> Snowflake internal stage -> Snowflake target table -> persisted run state`

## Supported in this pass

Sources:
- BigQuery
- Postgres
- Redshift
- MySQL

Target:
- Snowflake

Load strategies:
- `full_load`: truncate target and reload from staged chunks
- `incremental`: extract rows newer than the stored watermark and merge by primary key
- `upsert`: same execution path as incremental merge
- `cdc`: watermark + merge + optional soft delete flag, not log-based CDC yet

## Example job payload

```json
{
  "name": "Postgres customers to Snowflake",
  "source_connection_id": "<source-connection-id>",
  "dest_connection_id": "<snowflake-connection-id>",
  "sf_warehouse": "COMPUTE_WH",
  "sf_database": "ANALYTICS_DB",
  "sf_schema": "RAW",
  "load_strategy": "incremental",
  "file_format": "parquet",
  "staging_area": "internal",
  "tasks": [
    {
      "source_dataset": "public",
      "source_table": "customers",
      "target_schema": "RAW",
      "target_table": "CUSTOMERS",
      "config": {
        "primary_key_columns": ["id"],
        "watermark_column": "updated_at",
        "delete_flag_column": "is_deleted",
        "batch_size": 50000
      }
    }
  ]
}
```

## Run the real engine

```bash
curl -X POST "http://localhost:8000/api/jobs/<job_id>/execute?engine=real"
```

For synchronous debugging:

```bash
curl -X POST "http://localhost:8000/api/jobs/<job_id>/execute-real"
```

Check history:

```bash
curl http://localhost:8000/api/jobs/<job_id>/runs
curl http://localhost:8000/api/jobs/<job_id>/state
```

## Product roadmap from here

1. Stabilize this path with one real source table.
2. Add source-vs-target validation immediately after each task.
3. Add schema drift preflight before extraction.
4. Add SQL Server and Oracle source adapters.
5. Add S3/GCS staging for large-scale production runs.
6. Add log-based CDC connectors after watermark CDC is stable.
