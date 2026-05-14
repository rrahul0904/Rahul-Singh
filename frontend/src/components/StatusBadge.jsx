import React from "react";

const STATUS_CLASS = {
  SUCCEEDED: "bg badge-dot",
  SUCCESS: "bg badge-dot",
  COMPLETED: "bg badge-dot",
  READY: "bg badge-dot",
  PASS: "bg badge-dot",
  PASSED: "bg badge-dot",
  CONVERTED: "bg badge-dot",
  HEALTHY: "bg badge-dot",
  RUNNING: "bb badge-dot",
  ACTIVE: "bb badge-dot",
  QUEUED: "bb badge-dot",
  PLANNED: "bb badge-dot",
  UPLOADED: "bb badge-dot",
  ANALYZING: "bb badge-dot",
  CONVERTING: "bb badge-dot",
  AI_REVIEWING: "bb badge-dot",
  JUDGING: "bb badge-dot",
  REPAIRING: "bb badge-dot",
  WARNING: "by badge-dot",
  PARTIALLY_SUCCEEDED: "by badge-dot",
  PAUSED: "by badge-dot",
  MEDIUM: "by badge-dot",
  CONVERTED_WITH_WARNINGS: "by badge-dot",
  REQUIRES_REVIEW: "by badge-dot",
  PASSED_WITH_WARNINGS: "by badge-dot",
  FAILED: "br badge-dot",
  FAIL: "br badge-dot",
  ERROR: "br badge-dot",
  HIGH: "br badge-dot",
  BLOCKED: "br badge-dot",
  CANCELLED: "bgr badge-dot",
  PENDING: "bgr badge-dot",
  DRAFT: "bgr badge-dot",
  NOT_CONFIGURED: "bgr badge-dot",
  NOT_CHECKED: "bgr badge-dot",
  UNKNOWN: "bgr",
  true: "bg badge-dot",
  false: "bgr badge-dot",
};

function labelFor(value, label) {
  if (label) return label;
  if (value === true) return "Yes";
  if (value === false) return "No";
  if (value == null || value === "") return "Unknown";
  return String(value)
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function StatusBadge({ status, label, tone = "" }) {
  const key = typeof status === "string" ? status.toUpperCase() : String(status);
  const cls = tone || STATUS_CLASS[key] || "bgr";
  return <span className={`badge ${cls}`}>{labelFor(status, label)}</span>;
}
