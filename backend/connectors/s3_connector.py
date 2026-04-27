"""
UMA Platform — S3 Connector + Flat File Connector
S3: direct reference for Snowflake COPY INTO, file listing, format detection
Flat File: CSV / Parquet / JSON / Avro / Excel → S3 → Snowflake
"""

import boto3
import logging
import time
import io
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger("uma.connectors.s3")


class S3Connector:
    """
    Amazon S3 connector.
    Primary use: staging area reference for Snowflake COPY INTO.
    Also supports: listing files, inferring schema from Parquet/CSV samples.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        config keys: bucket, region, prefix
        credentials keys: aws_access_key_id, aws_secret_access_key
                          OR iam_role (ARN — used in COPY INTO, not for boto3)
        """
        self.config = config
        self._s3 = None

    def connect(self):
        creds = self.config
        self._s3 = boto3.client(
            "s3",
            aws_access_key_id=creds.get("aws_access_key_id", ""),
            aws_secret_access_key=creds.get("aws_secret_access_key", ""),
            region_name=creds.get("region", "us-east-1"),
        )
        logger.info(f"S3 connected: bucket={self.config.get('bucket')}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        pass

    def test_connection(self) -> Dict[str, Any]:
        try:
            bucket = self.config.get("bucket", "")
            resp = self._s3.head_bucket(Bucket=bucket)
            # List a few objects to verify read access
            obj_resp = self._s3.list_objects_v2(Bucket=bucket, MaxKeys=5)
            return {
                "success": True,
                "bucket": bucket,
                "region": resp.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get("x-amz-bucket-region"),
                "sample_objects": [o["Key"] for o in obj_resp.get("Contents", [])],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_files(
        self,
        prefix: str = "",
        max_keys: int = 1000,
        extensions: Optional[List[str]] = None,
    ) -> List[Dict]:
        bucket = self.config.get("bucket", "")
        paginator = self._s3.get_paginator("list_objects_v2")
        files = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, PaginationConfig={"MaxItems": max_keys}):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if extensions:
                    if not any(key.lower().endswith(ext) for ext in extensions):
                        continue
                files.append({
                    "key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "etag": obj["ETag"].strip('"'),
                })
        return files

    def list_datasets(self, prefix: str = "") -> List[Dict]:
        """List logical 'tables' — top-level subdirectories under prefix."""
        result = self._s3.list_objects_v2(
            Bucket=self.config.get("bucket", ""),
            Prefix=prefix,
            Delimiter="/"
        )
        datasets = []
        for cp in result.get("CommonPrefixes", []):
            name = cp["Prefix"].rstrip("/").split("/")[-1]
            datasets.append({"name": name, "prefix": cp["Prefix"]})
        return datasets

    def infer_schema_from_parquet(self, key: str) -> List[Dict]:
        """Read Parquet file metadata to infer schema without downloading full file."""
        import pyarrow.parquet as pq
        obj = self._s3.get_object(Bucket=self.config.get("bucket", ""), Key=key)
        buf = io.BytesIO(obj["Body"].read())
        pf = pq.ParquetFile(buf)
        schema = pf.schema_arrow
        result = []
        for i, name in enumerate(schema.names):
            field = schema.field(name)
            result.append({
                "name": name,
                "type": str(field.type).upper(),
                "mode": "NULLABLE" if field.nullable else "REQUIRED",
            })
        return result

    def infer_schema_from_csv(self, key: str, sample_rows: int = 1000) -> List[Dict]:
        """Sample CSV to infer column types."""
        import pandas as pd
        obj = self._s3.get_object(Bucket=self.config.get("bucket", ""), Key=key)
        df = pd.read_csv(io.BytesIO(obj["Body"].read()), nrows=sample_rows)
        result = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            if "int" in dtype:    sf_type = "NUMBER(38,0)"
            elif "float" in dtype: sf_type = "FLOAT"
            elif "bool" in dtype:  sf_type = "BOOLEAN"
            elif "datetime" in dtype: sf_type = "TIMESTAMP_NTZ"
            else:                  sf_type = "VARCHAR(16777216)"
            result.append({"name": col, "type": dtype.upper(), "snowflake_type": sf_type, "mode": "NULLABLE"})
        return result

    def get_snowflake_s3_path(self, prefix: str = "") -> str:
        bucket = self.config.get("bucket", "")
        p = f"s3://{bucket}/{prefix}".rstrip("/") + "/"
        return p

    def put_object(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.config.get("bucket", ""), Key=key, Body=data)

    def get_object(self, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=self.config.get("bucket", ""), Key=key)
        return resp["Body"].read()


# ─── Flat File Connector ──────────────────────────────────────

logger_ff = logging.getLogger("uma.connectors.flatfile")


class FlatFileConnector:
    """
    Handles: CSV, Parquet, JSON, JSONL, Avro, Excel → S3 → Snowflake.
    Accepts file bytes directly (from upload) or local path.
    """

    SUPPORTED_FORMATS = {
        ".csv":     "csv",
        ".tsv":     "csv",
        ".parquet": "parquet",
        ".json":    "json",
        ".jsonl":   "json",
        ".ndjson":  "json",
        ".avro":    "avro",
        ".xlsx":    "excel",
        ".xls":     "excel",
    }

    @staticmethod
    def detect_format(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        return FlatFileConnector.SUPPORTED_FORMATS.get(ext, "unknown")

    @staticmethod
    def infer_schema(data: bytes, filename: str) -> List[Dict]:
        import pandas as pd
        fmt = FlatFileConnector.detect_format(filename)

        if fmt == "csv":
            df = pd.read_csv(io.BytesIO(data), nrows=5000)
        elif fmt == "parquet":
            import pyarrow.parquet as pq
            import pyarrow as pa
            table = pq.read_table(io.BytesIO(data))
            return [{"name": f.name, "type": str(f.type).upper(), "mode": "NULLABLE"} for f in table.schema]
        elif fmt == "json":
            df = pd.read_json(io.BytesIO(data), lines=True, nrows=5000)
        elif fmt == "excel":
            df = pd.read_excel(io.BytesIO(data), nrows=5000)
        else:
            return [{"name": "raw", "type": "VARIANT", "mode": "NULLABLE"}]

        result = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            if "int"      in dtype: sf = "NUMBER(38,0)"
            elif "float"  in dtype: sf = "FLOAT"
            elif "bool"   in dtype: sf = "BOOLEAN"
            elif "datetime" in dtype: sf = "TIMESTAMP_NTZ"
            else:                   sf = "VARCHAR(16777216)"
            result.append({"name": str(col), "type": dtype.upper(), "snowflake_type": sf, "mode": "NULLABLE"})
        return result

    @staticmethod
    def to_parquet(data: bytes, filename: str) -> bytes:
        """Convert any supported format to Parquet bytes."""
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq

        fmt = FlatFileConnector.detect_format(filename)

        if fmt == "csv":
            df = pd.read_csv(io.BytesIO(data))
        elif fmt == "parquet":
            return data  # Already parquet
        elif fmt == "json":
            try:
                df = pd.read_json(io.BytesIO(data), lines=True)
            except Exception:
                df = pd.read_json(io.BytesIO(data))
        elif fmt == "excel":
            df = pd.read_excel(io.BytesIO(data))
        elif fmt == "avro":
            import fastavro
            records = list(fastavro.reader(io.BytesIO(data)))
            df = pd.DataFrame(records)
        else:
            raise ValueError(f"Unsupported file format: {filename}")

        # Clean types
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str)

        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(df), buf, compression="snappy")
        return buf.getvalue()

    @staticmethod
    def upload_to_s3(
        data: bytes,
        filename: str,
        s3_bucket: str,
        s3_prefix: str,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
    ) -> Dict[str, Any]:
        """Convert file to Parquet and upload to S3."""
        import boto3

        parquet_data = FlatFileConnector.to_parquet(data, filename)
        stem = Path(filename).stem
        key = f"{s3_prefix}/{stem}.parquet"

        s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region,
        )
        s3.put_object(Bucket=s3_bucket, Key=key, Body=parquet_data)
        logger_ff.info(f"Flat file uploaded: s3://{s3_bucket}/{key} ({len(parquet_data)/1e3:.1f} KB)")

        return {
            "s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
            "key": key,
            "bytes": len(parquet_data),
            "files": 1,
        }
