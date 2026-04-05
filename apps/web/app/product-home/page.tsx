import Link from "next/link";

const modules = [
  {
    name: "Operating Center",
    route: "/operating-center",
    description: "Unified navigation hub across the product modules.",
  },
  {
    name: "Project Control Plane",
    route: "/project-control-plane",
    description: "Projects, inventory, ownership, and migration progress.",
  },
  {
    name: "Discovery",
    route: "/discovery",
    description: "Discovery runs, complexity, and assessment outputs.",
  },
  {
    name: "Conversion",
    route: "/conversion",
    description: "Conversion workbench for source-to-target artifacts.",
  },
  {
    name: "Validation",
    route: "/validation",
    description: "Validation runs, warnings, and failed checks.",
  },
  {
    name: "Workspace",
    route: "/workspace",
    description: "Saved queries and analyst workspace shell.",
  },
];

export default function ProductHomePage() {
  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "40px 24px 64px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 28 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.7rem", lineHeight: 1.02 }}>Unified Data Migration Accelerator</h1>
            <p style={{ marginTop: 12, color: "#5a5374", maxWidth: 860, fontSize: "1.05rem" }}>
              A unified product shell for migration planning, discovery, conversion, validation, and analyst workflows.
              This route gives the app a cleaner entry surface into the current product modules.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 700, fontSize: "0.92rem" }}>Product Home</div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16, marginBottom: 28 }}>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <div style={{ color: "#6a6384", marginBottom: 8 }}>Core modules</div>
            <div style={{ fontSize: "2rem", fontWeight: 800 }}>5+</div>
          </div>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <div style={{ color: "#6a6384", marginBottom: 8 }}>Persistent shell</div>
            <div style={{ fontSize: "2rem", fontWeight: 800 }}>Enabled</div>
          </div>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <div style={{ color: "#6a6384", marginBottom: 8 }}>Demo readiness</div>
            <div style={{ fontSize: "2rem", fontWeight: 800 }}>Packaged</div>
          </div>
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
