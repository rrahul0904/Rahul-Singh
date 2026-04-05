import Link from "next/link";

const sections = [
  {
    title: "Integrated API shell",
    detail: "Use main_integrated.py for a single-process product shell across all core modules.",
  },
  {
    title: "Stateful API shell",
    detail: "Use main_stateful_phase2.py when you want JSON-backed persistence across most core modules.",
  },
  {
    title: "Frontend route flow",
    detail: "Operating Center → Project Control Plane → Discovery → Conversion → Validation → Workspace → Stateful Lab.",
  },
  {
    title: "Smoke tests",
    detail: "Use the smoke-test playbook to verify health endpoints, module routes, and stateful write actions.",
  },
];

export default function DemoReadinessPage() {
  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.4rem", lineHeight: 1.05 }}>Demo Readiness</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 820 }}>
              This route collects the most important product-shell guidance in one place so the demo can be run without hunting through scattered docs.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Readiness</div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
          {sections.map((section) => (
            <div key={section.title} style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
              <h2 style={{ marginTop: 0 }}>{section.title}</h2>
              <p style={{ color: "#5a5374" }}>{section.detail}</p>
            </div>
          ))}
        </section>

        <div style={{ marginTop: 24, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link href="/operating-center" style={{ display: "inline-flex", textDecoration: "none", padding: "10px 14px", borderRadius: 12, background: "#1f1736", color: "white", fontWeight: 700 }}>
            Open Operating Center
          </Link>
          <Link href="/stateful-lab" style={{ display: "inline-flex", textDecoration: "none", padding: "10px 14px", borderRadius: 12, background: "#f5f0ff", color: "#4d2fa9", fontWeight: 700 }}>
            Open Stateful Lab
          </Link>
        </div>
      </div>
    </main>
  );
}
