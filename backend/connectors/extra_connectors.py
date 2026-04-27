"""
UMA Platform — Additional Database & Streaming Connectors
IBM DB2 · SAP HANA · GCP Pub/Sub · Azure Event Hubs
"""

import logging
import time
import io
from typing import Dict, List, Any, Optional

logger = logging.getLogger("uma.connectors.extra")


# ══════════════════════════════════════════════════════════════
# IBM DB2
# ══════════════════════════════════════════════════════════════

class DB2Connector:
    """
    IBM DB2 connector using ibm_db_dbi.
    config: host, port, database, user, password, ssl
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    def connect(self):
        import ibm_db_dbi
        dsn = (
            f"DATABASE={self.config.get('database')};"
            f"HOSTNAME={self.config.get('host')};"
            f"PORT={self.config.get('port', 50000)};"
            f"PROTOCOL=TCPIP;"
            f"UID={self.config.get('user')};"
            f"PWD={self.config.get('password')};"
        )
        if self.config.get("ssl", False):
            dsn += "SECURITY=SSL;"
        self._conn = ibm_db_dbi.connect(dsn, "", "")
        logger.info(f"DB2 connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn: self._conn.close(); self._conn = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT CURRENT SERVER, CURRENT USER FROM SYSIBM.SYSDUMMY1")
            r = cur.fetchone()
            return {"success": True, "server": str(r[0]), "user": str(r[1])}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT TRIM(TABSCHEMA) FROM SYSCAT.TABLES "
                    "WHERE TABSCHEMA NOT LIKE 'SYS%' ORDER BY 1")
        return [r[0] for r in cur.fetchall()]

    def list_tables(self, schema: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT TRIM(TABNAME), TYPE FROM SYSCAT.TABLES "
                    "WHERE TABSCHEMA = ? ORDER BY TABNAME", (schema.upper(),))
        return [{"schema": schema, "table": r[0], "type": r[1]} for r in cur.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("""SELECT COLNAME, TYPENAME, LENGTH, SCALE, NULLS
                       FROM SYSCAT.COLUMNS
                       WHERE TABSCHEMA = ? AND TABNAME = ?
                       ORDER BY COLNO""", (schema.upper(), table.upper()))
        return [{"name": r[0], "type": r[1], "length": r[2], "scale": r[3],
                 "mode": "NULLABLE" if r[4] == "Y" else "REQUIRED"}
                for r in cur.fetchall()]

    def get_row_count(self, schema: str, table: str) -> int:
        cur = self._conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        return cur.fetchone()[0]

    def export_to_s3(self, schema: str, table: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1", batch_size: int = 200_000) -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        s3 = boto3.client("s3", aws_access_key_id=aws_access_key,
                          aws_secret_access_key=aws_secret_key, region_name=aws_region)
        start = time.time(); total = 0; files = 0
        cur = self._conn.cursor()
        cur.execute(f'SELECT * FROM "{schema}"."{table}"')
        cols = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows: break
            df = pd.DataFrame(rows, columns=cols)
            for c in df.select_dtypes(include=["object"]).columns:
                df[c] = df[c].astype(str)
            buf = io.BytesIO()
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                           buf, compression="snappy")
            s3.put_object(Bucket=s3_bucket, Key=f"{s3_prefix}/part-{files:05d}.parquet",
                          Body=buf.getvalue())
            total += len(df); files += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": total, "files": files,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# SAP HANA
# ══════════════════════════════════════════════════════════════

class SAPHanaConnector:
    """
    SAP HANA connector using hdbcli.
    config: host, port, user, password, encrypt, sslValidateCertificate
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    def connect(self):
        from hdbcli import dbapi
        self._conn = dbapi.connect(
            address=self.config.get("host"),
            port=int(self.config.get("port", 443)),
            user=self.config.get("user"),
            password=self.config.get("password"),
            encrypt=str(self.config.get("encrypt", True)).lower(),
            sslValidateCertificate=str(
                self.config.get("sslValidateCertificate", False)).lower(),
        )
        logger.info(f"SAP HANA connected: {self.config.get('host')}")

    def disconnect(self):
        if self._conn: self._conn.close(); self._conn = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT CURRENT_USER, CURRENT_DATE FROM DUMMY")
            r = cur.fetchone()
            return {"success": True, "user": r[0]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_schemas(self) -> List[str]:
        cur = self._conn.cursor()
        cur.execute("SELECT SCHEMA_NAME FROM SCHEMAS "
                    "WHERE SCHEMA_NAME NOT LIKE '\\_SYS%' ESCAPE '\\' "
                    "ORDER BY SCHEMA_NAME")
        return [r[0] for r in cur.fetchall()]

    def list_tables(self, schema: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT TABLE_NAME FROM TABLES WHERE SCHEMA_NAME = ? "
                    "ORDER BY TABLE_NAME", (schema,))
        return [{"schema": schema, "table": r[0]} for r in cur.fetchall()]

    def get_table_schema(self, schema: str, table: str) -> List[Dict]:
        cur = self._conn.cursor()
        cur.execute("""SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, SCALE, IS_NULLABLE
                       FROM TABLE_COLUMNS
                       WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
                       ORDER BY POSITION""", (schema, table))
        return [{"name": r[0], "type": r[1], "length": r[2], "scale": r[3],
                 "mode": "NULLABLE" if r[4] == "TRUE" else "REQUIRED"}
                for r in cur.fetchall()]

    def get_row_count(self, schema: str, table: str) -> int:
        cur = self._conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        return cur.fetchone()[0]

    def export_to_s3(self, schema: str, table: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1", batch_size: int = 200_000) -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        s3 = boto3.client("s3", aws_access_key_id=aws_access_key,
                          aws_secret_access_key=aws_secret_key, region_name=aws_region)
        start = time.time(); total = 0; files = 0
        cur = self._conn.cursor()
        cur.execute(f'SELECT * FROM "{schema}"."{table}"')
        cols = [d[0] for d in cur.description]
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows: break
            df = pd.DataFrame(rows, columns=cols)
            for c in df.select_dtypes(include=["object"]).columns:
                df[c] = df[c].astype(str)
            buf = io.BytesIO()
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                           buf, compression="snappy")
            s3.put_object(Bucket=s3_bucket, Key=f"{s3_prefix}/part-{files:05d}.parquet",
                          Body=buf.getvalue())
            total += len(df); files += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": total, "files": files,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# GCP Pub/Sub
# ══════════════════════════════════════════════════════════════

class PubSubConnector:
    """
    Google Cloud Pub/Sub subscriber → S3 micro-batch.
    config: project_id, subscription, service_account_json
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._subscriber = None
        self._sub_path = None

    def connect(self):
        from google.cloud import pubsub_v1
        from google.oauth2 import service_account
        import json

        sa_json = self.config.get("service_account_json", "")
        if sa_json:
            sa_info = json.loads(sa_json) if isinstance(sa_json, str) else sa_json
            creds = service_account.Credentials.from_service_account_info(sa_info)
            self._subscriber = pubsub_v1.SubscriberClient(credentials=creds)
        else:
            self._subscriber = pubsub_v1.SubscriberClient()

        self._sub_path = self._subscriber.subscription_path(
            self.config.get("project_id"), self.config.get("subscription"))
        logger.info(f"Pub/Sub connected: {self._sub_path}")

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            sub = self._subscriber.get_subscription(
                request={"subscription": self._sub_path})
            return {"success": True, "subscription": self._sub_path,
                    "topic": sub.topic}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def consume_batch(self, max_messages: int = 10000) -> List[Dict]:
        import json
        all_records = []; fetched = 0
        while fetched < max_messages:
            response = self._subscriber.pull(
                request={"subscription": self._sub_path,
                          "max_messages": min(1000, max_messages - fetched)},
                timeout=10)
            if not response.received_messages: break
            ack_ids = []
            for msg in response.received_messages:
                try:
                    data = json.loads(msg.message.data.decode("utf-8"))
                except Exception:
                    data = {"raw": msg.message.data.decode("utf-8", errors="replace")}
                data["_pubsub_message_id"] = msg.message.message_id
                data["_pubsub_publish_time"] = msg.message.publish_time.isoformat()
                all_records.append(data)
                ack_ids.append(msg.ack_id)
            # Acknowledge
            self._subscriber.acknowledge(
                request={"subscription": self._sub_path, "ack_ids": ack_ids})
            fetched += len(response.received_messages)
        return all_records

    def stream_to_s3(self, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.consume_batch()
        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0, "files": 0}

        start = time.time()
        df = pd.json_normalize(records)
        for c in df.select_dtypes(include=["object"]).columns:
            df[c] = df[c].astype(str)
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                       buf, compression="snappy")
        buf.seek(0)
        boto3.client("s3", aws_access_key_id=aws_access_key,
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket,
            Key=f"{s3_prefix}/{int(time.time()*1000)}.parquet",
            Body=buf.getvalue())
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Azure Event Hubs
# ══════════════════════════════════════════════════════════════

class EventHubsConnector:
    """
    Azure Event Hubs consumer → S3 micro-batch.
    config: connection_string, event_hub_name, consumer_group
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None

    def connect(self):
        from azure.eventhub import EventHubConsumerClient
        self._client = EventHubConsumerClient.from_connection_string(
            conn_str=self.config.get("connection_string", ""),
            consumer_group=self.config.get("consumer_group", "$Default"),
            eventhub_name=self.config.get("event_hub_name", ""),
        )
        logger.info(f"Event Hubs connected: {self.config.get('event_hub_name')}")

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a):
        if self._client: self._client.close()

    def test_connection(self) -> Dict:
        try:
            props = self._client.get_eventhub_properties()
            return {"success": True, "event_hub": props["eventhub_name"],
                    "partition_count": len(props["partition_ids"])}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def consume_batch(self, max_messages: int = 10000, timeout_seconds: int = 30) -> List[Dict]:
        import json
        records = []

        def on_event(partition_context, event):
            if not event: return
            try:
                body = b"".join(event.body)
                data = json.loads(body.decode("utf-8"))
            except Exception:
                data = {"raw": event.body_as_str() if hasattr(event, "body_as_str") else "?"}
            data["_eh_offset"] = event.offset
            data["_eh_seq"]    = event.sequence_number
            data["_eh_partition"] = partition_context.partition_id
            records.append(data)
            partition_context.update_checkpoint(event)
            if len(records) >= max_messages:
                raise StopIteration

        try:
            self._client.receive(on_event=on_event,
                                 starting_position="-1",
                                 max_wait_time=timeout_seconds)
        except StopIteration:
            pass
        except Exception as e:
            logger.error(f"Event Hubs receive error: {e}")

        return records

    def stream_to_s3(self, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.consume_batch()
        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0, "files": 0}

        start = time.time()
        df = pd.json_normalize(records)
        for c in df.select_dtypes(include=["object"]).columns:
            df[c] = df[c].astype(str)
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                       buf, compression="snappy")
        buf.seek(0)
        boto3.client("s3", aws_access_key_id=aws_access_key,
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket,
            Key=f"{s3_prefix}/{int(time.time()*1000)}.parquet",
            Body=buf.getvalue())
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}
