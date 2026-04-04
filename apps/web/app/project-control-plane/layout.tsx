import Link from "next/link";
import React from "react";

export default function ProjectControlPlaneLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <nav style={{ display: "flex", gap: 12, padding: 16, borderBottom: "1px solid #ece5fb", background: "#ffffff" }}>
        <Link href="/project-control-plane">Project Control Plane</Link>
        <Link href="/project-control-plane/new">Create Project</Link>
        <Link href="/">Main App</Link>
      </nav>
      {children}
    </div>
  );
}
