from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

APP_TITLE = os.getenv("APP_TITLE", "Unified Data Migration Accelerator")
APP_ENV = os.getenv("APP_ENV", "demo")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

PROJECTS = [
    {
        "name": "Prologis Leasing Migration",
        "source": "Teradata",
        "target": "Snowflake",
        "status": "In Validation",
        "progress": 72,
    },
    {
        "name": "RevOps Modernization",
        "source": "SQL Server",
        "target": "Databricks",
        "status": "In Conversion",
        "progress": 48,
    },
    {
        "name": "Finance Mart Upgrade",
        "source": "Oracle",
        "target": "Snowflake",
        "status": "Assessment Complete",
        "progress": 31,
    },
]

INVENTORY = [
    {"type": "Tables", "count": 29686, "status": "Discovered"},
    {"type": "Views", "count": 842, "status": "Discovered"},
    {"type": "Stored Procedures", "count": 154, "status": "Needs Review"},
    {"type": "ETL Jobs", "count": 211, "status": "Mapped"},
    {"type": "Pipelines", "count": 57, "status": "Mapped"},
]

CONVERSIONS = [
    {
        "object": "processed_lease_occupancy_monthly",
        "source_type": "BigQuery Scheduled Query",
        "target_type": "dbt Model",
        "status": "Approved",
        "risk": "Low",
    },
    {
        "object": "tenant_revenue_rollup",
        "source_type": "Teradata View",
        "target_type": "Snowflake SQL",
        "status": "Needs Review",
        "risk": "Medium",
    },
    {
        "object": "lease_expiry_projection",
        "source_type": "ADF Pipeline",
        "target_type": "Databricks Job",
        "status": "Drafted",
        "risk": "Medium",
    },
]

VALIDATION = {
    "passed": 184,
    "failed": 12,
    "warning": 9,
    "latest": [
        {"rule": "row_count_parity", "object": "tenant_dim", "severity": "High", "status": "Failed"},
        {"rule": "schema_match", "object": "lease_fact", "severity": "Medium", "status": "Warning"},
        {"rule": "null_check", "object": "occupancy_fact", "severity": "Low", "status": "Passed"},
    ],
}

BUSINESS_SQL = {
    "occupancy": "SELECT region, ROUND(AVG(occupied_sqft / total_sqft) * 100, 2) AS occupancy_rate\nFROM mart_leasing_occupancy\nGROUP BY region\nORDER BY occupancy_rate DESC;",
    "tenants": "SELECT tenant_name, SUM(revenue_usd) AS total_revenue\nFROM mart_tenant_revenue\nGROUP BY tenant_name\nORDER BY total_revenue DESC\nLIMIT 10;",
    "expire": "SELECT COUNT(*) AS leases_expiring_12m,\n       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_due_12m\nFROM mart_leases\nWHERE expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '12 months';",
    "renew": "SELECT month, actual_renewals, forecast_renewals, actual_renewals - forecast_renewals AS variance\nFROM mart_renewal_tracking\nORDER BY month;",
}

QUERY_RESULTS = {
    "occupancy": {
        "columns": ["region", "occupancy_rate"],
        "rows": [
            ["West", 96.1],
            ["Northeast", 94.4],
            ["South", 92.8],
            ["Midwest", 90.7],
        ],
    },
    "tenants": {
        "columns": ["tenant_name", "total_revenue"],
        "rows": [
            ["Amazon", 12400000],
            ["FedEx", 11750000],
            ["Home Depot", 10120000],
            ["Target", 9650000],
            ["Walmart", 9120000],
            ["UPS", 8860000],
            ["Costco", 8420000],
            ["Wayfair", 7990000],
            ["DHL", 7650000],
            ["IKEA", 7440000],
        ],
    },
    "expire": {
        "columns": ["leases_expiring_12m", "pct_due_12m"],
        "rows": [[382, 18.6]],
    },
    "renew": {
        "columns": ["month", "actual_renewals", "forecast_renewals", "variance"],
        "rows": [
            ["2026-01", 82, 78, 4],
            ["2026-02", 76, 79, -3],
            ["2026-03", 88, 84, 4],
            ["2026-04", 91, 89, 2],
        ],
    },
    "default": {
        "columns": ["message"],
        "rows": [["Demo query executed successfully. Replace with live connector execution next."]],
    },
}


class PromptRequest(BaseModel):
    prompt: str


class QueryRequest(BaseModel):
    text: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": APP_ENV, "version": APP_VERSION}


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    return {
        "title": APP_TITLE,
        "environment": APP_ENV,
        "version": APP_VERSION,
        "totals": {
            "projects": len(PROJECTS),
            "objects": sum(item["count"] for item in INVENTORY),
            "approved_conversions": len([x for x in CONVERSIONS if x["status"] == "Approved"]),
            "validation_pass_rate": 90,
        },
    }


@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    return PROJECTS


@app.get("/api/inventory")
def inventory() -> list[dict[str, Any]]:
    return INVENTORY


@app.get("/api/conversions")
def conversions() -> list[dict[str, Any]]:
    return CONVERSIONS


@app.get("/api/validation")
def validation() -> dict[str, Any]:
    return VALIDATION


@app.post("/api/generate-sql")
def generate_sql(request: PromptRequest) -> dict[str, str]:
    prompt = request.prompt.lower()
    if "occupancy" in prompt:
        key = "occupancy"
        explanation = "Calculates occupancy by region from a curated leasing mart."
    elif "tenant" in prompt and "revenue" in prompt:
        key = "tenants"
        explanation = "Ranks tenants by total recognized revenue."
    elif "expire" in prompt or "expir" in prompt:
        key = "expire"
        explanation = "Calculates leases due to expire in the next 12 months."
    elif "renew" in prompt:
        key = "renew"
        explanation = "Compares actual renewals to forecast by month."
    else:
        key = "occupancy"
        explanation = "Default demo SQL returned. Plug connector-aware generation here later."
    return {"sql": BUSINESS_SQL[key], "explanation": explanation}


@app.post("/api/query")
def execute_query(request: QueryRequest) -> dict[str, Any]:
    text = request.text.lower()
    if "occupancy" in text:
        result_key = "occupancy"
    elif "tenant" in text and "revenue" in text:
        result_key = "tenants"
    elif "expire" in text or "expir" in text:
        result_key = "expire"
    elif "renew" in text:
        result_key = "renew"
    else:
        result_key = "default"
    return QUERY_RESULTS[result_key]


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return f"""
<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1.0' />
  <title>{APP_TITLE}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #141b34;
      --panel-2: #1b2442;
      --text: #eef3ff;
      --muted: #aab6d3;
      --accent: #6ea8fe;
      --success: #22c55e;
      --warn: #f59e0b;
      --danger: #ef4444;
      --border: rgba(255,255,255,0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, sans-serif; background: linear-gradient(180deg, #0b1020 0%, #0f172a 100%); color: var(--text); }}
    .shell {{ display: grid; grid-template-columns: 260px 1fr; min-height: 100vh; }}
    .sidebar {{ background: rgba(7, 12, 26, 0.85); border-right: 1px solid var(--border); padding: 24px; }}
    .logo {{ font-size: 22px; font-weight: 700; line-height: 1.25; margin-bottom: 24px; }}
    .nav a {{ display: block; color: var(--muted); text-decoration: none; padding: 10px 12px; border-radius: 10px; margin-bottom: 8px; background: transparent; }}
    .nav a:hover {{ background: rgba(110,168,254,.12); color: var(--text); }}
    .content {{ padding: 24px; }}
    .hero {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 20px; }}
    .hero h1 {{ margin: 0; font-size: 30px; }}
    .hero p {{ margin: 8px 0 0; color: var(--muted); }}
    .pill {{ display: inline-block; padding: 6px 10px; background: rgba(110,168,254,.16); border: 1px solid var(--border); border-radius: 999px; color: var(--text); font-size: 13px; }}
    .grid {{ display: grid; gap: 16px; }}
    .cards {{ grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 18px; }}
    .two {{ grid-template-columns: 1.35fr .95fr; margin-bottom: 18px; }}
    .three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 18px; }}
    .panel {{ background: rgba(20,27,52,.95); border: 1px solid var(--border); border-radius: 18px; padding: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.18); }}
    .panel h2, .panel h3 {{ margin-top: 0; }}
    .metric .label {{ color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .metric .value {{ font-size: 30px; font-weight: 700; }}
    .subtle {{ color: var(--muted); font-size: 13px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--border); font-size: 14px; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .workspace {{ display: grid; grid-template-columns: 240px 1fr 320px; gap: 16px; }}
    .list-item {{ padding: 10px 12px; border: 1px solid var(--border); border-radius: 12px; margin-bottom: 10px; background: rgba(255,255,255,.02); }}
    textarea {{ width: 100%; min-height: 180px; background: #0a1125; color: var(--text); border: 1px solid var(--border); border-radius: 14px; padding: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }}
    input[type='text'] {{ width: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--border); background: #0a1125; color: var(--text); }}
    .actions {{ display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }}
    button {{ border: 0; border-radius: 12px; padding: 10px 14px; cursor: pointer; font-weight: 600; }}
    .primary {{ background: var(--accent); color: #081120; }}
    .secondary {{ background: rgba(255,255,255,.08); color: var(--text); border: 1px solid var(--border); }}
    .status-pass {{ color: var(--success); }}
    .status-warn {{ color: var(--warn); }}
    .status-fail {{ color: var(--danger); }}
    .results {{ overflow: auto; max-height: 340px; }}
    .bars {{ display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }}
    .bar-row {{ display: grid; grid-template-columns: 120px 1fr 50px; gap: 10px; align-items: center; }}
    .bar {{ height: 12px; background: rgba(255,255,255,.08); border-radius: 999px; overflow: hidden; }}
    .bar > span {{ display: block; height: 100%; background: var(--accent); border-radius: 999px; }}
    @media (max-width: 1200px) {{
      .cards, .two, .three, .workspace {{ grid-template-columns: 1fr; }}
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{ border-right: 0; border-bottom: 1px solid var(--border); }}
    }}
  </style>
</head>
<body>
  <div class='shell'>
    <aside class='sidebar'>
      <div class='logo'>Unified Data Migration Accelerator</div>
      <div class='subtle'>Snowflake + Databricks focused migration workbench</div>
      <nav class='nav' style='margin-top:20px'>
        <a href='#overview'>Overview</a>
        <a href='#inventory'>Inventory</a>
        <a href='#conversion'>Conversion</a>
        <a href='#validation'>Validation</a>
        <a href='#workspace'>Query Workspace</a>
      </nav>
    </aside>
    <main class='content'>
      <section class='hero' id='overview'>
        <div>
          <h1>{APP_TITLE}</h1>
          <p>Demo-ready migration dashboard with assessment, conversion, validation, and business query workspace.</p>
        </div>
        <div class='pill'>Environment: {APP_ENV} · v{APP_VERSION}</div>
      </section>

      <section class='grid cards'>
        <div class='panel metric'><div class='label'>Projects</div><div id='metric-projects' class='value'>-</div></div>
        <div class='panel metric'><div class='label'>Objects Discovered</div><div id='metric-objects' class='value'>-</div></div>
        <div class='panel metric'><div class='label'>Approved Conversions</div><div id='metric-conversions' class='value'>-</div></div>
        <div class='panel metric'><div class='label'>Validation Pass Rate</div><div id='metric-passrate' class='value'>-</div></div>
      </section>

      <section class='grid two'>
        <div class='panel'>
          <h2>Migration Projects</h2>
          <table>
            <thead><tr><th>Name</th><th>Source</th><th>Target</th><th>Status</th><th>Progress</th></tr></thead>
            <tbody id='projects-table'></tbody>
          </table>
        </div>
        <div class='panel' id='inventory'>
          <h2>Discovered Inventory</h2>
          <table>
            <thead><tr><th>Object Type</th><th>Count</th><th>Status</th></tr></thead>
            <tbody id='inventory-table'></tbody>
          </table>
        </div>
      </section>

      <section class='grid three'>
        <div class='panel' id='conversion'>
          <h3>Conversion Workbench Status</h3>
          <table>
            <thead><tr><th>Object</th><th>Target</th><th>Status</th></tr></thead>
            <tbody id='conversion-table'></tbody>
          </table>
        </div>
        <div class='panel' id='validation'>
          <h3>Validation Summary</h3>
          <div style='display:flex; gap:18px; margin-bottom:12px'>
            <div><div class='subtle'>Passed</div><div id='val-passed' class='value' style='font-size:24px'>-</div></div>
            <div><div class='subtle'>Failed</div><div id='val-failed' class='value' style='font-size:24px'>-</div></div>
            <div><div class='subtle'>Warning</div><div id='val-warning' class='value' style='font-size:24px'>-</div></div>
          </div>
          <table>
            <thead><tr><th>Rule</th><th>Object</th><th>Status</th></tr></thead>
            <tbody id='validation-table'></tbody>
          </table>
        </div>
        <div class='panel'>
          <h3>Demo Business Questions</h3>
          <div class='list-item'>What is our current occupancy rate by region?</div>
          <div class='list-item'>Who are our top 10 tenants by revenue?</div>
          <div class='list-item'>What percentage of leases are due to expire in the next 12 months?</div>
          <div class='list-item'>How are lease renewals tracking compared to forecasts?</div>
        </div>
      </section>

      <section class='panel' id='workspace'>
        <h2>Query Workspace</h2>
        <div class='workspace'>
          <div>
            <h3 style='margin-top:0'>Schema Browser</h3>
            <div class='list-item'><strong>mart_leasing_occupancy</strong><br><span class='subtle'>region, occupied_sqft, total_sqft</span></div>
            <div class='list-item'><strong>mart_tenant_revenue</strong><br><span class='subtle'>tenant_name, revenue_usd</span></div>
            <div class='list-item'><strong>mart_leases</strong><br><span class='subtle'>lease_id, expiry_date, status</span></div>
            <div class='list-item'><strong>mart_renewal_tracking</strong><br><span class='subtle'>month, actual_renewals, forecast_renewals</span></div>
          </div>
          <div>
            <label class='subtle'>Ask a business question</label>
            <input id='prompt' type='text' value='What is our current occupancy rate by region?' />
            <div class='actions'>
              <button class='primary' onclick='generateSql()'>AI Generate SQL</button>
              <button class='secondary' onclick='runQuery()'>Run Query</button>
            </div>
            <div style='margin-top:12px'>
              <label class='subtle'>SQL Editor</label>
              <textarea id='sql-editor'>-- AI-generated SQL will appear here</textarea>
            </div>
            <div class='results panel' style='margin-top:12px; padding:12px'>
              <h3 style='margin-top:0'>Results</h3>
              <div id='results-table'></div>
              <div id='chart-area' class='bars'></div>
            </div>
          </div>
          <div>
            <h3 style='margin-top:0'>AI Explanation</h3>
            <div id='sql-explanation' class='list-item'>Generate SQL to see explanation.</div>
            <div class='list-item'>Saved Queries<br><span class='subtle'>occupancy_by_region.sql</span></div>
            <div class='list-item'>Saved Queries<br><span class='subtle'>top_tenants_by_revenue.sql</span></div>
            <div class='list-item'>Saved Queries<br><span class='subtle'>lease_expiry_12_months.sql</span></div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    async function loadDashboard() {{
      const [summary, projects, inventory, conversions, validation] = await Promise.all([
        fetch('/api/summary').then(r => r.json()),
        fetch('/api/projects').then(r => r.json()),
        fetch('/api/inventory').then(r => r.json()),
        fetch('/api/conversions').then(r => r.json()),
        fetch('/api/validation').then(r => r.json())
      ]);

      document.getElementById('metric-projects').textContent = summary.totals.projects;
      document.getElementById('metric-objects').textContent = summary.totals.objects.toLocaleString();
      document.getElementById('metric-conversions').textContent = summary.totals.approved_conversions;
      document.getElementById('metric-passrate').textContent = summary.totals.validation_pass_rate + '%';

      document.getElementById('projects-table').innerHTML = projects.map(p => `
        <tr><td>${{p.name}}</td><td>${{p.source}}</td><td>${{p.target}}</td><td>${{p.status}}</td><td>${{p.progress}}%</td></tr>`).join('');

      document.getElementById('inventory-table').innerHTML = inventory.map(i => `
        <tr><td>${{i.type}}</td><td>${{i.count.toLocaleString()}}</td><td>${{i.status}}</td></tr>`).join('');

      document.getElementById('conversion-table').innerHTML = conversions.map(c => `
        <tr><td>${{c.object}}</td><td>${{c.target_type}}</td><td>${{c.status}}</td></tr>`).join('');

      document.getElementById('val-passed').textContent = validation.passed;
      document.getElementById('val-failed').textContent = validation.failed;
      document.getElementById('val-warning').textContent = validation.warning;
      document.getElementById('validation-table').innerHTML = validation.latest.map(v => `
        <tr><td>${{v.rule}}</td><td>${{v.object}}</td><td>${{v.status}}</td></tr>`).join('');
    }}

    async function generateSql() {{
      const prompt = document.getElementById('prompt').value;
      const response = await fetch('/api/generate-sql', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ prompt }})
      }}).then(r => r.json());

      document.getElementById('sql-editor').value = response.sql;
      document.getElementById('sql-explanation').textContent = response.explanation;
    }}

    function makeTable(columns, rows) {{
      return `
        <table>
          <thead><tr>${{columns.map(c => `<th>${{c}}</th>`).join('')}}</tr></thead>
          <tbody>
            ${{rows.map(row => `<tr>${{row.map(cell => `<td>${{cell}}</td>`).join('')}}</tr>`).join('')}}
          </tbody>
        </table>`;
    }}

    function renderChart(columns, rows) {{
      const chart = document.getElementById('chart-area');
      chart.innerHTML = '';
      if (columns.length !== 2 || rows.length === 0 || typeof rows[0][1] !== 'number') return;
      const values = rows.map(r => r[1]);
      const max = Math.max(...values);
      chart.innerHTML = rows.map(r => `
        <div class='bar-row'>
          <div>${{r[0]}}</div>
          <div class='bar'><span style='width:${{Math.max(8, (r[1] / max) * 100)}}%'></span></div>
          <div>${{r[1]}}</div>
        </div>`).join('');
    }}

    async function runQuery() {{
      const text = document.getElementById('sql-editor').value || document.getElementById('prompt').value;
      const result = await fetch('/api/query', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ text }})
      }}).then(r => r.json());

      document.getElementById('results-table').innerHTML = makeTable(result.columns, result.rows);
      renderChart(result.columns, result.rows);
    }}

    loadDashboard().then(generateSql).then(runQuery);
  </script>
</body>
</html>
"""
