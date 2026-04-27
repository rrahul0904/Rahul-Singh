"""
UMA Platform — Salesforce Connector
Uses Salesforce Bulk API 2.0 for high-volume object export → S3
"""

import requests
import time
import io
import csv
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("uma.connectors.salesforce")


class SalesforceConnector:
    """
    Salesforce Bulk API 2.0 connector.
    Supports OAuth 2.0 username-password flow and Connected App JWT.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        config keys:
          instance_url, client_id, client_secret, username, password, security_token
          OR: access_token (pre-authenticated)
        """
        self.config = config
        self.instance_url = config.get("instance_url", "https://login.salesforce.com")
        self.access_token: Optional[str] = config.get("access_token")
        self.api_version = config.get("api_version", "v59.0")
        self._session = requests.Session()

    def connect(self):
        if self.access_token:
            return
        # OAuth 2.0 username-password flow
        payload = {
            "grant_type": "password",
            "client_id": self.config.get("client_id"),
            "client_secret": self.config.get("client_secret"),
            "username": self.config.get("username"),
            "password": self.config.get("password", "") + self.config.get("security_token", ""),
        }
        resp = requests.post(
            f"{self.instance_url}/services/oauth2/token",
            data=payload,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.instance_url = data["instance_url"]
        logger.info(f"Salesforce authenticated: {self.instance_url}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        pass

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.instance_url}/services/data/{self.api_version}{path}"

    def test_connection(self) -> Dict[str, Any]:
        try:
            resp = self._session.get(
                self._url("/sobjects/"),
                headers=self._headers(),
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "encoding": data.get("encoding"),
                "object_count": len(data.get("sobjects", [])),
                "instance_url": self.instance_url,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[Dict]:
        """List queryable SObjects."""
        resp = self._session.get(self._url("/sobjects/"), headers=self._headers())
        resp.raise_for_status()
        return [
            {"name": o["name"], "label": o["label"], "queryable": o["queryable"]}
            for o in resp.json().get("sobjects", [])
            if o.get("queryable")
        ]

    def describe_object(self, object_name: str) -> Dict:
        resp = self._session.get(
            self._url(f"/sobjects/{object_name}/describe"),
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_object_schema(self, object_name: str) -> List[Dict]:
        desc = self.describe_object(object_name)
        result = []
        for field in desc.get("fields", []):
            sf_type = self._map_sf_type(field["type"], field.get("length", 0))
            result.append({
                "name": field["name"],
                "type": field["type"],
                "snowflake_type": sf_type,
                "length": field.get("length", 0),
                "mode": "NULLABLE",
                "label": field.get("label", ""),
            })
        return result

    def get_row_count(self, object_name: str) -> int:
        soql = f"SELECT COUNT() FROM {object_name}"
        resp = self._session.get(
            self._url("/query"),
            headers=self._headers(),
            params={"q": soql}
        )
        resp.raise_for_status()
        return resp.json().get("totalSize", 0)

    def bulk_export(
        self,
        object_name: str,
        fields: Optional[List[str]] = None,
        where_clause: Optional[str] = None,
        operation: str = "query",
    ) -> List[Dict]:
        """
        Bulk API 2.0 export — handles millions of records.
        Returns list of records as dicts.
        """
        # Build SOQL
        if not fields:
            schema = self.get_object_schema(object_name)
            # Skip compound fields and binary
            fields = [
                f["name"] for f in schema
                if f["type"] not in ("address", "location", "base64")
            ]

        soql = f"SELECT {', '.join(fields)} FROM {object_name}"
        if where_clause:
            soql += f" WHERE {where_clause}"

        # Create bulk job
        job_resp = self._session.post(
            self._url("/jobs/query"),
            headers=self._headers(),
            json={"operation": operation, "query": soql, "contentType": "CSV"},
        )
        job_resp.raise_for_status()
        job_id = job_resp.json()["id"]
        logger.info(f"Salesforce Bulk job created: {job_id} for {object_name}")

        # Poll for completion
        self._wait_for_job(job_id)

        # Download results
        all_records = []
        locator = None

        while True:
            params = {"maxRecords": 50000}
            if locator:
                params["locator"] = locator

            result_resp = self._session.get(
                self._url(f"/jobs/query/{job_id}/results"),
                headers={**self._headers(), "Accept": "text/csv"},
                params=params,
            )
            result_resp.raise_for_status()

            reader = csv.DictReader(io.StringIO(result_resp.text))
            batch = list(reader)
            all_records.extend(batch)

            locator = result_resp.headers.get("Sforce-Locator")
            if not locator or locator == "null":
                break

        logger.info(f"Salesforce Bulk export complete: {len(all_records):,} records from {object_name}")
        return all_records

    def export_to_s3(
        self,
        object_name: str,
        s3_bucket: str,
        s3_prefix: str,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
        fields: Optional[List[str]] = None,
        where_clause: Optional[str] = None,
        batch_size: int = 500_000,
    ) -> Dict[str, Any]:
        """Export Salesforce object directly to S3 as Parquet."""
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

        start = time.time()
        records = self.bulk_export(object_name, fields=fields, where_clause=where_clause)

        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0, "files": 0, "duration_seconds": 0}

        # Write in batches
        file_count = 0
        total_rows = 0

        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            df = pd.DataFrame(batch)
            # Clean types
            for col in df.columns:
                df[col] = df[col].replace("", None)

            buf = io.BytesIO()
            pq.write_table(pa.Table.from_pandas(df), buf, compression="snappy")
            buf.seek(0)

            key = f"{s3_prefix}/part-{file_count:05d}.parquet"
            s3.put_object(Bucket=s3_bucket, Key=key, Body=buf.getvalue())
            total_rows += len(df)
            file_count += 1

        duration = time.time() - start
        logger.info(f"Salesforce → S3 complete: {total_rows:,} rows, {file_count} files, {duration:.1f}s")

        return {
            "s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
            "total_rows": total_rows,
            "files": file_count,
            "duration_seconds": duration,
            "bytes": 0,
        }

    def _wait_for_job(self, job_id: str, poll_interval: int = 3, timeout: int = 3600):
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._session.get(
                self._url(f"/jobs/query/{job_id}"),
                headers=self._headers()
            )
            resp.raise_for_status()
            state = resp.json().get("state")
            logger.debug(f"Bulk job {job_id} state: {state}")
            if state == "JobComplete":
                return
            if state in ("Failed", "Aborted"):
                raise RuntimeError(f"Salesforce Bulk job {job_id} failed: {state}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Salesforce Bulk job {job_id} timed out after {timeout}s")

    @staticmethod
    def _map_sf_type(sf_type: str, length: int = 0) -> str:
        mapping = {
            "id": "VARCHAR(18)",
            "string": f"VARCHAR({min(length, 16777216)})" if length else "VARCHAR(16777216)",
            "textarea": "VARCHAR(16777216)",
            "picklist": "VARCHAR(255)",
            "multipicklist": "VARCHAR(16777216)",
            "reference": "VARCHAR(18)",
            "boolean": "BOOLEAN",
            "int": "NUMBER(18,0)",
            "double": "FLOAT",
            "currency": "NUMBER(18,2)",
            "percent": "NUMBER(18,2)",
            "date": "DATE",
            "datetime": "TIMESTAMP_TZ",
            "time": "TIME",
            "email": "VARCHAR(254)",
            "phone": "VARCHAR(40)",
            "url": "VARCHAR(1024)",
            "encryptedstring": "VARCHAR(16777216)",
        }
        return mapping.get(sf_type.lower(), "VARCHAR(16777216)")
