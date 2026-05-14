import React from "react";

export default function LoadingPanel({ label = "Loading" }) {
  return (
    <div className="pq-loading-panel">
      <span className="spin" aria-hidden="true">↻</span>
      <span>{label}</span>
    </div>
  );
}
