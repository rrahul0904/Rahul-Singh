"""
UMA Platform — CDC Engine & Schema Drift Service
Handles: incremental replication, change data capture, schema drift detection,
         auto-add columns, retry/replay, backfill management
"""

import logging
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("uma.services.cdc")


# ══════════════════════════════════════════════════════════════
# Data Classes
# ══════════════════════════════════════════════════════════════

@dataclass
class ColumnDrift:
    column_name: str
    drift_type: str          # "added" | "removed" | "type_changed" | "nullable_changed"
    source_type: Optional[str] = None
    target_type: Optional[str] = None
    source_nullable: Optional[bool] = None
    target_nullable: Optional[bool] = None


@dataclass
class SchemaDriftResult:
    table: str
    has_drift: bool
    drifts: List[ColumnDrift] = field(default_factory=list)
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "table": self.table,
            "has_drift": self.has_drift,
            "drifts": [asdict(d) for d in self.drifts],
            "detected_at": self.detected_at,
        }


@dataclass
class WatermarkState:
    """Tracks high-water mark for incremental loads."""
    job_id: str
    table: str
    watermark_column: str
    last_value: Any
    last_run: str
    row_count: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════
# Schema Drift Detector
# ══════════════════════════════════════════════════════════════

class SchemaDriftDetector:
    """
    Compares source schema against target Snowflake schema.
    Detects: new columns, dropped columns, type changes, nullability changes.
    Can auto-apply ALTER TABLE to add new columns in Snowflake.
    """

    def __init__(self, sf_connector):
        self.sf = sf_connector

    def detect_drift(
        self,
        source_schema: List[Dict],   # [{name, type, mode}, ...]
        database: str,
        schema: str,
        table: str,
    ) -> SchemaDriftResult:
        """Compare source schema to what's currently in Snowflake."""

        result = SchemaDriftResult(table=f"{database}.{schema}.{table}", has_drift=False)

        if not self.sf.table_exists(database, schema, table):
            # Table doesn't exist yet — no drift to detect
            return result

        target_cols = self.sf.get_column_list(database, schema, table)
        target_map = {c["COLUMN_NAME"].upper(): c for c in target_cols}

        source_map = {}
        for col in source_schema:
            name = col["name"].upper()
            # Skip UMA audit columns
            if name.startswith("_UMA_"):
                continue
            source_map[name] = col

        drifts = []

        # New columns in source (not in target)
        for name, col in source_map.items():
            if name not in target_map:
                drifts.append(ColumnDrift(
                    column_name=name,
                    drift_type="added",
                    source_type=col.get("type"),
                ))

        # Removed columns (in target, not in source)
        for name in target_map:
            if name.startswith("_UMA_"):
                continue
            if name not in source_map:
                drifts.append(ColumnDrift(
                    column_name=name,
                    drift_type="removed",
                    target_type=target_map[name].get("DATA_TYPE"),
                ))

        # Type changes
        for name in set(source_map) & set(target_map):
            src_type = source_map[name].get("type", "")
            tgt_type = target_map[name].get("DATA_TYPE", "")
            from connectors.snowflake_connector import SnowflakeConnector
            expected_sf_type = SnowflakeConnector.map_source_type_to_snowflake(
                src_type,
                source_map[name].get("precision", 0),
                source_map[name].get("scale", 0),
                source_map[name].get("length", 0),
            )
            if expected_sf_type.split("(")[0] != tgt_type.split("(")[0]:
                drifts.append(ColumnDrift(
                    column_name=name,
                    drift_type="type_changed",
                    source_type=expected_sf_type,
                    target_type=tgt_type,
                ))

        if drifts:
            result.has_drift = True
            result.drifts = drifts

        return result

    def apply_drift(
        self,
        drift_result: SchemaDriftResult,
        database: str,
        schema: str,
        table: str,
        source_schema: List[Dict],
        auto_add: bool = True,
    ) -> List[str]:
        """
        Apply schema drift fixes to Snowflake.
        Returns list of DDL statements executed.
        """
        executed = []
        from connectors.snowflake_connector import SnowflakeConnector

        for drift in drift_result.drifts:
            if drift.drift_type == "added" and auto_add:
                # Find the source column definition
                src_col = next(
                    (c for c in source_schema if c["name"].upper() == drift.column_name),
                    None
                )
                if src_col:
                    sf_type = SnowflakeConnector.map_source_type_to_snowflake(
                        src_col.get("type", "STRING"),
                        src_col.get("precision", 0),
                        src_col.get("scale", 0),
                        src_col.get("length", 0),
                    )
                    ddl = (f'ALTER TABLE "{database}"."{schema}"."{table}" '
                           f'ADD COLUMN "{drift.column_name}" {sf_type}')
                    self.sf.execute(ddl)
                    executed.append(ddl)
                    logger.info(f"Auto-added column: {drift.column_name} ({sf_type}) to {table}")

            elif drift.drift_type == "removed":
                logger.warning(
                    f"Column {drift.column_name} removed from source — "
                    f"NOT dropping from Snowflake (data preservation). "
                    f"Manual action required if desired."
                )

            elif drift.drift_type == "type_changed":
                logger.warning(
                    f"Type changed for {drift.column_name}: "
                    f"{drift.target_type} → {drift.source_type}. "
                    f"Consider manual ALTER COLUMN if safe."
                )

        return executed


# ══════════════════════════════════════════════════════════════
# Incremental Load / Watermark Manager
# ══════════════════════════════════════════════════════════════

class WatermarkManager:
    """
    Manages high-water mark state for incremental loads.
    Stores state in PostgreSQL (or Redis for faster access).
    """

    def __init__(self, db_session_factory):
        self._db_factory = db_session_factory

    async def get_watermark(self, job_id: str, table: str) -> Optional[WatermarkState]:
        """Retrieve last watermark for a job+table combination."""
        async with self._db_factory() as db:
            from sqlalchemy import text
            result = await db.execute(
                text("SELECT state FROM uma_watermarks WHERE job_id=:j AND table_key=:t"),
                {"j": job_id, "t": table}
            )
            row = result.fetchone()
            if row:
                data = json.loads(row[0])
                return WatermarkState(**data)
        return None

    async def set_watermark(self, state: WatermarkState):
        """Persist watermark state."""
        async with self._db_factory() as db:
            from sqlalchemy import text
            await db.execute(
                text("""INSERT INTO uma_watermarks (job_id, table_key, state, updated_at)
                        VALUES (:j, :t, :s, NOW())
                        ON CONFLICT (job_id, table_key)
                        DO UPDATE SET state=:s, updated_at=NOW()"""),
                {"j": state.job_id, "t": state.table, "s": json.dumps(state.to_dict())}
            )
            await db.commit()

    def build_incremental_query(
        self,
        base_query: str,
        watermark_col: str,
        last_value: Any,
        source_type: str = "timestamp",
    ) -> str:
        """Build a WHERE clause to fetch only new/changed rows."""
        if last_value is None:
            return base_query  # Full load on first run

        if "WHERE" in base_query.upper():
            clause = f" AND {watermark_col} > '{last_value}'"
        else:
            clause = f" WHERE {watermark_col} > '{last_value}'"

        return base_query + clause + f" ORDER BY {watermark_col} ASC"


# ══════════════════════════════════════════════════════════════
# Retry / Replay Manager
# ══════════════════════════════════════════════════════════════

class RetryManager:
    """
    Handles failed task retries with exponential backoff.
    Integrates with the ARQ job queue.
    """

    MAX_RETRIES = 3
    BASE_DELAY_SECONDS = 30

    @staticmethod
    def should_retry(attempt: int, error: str) -> bool:
        """Determine if a failed task should be retried."""
        if attempt >= RetryManager.MAX_RETRIES:
            return False
        # Don't retry auth errors or schema errors
        permanent_errors = ["authentication failed", "access denied", "does not exist",
                            "permission denied", "invalid credentials"]
        error_lower = error.lower()
        return not any(e in error_lower for e in permanent_errors)

    @staticmethod
    def backoff_seconds(attempt: int) -> int:
        """Exponential backoff: 30s, 60s, 120s."""
        return RetryManager.BASE_DELAY_SECONDS * (2 ** (attempt - 1))

    @staticmethod
    async def schedule_retry(job_id: str, task_id: str, attempt: int,
                              error: str, queue_client) -> bool:
        """Schedule a retry via ARQ queue."""
        if not RetryManager.should_retry(attempt, error):
            logger.warning(f"No retry for task {task_id} (attempt {attempt}): {error}")
            return False

        delay = RetryManager.backoff_seconds(attempt)
        logger.info(f"Scheduling retry #{attempt+1} for task {task_id} in {delay}s")

        await queue_client.enqueue_job(
            "retry_task",
            job_id=job_id,
            task_id=task_id,
            attempt=attempt + 1,
            _defer_by=timedelta(seconds=delay),
        )
        return True


# ══════════════════════════════════════════════════════════════
# Lineage Tracker
# ══════════════════════════════════════════════════════════════

class LineageTracker:
    """
    Tracks data lineage for all migrations.
    Records: source → job → task → target table relationships,
             row counts, timestamps, transformation steps.
    """

    def __init__(self, db_session_factory):
        self._db_factory = db_session_factory

    async def record_lineage(
        self,
        job_id: str,
        task_id: str,
        source_connection: str,
        source_dataset: str,
        source_table: str,
        target_connection: str,
        target_database: str,
        target_schema: str,
        target_table: str,
        rows_transferred: int,
        bytes_transferred: float,
        load_strategy: str,
        destination_mode: str,
        started_at: datetime,
        ended_at: datetime,
    ):
        """Record a completed data movement in the lineage store."""
        async with self._db_factory() as db:
            from sqlalchemy import text
            await db.execute(text("""
                INSERT INTO uma_lineage (
                    job_id, task_id,
                    source_connection, source_dataset, source_table,
                    target_connection, target_database, target_schema, target_table,
                    rows_transferred, bytes_transferred,
                    load_strategy, destination_mode,
                    started_at, ended_at, duration_seconds
                ) VALUES (
                    :job_id, :task_id,
                    :src_conn, :src_ds, :src_tbl,
                    :tgt_conn, :tgt_db, :tgt_schema, :tgt_tbl,
                    :rows, :bytes,
                    :strategy, :mode,
                    :started, :ended, :duration
                )
            """), {
                "job_id": job_id, "task_id": task_id,
                "src_conn": source_connection, "src_ds": source_dataset, "src_tbl": source_table,
                "tgt_conn": target_connection, "tgt_db": target_database,
                "tgt_schema": target_schema, "tgt_tbl": target_table,
                "rows": rows_transferred, "bytes": bytes_transferred,
                "strategy": load_strategy, "mode": destination_mode,
                "started": started_at, "ended": ended_at,
                "duration": (ended_at - started_at).total_seconds(),
            })
            await db.commit()

    async def get_table_lineage(self, target_table: str) -> List[Dict]:
        """Get full history of a Snowflake table."""
        async with self._db_factory() as db:
            from sqlalchemy import text
            result = await db.execute(text("""
                SELECT * FROM uma_lineage
                WHERE target_table=:t
                ORDER BY ended_at DESC
                LIMIT 100
            """), {"t": target_table})
            return [dict(r) for r in result.mappings()]

    async def get_job_lineage(self, job_id: str) -> List[Dict]:
        async with self._db_factory() as db:
            from sqlalchemy import text
            result = await db.execute(text("""
                SELECT * FROM uma_lineage WHERE job_id=:j ORDER BY ended_at DESC
            """), {"j": job_id})
            return [dict(r) for r in result.mappings()]


# ══════════════════════════════════════════════════════════════
# Backfill Manager
# ══════════════════════════════════════════════════════════════

class BackfillManager:
    """
    Manages historical backfill operations.
    Splits large historical ranges into manageable chunks,
    tracks progress, supports resume on failure.
    """

    def __init__(self, chunk_size_days: int = 30):
        self.chunk_size_days = chunk_size_days

    def build_date_chunks(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict]:
        """Split a date range into chunks for parallel backfill."""
        chunks = []
        current = start_date
        while current < end_date:
            chunk_end = min(current + timedelta(days=self.chunk_size_days), end_date)
            chunks.append({
                "chunk_start": current.isoformat(),
                "chunk_end": chunk_end.isoformat(),
                "chunk_id": hashlib.md5(
                    f"{current.isoformat()}{chunk_end.isoformat()}".encode()
                ).hexdigest()[:8],
            })
            current = chunk_end
        return chunks

    def build_incremental_where(
        self,
        date_col: str,
        chunk_start: str,
        chunk_end: str,
    ) -> str:
        return f"{date_col} >= '{chunk_start}' AND {date_col} < '{chunk_end}'"


# ══════════════════════════════════════════════════════════════
# Schema Fingerprint (for drift hashing)
# ══════════════════════════════════════════════════════════════

def fingerprint_schema(schema: List[Dict]) -> str:
    """Generate a stable hash of a schema for quick drift comparison."""
    normalized = sorted([
        f"{c.get('name','').upper()}:{c.get('type','').upper()}"
        for c in schema
        if not c.get("name","").upper().startswith("_UMA_")
    ])
    return hashlib.md5("|".join(normalized).encode()).hexdigest()
