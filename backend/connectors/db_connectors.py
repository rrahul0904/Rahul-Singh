"""
UMA Platform — Database Connectors
Oracle · PostgreSQL · MySQL · Teradata · Synapse
All follow the same interface: connect, test, list_schemas, list_tables,
get_table_schema, get_row_count, export_to_s3
"""

import logging, time, io
from typing import Dict, List, Any, Optional

logger = logging.getLogger("uma.connectors.db")


# ── Shared helpers ────────────────────────────────────────────

def _df_to_parquet(df) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    buf = io.BytesIO()
    # Stringify object columns for Parquet compatibility
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
    return buf.getvalue()


def _upload_to_s3(data: bytes, bucket: str, key: str, ak: str, sk: str, region: str):
    import boto3
    boto3.client("s3", aws_access_key_id=ak, aws_secret_access_key=sk,
                 region_name=region).put_object(Bucket=bucket, Key=key, Body=data)


# ══════════════════════════════════════════════════════════════
# Oracle
# ══════════════════════════════════════════════════════════════

class OracleConnector:
    """
    Requires: cx_Oracle (or oracledb thin driver — no client needed).
    config: host, port, service_name (or sid), user, password
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    def connect(self):
        try:
            import oracledb  # thin mode — no Oracle client required
            oracledb.init_oracle_client()  # no-op in thin mode
            dsn = oracledb.makedsn(
                self.config.get("host"),
                int(self.config.get("port", 1521)),
                service_name=self.config.get("service_name", ""),
                sid=self.config.get("sid", ""),
            )
            self._conn = oracledb.connect(
                user=self.config.get("user"),
                password=self.config.get("password"),
                dsn=dsn,
            )
        except ImportError:
            import cx_Oracle as ora
            dsn = ora.makedsn(self.config["host"], int(self.config.get("port", 1521)),
                              service_name=self.config.get("service_name", ""),
                              sid=self.config.get("sid", ""))
            self._conn = ora.connect(self.config["user"], self.config["password"], dsn)
        logger.info(f"Oracle connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn: self._conn.close(); self._conn = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM v$version WHERE ROWNUM=1")
            row = cur.fetchone()
            return {"success": True, "version": str(row[0])[:60] if row else "connected"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        cur = self._conn.cursor()
        cur.execute("SELECT username FROM all_users ORDER BY username")
        return [r[0] for r in cur.fetchall()]

    def list_tables(self, schema: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT table_name FROM all_tables WHERE owner=:s ORDER BY table_name",
                    {"s": schema.upper()})
        return [{"schema": schema, "table": r[0]} for r in cur.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("""SELECT column_name, data_type, data_length, data_precision,
                              data_scale, nullable
                       FROM all_tab_columns
                       WHERE owner=:s AND table_name=:t
                       ORDER BY column_id""",
                    {"s": schema.upper(), "t": table.upper()})
        return [{"name": r[0], "type": r[1], "length": r[2], "precision": r[3],
                 "scale": r[4], "mode": "REQUIRED" if r[5]=="N" else "NULLABLE"}
                for r in cur.fetchall()]

    def get_row_count(self, schema: str, table: str) -> int:
        cur = self._conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        return cur.fetchone()[0]

    def export_to_s3(self, schema: str, table: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1", batch_size: int = 500_000) -> Dict:
        import pandas as pd
        start = time.time(); total = 0; files = 0
        cur = self._conn.cursor()
        cur.execute(f'SELECT * FROM "{schema}"."{table}"')
        cols = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows: break
            df = pd.DataFrame(rows, columns=cols)
            data = _df_to_parquet(df)
            key = f"{s3_prefix}/part-{files:05d}.parquet"
            _upload_to_s3(data, s3_bucket, key, aws_access_key, aws_secret_key, aws_region)
            total += len(df); files += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": total,
                "files": files, "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# PostgreSQL
# ══════════════════════════════════════════════════════════════

class PostgreSQLConnector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    def connect(self):
        import psycopg2, psycopg2.extras
        self._DictCursor = psycopg2.extras.RealDictCursor
        self._conn = psycopg2.connect(
            host=self.config.get("host"),
            port=int(self.config.get("port", 5432)),
            dbname=self.config.get("database", "postgres"),
            user=self.config.get("user", ""),
            password=self.config.get("password", ""),
            sslmode=self.config.get("sslmode", "prefer"),
            connect_timeout=30,
        )
        self._conn.autocommit = True
        logger.info(f"PostgreSQL connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn: self._conn.close(); self._conn = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def _cur(self):
        import psycopg2.extras
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def test_connection(self) -> Dict:
        try:
            with self._cur() as c:
                c.execute("SELECT current_database(), current_user, version()")
                r = c.fetchone()
                return {"success": True, "database": r["current_database"],
                        "user": r["current_user"], "version": r["version"][:50]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        with self._cur() as c:
            c.execute("SELECT schema_name FROM information_schema.schemata "
                      "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') "
                      "ORDER BY schema_name")
            return [r["schema_name"] for r in c.fetchall()]

    def list_tables(self, schema: str = "public") -> List[Dict]:
        with self._cur() as c:
            c.execute("SELECT table_name, table_type FROM information_schema.tables "
                      "WHERE table_schema=%s ORDER BY table_name", (schema,))
            return [{"schema": schema, "table": r["table_name"], "type": r["table_type"]}
                    for r in c.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        with self._cur() as c:
            c.execute("SELECT column_name, data_type, character_maximum_length, "
                      "numeric_precision, numeric_scale, is_nullable "
                      "FROM information_schema.columns "
                      "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                      (schema, table))
            return [{"name": r["column_name"], "type": r["data_type"].upper(),
                     "length": r["character_maximum_length"],
                     "precision": r["numeric_precision"], "scale": r["numeric_scale"],
                     "mode": "REQUIRED" if r["is_nullable"]=="NO" else "NULLABLE"}
                    for r in c.fetchall()]

    def get_row_count(self, schema: str, table: str) -> int:
        with self._cur() as c:
            c.execute(f'SELECT COUNT(*) AS cnt FROM "{schema}"."{table}"')
            return c.fetchone()["cnt"]

    def export_to_s3(self, schema: str, table: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1", batch_size: int = 500_000) -> Dict:
        import pandas as pd
        start = time.time(); total = 0; files = 0
        with self._cur() as c:
            c.execute(f'SELECT * FROM "{schema}"."{table}"')
            cols = [d[0] for d in c.description]
            while True:
                rows = c.fetchmany(batch_size)
                if not rows: break
                df = pd.DataFrame([dict(r) for r in rows])
                data = _df_to_parquet(df)
                _upload_to_s3(data, s3_bucket, f"{s3_prefix}/part-{files:05d}.parquet",
                              aws_access_key, aws_secret_key, aws_region)
                total += len(df); files += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": total,
                "files": files, "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# MySQL
# ══════════════════════════════════════════════════════════════

class MySQLConnector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    def connect(self):
        import mysql.connector
        self._conn = mysql.connector.connect(
            host=self.config.get("host"),
            port=int(self.config.get("port", 3306)),
            database=self.config.get("database", ""),
            user=self.config.get("user", ""),
            password=self.config.get("password", ""),
            ssl_disabled=not self.config.get("ssl", True),
            connection_timeout=30,
        )
        logger.info(f"MySQL connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn: self._conn.close(); self._conn = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT VERSION(), DATABASE(), USER()")
            r = cur.fetchone()
            return {"success": True, "version": r[0], "database": r[1], "user": r[2]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        cur = self._conn.cursor()
        cur.execute("SHOW DATABASES")
        return [r[0] for r in cur.fetchall()
                if r[0] not in ("information_schema","performance_schema","mysql","sys")]

    def list_tables(self, schema: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME", (schema,))
        return [{"schema": schema, "table": r[0], "type": r[1]} for r in cur.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
                    "NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                    (schema, table))
        return [{"name": r[0], "type": r[1].upper(), "length": r[2],
                 "precision": r[3], "scale": r[4],
                 "mode": "REQUIRED" if r[5]=="NO" else "NULLABLE"}
                for r in cur.fetchall()]

    def get_row_count(self, schema: str, table: str) -> int:
        cur = self._conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM `{schema}`.`{table}`")
        return cur.fetchone()[0]

    def export_to_s3(self, schema: str, table: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1", batch_size: int = 500_000) -> Dict:
        import pandas as pd
        start = time.time(); total = 0; files = 0
        cur = self._conn.cursor()
        cur.execute(f"SELECT * FROM `{schema}`.`{table}`")
        cols = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows: break
            df = pd.DataFrame(rows, columns=cols)
            data = _df_to_parquet(df)
            _upload_to_s3(data, s3_bucket, f"{s3_prefix}/part-{files:05d}.parquet",
                          aws_access_key, aws_secret_key, aws_region)
            total += len(df); files += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": total,
                "files": files, "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Teradata
# ══════════════════════════════════════════════════════════════

class TeradataConnector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    def connect(self):
        import teradatasql
        self._conn = teradatasql.connect(
            host=self.config.get("host"),
            user=self.config.get("user"),
            password=self.config.get("password"),
            database=self.config.get("database", ""),
            logmech=self.config.get("logmech", "TD2"),
            encryptdata=self.config.get("encrypt", True),
        )
        logger.info(f"Teradata connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn: self._conn.close(); self._conn = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT CURRENT_USER, CURRENT_DATE, DATABASE")
            r = cur.fetchone()
            return {"success": True, "user": r[0], "database": r[2]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_databases(self) -> List[str]:
        cur = self._conn.cursor()
        cur.execute("SELECT DatabaseName FROM DBC.Databases ORDER BY DatabaseName")
        return [r[0].strip() for r in cur.fetchall()]

    def list_tables(self, database: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT TableName, TableKind FROM DBC.Tables "
                    "WHERE DatabaseName=? ORDER BY TableName", (database,))
        return [{"schema": database, "table": r[0].strip(), "type": r[1]} for r in cur.fetchall()]

    def get_table_schema(self, database: str, table: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT ColumnName, ColumnType, ColumnLength, DecimalFractionalDigits, Nullable "
                    "FROM DBC.Columns WHERE DatabaseName=? AND TableName=? ORDER BY ColumnId",
                    (database, table))
        TD_TYPE_MAP = {
            "CV": "STRING", "CF": "STRING", "CO": "TEXT", "N ": "NUMBER",
            "D ": "DECIMAL", "I ": "INT", "I1": "INT", "I2": "INT", "I8": "BIGINT",
            "F ": "FLOAT", "BF": "BYTES", "BV": "BYTES",
            "DA": "DATE", "TS": "TIMESTAMP", "TZ": "TIMESTAMP_TZ",
            "BO": "BOOLEAN", "++": "INTERVAL",
        }
        result = []
        for r in cur.fetchall():
            col_type = r[1].strip() if r[1] else "CV"
            result.append({
                "name": r[0].strip(), "type": TD_TYPE_MAP.get(col_type, "STRING"),
                "length": r[2], "scale": r[3],
                "mode": "NULLABLE" if r[4]=="Y" else "REQUIRED",
            })
        return result

    def get_row_count(self, database: str, table: str) -> int:
        cur = self._conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{database}"."{table}"')
        return cur.fetchone()[0]

    def export_to_s3(self, database: str, table: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1", batch_size: int = 200_000) -> Dict:
        import pandas as pd
        start = time.time(); total = 0; files = 0
        cur = self._conn.cursor()
        cur.execute(f'SELECT * FROM "{database}"."{table}"')
        cols = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows: break
            df = pd.DataFrame(rows, columns=cols)
            data = _df_to_parquet(df)
            _upload_to_s3(data, s3_bucket, f"{s3_prefix}/part-{files:05d}.parquet",
                          aws_access_key, aws_secret_key, aws_region)
            total += len(df); files += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": total,
                "files": files, "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Azure Synapse Analytics
# (Same wire as SQL Server — uses pyodbc with Synapse endpoint)
# ══════════════════════════════════════════════════════════════

class SynapseConnector:
    """Synapse Dedicated SQL Pool — identical interface to SQLServerConnector."""

    def __init__(self, config: Dict[str, Any]):
        from connectors.sqlserver_connector import SQLServerConnector
        config["driver"] = config.get("driver", "ODBC Driver 18 for SQL Server")
        config["encrypt"] = config.get("encrypt", True)
        self._inner = SQLServerConnector(config)

    def connect(self):    self._inner.connect()
    def disconnect(self): self._inner.disconnect()
    def __enter__(self):  self._inner.connect(); return self
    def __exit__(self, *a): self._inner.disconnect()

    def test_connection(self) -> Dict:  return self._inner.test_connection()
    def list_schemas(self) -> List[str]: return self._inner.list_schemas()
    def list_tables(self, schema: str) -> List[Dict]: return self._inner.list_tables(schema)
    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        return self._inner.get_table_schema(schema, table)
    def get_row_count(self, schema: str, table: str) -> int:
        return self._inner.get_row_count(schema, table)
    def export_to_s3(self, **kw) -> Dict: return self._inner.export_to_s3(**kw)
