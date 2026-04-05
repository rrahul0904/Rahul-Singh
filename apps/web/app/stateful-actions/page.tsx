"use client";

import { useState } from "react";

import { createStatefulProject, createStatefulQuery, executeStatefulQuery } from "../../lib/statefulClient";

export default function StatefulActionsPage() {
  const [projectStatus, setProjectStatus] = useState("Idle");
  const [queryStatus, setQueryStatus] = useState("Idle");
  const [executeStatus, setExecuteStatus] = useState("Idle");

  async function handleCreateProject() {
    setProjectStatus("Submitting...");
    try {
      const project = await createStatefulProject({
        name: "Browser Created Project",
        description: "Created from the interactive stateful actions page.",
        source_platform: "Oracle",
        target_platform: "Snowflake",
        owner: "Rahul",
      });
      setProjectStatus(`Created ${project.id}`);
    } catch (error) {
      setProjectStatus(error instanceof Error ? error.message : "Project creation failed");
    }
  }

  async function handleCreateQuery() {
    setQueryStatus("Submitting...");
    try {
      const query = await createStatefulQuery({
        name: "browser_saved_query",
        sql_text: "SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC",
        owner: "Rahul",
      });
      setQueryStatus(`Saved ${query.id}`);
    } catch (error) {
      setQueryStatus(error instanceof Error ? error.message : "Query save failed");
    }
  }

  async function handleExecuteQuery() {
    setExecuteStatus("Submitting...");
    try {
      const result = await executeStatefulQuery(
        "SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC",
      );
      setExecuteStatus(`Returned ${result.rows.length} rows`);
    } catch (error) {
      setExecuteStatus(error instanceof Error ? error.message : "Execution failed");
    }
  }

  const cardStyle = {
    background: "#ffffff",
    border: "1px solid #ece5fb",
    borderRadius: 18,
    padding: 18,
    boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)",
  } as const;

  const buttonStyle = {
    padding: "10px 14px",
    borderRadius: 12,
    border: 0,
    background: "#1f1736",
    color: "white",
    fontWeight: 700,
    cursor: "pointer",
  } as const;

  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.4rem", lineHeight: 1.05 }}>Interactive Stateful Actions</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 820 }}>
              This page turns the earlier documentation-style stateful handoff into live browser-side actions against the persistent API shell.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Interactive</div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
          <div style={cardStyle}>
            <h2 style={{ marginTop: 0 }}>Create Project</h2>
            <p style={{ color: "#5a5374" }}>Posts to the persistent project route.</p>
            <button onClick={handleCreateProject} style={buttonStyle}>Create</button>
            <p style={{ marginTop: 12 }}>{projectStatus}</p>
          </div>
          <div style={cardStyle}>
            <h2 style={{ marginTop: 0 }}>Save Query</h2>
            <p style={{ color: "#5a5374" }}>Posts to the persistent workspace route.</p>
            <button onClick={handleCreateQuery} style={buttonStyle}>Save</button>
            <p style={{ marginTop: 12 }}>{queryStatus}</p>
          </div>
          <div style={cardStyle}>
            <h2 style={{ marginTop: 0 }}>Execute Query</h2>
            <p style={{ color: "#5a5374" }}>Runs against the persistent execution endpoint.</p>
            <button onClick={handleExecuteQuery} style={buttonStyle}>Execute</button>
            <p style={{ marginTop: 12 }}>{executeStatus}</p>
          </div>
        </section>
      </div>
    </main>
  );
}
