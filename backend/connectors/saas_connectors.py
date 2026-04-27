"""
UMA Platform — SaaS Connectors
Zendesk · Stripe · HubSpot · NetSuite · Jira · Shopify
All extend RESTConnector with object-specific logic.
"""

import logging, time, io
from typing import Dict, List, Any, Optional
from connectors.storage_connectors import RESTConnector

logger = logging.getLogger("uma.connectors.saas")


# ══════════════════════════════════════════════════════════════
# Zendesk
# ══════════════════════════════════════════════════════════════

class ZendeskConnector:
    """
    Zendesk Support API connector.
    config: subdomain, email, api_token
    Objects: tickets, users, organizations, ticket_comments, groups, satisfaction_ratings
    """

    OBJECTS = {
        "tickets": ("/api/v2/tickets.json", "tickets"),
        "users": ("/api/v2/users.json", "users"),
        "organizations": ("/api/v2/organizations.json", "organizations"),
        "groups": ("/api/v2/groups.json", "groups"),
        "satisfaction_ratings": ("/api/v2/satisfaction_ratings.json", "satisfaction_ratings"),
        "ticket_fields": ("/api/v2/ticket_fields.json", "ticket_fields"),
        "macros": ("/api/v2/macros.json", "macros"),
        "sla_policies": ("/api/v2/slas/policies.json", "sla_policies"),
    }

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        subdomain = config.get("subdomain", "")
        base_url = f"https://{subdomain}.zendesk.com"
        import base64
        token = base64.b64encode(
            f"{config.get('email')}/token:{config.get('api_token')}".encode()
        ).decode()
        self._rest = RESTConnector({
            "base_url": base_url,
            "auth_type": "bearer",
            "bearer_token": "",  # overridden below
            "pagination_type": "link",
            "page_size": 100,
        })
        self._base_url = base_url
        self._auth_header = f"Basic {token}"

    def connect(self):
        import requests
        self._rest._session = requests.Session()
        self._rest._session.headers["Authorization"] = self._auth_header
        self._rest._session.headers["Content-Type"] = "application/json"

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            import requests
            resp = requests.get(f"{self._base_url}/api/v2/account.json",
                                headers={"Authorization": self._auth_header}, timeout=10)
            data = resp.json()
            return {"success": resp.ok, "subdomain": data.get("account", {}).get("subdomain"),
                    "plan": data.get("account", {}).get("plan_name")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]:
        return list(self.OBJECTS.keys())

    def fetch_object(self, object_name: str) -> List[Dict]:
        if object_name not in self.OBJECTS:
            raise ValueError(f"Unknown Zendesk object: {object_name}")
        endpoint, data_key = self.OBJECTS[object_name]
        return self._rest.fetch_all(endpoint, data_path=data_key)

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_object(object_name)
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
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# Stripe
# ══════════════════════════════════════════════════════════════

class StripeConnector:
    """
    Stripe API connector using cursor-based pagination.
    config: api_key, api_version
    Objects: charges, customers, invoices, payment_intents, subscriptions,
             products, prices, refunds, disputes, payouts
    """

    OBJECTS = [
        "charges", "customers", "invoices", "payment_intents",
        "subscriptions", "products", "prices", "refunds", "disputes", "payouts",
        "events", "balance_transactions",
    ]

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._rest = RESTConnector({
            "base_url": "https://api.stripe.com/v1",
            "auth_type": "basic",
            "username": config.get("api_key", ""),
            "password": "",
            "pagination_type": "cursor",
            "cursor_path": "data.last",
            "page_size": 100,
        })

    def connect(self):
        import requests
        from requests.auth import HTTPBasicAuth
        self._rest._session = requests.Session()
        self._rest._session.auth = HTTPBasicAuth(self.config.get("api_key", ""), "")
        if self.config.get("api_version"):
            self._rest._session.headers["Stripe-Version"] = self.config["api_version"]

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            resp = self._rest._session.get("https://api.stripe.com/v1/balance", timeout=10)
            data = resp.json()
            return {"success": resp.ok,
                    "available": data.get("available", []),
                    "livemode": data.get("livemode")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_objects(self) -> List[str]: return self.OBJECTS

    def fetch_object(self, object_name: str, limit: int = 100) -> List[Dict]:
        """Stripe uses cursor pagination with starting_after."""
        all_records = []
        params = {"limit": limit}
        while True:
            resp = self._rest._session.get(
                f"https://api.stripe.com/v1/{object_name}", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data", [])
            all_records.extend(records)
            if not data.get("has_more"):
                break
            params["starting_after"] = records[-1]["id"]
        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_object(object_name)
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
            Bucket=s3_bucket, Key=f"{s3_prefix}/data.parquet", Body=buf.getvalue())

        return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/",
                "total_rows": len(df), "files": 1,
                "duration_seconds": time.time()-start}


# ══════════════════════════════════════════════════════════════
# HubSpot
# ══════════════════════════════════════════════════════════════

class HubSpotConnector:
    """
    HubSpot CRM API v3 connector.
    config: access_token (private app token or OAuth)
    Objects: contacts, companies, deals, tickets, products, line_items
    """

    OBJECTS = {
        "contacts": "/crm/v3/objects/contacts",
        "companies": "/crm/v3/objects/companies",
        "deals": "/crm/v3/objects/deals",
        "tickets": "/crm/v3/objects/tickets",
        "products": "/crm/v3/objects/products",
        "line_items": "/crm/v3/objects/line_items",
        "owners": "/crm/v3/owners",
        "pipelines": "/crm/v3/pipelines/deals",
    }

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None

    def connect(self):
        import requests
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.config.get('access_token', '')}"
        self._session.headers["Content-Type"] = "application/json"

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            resp = self._session.get("https://api.hubapi.com/oauth/v1/access-tokens/"
                                     + self.config.get("access_token",""), timeout=10)
            if resp.ok:
                data = resp.json()
                return {"success": True, "hub_id": data.get("hub_id"), "scopes": data.get("scopes", [])}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def fetch_object(self, object_name: str, properties: Optional[List[str]] = None) -> List[Dict]:
        endpoint = self.OBJECTS.get(object_name)
        if not endpoint:
            raise ValueError(f"Unknown HubSpot object: {object_name}")

        base = "https://api.hubapi.com"
        all_records = []
        after = None

        while True:
            params = {"limit": 100}
            if properties:
                params["properties"] = ",".join(properties)
            if after:
                params["after"] = after

            resp = self._session.get(f"{base}{endpoint}", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])

            # Flatten properties
            for r in results:
                flat = {"id": r.get("id"), "createdAt": r.get("createdAt"), "updatedAt": r.get("updatedAt")}
                flat.update(r.get("properties", {}))
                all_records.append(flat)

            paging = data.get("paging", {})
            after = paging.get("next", {}).get("after")
            if not after:
                break

        return all_records

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        records = self.fetch_object(object_name)
        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0, "files": 0}

        start = time.time()
        df = pd.DataFrame(records)
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str)

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


# ══════════════════════════════════════════════════════════════
# Jira
# ══════════════════════════════════════════════════════════════

class JiraConnector:
    """
    Jira Cloud REST API connector.
    config: base_url (https://yourorg.atlassian.net), email, api_token
    Objects: issues, projects, users, boards, sprints, components
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session = None

    def connect(self):
        import requests, base64
        token = base64.b64encode(
            f"{self.config.get('email')}:{self.config.get('api_token')}".encode()
        ).decode()
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        })

    def __enter__(self): self.connect(); return self
    def __exit__(self, *a): pass

    def test_connection(self) -> Dict:
        try:
            base = self.config.get("base_url", "").rstrip("/")
            resp = self._session.get(f"{base}/rest/api/3/myself", timeout=10)
            data = resp.json()
            return {"success": resp.ok, "account_id": data.get("accountId"),
                    "display_name": data.get("displayName")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def fetch_issues(self, jql: str = "ORDER BY created DESC",
                     fields: Optional[str] = None, max_results: int = 50000) -> List[Dict]:
        base = self.config.get("base_url", "").rstrip("/")
        all_issues = []; start_at = 0; page_size = 100
        while len(all_issues) < max_results:
            resp = self._session.post(
                f"{base}/rest/api/3/search",
                json={"jql": jql, "startAt": start_at, "maxResults": page_size,
                      "fields": fields or ["summary","status","assignee","reporter",
                                           "priority","created","updated","issuetype","project"]},
                timeout=30)
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            if not issues: break
            for i in issues:
                flat = {"id": i["id"], "key": i["key"]}
                flat.update({k: str(v) if not isinstance(v,(str,int,float,bool,type(None))) else v
                              for k,v in i.get("fields",{}).items()})
                all_issues.append(flat)
            start_at += len(issues)
            if start_at >= data.get("total", 0): break
        return all_issues

    def export_to_s3(self, object_name: str, s3_bucket: str, s3_prefix: str,
                     aws_access_key: str, aws_secret_key: str,
                     aws_region: str = "us-east-1",
                     jql: str = "ORDER BY created DESC") -> Dict:
        import pandas as pd, boto3
        import pyarrow as pa, pyarrow.parquet as pq

        if object_name == "issues":
            records = self.fetch_issues(jql=jql)
        else:
            base = self.config.get("base_url","").rstrip("/")
            resp = self._session.get(f"{base}/rest/api/3/{object_name}", timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("values", [])

        if not records:
            return {"s3_path": f"s3://{s3_bucket}/{s3_prefix}/", "total_rows": 0, "files": 0}

        start = time.time()
        df = pd.DataFrame(records)
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str)

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
