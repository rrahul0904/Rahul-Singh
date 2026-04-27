"""
UMA Platform — Streaming Connectors
Kafka · Kinesis · Azure Event Hubs · GCP Pub/Sub
Consumes events, batches them, writes Parquet to staging, triggers Snowflake COPY INTO.
"""

import logging, time, io
from typing import Dict, List, Any, Optional

logger = logging.getLogger("uma.connectors.streaming")


# ══════════════════════════════════════════════════════════════
# Kafka Consumer → S3 → Snowflake
# ══════════════════════════════════════════════════════════════

class KafkaConnector:
    """
    Kafka → S3 micro-batch connector.
    Consumes messages from a topic, batches them into Parquet files,
    uploads to S3, triggers Snowflake COPY INTO.

    config: bootstrap_servers, topic, group_id, security_protocol,
            sasl_mechanism, sasl_username, sasl_password,
            schema_registry_url (optional), batch_size, batch_interval_seconds
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._consumer = None

    def connect(self):
        from kafka import KafkaConsumer
        from kafka.errors import NoBrokersAvailable

        security = self.config.get("security_protocol", "PLAINTEXT")
        kwargs = {
            "bootstrap_servers": self.config.get("bootstrap_servers", "localhost:9092"),
            "group_id": self.config.get("group_id", "uma-ingestion"),
            "auto_offset_reset": self.config.get("auto_offset_reset", "earliest"),
            "enable_auto_commit": False,
            "value_deserializer": lambda m: m,  # raw bytes — we decode below
            "consumer_timeout_ms": int(self.config.get("consumer_timeout_ms", 10000)),
        }

        if security in ("SASL_PLAINTEXT", "SASL_SSL"):
            kwargs.update({
                "security_protocol": security,
                "sasl_mechanism": self.config.get("sasl_mechanism", "PLAIN"),
                "sasl_plain_username": self.config.get("sasl_username", ""),
                "sasl_plain_password": self.config.get("sasl_password", ""),
            })
        if security == "SSL":
            kwargs["security_protocol"] = "SSL"

        self._consumer = KafkaConsumer(**kwargs)
        topic = self.config.get("topic", "")
        if topic:
            self._consumer.subscribe([topic])
        logger.info(f"Kafka connected: {self.config.get('bootstrap_servers')} topic={topic}")

    def disconnect(self):
        if self._consumer:
            self._consumer.close()
            self._consumer = None

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            topics = self._consumer.topics()
            return {"success": True,
                    "broker": self.config.get("bootstrap_servers"),
                    "available_topics": list(topics)[:10]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _deserialize_message(self, raw: bytes) -> Any:
        """Deserialize message value — JSON, Avro, or raw string."""
        import json
        fmt = self.config.get("message_format", "json")
        try:
            if fmt == "json":
                return json.loads(raw.decode("utf-8"))
            elif fmt == "avro":
                import fastavro
                return next(fastavro.reader(io.BytesIO(raw)))
            else:
                return {"raw": raw.decode("utf-8", errors="replace")}
        except Exception:
            return {"raw": raw.decode("utf-8", errors="replace")}

    def consume_batch(self, max_messages: int = 10000,
                      timeout_seconds: int = 30) -> List[Dict]:
        """Consume up to max_messages from the topic."""
        records = []
        deadline = time.time() + timeout_seconds
        for msg in self._consumer:
            val = self._deserialize_message(msg.value)
            if isinstance(val, dict):
                val["_kafka_offset"]    = msg.offset
                val["_kafka_partition"] = msg.partition
                val["_kafka_timestamp"] = msg.timestamp
                val["_kafka_topic"]     = msg.topic
            records.append(val)
            if len(records) >= max_messages or time.time() > deadline:
                break
        self._consumer.commit()
        return records

    def stream_to_s3(self, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1",
                     batch_size: int = 50_000,
                     run_seconds: int = 300) -> Dict:
        """
        Continuous streaming: consume → batch → Parquet → S3.
        Runs for run_seconds then stops (designed for scheduled micro-batch).
        """
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        s3 = boto3.client("s3", aws_access_key_id=aws_access_key,
                          aws_secret_access_key=aws_secret_key, region_name=aws_region)
        start = time.time(); total_rows = 0; file_count = 0
        buffer = []

        def flush():
            nonlocal total_rows, file_count, buffer
            if not buffer: return
            df = pd.json_normalize(buffer)
            for col in df.select_dtypes(include=["object"]).columns:
                df[col] = df[col].astype(str)
            buf = io.BytesIO()
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
            ts = int(time.time() * 1000)
            s3.put_object(Bucket=s3_bucket, Key=f"{s3_prefix}/{ts}.parquet", Body=buf.getvalue())
            total_rows += len(df); file_count += 1
            logger.info(f"Kafka batch flushed: {len(df):,} rows → s3://{s3_bucket}/{s3_prefix}/{ts}.parquet")
            buffer = []

        while time.time() - start < run_seconds:
            records = self.consume_batch(max_messages=batch_size, timeout_seconds=10)
            buffer.extend(records)
            if len(buffer) >= batch_size or (buffer and time.time() - start > run_seconds - 5):
                flush()

        flush()  # Final flush
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": total_rows, "files": file_count,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# AWS Kinesis → S3 → Snowflake
# ══════════════════════════════════════════════════════════════

class KinesisConnector:
    """
    AWS Kinesis Data Streams → S3 micro-batch connector.
    config: stream_name, region, shard_iterator_type (TRIM_HORIZON / LATEST)
    credentials: aws_access_key_id, aws_secret_access_key
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None

    def connect(self):
        import boto3
        self._client = boto3.client(
            "kinesis",
            region_name=self.config.get("region", "us-east-1"),
            aws_access_key_id=self.config.get("aws_access_key_id", ""),
            aws_secret_access_key=self.config.get("aws_secret_access_key", ""),
        )
        logger.info(f"Kinesis connected: {self.config.get('stream_name')}")

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            resp = self._client.describe_stream_summary(
                StreamName=self.config.get("stream_name", ""))
            summary = resp["StreamDescriptionSummary"]
            return {"success": True,
                    "stream_name": summary["StreamName"],
                    "stream_status": summary["StreamStatus"],
                    "shard_count": summary["OpenShardCount"]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_shards(self) -> List[str]:
        resp = self._client.list_shards(StreamName=self.config.get("stream_name", ""))
        return [s["ShardId"] for s in resp.get("Shards", [])]

    def consume_batch(self, max_records_per_shard: int = 10000) -> List[Dict]:
        import json
        stream = self.config.get("stream_name", "")
        iterator_type = self.config.get("shard_iterator_type", "TRIM_HORIZON")
        all_records = []
        for shard_id in self._get_shards():
            iter_resp = self._client.get_shard_iterator(
                StreamName=stream, ShardId=shard_id,
                ShardIteratorType=iterator_type)
            iterator = iter_resp["ShardIterator"]
            fetched = 0
            while fetched < max_records_per_shard:
                resp = self._client.get_records(ShardIterator=iterator, Limit=1000)
                for rec in resp.get("Records", []):
                    try:
                        data = json.loads(rec["Data"].decode("utf-8"))
                    except Exception:
                        data = {"raw": rec["Data"].decode("utf-8", errors="replace")}
                    data.update({"_kinesis_shard": shard_id,
                                 "_kinesis_seq": rec["SequenceNumber"],
                                 "_kinesis_ts": rec["ApproximateArrivalTimestamp"].isoformat()})
                    all_records.append(data)
                fetched += len(resp.get("Records", []))
                iterator = resp.get("NextShardIterator")
                if not iterator or not resp.get("Records"):
                    break
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
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str)

        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
        buf.seek(0)
        boto3.client("s3", aws_access_key_id=aws_access_key,
                     aws_secret_access_key=aws_secret_key,
                     region_name=aws_region).put_object(
            Bucket=s3_bucket,
            Key=f"{s3_prefix}/{int(time.time()*1000)}.parquet",
            Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}
