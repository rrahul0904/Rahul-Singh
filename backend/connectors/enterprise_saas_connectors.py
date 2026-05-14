"""
UMA Platform — Enterprise SaaS Connectors
NetSuite · Workday · ServiceNow · Marketo · Shopify · Google Analytics 4
"""

import logging
import time
import io
import base64
from typing import Dict, List, Any, Optional

logger = logging.getLogger("uma.connectors.enterprise_saas")


# ══════════════════════════════════════════════════════════════
# NetSuite (SuiteQL REST API)
# ══════════════════════════════════════════════════════════════

class NetSuiteConnector:
    """
    NetSuite SuiteQL REST connector using OAuth 2.0 token-based auth.
    config: account_id, consumer_key, consumer_secret, token_id, token_secret
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None

    def _oauth_header(self, method: str, url: str) -> str:
        """Build OAuth 1.0a header for NetSuite (they still use this for SuiteQL)."""
        import secrets, hmac, hashlib, urllib.parse, time as _t
        account_id   = self.config.get("account_id", "").replace("_", "-").lower()
        consumer_key = self.config.get("consumer_key", "")
        token_id     = self.config.get("token_id", "")
        nonce        = secrets.token_hex(16)
        timestamp    = str(int(_t.time()))

        params = {
            "oauth_consumer_key":     consumer_key,
            "oauth_token":            token_id,
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp":        timestamp,
            "oauth_nonce":            nonce,
            "oauth_version":          "1.0",
        }
        # Base string
        param_str = "&".join(f"{k}={urllib.parse.quote(v, safe='')}"
                             for k, v in sorted(params.items()))
        base = "&".join([method, urllib.parse.quote(url, safe=""),
                          urllib.parse.quote(param_str, safe="")])
        # Signing key
        key = (urllib.parse.quote(self.config.get("consumer_secret",""), safe="") + "&" +
               urllib.parse.quote(self.config.get("token_secret",""), safe=""))
        sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha256).digest()).decode()
        params["oauth_signature"] = sig

        realm = self.config.get("account_id", "").replace("-", "_").upper()
        return ('OAuth realm="' + realm + '",' +
                ",".join(f'{k}="{urllib.parse.quote(v, safe="")}"'
                          for k, v in params.items()))

    def connect(self):
        import requests
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json",
                                       "Prefer": "transient"})

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    @property
    def _base_url(self) -> str:
        account = self.config.get("account_id", "").replace("_", "-").lower()
        return f"https://{account}.suitetalk.api.netsuite.com/services/rest"

    def test_connection(self) -> Dict:
        try:
            url = f"{self._base_url}/query/v1/suiteql"
            resp = self._session.post(
                url, json={"q": "SELECT 1"},
                headers={"Authorization": self._oauth_header("POST", url)},
                timeout=15)
            return {"success": resp.ok, "status": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]:
        return []

    def fetch_records(self, object_name: str, limit: int = 1000) -> List[Dict]:
        url = f"{self._base_url}/query/v1/suiteql"
        all_records = []
        offset = 0
        while True:
            sql = f"SELECT * FROM {object_name} ORDER BY id OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
            resp = self._session.post(
                url, json={"q": sql},
                headers={"Authorization": self._oauth_header("POST", url)},
                timeout=60)
            if not resp.ok:
                logger.error(f"NetSuite error: {resp.status_code} {resp.text[:200]}")
                break
            data = resp.json()
            items = data.get("items", [])
            if not items: break
            all_records.extend(items)
            if not data.get("hasMore"): break
            offset += limit
        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_records(object_name)
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
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Workday (REST API / RaaS)
# ══════════════════════════════════════════════════════════════

class WorkdayConnector:
    """
    Workday REST API connector — uses Report-as-a-Service or REST v1.
    config: tenant, host, client_id, client_secret, refresh_token
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None
        self._access_token = None

    def connect(self):
        import requests
        tenant = self.config.get("tenant", "")
        host   = self.config.get("host", "wd5-impl-services1.workday.com")
        token_url = f"https://{host}/ccx/oauth2/{tenant}/token"

        resp = requests.post(token_url, data={
            "grant_type":    "refresh_token",
            "refresh_token": self.config.get("refresh_token", ""),
            "client_id":     self.config.get("client_id", ""),
            "client_secret": self.config.get("client_secret", ""),
        }, timeout=30)
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]

        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self._access_token}"
        logger.info(f"Workday connected: tenant={tenant}")

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            tenant = self.config.get("tenant", "")
            host   = self.config.get("host", "")
            url = f"https://{host}/ccx/api/v1/{tenant}/workers"
            resp = self._session.get(url, params={"limit": 1}, timeout=15)
            return {"success": resp.ok, "tenant": tenant, "status": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]:
        return ["workers", "organizations", "jobProfiles", "positions", "supervisoryOrganizations"]

    def fetch_records(self, object_name: str, report_name: Optional[str] = None) -> List[Dict]:
        tenant = self.config.get("tenant", "")
        host   = self.config.get("host", "")
        all_records = []

        if report_name:
            # RaaS: fetch a configured report
            url = f"https://{host}/ccx/service/customreport2/{tenant}/{report_name}?format=json"
            resp = self._session.get(url, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("Report_Entry", [])

        # REST API v1 — paginated
        url = f"https://{host}/ccx/api/v1/{tenant}/{object_name}"
        offset = 0; limit = 100
        while True:
            resp = self._session.get(url, params={"limit": limit, "offset": offset}, timeout=60)
            if not resp.ok: break
            data = resp.json()
            items = data.get("data", [])
            if not items: break
            all_records.extend(items)
            if data.get("total", 0) <= offset + limit: break
            offset += limit
        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_records(object_name)
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
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# ServiceNow (Table API)
# ══════════════════════════════════════════════════════════════

class ServiceNowConnector:
    """
    ServiceNow Table API connector.
    config: instance (e.g. dev12345), username, password
    OR:    instance, oauth_client_id, oauth_client_secret, refresh_token
    """

    DEFAULT_TABLES = ["incident", "change_request", "problem", "sys_user",
                      "sys_user_group", "cmdb_ci", "task", "kb_knowledge"]

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None

    def connect(self):
        import requests
        self._session = requests.Session()
        if self.config.get("oauth_client_id"):
            self._oauth_login()
        else:
            self._session.auth = (self.config.get("username", ""),
                                   self.config.get("password", ""))
        self._session.headers["Accept"] = "application/json"

    def _oauth_login(self):
        import requests
        instance = self.config.get("instance", "")
        resp = requests.post(
            f"https://{instance}.service-now.com/oauth_token.do",
            data={
                "grant_type":    "refresh_token",
                "client_id":     self.config.get("oauth_client_id"),
                "client_secret": self.config.get("oauth_client_secret"),
                "refresh_token": self.config.get("refresh_token"),
            }, timeout=30)
        resp.raise_for_status()
        self._session.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    @property
    def _base_url(self) -> str:
        return f"https://{self.config.get('instance','')}.service-now.com/api/now"

    def test_connection(self) -> Dict:
        try:
            resp = self._session.get(f"{self._base_url}/table/sys_user?sysparm_limit=1", timeout=15)
            return {"success": resp.ok, "instance": self.config.get("instance"),
                    "status": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]:
        return self.DEFAULT_TABLES

    def fetch_records(self, table: str, query: str = "",
                       fields: Optional[List[str]] = None) -> List[Dict]:
        all_records = []; offset = 0; limit = 1000
        while True:
            params = {"sysparm_limit": limit, "sysparm_offset": offset}
            if query: params["sysparm_query"] = query
            if fields: params["sysparm_fields"] = ",".join(fields)
            resp = self._session.get(f"{self._base_url}/table/{table}",
                                      params=params, timeout=60)
            if not resp.ok: break
            result = resp.json().get("result", [])
            if not result: break
            all_records.extend(result)
            if len(result) < limit: break
            offset += limit
        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_records(object_name)
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
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Marketo (REST API)
# ══════════════════════════════════════════════════════════════

class MarketoConnector:
    """
    Marketo REST API connector.
    config: endpoint (munchkin id-based URL), client_id, client_secret
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None
        self._access_token = None
        self._expires_at = 0

    def connect(self):
        import requests
        self._session = requests.Session()
        self._refresh_token()

    def _refresh_token(self):
        import requests
        endpoint = self.config.get("endpoint", "").rstrip("/")
        resp = requests.get(
            f"{endpoint}/identity/oauth/token",
            params={
                "grant_type":    "client_credentials",
                "client_id":     self.config.get("client_id"),
                "client_secret": self.config.get("client_secret"),
            }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at   = time.time() + data.get("expires_in", 3600) - 60
        self._session.headers["Authorization"] = f"Bearer {self._access_token}"

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            endpoint = self.config.get("endpoint", "").rstrip("/")
            resp = self._session.get(f"{endpoint}/rest/v1/stats/usage.json", timeout=15)
            return {"success": resp.ok, "endpoint": endpoint}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]:
        return ["leads", "companies", "opportunities", "programs", "campaigns", "lists"]

    def fetch_records(self, object_name: str) -> List[Dict]:
        endpoint = self.config.get("endpoint", "").rstrip("/")
        all_records = []; next_page_token = None

        # Different objects use different endpoints
        paths = {
            "leads":         "/rest/v1/leads.json",
            "companies":     "/rest/v1/companies.json",
            "opportunities": "/rest/v1/opportunities.json",
            "programs":      "/rest/asset/v1/programs.json",
            "campaigns":     "/rest/v1/campaigns.json",
            "lists":         "/rest/v1/lists.json",
        }
        path = paths.get(object_name, f"/rest/v1/{object_name}.json")

        while True:
            if time.time() > self._expires_at: self._refresh_token()
            params = {"batchSize": 300}
            if next_page_token: params["nextPageToken"] = next_page_token

            resp = self._session.get(f"{endpoint}{path}", params=params, timeout=60)
            if not resp.ok: break
            data = resp.json()
            records = data.get("result", [])
            if not records: break
            all_records.extend(records)
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not data.get("moreResult"): break
        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_records(object_name)
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
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Shopify (Admin REST API)
# ══════════════════════════════════════════════════════════════

class ShopifyConnector:
    """
    Shopify Admin API connector.
    config: shop_domain (e.g. mystore.myshopify.com), access_token, api_version
    """

    DEFAULT_OBJECTS = ["orders", "products", "customers", "collections",
                       "inventory_levels", "fulfillments", "transactions",
                       "discount_codes", "price_rules", "abandoned_checkouts"]

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None

    def connect(self):
        import requests
        self._session = requests.Session()
        self._session.headers.update({
            "X-Shopify-Access-Token": self.config.get("access_token", ""),
            "Content-Type": "application/json",
        })

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    @property
    def _base_url(self) -> str:
        shop    = self.config.get("shop_domain", "")
        version = self.config.get("api_version", "2024-10")
        return f"https://{shop}/admin/api/{version}"

    def test_connection(self) -> Dict:
        try:
            resp = self._session.get(f"{self._base_url}/shop.json", timeout=15)
            shop = resp.json().get("shop", {})
            return {"success": resp.ok, "shop": shop.get("name"),
                    "plan": shop.get("plan_name")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]:
        return self.DEFAULT_OBJECTS

    def fetch_records(self, object_name: str) -> List[Dict]:
        all_records = []
        url = f"{self._base_url}/{object_name}.json"
        params = {"limit": 250, "status": "any"} if object_name == "orders" else {"limit": 250}

        while True:
            resp = self._session.get(url, params=params, timeout=60)
            if not resp.ok: break
            data = resp.json()
            records = data.get(object_name, data)
            if isinstance(records, list) and records:
                all_records.extend(records)
            # Shopify uses cursor-based Link header pagination
            link_header = resp.headers.get("Link", "")
            if 'rel="next"' not in link_header: break
            next_url = None
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
                    break
            if not next_url: break
            url = next_url; params = {}
        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_records(object_name)
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
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Google Analytics 4 (Data API)
# ══════════════════════════════════════════════════════════════

class GA4Connector:
    """
    GA4 Data API connector.
    config: property_id, service_account_json
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None

    def connect(self):
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account
        import json

        sa_json = self.config.get("service_account_json", "")
        sa_info = json.loads(sa_json) if isinstance(sa_json, str) else sa_json
        creds = service_account.Credentials.from_service_account_info(sa_info)
        self._client = BetaAnalyticsDataClient(credentials=creds)
        logger.info(f"GA4 connected: property={self.config.get('property_id')}")

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            # Run a minimal query
            rows = self.run_report(
                dimensions=["country"],
                metrics=["activeUsers"],
                date_range_start="7daysAgo", date_range_end="today",
                limit=1,
            )
            return {"success": True, "property_id": self.config.get("property_id"),
                    "sample_rows": len(rows)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_report(self, dimensions: List[str], metrics: List[str],
                   date_range_start: str = "30daysAgo",
                   date_range_end: str = "today",
                   limit: int = 100000) -> List[Dict]:
        from google.analytics.data_v1beta.types import (
            Dimension, Metric, DateRange, RunReportRequest,
        )
        req = RunReportRequest(
            property=f"properties/{self.config.get('property_id', '')}",
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m)     for m in metrics],
            date_ranges=[DateRange(start_date=date_range_start, end_date=date_range_end)],
            limit=limit,
        )
        resp = self._client.run_report(req)

        records = []
        for row in resp.rows:
            rec = {}
            for i, d in enumerate(dimensions):
                rec[d] = row.dimension_values[i].value
            for i, m in enumerate(metrics):
                rec[m] = row.metric_values[i].value
            records.append(rec)
        return records

    def list_objects(self) -> List[str]:
        return ["sessions", "active_users", "page_views", "events", "conversions"]

    def fetch_records(self, report_type: str) -> List[Dict]:
        PRESETS = {
            "sessions":     (["date","country","deviceCategory"], ["sessions","bounceRate"]),
            "active_users": (["date"], ["activeUsers","newUsers"]),
            "page_views":   (["date","pagePath","pageTitle"], ["screenPageViews","averageSessionDuration"]),
            "events":       (["date","eventName"], ["eventCount","totalUsers"]),
            "conversions":  (["date","eventName"], ["conversions","totalRevenue"]),
        }
        dimensions, metrics = PRESETS.get(report_type, (["date"], ["activeUsers"]))
        return self.run_report(dimensions, metrics)

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_records(object_name)
        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0, "files": 0}

        start = time.time()
        df = pd.DataFrame(records)
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
        buf.seek(0)
        boto3.client("s3", aws_access_key_id=aws_access_key,
                     aws_secret_access_key=aws_secret_key, region_name=aws_region).put_object(
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}
