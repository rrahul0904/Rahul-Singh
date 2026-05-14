"""
UMA Platform — Snowflake Connector
Handles: connection testing, schema introspection, table creation,
COPY INTO execution, row count validation
"""

import snowflake.connector
from snowflake.connector import DictCursor
from typing import Optional, List, Dict, Any
import logging
import os
import time

from services.snowflake_connection import snowflake_connect_kwargs

logger = logging.getLogger("uma.connectors.snowflake")


def _mfa_required_error(err: str) -> bool:
    lowered = (err or "").lower()
    return "mfa with totp is required" in lowered or ("mfa" in lowered and "totp" in lowered and "required" in lowered)


class SnowflakeConnector:
    """
    Manages a Snowflake connection for a single job execution.
    Uses synchronous snowflake-connector-python (run in thread pool from async code).
    """

    def __init__(self, config: Dict[str, Any]):
        """
        config keys:
          account, user, password, warehouse, database, schema, role
          Optional: private_key, private_key_passphrase (for key-pair auth)
        """
        self.config = config
        self._conn: Optional[snowflake.connector.SnowflakeConnection] = None

    def connect(self) -> None:
        logger.info(f"Connecting to Snowflake account: {self.config.get('account')}")
        insecure_mode = os.getenv("SNOWFLAKE_INSECURE_MODE", "false").lower() == "true"
        ca_bundle = os.getenv("SNOWFLAKE_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE")
        if ca_bundle:
            os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
            os.environ["SSL_CERT_FILE"] = ca_bundle
        if insecure_mode:
            logger.warning("SNOWFLAKE_INSECURE_MODE=true; TLS certificate validation is disabled for local development")
        connect_kwargs = snowflake_connect_kwargs(self.config)
        try:
            self._conn = snowflake.connector.connect(**connect_kwargs)
        finally:
            self.config.pop("mfa_passcode", None)
        logger.info("Snowflake connection established")

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def _cursor(self) -> DictCursor:
        if not self._conn:
            raise RuntimeError("Not connected to Snowflake")
        return self._conn.cursor(DictCursor)

    # ── Connection Test ────────────────────────────────────────

    def test_connection(self) -> Dict[str, Any]:
        """Test connectivity and return account metadata."""
        try:
            with self._cursor() as cur:
                cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_REGION(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
                row = cur.fetchone()
                return {
                    "success": True,
                    "account": row["CURRENT_ACCOUNT()"],
                    "region": row["CURRENT_REGION()"],
                    "role": row["CURRENT_ROLE()"],
                    "warehouse": row["CURRENT_WAREHOUSE()"],
                }
        except Exception as e:
            logger.error(f"Snowflake connection test failed: {e}")
            err = str(e)
            diagnostic = None
            lowered = err.lower()
            if _mfa_required_error(err):
                diagnostic = "Snowflake requires MFA/TOTP. Enter a current MFA code and rerun the diagnostic."
            elif any(s in lowered for s in ("certificate verify failed", "self signed certificate", "tlsv1 alert", "ssl")):
                diagnostic = (
                    "Snowflake TLS certificate validation failed. Ensure the container has ca-certificates installed, "
                    "set SNOWFLAKE_CA_BUNDLE or REQUESTS_CA_BUNDLE to your corporate CA bundle if TLS inspection is used, "
                    "or use SNOWFLAKE_INSECURE_MODE=true only for local development."
                )
            return {"success": False, "error": err, "diagnostic": diagnostic}

    # ── Schema / DDL ──────────────────────────────────────────

    def ensure_schema(self, database: str, schema: str) -> None:
        """Create database and schema if they don't exist."""
        with self._cursor() as cur:
            cur.execute(f'CREATE DATABASE IF NOT EXISTS "{database}"')
            cur.execute(f'USE DATABASE "{database}"')
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{database}"."{schema}"')
        logger.info(f"Schema ensured: {database}.{schema}")

    def table_exists(self, database: str, schema: str, table: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                "WHERE table_catalog = %s AND table_schema = %s AND table_name = %s",
                (database.upper(), schema.upper(), table.upper())
            )
            return cur.fetchone()["CNT"] > 0

    def create_table_from_definition(self, ddl: str) -> None:
        """Execute a CREATE TABLE IF NOT EXISTS statement."""
        with self._cursor() as cur:
            cur.execute(ddl)
        logger.info("Table created from DDL")

    def get_row_count(self, database: str, schema: str, table: str) -> int:
        with self._cursor() as cur:
            cur.execute(f'SELECT COUNT(*) AS cnt FROM "{database}"."{schema}"."{table}"')
            return cur.fetchone()["CNT"]

    def get_column_list(self, database: str, schema: str, table: str) -> List[Dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_catalog = %s AND table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (database.upper(), schema.upper(), table.upper())
            )
            return cur.fetchall()

    # ── COPY INTO (S3 → Snowflake) ────────────────────────────

    def copy_from_s3(
        self,
        database: str,
        schema: str,
        table: str,
        s3_path: str,
        iam_role: str,
        file_format: str = "parquet",
        purge: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute COPY INTO from S3 external stage using IAM role.
        Returns load statistics.
        """
        format_clause = self._file_format_clause(file_format)
        purge_clause = "PURGE = TRUE" if purge else ""

        copy_sql = f"""
COPY INTO "{database}"."{schema}"."{table}"
FROM '{s3_path}'
CREDENTIALS = (AWS_ROLE = '{iam_role}')
{format_clause}
{purge_clause}
ON_ERROR = 'CONTINUE'
""".strip()

        logger.info(f"Executing COPY INTO: {database}.{schema}.{table} from {s3_path}")
        start = time.time()

        with self._cursor() as cur:
            cur.execute(copy_sql)
            results = cur.fetchall()

        duration = time.time() - start
        rows_loaded = sum(r.get("rows_loaded", 0) for r in results)
        rows_error  = sum(r.get("rows_with_errors", 0) for r in results)

        logger.info(f"COPY INTO complete: {rows_loaded} rows loaded, {rows_error} errors, {duration:.1f}s")
        return {
            "copy_statement": copy_sql,
            "rows_loaded": rows_loaded,
            "rows_with_errors": rows_error,
            "duration_seconds": duration,
            "results": results,
        }

    def copy_from_azure(
        self,
        database: str,
        schema: str,
        table: str,
        azure_path: str,
        sas_token: str,
        file_format: str = "parquet",
    ) -> Dict[str, Any]:
        """COPY INTO from Azure Blob / ADLS Gen2."""
        format_clause = self._file_format_clause(file_format)
        copy_sql = f"""
COPY INTO "{database}"."{schema}"."{table}"
FROM '{azure_path}'
CREDENTIALS = (AZURE_SAS_TOKEN = '{sas_token}')
{format_clause}
ON_ERROR = 'CONTINUE'
""".strip()

        start = time.time()
        with self._cursor() as cur:
            cur.execute(copy_sql)
            results = cur.fetchall()

        rows_loaded = sum(r.get("rows_loaded", 0) for r in results)
        return {
            "copy_statement": copy_sql,
            "rows_loaded": rows_loaded,
            "duration_seconds": time.time() - start,
        }

    def copy_from_internal_stage(
        self,
        database: str,
        schema: str,
        table: str,
        stage_name: str,
        path: str = "",
        file_format: str = "parquet",
    ) -> Dict[str, Any]:
        """COPY INTO from a named Snowflake internal stage."""
        format_clause = self._file_format_clause(file_format)
        stage_ref = f"@{stage_name}/{path}" if path else f"@{stage_name}"
        copy_sql = f"""
COPY INTO "{database}"."{schema}"."{table}"
FROM {stage_ref}
{format_clause}
ON_ERROR = 'CONTINUE'
""".strip()

        start = time.time()
        with self._cursor() as cur:
            cur.execute(copy_sql)
            results = cur.fetchall()

        rows_loaded = sum(r.get("rows_loaded", 0) for r in results)
        return {
            "copy_statement": copy_sql,
            "rows_loaded": rows_loaded,
            "duration_seconds": time.time() - start,
        }

    # ── External Stage / Table / Iceberg ─────────────────────

    def create_external_stage(
        self,
        database: str,
        schema: str,
        stage_name: str,
        s3_url: str,
        iam_role: str,
        file_format: str = "parquet",
    ) -> str:
        sql = f"""
CREATE OR REPLACE STAGE "{database}"."{schema}"."{stage_name}"
URL = '{s3_url}'
CREDENTIALS = (AWS_ROLE = '{iam_role}')
FILE_FORMAT = ({self._file_format_clause(file_format, inline=True)})
""".strip()
        with self._cursor() as cur:
            cur.execute(sql)
        return sql

    def create_external_table(
        self,
        database: str,
        schema: str,
        table: str,
        stage_name: str,
        columns_ddl: str,
        file_format: str = "parquet",
    ) -> str:
        sql = f"""
CREATE OR REPLACE EXTERNAL TABLE "{database}"."{schema}"."{table}"
({columns_ddl})
WITH LOCATION = @"{database}"."{schema}"."{stage_name}"
FILE_FORMAT = ({self._file_format_clause(file_format, inline=True)})
AUTO_REFRESH = TRUE
""".strip()
        with self._cursor() as cur:
            cur.execute(sql)
        return sql

    # ── Validation Queries ────────────────────────────────────

    def run_query(self, sql: str) -> List[Dict]:
        with self._cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    def execute(self, sql: str) -> None:
        with self._cursor() as cur:
            cur.execute(sql)

    # ── DDL Generation ────────────────────────────────────────

    @staticmethod
    def map_source_type_to_snowflake(source_type: str, precision: int = 0, scale: int = 0, length: int = 0) -> str:
        """
        Map common source SQL types to Snowflake equivalents.
        Handles BigQuery, Redshift, SQL Server, Salesforce field types.
        """
        t = source_type.upper().strip()

        # String types
        if t in ("STRING", "TEXT", "NTEXT", "LONGTEXT", "MEDIUMTEXT", "CLOB", "NVARCHAR(MAX)", "VARCHAR(MAX)"):
            return "VARCHAR(16777216)"
        if t.startswith("VARCHAR") or t.startswith("NVARCHAR") or t.startswith("CHAR"):
            if length and length <= 16777216:
                return f"VARCHAR({length})"
            return "VARCHAR(16777216)"

        # Numeric
        if t in ("INT64", "INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT"):
            return "NUMBER(38,0)"
        if t in ("FLOAT64", "FLOAT", "DOUBLE", "REAL"):
            return "FLOAT"
        if t.startswith("NUMERIC") or t.startswith("DECIMAL"):
            if precision:
                return f"NUMBER({precision},{scale})"
            return "NUMBER(38,9)"

        # Boolean
        if t in ("BOOL", "BOOLEAN", "BIT"):
            return "BOOLEAN"

        # Date/Time
        if t in ("DATE",):
            return "DATE"
        if t in ("TIME",):
            return "TIME"
        if t in ("DATETIME", "DATETIME2", "SMALLDATETIME"):
            return "TIMESTAMP_NTZ"
        if t in ("TIMESTAMP", "TIMESTAMP_WITH_TIME_ZONE", "TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"):
            return "TIMESTAMP_TZ"
        if t in ("TIMESTAMP_NTZ", "TIMESTAMP WITHOUT TIME ZONE"):
            return "TIMESTAMP_NTZ"

        # Semi-structured
        if t in ("JSON", "JSONB", "SUPER", "HLLSKETCH", "GEOGRAPHY", "GEOMETRY"):
            return "VARIANT"
        if t in ("ARRAY",):
            return "ARRAY"

        # Binary
        if t in ("BYTES", "BYTEA", "BINARY", "VARBINARY", "IMAGE"):
            return "BINARY"

        # Fallback
        return "VARCHAR(16777216)"

    @staticmethod
    def _file_format_clause(file_format: str, inline: bool = False) -> str:
        fmt = file_format.lower()
        if fmt == "parquet":
            clause = "TYPE = PARQUET SNAPPY_COMPRESSION = TRUE"
        elif fmt == "csv":
            clause = "TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = '\"' NULL_IF = ('NULL', 'null', '') EMPTY_FIELD_AS_NULL = TRUE SKIP_HEADER = 1"
        elif fmt == "json":
            clause = "TYPE = JSON STRIP_OUTER_ARRAY = TRUE"
        elif fmt == "avro":
            clause = "TYPE = AVRO"
        else:
            clause = "TYPE = PARQUET"

        if inline:
            return clause
        return f"FILE_FORMAT = ({clause})"


    # ── Navigator helpers ─────────────────────────────────────

    def list_databases(self) -> List[str]:
        with self._cursor() as cur:
            cur.execute("SHOW DATABASES")
            return [row["name"] for row in cur.fetchall()]

    def list_schemas(self, database: str) -> List[str]:
        with self._cursor() as cur:
            cur.execute(f'SHOW SCHEMAS IN DATABASE "{database}"')
            return [row["name"] for row in cur.fetchall()]

    def list_tables(self, database: str, schema: str) -> List[str]:
        with self._cursor() as cur:
            cur.execute(f'SHOW TABLES IN SCHEMA "{database}"."{schema}"')
            return [row["name"] for row in cur.fetchall()]

    def describe_table(self, database: str, schema: str, table: str) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f'DESCRIBE TABLE "{database}"."{schema}"."{table}"')
            rows = cur.fetchall()
            return [{"name": r.get("name"), "type": r.get("type"), "kind": r.get("kind"), "null?": r.get("null?"), "default": r.get("default")} for r in rows]

    def preview_table(self, database: str, schema: str, table: str, limit: int = 100) -> Dict[str, Any]:
        with self._cursor() as cur:
            cur.execute(f'SELECT * FROM "{database}"."{schema}"."{table}" LIMIT {int(limit)}')
            rows = cur.fetchall()
            cols = list(rows[0].keys()) if rows else []
            out_rows = [[row.get(c) for c in cols] for row in rows]
            return {"columns": cols, "rows": out_rows, "row_count": len(out_rows)}
