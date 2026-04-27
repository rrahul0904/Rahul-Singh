"""
UMA Platform — Job Execution Engine (Complete)
Orchestrates the full pipeline for ALL source types:
  BigQuery / Redshift / SQLServer / Salesforce / S3 / Azure / FlatFile
  → Stage (S3 / Azure / GCS)
  → Snowflake COPY INTO
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import (
    Job, JobTask, JobLog, JobStatus, TaskStatus,
    LogLevel, Connection, ConnectionType, DestinationMode
)
from connectors.snowflake_connector import SnowflakeConnector
from connectors.bigquery_connector import BigQueryConnector
from connectors.redshift_connector import RedshiftConnector
from connectors.sqlserver_connector import SQLServerConnector
from connectors.salesforce_connector import SalesforceConnector
from connectors.azure_connector import AzureConnector
from connectors.s3_connector import S3Connector
from core.database import AsyncSessionLocal
from core.config import settings
from core.security import get_cipher

logger = logging.getLogger("uma.engine")
_executor = ThreadPoolExecutor(max_workers=10)


async def run_in_thread(fn, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


class JobEngine:

    def __init__(self, job_id: str):
        self.job_id = job_id

    async def execute(self):
        async with AsyncSessionLocal() as db:
            try:
                await self._run(db)
            except Exception as e:
                logger.exception(f"Job {self.job_id} crashed: {e}")
                await self._fail_job(db, str(e))

    async def _run(self, db: AsyncSession):
        job = await self._get_job(db)
        if not job:
            return

        src_conn  = await db.get(Connection, job.source_connection_id)
        dest_conn = await db.get(Connection, job.dest_connection_id)

        await self._update_job(db, job, status=JobStatus.running, phase="STARTING", started_at=datetime.utcnow())
        await self._log(db, "JOB_STARTED", f"Job '{job.name}' started — {src_conn.type.value} → Snowflake")

        tasks = list(job.tasks)
        if not tasks:
            await self._log(db, "NO_TASKS", "No tasks defined.", level=LogLevel.warn)
            await self._update_job(db, job, status=JobStatus.succeeded, phase="COMPLETED", ended_at=datetime.utcnow())
            return

        # Phase 1: Export
        await self._update_job(db, job, phase="EXPORTING")
        await self._log(db, "EXPORT_STARTED", f"Exporting {len(tasks)} tables from {src_conn.type.value}")
        t0 = time.time()
        export_results = await self._export_phase(db, job, src_conn, tasks)
        await self._update_job(db, job, export_duration_s=round(time.time()-t0, 2))
        await self._log(db, "EXPORT_COMPLETE", f"Export done in {time.time()-t0:.1f}s")

        # Phase 2: Stage
        await self._update_job(db, job, phase="STAGING")
        t1 = time.time()
        stage_results = await self._stage_phase(db, job, src_conn, export_results)
        await self._update_job(db, job, stage_duration_s=round(time.time()-t1, 2), phase="LOADING")

        # Phase 3: Load
        await self._log(db, "LOAD_STARTED", f"Loading → Snowflake {job.sf_database}.{job.sf_schema}")
        t2 = time.time()
        sf_config = self._build_sf_config(dest_conn)
        load_results = await self._load_phase(db, job, sf_config, stage_results, tasks)
        await self._update_job(db, job, load_duration_s=round(time.time()-t2, 2))

        # Finalize
        failed     = sum(1 for t in tasks if t.status == TaskStatus.failed)
        total_rows = sum(r.get("rows_loaded", 0) for r in load_results if isinstance(r, dict))
        total_bytes= sum(t.bytes_exported for t in tasks)

        final = (
            JobStatus.failed if failed == len(tasks)
            else JobStatus.partially_succeeded if failed > 0
            else JobStatus.succeeded
        )
        await self._update_job(db, job,
            status=final, phase="COMPLETED", ended_at=datetime.utcnow(),
            total_rows_exported=total_rows, total_bytes=total_bytes,
        )
        await self._log(db, "JOB_COMPLETED",
            f"Done: {len(tasks)-failed}/{len(tasks)} tasks · {total_rows:,} rows · {total_bytes/1e9:.2f} GB")

    # ── Export ────────────────────────────────────────────────

    async def _export_phase(self, db, job, src_conn, tasks) -> List[Dict]:
        results = []
        for task in tasks:
            ref = f"{task.source_dataset}.{task.source_table}"
            try:
                await self._update_task(db, task, TaskStatus.running, started_at=datetime.utcnow())
                await self._log(db, "TASK_EXPORT_STARTED", f"Exporting {ref}", task_ref=ref)
                result = await run_in_thread(self._sync_export, job, src_conn, task)
                task.bytes_exported = result.get("bytes", 0)
                task.files_exported = result.get("files", 1)
                await db.commit()
                results.append(result)
                await self._log(db, "TASK_EXPORT_DONE",
                    f"{ref} → {result.get('files',0)} files {result.get('bytes',0)/1e6:.1f} MB",
                    task_ref=ref)
            except Exception as e:
                await self._update_task(db, task, TaskStatus.failed, error_message=str(e), ended_at=datetime.utcnow())
                await self._log(db, "TASK_EXPORT_FAILED", str(e), level=LogLevel.error, task_ref=ref)
                results.append({"error": str(e), "task_id": task.id})
        return results

    def _sync_export(self, job, src_conn: Connection, task: JobTask) -> Dict:
        s3_prefix = f"uma/{job.id}/{task.source_dataset}/{task.source_table}"

        if src_conn.type == ConnectionType.bigquery:
            return self._export_bigquery(src_conn, task, job)

        elif src_conn.type == ConnectionType.redshift:
            cfg = self._conn_config(src_conn)
            s3_path = f"s3://{settings.S3_STAGING_BUCKET}/{s3_prefix}/"
            with RedshiftConnector(cfg) as rs:
                schema    = rs.get_table_schema(task.source_dataset, task.source_table)
                row_count = rs.get_row_count(task.source_dataset, task.source_table)
                res       = rs.unload_to_s3(task.source_dataset, task.source_table, s3_path,
                                iam_role=cfg.get("iam_role", settings.AWS_ACCESS_KEY_ID),
                                file_format=job.file_format)
            return {"task_id": task.id, "staging_path": s3_path, "staging_type": "s3",
                    "schema": schema, "row_count": row_count, "bytes": 0, "files": 1, **res}

        elif src_conn.type == ConnectionType.sqlserver:
            cfg = self._conn_config(src_conn)
            with SQLServerConnector(cfg) as ss:
                schema = ss.get_table_schema(cfg.get("schema", "dbo"), task.source_table)
                res    = ss.export_to_s3(
                    schema=cfg.get("schema", "dbo"), table=task.source_table,
                    s3_bucket=settings.S3_STAGING_BUCKET, s3_prefix=s3_prefix,
                    aws_access_key=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
                    aws_region=settings.AWS_REGION, file_format=job.file_format)
            return {"task_id": task.id, "staging_path": res["s3_path"], "staging_type": "s3",
                    "schema": schema, "bytes": 0, "files": res["files"], "row_count": res["total_rows"]}

        elif src_conn.type == ConnectionType.salesforce:
            cfg = self._conn_config(src_conn)
            with SalesforceConnector(cfg) as sf:
                schema = sf.get_object_schema(task.source_table)
                res    = sf.export_to_s3(
                    object_name=task.source_table,
                    s3_bucket=settings.S3_STAGING_BUCKET, s3_prefix=s3_prefix,
                    aws_access_key=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
                    aws_region=settings.AWS_REGION)
            return {"task_id": task.id, "staging_path": res["s3_path"], "staging_type": "s3",
                    "schema": schema, "bytes": res.get("bytes",0), "files": res["files"],
                    "row_count": res["total_rows"]}

        elif src_conn.type == ConnectionType.s3:
            cfg = self._conn_config(src_conn)
            with S3Connector(cfg) as s3c:
                prefix = src_conn.config.get("prefix","") + task.source_table + "/"
                files  = s3c.list_files(prefix, max_keys=5)
                schema = []
                if files:
                    k = files[0]["key"]
                    if k.endswith(".parquet"): schema = s3c.infer_schema_from_parquet(k)
                    elif k.endswith(".csv"):   schema = s3c.infer_schema_from_csv(k)
                staging = s3c.get_snowflake_s3_path(prefix)
            return {"task_id": task.id, "staging_path": staging, "staging_type": "s3",
                    "iam_role": cfg.get("iam_role",""),
                    "schema": schema, "bytes": 0, "files": len(files)}

        elif src_conn.type in (ConnectionType.azureblob, ConnectionType.adls):
            cfg = self._conn_config(src_conn)
            with AzureConnector(cfg) as az:
                container = src_conn.config.get("container_name","")
                prefix    = src_conn.config.get("prefix","") + task.source_table + "/"
                if job.staging_area == "s3":
                    res = az.download_to_s3(container, prefix,
                        settings.S3_STAGING_BUCKET, s3_prefix,
                        settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY, settings.AWS_REGION)
                    return {"task_id": task.id, "staging_path": res["s3_path"], "staging_type": "s3",
                            "schema": [], "bytes": res["bytes"], "files": res["files"]}
                else:
                    sas  = az.generate_sas_token(container, expiry_hours=48)
                    path = az.get_snowflake_azure_path(container, prefix)
                    return {"task_id": task.id, "staging_path": path, "staging_type": "azure",
                            "sas_token": sas, "schema": [], "bytes": 0, "files": 0}

        elif src_conn.type == ConnectionType.flatfile:
            staging_path = src_conn.config.get("s3_path","")
            schema       = src_conn.config.get("schema",[])
            return {"task_id": task.id, "staging_path": staging_path,
                    "staging_type": "s3", "schema": schema, "bytes": 0, "files": 1}

        else:
            raise NotImplementedError(f"Source '{src_conn.type.value}' not yet implemented")

    def _export_bigquery(self, src_conn, task, job) -> Dict:
        cfg = self._conn_config(src_conn)
        creds = cfg
        gcs_uri = f"gs://uma-staging/{job.id}/{task.source_dataset}/{task.source_table}/*.parquet"
        with BigQueryConnector({"service_account_json": creds.get("service_account_json"), **cfg}) as bq:
            row_count = bq.get_row_count(task.source_dataset, task.source_table)
            schema    = bq.get_table_schema(task.source_dataset, task.source_table)
            export    = bq.export_to_gcs(task.source_dataset, task.source_table, gcs_uri)
        return {"task_id": task.id, "staging_path": gcs_uri, "staging_type": "gcs",
                "schema": schema, "row_count": row_count, "bytes": 0, "files": 1}

    # ── Stage ────────────────────────────────────────────────

    async def _stage_phase(self, db, job, src_conn, export_results) -> List[Dict]:
        staged = []
        for result in export_results:
            if result.get("staging_type") == "gcs" and job.staging_area == "s3":
                await self._log(db, "STAGE_GCS",
                    f"GCS stage: {result.get('staging_path')} (Snowflake will COPY from GCS)")
            staged.append(result)
        return staged

    # ── Load ─────────────────────────────────────────────────

    async def _load_phase(self, db, job, sf_config, staged_results, tasks) -> List[Dict]:
        def _run():
            results = []
            with SnowflakeConnector(sf_config) as sf:
                sf.ensure_schema(job.sf_database, job.sf_schema)
                for task, exp in zip(tasks, staged_results):
                    if "error" in exp:
                        results.append({"error": exp["error"], "rows_loaded": 0})
                        continue
                    try:
                        if job.destination_mode == DestinationMode.external_stage:
                            r = self._create_external_stage_target(sf, job, task, exp)
                        elif job.destination_mode == DestinationMode.external_table:
                            r = self._create_external_table_target(sf, job, task, exp)
                        else:
                            r = self._copy_into_internal(sf, job, task, exp)
                        task.copy_statement = r.get("copy_statement","")
                        task.rows_exported  = r.get("rows_loaded", 0)
                        results.append(r)
                    except Exception as e:
                        results.append({"error": str(e), "rows_loaded": 0})
            return results

        results = await run_in_thread(_run)

        for task, result in zip(tasks, results):
            ref = f"{task.source_dataset}.{task.source_table}"
            if "error" in result:
                await self._update_task(db, task, TaskStatus.failed,
                    error_message=result["error"], ended_at=datetime.utcnow())
                await self._log(db, "TASK_LOAD_FAILED", result["error"],
                    level=LogLevel.error, task_ref=ref)
            else:
                await self._update_task(db, task, TaskStatus.succeeded, ended_at=datetime.utcnow())
                await self._log(db, "COPY_COMPLETED",
                    f"COPY done: {result.get('rows_loaded',0):,} rows → "
                    f"{job.sf_database}.{job.sf_schema}.{task.target_table}",
                    task_ref=ref, detail=result.get("copy_statement"))
        return results

    def _copy_into_internal(self, sf, job, task, exp) -> Dict:
        ddl = self._generate_ddl(job, task, exp.get("schema", []))
        task.create_statement = ddl
        if not sf.table_exists(job.sf_database, job.sf_schema, task.target_table):
            sf.create_table_from_definition(ddl)
        staging_type = exp.get("staging_type","s3")
        path = exp.get("staging_path","")
        if staging_type == "s3":
            iam = exp.get("iam_role") or settings.AWS_ACCESS_KEY_ID
            return sf.copy_from_s3(job.sf_database, job.sf_schema, task.target_table,
                                   path, iam, job.file_format)
        elif staging_type == "azure":
            return sf.copy_from_azure(job.sf_database, job.sf_schema, task.target_table,
                                      path, exp.get("sas_token",""), job.file_format)
        return {"rows_loaded": 0, "copy_statement": ""}

    def _create_external_stage_target(self, sf, job, task, exp) -> Dict:
        sql = sf.create_external_stage(
            job.sf_database, job.sf_schema, f"{task.target_table}_stage",
            exp.get("staging_path",""),
            exp.get("iam_role") or settings.AWS_ACCESS_KEY_ID,
            job.file_format)
        return {"copy_statement": sql, "rows_loaded": 0}

    def _create_external_table_target(self, sf, job, task, exp) -> Dict:
        schema   = exp.get("schema", [])
        stage_nm = f"{task.target_table}_stage"
        sf.create_external_stage(job.sf_database, job.sf_schema, stage_nm,
            exp.get("staging_path",""),
            exp.get("iam_role") or settings.AWS_ACCESS_KEY_ID, job.file_format)
        cols = ",\n".join(
            f'  "{c["name"]}" {SnowflakeConnector.map_source_type_to_snowflake(c.get("type","STRING"))}'
            for c in schema
        ) if schema else "  value VARIANT"
        sql = sf.create_external_table(
            job.sf_database, job.sf_schema, task.target_table, stage_nm, cols)
        return {"copy_statement": sql, "rows_loaded": 0}

    def _generate_ddl(self, job, task, schema: list) -> str:
        if not schema:
            return (f'CREATE TABLE IF NOT EXISTS "{job.sf_database}"."{job.sf_schema}".'
                    f'"{task.target_table}" (_uma_raw VARIANT, '
                    f'_uma_loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())')
        long_text = 0
        cols = []
        for c in schema:
            sf_type = (c.get("snowflake_type") or
                       SnowflakeConnector.map_source_type_to_snowflake(
                           c.get("type","STRING"), c.get("precision",0),
                           c.get("scale",0), c.get("length",0)))
            if sf_type == "VARCHAR(16777216)": long_text += 1
            nullable = " NOT NULL" if c.get("mode") == "REQUIRED" else ""
            cols.append(f'  "{c["name"]}" {sf_type}{nullable}')
        cols.append("  _uma_loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()")
        task.long_text_columns = long_text
        return (f'CREATE TABLE IF NOT EXISTS "{job.sf_database}"."{job.sf_schema}".'
                f'"{task.target_table}" (\n' + ",\n".join(cols) + "\n)")

    # ── Helpers ───────────────────────────────────────────────

    def _build_sf_config(self, conn: Connection) -> Dict:
        cfg = self._conn_config(conn)
        return {
            "account":   cfg.get("account",""),
            "user":      cfg.get("user","") or cfg.get("username",""),
            "password":  cfg.get("password",""),
            "warehouse": cfg.get("warehouse",""),
            "database":  cfg.get("database",""),
            "schema":    cfg.get("schema",""),
            "role":      cfg.get("role",""),
        }

    def _conn_config(self, conn: Connection) -> Dict:
        credentials = get_cipher().decrypt_dict(conn.credentials) if conn.credentials else {}
        return {**(conn.config or {}), **credentials}

    async def _get_job(self, db) -> Optional[Job]:
        r = await db.execute(select(Job).where(Job.id == self.job_id))
        return r.scalar_one_or_none()

    async def _update_job(self, db, job: Job, **kw):
        for k, v in kw.items(): setattr(job, k, v)
        job.updated_at = datetime.utcnow()
        await db.commit()

    async def _update_task(self, db, task: JobTask, status: TaskStatus, **kw):
        task.status = status
        for k, v in kw.items(): setattr(task, k, v)
        await db.commit()

    async def _fail_job(self, db, error: str):
        job = await self._get_job(db)
        if job:
            await self._update_job(db, job, status=JobStatus.failed,
                                   phase="FAILED", ended_at=datetime.utcnow())
            await self._log(db, "JOB_FAILED", f"Job failed: {error}", level=LogLevel.error)

    async def _log(self, db, event: str, message: str,
                   level=LogLevel.info, task_ref=None, detail=None):
        db.add(JobLog(job_id=self.job_id, task_ref=task_ref, level=level,
                      event=event, message=message, detail=detail))
        await db.commit()
        logger.info(f"[{event}] {message}")
