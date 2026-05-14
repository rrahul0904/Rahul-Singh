import React from "react";

export default function ErrorPanel({ error, title = "Unable to load this view" }) {
  if (!error) return null;
  const message = typeof error === "string" ? error : error?.message || "An unexpected error occurred.";
  return (
    <div className="alert-err pq-error-panel">
      <div style={{ fontWeight: 850, marginBottom: 4 }}>{title}</div>
      <div>{message}</div>
    </div>
  );
}
