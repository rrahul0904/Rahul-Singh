import { getSavedQueries } from "../../lib/workspaceClient";

export default async function WorkspacePage() {
  const queries = await getSavedQueries();

  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.2rem", lineHeight: 1.1 }}>Query Workspace</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 760 }}>
              This workspace is the analyst-facing surface for saved queries, prompt-to-SQL follow-ons, and result
              exploration. The backend route shape is now in the repo and this screen gives the module a usable UI shell.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Workspace</div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 16 }}>
          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <h2>Saved Queries</h2>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Name</th>
                  <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Owner</th>
                  <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>SQL Preview</th>
                </tr>
              </thead>
              <tbody>
                {queries.map((query) => (
                  <tr key={query.id}>
                    <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb", fontWeight: 700 }}>{query.name}</td>
                    <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>{query.owner}</td>
                    <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb", color: "#5a5374" }}>{query.sql_text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
            <h2>What comes next</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ border: "1px solid #ece5fb", borderRadius: 14, padding: 14, background: "#fcfbff" }}>
                <strong>Execute query panel</strong>
                <div style={{ marginTop: 6 }}>Connect this screen to live query execution and result rendering.</div>
              </div>
              <div style={{ border: "1px solid #ece5fb", borderRadius: 14, padding: 14, background: "#fcfbff" }}>
                <strong>Prompt-to-SQL</strong>
                <div style={{ marginTop: 6 }}>Layer AI-assisted SQL generation on top of the workspace APIs.</div>
              </div>
              <div style={{ border: "1px solid #ece5fb", borderRadius: 14, padding: 14, background: "#fcfbff" }}>
                <strong>Result charts</strong>
                <div style={{ marginTop: 6 }}>Add chart rendering and richer result tabs once live data is wired in.</div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
