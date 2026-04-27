"""
UMA Platform — SQL Server Connector
Handles: connection testing, schema introspection, bulk export via pyodbc + pandas → Parquet → S3
"""

# import pyodbc  -- lazy imported in connect()
from typing import Dict, List, Any, Optional
import logging
import time
import io
import os

logger = logging.getLogger("uma.connectors.sqlserver")


class SQLServerConnector:
    def __init__(self, config: Dict[str, Any]):
        """
        config keys: host, port, database, user, password, driver
        """
        self.config = config
        self._conn = None

    def _connection_string(self) -> str:
        driver = self.config.get("driver", "ODBC Driver 18 for SQL Server")
        host = self.config.get("host", "")
        port = self.config.get("port", 1433)
        database = self.config.get("database", "master")
        user = self.config.get("user", "")
        password = self.config.get("password", "")
        encrypt = "yes" if self.config.get("encrypt", True) else "no"
        trust_cert = "yes" if self.config.get("trust_server_certificate", False) else "no"

        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={host},{port};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust_cert};"
            f"Connection Timeout=30;"
        )

    def connect(self):
        import pyodbc
        self._conn = pyodbc.connect(self._connection_string())
        logger.info(f"SQL Server connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def test_connection(self) -> Dict[str, Any]:
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT @@VERSION AS ver, DB_NAME() AS db, SYSTEM_USER AS usr")
            row = cursor.fetchone()
            return {
                "success": True,
                "version": row.ver[:60],
                "database": row.db,
                "user": row.usr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
            "WHERE SCHEMA_NAME NOT IN ('sys','INFORMATION_SCHEMA') ORDER BY SCHEMA_NAME"
        )
        return [r[0] for r in cursor.fetchall()]

    def list_tables(self, schema: str = "dbo") -> List[Dict]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? ORDER BY TABLE_NAME",
            schema
        )
        return [{"schema": schema, "table": r[0], "type": r[1]} for r in cursor.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.CHARACTER_MAXIMUM_LENGTH,
                c.NUMERIC_PRECISION,
                c.NUMERIC_SCALE,
                c.IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS c
            WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ?
            ORDER BY c.ORDINAL_POSITION
        """, schema, table)
        return [{
            "name": r[0],
            "type": r[1].upper(),
            "length": r[2],
            "precision": r[3],
            "scale": r[4],
            "mode": "REQUIRED" if r[5] == "NO" else "NULLABLE",
        } for r in cursor.fetchall()]

    def get_row_count(self, schema: str, table: str) -> int:
        cursor = self._conn.cursor()
        cursor.execute(f'SELECT COUNT(*) FROM [{schema}].[{table}]')
        return cursor.fetchone()[0]

    def export_to_s3(
        self,
        schema: str,
        table: str,
        s3_bucket: str,
        s3_prefix: str,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
        file_format: str = "parquet",
        batch_size: int = 500_000,
    ) -> Dict[str, Any]:
        """
        Export SQL Server table to S3 via chunked pandas read → Parquet → boto3 upload.
        Handles tables of any size by streaming in batches.
        """
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
        import boto3

        s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region,
        )

        sql = f"SELECT * FROM [{schema}].[{table}]"
        start = time.time()
        total_rows = 0
        file_count = 0

        logger.info(f"SQL Server export: [{schema}].[{table}] → s3://{s3_bucket}/{s3_prefix}")

        cursor = self._conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]

        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break

            df = pd.DataFrame.from_records(rows, columns=columns)
            # Convert unsupported types
            for col in df.select_dtypes(include=["object"]).columns:
                df[col] = df[col].astype(str)

            buf = io.BytesIO()
            if file_format == "parquet":
                table_pa = pa.Table.from_pandas(df)
                pq.write_table(table_pa, buf, compression="snappy")
                ext = "parquet"
            else:
                df.to_csv(buf, index=False)
                ext = "csv"

            buf.seek(0)
            key = f"{s3_prefix}/part-{file_count:05d}.{ext}"
            s3.put_object(Bucket=s3_bucket, Key=key, Body=buf.getvalue())

            total_rows += len(df)
            file_count += 1
            logger.info(f"  Uploaded part {file_count}: {len(df):,} rows → s3://{s3_bucket}/{key}")

        duration = time.time() - start
        s3_path = f"s3://{s3_bucket}/{s3_prefix}/"

        logger.info(f"SQL Server export complete: {total_rows:,} rows, {file_count} files, {duration:.1f}s")
        return {
            "s3_path": s3_path,
            "total_rows": total_rows,
            "files": file_count,
            "duration_seconds": duration,
        }
