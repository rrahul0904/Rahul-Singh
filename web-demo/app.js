const data = {
  metrics: [
    { label: 'Projects', value: '3' },
    { label: 'Objects Discovered', value: '30,950' },
    { label: 'Approved Conversions', value: '148' },
    { label: 'Validation Pass Rate', value: '90%' }
  ],
  projects: [
    ['Prologis Leasing Migration', 'Teradata', 'Snowflake', 'In Validation'],
    ['RevOps Modernization', 'SQL Server', 'Databricks', 'In Conversion'],
    ['Finance Mart Upgrade', 'Oracle', 'Snowflake', 'Assessment Complete']
  ],
  inventory: [
    ['Tables', '29,686', 'Discovered'],
    ['Views', '842', 'Discovered'],
    ['Stored Procedures', '154', 'Needs Review'],
    ['ETL Jobs', '211', 'Mapped'],
    ['Pipelines', '57', 'Mapped']
  ],
  conversions: [
    ['processed_lease_occupancy_monthly', 'dbt Model', 'Approved'],
    ['tenant_revenue_rollup', 'Snowflake SQL', 'Needs Review'],
    ['lease_expiry_projection', 'Databricks Job', 'Drafted']
  ],
  validation: [
    ['row_count_parity', 'tenant_dim', 'Failed'],
    ['schema_match', 'lease_fact', 'Warning'],
    ['null_check', 'occupancy_fact', 'Passed']
  ],
  questions: [
    'What is our current occupancy rate by region?',
    'Who are our top 10 tenants by revenue?',
    'What percentage of leases are due to expire in the next 12 months?',
    'How are lease renewals tracking compared to forecasts?'
  ],
  schema: [
    ['mart_leasing_occupancy', 'region, occupied_sqft, total_sqft'],
    ['mart_tenant_revenue', 'tenant_name, revenue_usd'],
    ['mart_leases', 'lease_id, expiry_date, status'],
    ['mart_renewal_tracking', 'month, actual_renewals, forecast_renewals']
  ],
  savedQueries: [
    'occupancy_by_region.sql',
    'top_tenants_by_revenue.sql',
    'lease_expiry_12_months.sql'
  ]
};

const sqlMap = {
  occupancy: "SELECT region, ROUND(AVG(occupied_sqft / total_sqft) * 100, 2) AS occupancy_rate FROM mart_leasing_occupancy GROUP BY region ORDER BY occupancy_rate DESC;",
  tenants: "SELECT tenant_name, SUM(revenue_usd) AS total_revenue FROM mart_tenant_revenue GROUP BY tenant_name ORDER BY total_revenue DESC LIMIT 10;",
  expire: "SELECT COUNT(*) AS leases_expiring_12m, ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_due_12m FROM mart_leases WHERE expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '12 months';",
  renew: "SELECT month, actual_renewals, forecast_renewals, actual_renewals - forecast_renewals AS variance FROM mart_renewal_tracking ORDER BY month;"
};

const resultMap = {
  occupancy: { columns: ['region', 'occupancy_rate'], rows: [['West', 96.1], ['Northeast', 94.4], ['South', 92.8], ['Midwest', 90.7]] },
  tenants: { columns: ['tenant_name', 'total_revenue'], rows: [['Amazon', 12400000], ['FedEx', 11750000], ['Home Depot', 10120000], ['Target', 9650000], ['Walmart', 9120000]] },
  expire: { columns: ['leases_expiring_12m', 'pct_due_12m'], rows: [[382, 18.6]] },
  renew: { columns: ['month', 'actual_renewals', 'forecast_renewals', 'variance'], rows: [['2026-01', 82, 78, 4], ['2026-02', 76, 79, -3], ['2026-03', 88, 84, 4], ['2026-04', 91, 89, 2]] }
};

function renderRows(rows) {
  return rows.map(r => `<tr>${r.map(v => `<td>${v}</td>`).join('')}</tr>`).join('');
}

function renderStaticSections() {
  document.getElementById('app').innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="logo">Unified Data Migration Accelerator</div>
        <div class="subtle">Standalone web demo container</div>
        <nav class="nav">
          <a href="#overview">Overview</a>
          <a href="#inventory">Inventory</a>
          <a href="#conversion">Conversion</a>
          <a href="#validation">Validation</a>
          <a href="#workspace">Query Workspace</a>
        </nav>
      </aside>
      <main class="content">
        <section class="hero" id="overview">
          <div>
            <h1>Unified Data Migration Accelerator</h1>
            <p>Standalone browser demo for migration, validation, and business query workflows.</p>
          </div>
          <div class="pill">Container: web-demo</div>
        </section>

        <section class="grid cards" id="metrics"></section>

        <section class="grid two">
          <div class="panel">
            <h2>Migration Projects</h2>
            <table><thead><tr><th>Name</th><th>Source</th><th>Target</th><th>Status</th></tr></thead><tbody id="projects-table"></tbody></table>
          </div>
          <div class="panel" id="inventory">
            <h2>Discovered Inventory</h2>
            <table><thead><tr><th>Object Type</th><th>Count</th><th>Status</th></tr></thead><tbody id="inventory-table"></tbody></table>
          </div>
        </section>

        <section class="grid three">
          <div class="panel" id="conversion">
            <h3>Conversion Workbench</h3>
            <table><thead><tr><th>Object</th><th>Target</th><th>Status</th></tr></thead><tbody id="conversion-table"></tbody></table>
          </div>
          <div class="panel" id="validation">
            <h3>Validation Summary</h3>
            <table><thead><tr><th>Rule</th><th>Object</th><th>Status</th></tr></thead><tbody id="validation-table"></tbody></table>
          </div>
          <div class="panel">
            <h3>Business Questions</h3>
            <div id="questions"></div>
          </div>
        </section>

        <section class="panel" id="workspace">
          <h2>Query Workspace</h2>
          <div class="workspace">
            <div>
              <h3>Schema Browser</h3>
              <div id="schema-browser"></div>
            </div>
            <div>
              <label class="subtle">Ask a business question</label>
              <input id="prompt" type="text" value="What is our current occupancy rate by region?" />
              <div class="actions">
                <button class="primary" onclick="generateSql()">AI Generate SQL</button>
                <button class="secondary" onclick="runQuery()">Run Query</button>
              </div>
              <div class="editor-block">
                <label class="subtle">SQL Editor</label>
                <textarea id="sql-editor">-- AI-generated SQL will appear here</textarea>
              </div>
              <div class="panel inner-panel">
                <h3>Results</h3>
                <div id="results-table"></div>
                <div id="chart-area" class="bars"></div>
              </div>
            </div>
            <div>
              <h3>AI Explanation</h3>
              <div id="sql-explanation" class="list-item">Generate SQL to see explanation.</div>
              <div id="saved-queries"></div>
            </div>
          </div>
        </section>
      </main>
    </div>`;

  document.getElementById('metrics').innerHTML = data.metrics.map(m => `<div class="panel metric"><div class="label">${m.label}</div><div class="value">${m.value}</div></div>`).join('');
  document.getElementById('projects-table').innerHTML = renderRows(data.projects);
  document.getElementById('inventory-table').innerHTML = renderRows(data.inventory);
  document.getElementById('conversion-table').innerHTML = renderRows(data.conversions);
  document.getElementById('validation-table').innerHTML = renderRows(data.validation);
  document.getElementById('questions').innerHTML = data.questions.map(q => `<div class="list-item">${q}</div>`).join('');
  document.getElementById('schema-browser').innerHTML = data.schema.map(s => `<div class="list-item"><strong>${s[0]}</strong><br><span class="subtle">${s[1]}</span></div>`).join('');
  document.getElementById('saved-queries').innerHTML = data.savedQueries.map(q => `<div class="list-item">Saved Query<br><span class="subtle">${q}</span></div>`).join('');
}

function modeForText(text) {
  const t = text.toLowerCase();
  if (t.includes('occupancy')) return 'occupancy';
  if (t.includes('tenant') && t.includes('revenue')) return 'tenants';
  if (t.includes('expire')) return 'expire';
  if (t.includes('renew')) return 'renew';
  return 'occupancy';
}

function generateSql() {
  const prompt = document.getElementById('prompt').value;
  const mode = modeForText(prompt);
  document.getElementById('sql-editor').value = sqlMap[mode];
  document.getElementById('sql-explanation').textContent = 'Generated demo SQL for: ' + mode;
}

function runQuery() {
  const text = document.getElementById('sql-editor').value || document.getElementById('prompt').value;
  const mode = modeForText(text);
  const result = resultMap[mode];
  document.getElementById('results-table').innerHTML = `<table><thead><tr>${result.columns.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${result.rows.map(r => `<tr>${r.map(v => `<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  if (result.columns.length === 2 && typeof result.rows[0][1] === 'number') {
    const max = Math.max(...result.rows.map(r => r[1]));
    document.getElementById('chart-area').innerHTML = result.rows.map(r => `<div class="bar-row"><div>${r[0]}</div><div class="bar"><span style="width:${Math.max(8,(r[1]/max)*100)}%"></span></div><div>${r[1]}</div></div>`).join('');
  } else {
    document.getElementById('chart-area').innerHTML = '';
  }
}

renderStaticSections();
generateSql();
runQuery();
