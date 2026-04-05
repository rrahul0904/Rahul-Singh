import Link from "next/link";

const examples = {
  createProject: `POST /api/stateful/v1/projects\n{\n  "name": "Stateful Demo Project",\n  "description": "Created against the JSON-backed API.",\n  "source_platform": "Oracle",\n  "target_platform": "Snowflake",\n  "owner": "Rahul"\n}`,
  saveQuery: `POST /api/stateful/v1/workspace/queries\n{\n  "name": "stateful_revenue_query",\n  "sql_text": "SELECT tenant_name, total_revenue FROM mart_revenue ORDER BY total_revenue DESC",\n  "owner": "Rahul"\n}`,
  executeQuery: `POST /api/stateful/v1/workspace/execute\n{\n  "sql_text": "SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC"\n}`,
};

export default function StatefulLabPage() {
  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.4rem", lineHeight: 1.05 }}>Stateful Lab</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 820 }}>
              This page documents the persistent API routes that now back projects, discovery, conversion, validation, and workspace. It also points to the browser-side stateful client for wiring richer write actions next.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Stateful</div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <h2 style={{ marginTop: 0 }}>Create Project</h2>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0, color: "#5a5374" }}>{examples.createProject}</pre>
          </div>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <h2 style={{ marginTop: 0 }}>Save Query</h2>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0, color: "#5a5374" }}>{examples.saveQuery}</pre>
          </div>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <h2 style={{ marginTop: 0 }}>Execute Query</h2>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0, color: "#5a5374" }}>{examples.executeQuery}</pre>
          </div>
        </section>

        <div style={{ marginTop: 24, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link href="/operating-center" style={{ display: "inline-flex", textDecoration: "none", padding: "10px 14px", borderRadius: 12, background: "#1f1736", color: "white", fontWeight: 700 }}>
            Back to Operating Center
          </Link>
          <Link href="/workspace" style={{ display: "inline-flex", textDecoration: "none", padding: "10px 14px", borderRadius: 12, background: "#f5f0ff", color: "#4d2fa9", fontWeight: 700 }}>
            Open Workspace
          </Link>
        </div>
      </div>
    </main>
  );
}
