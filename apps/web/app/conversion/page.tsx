import { getConversionItems } from "../../lib/conversionClient";

function riskStyle(risk: "Low" | "Medium" | "High") {
  if (risk === "Low") return { background: "#eef8ef", color: "#207049" };
  if (risk === "Medium") return { background: "#fff7e8", color: "#9c6512" };
  return { background: "#fdebec", color: "#9c2f3b" };
}

export default async function ConversionPage() {
  const items = await getConversionItems();

  return (
    <main style={{ minHeight: "100vh", background: "linear-gradient(180deg, #f7f4ff 0%, #ffffff 100%)", color: "#161126" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 24px 56px" }}>
        <section style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "2.2rem", lineHeight: 1.1 }}>Conversion Workbench</h1>
            <p style={{ marginTop: 10, color: "#5a5374", maxWidth: 760 }}>
              This module tracks source-to-target conversion artifacts, review workflow, and risk across the migration lifecycle.
            </p>
          </div>
          <div style={{ display: "inline-flex", padding: "8px 12px", borderRadius: 999, background: "#efe7ff", color: "#4d2fa9", fontWeight: 600, fontSize: "0.9rem" }}>Conversion</div>
        </section>

        <section style={{ background: "#ffffff", border: "1px solid #ece5fb", borderRadius: 18, padding: 18, boxShadow: "0 12px 30px rgba(87, 59, 155, 0.08)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Source Object</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Source Type</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Target Type</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Status</th>
                <th style={{ textAlign: "left", padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>Risk</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb", fontWeight: 700 }}>{item.source_object_name}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>{item.source_type}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>{item.target_type}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}>{item.status}</td>
                  <td style={{ padding: "12px 10px", borderBottom: "1px solid #eee7fb" }}><span style={{ display: "inline-flex", padding: "6px 10px", borderRadius: 999, fontWeight: 700, ...riskStyle(item.risk) }}>{item.risk}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </main>
  );
}
