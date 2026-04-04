import Link from "next/link";

export default function ProjectControlPlaneNotFound() {
  return (
    <main style={{ minHeight: "70vh", display: "grid", placeItems: "center", padding: 24, background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)" }}>
      <div style={{ maxWidth: 640, width: "100%", background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 24, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
        <h1 style={{ marginTop: 0 }}>Project not found</h1>
        <p style={{ color: "#5a5374" }}>
          The project you tried to open is not available in the current Phase 1 demo store. Return to the control plane
          and choose one of the seeded projects.
        </p>
        <Link href="/project-control-plane">Back to Project Control Plane</Link>
      </div>
    </main>
  );
}
