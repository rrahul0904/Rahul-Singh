"""
UMA Platform — Storage & API Connectors
GCS · SFTP · Generic REST/GraphQL
"""

import logging, time, io
from typing import Dict, List, Any, Optional

logger = logging.getLogger("uma.connectors.storage")


# ══════════════════════════════════════════════════════════════
# Google Cloud Storage
# ══════════════════════════════════════════════════════════════

class GCSConnector:
    """
    Google Cloud Storage connector.
    config: bucket, prefix, service_account_json
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None
        self._bucket = None

    def connect(self):
        from google.cloud import storage
        from google.oauth2 import service_account
        import json

        sa_json = self.config.get("service_account_json", "")
        if sa_json:
            sa_info = json.loads(sa_json) if isinstance(sa_json, str) else sa_json
            creds = service_account.Credentials.from_service_account_info(sa_info)
            self._client = storage.Client(credentials=creds, project=sa_info.get("project_id"))
        else:
            self._client = storage.Client()  # Uses ADC

        bucket_name = self.config.get("bucket", "")
        self._bucket = self._client.bucket(bucket_name)
        logger.info(f"GCS connected: gs://{bucket_name}")

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            blobs = list(self._bucket.list_blobs(max_results=3))
            return {"success": True, "bucket": self.config.get("bucket"),
                    "sample_objects": [b.name for b in blobs]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_blobs(self, prefix: str = "", max_results: int = 1000) -> List[Dict]:
        blobs = self._bucket.list_blobs(prefix=prefix, max_results=max_results)
        return [{"name": b.name, "size": b.size,
                 "updated": b.updated.isoformat() if b.updated else None,
                 "content_type": b.content_type}
                for b in blobs]

    def list_datasets(self, prefix: str = "") -> List[Dict]:
        """Top-level 'directories' under prefix = logical datasets."""
        seen = set()
        datasets = []
        for b in self._bucket.list_blobs(prefix=prefix, delimiter="/"):
            pass
        for prefix_result in self._bucket.list_blobs(prefix=prefix, delimiter="/").__iter__():
            pass
        # Use list_blobs with delimiter to get common prefixes
        iterator = self._bucket.list_blobs(prefix=prefix, delimiter="/")
        list(iterator)  # exhaust iterator to populate prefixes
        for p in iterator.prefixes:
            name = p.rstrip("/").split("/")[-1]
            if name not in seen:
                seen.add(name)
                datasets.append({"name": name, "prefix": p})
        return datasets

    def infer_schema_from_parquet(self, blob_name: str) -> List[Dict]:
        import pyarrow.parquet as pq
        blob = self._bucket.blob(blob_name)
        data = blob.download_as_bytes()
        pf = pq.ParquetFile(io.BytesIO(data))
        schema = pf.schema_arrow
        return [{"name": schema.names[i], "type": str(schema.field(schema.names[i]).type).upper(),
                 "mode": "NULLABLE" if schema.field(schema.names[i]).nullable else "REQUIRED"}
                for i in range(len(schema.names))]

    def get_snowflake_gcs_path(self, prefix: str = "") -> str:
        bucket = self.config.get("bucket", "")
        return f"gcs://{bucket}/{prefix}".rstrip("/") + "/"

    def download_blob(self, blob_name: str) -> bytes:
        return self._bucket.blob(blob_name).download_as_bytes()

    def upload_blob(self, blob_name: str, data: bytes, content_type: str = "application/octet-stream"):
        blob = self._bucket.blob(blob_name)
        blob.upload_from_string(data, content_type=content_type)

    def copy_to_s3(self, source_prefix: str, s3_bucket: str, s3_prefix: str,
                   aws_access_key: str, aws_secret_key: str, aws_region: str = "us-east-1",
                   max_files: int = 10_000) -> Dict:
        """Copy GCS blobs → S3 for Snowflake S3-based COPY INTO."""
        import boto3
        s3 = boto3.client("s3", aws_access_key_id=aws_access_key,
                          aws_secret_access_key=aws_secret_key, region_name=aws_region)
        blobs = self.list_blobs(source_prefix, max_results=max_files)
        start = time.time(); total_bytes = 0; count = 0
        for blob_meta in blobs:
            data = self.download_blob(blob_meta["name"])
            rel = blob_meta["name"][len(source_prefix):].lstrip("/")
            s3.put_object(Bucket=s3_bucket, Key=f"{s3_prefix}/{rel}", Body=data)
            total_bytes += len(data); count += 1
        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "files": count, "bytes": total_bytes,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# SFTP
# ══════════════════════════════════════════════════════════════

class SFTPConnector:
    """
    SFTP connector — downloads files to S3 for Snowflake ingestion.
    config: host, port, username, password (or private_key), remote_path
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None
        self._sftp = None

    def connect(self):
        import paramiko
        transport = paramiko.Transport((
            self.config.get("host"),
            int(self.config.get("port", 22))
        ))

        private_key_str = self.config.get("private_key", "")
        if private_key_str:
            import io as _io
            pkey = paramiko.RSAKey.from_private_key(_io.StringIO(private_key_str))
            transport.connect(username=self.config.get("username"), pkey=pkey)
        else:
            transport.connect(username=self.config.get("username"),
                              password=self.config.get("password", ""))

        self._client = transport
        self._sftp = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP connected: {self.config.get('host')}")

    def disconnect(self):
        if self._sftp: self._sftp.close()
        if self._client: self._client.close()

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): self.disconnect()

    def test_connection(self) -> Dict:
        try:
            remote_path = self.config.get("remote_path", "/")
            files = self._sftp.listdir(remote_path)
            return {"success": True, "host": self.config.get("host"),
                    "remote_path": remote_path, "file_count": len(files)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_files(self, remote_path: str = "") -> List[Dict]:
        path = remote_path or self.config.get("remote_path", "/")
        files = []
        for attr in self._sftp.listdir_attr(path):
            files.append({"name": attr.filename,
                          "path": f"{path}/{attr.filename}",
                          "size": attr.st_size,
                          "modified": attr.st_mtime})
        return files

    def download_to_s3(self, remote_path: str, s3_bucket: str, s3_prefix: str,
                       aws_access_key: str, aws_secret_key: str,
                       aws_region: str = "us-east-1") -> Dict:
        """Download SFTP files → convert to Parquet → upload to S3."""
        import boto3
        from connectors.s3_connector import FlatFileConnector

        s3 = boto3.client("s3", aws_access_key_id=aws_access_key,
                          aws_secret_access_key=aws_secret_key, region_name=aws_region)
        files = self.list_files(remote_path)
        start = time.time(); total_bytes = 0; count = 0

        for f in files:
            try:
                buf = io.BytesIO()
                self._sftp.getfo(f["path"], buf)
                raw_data = buf.getvalue()

                # Convert to Parquet
                try:
                    parquet_data = FlatFileConnector.to_parquet(raw_data, f["name"])
                    ext = "parquet"
                except Exception:
                    parquet_data = raw_data
                    ext = f["name"].split(".")[-1]

                key = f"{s3_prefix}/{f['name'].rsplit('.', 1)[0]}.{ext}"
                s3.put_object(Bucket=s3_bucket, Key=key, Body=parquet_data)
                total_bytes += len(parquet_data); count += 1
                logger.info(f"SFTP→S3: {f['name']} ({len(parquet_data)/1e3:.0f} KB)")
            except Exception as e:
                logger.error(f"Failed to download {f['name']}: {e}")

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "files": count, "bytes": total_bytes,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Generic REST / GraphQL API Connector
# ══════════════════════════════════════════════════════════════

class RESTConnector:
    """
    Generic REST/GraphQL API connector.
    Supports: pagination (offset/cursor/link-header), auth (Bearer/API Key/Basic/OAuth2),
              response normalization to tabular format.
    config: base_url, auth_type, headers, pagination_type, data_path
    credentials: api_key, bearer_token, username, password,
                 oauth_token_url, oauth_client_id, oauth_client_secret
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None
        self._access_token: Optional[str] = None

    def connect(self):
        import requests
        self._session = requests.Session()
        auth_type = self.config.get("auth_type", "bearer")

        if auth_type == "bearer":
            token = self.config.get("bearer_token", "")
            self._session.headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "api_key":
            key_header = self.config.get("api_key_header", "X-API-Key")
            self._session.headers[key_header] = self.config.get("api_key", "")

        elif auth_type == "basic":
            from requests.auth import HTTPBasicAuth
            self._session.auth = HTTPBasicAuth(
                self.config.get("username", ""), self.config.get("password", ""))

        elif auth_type == "oauth2":
            self._refresh_oauth2_token()

        # Custom headers
        for k, v in self.config.get("headers", {}).items():
            self._session.headers[k] = v

        logger.info(f"REST connected: {self.config.get('base_url')}")

    def _refresh_oauth2_token(self):
        import requests
        resp = requests.post(self.config["oauth_token_url"], data={
            "grant_type": "client_credentials",
            "client_id": self.config.get("oauth_client_id"),
            "client_secret": self.config.get("oauth_client_secret"),
        })
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]
        self._session.headers["Authorization"] = f"Bearer {self._access_token}"

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            test_url = self.config.get("test_url", self.config.get("base_url", ""))
            resp = self._session.get(test_url, timeout=10)
            return {"success": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "url": test_url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def fetch_all(self, endpoint: str, params: Optional[Dict] = None,
                  data_path: Optional[str] = None,
                  max_pages: int = 1000) -> List[Dict]:
        """
        Fetch all records from a paginated endpoint.
        Handles: offset pagination, cursor pagination, Link-header pagination.
        """
        import requests

        base_url = self.config.get("base_url", "").rstrip("/")
        url = f"{base_url}/{endpoint.lstrip('/')}"
        data_path = data_path or self.config.get("data_path", "")
        pagination = self.config.get("pagination_type", "offset")
        page_size = self.config.get("page_size", 100)
        all_records = []
        p = {**(params or {})}

        for page_num in range(max_pages):
            if pagination == "offset":
                p["offset"] = page_num * page_size
                p["limit"] = page_size
            elif pagination == "page":
                p["page"] = page_num + 1
                p["per_page"] = page_size

            resp = self._session.get(url, params=p, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Navigate to data path
            records = data
            if data_path:
                for key in data_path.split("."):
                    if isinstance(records, dict):
                        records = records.get(key, [])
                    else:
                        break

            if not isinstance(records, list):
                records = [records] if records else []

            if not records:
                break

            all_records.extend(records)

            # Cursor pagination
            if pagination == "cursor":
                cursor_path = self.config.get("cursor_path", "next_cursor")
                cursor = data.get(cursor_path)
                if not cursor:
                    break
                p["cursor"] = cursor

            # Link header pagination
            elif pagination == "link":
                link_header = resp.headers.get("Link", "")
                if 'rel="next"' not in link_header:
                    break
                # Parse next URL from Link header
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip().strip("<>")
                        p = {}
                        break

            # Stop if fewer results than page size
            elif len(records) < page_size:
                break

        logger.info(f"REST fetch complete: {len(all_records)} records from {endpoint}")
        return all_records

    def graphql_query(self, query: str, variables: Optional[Dict] = None,
                      data_path: Optional[str] = None) -> List[Dict]:
        """Execute a GraphQL query with optional pagination via cursor."""
        base_url = self.config.get("base_url", "").rstrip("/")
        endpoint = self.config.get("graphql_endpoint", "/graphql")
        url = f"{base_url}{endpoint}"

        resp = self._session.post(url, json={
            "query": query,
            "variables": variables or {}
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        if data_path:
            for key in data_path.split("."):
                data = data.get(key, {})

        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "edges" in data:
            return [e.get("node", e) for e in data["edges"]]
        elif isinstance(data, dict) and "nodes" in data:
            return data["nodes"]
        return [data] if data else []

    def export_to_s3(self, endpoint: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1",
                     params: Optional[Dict] = None,
                     data_path: Optional[str] = None) -> Dict:
        import pandas as pd
        import boto3

        records = self.fetch_all(endpoint, params=params, data_path=data_path)
        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0,
                    "files": 0, "duration_seconds": 0}

        start = time.time()
        df = pd.json_normalize(records)
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str)

        import pyarrow as pa, pyarrow.parquet as pq
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
        buf.seek(0)

        boto3.client("s3", aws_access_key_id=aws_access_key,
                     aws_secret_access_key=aws_secret_key,
                     region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}
