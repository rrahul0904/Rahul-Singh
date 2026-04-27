"""
UMA Platform — Redshift Connector
Handles: connection testing, schema introspection, UNLOAD to S3
"""

import psycopg2
import psycopg2.extras
from typing import Dict, List, Any, Optional
import logging
import time

logger = logging.getLogger("uma.connectors.redshift")


class RedshiftConnector:
    def __init__(self, config: Dict[str, Any]):
        """
        config keys: host, port, database, user, password, ssl (bool)
        credentials keys: user, password
        """
        self.config = config
        self._conn = None

    def connect(self):
        self._conn = psycopg2.connect(
            host=self.config.get("host"),
            port=int(self.config.get("port", 5439)),
            dbname=self.config.get("database", "dev"),
            user=self.config.get("user", ""),
            password=self.config.get("password", ""),
            sslmode="require" if self.config.get("ssl", True) else "prefer",
            connect_timeout=30,
        )
        self._conn.autocommit = True
        logger.info(f"Redshift connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def _cursor(self):
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def test_connection(self) -> Dict[str, Any]:
        try:
            with self._cursor() as cur:
                cur.execute("SELECT current_database(), current_user, version()")
                row = cur.fetchone()
                return {
                    "success": True,
                    "database": row["current_database"],
                    "user": row["current_user"],
                    "version": row["version"][:50],
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast','pg_temp_1') "
                "ORDER BY schema_name"
            )
            return [r["schema_name"] for r in cur.fetchall()]

    def list_tables(self, schema: str = "public") -> List[Dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                (schema,)
            )
            return [{"schema": schema, "table": r["table_name"], "type": r["table_type"]} for r in cur.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, character_maximum_length, "
                "numeric_precision, numeric_scale, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (schema, table)
            )
            rows = cur.fetchall()
            return [{
                "name": r["column_name"],
                "type": r["data_type"].upper(),
                "length": r["character_maximum_length"],
                "precision": r["numeric_precision"],
                "scale": r["numeric_scale"],
                "mode": "REQUIRED" if r["is_nullable"] == "NO" else "NULLABLE",
            } for r in rows]

    def get_row_count(self, schema: str, table: str) -> int:
        with self._cursor() as cur:
            cur.execute(f'SELECT COUNT(*) AS cnt FROM "{schema}"."{table}"')
            return cur.fetchone()["cnt"]

    def unload_to_s3(
        self,
        schema: str,
        table: str,
        s3_path: str,
        iam_role: str,
        file_format: str = "parquet",
        partition_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        UNLOAD a Redshift table to S3.
        Uses Redshift native UNLOAD command — fastest path for large tables.
        """
        query = f'SELECT * FROM "{schema}"."{table}"'

        if file_format.lower() == "parquet":
            format_clause = "FORMAT AS PARQUET"
        elif file_format.lower() == "csv":
            format_clause = "DELIMITER ',' ADDQUOTES HEADER GZIP"
        else:
            format_clause = "FORMAT AS PARQUET"

        partition_clause = f"PARTITION BY ({partition_by})" if partition_by else ""

        unload_sql = f"""
UNLOAD ('{query}')
TO '{s3_path}'
IAM_ROLE '{iam_role}'
{format_clause}
{partition_clause}
ALLOWOVERWRITE
PARALLEL ON
""".strip()

        logger.info(f"UNLOAD: {schema}.{table} → {s3_path}")
        start = time.time()

        with self._cursor() as cur:
            cur.execute(unload_sql)

        duration = time.time() - start
        logger.info(f"UNLOAD complete in {duration:.1f}s")

        return {
            "unload_statement": unload_sql,
            "s3_path": s3_path,
            "duration_seconds": duration,
        }

    def run_query(self, sql: str) -> List[Dict]:
        with self._cursor() as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
