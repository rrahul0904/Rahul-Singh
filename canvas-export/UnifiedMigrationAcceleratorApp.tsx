import React, { useMemo, useState } from "react";
import {
  BarChart3,
  Bell,
  ChevronRight,
  Copy,
  Database,
  Download,
  Eye,
  FileCode2,
  FileText,
  Filter,
  FolderTree,
  LayoutDashboard,
  LineChart,
  MessageSquareText,
  PieChart,
  Play,
  Plug,
  Plus,
  Save,
  Search,
  Settings,
  ShieldCheck,
  Table2,
  TerminalSquare,
  User,
  Wand2,
} from "lucide-react";

const NAV_ITEMS = [
  { id: "insights", label: "Insights", icon: BarChart3 },
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "tables", label: "Tables", icon: Database },
  { id: "jobs", label: "Jobs", icon: Play },
  { id: "generators", label: "Generators", icon: FileCode2 },
  { id: "validation", label: "Validation", icon: ShieldCheck },
  { id: "connections", label: "Connections", icon: Plug },
  { id: "admin", label: "Admin", icon: Settings },
];

const METRICS = [
  { label: "Objects in Scope", value: "2,846", sub: "+218 this week" },
  { label: "Jobs Executed", value: "196", sub: "24 active today" },
  { label: "Validation Pass Rate", value: "97.8%", sub: "3 exceptions open" },
  { label: "Saved Queries", value: "128", sub: "Leasing, revenue, forecast" },
];

const TABLES = [
  { object: "customer_profile", source: "BigQuery", target: "Snowflake", rows: "48.2M", pattern: "MERGE", status: "Ready" },
  { object: "reservation_fact", source: "BigQuery", target: "Databricks", rows: "310.5M", pattern: "COPY", status: "Running" },
  { object: "guest_feedback", source: "BigQuery", target: "Snowflake", rows: "12.8M", pattern: "Snowpark", status: "Review" },
  { object: "salesforce_opportunity", source: "Azure SQL", target: "Databricks", rows: "5.1M", pattern: "INSERT", status: "Ready" },
];

const JOBS = [
  { id: "JOB-1042", name: "BQ to Snowflake Daily Core Load", type: "Full Load", runtime: "SQL", env: "Test", status: "Running", progress: 84 },
  { id: "JOB-1043", name: "Snowflake Occupancy Validation Pack", type: "Validation", runtime: "Snowpark", env: "Dev", status: "Succeeded", progress: 100 },
  { id: "JOB-1044", name: "Azure SQL to Databricks Merge Pack", type: "Conversion", runtime: "Generator", env: "Test", status: "Review", progress: 61 },
  { id: "JOB-1045", name: "Databricks Revenue Reconciliation", type: "Validation", runtime: "Spark", env: "Prod", status: "Queued", progress: 42 },
];

const GENERATORS = [
  { id: "copy", name: "COPY Command Generator", description: "Generate Snowflake and Databricks staged load commands.", sample: "COPY INTO target_schema.target_table FROM @stage/path FILE_FORMAT = (TYPE = PARQUET);" },
  { id: "merge", name: "MERGE Statement Generator", description: "Generate upsert logic from key mappings.", sample: "MERGE INTO tgt USING src ON tgt.id = src.id WHEN MATCHED THEN UPDATE SET ... WHEN NOT MATCHED THEN INSERT (...);" },
  { id: "insert", name: "INSERT Statement Generator", description: "Generate insert-select or direct insert patterns.", sample: "INSERT INTO target_table (col1, col2) SELECT col1, col2 FROM source_table;" },
  { id: "delete", name: "DELETE Statement Generator", description: "Generate delete logic using keys or predicates.", sample: "DELETE FROM target_table WHERE business_date < current_date - 90;" },
  { id: "ddl", name: "DDL Generator", description: "Create Snowflake or Databricks target DDL.", sample: "CREATE TABLE schema.table_name (id BIGINT, created_at TIMESTAMP, payload STRING);" },
  { id: "validation", name: "Validation SQL Generator", description: "Generate row-count, aggregate, and parity SQL.", sample: "SELECT 'row_count' AS check_name, COUNT(*) AS src_count FROM src_table;" },
  { id: "snowpark", name: "Snowpark Procedure Generator", description: "Generate Python Snowpark procedures for governed execution.", sample: "CREATE OR REPLACE PROCEDURE run_validation_pack() RETURNS STRING LANGUAGE PYTHON ..." },
  { id: "spark", name: "Spark Job Generator", description: "Generate PySpark jobs for Databricks workloads.", sample: "df = spark.read.table('source_table')\ndf.write.format('delta').mode('append').saveAsTable('target_table')" },
];

const VALIDATIONS = [
  { object: "customer_profile", checks: 18, passed: 18, failed: 0, severity: "Low", lastRun: "2026-04-03 20:15" },
  { object: "reservation_fact", checks: 32, passed: 31, failed: 1, severity: "Medium", lastRun: "2026-04-03 20:04" },
  { object: "booking_events", checks: 21, passed: 17, failed: 4, severity: "High", lastRun: "2026-04-03 19:58" },
];

const CONNECTIONS = [
  { name: "bq-prod-core", type: "BigQuery", env: "Prod", status: "Healthy", owner: "Platform Team" },
  { name: "azure-sql-source", type: "Azure SQL", env: "Test", status: "Healthy", owner: "Data Engineering" },
  { name: "snowflake-dev", type: "Snowflake", env: "Dev", status: "Warning", owner: "Analytics Eng" },
  { name: "databricks-workspace-prod", type: "Databricks", env: "Prod", status: "Healthy", owner: "Lakehouse Team" },
];

const BUSINESS_QUESTIONS = [
  "What is our current occupancy rate by region?",
  "Who are our top 10 tenants by revenue?",
  "What percentage of leases are due to expire in the next 12 months?",
  "How are lease renewals tracking compared to forecasts?",
];

const SAVED_QUERIES = [
  { name: "Occupancy by Region", folder: "Leasing KPIs", engine: "Snowflake" },
  { name: "Top 10 Tenants by Revenue", folder: "Revenue", engine: "Databricks" },
  { name: "Lease Expiry in 12 Months", folder: "Lease Management", engine: "Snowflake" },
];

const RECENT_QUERIES = [
  { name: "Occupancy by Region", dialect: "Snowflake SQL", ranAt: "2026-04-03 21:10", status: "Succeeded" },
  { name: "Top Tenants by Revenue", dialect: "Databricks SQL", ranAt: "2026-04-03 20:42", status: "Succeeded" },
  { name: "Lease Expiry Next 12 Months", dialect: "Snowflake SQL", ranAt: "2026-04-03 20:12", status: "Review" },
];

const SCHEMA_BROWSER = [
  { connection: "snowflake-dev", database: "LEASING_ANALYTICS", groups: ["MART_LEASING_OCCUPANCY", "MART_TENANT_REVENUE", "FACT_LEASE_RENEWALS"] },
  { connection: "databricks-workspace-prod", database: "leasing_gold", groups: ["occupancy_by_region", "tenant_revenue_summary", "lease_expiry_forecast"] },
];

function cx(...items: Array<string | false | undefined>) {
  return items.filter(Boolean).join(" ");
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={cx("rounded-3xl border border-white/70 bg-white/90 shadow-sm", className)}>{children}</div>;
}

function CardHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 md:flex-row md:items-center md:justify-between">
      <div>
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        {subtitle ? <p className="mt-1 text-sm text-slate-500">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
  );
}

function CardBody({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={cx("p-5", className)}>{children}</div>;
}

function Button({ children, variant = "primary", className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children: React.ReactNode; variant?: "primary" | "outline" }) {
  const styles =
    variant === "outline"
      ? "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
      : "bg-gradient-to-r from-fuchsia-600 via-violet-600 to-indigo-600 text-white hover:opacity-95";
  return (
    <button className={cx("inline-flex items-center gap-2 rounded-2xl px-4 py-2 text-sm font-medium transition", styles, className)} {...props}>
      {children}
    </button>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "green" | "amber" | "blue" | "red" }) {
  const tones = {
    neutral: "border-slate-200 bg-slate-50 text-slate-700",
    green: "border-emerald-200 bg-emerald-50 text-emerald-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    blue: "border-sky-200 bg-sky-50 text-sky-700",
    red: "border-rose-200 bg-rose-50 text-rose-700",
  };
  return <span className={cx("inline-flex rounded-full border px-2.5 py-1 text-xs font-medium", tones[tone])}>{children}</span>;
}

function StatusBadge({ value }: { value: string }) {
  if (["Ready", "Succeeded", "Healthy", "Passed", "Low"].includes(value)) return <Badge tone="green">{value}</Badge>;
  if (value === "Running") return <Badge tone="blue">{value}</Badge>;
  if (["Review", "Queued", "Warning", "Medium"].includes(value)) return <Badge tone="amber">{value}</Badge>;
  if (["High", "Failed"].includes(value)) return <Badge tone="red">{value}</Badge>;
  return <Badge>{value}</Badge>;
}

function Progress({ value }: { value: number }) {
  return (
    <div className="h-2 w-full rounded-full bg-slate-100">
      <div className="h-2 rounded-full bg-gradient-to-r from-fuchsia-600 via-violet-600 to-indigo-600" style={{ width: `${value}%` }} />
    </div>
  );
}

function Input({ defaultValue = "", placeholder = "", className = "" }: { defaultValue?: string; placeholder?: string; className?: string }) {
  return <input defaultValue={defaultValue} placeholder={placeholder} className={cx("w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-fuchsia-200", className)} />;
}

function SelectLike({ value }: { value: string }) {
  return <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">{value}</div>;
}

function TextArea({ defaultValue = "", placeholder = "", className = "" }: { defaultValue?: string; placeholder?: string; className?: string }) {
  return <textarea defaultValue={defaultValue} placeholder={placeholder} className={cx("min-h-[180px] w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-fuchsia-200", className)} />;
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <Card>
      <CardBody>
        <div className="text-sm text-slate-500">{label}</div>
        <div className="mt-2 text-3xl font-semibold text-slate-900">{value}</div>
        <div className="mt-1 text-sm text-slate-500">{sub}</div>
      </CardBody>
    </Card>
  );
}

function SectionHeader({ title, description, actions }: { title: string; description: string; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h2 className="text-2xl font-semibold text-slate-900">{title}</h2>
        <p className="mt-1 text-sm text-slate-500">{description}</p>
      </div>
      {actions}
    </div>
  );
}

function Table({ columns, rows }: { columns: string[]; rows: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-slate-500">
            {columns.map((col) => (
              <th key={col} className="px-3 py-3 font-medium">{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}

function TopBar() {
  return (
    <div className="sticky top-0 z-20 flex items-center justify-between border-b border-white/60 bg-white/80 px-6 py-4 backdrop-blur">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.22em] text-fuchsia-700">Unified Migration Accelerator</p>
        <h1 className="text-xl font-semibold text-slate-900">One control plane for migration, conversion, and analysis</h1>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden w-80 items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-500 md:flex">
          <Search className="h-4 w-4" />
          <input className="w-full bg-transparent outline-none" placeholder="Search jobs, queries, tables, generators..." />
        </div>
        <Button variant="outline" className="px-3 py-2"><Bell className="h-4 w-4" /></Button>
        <Button variant="outline" className="px-3 py-2"><User className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

function Sidebar({ current, setCurrent }: { current: string; setCurrent: (id: string) => void }) {
  return (
    <div className="hidden min-h-screen w-72 border-r border-white/60 bg-white/60 p-4 backdrop-blur lg:block">
      <div className="mb-4 rounded-3xl bg-gradient-to-br from-fuchsia-700 via-violet-700 to-indigo-700 p-5 text-white shadow-sm">
        <div className="text-sm text-fuchsia-100">Workspace</div>
        <div className="mt-1 text-lg font-semibold">Enterprise Migration Workspace</div>
      </div>
      <div className="space-y-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = current === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setCurrent(item.id)}
              className={cx("flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-sm transition", active ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:bg-white/70")}
            >
              <Icon className="h-4 w-4" />
              <span className="font-medium">{item.label}</span>
              {active ? <ChevronRight className="ml-auto h-4 w-4" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function DashboardPage() { return <div className="text-slate-900">Dashboard placeholder</div>; }
function TablesPage() { return <div className="text-slate-900">Tables placeholder</div>; }
function JobsPage() { return <div className="text-slate-900">Jobs placeholder</div>; }
function GeneratorsPage() { return <div className="text-slate-900">Generators placeholder</div>; }
function ValidationPage() { return <div className="text-slate-900">Validation placeholder</div>; }
function ConnectionsPage() { return <div className="text-slate-900">Connections placeholder</div>; }
function AdminPage() { return <div className="text-slate-900">Admin placeholder</div>; }

function InsightsPage() {
  const [question, setQuestion] = useState(BUSINESS_QUESTIONS[0]);
  const [chart, setChart] = useState("table");
  const sql = `SELECT\n  region,\n  ROUND(SUM(occupied_units) / NULLIF(SUM(total_units), 0) * 100, 2) AS occupancy_rate_pct\nFROM mart_leasing_occupancy\nGROUP BY region\nORDER BY occupancy_rate_pct DESC;`;

  return (
    <div className="space-y-6">
      <SectionHeader title="Business Insights Studio" description="Use a conversational workspace to explore business questions, generate SQL, and analyze governed data in Snowflake or Databricks." actions={<div className="flex gap-2"><Button variant="outline"><MessageSquareText className="h-4 w-4" />New Prompt</Button><Button><TerminalSquare className="h-4 w-4" />Open Query Editor</Button></div>} />
      <Card>
        <CardHeader title="Ask UMA" subtitle="Type a business question in natural language and let the platform generate SQL, explain the logic, and return results." />
        <CardBody className="space-y-4">
          <div className="rounded-[28px] border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-start gap-3">
              <div className="mt-1 rounded-2xl bg-gradient-to-br from-fuchsia-600 via-violet-600 to-indigo-600 px-3 py-2 text-xs font-semibold text-white">UMA</div>
              <div className="flex-1 space-y-3">
                <textarea value={question} onChange={(e) => setQuestion(e.target.value)} className="min-h-[120px] w-full resize-none rounded-2xl border-0 bg-transparent px-2 py-2 text-sm outline-none" placeholder="Ask about occupancy, revenue, lease expiries, renewals, tenant performance, or portfolio trends..." />
                <div className="flex flex-wrap gap-2"><Button><MessageSquareText className="h-4 w-4" />Send Prompt</Button><Button variant="outline"><Wand2 className="h-4 w-4" />Generate SQL</Button><Button variant="outline"><Play className="h-4 w-4" />Run</Button><Button variant="outline"><Save className="h-4 w-4" />Save Prompt</Button></div>
              </div>
            </div>
          </div>
        </CardBody>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.3fr_1fr]">
        <Card>
          <CardHeader title="Starter Questions" subtitle="Leasing, occupancy, revenue, and renewals" />
          <CardBody className="space-y-3">
            {BUSINESS_QUESTIONS.map((item) => (
              <button key={item} onClick={() => setQuestion(item)} className={cx("w-full rounded-2xl border p-4 text-left transition", question === item ? "border-fuchsia-300 bg-fuchsia-50" : "border-slate-100 hover:bg-slate-50")}>
                <div className="text-sm font-medium text-slate-900">{item}</div>
              </button>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Query Workspace" subtitle={question} />
          <CardBody className="space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <SelectLike value="snowflake-dev" />
              <SelectLike value="Snowflake SQL" />
              <SelectLike value="COMPUTE_XS" />
            </div>
            <TextArea defaultValue={sql} className="min-h-[240px] font-mono text-xs" />
            <div className="flex flex-wrap gap-2"><Button><Play className="h-4 w-4" />Run Query</Button><Button variant="outline"><Copy className="h-4 w-4" />Copy SQL</Button><Button variant="outline"><Download className="h-4 w-4" />Export Results</Button></div>
            <div className="rounded-2xl border border-fuchsia-100 bg-fuchsia-50/60 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-900"><FileText className="h-4 w-4" />AI-generated SQL explanation</div>
              <p className="text-sm text-slate-600">This query aggregates occupied and total units by region, calculates occupancy as a percentage, and orders regions from highest to lowest occupancy.</p>
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Schema Browser" subtitle="Object explorer for governed querying" />
          <CardBody className="space-y-4">
            {SCHEMA_BROWSER.map((item) => (
              <div key={item.connection} className="rounded-2xl border border-slate-100 p-4">
                <div className="font-medium text-slate-900">{item.connection}</div>
                <div className="mt-1 text-xs uppercase tracking-wide text-slate-400">{item.database}</div>
                <div className="mt-3 space-y-2">
                  {item.groups.map((name) => (
                    <div key={name} className="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">{name}</div>
                  ))}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.3fr]">
        <Card>
          <CardHeader title="Saved Queries" subtitle="Reusable analyst queries by folder" />
          <CardBody className="space-y-3">
            {SAVED_QUERIES.map((item) => (
              <div key={item.name} className="rounded-2xl border border-slate-100 p-4">
                <div className="flex items-start gap-3"><FolderTree className="mt-0.5 h-4 w-4 text-slate-500" /><div><div className="font-medium text-slate-900">{item.name}</div><div className="mt-1 text-sm text-slate-500">{item.folder} • {item.engine}</div></div></div>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Results Preview" subtitle="Interactive results with table and chart views" actions={<div className="flex gap-2"><Button variant={chart === "table" ? "primary" : "outline"} className="px-3 py-2" onClick={() => setChart("table")}><Table2 className="h-4 w-4" /></Button><Button variant={chart === "pie" ? "primary" : "outline"} className="px-3 py-2" onClick={() => setChart("pie")}><PieChart className="h-4 w-4" /></Button><Button variant={chart === "line" ? "primary" : "outline"} className="px-3 py-2" onClick={() => setChart("line")}><LineChart className="h-4 w-4" /></Button></div>} />
          <CardBody>
            {chart === "table" ? (
              <Table
                columns={["Region", "Occupied Units", "Total Units", "Occupancy Rate %"]}
                rows={[["Northeast", "18,422", "19,850", "92.8"], ["West", "15,901", "17,410", "91.3"], ["Central", "11,446", "12,910", "88.7"], ["South", "13,112", "15,206", "86.2"]].map((row) => (
                  <tr key={row[0]} className="border-b border-slate-50 last:border-0">
                    <td className="px-3 py-3 font-medium text-slate-900">{row[0]}</td>
                    <td className="px-3 py-3">{row[1]}</td>
                    <td className="px-3 py-3">{row[2]}</td>
                    <td className="px-3 py-3">{row[3]}</td>
                  </tr>
                ))}
              />
            ) : (
              <div className="flex h-[260px] items-end justify-around rounded-2xl border border-slate-100 bg-slate-50 p-6">
                {[92.8, 91.3, 88.7, 86.2].map((v, i) => (
                  <div key={i} className="flex flex-col items-center gap-2">
                    <div className="w-14 rounded-t-2xl bg-gradient-to-t from-fuchsia-600 via-violet-600 to-indigo-600" style={{ height: `${v * 2}px` }} />
                    <div className="text-xs text-slate-500">{["NE", "W", "C", "S"][i]}</div>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader title="Recent Queries" subtitle="Saved analyst questions and generated SQL history" />
        <CardBody className="space-y-3">
          {RECENT_QUERIES.map((item) => (
            <div key={item.name} className="rounded-2xl border border-slate-100 p-4">
              <div className="flex items-center justify-between gap-3"><div><div className="font-medium text-slate-900">{item.name}</div><div className="mt-1 text-sm text-slate-500">{item.dialect} • {item.ranAt}</div></div><StatusBadge value={item.status} /></div>
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

export default function UnifiedMigrationAcceleratorApp() {
  const [current, setCurrent] = useState("insights");
  const page = useMemo(() => {
    if (current === "insights") return <InsightsPage />;
    if (current === "dashboard") return <DashboardPage />;
    if (current === "tables") return <TablesPage />;
    if (current === "jobs") return <JobsPage />;
    if (current === "generators") return <GeneratorsPage />;
    if (current === "validation") return <ValidationPage />;
    if (current === "connections") return <ConnectionsPage />;
    if (current === "admin") return <AdminPage />;
    return <DashboardPage />;
  }, [current]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(192,132,252,0.16),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(129,140,248,0.16),_transparent_24%),linear-gradient(to_bottom,_#faf7ff,_#f8fafc)] text-slate-900">
      <div className="flex min-h-screen">
        <Sidebar current={current} setCurrent={setCurrent} />
        <div className="flex-1">
          <TopBar />
          <main className="mx-auto max-w-7xl p-6">{page}</main>
        </div>
      </div>
    </div>
  );
}
