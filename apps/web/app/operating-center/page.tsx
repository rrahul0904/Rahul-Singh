import Link from "next/link";

const modules = [
  {
    name: "Project Control Plane",
    route: "/project-control-plane",
    description: "Projects, ownership, progress, and inventory drilldown.",
  },
  {
    name: "Discovery and Assessment",
    route: "/discovery",
    description: "Discovery runs, complexity, and metadata scan outputs.",
  },
  {
    name: "Conversion Workbench",
    route: "/conversion",
    description: "Conversion items, review status, and migration artifact tracking.",
  },
  {
    name: "Validation and Reconciliation",
    route: "/validation",
    description: "Validation runs, mismatches, and severity tracking.",
  },
  {
    name: "Query Workspace",
    route: "/workspace",
    description: "Saved queries, execution flow, and analyst workspace shell.",
  },
];

export default function OperatingCenterPage() {
  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.4rem", lineHeight: 1.05 }}>Unified Product Operating Center</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 820 }}>
              This route brings the current module surfaces together in one place so the product can be navigated like a single system rather than a set of disconnected pages.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Operating Center</div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
          {modules.map((module) => (
            <div key={module.route} style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
              <h2 style={{ marginTop: 0 }}>{module.name}</h2>
              <p style={{ color: "#5a5374" }}>{module.description}</p>
              <Link href={module.route} style={{ display: "inline-flex", textDecoration: "none", padding: "10px 14px", borderRadius: 12, background: "#1f1736", color: "white", fontWeight: 700 }}>
                Open module
              </Link>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
