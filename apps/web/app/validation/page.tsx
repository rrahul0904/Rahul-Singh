import { getValidationResults, getValidationRuns } from "../../lib/validationClient";

function severityStyle(level: "Low" | "Medium" | "High") {
  if (level === "Low") return { background: "#eef8ef", color: "#207049" };
  if (level === "Medium") return { background: "#fff7e8", color: "#9c6512" };
  return { background: "#fdebec", color: "#9c2f3b" };
}

function statusStyle(status: "Passed" | "Warning" | "Failed") {
  if (status === "Passed") return { background: "#eef8ef", color: "#207049" };
  if (status === "Warning") return { background: "#fff7e8", color: "#9c6512" };
  return { background: "#fdebec", color: "#9c2f3b" };
}

export default async function ValidationPage() {
  const runs = await getValidationRuns();
  const activeRun = runs[0] ?? null;
  const results = activeRun ? await getValidationResults(activeRun.id) : [];

  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.2rem", lineHeight: 1.1 }}>Validation and Reconciliation</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 760 }}>
              This module tracks validation runs and highlights mismatches before cutover so teams can review risk clearly.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Validation</div>
        </section>

        <section style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Object</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Rule</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Severity</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Result</th>
              </tr>
            </thead>
            <tbody>
              {results.map((item) => (
                <tr key={item.id}>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb", fontWeight: 700 }}>{item.object_name}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>{item.rule_type}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}><span style={{ display: "inline-flex", padding: "6px 10px", borderRadius: 999, fontWeight: 700, ...severityStyle(item.severity) }}>{item.severity}</span></td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}><span style={{ display: "inline-flex", padding: "6px 10px", borderRadius: 999, fontWeight: 700, ...statusStyle(item.result_status) }}>{item.result_status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </main>
  );
}
