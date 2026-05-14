import React from "react";

export default function EmptyState({ title = "Nothing to show yet", message = "", action = null, compact = false }) {
  return (
    <div className="empty-state" style={{ padding: compact ? 16 : 24, border: "1px solid var(--border)", borderRadius: "var(--r)", background: "var(--bg3)", textAlign: "center" }}>
      <div className="empty-title" style={{ fontWeight: 850, color: "var(--text)" }}>{title}</div>
      {message ? <div className="empty-copy" style={{ margin: "6px auto 0", maxWidth: 520, color: "var(--text3)", fontSize: 12, lineHeight: 1.55 }}>{message}</div> : null}
      {action ? <div style={{ marginTop: 12 }}>{action}</div> : null}
    </div>
  );
}
