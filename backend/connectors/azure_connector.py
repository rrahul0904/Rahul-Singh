"""
UMA Platform — Azure Blob Storage / ADLS Gen2 Connector
Handles: connection testing, file listing, download → reupload to Snowflake staging,
         direct ADLS → Snowflake COPY via SAS token
"""

from azure.storage.blob import BlobServiceClient, generate_container_sas, ContainerSasPermissions
from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging
import time
import io

logger = logging.getLogger("uma.connectors.azure")


class AzureConnector:
    """
    Supports both:
    - Azure Blob Storage (standard containers)
    - ADLS Gen2 (hierarchical namespace)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        config keys:
          account_name, account_key (or sas_token or connection_string)
          container_name, prefix (optional)
          adls_gen2: bool (default False)
        """
        self.config = config
        self._client: Optional[BlobServiceClient] = None

    def connect(self):
        account_name = self.config.get("account_name", "")
        account_key  = self.config.get("account_key", "")
        sas_token    = self.config.get("sas_token", "")
        conn_str     = self.config.get("connection_string", "")

        if conn_str:
            self._client = BlobServiceClient.from_connection_string(conn_str)
        elif sas_token:
            url = f"https://{account_name}.blob.core.windows.net/?{sas_token}"
            self._client = BlobServiceClient(account_url=url)
        elif account_key:
            url = f"https://{account_name}.blob.core.windows.net"
            self._client = BlobServiceClient(account_url=url, credential=account_key)
        else:
            raise ValueError("Azure: provide account_key, sas_token, or connection_string")

        logger.info(f"Azure Blob connected: {account_name}")

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def test_connection(self) -> Dict[str, Any]:
        try:
            containers = list(self._client.list_containers(max_results=5))
            return {
                "success": True,
                "account": self.config.get("account_name"),
                "containers": [c["name"] for c in containers],
            }
        except ClientAuthenticationError as e:
            return {"success": False, "error": f"Authentication failed: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_blobs(self, container: str, prefix: str = "", max_results: int = 1000) -> List[Dict]:
        container_client = self._client.get_container_client(container)
        blobs = []
        for blob in container_client.list_blobs(name_starts_with=prefix, max_results=max_results):
            blobs.append({
                "name": blob.name,
                "size": blob.size,
                "last_modified": blob.last_modified.isoformat() if blob.last_modified else None,
                "content_type": blob.content_settings.content_type if blob.content_settings else None,
            })
        return blobs

    def generate_sas_token(
        self,
        container: str,
        expiry_hours: int = 24,
    ) -> str:
        """Generate a read-only SAS token for a container (for Snowflake COPY INTO)."""
        account_name = self.config.get("account_name", "")
        account_key  = self.config.get("account_key", "")

        sas = generate_container_sas(
            account_name=account_name,
            container_name=container,
            account_key=account_key,
            permission=ContainerSasPermissions(read=True, list=True),
            expiry=datetime.utcnow() + timedelta(hours=expiry_hours),
        )
        return sas

    def get_snowflake_azure_path(self, container: str, prefix: str = "") -> str:
        """Return azure:// path format for Snowflake COPY INTO."""
        account = self.config.get("account_name", "")
        path = f"azure://{account}.blob.core.windows.net/{container}/{prefix}"
        return path.rstrip("/") + "/"

    def list_datasets(self, container: str, prefix: str = "") -> List[Dict]:
        """
        Treat top-level 'directories' under prefix as datasets.
        Each subdirectory = one table/dataset.
        """
        blobs = self.list_blobs(container, prefix)
        seen = set()
        datasets = []
        for blob in blobs:
            # Extract first path component after prefix
            rel = blob["name"][len(prefix):].lstrip("/")
            parts = rel.split("/")
            if len(parts) > 0 and parts[0]:
                ds = parts[0]
                if ds not in seen:
                    seen.add(ds)
                    # Infer format from files
                    ext = "unknown"
                    if len(parts) > 1:
                        fname = parts[-1]
                        for e in ["parquet", "csv", "json", "avro"]:
                            if e in fname.lower():
                                ext = e
                                break
                    datasets.append({"name": ds, "format": ext})
        return datasets

    def download_to_s3(
        self,
        source_container: str,
        source_prefix: str,
        s3_bucket: str,
        s3_prefix: str,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
        max_files: int = 10_000,
    ) -> Dict[str, Any]:
        """
        Pipe blobs from Azure → S3.
        Used when Snowflake target uses S3 staging.
        """
        import boto3
        s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region,
        )

        blobs = self.list_blobs(source_container, source_prefix, max_results=max_files)
        container_client = self._client.get_container_client(source_container)

        start = time.time()
        total_bytes = 0
        count = 0

        for blob in blobs:
            blob_client = container_client.get_blob_client(blob["name"])
            data = blob_client.download_blob().readall()
            rel_path = blob["name"][len(source_prefix):].lstrip("/")
            s3_key = f"{s3_prefix}/{rel_path}"
            s3.put_object(Bucket=s3_bucket, Key=s3_key, Body=data)
            total_bytes += len(data)
            count += 1
            if count % 100 == 0:
                logger.info(f"  Azure→S3: {count}/{len(blobs)} files copied")

        duration = time.time() - start
        logger.info(f"Azure→S3 complete: {count} files, {total_bytes/1e6:.1f} MB, {duration:.1f}s")
        return {
            "s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
            "files": count,
            "bytes": total_bytes,
            "duration_seconds": duration,
        }
