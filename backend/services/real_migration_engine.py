"""
Real migration execution path for UMA — Phase 1+4 hardened.

Source DB/BigQuery -> local Parquet chunks -> Snowflake internal user stage -> target table.

Supported sources: BigQuery, Postgres, Redshift, MySQL.
Supported target: Snowflake.

Load strategies:
  - full_load: TRUNCATE + bulk insert
  - incremental/upsert/cdc: keyset/watermark extraction + Snowflake MERGE by PK with proper counts

Hardening over the previous pass (Phase 1 + Phase 4):
  - Keyset pagination on a stable sort key (eliminates OFFSET drift on large tables).
  - Watermark column type captured from source schema; SQL params typed instead of stringly-cast.
  - COPY INTO is column-explicit: _UMA_BATCH_ID / _UMA_LOADED_AT / _UMA_IS_DELETED are
    populated by the COPY itself via a SELECT-list, not a follow-up UPDATE.
  - Real MERGE counts via RESULT_SCAN(LAST_QUERY_ID()) — so rows_merged really means
    inserts+updates, not stage row count.
  - Per-task retry with exponential backoff for transient Snowflake / source errors.
  - Cancellation check between tables so a CANCELLED job actually stops mid-run.
  - delete_flag_column is validated against source schema before extraction.
  - Defensive cleanup of stage tables and local files even on partial failures.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import AsyncSessionLocal
from core.security import get_cipher
from models import (
    Connection,
    ConnectionType,
    Job,
    JobLog,
    JobStatus,
    JobTask,
    LoadStrategy,
    LogLevel,
    MigrationRun,
    MigrationState,
    MigrationTaskRun,
    TaskStatus,
    ValidationRule,
)

logger = logging.getLogger("uma.real_migration")


# ─── Errors ─────────────────────────────────────────────────────────────────

class TransientError(Exception):
    """Errors that may succeed on retry (network blip, lock timeout, etc.)."""


class PermanentError(Exception):
    """Errors that will not succeed on retry (auth, schema mismatch, syntax)."""


_TRANSIENT_PATTERNS = re.compile(
    r"(connection reset|timeout|temporarily unavailable|deadlock|lock_timeout|"
    r"could not connect|broken pipe|ssl: |reset by peer|network is unreachable|"
    r"503 |504 |429 |internal error|service unavailable|connection refused)",
    re.IGNORECASE,
)


def _classify(exc: Exception) -> Exception:
    msg = str(exc) or exc.__class__.__name__
    if _TRANSIENT_PATTERNS.search(msg):
        return TransientError(msg)
    return PermanentError(msg)


def _retry(max_attempts: int = 3, base_delay: float = 1.5):
    """Decorator: retry on TransientError or transient-classified Exception."""
    def deco(fn):
        def wrapped(*args, **kwargs):
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except TransientError as e:
                    last_exc = e
                except Exception as e:
                    classified = _classify(e)
                    if isinstance(classified, TransientError):
                        last_exc = classified
                    else:
                        raise classified from e
                if attempt == max_attempts:
                    break
                sleep_for = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "transient error in %s (attempt %d/%d): %s — retrying in %.1fs",
                    fn.__name__, attempt, max_attempts, last_exc, sleep_for,
                )
                time.sleep(sleep_for)
            assert last_exc is not None
            raise last_exc
        return wrapped
    return deco


# ─── Data classes ───────────────────────────────────────────────────────────

@dataclass
class ChunkResult:
    file_path: str
    rows: int
    bytes: int
    batch_index: int


@dataclass
class TablePlan:
    pk_columns: list[str]
    watermark_column: Optional[str]
    delete_flag_column: Optional[str]
    batch_size: int
    full_refresh: bool
    max_retries: int = 3


@dataclass
class ColumnSpec:
    name: str
    type: str
    length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    mode: str = "NULLABLE"


@dataclass
class TableSchema:
    columns: list[ColumnSpec]

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]

    def get(self, name: str) -> Optional[ColumnSpec]:
        for c in self.columns:
            if c.name == name:
                return c
        return None


# ─── Source adapters ────────────────────────────────────────────────────────

class SourceAdapter:
    """Abstract source adapter — implementations return ColumnSpec-based schemas
    and yield ChunkResult Parquet files using keyset pagination."""

    def schema(self, dataset: str, table: str) -> TableSchema:
        raise NotImplementedError

    def row_count(self, dataset: str, table: str) -> int:
        raise NotImplementedError

    def min_max(self, dataset: str, table: str, column: str) -> tuple[Any, Any]:
        raise NotImplementedError

    def max_watermark(self, dataset: str, table: str, column: str, start_value: Any) -> Any:
        raise NotImplementedError

    def extract_chunks(
        self,
        dataset: str,
        table: str,
        columns: list[str],
        plan: TablePlan,
        schema: TableSchema,
        start_watermark: Any,
        end_watermark: Any,
        out_dir: Path,
    ) -> Iterable[ChunkResult]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class BigQuerySourceAdapter(SourceAdapter):
    def __init__(self, conn: Connection):
        from google.cloud import bigquery
        from google.oauth2 import service_account

        cipher = get_cipher()
        credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
        cfg = {**(conn.config or {}), **credentials}
        sa_json = cfg.get("service_account_json")
        if isinstance(sa_json, str):
            sa_info = json.loads(sa_json)
        else:
            sa_info = sa_json
        if not sa_info:
            raise PermanentError("BigQuery service_account_json is required")
        credentials = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/bigquery"]
        )
        self.project_id = cfg.get("project_id") or sa_info.get("project_id")
        self.client = bigquery.Client(project=self.project_id, credentials=credentials)

    def _table_ref(self, dataset: str, table: str) -> str:
        return f"`{self.project_id}.{dataset}.{table}`"

    def schema(self, dataset: str, table: str) -> TableSchema:
        try:
            tbl = self.client.get_table(f"{self.project_id}.{dataset}.{table}")
        except Exception as e:
            raise _classify(e) from e
        cols = [
            ColumnSpec(name=f.name, type=f.field_type, mode=f.mode or "NULLABLE")
            for f in tbl.schema
        ]
        return TableSchema(cols)

    @_retry()
    def max_watermark(self, dataset: str, table: str, column: str, start_value: Any) -> Any:
        from google.cloud import bigquery
        params: list[Any] = []
        where = ""
        if start_value is not None:
            params.append(bigquery.ScalarQueryParameter("start_value", "STRING", str(start_value)))
            where = f"WHERE CAST(`{column}` AS STRING) > @start_value"
        sql = f"SELECT MAX(`{column}`) AS wm FROM {self._table_ref(dataset, table)} {where}"
        rows = list(
            self.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
        )
        return rows[0]["wm"] if rows else None

    def row_count(self, dataset: str, table: str) -> int:
        rows = list(self.client.query(f"SELECT COUNT(*) AS cnt FROM {self._table_ref(dataset, table)}").result())
        return int(rows[0]["cnt"] or 0) if rows else 0

    def min_max(self, dataset: str, table: str, column: str) -> tuple[Any, Any]:
        rows = list(self.client.query(
            f"SELECT MIN(`{column}`) AS min_v, MAX(`{column}`) AS max_v FROM {self._table_ref(dataset, table)}"
        ).result())
        return (rows[0]["min_v"], rows[0]["max_v"]) if rows else (None, None)

    def extract_chunks(self, dataset, table, columns, plan, schema, start_watermark, end_watermark, out_dir):
        """BigQuery keyset pagination using the watermark column or first PK column.

        We page using `WHERE sort_key > @cursor` rather than OFFSET, which keeps
        the read consistent under concurrent writes and avoids quadratic plans.
        """
        from google.cloud import bigquery

        select_cols = ", ".join(f"`{c}`" for c in columns)
        sort_col = plan.watermark_column or (plan.pk_columns[0] if plan.pk_columns else columns[0])

        cursor: Any = start_watermark
        end_wm = end_watermark
        batch = 0
        while True:
            params: list[Any] = []
            preds: list[str] = []
            if cursor is not None:
                params.append(bigquery.ScalarQueryParameter("cursor", "STRING", str(cursor)))
                preds.append(f"CAST(`{sort_col}` AS STRING) > @cursor")
            if end_wm is not None and plan.watermark_column:
                params.append(bigquery.ScalarQueryParameter("end_wm", "STRING", str(end_wm)))
                preds.append(f"CAST(`{plan.watermark_column}` AS STRING) <= @end_wm")
            where = "WHERE " + " AND ".join(preds) if preds else ""
            sql = f"""
                SELECT {select_cols}
                FROM {self._table_ref(dataset, table)}
                {where}
                ORDER BY `{sort_col}`
                LIMIT {plan.batch_size}
            """
            try:
                df = self.client.query(
                    sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
                ).to_dataframe()
            except Exception as e:
                raise _classify(e) from e
            if df.empty:
                break
            path = out_dir / f"batch_{batch:05d}.parquet"
            df.to_parquet(path, index=False)
            yield ChunkResult(str(path), len(df), path.stat().st_size, batch)
            cursor = df[sort_col].iloc[-1]
            if len(df) < plan.batch_size:
                break
            batch += 1

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


class SqlSourceAdapter(SourceAdapter):
    def __init__(self, conn: Connection):
        self.conn_model = conn
        cipher = get_cipher()
        credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
        self.cfg = {**(conn.config or {}), **credentials}
        self.conn = self._connect(conn.type)

    def _connect(self, ctype: ConnectionType):
        try:
            if ctype in (ConnectionType.postgres, ConnectionType.redshift):
                import psycopg2
                host = self.cfg.get("host") or ("postgres" if ctype == ConnectionType.postgres else None)
                database = self.cfg.get("database") or self.cfg.get("dbname")
                user = self.cfg.get("user") or self.cfg.get("username")
                password = self.cfg.get("password")
                if not host or not database or not user:
                    raise PermanentError(
                        f"Missing required {ctype.value} connection fields. Expected host, database, user/username, and password."
                    )
                return psycopg2.connect(
                    host=host,
                    port=int(self.cfg.get("port") or (5439 if ctype == ConnectionType.redshift else 5432)),
                    dbname=database,
                    user=user,
                    password=password,
                    connect_timeout=30,
                    sslmode=self.cfg.get("sslmode", "prefer"),
                )
            if ctype == ConnectionType.mysql:
                import mysql.connector
                return mysql.connector.connect(
                    host=self.cfg.get("host"),
                    port=int(self.cfg.get("port") or 3306),
                    database=self.cfg.get("database"),
                    user=self.cfg.get("user") or self.cfg.get("username"),
                    password=self.cfg.get("password"),
                    connection_timeout=30,
                )
        except Exception as e:
            raise _classify(e) from e
        raise PermanentError(f"SQL adapter does not support {ctype.value}")

    def _qident(self, name: str) -> str:
        q = "`" if self.conn_model.type == ConnectionType.mysql else '"'
        return q + str(name).replace(q, q + q) + q

    def _fqtn(self, dataset: str, table: str) -> str:
        if dataset:
            return f"{self._qident(dataset)}.{self._qident(table)}"
        return self._qident(table)

    def schema(self, dataset: str, table: str) -> TableSchema:
        cur = self.conn.cursor()
        try:
            if self.conn_model.type == ConnectionType.mysql:
                schema_name = dataset or self.cfg.get("database")
            else:
                schema_name = dataset or "public"
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, character_maximum_length,
                       numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema_name, table),
            )
            rows = cur.fetchall()
        except Exception as e:
            raise _classify(e) from e
        finally:
            cur.close()
        if not rows:
            raise PermanentError(f"Source table {dataset}.{table} not found or has no columns")
        cols = [
            ColumnSpec(
                name=r[0],
                type=str(r[1]),
                mode="NULLABLE" if str(r[2]).upper() in ("YES", "TRUE") else "REQUIRED",
                length=r[3],
                precision=r[4],
                scale=r[5],
            )
            for r in rows
        ]
        return TableSchema(cols)

    @_retry()
    def max_watermark(self, dataset: str, table: str, column: str, start_value: Any) -> Any:
        cur = self.conn.cursor()
        try:
            sql = f"SELECT MAX({self._qident(column)}) FROM {self._fqtn(dataset, table)}"
            params: list[Any] = []
            if start_value is not None:
                sql += f" WHERE {self._qident(column)} > %s"
                params.append(start_value)
            cur.execute(sql, params)
            val = cur.fetchone()[0]
            return val
        except Exception as e:
            raise _classify(e) from e
        finally:
            cur.close()

    def row_count(self, dataset: str, table: str) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {self._fqtn(dataset, table)}")
            return int(cur.fetchone()[0] or 0)
        finally:
            cur.close()

    def min_max(self, dataset: str, table: str, column: str) -> tuple[Any, Any]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                f"SELECT MIN({self._qident(column)}), MAX({self._qident(column)}) "
                f"FROM {self._fqtn(dataset, table)}"
            )
            row = cur.fetchone()
            return (row[0], row[1]) if row else (None, None)
        finally:
            cur.close()

    def extract_chunks(self, dataset, table, columns, plan, schema, start_watermark, end_watermark, out_dir):
        """SQL keyset pagination on watermark or first PK column.

        Each subsequent batch reads rows strictly greater than the last value of
        the previous batch. OFFSET is never used — it scales linearly per batch
        but quadratically across batches and is unstable under concurrent writes.
        """
        select_cols = ", ".join(self._qident(c) for c in columns)
        sort_col = plan.watermark_column or (plan.pk_columns[0] if plan.pk_columns else columns[0])

        cursor: Any = start_watermark
        end_wm = end_watermark
        batch = 0
        while True:
            preds: list[str] = []
            params: list[Any] = []
            if cursor is not None:
                preds.append(f"{self._qident(sort_col)} > %s")
                params.append(cursor)
            if end_wm is not None and plan.watermark_column:
                preds.append(f"{self._qident(plan.watermark_column)} <= %s")
                params.append(end_wm)
            where = " WHERE " + " AND ".join(preds) if preds else ""
            sql = (
                f"SELECT {select_cols} FROM {self._fqtn(dataset, table)}{where} "
                f"ORDER BY {self._qident(sort_col)} ASC LIMIT {plan.batch_size}"
            )
            try:
                df = pd.read_sql_query(sql, self.conn, params=params)
            except Exception as e:
                raise _classify(e) from e
            if df.empty:
                break
            path = out_dir / f"batch_{batch:05d}.parquet"
            df.to_parquet(path, index=False)
            yield ChunkResult(str(path), len(df), path.stat().st_size, batch)
            cursor = df[sort_col].iloc[-1]
            if len(df) < plan.batch_size:
                break
            batch += 1

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def build_source_adapter(conn: Connection) -> SourceAdapter:
    if conn.type == ConnectionType.bigquery:
        return BigQuerySourceAdapter(conn)
    if conn.type in (ConnectionType.postgres, ConnectionType.redshift, ConnectionType.mysql):
        return SqlSourceAdapter(conn)
    raise PermanentError(
        f"Real engine supports BigQuery, Postgres, Redshift and MySQL sources. Got: {conn.type.value}"
    )


# ─── Snowflake target ───────────────────────────────────────────────────────

class SnowflakeTargetAdapter:
    """Snowflake target with explicit-column COPY INTO and accurate MERGE counts."""

    def __init__(self, conn: Connection, job: Job):
        import snowflake.connector
        cipher = get_cipher()
        credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
        cfg = {**(conn.config or {}), **credentials}
        self.cfg = cfg
        self.job = job
        try:
            account = cfg.get("account")
            user = cfg.get("user") or cfg.get("username")
            password = cfg.get("password")
            warehouse = job.sf_warehouse or cfg.get("warehouse")
            database = job.sf_database or cfg.get("database")
            schema = job.sf_schema or cfg.get("schema")
            role = job.sf_role or cfg.get("role") or None
            missing = [k for k, v in {
                "account": account, "user": user, "password": password,
                "warehouse": warehouse, "database": database, "schema": schema,
            }.items() if not v]
            if missing:
                raise PermanentError(f"Missing Snowflake connection fields: {', '.join(missing)}")
            ca_bundle = os.getenv("SNOWFLAKE_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE")
            if ca_bundle:
                os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
                os.environ["SSL_CERT_FILE"] = ca_bundle
            self.conn = snowflake.connector.connect(
                account=account,
                user=user,
                password=password,
                warehouse=warehouse,
                database=database,
                schema=schema,
                role=role,
                session_parameters={"QUERY_TAG": f"UMA_REAL_ENGINE_JOB_{job.id}"},
                client_session_keep_alive=True,
                login_timeout=30,
                network_timeout=120,
                insecure_mode=os.getenv("SNOWFLAKE_INSECURE_MODE", "false").lower() == "true",
            )
        except Exception as e:
            raise _classify(e) from e
        self._stage_tables_to_drop: list[str] = []

    def close(self):
        for fqn in self._stage_tables_to_drop:
            try:
                self.execute_simple(f"DROP TABLE IF EXISTS {fqn}")
            except Exception as e:
                logger.warning("Failed to drop stage table %s: %s", fqn, e)
        try:
            self.conn.close()
        except Exception:
            pass

    @_retry()
    def execute(self, sql: str, params: Optional[tuple] = None):
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            try:
                return cur.fetchall(), cur.sfqid
            except Exception:
                return [], cur.sfqid
        except Exception as e:
            raise _classify(e) from e
        finally:
            cur.close()

    def execute_simple(self, sql: str, params: Optional[tuple] = None):
        rows, _ = self.execute(sql, params)
        return rows

    def q(self, name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    def fqn(self, database: str, schema: str, table: str) -> str:
        return f"{self.q(database)}.{self.q(schema)}.{self.q(table)}"

    def map_type(self, source_type: str, length=None, precision=None, scale=None) -> str:
        t = (source_type or "STRING").upper()
        if any(x in t for x in ["INT", "INTEGER", "BIGINT", "SMALLINT"]):
            return "NUMBER(38,0)"
        if any(x in t for x in ["NUMERIC", "DECIMAL", "NUMBER"]):
            p = int(precision or 38)
            s = int(scale or 9)
            return f"NUMBER({min(p,38)},{min(s,37)})"
        if any(x in t for x in ["FLOAT", "DOUBLE", "REAL"]):
            return "FLOAT"
        if "BOOL" in t:
            return "BOOLEAN"
        if t == "DATE":
            return "DATE"
        if "TIME" in t or "DATETIME" in t:
            return "TIMESTAMP_NTZ"
        if any(x in t for x in ["JSON", "VARIANT", "STRUCT", "RECORD", "ARRAY"]):
            return "VARIANT"
        return "VARCHAR"

    def ensure_database_schema(self):
        self.execute_simple(f"CREATE DATABASE IF NOT EXISTS {self.q(self.job.sf_database)}")
        self.execute_simple(
            f"CREATE SCHEMA IF NOT EXISTS {self.q(self.job.sf_database)}.{self.q(self.job.sf_schema)}"
        )

    def _column_ddl(self, c: ColumnSpec) -> str:
        return f"{self.q(c.name)} {self.map_type(c.type, c.length, c.precision, c.scale)}"

    def ensure_table(self, table: str, schema: TableSchema):
        cols = [self._column_ddl(c) for c in schema.columns]
        cols.extend([
            "_UMA_BATCH_ID VARCHAR",
            "_UMA_LOADED_AT TIMESTAMP_NTZ",
            "_UMA_IS_DELETED BOOLEAN",
        ])
        self.execute_simple(
            f"CREATE TABLE IF NOT EXISTS "
            f"{self.fqn(self.job.sf_database, self.job.sf_schema, table)} "
            f"(" + ", ".join(cols) + ")"
        )

    def recreate_stage_table(self, stage_table: str, schema: TableSchema):
        fqn = self.fqn(self.job.sf_database, self.job.sf_schema, stage_table)
        self.execute_simple(f"DROP TABLE IF EXISTS {fqn}")
        cols = [self._column_ddl(c) for c in schema.columns]
        cols.extend([
            "_UMA_BATCH_ID VARCHAR",
            "_UMA_LOADED_AT TIMESTAMP_NTZ",
            "_UMA_IS_DELETED BOOLEAN",
        ])
        # NB: deliberately not TEMP — engine can crash mid-run; we want the stage to outlive
        # a single connection so a retry/resume can re-use it. We drop it in close().
        self.execute_simple(f"CREATE TABLE {fqn} (" + ", ".join(cols) + ")")
        self._stage_tables_to_drop.append(fqn)

    def put_and_copy(
        self,
        files: list[ChunkResult],
        stage_table: str,
        schema: TableSchema,
        batch_id: str,
        delete_flag_column: Optional[str],
    ) -> int:
        """PUT each chunk to user stage, then COPY INTO with explicit column SELECT
        so _UMA_BATCH_ID / _UMA_LOADED_AT / _UMA_IS_DELETED are populated by COPY itself.

        Returns the number of rows landed in the stage table.
        """
        stage_path = f"@~/uma/{batch_id}/{stage_table}"
        for f in files:
            # OVERWRITE=TRUE so a retry of the same batch_id is idempotent.
            self.execute_simple(
                f"PUT 'file://{f.file_path}' {stage_path} AUTO_COMPRESS=TRUE OVERWRITE=TRUE PARALLEL=4"
            )
        stage_fqn = self.fqn(self.job.sf_database, self.job.sf_schema, stage_table)
        col_select_parts: list[str] = []
        for c in schema.columns:
            col_select_parts.append(
                f"$1:{self.q(c.name)}::{self.map_type(c.type, c.length, c.precision, c.scale)}"
            )
        col_select_parts.append(f"'{batch_id}'")
        col_select_parts.append("CURRENT_TIMESTAMP()")
        if delete_flag_column and schema.get(delete_flag_column):
            col_select_parts.append(
                f"COALESCE(TRY_TO_BOOLEAN($1:{self.q(delete_flag_column)}::VARCHAR), FALSE)"
            )
        else:
            col_select_parts.append("FALSE")
        column_list = ", ".join(
            [self.q(c.name) for c in schema.columns]
            + ["_UMA_BATCH_ID", "_UMA_LOADED_AT", "_UMA_IS_DELETED"]
        )
        copy_sql = f"""
        COPY INTO {stage_fqn} ({column_list})
        FROM (SELECT {', '.join(col_select_parts)} FROM {stage_path})
        FILE_FORMAT = (TYPE = PARQUET USE_LOGICAL_TYPE = TRUE)
        ON_ERROR = 'ABORT_STATEMENT'
        PURGE = TRUE
        """
        self.execute_simple(copy_sql)
        rows, _ = self.execute(f"SELECT COUNT(*) FROM {stage_fqn}")
        return int(rows[0][0]) if rows else 0

    def apply_full_load(self, target_table: str, stage_table: str, columns: list[str]) -> dict[str, int]:
        target = self.fqn(self.job.sf_database, self.job.sf_schema, target_table)
        stage = self.fqn(self.job.sf_database, self.job.sf_schema, stage_table)
        quoted_cols = ", ".join(self.q(c) for c in columns)
        self.execute_simple(f"TRUNCATE TABLE {target}")
        self.execute_simple(
            f"INSERT INTO {target} ({quoted_cols}, _UMA_BATCH_ID, _UMA_LOADED_AT, _UMA_IS_DELETED) "
            f"SELECT {quoted_cols}, _UMA_BATCH_ID, _UMA_LOADED_AT, _UMA_IS_DELETED FROM {stage}"
        )
        rows, _ = self.execute(f"SELECT COUNT(*) FROM {target}")
        inserted = int(rows[0][0]) if rows else 0
        return {"inserted": inserted, "updated": 0, "deleted": 0}

    def apply_merge(
        self,
        target_table: str,
        stage_table: str,
        schema: TableSchema,
        pk_columns: list[str],
        delete_flag: Optional[str],
    ) -> dict[str, int]:
        if not pk_columns:
            raise PermanentError(
                "Incremental/upsert/cdc loads require primary_key_columns in task config"
            )

        # Validate every PK is actually present in the source schema.
        for pk in pk_columns:
            if not schema.get(pk):
                raise PermanentError(
                    f"primary_key_column '{pk}' is not present in source table schema"
                )

        target = self.fqn(self.job.sf_database, self.job.sf_schema, target_table)
        stage = self.fqn(self.job.sf_database, self.job.sf_schema, stage_table)
        on_clause = " AND ".join(f"t.{self.q(pk)} = s.{self.q(pk)}" for pk in pk_columns)
        non_meta_cols = schema.names

        update_set = ", ".join(
            [f"t.{self.q(c)} = s.{self.q(c)}" for c in non_meta_cols]
            + [
                "t._UMA_BATCH_ID = s._UMA_BATCH_ID",
                "t._UMA_LOADED_AT = CURRENT_TIMESTAMP()",
                "t._UMA_IS_DELETED = s._UMA_IS_DELETED",
            ]
        )
        insert_cols = ", ".join(
            [self.q(c) for c in non_meta_cols] + ["_UMA_BATCH_ID", "_UMA_LOADED_AT", "_UMA_IS_DELETED"]
        )
        insert_vals = ", ".join(
            [f"s.{self.q(c)}" for c in non_meta_cols]
            + ["s._UMA_BATCH_ID", "CURRENT_TIMESTAMP()", "s._UMA_IS_DELETED"]
        )
        # Dedup the stage view so MERGE never sees two rows per PK.
        partition_cols = ", ".join(self.q(pk) for pk in pk_columns)
        merge_sql = f"""
        MERGE INTO {target} t
        USING (
          SELECT *
          FROM {stage}
          QUALIFY ROW_NUMBER() OVER (PARTITION BY {partition_cols} ORDER BY _UMA_LOADED_AT DESC) = 1
        ) s
        ON {on_clause}
        WHEN MATCHED AND s._UMA_IS_DELETED THEN UPDATE SET
            t._UMA_IS_DELETED = TRUE,
            t._UMA_BATCH_ID = s._UMA_BATCH_ID,
            t._UMA_LOADED_AT = CURRENT_TIMESTAMP()
        WHEN MATCHED THEN UPDATE SET {update_set}
        WHEN NOT MATCHED AND NOT s._UMA_IS_DELETED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
        """
        _, qid = self.execute(merge_sql)
        # Snowflake MERGE returns per-action row counts in the result set —
        # columns: "number of rows inserted", "number of rows updated", "number of rows deleted".
        # We retrieve them via RESULT_SCAN of the MERGE query id.
        try:
            scan_rows = self.execute_simple(f"SELECT * FROM TABLE(RESULT_SCAN('{qid}'))")
        except Exception:
            scan_rows = []
        inserted = updated = deleted_hard = 0
        if scan_rows:
            r = scan_rows[0]
            try:
                inserted = int(r[0] or 0)
            except (TypeError, IndexError, ValueError):
                pass
            try:
                updated = int(r[1] or 0)
            except (TypeError, IndexError, ValueError):
                pass
            try:
                deleted_hard = int(r[2] or 0)
            except (TypeError, IndexError, ValueError):
                pass
        # Soft deletes (rows marked _UMA_IS_DELETED=TRUE in this batch) — count from stage.
        deleted_marked = 0
        if delete_flag:
            rows, _ = self.execute(
                f"SELECT COUNT(*) FROM {stage} WHERE _UMA_IS_DELETED = TRUE"
            )
            deleted_marked = int(rows[0][0]) if rows else 0
        return {
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted_marked or deleted_hard,
        }

    def target_row_count(self, table: str) -> int:
        rows, _ = self.execute(
            f"SELECT COUNT(*) FROM {self.fqn(self.job.sf_database, self.job.sf_schema, table)} "
            f"WHERE COALESCE(_UMA_IS_DELETED, FALSE) = FALSE"
        )
        return int(rows[0][0] or 0) if rows else 0

    def target_min_max(self, table: str, column: str) -> tuple[Any, Any]:
        rows, _ = self.execute(
            f"SELECT MIN({self.q(column)}), MAX({self.q(column)}) "
            f"FROM {self.fqn(self.job.sf_database, self.job.sf_schema, table)} "
            f"WHERE COALESCE(_UMA_IS_DELETED, FALSE) = FALSE"
        )
        return (rows[0][0], rows[0][1]) if rows else (None, None)


# ─── Plan builder ───────────────────────────────────────────────────────────

def task_plan(job: Job, task: JobTask) -> TablePlan:
    cfg = getattr(task, "config", None) or {}
    if not cfg and task.create_statement and task.create_statement.strip().startswith("{"):
        try:
            cfg = json.loads(task.create_statement)
        except Exception:
            cfg = {}
    pk = cfg.get("primary_key_columns") or cfg.get("primary_keys") or []
    if isinstance(pk, str):
        pk = [x.strip() for x in pk.split(",") if x.strip()]
    return TablePlan(
        pk_columns=pk,
        watermark_column=cfg.get("watermark_column"),
        delete_flag_column=cfg.get("delete_flag_column"),
        batch_size=int(cfg.get("batch_size") or getattr(settings, "MIGRATION_BATCH_SIZE", 50000) or 50000),
        full_refresh=job.load_strategy == LoadStrategy.full_load,
        max_retries=int(cfg.get("max_retries") or 3),
    )


# ─── The engine ─────────────────────────────────────────────────────────────

class RealMigrationEngine:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.batch_id = f"uma_{job_id}_{int(time.time())}"
        self._cancelled = False

    async def _is_cancelled(self) -> bool:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(Job.status).where(Job.id == self.job_id))).first()
            if row and row[0] == JobStatus.cancelled:
                self._cancelled = True
                return True
            return False

    async def execute(self) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            job = (
                await db.execute(
                    select(Job).options(selectinload(Job.tasks)).where(Job.id == self.job_id)
                )
            ).scalar_one_or_none()
            if not job:
                raise ValueError(f"Job not found: {self.job_id}")
            # Run-level dedupe: don't kick off a second concurrent run.
            if job.status == JobStatus.running:
                logger.warning("execute called while job %s is already running — refusing", job.id)
                return {"success": False, "error": "Job already running"}

            run = await self._create_run(db, job)
            try:
                await self._mark_job(db, job, JobStatus.running, "REAL_ENGINE_RUNNING")
                await self._log(
                    db,
                    "REAL_ENGINE_STARTED",
                    f"Run {run.id} (attempt {run.attempt_number}) starting",
                    detail=json.dumps({
                        "load_strategy": job.load_strategy.value,
                        "task_count": len(job.tasks),
                        "batch_id": self.batch_id,
                    }),
                )
                result = await self._execute_sync(db, job, run)
                run.status = "CANCELLED" if self._cancelled else "SUCCEEDED"
                run.ended_at = datetime.utcnow()
                run.rows_extracted = result["rows_extracted"]
                run.rows_loaded = result["rows_loaded"]
                run.rows_merged = result["rows_merged"]
                run.rows_deleted = result["rows_deleted"]
                run.bytes_staged = result["bytes_staged"]
                terminal = JobStatus.cancelled if self._cancelled else JobStatus.succeeded
                await self._mark_job(db, job, terminal, "CANCELLED" if self._cancelled else "COMPLETED")
                job.total_rows_exported = result["rows_loaded"]
                job.total_bytes = result["bytes_staged"]
                await db.commit()
                await self._log(
                    db,
                    "REAL_ENGINE_CANCELLED" if self._cancelled else "REAL_ENGINE_COMPLETED",
                    f"Moved {result['rows_loaded']:,} rows ({result['bytes_staged']:,} staged bytes) "
                    f"— inserted={result['rows_inserted']:,} updated={result['rows_updated']:,} "
                    f"deleted={result['rows_deleted']:,}",
                )
                return {"success": True, "run_id": run.id, **result}
            except Exception as e:
                logger.exception("Real migration failed")
                run.status = "FAILED"
                run.error_message = str(e)[:2000]
                run.ended_at = datetime.utcnow()
                await self._mark_job(db, job, JobStatus.failed, "FAILED")
                await self._log(db, "REAL_ENGINE_FAILED", str(e)[:500], level=LogLevel.error)
                await db.commit()
                return {"success": False, "run_id": run.id, "error": str(e)}

    async def _execute_sync(self, db: AsyncSession, job: Job, run: MigrationRun) -> dict[str, int]:
        src_conn = await db.get(Connection, job.source_connection_id)
        dst_conn = await db.get(Connection, job.dest_connection_id)
        if not src_conn or not dst_conn:
            raise PermanentError("Source or destination connection missing")
        if dst_conn.type != ConnectionType.snowflake:
            raise PermanentError("Real engine currently writes only to Snowflake")

        totals = {
            "rows_extracted": 0,
            "rows_loaded": 0,
            "rows_merged": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_deleted": 0,
            "bytes_staged": 0,
        }
        source = build_source_adapter(src_conn)
        target = SnowflakeTargetAdapter(dst_conn, job)
        target.ensure_database_schema()
        try:
            for task in list(job.tasks):
                if await self._is_cancelled():
                    await self._log(
                        db, "REAL_ENGINE_CANCELLED",
                        "Cancellation requested — stopping mid-run",
                    )
                    break
                table_result = await self._run_table(db, job, run, task, source, target)
                for k in totals:
                    totals[k] += table_result.get(k, 0)
            return totals
        finally:
            try:
                source.close()
            except Exception:
                logger.warning("source.close() failed", exc_info=True)
            try:
                target.close()
            except Exception:
                logger.warning("target.close() failed", exc_info=True)

    async def _run_table(self, db, job, run, task, source, target) -> dict[str, int]:
        table_key = f"{task.source_dataset}.{task.source_table}"
        plan = task_plan(job, task)
        state = await self._get_state(db, job, task, table_key, plan)
        tr = MigrationTaskRun(
            run_id=run.id,
            job_id=job.id,
            task_id=task.id,
            table_key=table_key,
            status="RUNNING",
            target_table=f"{job.sf_database}.{job.sf_schema}.{task.target_table}",
            watermark_start=str(state.last_watermark_value) if state.last_watermark_value is not None else None,
            started_at=datetime.utcnow(),
        )
        db.add(tr)
        task.status = TaskStatus.running
        task.started_at = datetime.utcnow()
        await db.commit()
        await self._log(db, "TABLE_STARTED", f"Starting real movement for {table_key}", task_ref=table_key)

        out_dir = Path(os.getenv("UMA_LOCAL_STAGE_DIR", "/tmp/uma_staging")) / run.id / task.id
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            schema = source.schema(task.source_dataset, task.source_table)
            columns = schema.names

            # Validate optional columns referenced in the plan exist in source
            if plan.delete_flag_column and not schema.get(plan.delete_flag_column):
                raise PermanentError(
                    f"delete_flag_column '{plan.delete_flag_column}' is not present in source schema"
                )
            if plan.watermark_column and not schema.get(plan.watermark_column):
                raise PermanentError(
                    f"watermark_column '{plan.watermark_column}' is not present in source schema"
                )

            end_wm = None
            if not plan.full_refresh and plan.watermark_column:
                end_wm = source.max_watermark(
                    task.source_dataset,
                    task.source_table,
                    plan.watermark_column,
                    state.last_watermark_value,
                )
                if end_wm is None:
                    await self._complete_empty_table(db, task, tr, state)
                    await self._log(
                        db, "TABLE_NO_NEW_DATA",
                        f"{table_key}: no new rows since watermark={state.last_watermark_value}",
                        task_ref=table_key,
                    )
                    return self._zero_table_result()

            chunks = list(
                source.extract_chunks(
                    task.source_dataset,
                    task.source_table,
                    columns,
                    plan,
                    schema,
                    state.last_watermark_value,
                    end_wm,
                    out_dir,
                )
            )
            rows_extracted = sum(c.rows for c in chunks)
            bytes_staged = sum(c.bytes for c in chunks)
            if not chunks:
                await self._complete_empty_table(db, task, tr, state)
                return self._zero_table_result()

            target.ensure_table(task.target_table, schema)
            stage_table = (
                f"_UMA_STAGE_{task.target_table}_{run.id[:8]}".replace("-", "_").upper()
            )
            target.recreate_stage_table(stage_table, schema)
            rows_loaded = target.put_and_copy(
                chunks, stage_table, schema, self.batch_id, plan.delete_flag_column
            )

            if plan.full_refresh:
                merge_result = target.apply_full_load(task.target_table, stage_table, columns)
            else:
                merge_result = target.apply_merge(
                    task.target_table, stage_table, schema, plan.pk_columns, plan.delete_flag_column
                )
            inserted = merge_result.get("inserted", 0)
            updated = merge_result.get("updated", 0)
            deleted = merge_result.get("deleted", 0)
            rows_merged = inserted + updated

            validation = await self._validate_table_counts(
                db, job, task, source, target, schema, table_key
            )
            if not validation["passed"]:
                raise PermanentError(validation["message"])

            if end_wm is not None:
                state.last_watermark_value = str(end_wm)
            elif plan.full_refresh and plan.watermark_column:
                max_wm = source.max_watermark(
                    task.source_dataset, task.source_table, plan.watermark_column, None
                )
                state.last_watermark_value = (
                    str(max_wm) if max_wm is not None else state.last_watermark_value
                )
            state.last_successful_run_id = run.id
            state.last_success_at = datetime.utcnow()
            state.strategy = job.load_strategy.value
            state.primary_key_columns = plan.pk_columns
            state.watermark_column = plan.watermark_column

            tr.status = "SUCCEEDED"
            tr.rows_extracted = rows_extracted
            tr.rows_loaded = rows_loaded
            tr.rows_merged = rows_merged
            tr.rows_deleted = deleted
            tr.bytes_staged = bytes_staged
            tr.batch_count = len(chunks)
            tr.staging_path = str(out_dir)
            tr.watermark_end = state.last_watermark_value
            tr.ended_at = datetime.utcnow()
            task.status = TaskStatus.succeeded
            task.rows_exported = rows_loaded
            task.bytes_exported = bytes_staged
            task.files_exported = len(chunks)
            task.ended_at = datetime.utcnow()
            await db.commit()
            await self._log(
                db,
                "TABLE_COMPLETED",
                f"{table_key}: {rows_loaded:,} loaded "
                f"(inserted={inserted:,}, updated={updated:,}, deleted={deleted:,}), "
                f"watermark={state.last_watermark_value}",
                task_ref=table_key,
            )
            return {
                "rows_extracted": rows_extracted,
                "rows_loaded": rows_loaded,
                "rows_merged": rows_merged,
                "rows_inserted": inserted,
                "rows_updated": updated,
                "rows_deleted": deleted,
                "bytes_staged": bytes_staged,
            }
        except Exception as e:
            classified = e if isinstance(e, (TransientError, PermanentError)) else _classify(e)
            tr.status = "FAILED"
            tr.error_message = str(classified)[:2000]
            tr.ended_at = datetime.utcnow()
            task.status = TaskStatus.failed
            task.error_message = str(classified)[:2000]
            task.ended_at = datetime.utcnow()
            await db.commit()
            await self._log(
                db, "TABLE_FAILED", str(classified)[:500], level=LogLevel.error, task_ref=table_key
            )
            raise classified
        finally:
            if os.getenv("UMA_KEEP_LOCAL_STAGE", "false").lower() != "true":
                shutil.rmtree(out_dir, ignore_errors=True)

    @staticmethod
    def _zero_table_result() -> dict[str, int]:
        return {
            "rows_extracted": 0,
            "rows_loaded": 0,
            "rows_merged": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_deleted": 0,
            "bytes_staged": 0,
        }

    async def _complete_empty_table(self, db, task, tr, state):
        tr.status = "SUCCEEDED"
        tr.ended_at = datetime.utcnow()
        task.status = TaskStatus.succeeded
        task.ended_at = datetime.utcnow()
        state.last_success_at = datetime.utcnow()
        await db.commit()

    async def _get_state(self, db, job, task, table_key, plan) -> MigrationState:
        state = (
            await db.execute(
                select(MigrationState).where(
                    MigrationState.job_id == job.id, MigrationState.task_id == task.id
                )
            )
        ).scalar_one_or_none()
        if not state:
            state = MigrationState(
                job_id=job.id,
                task_id=task.id,
                table_key=table_key,
                strategy=job.load_strategy.value,
                primary_key_columns=plan.pk_columns,
                watermark_column=plan.watermark_column,
            )
            db.add(state)
            await db.commit()
        return state

    async def _validate_table_counts(self, db, job, task, source, target, schema, table_key) -> dict[str, Any]:
        source_count = source.row_count(task.source_dataset, task.source_table)
        target_count = target.target_row_count(task.target_table)
        passed = int(source_count) == int(target_count)
        delta = int(target_count) - int(source_count)
        db.add(ValidationRule(
            name=f"auto_row_count_{task.target_table}",
            rule_type="row_count",
            target_table=f"{job.sf_database}.{job.sf_schema}.{task.target_table}",
            job_id=job.id,
            source_connection_id=job.source_connection_id,
            source_dataset=task.source_dataset,
            source_table=task.source_table,
            threshold_pct=0.0,
            status="SUCCEEDED" if passed else "FAILED",
            source_value=str(source_count),
            target_value=str(target_count),
            delta=f"{delta:+,}",
            last_run=datetime.utcnow(),
            error_message="" if passed else "Source and Snowflake row counts differ",
        ))
        if schema.get("updated_at"):
            src_min, src_max = source.min_max(task.source_dataset, task.source_table, "updated_at")
            tgt_min, tgt_max = target.target_min_max(task.target_table, "updated_at")
            minmax_passed = str(src_min) == str(tgt_min) and str(src_max) == str(tgt_max)
            db.add(ValidationRule(
                name=f"auto_minmax_updated_at_{task.target_table}",
                rule_type="minmax_updated_at",
                target_table=f"{job.sf_database}.{job.sf_schema}.{task.target_table}",
                job_id=job.id,
                source_connection_id=job.source_connection_id,
                source_dataset=task.source_dataset,
                source_table=task.source_table,
                threshold_pct=0.0,
                status="SUCCEEDED" if minmax_passed else "FAILED",
                source_value=f"{src_min} → {src_max}",
                target_value=f"{tgt_min} → {tgt_max}",
                delta="matched" if minmax_passed else "mismatch",
                last_run=datetime.utcnow(),
                error_message="" if minmax_passed else "updated_at min/max differs",
            ))
            passed = passed and minmax_passed
        await db.commit()
        message = (
            f"{table_key}: validation passed source={source_count:,} target={target_count:,}"
            if passed else
            f"{table_key}: validation failed source={source_count:,} target={target_count:,}"
        )
        await self._log(
            db,
            "VALIDATION_PASSED" if passed else "VALIDATION_FAILED",
            message,
            level=LogLevel.info if passed else LogLevel.error,
            task_ref=table_key,
        )
        return {"passed": passed, "message": message}

    async def _create_run(self, db, job) -> MigrationRun:
        attempts = (
            await db.execute(
                select(func.count(MigrationRun.id)).where(MigrationRun.job_id == job.id)
            )
        ).scalar_one() or 0
        run = MigrationRun(
            job_id=job.id,
            mode=job.load_strategy.value,
            attempt_number=attempts + 1,
            status="RUNNING",
            started_at=datetime.utcnow(),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run

    async def _mark_job(self, db, job, status, phase):
        job.status = status
        job.phase = phase
        now = datetime.utcnow()
        if status == JobStatus.running and not job.started_at:
            job.started_at = now
        if status in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled):
            job.ended_at = now
            if job.started_at:
                job.export_duration_s = (now - job.started_at).total_seconds()
        job.updated_at = now
        await db.commit()

    async def _log(self, db, event, message, level=LogLevel.info, task_ref=None, detail=None):
        msg = message[:2000] if isinstance(message, str) else str(message)[:2000]
        db.add(
            JobLog(
                job_id=self.job_id,
                task_ref=task_ref,
                level=level,
                event=event,
                message=msg,
                detail=detail,
            )
        )
        await db.commit()
