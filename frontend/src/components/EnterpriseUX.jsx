import React from "react";

const TONE_BY_STATUS = {
  COMPLETE: "success",
  COMPLETED: "success",
  PASSED: "success",
  PASS: "success",
  READY: "success",
  GOLDEN_PATH: "success",
  RUNNING: "running",
  ACTIVE: "running",
  IN_REVIEW: "review",
  REQUIRES_REVIEW: "review",
  APPROVAL_REQUIRED: "review",
  NEEDS_REWORK: "review",
  WARNING: "warning",
  WARN: "warning",
  BETA: "warning",
  PREVIEW: "info",
  CONNECTOR_ONLY: "info",
  PLANNED: "info",
  NOT_STARTED: "neutral",
  PENDING: "neutral",
  SKIPPED: "neutral",
  COMING_SOON: "neutral",
  BLOCKED: "danger",
  FAILED: "danger",
  FAIL: "danger",
  ERROR: "danger",
  CRITICAL: "danger",
  HIGH: "danger",
};

function labelFor(value, label) {
  if (label) return label;
  if (value === true) return "Supported";
  if (value === false) return "Not supported";
  if (value == null || value === "") return "Unknown";
  return String(value).replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
}

function toneFor(status) {
  const key = typeof status === "string" ? status.toUpperCase() : String(status);
  return TONE_BY_STATUS[key] || "neutral";
}

export function StatusPill({ status, label }) {
  const tone = toneFor(status);
  return <span className={`ux-status ux-status-${tone}`}>{labelFor(status, label)}</span>;
}

export function AnimatedCard({ children, className = "", delay = 0, ...props }) {
  return (
    <div className={`ux-card ${className}`} style={{ "--ux-delay": `${delay}ms` }} {...props}>
      {children}
    </div>
  );
}

export function PageTransition({ children, className = "" }) {
  return <div className={`ux-page-transition ${className}`}>{children}</div>;
}

export function SkeletonState({ rows = 4, title = "Loading workspace state" }) {
  return (
    <div className="ux-skeleton-wrap" aria-label={title}>
      {Array.from({ length: rows }).map((_, index) => (
        <div className="ux-skeleton-row" key={index}>
          <span className="ux-skeleton-dot" />
          <span className="ux-skeleton-line" />
          <span className="ux-skeleton-short" />
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ title = "Unable to load this state", message = "", action = null }) {
  return (
    <div className="ux-error-state">
      <div className="ux-error-icon">!</div>
      <div>
        <div className="ux-error-title">{title}</div>
        {message ? <div className="ux-error-message">{message}</div> : null}
        {action ? <div className="mt3">{action}</div> : null}
      </div>
    </div>
  );
}

export function MotionChecklist({ checks = [] }) {
  return (
    <div className="ux-checklist">
      {checks.map((check, index) => {
        const status = check.status || "pending";
        const tone = toneFor(status);
        return (
          <div className={`ux-check-row ux-check-${tone}`} key={`${check.label}-${index}`} style={{ "--ux-delay": `${index * 45}ms` }}>
            <span className="ux-check-icon">{tone === "running" ? "↻" : tone === "success" ? "✓" : tone === "danger" ? "!" : tone === "warning" ? "!" : "•"}</span>
            <div className="ux-check-main">
              <div className="ux-check-label">{check.label}</div>
              {check.detail ? <div className="ux-check-detail">{check.detail}</div> : null}
            </div>
            <StatusPill status={status} label={check.statusLabel} />
          </div>
        );
      })}
    </div>
  );
}

export function MigrationJourneyRail({ stages = [] }) {
  return (
    <div className="ux-journey-rail">
      {stages.map((stage, index) => {
        const status = stage.status || "not_started";
        const tone = toneFor(status);
        return (
          <div className={`ux-journey-stage ux-journey-${tone}`} key={stage.label} style={{ "--ux-delay": `${index * 35}ms` }}>
            <div className="ux-journey-node">{index + 1}</div>
            <div className="ux-journey-copy">
              <div className="ux-journey-label">{stage.label}</div>
              <StatusPill status={status} label={stage.statusLabel} />
              {stage.detail ? <div className="ux-journey-detail">{stage.detail}</div> : null}
            </div>
            {index < stages.length - 1 ? <div className="ux-journey-line" /> : null}
          </div>
        );
      })}
    </div>
  );
}

export function RunTimeline({ phases = [] }) {
  return (
    <div className="ux-run-timeline">
      {phases.map((phase, index) => {
        const status = phase.status || "pending";
        const tone = toneFor(status);
        const progress = Math.max(0, Math.min(100, Number(phase.progress ?? (tone === "success" ? 100 : tone === "running" ? 58 : 0))));
        return (
          <div className={`ux-run-phase ux-run-${tone}`} key={phase.label} style={{ "--ux-delay": `${index * 50}ms` }}>
            <div className="ux-run-phase-head">
              <div>
                <div className="ux-run-label">{phase.label}</div>
                <div className="ux-run-detail">{phase.detail || phase.table || "Waiting for this phase"}</div>
              </div>
              <StatusPill status={phase.status} />
            </div>
            <div className="ux-progress"><span style={{ width: `${progress}%` }} /></div>
            <div className="ux-run-meta">
              <span>{phase.rows ?? "0"} rows</span>
              <span>{phase.bytes || "0 B"}</span>
              {phase.logs ? <button className="ux-link-button" onClick={phase.logs}>Logs</button> : null}
              {phase.retry ? <button className="ux-link-button" onClick={phase.retry}>Retry</button> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ValidationChecklist({ checks = [] }) {
  return <MotionChecklist checks={checks} />;
}

export function EnterpriseToolCard({ tool, onOpen, delay = 0 }) {
  return (
    <AnimatedCard className={`ux-tool-card ${tool.disabled ? "ux-tool-disabled" : ""}`} delay={delay}>
      <div className="ux-tool-head">
        <div>
          <div className="ux-tool-name">{tool.title}</div>
          <div className="ux-tool-desc">{tool.helps}</div>
        </div>
        <StatusPill status={tool.status} />
      </div>
      <div className="ux-tool-foot">
        <button className={tool.disabled ? "btn btn-ghost btn-sm" : "btn btn-primary btn-sm"} disabled={tool.disabled} onClick={() => !tool.disabled && onOpen?.(tool.id)}>
          {tool.action}
        </button>
      </div>
    </AnimatedCard>
  );
}

export function ReviewItemCard({ item, selected = false, onClick }) {
  return (
    <button className={`ux-review-card ${selected ? "active" : ""}`} onClick={onClick}>
      <div className="ux-review-card-head">
        <StatusPill status={item.severity} />
        <StatusPill status={item.status} />
      </div>
      <div className="ux-review-title">{item.title}</div>
      <div className="ux-review-meta">{item.source_object || item.source_file || "Source artifact"} → {item.target_object || "Snowflake target"}</div>
      <div className="ux-review-finding">{item.reason || item.description || item.finding || "Review required before approval."}</div>
      <div className="ux-review-action">{item.recommendation || "Open the item and decide approve, reject, assign, or resolve."}</div>
    </button>
  );
}
