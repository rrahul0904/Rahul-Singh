"""
UMA Platform — BigQuery Connector
Handles: connection testing, schema introspection, export to GCS / S3
"""

from google.cloud import bigquery
from google.cloud.bigquery import Client, QueryJobConfig
from google.oauth2 import service_account
from typing import Dict, List, Any, Optional
import json
import logging
import time

logger = logging.getLogger("uma.connectors.bigquery")


class BigQueryConnector:
    def __init__(self, config: Dict[str, Any]):
        """
        config keys:
          service_account_json: str (full JSON key content)
          project_id: str (optional — inferred from key if not set)
        """
        self.config = config
        self._client: Optional[Client] = None

    def connect(self):
        sa_json = self.config.get("service_account_json", "")
        if isinstance(sa_json, str):
            sa_info = json.loads(sa_json)
        else:
            sa_info = sa_json

        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/bigquery"]
        )
        project = self.config.get("project_id") or sa_info.get("project_id")
        self._client = Client(project=project, credentials=credentials)
        logger.info(f"BigQuery connected: project={project}")

    def disconnect(self):
        if self._client:
            self._client.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def test_connection(self) -> Dict[str, Any]:
        try:
            datasets = list(self._client.list_datasets(max_results=1))
            return {"success": True, "project": self._client.project}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_datasets(self) -> List[str]:
        return [d.dataset_id for d in self._client.list_datasets()]

    def list_tables(self, dataset_id: str) -> List[Dict]:
        tables = []
        for tbl in self._client.list_tables(dataset_id):
            tables.append({"dataset": dataset_id, "table": tbl.table_id, "type": tbl.table_type})
        return tables

    def get_table_schema(self, dataset_id: str, table_id: str) -> List[Dict]:
        """Return column definitions including type, mode, description."""
        ref = self._client.dataset(dataset_id).table(table_id)
        tbl = self._client.get_table(ref)
        result = []
        for field in tbl.schema:
            result.append({
                "name": field.name,
                "type": field.field_type,
                "mode": field.mode,
                "description": field.description or "",
            })
        return result

    def get_row_count(self, dataset_id: str, table_id: str) -> int:
        query = f"SELECT COUNT(*) AS cnt FROM `{self._client.project}.{dataset_id}.{table_id}`"
        result = list(self._client.query(query).result())
        return result[0]["cnt"]

    def export_to_gcs(
        self,
        dataset_id: str,
        table_id: str,
        gcs_uri: str,
        file_format: str = "PARQUET",
        compression: str = "SNAPPY",
    ) -> Dict[str, Any]:
        """Export a BigQuery table to GCS as Parquet/CSV/JSON."""
        ref = self._client.dataset(dataset_id).table(table_id)
        job_config = bigquery.ExtractJobConfig(
            destination_format=getattr(bigquery.DestinationFormat, file_format, bigquery.DestinationFormat.PARQUET),
            compression=getattr(bigquery.Compression, compression, bigquery.Compression.SNAPPY),
            print_header=(file_format == "CSV"),
        )
        start = time.time()
        job = self._client.extract_table(ref, gcs_uri, job_config=job_config)
        job.result()  # Wait for completion
        duration = time.time() - start

        logger.info(f"BQ export complete: {dataset_id}.{table_id} → {gcs_uri} ({duration:.1f}s)")
        return {
            "gcs_uri": gcs_uri,
            "duration_seconds": duration,
            "job_id": job.job_id,
        }

    def run_query(self, sql: str) -> List[Dict]:
        rows = list(self._client.query(sql).result())
        return [dict(r) for r in rows]
