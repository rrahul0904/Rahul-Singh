import React, { useEffect, useMemo, useState } from "react";
import * as api from "../api";
import StatusBadge from "../components/StatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import LoadingPanel from "../components/LoadingPanel.jsx";
import ErrorPanel from "../components/ErrorPanel.jsx";
import {
  EnterpriseToolCard,
  MigrationJourneyRail,
  PageTransition,
  RunTimeline,
  SkeletonState,
} from "../components/EnterpriseUX.jsx";
import { fmtDate, getErrorMessage } from "../components/format.js";

const DIALECTS = ["auto_detect", "bigquery", "teradata", "databricks", "spark", "oracle", "mysql", "sqlserver", "postgres", "hive"];
const SAFETY_MODES = ["READ_ONLY", "PLAN_ONLY", "VALIDATION_ONLY", "WRITE_APPROVED", "DEPLOY_APPROVED"];
const REPLICATION_STRATEGIES = ["full refresh", "incremental append", "incremental merge", "CDC ready"];
const VALIDATION_TYPES = ["row count", "schema compare", "null count", "hash aggregate", "sampled row diff"];
const WORKFLOW_STEPS = ["Discover", "Assess", "Convert", "Generate", "Validate", "Report"];
const HIDDEN_INPUT_CATEGORIES = new Set(["REPORT", "ADVISOR_RESULT", "VALIDATION_RESULT", "PROVISION_PLAN", "GENERATED_SQL", "GENERATED_DBT", "GENERATED_SQL_PATCH"]);
const REPORT_FOCUSED_CATEGORIES = new Set(["REPORT", "ADVISOR_RESULT", "VALIDATION_RESULT", "PROVISION_PLAN"]);
const ARTIFACT_FACTORY_GENERATION_TYPES = [
  "Snowflake DDL",
  "dbt project",
  "dbt staging model",
  "dbt incremental model",
  "dbt schema.yml",
  "dbt sources.yml",
  "Airflow DAG",
  "validation SQL",
  "reconciliation SQL",
  "migration runbook",
  "cutover checklist",
  "advisor remediation checklist",
  "executive report markdown/json",
];
const COPILOT_SUGGESTIONS = [
  "Summarize this migration run",
  "Explain SQL conversion warnings",
  "What risks need review?",
  "What dbt models should be created?",
  "Explain validation failures",
  "What Snowflake readiness issues exist?",
];

function formatLabel(value) {
  if (value == null || value === "") return "Not available";
  return String(value).replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function objectDisplayName(row = {}) {
  const raw = row.name || row.run_name || row.job_name || row.id || "Migration object";
  return String(raw).replace(/\bdemo\b\s*-?\s*/gi, "").trim();
}

function setSelectedMigrationRun(runId) {
  if (!runId || typeof window === "undefined") return;
  window.localStorage.setItem("uma.selectedRunId", runId);
  window.dispatchEvent(new CustomEvent("uma:selected-run-changed", { detail: { runId } }));
}

function filterArtifactsForModule(artifacts, allowedTypes = [], selectedRunId = "") {
  return (artifacts || []).filter((artifact) => {
    const inAllowedType = !allowedTypes.length || allowedTypes.includes(artifact.file_type) || allowedTypes.includes(artifact.artifact_category);
    if (!inAllowedType) return false;
    if (selectedRunId && artifact.run_id === selectedRunId) return true;
    if (artifact.run_id && artifact.run_id !== selectedRunId) return false;
    return !HIDDEN_INPUT_CATEGORIES.has(artifact.artifact_category);
  });
}

function summaryValue(value) {
  if (value == null || value === "") return "Not available";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "None";
  if (typeof value === "object") return "Available";
  return String(value);
}

function sqlPreviewFromStatements(statements = []) {
  return statements?.length ? { text: statements.join("\n") } : null;
}

function truncateSql(value = "", maxLines = 90) {
  const lines = String(value || "").split("\n");
  return lines.slice(0, maxLines).join("\n") + (lines.length > maxLines ? `\n-- ${lines.length - maxLines} more lines in generated artifact preview` : "");
}

function numberedSqlExcerpt(value = "", maxLines = 70) {
  const lines = String(value || "").split("\n");
  return lines.slice(0, maxLines).map((line, index) => `${String(index + 1).padStart(3, " ")}  ${line}`).join("\n")
    + (lines.length > maxLines ? `\n-- ${lines.length - maxLines} more lines in generated artifact preview` : "");
}

function inferConversionInputType(selectedArtifacts = [], allArtifacts = []) {
  const items = (selectedArtifacts || [])
    .map((id) => (allArtifacts || []).find((artifact) => artifact.id === id))
    .filter(Boolean);
  if (!items.length) return "sql_file";
  if (items.some((artifact) => artifact.artifact_category === "DBT_PROJECT")) return "dbt_project";
  if (items.every((artifact) => artifact.file_type === "ddl" || artifact.artifact_category === "SOURCE_DDL")) return "ddl_export";
  if (items.some((artifact) => /procedure|proc/i.test(artifact.original_filename || ""))) return "stored_procedure";
  if (items.some((artifact) => artifact.file_type === "zip")) return "mixed_zip";
  return "sql_file";
}

function validationResultRows(report) {
  if (Array.isArray(report?.results)) return report.results;
  if (Array.isArray(report?.tables)) {
    return report.tables.map((table) => ({
      table: table.table,
      check_type: "plan",
      source_value: "Not executed",
      target_value: "Not executed",
      status: table.status || "PLANNED",
      difference: table.max_differences ?? 0,
      recommendation: "Review generated SQL and execute only after approval in VALIDATION_ONLY mode.",
    }));
  }
  return [];
}

function copilotServiceItems(services) {
  if (!services || typeof services !== "object") {
    return [
      { label: "Snowflake Intelligence", value: "Unknown" },
      { label: "Cortex status", value: "Unknown" },
      { label: "Analyst status", value: "Unknown" },
      { label: "Search status", value: "Unknown" },
    ];
  }
  return [
    { label: "Snowflake Intelligence", value: services.status || services.message || "Available" },
    { label: "Cortex status", value: services.cortex_status || services.cortex || "Not reported" },
    { label: "Analyst status", value: services.analyst_status || services.analyst || "Not reported" },
    { label: "Search status", value: services.search_status || services.search || "Not reported" },
  ];
}

const MIGRATION_JOURNEY_LABELS = ["Connect", "Inventory", "Analyze", "Convert", "Brain Review", "Migrate", "Validate", "Report", "Cutover"];
const RUN_PHASE_LABELS = ["Extract", "Stage", "Load", "Merge", "Validate", "Report"];

function workflowStatusFromRun(run, summary = {}) {
  if (!run && summary.failed) return "blocked";
  if (!run && summary.review) return "requires_review";
  if (!run) return "not_started";
  const status = String(run.status || "").toUpperCase();
  if (["FAILED", "ERROR"].includes(status)) return "failed";
  if (["BLOCKED"].includes(status)) return "blocked";
  if (["REQUIRES_REVIEW", "APPROVAL_REQUIRED", "IN_REVIEW", "NEEDS_REWORK"].includes(status)) return "requires_review";
  if (["RUNNING", "QUEUED", "STARTED"].includes(status)) return "running";
  if (["COMPLETED", "SUCCEEDED", "SUCCESS"].includes(status)) return "complete";
  return "not_started";
}

function buildMigrationJourney(selectedRun, summary = {}) {
  const currentPhase = String(selectedRun?.current_phase || selectedRun?.workflow_type || "").toUpperCase();
  const runStatus = workflowStatusFromRun(selectedRun, summary);
  return MIGRATION_JOURNEY_LABELS.map((label, index) => {
    let status = index < 2 ? "complete" : "not_started";
    if (summary.total && index === 2) status = "complete";
    if (/CONVERT|SQL|DBT/.test(currentPhase) && index === 3) status = runStatus;
    if (["requires_review", "blocked", "failed"].includes(runStatus) && index === 4) status = runStatus;
    if (selectedRun?.workflow_type === "DATA_VALIDATION" && index === 6) status = runStatus;
    if (selectedRun?.report_artifact || selectedRun?.status === "COMPLETED") status = index <= 7 ? "complete" : status;
    if (!selectedRun && index > 2) status = "not_started";
    return { label, status };
  });
}

function buildRunTimeline(run, jobs = [], artifacts = []) {
  const status = workflowStatusFromRun(run);
  return RUN_PHASE_LABELS.map((label, index) => {
    const job = jobs.find((item) => String(item.phase || item.module || "").toLowerCase().includes(label.toLowerCase()));
    const completeByArtifact = label === "Report" && artifacts.some((artifact) => artifact.artifact_category === "REPORT");
    let phaseStatus = index === 0 && !run ? "pending" : index < 2 ? "complete" : "pending";
    if (job) phaseStatus = workflowStatusFromRun(job);
    if (completeByArtifact) phaseStatus = "complete";
    if (run && index === 2 && status === "running") phaseStatus = "running";
    if (run && index === 4 && ["requires_review", "blocked", "failed"].includes(status)) phaseStatus = status;
    return {
      label,
      status: phaseStatus,
      detail: job?.phase || job?.module || (completeByArtifact ? "Evidence pack generated" : `${label} waits for the prior gate`),
      rows: job?.output_json?.rows_loaded || job?.output_json?.row_count || "0",
      bytes: job?.output_json?.bytes_moved || "0 B",
      progress: phaseStatus === "complete" ? 100 : phaseStatus === "running" ? 62 : 0,
    };
  });
}

function buildValidationChecks(report) {
  const rows = validationResultRows(report);
  const findStatus = (name) => {
    const row = rows.find((item) => String(item.check_type || item.validation_type || "").toLowerCase().includes(name));
    if (!row) return report ? "planned" : "pending";
    const status = String(row.status || "").toUpperCase();
    if (["PASS", "PASSED", "COMPLETED", "SUCCESS"].includes(status)) return "passed";
    if (["WARN", "WARNING"].includes(status)) return "warning";
    if (["FAIL", "FAILED", "ERROR"].includes(status)) return "failed";
    if (["SKIPPED"].includes(status)) return "skipped";
    return "planned";
  };
  return [
    { label: "Schema match", status: findStatus("schema"), detail: "Column names, ordering, and compatible target types." },
    { label: "Row count", status: findStatus("row"), detail: "Source and Snowflake row counts within tolerance." },
    { label: "Null count", status: findStatus("null"), detail: "Nullable column distributions checked by table." },
    { label: "Aggregate checks", status: findStatus("aggregate"), detail: "Numeric totals, min/max, and business aggregates." },
    { label: "Hash/checksum", status: findStatus("hash"), detail: "Deterministic row or partition hashes where supported." },
    { label: "Sample row diff", status: findStatus("sample"), detail: "Sampled mismatches link to UMA Brain Review." },
    { label: "Business rules", status: findStatus("business"), detail: "Customer-defined assertions and tolerance thresholds." },
  ];
}

function PageHeader({ title, subtitle, status, primaryAction, secondaryAction }) {
  return (
    <div className="page-header">
      <div className="page-header-copy">
        <div className="page-eyebrow">Migration Control Plane</div>
        <div className="page-title">{title}</div>
        <div className="page-subtitle">{subtitle}</div>
        {status ? <div className="mt2"><StatusBadge status={status} /></div> : null}
      </div>
      {(primaryAction || secondaryAction) ? (
        <div className="page-actions">
          {secondaryAction}
          {primaryAction}
        </div>
      ) : null}
    </div>
  );
}

function WorkflowStepper({ active = 0 }) {
  return (
    <div className="steps">
      {WORKFLOW_STEPS.map((step, index) => (
        <React.Fragment key={step}>
          <div className={`step ${index < active ? "done" : index === active ? "active" : ""}`}>
            <div className="sdot2">{index + 1}</div>
            <div className="step-lbl">{step}</div>
          </div>
          {index < WORKFLOW_STEPS.length - 1 ? <div className="step-line" /> : null}
        </React.Fragment>
      ))}
    </div>
  );
}

function StatCard({ label, value, trend, help }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value ?? "0"}</div>
      <div className="stat-change">{trend || help || ""}</div>
    </div>
  );
}

function SeverityBadge({ severity }) {
  return <StatusBadge status={severity} />;
}

function SectionCard({ title, subtitle, actions, loading, error, empty, children }) {
  return (
    <div className="card ep-card">
      <div className="card-header ep-card-header">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="card-title">{title}</div>
          {subtitle ? <div className="text-muted mt2">{subtitle}</div> : null}
        </div>
        {actions}
      </div>
      <div style={{ padding: 16 }}>
        {loading ? <LoadingPanel label={`Loading ${title.toLowerCase()}`} /> : null}
        {!loading && error ? <ErrorPanel error={error} /> : null}
        {!loading && !error && empty ? empty : null}
        {!loading && !error && !empty ? children : null}
      </div>
    </div>
  );
}

function DataTable({ columns, rows, onRowClick, emptyTitle, emptyMessage, emptyAction }) {
  if (!rows?.length) {
    return <EmptyState title={emptyTitle || "No rows yet"} message={emptyMessage || "No result generated yet."} action={emptyAction} compact />;
  }
  return (
    <div className="table-scroll">
      <table className="tbl">
        <thead>
          <tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || `${index}`} onClick={onRowClick ? () => onRowClick(row) : undefined} style={onRowClick ? { cursor: "pointer" } : undefined}>
              {columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OperationsAlertStrip({ items = [], fallback = "No open blockers. Continue with the next planned migration action.", activeId = "" }) {
  const visible = items.filter(Boolean).slice(0, 3);
  const activeItem = visible.find((item) => String(item.id || "") === String(activeId || "")) || visible[0];
  return (
    <div className={`ep-alert-strip ${visible.length ? "has-blockers" : ""}`}>
      <div>
        <div className="ep-alert-kicker">{visible.length ? `${visible.length} priority blocker${visible.length === 1 ? "" : "s"}` : "No critical blockers"}</div>
        <div className="ep-alert-title">{activeItem?.title || fallback}</div>
      </div>
      <div className="ep-alert-items">
        {visible.length ? visible.map((item, index) => (
          <button key={item.id || index} type="button" className={`ep-alert-item ${String(item.id || "") === String(activeId || "") ? "active" : ""}`} onClick={item.onClick}>
            <StatusBadge status={item.status || "REQUIRES_REVIEW"} />
            <span className="ep-alert-copy">
              <strong>{item.title || "Open blocker"}</strong>
              <span>{item.action || "Open evidence"}</span>
            </span>
          </button>
        )) : <span className="ep-alert-ok">Workspace is clear</span>}
      </div>
    </div>
  );
}

function EnterpriseKpiRow({ items = [] }) {
  return (
    <div className="ep-kpi-row">
      {items.map((item) => {
        const Tag = item.onClick ? "button" : "div";
        return (
        <Tag
          type={item.onClick ? "button" : undefined}
          className={`ep-kpi ${item.active ? "active" : ""}`}
          key={item.label}
          onClick={item.onClick}
          aria-label={item.onClick ? `Open ${item.label} details` : undefined}
        >
          <div className="ep-kpi-label">{item.label}</div>
          <div className="ep-kpi-value">{item.value}</div>
          <div className="ep-kpi-note">{item.note}</div>
        </Tag>
      );})}
    </div>
  );
}

function ObjectDetailPanel({ title, subtitle, status, actions, children, empty }) {
  return (
    <aside className="ep-detail-panel">
      <div className="ep-detail-head">
        <div>
          <div className="ep-detail-title">{title}</div>
          {subtitle ? <div className="ep-detail-subtitle">{subtitle}</div> : null}
        </div>
        {status ? <StatusBadge status={status} /> : null}
      </div>
      {actions ? <div className="ep-detail-actions">{actions}</div> : null}
      <div className="ep-detail-body">{empty || children}</div>
    </aside>
  );
}

function WorkspaceTabs({ tabs, active, onChange }) {
  return (
    <div className="tabs">
      {tabs.map((tab) => (
        <div key={tab.id} className={`tab ${active === tab.id ? "active" : ""}`} onClick={() => onChange(tab.id)}>
          {tab.label}
        </div>
      ))}
    </div>
  );
}

function ContextRail({ title = "Context", items = [], cta = null }) {
  return (
    <SectionCard title={title} subtitle="Live workspace context for the current module and selected run.">
      <SummaryList items={items.filter((item) => item)} />
      {cta ? <div className="mt3">{cta}</div> : null}
    </SectionCard>
  );
}

function FooterActionBar({ actions = [] }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="card-title">Recommended next actions</div>
          <div className="text-muted mt2">These actions continue the migration flow without executing SQL, dbt, or provisioning by default.</div>
        </div>
      </div>
      <div style={{ padding: 16, display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12 }}>
        {actions.map((action) => (
          <div key={action.title} className="info-tile">
            <div className="td-main">{action.title}</div>
            <div className="text-muted mt2">{action.description}</div>
            <div className="text-muted mt2">{action.reuse}</div>
            <div className="mt3">
              {action.button}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CopyButton({ value }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  };
  return <button className="btn btn-ghost btn-sm" onClick={copy}>{copied ? "Copied" : "Copy"}</button>;
}

function asArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function compactUnique(items = []) {
  return [...new Set(items.map((item) => String(item || "").trim()).filter(Boolean))];
}

function fileDisplayName(file = {}) {
  const raw = file.source_path || file.file_name || file.target_path || "Unknown file";
  const afterArchive = String(raw).split(":").pop();
  return afterArchive.split("/").pop() || afterArchive || String(raw);
}

function percentLabel(value) {
  if (value == null || value === "") return "Not available";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  const percent = numeric <= 1 ? numeric * 100 : numeric;
  return `${Math.round(percent)}%`;
}

function numericConfidence(value) {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric <= 1 ? numeric * 100 : numeric;
}

function hasText(value) {
  return String(value || "").trim().length > 0;
}

function containsAny(value, terms = []) {
  const text = String(value || "").toLowerCase();
  return terms.some((term) => text.includes(term.toLowerCase()));
}

function brainInventory(report) {
  const nodes = report?.conversion_context?.nodes || report?.graph || [];
  const uploadNode = nodes.find((node) => node.node === "UploadInventoryNode");
  return uploadNode?.output?.files || report?.inventory || [];
}

function brainFilesFromReport(report) {
  return report?.conversion_context?.files || report?.file_reports || [];
}

function conversionJobState(report, selectedRun) {
  return report?.job_state || selectedRun?.summary_json?.job_state || selectedRun?.job_state || {};
}

export function conversionQualityBlocks(state = {}) {
  const blocks = [];
  if (state.snowflake_ready === false) blocks.push("Snowflake-ready is false.");
  if (state.judge_status === "failed") blocks.push("Judge status is failed.");
  if (Number(state.rules_applied_count || 0) === 0) blocks.push("No conversion rules were applied.");
  if ((state.source_residue || []).length) blocks.push(`Source residue remains: ${(state.source_residue || []).join(", ")}.`);
  return blocks;
}

export function conversionDownloadAllowed(state = {}) {
  return state.snowflake_ready === true
    && state.judge_status !== "failed"
    && Number(state.rules_applied_count || 0) > 0
    && !(state.source_residue || []).length
    && ["validation_passed", "waived_by_brain_review"].includes(state.validation_status);
}

function conversionProductStatus(state = {}) {
  if (state.status === "failed" || state.judge_status === "failed") return "Failed";
  if (state.status === "requires_review" || state.manual_review_required) return "Requires Review";
  if (state.status === "converted_with_warnings" || state.judge_status === "passed_with_warnings" || (state.warnings || []).length) return "Converted with Warnings";
  if (state.status === "converted" || state.snowflake_ready === true) return "Converted";
  if (state.status) return formatLabel(state.status);
  return "Uploaded";
}

function fileReviewStatus(file = {}) {
  const status = String(file.conversion_status || "").toUpperCase();
  if (status === "FAILED" || file.judge_status === "failed") return "Failed";
  if (status === "REQUIRES_REVIEW" || file.manual_review_required) return "Requires Review";
  if (status === "CONVERTED_WITH_WARNINGS" || file.judge_status === "passed_with_warnings" || (file.warnings || []).length) return "Converted with Warnings";
  if (status === "COMPLETED" || file.snowflake_ready) return "Converted";
  return formatLabel(file.conversion_status || "Not converted");
}

export function readinessReason(state = {}, files = []) {
  if (state.snowflake_ready) return "All quality gates passed. Snowflake-ready artifacts can be downloaded.";
  if (state.judge_status === "failed") return "Judge blocked readiness because one or more files failed conversion quality gates.";
  if (state.validation_status === "compile_passed") return "dbt compile passed, but real Snowflake connection, permission, and EXPLAIN validation still must pass.";
  if (state.validation_status && !["validation_passed", "waived_by_brain_review"].includes(state.validation_status)) return `Snowflake validation gate is ${formatLabel(state.validation_status)}.`;
  if ((state.source_residue || []).length) return `BigQuery residue remains: ${(state.source_residue || []).join(", ")}.`;
  const reasons = compactUnique([...(state.readiness_reasons || []), ...files.flatMap((file) => file.readiness_reasons || [])].map((reason) => reason.message || reason));
  if (reasons.length) {
    return "SQL syntax conversion completed, but " + reasons[0].charAt(0).toLowerCase() + reasons[0].slice(1);
  }
  if (state.manual_review_required) {
    const warnings = compactUnique([...(state.warnings || []), ...files.flatMap((file) => file.warnings || [])]);
    if (warnings.length) return warnings[0];
    return "Manual dbt review is required before this can be marked Snowflake-ready.";
  }
  if (Number(state.rules_applied_count || 0) === 0) return "No conversion rules were applied, so UMA will not mark the output as converted.";
  return "Snowflake validation has not been run.";
}

export function modelIssueCards(file = {}, state = {}) {
  const cards = [];
  const residue = file.source_residue || [];
  const rules = file.rules_applied || [];
  const errors = file.errors || [];
  const warnings = file.warnings || [];
  const readinessReasons = [...(state.readiness_reasons || []), ...(file.readiness_reasons || [])]
    .filter((reason, index, all) => all.findIndex((item) => item.message === reason.message) === index);
  if (rules.length && !residue.length) cards.push({ title: "BigQuery residue removed", tone: "ready", detail: "Checked BigQuery residue scanner found no remaining source dialect syntax for this model." });
  if (file.original_sql?.includes("{{") || file.original_sql?.includes("{%")) cards.push({ title: "dbt/Jinja preserved", tone: "ready", detail: "dbt config and Jinja blocks were protected and restored during conversion." });
  if (rules.length) cards.push({ title: "Snowflake syntax rewrites applied", tone: "ready", detail: rules.slice(0, 5).join(", ") });
  if (residue.length) cards.push({ title: "Source residue remains", tone: "blocked", detail: residue.join(", ") });
  errors.forEach((error) => cards.push({ title: "Judge blocker", tone: "blocked", detail: error }));
  readinessReasons.forEach((reason) => cards.push({
    title: formatLabel(reason.category || "readiness reason"),
    tone: reason.severity === "error" ? "blocked" : "review",
    detail: `${reason.message}${reason.recommended_action ? ` Recommended action: ${reason.recommended_action}` : ""}`,
  }));
  warnings.forEach((warning) => cards.push({ title: warning.toLowerCase().includes("ai review unavailable") ? "AI Review Unavailable" : "Manual review required", tone: "review", detail: warning }));
  if (!state.snowflake_ready) cards.push({ title: "Snowflake Validation Not Run", tone: "review", detail: "UMA did not connect to Snowflake or execute generated SQL during conversion." });
  return cards.length ? cards : [{ title: "No open issues", tone: "ready", detail: "No judge blockers, residue, or warnings are attached to this model." }];
}

function aiModeSummary(report = {}) {
  const provider = report?.ai_provider_status || {};
  const configured = Boolean(report?.ai_patch_available || report?.ai_review_available || provider.ai_patch_available || provider.ai_review_available || report?.llm_available);
  return {
    mode: configured ? "LLM-assisted review available" : "Deterministic only",
    rag: report?.rag_enabled ? "RAG-assisted context" : "RAG context unavailable",
    provider: provider.provider_name || report?.ai_provider_name || report?.llm_provider || "offline",
    model: provider.model_name || report?.ai_model_name || "offline",
    review: configured ? "AI review available" : "LLM-assisted review unavailable",
    patch: configured ? "AI patching available" : "AI patching unavailable",
    patchAvailable: Boolean(report?.ai_patch_available || provider.ai_patch_available || report?.llm_available),
  };
}

export function aiPatchProposalAllowed(report = {}) {
  return Boolean(aiModeSummary(report).patchAvailable);
}

export function validationCredentialsComplete(credentials = {}) {
  return ["account", "user", "role", "warehouse", "database", "schema"].every((key) => String(credentials[key] || "").trim())
    && Boolean(String(credentials.password || credentials.authenticator || credentials.auth_method || "").trim());
}

function downloadGroups(runArtifacts = [], canDownloadPackage = false) {
  const reviewCategories = new Set(["REPORT", "REVIEW_SQL", "REVIEW_DBT", "GENERATED_SQL_PATCH"]);
  const snowflakeCategories = new Set(["CONVERSION_PACKAGE", "GENERATED_SQL", "GENERATED_DBT"]);
  const review = (runArtifacts || []).filter((artifact) => {
    if (reviewCategories.has(artifact.artifact_category)) return true;
    return !canDownloadPackage && artifact.artifact_category === "CONVERSION_PACKAGE";
  });
  return {
    review,
    snowflake: canDownloadPackage ? (runArtifacts || []).filter((artifact) => snowflakeCategories.has(artifact.artifact_category)) : [],
  };
}

function inventoryForFile(file, inventory = []) {
  const name = fileDisplayName(file);
  return inventory.find((item) => {
    const itemName = fileDisplayName(item);
    return itemName === name || file.source_path === item.file_name || String(file.source_path || "").includes(String(item.file_name || "__missing__"));
  }) || {};
}

function fileSizeBytes(file, inventory = []) {
  const inv = inventoryForFile(file, inventory);
  const value = file.file_size ?? file.file_size_bytes ?? file.size_bytes ?? inv.size_bytes ?? inv.file_size;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function fileCombinedText(file = {}) {
  return [
    file.original_sql,
    file.converted_sql,
    file.diff,
    ...(file.rules_applied || []),
    ...(file.warnings || []),
    ...(file.unsupported_features || []),
    ...((file.agent_review_results?.findings || []).map((finding) => finding.finding)),
  ].join("\n");
}

function parserFailureText(file = {}) {
  const text = fileCombinedText(file);
  return containsAny(text, ["parser failure", "parser failed", "parse error", "parser-backed", "syntax error"]);
}

function isDbtBrainRun(report, files = []) {
  return containsAny(report?.input_type, ["dbt"]) || files.some((file) => {
    const metadata = file.dbt_metadata || {};
    return Object.keys(metadata).length || containsAny(file.original_sql, ["{{", "{%", "ref(", "source("]);
  });
}

function humanFileStatus(file = {}, report = {}, inventory = []) {
  const status = String(file.conversion_status || file.status || "").toUpperCase();
  const size = fileSizeBytes(file, inventory);
  const originalKnown = Object.prototype.hasOwnProperty.call(file, "original_sql");
  const convertedKnown = Object.prototype.hasOwnProperty.call(file, "converted_sql");
  const statementKnown = Object.prototype.hasOwnProperty.call(file, "statement_count");
  const blocked = status === "FAILED"
    || parserFailureText(file)
    || (convertedKnown && !hasText(file.converted_sql))
    || (originalKnown && size > 0 && !hasText(file.original_sql))
    || (statementKnown && size > 0 && Number(file.statement_count) === 0);
  if (blocked) return "Blocked";
  if (status === "REQUIRES_REVIEW" || file.manual_review_required || (file.warnings || []).length || (file.unsupported_features || []).length) return "Requires Review";
  if (report?.executed) return "Validated";
  if (isDbtBrainRun(report, [file])) return "Ready for Compile";
  if (file.converted_file_ready || ["COMPLETED", "CONVERTED_WITH_WARNINGS", "READY"].includes(status)) return "Ready for Snowflake Validation";
  return "Requires Review";
}

function convertedSqlReadiness(file = {}, status) {
  const convertedKnown = Object.prototype.hasOwnProperty.call(file, "converted_sql");
  if (status === "Blocked") return "No. A blocker must be resolved before converted SQL can be trusted.";
  if (convertedKnown && !hasText(file.converted_sql)) return "No. UMA did not produce converted SQL for this file.";
  if (status === "Requires Review") return "Partially. Converted SQL exists, but it requires human review before compile or validation.";
  if (file.converted_file_ready === false) return "No. UMA marked this file as not ready.";
  return "Yes for the next offline step. It still needs compile and Snowflake validation.";
}

function confidenceBreakdown(file = {}, status, report = {}) {
  const confidence = numericConfidence(file.confidence_score);
  const hasWarnings = (file.warnings || []).length || (file.unsupported_features || []).length;
  let conversionConfidence = "Medium";
  if (status === "Blocked") conversionConfidence = "Low";
  else if (status === "Requires Review" || hasWarnings) conversionConfidence = "Medium - review required";
  else conversionConfidence = "High for deterministic conversion";
  return {
    dialect: confidence == null ? "Not available" : `${percentLabel(confidence)} dialect detection confidence`,
    conversion: conversionConfidence,
    validation: report?.executed ? "Established by execution evidence in this payload" : "Not established - static validation only",
    production: report?.executed ? "Not automatically production ready; approval evidence is still required" : "Not production ready - Snowflake execution, dbt compile, row-count, and sample-data validation were not run",
  };
}

function fileFindings(file = {}, status, report = {}, inventory = []) {
  const findings = [];
  const name = fileDisplayName(file);
  const statusValue = String(file.conversion_status || "").toUpperCase();
  const size = fileSizeBytes(file, inventory);
  if (statusValue === "FAILED") findings.push(`${name} has conversion_status = FAILED.`);
  if (Object.prototype.hasOwnProperty.call(file, "converted_sql") && !hasText(file.converted_sql)) findings.push("Converted SQL is empty.");
  if (Object.prototype.hasOwnProperty.call(file, "original_sql") && size > 0 && !hasText(file.original_sql)) findings.push("The file had content, but UMA did not extract original SQL.");
  if (Object.prototype.hasOwnProperty.call(file, "statement_count") && size > 0 && Number(file.statement_count) === 0) findings.push("The file had content, but no SQL statements were extracted.");
  if (parserFailureText(file)) findings.push("Parser/static validation reported a parsing failure.");
  if (String(file.conversion_status || "").toUpperCase() === "REQUIRES_REVIEW") findings.push("UMA marked the conversion as requiring review.");
  findings.push(...asArray(file.unsupported_features));
  findings.push(...asArray(file.warnings));
  findings.push(...(file.agent_review_results?.findings || []).map((finding) => finding.finding));
  if (containsAny(fileCombinedText(file), ["unnest", "generate_date_array", "flatten", "array_generate_range"])) {
    findings.push("BigQuery UNNEST / GENERATE_DATE_ARRAY logic was rewritten for Snowflake FLATTEN / ARRAY_GENERATE_RANGE behavior.");
  }
  if (!findings.length && status !== "Blocked") findings.push("No critical findings were attached to this file.");
  return compactUnique(findings);
}

function fileWhyItMatters(file = {}, status, report = {}, inventory = []) {
  const reasons = [];
  const size = fileSizeBytes(file, inventory);
  if (status === "Blocked") reasons.push("Blocked files can make a migration package look complete even though UMA could not produce trustworthy SQL.");
  if (Object.prototype.hasOwnProperty.call(file, "statement_count") && size > 0 && Number(file.statement_count) === 0) reasons.push("If SQL statements are not extracted, downstream conversion, dbt compile, and validation have nothing reliable to check.");
  if (containsAny(fileCombinedText(file), ["unnest", "generate_date_array", "flatten", "array_generate_range"])) reasons.push("Array/date expansion semantics can change row counts, date ranges, and join cardinality when moved from BigQuery to Snowflake.");
  if ((file.dbt_metadata?.sources || file.dbt_metadata?.refs || file.dbt_metadata?.source_relations)?.length) reasons.push("dbt source/ref mappings affect lineage and deployment dependencies.");
  if (!report?.executed) reasons.push("Static checks cannot prove Snowflake syntax, permissions, row counts, or sample data parity.");
  return compactUnique(reasons).join(" ");
}

function fileRecommendedActions(file = {}, status, report = {}, inventory = []) {
  const actions = [];
  const name = fileDisplayName(file);
  const size = fileSizeBytes(file, inventory);
  if (status === "Blocked") actions.push(`Fix parsing or extraction for ${name}, then rerun UMA Brain Review.`);
  if (Object.prototype.hasOwnProperty.call(file, "statement_count") && size > 0 && Number(file.statement_count) === 0) actions.push(`Confirm ${name} contains executable SQL or supported dbt SQL, then rerun analysis.`);
  if (containsAny(fileCombinedText(file), ["unnest", "generate_date_array", "flatten", "array_generate_range"])) actions.push(`Review the SQL diff for ${name}, especially FLATTEN / ARRAY_GENERATE_RANGE behavior and expected row counts.`);
  if ((file.dbt_metadata?.sources || file.dbt_metadata?.refs || file.dbt_metadata?.source_relations)?.length) actions.push(`Check dbt source/ref mappings for ${name} before compile.`);
  if (String(file.conversion_status || "").toUpperCase() === "REQUIRES_REVIEW") actions.push(`Approve or revise ${name} after human review.`);
  if (!report?.executed) actions.push(`Run Snowflake syntax validation for ${name} after configuring Snowflake.`);
  return compactUnique(actions).join(" ");
}

function buildUmaBrainReviewTranscript(report, selectedRun) {
  const files = brainFilesFromReport(report);
  const inventory = brainInventory(report);
  const fileCount = Number(report?.file_count ?? inventory.length ?? files.length) || files.length;
  const fileReviews = files.map((file) => {
    const status = humanFileStatus(file, report, inventory);
    return {
      file,
      name: fileDisplayName(file),
      status,
      dialect: file.detected_dialect || report?.source_dialect || selectedRun?.source_dialect || "Not available",
      convertedReady: convertedSqlReadiness(file, status),
      confidence: confidenceBreakdown(file, status, report),
      findings: fileFindings(file, status, report, inventory),
      why: fileWhyItMatters(file, status, report, inventory),
      action: fileRecommendedActions(file, status, report, inventory),
    };
  });
  const blockers = [];
  const reviewItems = [];
  fileReviews.forEach((row) => {
    const file = row.file;
    const size = fileSizeBytes(file, inventory);
    const name = row.name;
    const statusValue = String(file.conversion_status || "").toUpperCase();
    if (statusValue === "FAILED") blockers.push(`${name} is blocked because conversion_status = FAILED.`);
    if (statusValue === "FAILED") reviewItems.push(`${name} requires review because conversion failed.`);
    if (Object.prototype.hasOwnProperty.call(file, "converted_sql") && !hasText(file.converted_sql)) blockers.push(`${name} is blocked because converted SQL is empty.`);
    if (Object.prototype.hasOwnProperty.call(file, "original_sql") && size > 0 && !hasText(file.original_sql)) blockers.push(`${name} is blocked because the file had content but no original SQL was extracted.`);
    if (Object.prototype.hasOwnProperty.call(file, "statement_count") && size > 0 && Number(file.statement_count) === 0) blockers.push(`${name} is blocked because the file had content but no SQL statements were extracted.`);
    if (parserFailureText(file)) blockers.push(`${name} is blocked because parser/static validation failed.`);
    if (statusValue === "REQUIRES_REVIEW") reviewItems.push(`${name} requires review because UMA marked conversion_status = REQUIRES_REVIEW.`);
    asArray(file.warnings).forEach((warning) => reviewItems.push(`${name} warning: ${warning}`));
    asArray(file.unsupported_features).forEach((feature) => reviewItems.push(`${name} unsupported feature: ${feature}`));
    if ((numericConfidence(file.confidence_score) ?? 100) < 70) reviewItems.push(`${name} requires review because dialect detection confidence is ${percentLabel(file.confidence_score)}.`);
    if (containsAny(fileCombinedText(file), ["unnest", "generate_date_array", "flatten", "array_generate_range"])) {
      reviewItems.push(`${name} requires review because BigQuery UNNEST / GENERATE_DATE_ARRAY logic was rewritten for Snowflake FLATTEN / ARRAY_GENERATE_RANGE behavior.`);
    }
    if ((file.dbt_metadata?.sources || file.dbt_metadata?.refs || file.dbt_metadata?.source_relations)?.length) reviewItems.push(`${name} requires dbt source/ref mapping checks.`);
  });
  if (!report?.executed) {
    blockers.push("Production readiness is blocked because Snowflake execution validation was not run.");
    reviewItems.push("No live Snowflake execution was run; review generated SQL before claiming Snowflake readiness.");
  }
  if (report?.missing_required_credentials?.length) blockers.push(`Missing required credentials: ${report.missing_required_credentials.join(", ")}.`);
  if (!report?.llm_available) reviewItems.push("No LLM provider was configured or available; LLM rewrite was unavailable.");

  const statuses = fileReviews.map((row) => row.status);
  const overallStatus = blockers.length ? "Blocked" : statuses.includes("Requires Review") ? "Requires Review" : report?.executed ? "Validated" : "Ready for Snowflake Validation";
  const detectedDialects = compactUnique(fileReviews.map((row) => row.dialect).filter((dialect) => dialect !== "Not available"));
  const sourceDialect = selectedRun?.source_dialect === "auto_detect" || !selectedRun?.source_dialect
    ? (detectedDialects.join(", ") || "Auto detected")
    : selectedRun.source_dialect;
  const targetDialect = report?.target_dialect || report?.target_platform || selectedRun?.target_dialect || selectedRun?.target_type || "snowflake";
  const dbtApplicable = isDbtBrainRun(report, files);

  const whatDid = [
    `UMA analyzed ${fileCount} file${fileCount === 1 ? "" : "s"}.`,
    `Uploaded and inventoried ${fileCount} file${fileCount === 1 ? "" : "s"}.`,
    "Ran dialect detection.",
    dbtApplicable ? "Ran dbt analysis." : "Checked for dbt metadata.",
    "Protected Jinja macros before deterministic rewriting.",
    "Ran static conversion.",
    "Ran parser/static validation and source residue checks.",
    report?.rag_enabled === false ? "RAG guidance retrieval was not enabled." : "Ran RAG guidance retrieval.",
    "Ran agent review.",
    "Generated report/artifact output.",
  ];
  const whatDidNot = [];
  if (!report?.executed) {
    whatDidNot.push("Did not connect to Snowflake or execute SQL.");
    whatDidNot.push("Live Snowflake syntax, dbt compile, row-count, and sample-data validation did not run.");
  }
  if (!report?.llm_available) {
    whatDidNot.push("LLM rewrite did not run because no provider was available for this run.");
  }

  const validationStatus = [
    "Static validation only: UMA ran offline parsing, rewrite, residue, and review checks from the payload.",
    report?.executed ? "Snowflake execution validation ran according to this payload." : "Snowflake execution validation did not run.",
    dbtApplicable ? "dbt compile did not run in this Brain Review." : "dbt compile was not applicable to the detected payload.",
    "Row-count validation did not run.",
    "Sample-data validation did not run.",
  ];
  const llmStatus = [
    report?.llm_available ? `LLM provider configured: ${report.llm_provider || "available"}.` : "LLM provider configured: No.",
    report?.llm_available ? "LLM rewrite evidence is attached to the run payload." : "Conversion was deterministic-only because LLM rewrite was unavailable.",
    report?.llm_available ? "User confidence should still come from compile, Snowflake validation, and data checks." : "This lowers confidence for complex semantic rewrites; users should review diffs and run validation before approval.",
  ];

  const nextActions = [];
  fileReviews.filter((row) => row.status === "Blocked").forEach((row) => nextActions.push(`Fix parsing for ${row.name} and rerun UMA Brain Review.`));
  fileReviews.filter((row) => containsAny(fileCombinedText(row.file), ["unnest", "generate_date_array", "flatten", "array_generate_range"])).forEach((row) => nextActions.push(`Review the SQL diff for ${row.name}, focusing on UNNEST / GENERATE_DATE_ARRAY to FLATTEN / ARRAY_GENERATE_RANGE behavior.`));
  if (!report?.executed) nextActions.push("Configure Snowflake credentials/connection for validation.");
  if (dbtApplicable) nextActions.push("Run dbt compile after blocked files are fixed.");
  if (!report?.executed) {
    nextActions.push("Run Snowflake syntax validation in a read-only or validation-only mode.");
    nextActions.push("Run row-count validation and sample-data validation before approving migration readiness.");
  }
  if (!report?.llm_available) nextActions.push("Optionally configure an LLM provider for an additional rewrite/review pass on complex SQL.");

  const summary = [
    { label: "Files analyzed", value: fileCount },
    { label: "Source dialect", value: sourceDialect },
    { label: "Target dialect/platform", value: targetDialect },
    { label: "Execution mode", value: report?.executed ? "Executed validation" : "Offline-only" },
    { label: "Overall status", value: overallStatus },
  ];

  const lines = [
    "# UMA Brain Review Transcript",
    "",
    "## Run Summary",
    ...summary.map((item) => `- ${item.label}: ${item.value}`),
    "",
    "## What UMA Did",
    ...whatDid.map((item) => `- ${item}`),
    "",
    "## What UMA Did Not Do",
    ...(whatDidNot.length ? whatDidNot : ["Nothing material was omitted according to this payload."]).map((item) => `- ${item}`),
    "",
    "## File-by-file Review",
    ...fileReviews.flatMap((row) => [
      `### ${row.name}`,
      `- Status: ${row.status}`,
      `- Dialect detected: ${row.dialect}`,
      `- Dialect detection confidence: ${row.confidence.dialect}`,
      `- Conversion confidence: ${row.confidence.conversion}`,
      `- Validation confidence: ${row.confidence.validation}`,
      `- Production readiness: ${row.confidence.production}`,
      `- Converted SQL ready: ${row.convertedReady}`,
      `- Main findings: ${row.findings.join("; ")}`,
      `- Why it matters: ${row.why || "No additional risk rationale was attached."}`,
      `- Recommended action: ${row.action || "Review the converted SQL before approval."}`,
      "",
    ]),
    "## Critical Blockers",
    ...(compactUnique(blockers).length ? compactUnique(blockers) : ["No critical blockers were detected."]).map((item) => `- ${item}`),
    "",
    "## Review Required",
    ...(compactUnique(reviewItems).length ? compactUnique(reviewItems) : ["No review-required items were detected."]).map((item) => `- ${item}`),
    "",
    "## Validation Status",
    ...validationStatus.map((item) => `- ${item}`),
    "",
    "## AI/LLM Status",
    ...llmStatus.map((item) => `- ${item}`),
    "",
    "## Recommended Next Actions",
    ...compactUnique(nextActions).map((item) => `- ${item}`),
  ];

  return {
    summary,
    whatDid,
    whatDidNot,
    fileReviews,
    blockers: compactUnique(blockers),
    reviewItems: compactUnique(reviewItems),
    validationStatus,
    llmStatus,
    nextActions: compactUnique(nextActions),
    markdown: lines.join("\n"),
    overallStatus,
  };
}

function downloadClientText(filename, text, type = "text/markdown") {
  const blob = new Blob([text || ""], { type });
  const href = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(href);
}

function CodeViewer({ title = "Preview", preview, artifact }) {
  const download = () => artifact?.id ? api.downloadControlPlaneArtifact(artifact.id, artifact.original_filename) : null;
  const text = preview?.text || (preview?.json ? JSON.stringify(preview.json, null, 2) : "");
  return (
    <SectionCard
      title={title}
      subtitle={artifact ? artifact.original_filename : "No artifact selected"}
      actions={text ? (
        <div className="flex gap2">
          <CopyButton value={text} />
          {artifact?.id ? <button className="btn btn-ghost btn-sm" onClick={download}>Download</button> : null}
        </div>
      ) : null}
      empty={!text ? <EmptyState title="No result generated yet" message="Run analysis or generation to preview SQL, dbt, YAML, or JSON artifacts here." compact /> : null}
    >
      {text ? <pre className="pq-code-block">{text}</pre> : null}
    </SectionCard>
  );
}

function ArtifactComparisonPanel({ comparison, loading, error }) {
  const sourceText = comparison?.source_text || "";
  const targetText = comparison?.generated_text || "";
  const sourceName = comparison?.source_artifact?.original_filename || "Source artifact";
  const targetName = comparison?.generated_artifact?.original_filename || "Generated target artifact";
  if (loading) {
    return <SkeletonState rows={4} title="Loading source and target artifacts" />;
  }
  if (error) {
    return <ErrorPanel error={error} />;
  }
  if (!comparison) {
    return <EmptyState title="No artifact comparison loaded" message="Select evidence to open the source and generated target model side by side." compact />;
  }
  return (
    <div className="info-tile">
      <div className="stat-label">Source and target dbt model comparison</div>
      <div className="text-muted mt1">{comparison.message}</div>
      <div className="brain-code-compare">
        <div className="brain-code-pane">
          <div className="brain-code-head">
            <span>Source</span>
            <span>{comparison.source_line_count || 0} lines</span>
          </div>
          <div className="td-mono brain-code-file">{sourceName}</div>
          <pre className="pq-code-block brain-code-block">{sourceText || "Source artifact was not resolved for this decision."}</pre>
        </div>
        <div className="brain-code-pane">
          <div className="brain-code-head">
            <span>Target</span>
            <span>{comparison.generated_line_count || 0} lines</span>
          </div>
          <div className="td-mono brain-code-file">{targetName}</div>
          <pre className="pq-code-block brain-code-block">{targetText || "Generated target artifact was not resolved for this decision."}</pre>
        </div>
      </div>
    </div>
  );
}

function ReportPreview({ title = "Report preview", report, emptyMessage = "No report generated yet." }) {
  const sections = report && typeof report === "object" ? Object.entries(report) : [];
  return (
    <SectionCard
      title={title}
      subtitle="Structured report sections, metrics, findings, and recommendations."
      empty={!sections.length ? <EmptyState title="No report generated yet" message={emptyMessage} compact /> : null}
    >
      {sections.length ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {sections.map(([key, value]) => {
            const label = formatLabel(key);
            if (Array.isArray(value)) {
              return (
                <div key={key} className="info-tile">
                  <div className="stat-label">{label}</div>
                  {value.length && typeof value[0] === "object" ? (
                    <DataTable
                      columns={Object.keys(value[0]).slice(0, 5).map((column) => ({ key: column, label: formatLabel(column), render: (row) => summaryValue(row[column]) }))}
                      rows={value.slice(0, 12).map((row, index) => ({ id: `${key}-${index}`, ...row }))}
                      emptyTitle={`No ${label.toLowerCase()}`}
                      emptyMessage={`No ${label.toLowerCase()} were generated.`}
                    />
                  ) : (
                    <div className="info-tile-value">{value.length ? value.join(", ") : "None"}</div>
                  )}
                </div>
              );
            }
            if (value && typeof value === "object") {
              return (
                <div key={key} className="info-tile">
                  <div className="stat-label">{label}</div>
                  <div className="soft-grid" style={{ marginTop: 8 }}>
                    {Object.entries(value).slice(0, 8).map(([childKey, childValue]) => (
                      <div key={childKey}>
                        <div className="text-muted">{formatLabel(childKey)}</div>
                        <div className="info-tile-value">{summaryValue(childValue)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            }
            return (
              <div key={key} className="info-tile">
                <div className="stat-label">{label}</div>
                <div className="info-tile-value">{summaryValue(value)}</div>
              </div>
            );
          })}
        </div>
      ) : null}
    </SectionCard>
  );
}

function ApprovalGate({ approved, onToggle, canApply, reason }) {
  return (
    <div className="alert-info">
      <div style={{ fontWeight: 800, marginBottom: 6 }}>Approval gate</div>
      <div style={{ marginBottom: 10 }}>Safety mode is plan-first. No SQL, dbt build, or Snowflake apply runs by default.</div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <input type="checkbox" checked={approved} onChange={(event) => onToggle(event.target.checked)} />
        Confirm that you reviewed the generated plan and still want to enable apply.
      </label>
      <div className="text-muted">{canApply ? "Apply remains guarded by backend configuration." : reason}</div>
    </div>
  );
}

function Field({ label, children, hint }) {
  return (
    <div className="fg">
      <label className="fl">{label}</label>
      {children}
      {hint ? <div className="fhint">{hint}</div> : null}
    </div>
  );
}

function FileUploadDropzone({ onUploaded, accept, title, message, artifactCategory }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const upload = async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setBusy(true);
    setError("");
    try {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        if (artifactCategory) {
          form.append("artifact_category", artifactCategory);
        }
        if (artifactCategory === "DBT_PROJECT") {
          await api.uploadDbtProject(form);
        } else {
          await api.uploadControlPlaneArtifact(form);
        }
      }
      await onUploaded?.();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  };
  return (
    <SectionCard
      title={title || "Upload artifacts"}
      subtitle={message || "Drag and drop is optional; upload persists artifacts for later runs."}
      error={error}
    >
      <input className="fi" type="file" multiple accept={accept} disabled={busy} onChange={upload} />
      <div className="text-muted mt2">{busy ? "Uploading..." : "Uploaded files remain available across runs and reports."}</div>
    </SectionCard>
  );
}

function ArtifactSelector({ artifacts, selected, setSelected, allowedTypes, selectedRunId = "", emptyAction = null }) {
  const filtered = filterArtifactsForModule(artifacts, allowedTypes, selectedRunId);
  const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  return (
    <SectionCard
      title="Select persisted artifacts"
      subtitle="Every workflow runs against uploaded artifacts and persisted run evidence."
      empty={!filtered.length ? <EmptyState title="No artifacts uploaded yet" message="Upload source SQL, DDL, requirements, XML, Tableau, or dbt project packages to start this workflow." action={emptyAction} compact /> : null}
    >
      <DataTable
        columns={[
          { key: "select", label: "", render: (row) => <input type="checkbox" checked={selected.includes(row.id)} onChange={() => toggle(row.id)} /> },
          { key: "original_filename", label: "Artifact", render: (row) => <span className="td-main">{row.original_filename}</span> },
          { key: "artifact_category", label: "Category" },
          { key: "file_type", label: "Type" },
          { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
        ]}
        rows={filtered}
      />
    </SectionCard>
  );
}

function DisabledReason({ children }) {
  return <div className="text-muted mt2">{children}</div>;
}

function useAsyncLoader(loader, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      setData(await loader());
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { refresh(); }, deps);
  return { data, loading, error, refresh, setData };
}

function SummaryList({ items }) {
  if (!items?.length) {
    return <EmptyState title="No result generated yet" message="Run the workflow to populate this section." compact />;
  }
  return (
    <div className="soft-grid">
      {items.map((item, index) => (
        <div key={index} className="info-tile">
          <div className="stat-label">{item.label}</div>
          <div className="info-tile-value">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

const REVIEW_STATUSES = ["NEW", "IN_REVIEW", "APPROVED", "REJECTED", "NEEDS_REWORK", "BLOCKED", "RESOLVED"];
const REVIEW_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

function normalizeReviewStatus(status) {
  return ({ OPEN: "NEW", REVIEWED: "RESOLVED", REQUIRES_REVIEW: "IN_REVIEW", APPROVAL_REQUIRED: "IN_REVIEW" })[status] || status || "NEW";
}

function normalizeReviewSeverity(severity) {
  return ({ WARN: "MEDIUM", WARNING: "MEDIUM", ERROR: "HIGH" })[severity] || severity || "INFO";
}

export function BrainReviewPage({ setPage = null }) {
  const { data, loading, error, refresh, setData } = useAsyncLoader(() => api.listBrainReviewItems(), []);
  const [selected, setSelected] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [severityFilter, setSeverityFilter] = useState("ALL");
  const [busy, setBusy] = useState("");

  const items = useMemo(() => (data || []).map((item) => ({
    ...item,
    status: normalizeReviewStatus(item.status),
    severity: normalizeReviewSeverity(item.severity),
    confidence_score: item.confidence_score ?? 0.72,
  })), [data]);

  const filtered = useMemo(() => items.filter((item) => {
    const openStatus = !["APPROVED", "REJECTED", "RESOLVED"].includes(item.status);
    if (statusFilter === "OPEN" && !openStatus) return false;
    if (statusFilter !== "OPEN" && statusFilter !== "ALL" && item.status !== statusFilter) return false;
    if (severityFilter !== "ALL" && item.severity !== severityFilter) return false;
    return true;
  }), [items, statusFilter, severityFilter]);

  const summary = useMemo(() => ({
    total: items.length,
    open: items.filter((item) => !["APPROVED", "REJECTED", "RESOLVED"].includes(item.status)).length,
    blockers: items.filter((item) => item.status === "BLOCKED" || item.severity === "CRITICAL").length,
    approvals: items.filter((item) => item.status === "APPROVED").length,
  }), [items]);

  const openItem = async (item) => {
    setSelected(item);
    setComparison(null);
    setComparisonError("");
    setComparisonLoading(true);
    try {
      setComparison(await api.getBrainReviewItemComparison(item.id));
    } catch (err) {
      setComparisonError(getErrorMessage(err));
    } finally {
      setComparisonLoading(false);
    }
  };

  useEffect(() => {
    if (loading) return;
    if (!filtered.length) {
      setSelected(null);
      setComparison(null);
      return;
    }
    if (!selected || !filtered.some((item) => item.id === selected.id)) {
      openItem(filtered[0]);
    }
  }, [loading, filtered, selected?.id]);

  const updateItem = async (item, status, reviewerComment = "") => {
    setBusy(`${item.id}-${status}`);
    try {
      const updated = await api.updateBrainReviewItem(item.id, {
        status,
        reviewer_comment: reviewerComment || item.reviewer_comment || "",
      });
      const normalized = { ...updated, status: normalizeReviewStatus(updated.status), severity: normalizeReviewSeverity(updated.severity) };
      setData((current) => (current || []).map((row) => row.id === item.id ? normalized : row));
      setSelected((current) => current?.id === item.id ? normalized : current);
    } finally {
      setBusy("");
    }
  };

  const assignItem = async (item) => {
    const owner = window.prompt("Assign owner", item.owner || "");
    if (owner == null) return;
    await updateItem(item, "IN_REVIEW", `Assigned to ${owner}`);
  };

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="UMA Brain Review"
        subtitle="Decision inbox for migration blockers, generated artifacts, validation failures, assignments, approvals, and rework."
        status={summary.blockers ? "BLOCKED" : summary.open ? "IN_REVIEW" : "RESOLVED"}
        primaryAction={<button className="btn btn-primary" onClick={refresh}>Refresh decisions</button>}
      />
      <OperationsAlertStrip
        items={filtered.filter((item) => item.status === "BLOCKED" || item.severity === "CRITICAL").map((item) => ({
          id: item.id,
          title: item.title || item.summary || item.description || "Review blocker",
          status: item.status,
          action: item.recommendation || "Open decision",
          onClick: () => openItem(item),
        }))}
        fallback="No critical Brain Review blockers are open."
      />
      <EnterpriseKpiRow items={[
        { label: "Decisions", value: summary.total, note: "persisted records", active: statusFilter === "ALL" && severityFilter === "ALL", onClick: () => { setStatusFilter("ALL"); setSeverityFilter("ALL"); } },
        { label: "Open", value: summary.open, note: "needs action", active: statusFilter === "OPEN", onClick: () => { setStatusFilter("OPEN"); setSeverityFilter("ALL"); } },
        { label: "Blockers", value: summary.blockers, note: "cutover risk", active: severityFilter === "CRITICAL" || statusFilter === "BLOCKED", onClick: () => { setStatusFilter("ALL"); setSeverityFilter("CRITICAL"); } },
        { label: "Approved", value: summary.approvals, note: "accepted evidence", active: statusFilter === "APPROVED", onClick: () => { setStatusFilter("APPROVED"); setSeverityFilter("ALL"); } },
      ]} />
      <ErrorPanel error={error} />
      <div className="ep-split-toolbar" style={{ marginBottom: 12, border: "1px solid var(--border)", borderRadius: 10 }}>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="OPEN">Open work</option>
          <option value="ALL">All statuses</option>
          {REVIEW_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
        </select>
        <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}>
          <option value="ALL">All severities</option>
          {REVIEW_SEVERITIES.map((severity) => <option key={severity} value={severity}>{severity}</option>)}
        </select>
      </div>
      {loading ? <SkeletonState rows={5} title="Loading UMA Brain Review" /> : (
        <div className="ep-queue">
          <div className="ep-queue-list">
            <div className="ep-list-head"><div><div className="ep-list-title">Decision queue</div><div className="ep-list-subtitle">Filtered by status and severity.</div></div></div>
            {!filtered.length ? (
              <EmptyState
                title="No review items"
                message="Review items appear when conversion, validation, schema drift, or artifact approval requires human judgment."
                action={setPage ? (
                  <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                    <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage("sql_conversion")}>Run conversion</button>
                    <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("validation_center")}>Open validation</button>
                    <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("tables")}>Check schema drift</button>
                  </div>
                ) : null}
                compact
              />
            ) : filtered.map((item) => (
              <button key={item.id} className={`ep-queue-item ${selected?.id === item.id ? "active" : ""}`} onClick={() => openItem(item)}>
                <div className="ep-queue-name">{item.title || item.summary || item.description || "Migration decision"}</div>
                <div className="ep-queue-meta"><StatusBadge status={item.severity} /><StatusBadge status={item.status} /></div>
                <div className="row-subtext mt2">{item.source_object || "Source evidence"} → {item.target_object || "Generated artifact"}</div>
              </button>
            ))}
          </div>
          <div className="ep-detail-card">
            {selected ? (
              <>
                <div className="flex fjb fac gap2"><div><div className="page-eyebrow">Decision detail</div><div className="page-title" style={{ fontSize: 24 }}>{selected.title || selected.summary || selected.description || "Migration decision"}</div></div><StatusBadge status={selected.status} /></div>
                <div className="ep-recommendation mt3"><strong>Recommendation:</strong> {selected.recommendation || "Review evidence and decide whether to approve, reject, or request rework."}</div>
                <div className="soft-grid mt3">
                  <div className="info-tile"><div className="stat-label">Severity</div><div className="info-tile-value"><StatusBadge status={selected.severity} /></div></div>
                  <div className="info-tile"><div className="stat-label">Category</div><div className="info-tile-value">{selected.item_type || selected.category || "Review"}</div></div>
                  <div className="info-tile"><div className="stat-label">Source</div><div className="info-tile-value">{selected.source_object || "Source evidence"}</div></div>
                  <div className="info-tile"><div className="stat-label">Target</div><div className="info-tile-value">{selected.target_object || "Generated artifact"}</div></div>
                </div>
                <div className="divider" />
                <div className="ep-section-label">Evidence</div>
                {comparisonLoading ? <LoadingPanel label="Loading comparison" /> : comparisonError ? <ErrorPanel error={comparisonError} /> : comparison ? <pre className="pq-code-block" style={{ maxHeight: 320 }}>{JSON.stringify(comparison, null, 2)}</pre> : <div className="ep-empty-compact">No comparison artifact loaded for this decision.</div>}
              </>
            ) : <EmptyState title="No decision selected" message="Choose a decision from the queue to inspect recommendation, evidence, and audit trail." compact />}
          </div>
          <div className="ep-detail-card">
            <div className="ep-section-label">Decision actions</div>
            {selected ? (
              <div className="ep-action-row">
                <button className="btn btn-primary btn-sm" disabled={busy === `${selected.id}-APPROVED`} onClick={() => updateItem(selected, "APPROVED")}>Approve</button>
                <button className="btn btn-danger btn-sm" disabled={busy === `${selected.id}-REJECTED`} onClick={() => updateItem(selected, "REJECTED")}>Reject</button>
                <button className="btn btn-ghost btn-sm" disabled={busy === `${selected.id}-NEEDS_REWORK`} onClick={() => updateItem(selected, "NEEDS_REWORK", "Request rework before approval.")}>Request rework</button>
                <button className="btn btn-ghost btn-sm" disabled={busy === `${selected.id}-IN_REVIEW`} onClick={() => assignItem(selected)}>Assign</button>
                <button className="btn btn-ghost btn-sm" disabled={busy === `${selected.id}-RESOLVED`} onClick={() => updateItem(selected, "RESOLVED")}>Mark resolved</button>
                <button className="btn btn-ghost btn-sm" disabled={comparisonLoading} onClick={() => openItem(selected)}>Refresh evidence</button>
              </div>
            ) : <div className="ep-empty-compact">Select a decision to enable approve, reject, request rework, assign, and resolve actions.</div>}
            <div className="divider" />
            <div className="ep-section-label">Audit trail</div>
            <div className="ep-empty-compact">{selected?.reviewer_comment || "Decision audit events and reviewer comments appear here after action."}</div>
          </div>
        </div>
      )}
    </PageTransition>
  );
}

export function MoreToolsPage({ setPage }) {
  const tools = [
    { id: "etl_analyzer", title: "ETL / BI Analyzer", status: "Ready", helps: "Extracts ETL, BI, XML, Tableau, and dependency evidence for migration assessment.", action: "Open analyzer" },
    { id: "snowflake_advisor", title: "Snowflake Readiness Scan", status: "Beta", helps: "Checks Snowflake posture, account objects, and readiness guardrails when a target is configured.", action: "Open readiness" },
    { id: "snowflake_provision", title: "Landing Zone Plan", status: "Ready", helps: "Builds plan-only Snowflake databases, schemas, warehouses, roles, and approval gates.", action: "Open planner" },
    { id: "artifact_factory", title: "Artifact Explorer", status: "Ready", helps: "Creates and inspects generated dbt, SQL, runbook, validation, and report artifacts.", action: "Open artifacts" },
    { id: "scheduler", title: "Scheduler", status: "Ready", helps: "Operates replication profiles, run cadence, sync history, and retry controls.", action: "Open scheduler" },
    { id: "connections", title: "Connector Diagnostics", status: "Ready", helps: "Shows configured connectors, test results, capability maturity, and known limitations.", action: "Open connectors" },
    { id: "settings", title: "Environment Diagnostics", status: "Ready", helps: "Reviews settings, notification tests, policy history, and local deployment configuration.", action: "Open settings" },
    { id: "developer_api", title: "Developer/API Tools", status: "Preview", helps: "Documents API route checks and integration hooks for pilot operators.", action: "Preview only", disabled: true },
    { id: "cost_estimator", title: "Cost Estimator", status: "Coming Soon", helps: "Will estimate Snowflake compute, storage, and migration run costs from inventory.", action: "Coming soon", disabled: true },
  ];
  const grouped = [
    { title: "Analyze", subtitle: "Discovery tools used before conversion or when a pilot needs a deeper assessment.", rows: tools.slice(0, 2) },
    { title: "Plan and Operate", subtitle: "Lower-frequency planning and run-management surfaces that support migration execution.", rows: tools.slice(2, 5) },
    { title: "Diagnostics", subtitle: "Operator checks for connector capability, environment health, and integration readiness.", rows: tools.slice(5, 8) },
    { title: "Future", subtitle: "Visible roadmap utilities that are intentionally disabled until implementation is ready.", rows: tools.slice(8) },
  ];

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="More Tools"
        subtitle="Lower-frequency but useful migration utilities. Tools stay visible here with clear readiness labels, useful descriptions, and disabled states when the implementation is not ready."
        status="READY"
      />
      <div className="alert-info">More Tools is the overview for secondary utilities. To avoid duplicate navigation, individual tools are opened from these cards instead of being repeated in the left nav.</div>
      {grouped.map((group) => (
        <SectionCard key={group.title} title={group.title} subtitle={group.subtitle} >
          <div className="ux-tool-grid">
            {group.rows.map((tool, index) => (
              <EnterpriseToolCard key={tool.title} tool={tool} delay={index * 45} onOpen={setPage} />
            ))}
          </div>
        </SectionCard>
      ))}
    </PageTransition>
  );
}

export function RunDetailPage({ setPage = null }) {
  const { data: runs, loading, error, refresh } = useAsyncLoader(() => api.getControlPlaneRuns(), []);
  const [selectedRunId, setSelectedRunId] = useState(() => (typeof window !== "undefined" ? window.localStorage.getItem("uma.selectedRunId") || "" : ""));
  const [detail, setDetail] = useState(null);
  const [detailState, setDetailState] = useState({ loading: false, error: "" });
  const selectedRun = useMemo(() => (runs || []).find((row) => row.id === selectedRunId) || (runs || [])[0] || null, [runs, selectedRunId]);

  useEffect(() => {
    if (!selectedRun?.id) return;
    if (selectedRun.id !== selectedRunId) setSelectedRunId(selectedRun.id);
    setSelectedMigrationRun(selectedRun.id);
    let mounted = true;
    const load = async () => {
      setDetailState({ loading: true, error: "" });
      try {
        const payload = await api.getControlPlaneRunDetail(selectedRun.id);
        if (mounted) {
          setDetail(payload);
          setDetailState({ loading: false, error: "" });
        }
      } catch (err) {
        if (mounted) setDetailState({ loading: false, error: getErrorMessage(err) });
      }
    };
    load();
    return () => { mounted = false; };
  }, [selectedRun?.id]);

  const ownerPage = (run) => {
    const type = String(run?.workflow_type || "").toUpperCase();
    if (type.includes("SQL_DBT") || type.includes("DBT_CONVERSION")) return "dbt_conversion";
    if (type.includes("SQL_CONVERSION")) return "sql_conversion";
    if (type.includes("DATA_VALIDATION")) return "validation_center";
    if (type.includes("PROVISION")) return "snowflake_provision";
    if (type.includes("ADVISOR")) return "snowflake_advisor";
    if (type.includes("ANALYZER")) return "etl_analyzer";
    return "reports";
  };
  const artifactGroups = detail?.artifact_groups || {};
  const blockers = detail?.blockers || [];
  const gates = detail?.gates || {};
  const chooseRun = (run) => {
    setSelectedRunId(run.id);
    setSelectedMigrationRun(run.id);
  };

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="Migration Run Detail"
        subtitle="Canonical run view for source artifacts, conversion jobs, generated outputs, Brain Review, validation, replication, drift, reports, blockers, and readiness."
        status={detail?.run_status || selectedRun?.status}
        primaryAction={<button className="btn btn-primary" type="button" onClick={refresh}>Refresh runs</button>}
        secondaryAction={selectedRun && setPage ? <button className="btn btn-ghost" type="button" onClick={() => setPage(ownerPage(selectedRun))}>Open module workspace</button> : null}
      />
      <ErrorPanel error={error || detailState.error} />
      {loading ? <SkeletonState rows={6} title="Loading migration runs" /> : (
        <div className="ep-workspace wide-detail">
          <div className="ep-list-panel">
            <div className="ep-list-head">
              <div>
                <div className="ep-list-title">Migration runs</div>
                <div className="ep-list-subtitle">Every module should attach its evidence back to one selected run.</div>
              </div>
              <StatusBadge status={runs?.length ? "ACTIVE" : "EMPTY"} />
            </div>
            <DataTable
              rows={runs || []}
              onRowClick={chooseRun}
              emptyTitle="No migration runs yet"
              emptyMessage="Create a SQL/dbt conversion, validation, report, or intelligence run to populate this control object."
              emptyAction={setPage ? (
                <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage("orchestrator")}>Create migration run</button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("orchestrator")}>Upload source artifacts</button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("connections")}>Configure connection</button>
                </div>
              ) : null}
              columns={[
                { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                { key: "workflow_type", label: "Type" },
                { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                { key: "current_phase", label: "Phase", render: (row) => row.current_phase || "Not recorded" },
              ]}
            />
          </div>
          <ObjectDetailPanel
            title={selectedRun ? objectDisplayName(selectedRun) : "Select a migration run"}
            subtitle={detail ? `${detail.source_target?.source_dialect || "source"} to ${detail.source_target?.target_dialect || "snowflake"} · readiness ${detail.readiness_score ?? 0}` : "Run detail loads persisted evidence from backend control tables."}
            status={detail?.run_status || selectedRun?.status}
            actions={selectedRun ? (
              <>
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage ? setPage("brain_review") : null}>Brain Review</button>
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage ? setPage("validation_center") : null}>Validation</button>
                {selectedRun.workflow_type === "SQL_DBT_TO_SNOWFLAKE" ? <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage ? setPage(ownerPage(selectedRun)) : null}>Run Snowflake Validation</button> : null}
                <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage ? setPage(ownerPage(selectedRun)) : null}>Drill down</button>
              </>
            ) : null}
            empty={!selectedRun ? <EmptyState title="No run selected" message="Choose a run to inspect canonical migration evidence." compact /> : detailState.loading ? <LoadingPanel label="Loading canonical run detail" /> : null}
          >
            {detail ? (
              <>
                <div className="ep-recommendation"><strong>Next action:</strong> {detail.next_recommended_action}</div>
                <SummaryList items={[
                  { label: "Source", value: `${detail.source_target?.source_type || "artifact"} / ${detail.source_target?.source_dialect || "auto_detect"}` },
                  { label: "Target", value: `${detail.source_target?.target_type || "snowflake"} / ${detail.source_target?.target_dialect || "snowflake"}` },
                  { label: "Readiness score", value: `${detail.readiness_score ?? 0}` },
                  { label: "Package gate", value: gates.snowflake_ready_package || "blocked" },
                  { label: "dbt compile", value: gates.dbt_compile || "not_run" },
                  { label: "Snowflake validation", value: gates.snowflake_validation || "blocked" },
                ]} />
                <div className="divider" />
                <div className="stat-label">Blockers</div>
                {!blockers.length ? <EmptyState title="No open blockers" message="Brain Review and validation gates do not report blockers for this run." compact /> : (
                  <div className="soft-grid">{blockers.slice(0, 8).map((item) => (
                    <div className="info-tile" key={item.id}>
                      <div className="flex fjb fac gap2"><div className="td-main">{item.title}</div><StatusBadge status={item.status || item.severity} /></div>
                      <div className="text-muted mt2">{item.recommendation || "Resolve this item before package readiness."}</div>
                    </div>
                  ))}</div>
                )}
                <div className="divider" />
                <SummaryList items={[
                  { label: "Source artifacts", value: artifactGroups.source_artifacts?.length || 0 },
                  { label: "Conversion jobs", value: detail.conversion_jobs?.length || 0 },
                  { label: "Generated artifacts", value: detail.generated_artifacts?.length || 0 },
                  { label: "Brain decisions", value: detail.brain_review_decisions?.length || 0 },
                  { label: "Validation status", value: detail.validation?.validation_status || "not_run" },
                  { label: "Latest validation error", value: detail.latest_validation_errors?.[0] || "None recorded" },
                  { label: "Replication jobs", value: detail.replication_jobs?.length || 0 },
                  { label: "Schema drift", value: detail.schema_drift_status?.status || "not_linked" },
                  { label: "Reports", value: detail.reports?.length || 0 },
                ]} />
                <div className="divider" />
                <div className="stat-label">Snowflake validation evidence</div>
                <div className="soft-grid">
                  <div className="info-tile">
                    <div className="td-main">Connection readiness</div>
                    {!(detail.connection_readiness_checks || []).length ? <div className="text-muted mt2">Not run</div> : (detail.connection_readiness_checks || []).map((row) => (
                      <div className="text-muted mt2" key={`${row.check}-${row.status}`}>{formatLabel(row.check)}: {row.status}{row.error ? ` - ${row.error}` : ""}</div>
                    ))}
                  </div>
                  <div className="info-tile">
                    <div className="td-main">Permission checks</div>
                    {!(detail.permission_check_results || []).length ? <div className="text-muted mt2">Not run</div> : (detail.permission_check_results || []).map((row) => (
                      <div className="text-muted mt2" key={`${row.check}-${row.status}`}>{formatLabel(row.check)}: {row.status}{row.error ? ` - ${row.error}` : ""}</div>
                    ))}
                  </div>
                  <div className="info-tile">
                    <div className="td-main">EXPLAIN syntax validation</div>
                    {!(detail.syntax_validation_results || []).length ? <div className="text-muted mt2">Not run</div> : (detail.syntax_validation_results || []).slice(0, 6).map((row) => (
                      <div className="text-muted mt2" key={`${row.model}-${row.status}`}>{row.model}: {row.status}{(row.errors || []).length ? ` - ${row.errors[0]}` : ""}</div>
                    ))}
                  </div>
                </div>
                <div className="divider" />
                <div className="stat-label">Replication evidence</div>
                {!(detail.replication_jobs || []).length ? <EmptyState title="No replication jobs linked" message="Link a replication job from Data Replication to include latest runs, table counts, watermarks, errors, and validation links here." compact /> : (
                  <div className="soft-grid">
                    {(detail.replication_jobs || []).map((job) => (
                      <div className="info-tile" key={job.id}>
                        <div className="flex fjb fac gap2"><div className="td-main">{job.name}</div><StatusBadge status={job.status} /></div>
                        <SummaryList items={[
                          { label: "Tables", value: job.table_count || 0 },
                          { label: "Latest runs", value: job.latest_runs?.length || 0 },
                          { label: "Watermarks", value: job.watermarks?.length || 0 },
                          { label: "Errors", value: job.errors?.length || 0 },
                          { label: "Validation links", value: job.validation_links?.length || 0 },
                        ]} />
                        {(job.errors || []).length ? <div className="text-muted mt2">{job.errors[0].safe_error || job.errors[0].message || "Latest replication error recorded."}</div> : null}
                      </div>
                    ))}
                  </div>
                )}
                <div className="divider" />
                <div className="stat-label">Schema drift</div>
                <div className="info-tile">
                  <div className="flex fjb fac gap2"><div className="td-main">{detail.schema_drift_status?.scope_name || "No drift scope linked"}</div><StatusBadge status={detail.schema_drift_status?.status || "not_linked"} /></div>
                  <div className="text-muted mt2">{detail.schema_drift_status?.message || "Schema drift evidence has not been attached to this migration run."}</div>
                  <SummaryList items={[
                    { label: "Drift count", value: detail.schema_drift_status?.drift_count ?? 0 },
                    { label: "Scope", value: detail.schema_drift_status?.scope_id || "Not linked" },
                    { label: "Latest check", value: detail.schema_drift_status?.latest_checked_at ? fmtDate(detail.schema_drift_status.latest_checked_at) : "Not recorded" },
                  ]} />
                </div>
                <div className="divider" />
                <div className="stat-label">Generated artifacts and reports</div>
                <DataTable
                  rows={[...(detail.generated_artifacts || []), ...(detail.reports || []), ...(artifactGroups.validation_artifacts || []), ...(artifactGroups.packages || [])]}
                  emptyTitle="No generated artifacts yet"
                  emptyMessage="Run conversion or validation to create generated SQL/dbt artifacts, reports, logs, and packages."
                  columns={[
                    { key: "original_filename", label: "Artifact", render: (row) => <span className="td-main">{row.original_filename}</span> },
                    { key: "artifact_category", label: "Category" },
                    { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                  ]}
                />
              </>
            ) : null}
          </ObjectDetailPanel>
        </div>
      )}
    </PageTransition>
  );
}

export function CommandCenterPage({ setPage = null }) {
  const { data: runs, loading, error, refresh } = useAsyncLoader(() => api.getControlPlaneRuns(), []);
  const [selectedRun, setSelectedRun] = useState(null);
  const [activeKpi, setActiveKpi] = useState("runs");
  const [detail, setDetail] = useState({ jobs: [], artifacts: [], report: null, loading: false, error: "" });

  useEffect(() => {
    if (!selectedRun?.id) return;
    let mounted = true;
    const load = async () => {
      setDetail((current) => ({ ...current, loading: true, error: "" }));
      try {
        const [jobs, artifacts, report] = await Promise.all([
          api.getControlPlaneRunJobs(selectedRun.id),
          api.getControlPlaneRunArtifacts(selectedRun.id),
          api.previewUnifiedReport(selectedRun.id).catch(() => null),
        ]);
        if (mounted) setDetail({ jobs, artifacts, report, loading: false, error: "" });
      } catch (err) {
        if (mounted) setDetail({ jobs: [], artifacts: [], report: null, loading: false, error: getErrorMessage(err) });
      }
    };
    load();
    return () => { mounted = false; };
  }, [selectedRun?.id]);

  const summary = useMemo(() => {
    const rows = runs || [];
    return {
      total: rows.length,
      active: rows.filter((row) => row.status === "RUNNING").length,
      review: rows.filter((row) => ["REQUIRES_REVIEW", "APPROVAL_REQUIRED"].includes(row.status)).length,
      failed: rows.filter((row) => row.status === "FAILED").length,
      artifacts: rows.reduce((sum, row) => sum + (row.latest_artifact ? 1 : 0), 0),
      validationFailures: rows.filter((row) => row.workflow_type === "DATA_VALIDATION" && row.status !== "COMPLETED").length,
    };
  }, [runs]);
  const journeyStages = buildMigrationJourney(selectedRun, summary);
  const runTimeline = buildRunTimeline(selectedRun, detail.jobs, detail.artifacts);
  const blockerRows = (runs || []).filter((row) => ["FAILED", "BLOCKED", "REQUIRES_REVIEW", "APPROVAL_REQUIRED"].includes(row.status)).slice(0, 6);
  const activeRunRows = useMemo(() => {
    const rows = runs || [];
    if (activeKpi === "running") return rows.filter((row) => row.status === "RUNNING");
    if (activeKpi === "review") return rows.filter((row) => ["REQUIRES_REVIEW", "APPROVAL_REQUIRED"].includes(row.status));
    if (activeKpi === "failed") return rows.filter((row) => row.status === "FAILED");
    if (activeKpi === "artifacts") return rows.filter((row) => row.latest_artifact || row.report_artifact);
    if (activeKpi === "validation") return rows.filter((row) => row.workflow_type === "DATA_VALIDATION" && row.status !== "COMPLETED");
    return rows;
  }, [activeKpi, runs]);
  const openRunEvidence = (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    if (setPage) setPage("run_detail");
  };
  useEffect(() => {
    if (!selectedRun && (blockerRows[0] || runs?.[0])) setSelectedRun(blockerRows[0] || runs[0]);
  }, [blockerRows, runs, selectedRun]);
  const selectedNextAction = selectedRun?.next_action || (selectedRun?.status === "FAILED" ? "Open run detail and inspect failed jobs, logs, and artifacts." : selectedRun ? "Review evidence and resolve blockers before validation or packaging." : "Create or open a migration run.");

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="Command Center"
        subtitle="Live operations cockpit for failed runs, review gates, validation blockers, artifacts, and the next operator action."
        primaryAction={<button className="btn btn-primary" onClick={refresh}>Refresh runs</button>}
      />
      <OperationsAlertStrip
        items={blockerRows.map((row) => ({
          id: row.id,
          title: objectDisplayName(row),
          status: row.status,
          action: row.next_action || (row.status === "FAILED" ? "Inspect failure" : "Open review"),
          onClick: () => {
            setSelectedRun(row);
            setActiveKpi(row.status === "FAILED" ? "failed" : "review");
          },
        }))}
        activeId={selectedRun?.id}
      />
      <EnterpriseKpiRow items={[
        { label: "Runs", value: summary.total, note: "persisted objects", active: activeKpi === "runs", onClick: () => setActiveKpi("runs") },
        { label: "Running", value: summary.active, note: "currently active", active: activeKpi === "running", onClick: () => setActiveKpi("running") },
        { label: "Review", value: summary.review, note: "needs judgment", active: activeKpi === "review", onClick: () => setActiveKpi("review") },
        { label: "Failed", value: summary.failed, note: "operator action", active: activeKpi === "failed", onClick: () => setActiveKpi("failed") },
        { label: "Artifacts", value: summary.artifacts, note: "generated evidence", active: activeKpi === "artifacts", onClick: () => setActiveKpi("artifacts") },
        { label: "Validation", value: summary.validationFailures, note: "open failures", active: activeKpi === "validation", onClick: () => setActiveKpi("validation") },
      ]} />
      <ErrorPanel error={error} />
      {loading ? <SkeletonState rows={6} title="Loading command center" /> : (
        <div className="ep-workspace wide-detail">
          <div className="ep-list-panel">
            <div className="ep-list-head">
              <div>
                <div className="ep-list-title">Active runs, failures, and review gates</div>
              <div className="ep-list-subtitle">Filtered by the selected KPI. Select a run to inspect current phase, artifacts, logs, report evidence, and next action.</div>
              </div>
              <StatusBadge status={summary.failed ? "FAILED" : summary.review ? "REQUIRES_REVIEW" : "HEALTHY"} />
            </div>
            <DataTable
              rows={activeRunRows}
              onRowClick={setSelectedRun}
              emptyTitle="No migration runs yet"
              emptyMessage="Start with Migration Intelligence, SQL Conversion, dbt Conversion, Validation Plans, or Reports to create persisted runs."
              emptyAction={setPage ? (
                <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage("orchestrator")}>Create migration run</button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("orchestrator")}>Upload source artifacts</button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("connections")}>Configure connection</button>
                </div>
              ) : null}
              columns={[
                { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                { key: "workflow_type", label: "Type" },
                { key: "status", label: "State", render: (row) => <StatusBadge status={row.status} /> },
                { key: "current_phase", label: "Phase", render: (row) => row.current_phase || "Not recorded" },
                { key: "updated", label: "Updated", render: (row) => fmtDate(row.completed_at || row.started_at || row.created_at) },
                { key: "next_action", label: "Next action", render: (row) => (
                  <button
                    className="btn btn-ghost btn-sm"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      openRunEvidence(row);
                    }}
                  >
                    {row.status === "FAILED" ? "Inspect failure" : row.status === "REQUIRES_REVIEW" ? "Open review" : "Open run"}
                  </button>
                ) },
                { key: "report", label: "Report", render: (row) => row.report_artifact ? <button className="btn btn-ghost btn-sm" type="button" onClick={(event) => { event.stopPropagation(); api.downloadUnifiedReport(row.id); }}>Download</button> : <span className="text-muted">None</span> },
              ]}
            />
          </div>
          <ObjectDetailPanel
            title={selectedRun ? objectDisplayName(selectedRun) : "Select a run"}
            subtitle={selectedRun ? `${selectedRun.workflow_type} · ${selectedRun.safety_mode || "safety not recorded"}` : "Run detail shows real jobs, artifacts, logs, and report evidence."}
            status={selectedRun?.status}
            actions={selectedRun ? (
              <>
                <button className="btn btn-primary btn-sm" type="button" onClick={() => openRunEvidence(selectedRun)}>Open evidence</button>
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage ? setPage("brain_review") : null}>Send to Brain Review</button>
                {selectedRun.report_artifact ? <button className="btn btn-ghost btn-sm" type="button" onClick={() => api.downloadUnifiedReport(selectedRun.id)}>Download report</button> : null}
              </>
            ) : null}
            empty={!selectedRun ? <EmptyState title="No run selected" message="Choose a run to inspect current phase, blockers, evidence, and artifacts." compact /> : detail.loading ? <LoadingPanel label="Loading run detail" /> : detail.error ? <ErrorPanel error={detail.error} /> : null}
          >
            {selectedRun ? (
              <>
                <div className="ep-recommendation"><strong>Next action:</strong> {selectedNextAction}</div>
                <SummaryList items={[
                  { label: "Status", value: <StatusBadge status={selectedRun.status} /> },
                  { label: "Safety mode", value: selectedRun.safety_mode },
                  { label: "Current phase", value: selectedRun.current_phase || "Not recorded" },
                  { label: "Created", value: fmtDate(selectedRun.created_at) },
                ]} />
                <div className="divider" />
                <div className="stat-label">Migration run timeline</div>
                <RunTimeline phases={runTimeline} />
                <div className="divider" />
                <div className="stat-label">Input and generated artifacts</div>
                <div className="table-scroll">
                  <table className="tbl">
                    <thead><tr><th>Artifact</th><th>Category</th><th>Created</th></tr></thead>
                    <tbody>
                      {detail.artifacts.map((artifact) => (
                        <tr key={artifact.id}>
                          <td className="td-main">{artifact.original_filename}</td>
                          <td>{artifact.artifact_category}</td>
                          <td>{fmtDate(artifact.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="divider" />
                <div className="stat-label">Redacted logs and warnings</div>
                {!detail.jobs.length ? <EmptyState title="No jobs recorded yet" message="This run has not persisted child jobs yet." compact /> : detail.jobs.map((job) => (
                  <div key={job.id} className="info-tile" style={{ marginBottom: 10 }}>
                    <div className="flex fjb fac gap2">
                      <div>
                        <div className="td-main">{job.module} · {job.phase}</div>
                        <div className="text-muted mt2">{fmtDate(job.started_at || job.created_at)}</div>
                      </div>
                      <StatusBadge status={job.status} />
                    </div>
                    <div className="mt3">
                      <pre className="pq-code-block">{job.logs_redacted || job.error_message || "No logs recorded."}</pre>
                    </div>
                  </div>
                ))}
                <div className="divider" />
                <div className="stat-label">Report preview</div>
                <SummaryList items={[
                  { label: "Title", value: detail.report?.report?.title || selectedRun.name },
                  { label: "Next action", value: selectedRun.next_action || "Review report" },
                  { label: "Warnings", value: detail.report?.report?.risk_register?.length ?? detail.report?.report?.warnings_count ?? 0 },
                  { label: "Generated artifacts", value: detail.report?.report?.generated_artifact_count ?? detail.artifacts.length },
                ]} />
              </>
            ) : null}
          </ObjectDetailPanel>
        </div>
      )}
    </PageTransition>
  );
}

export function MigrationIntelligenceControlPage() {
  const { data: artifacts, loading, error, refresh } = useAsyncLoader(() => api.listControlPlaneArtifacts(), []);
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.listMigrationControlRuns(), []);
  const [tab, setTab] = useState("artifacts");
  const [activeKpi, setActiveKpi] = useState("artifacts");
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [report, setReport] = useState(null);
  const [review, setReview] = useState([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "Migration Readiness Run",
    source_type: "legacy",
    target_type: "snowflake",
    source_dialect: "oracle",
    target_dialect: "snowflake",
    safety_mode: "PLAN_ONLY",
    include_dbt_conversion: true,
    include_validation_plan: true,
    include_provisioning_plan: true,
  });

  const runAssessment = async () => {
    setBusy(true);
    try {
      const created = await api.createMigrationControlRun({
        name: form.name,
        workflow_type: "MIGRATION_READINESS",
        source_type: form.source_type,
        target_type: form.target_type,
        source_dialect: form.source_dialect,
        target_dialect: form.target_dialect,
        safety_mode: form.safety_mode,
        artifact_ids: selectedArtifacts,
        config: {
          include_dbt_conversion: form.include_dbt_conversion,
          include_validation_plan: form.include_validation_plan,
          include_provisioning_plan: form.include_provisioning_plan,
        },
      });
      const nextReport = await api.executeMigrationControlRun(created.id);
      const nextReview = await api.getMigrationHumanReview(created.id);
      setSelectedRun(created);
      setSelectedMigrationRun(created.id);
      setReport(nextReport);
      setReview(nextReview);
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  const openRun = async (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    const [nextReport, nextReview] = await Promise.all([
      api.getMigrationControlReport(run.id),
      api.getMigrationHumanReview(run.id),
    ]);
    setReport(nextReport);
    setReview(nextReview);
  };

  const visibleArtifacts = filterArtifactsForModule(
    artifacts,
    ["sql", "ddl", "txt", "md", "json", "yaml", "yml", "xml", "twb", "twbx", "pdf", "zip", "SOURCE_SQL", "SOURCE_DDL", "REQUIREMENTS", "ETL_XML", "TABLEAU", "DBT_PROJECT"],
    selectedRun?.id || "",
  );

  const contextItems = [
    { label: "Latest run", value: selectedRun?.name || runs?.[0]?.name || "No run selected" },
    { label: "Run status", value: selectedRun ? <StatusBadge status={selectedRun.status} /> : "No run selected" },
    { label: "Artifact count", value: selectedArtifacts.length || visibleArtifacts.length || 0 },
    { label: "Safety mode", value: selectedRun?.safety_mode || form.safety_mode },
    { label: "Readiness score", value: report?.readiness_score ?? "NA" },
    { label: "Complexity score", value: report?.complexity_score ?? "NA" },
    { label: "Report status", value: report ? "Generated" : "Not generated" },
    { label: "Recommended next action", value: report ? "Review risks and choose downstream workflow" : "Upload artifacts and run assessment" },
  ];

  const nextActions = [
    {
      title: "Convert SQL",
      description: "Launch SQL Conversion using the same uploaded source artifacts.",
      reuse: "Reuses selected SQL and DDL evidence. No SQL executes.",
      button: <button className="btn btn-ghost btn-sm" disabled>Convert SQL</button>,
    },
    {
      title: "Generate dbt Models",
      description: "Hand off assessment output into dbt Conversion for model generation.",
      reuse: "Reuses source inventory and dbt recommendations. No dbt runs.",
      button: <button className="btn btn-ghost btn-sm" disabled>Create dbt models</button>,
    },
    {
      title: "Plan Validation",
      description: "Create a validation plan using the target comparison scope.",
      reuse: "Reuses table inventory and risk context. No validation SQL executes.",
      button: <button className="btn btn-ghost btn-sm" disabled>Plan validation</button>,
    },
    {
      title: "Generate Landing Zone Plan",
      description: "Create a plan-only landing-zone resource package.",
      reuse: "Reuses target platform and migration scope. Approval required before apply.",
      button: <button className="btn btn-ghost btn-sm" disabled>Generate plan</button>,
    },
    {
      title: "Open Report",
      description: "Download the persisted migration readiness report.",
      reuse: "Uses the selected run report artifact only.",
      button: <button className="btn btn-primary btn-sm" disabled={!selectedRun} onClick={() => selectedRun && api.downloadUnifiedReport(selectedRun.id)}>Open report</button>,
    },
  ];

  const heroMetrics = [
    { id: "artifacts", label: "Selected artifacts", value: selectedArtifacts.length || 0, detail: "source evidence in scope", tab: "artifacts" },
    { id: "runs", label: "Latest run", value: selectedRun?.name || "Not started", detail: selectedRun?.status || "assessment pending", tab: "assessment" },
    { id: "decisions", label: "Brain decisions", value: review.length || 0, detail: "human judgment required", tab: "review" },
    { id: "report", label: "Report state", value: report ? "Ready" : "Draft", detail: report ? "persisted summary available" : "run assessment to generate", tab: "report" },
  ];

  const openIntelligenceKpi = (metric) => {
    setActiveKpi(metric.id);
    setTab(metric.tab);
  };

  const kpiDrilldownTitle = {
    artifacts: "Selected source evidence",
    runs: "Assessment run history",
    decisions: "Brain Review decisions",
    report: "Readiness report evidence",
  }[activeKpi] || "Migration Intelligence evidence";

  const renderKpiDrilldown = () => {
    if (activeKpi === "runs") {
      return (
        <DataTable
          rows={runs || []}
          onRowClick={openRun}
          emptyTitle="No assessment runs"
          emptyMessage="Run an assessment after selecting source evidence."
          columns={[
            { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "source_dialect", label: "Source" },
            { key: "target_dialect", label: "Target" },
            { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
          ]}
        />
      );
    }
    if (activeKpi === "decisions") {
      return (
        <DataTable
          rows={review || []}
          emptyTitle="No Brain Review decisions"
          emptyMessage="Decision records appear here after assessment finds manual-review blockers."
          columns={[
            { key: "severity", label: "Severity", render: (row) => <SeverityBadge severity={row.severity} /> },
            { key: "item_type", label: "Type" },
            { key: "title", label: "Decision", render: (row) => <span className="td-main">{row.title || row.summary || "Review item"}</span> },
            { key: "evidence", label: "Evidence", render: (row) => <span className="td-main">{String(row.evidence || row.description || "").slice(0, 220) || "No evidence captured"}</span> },
            { key: "recommendation", label: "Recommendation" },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
          ]}
        />
      );
    }
    if (activeKpi === "report") {
      return (
        <div className="pq-kpi-grid">
          <div className="info-tile"><div className="text-muted">Readiness score</div><div className="info-tile-value">{report?.readiness_score ?? "Not generated"}</div></div>
          <div className="info-tile"><div className="text-muted">Complexity score</div><div className="info-tile-value">{report?.complexity_score ?? "Not generated"}</div></div>
          <div className="info-tile"><div className="text-muted">Risk count</div><div className="info-tile-value">{report?.risk_register?.length ?? 0}</div></div>
          <div className="info-tile"><div className="text-muted">Next action</div><div className="info-tile-value">{report ? "Review risks and choose downstream workflow" : "Select evidence and run assessment"}</div></div>
        </div>
      );
    }
    const rows = visibleArtifacts.filter((artifact) => selectedArtifacts.includes(artifact.id));
    return (
      <DataTable
        rows={rows}
        emptyTitle="No selected evidence"
        emptyMessage="Click source artifacts below to add them to the assessment scope."
        columns={[
          { key: "original_filename", label: "Artifact", render: (row) => <span className="td-main">{row.original_filename}</span> },
          { key: "file_type", label: "Type" },
          { key: "artifact_category", label: "Category" },
          { key: "size_bytes", label: "Size", render: (row) => `${Math.max(1, Math.round((row.size_bytes || 0) / 1024))} KB` },
          { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
        ]}
      />
    );
  };

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="Migration Intelligence"
        subtitle="Guide source discovery into a persisted migration readiness assessment with object inventory, SQL findings, dbt opportunity signals, validation planning, and provisioning recommendations."
        status={selectedRun?.status}
        primaryAction={<button className="btn btn-primary" disabled={!selectedArtifacts.length || busy} onClick={runAssessment}>{busy ? "Running" : "Run assessment"}</button>}
        secondaryAction={<button className="btn btn-ghost" onClick={refresh}>Refresh artifacts</button>}
      />
      <ErrorPanel error={error} />
      <OperationsAlertStrip
        items={(report?.risk_register || []).slice(0, 3).map((risk, index) => ({
          id: `${index}`,
          title: risk.title || risk.message || risk,
          status: risk.severity || "REQUIRES_REVIEW",
          action: risk.recommended_action || "Review assessment risk",
        }))}
        fallback={report ? "No critical assessment blockers in the selected report." : "Upload evidence and run an assessment to populate readiness blockers."}
      />
      <EnterpriseKpiRow items={heroMetrics.map((metric) => ({
        label: metric.label,
        value: metric.value,
        note: metric.detail,
        active: activeKpi === metric.id,
        onClick: () => openIntelligenceKpi(metric),
      }))} />
      <div className="ep-list-panel" style={{ marginBottom: 12 }}>
        <div className="ep-list-head">
          <div>
            <div className="ep-list-title">{kpiDrilldownTitle}</div>
            <div className="ep-list-subtitle">Opened from the Migration Intelligence KPI strip. Use this panel to inspect evidence before moving downstream.</div>
          </div>
          <StatusBadge status={selectedRun?.status || (report ? "READY" : "DRAFT")} />
        </div>
        <div style={{ padding: 12 }}>
          {renderKpiDrilldown()}
        </div>
      </div>
      <div className="ep-workspace" style={{ gridTemplateColumns: "minmax(0,1fr) 340px" }}>
        <div>
          <div className="mi-workspace-shell">
            <div className="mi-workspace-header">
              <div>
                <div className="mi-workspace-title">Migration operating workspace</div>
                <div className="mi-workspace-subtitle">Move through intake, configuration, assessment, review, and reporting without losing context.</div>
              </div>
            </div>
            <WorkspaceTabs
              active={tab}
              onChange={setTab}
              tabs={[
                { id: "artifacts", label: "Artifacts" },
                { id: "configuration", label: "Configuration" },
                { id: "assessment", label: "Assessment" },
                { id: "review", label: "Review" },
                { id: "report", label: "Report" },
                { id: "next_actions", label: "Next Actions" },
              ]}
            />
          </div>
          {tab === "artifacts" ? (
            <div className="soft-grid mt4 mi-intake-grid">
              <SectionCard title="Source package intake" subtitle="Upload migration evidence and define the source package for this readiness run.">
                <div className="mi-upload-panel">
                  <FileUploadDropzone
                    onUploaded={refresh}
                    accept=".sql,.ddl,.txt,.md,.json,.yaml,.yml,.xml,.twb,.twbx,.pdf,.zip"
                    title="Upload source artifacts"
                    message="SQL, DDL, runbooks, XML, Tableau, PDFs, and dbt project zips are supported."
                  />
                  <div className="mi-upload-guidance">
                    <div className="mi-guidance-title">What this tab does</div>
                    <ul className="mi-guidance-list">
                      <li>Collects source migration evidence and persists it for reuse across downstream workflows.</li>
                      <li>Lets you choose the exact artifact package that feeds readiness assessment.</li>
                      <li>Excludes unrelated generated outputs so discovery stays focused on inputs.</li>
                    </ul>
                  </div>
                </div>
              </SectionCard>
              <SectionCard title="Artifact inventory" subtitle="Only source artifacts and artifacts tied to the selected Migration Intelligence run appear here." loading={loading}>
                <DataTable
                  rows={visibleArtifacts.map((artifact) => ({ ...artifact, selected_for_run: selectedArtifacts.includes(artifact.id) }))}
                  emptyTitle="No source artifacts uploaded yet"
                  emptyMessage="Upload SQL, DDL, documents, XML, Tableau, or dbt project zips to start migration discovery."
                  emptyAction={(
                    <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                      <button className="btn btn-primary btn-sm" type="button" onClick={() => setTab("artifacts")}>Upload source artifacts</button>
                    </div>
                  )}
                  columns={[
                    { key: "selected_for_run", label: "Selected", render: (row) => <input type="checkbox" checked={selectedArtifacts.includes(row.id)} onChange={() => setSelectedArtifacts((current) => current.includes(row.id) ? current.filter((value) => value !== row.id) : [...current, row.id])} /> },
                    { key: "original_filename", label: "File", render: (row) => <span className="td-main">{row.original_filename}</span> },
                    { key: "file_type", label: "Type" },
                    { key: "artifact_category", label: "Category" },
                    { key: "size_bytes", label: "Size", render: (row) => `${Math.max(1, Math.round((row.size_bytes || 0) / 1024))} KB` },
                    { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                    { key: "preview", label: "Preview", render: (row) => <button className="btn btn-ghost btn-sm" onClick={(event) => event.stopPropagation()}>Preview</button> },
                  ]}
                />
              </SectionCard>
            </div>
          ) : null}
          {tab === "configuration" ? (
            <SectionCard title="Configuration" subtitle="Define the migration assessment run that will be persisted and reported." actions={<button className="btn btn-primary btn-sm" disabled={!selectedArtifacts.length || busy} onClick={runAssessment}>{busy ? "Running" : "Run assessment"}</button>}>
              <Field label="Run name"><input className="fi" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
              <div className="fr">
                <Field label="Source platform"><input className="fi" value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })} /></Field>
                <Field label="Target platform"><input className="fi" value={form.target_type} onChange={(event) => setForm({ ...form, target_type: event.target.value })} /></Field>
              </div>
              <div className="fr">
                <Field label="Source dialect"><select className="fi" value={form.source_dialect} onChange={(event) => setForm({ ...form, source_dialect: event.target.value })}>{DIALECTS.map((dialect) => <option key={dialect}>{dialect}</option>)}</select></Field>
                <Field label="Target dialect"><select className="fi" value={form.target_dialect} onChange={(event) => setForm({ ...form, target_dialect: event.target.value })}><option>snowflake</option></select></Field>
              </div>
              <Field label="Safety mode"><select className="fi" value={form.safety_mode} onChange={(event) => setForm({ ...form, safety_mode: event.target.value })}>{SAFETY_MODES.map((mode) => <option key={mode}>{mode}</option>)}</select></Field>
              <label className="settings-row"><span className="settings-key">Include SQL analysis</span><input type="checkbox" checked={true} readOnly /></label>
              <label className="settings-row"><span className="settings-key">Include dbt recommendation</span><input type="checkbox" checked={form.include_dbt_conversion} onChange={(event) => setForm({ ...form, include_dbt_conversion: event.target.checked })} /></label>
              <label className="settings-row"><span className="settings-key">Include validation plan</span><input type="checkbox" checked={form.include_validation_plan} onChange={(event) => setForm({ ...form, include_validation_plan: event.target.checked })} /></label>
              <label className="settings-row"><span className="settings-key">Include provisioning plan</span><input type="checkbox" checked={form.include_provisioning_plan} onChange={(event) => setForm({ ...form, include_provisioning_plan: event.target.checked })} /></label>
              {!selectedArtifacts.length ? <DisabledReason>Select at least one source artifact in the Artifacts tab before running assessment.</DisabledReason> : null}
            </SectionCard>
          ) : null}
          {tab === "assessment" ? (
            <>
              <div className="stats-grid mt4">
                <StatCard label="Readiness score" value={report?.readiness_score ?? "NA"} helper="How ready the migration package is for downstream conversion." />
                <StatCard label="Complexity score" value={report?.complexity_score ?? "NA"} helper="Composite score from SQL, ETL, and review complexity." />
                <StatCard label="Risks" value={report?.risk_register?.length ?? 0} helper="Review blockers and warnings discovered." />
                <StatCard label="Decision items" value={review.length} helper="Human judgment records persisted for this run." />
              </div>
              <SectionCard title="Assessment runs" subtitle="Persisted readiness runs and the current selected report.">
                <DataTable
                  rows={runs || []}
                  onRowClick={openRun}
                  emptyTitle="No migration intelligence runs yet"
                  emptyMessage="Run an assessment after selecting artifacts and configuration."
                  columns={[
                    { key: "name", label: "Run name", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                    { key: "source_dialect", label: "Source dialect" },
                    { key: "safety_mode", label: "Safety mode" },
                    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                    { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                  ]}
                />
              </SectionCard>
              <div className="soft-grid mt4">
                <SectionCard title="Object inventory" subtitle="Detected inventory and discovered references from uploaded artifacts.">
                  <DataTable
                    rows={(report?.source_inventory || []).map((row, index) => ({ id: `${index}`, ...row }))}
                    emptyTitle="No object inventory yet"
                    emptyMessage="Run assessment to build source inventory."
                    columns={[
                      { key: "file_name", label: "Artifact", render: (row) => <span className="td-main">{row.file_name}</span> },
                      { key: "category", label: "Category" },
                      { key: "line_count", label: "Lines" },
                      { key: "detected_references", label: "References", render: (row) => row.detected_references?.slice(0, 3).join(", ") || "None" },
                    ]}
                  />
                </SectionCard>
                <SectionCard title="Findings" subtitle="SQL risks, ETL/BI complexity, and dbt opportunities surfaced by the engine.">
                  <SummaryList items={[
                    { label: "SQL findings", value: report?.sql_conversion_readiness?.summary?.WARN ?? 0 },
                    { label: "ETL/BI findings", value: report?.etl_bi_dependency_analysis?.dependency_count ?? 0 },
                    { label: "dbt opportunities", value: report?.source_to_target_mapping?.length ?? 0 },
                    { label: "Validation plan", value: report?.validation_plan?.checks?.join(", ") || "Not planned" },
                  ]} />
                </SectionCard>
              </div>
            </>
          ) : null}
          {tab === "review" ? (
            <SectionCard title="Human decisions" subtitle="Evidence requiring analyst or architect judgment before downstream implementation.">
              <DataTable
                rows={review}
                emptyTitle="No decision items"
                emptyMessage="This run did not generate human decision blockers."
                columns={[
                  { key: "severity", label: "Severity", render: (row) => <SeverityBadge severity={row.severity} /> },
                  { key: "item_type", label: "Type" },
                  { key: "title", label: "Title", render: (row) => <span className="td-main">{row.title}</span> },
                  { key: "evidence", label: "Evidence", render: (row) => <span className="td-main">{String(row.evidence || row.description || "").slice(0, 220) || "No evidence captured"}</span> },
                  { key: "recommendation", label: "Recommendation" },
                  { key: "status", label: "Status" },
                  { key: "reviewer_comment", label: "Reviewer comment", render: (row) => row.reviewer_comment || "Not reviewed" },
                ]}
              />
            </SectionCard>
          ) : null}
          {tab === "report" ? (
            <ReportPreview report={report} emptyMessage="Run assessment to create a Migration Readiness Report." />
          ) : null}
          {tab === "next_actions" ? (
            <>
              <FooterActionBar actions={nextActions} />
              <DisabledReason>Downstream actions remain plan-only and create their own persisted runs in the dedicated modules.</DisabledReason>
            </>
          ) : null}
        </div>
        <div>
          <ContextRail title="Migration context" items={contextItems} />
          {selectedRun ? <ReportPreview title="Latest report snapshot" report={report} emptyMessage="No report generated for the selected run yet." /> : null}
        </div>
      </div>
    </PageTransition>
  );
}

export function SqlConversionControlPage({ setPage = null }) {
  const { data: artifacts, refresh } = useAsyncLoader(() => api.listControlPlaneArtifacts(), []);
  const { data: runs, loading, error, refresh: refreshRuns } = useAsyncLoader(() => api.listSqlConversionRuns(), []);
  const [tab, setTab] = useState("intake");
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [report, setReport] = useState(null);
  const [messages, setMessages] = useState([]);
  const [runArtifacts, setRunArtifacts] = useState([]);
  const [runDetail, setRunDetail] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewArtifact, setPreviewArtifact] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "SQL Conversion Run", source_dialect: "oracle", target_dialect: "snowflake", safety_mode: "PLAN_ONLY" });

  const openRun = async (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    const [nextReport, nextMessages, nextArtifacts, nextDetail] = await Promise.all([
      api.getSqlConversionReport(run.id),
      api.getSqlConversionMessages(run.id),
      api.getSqlConversionArtifacts(run.id),
      api.getControlPlaneRunDetail(run.id).catch(() => null),
    ]);
    setReport(nextReport);
    setMessages(nextMessages);
    setRunArtifacts(nextArtifacts);
    setRunDetail(nextDetail);
    const generated = nextArtifacts.find((artifact) => artifact.artifact_category === "GENERATED_SQL")
      || nextArtifacts.find((artifact) => artifact.artifact_category === "GENERATED_DBT");
    if (generated) {
      setPreviewArtifact(generated);
      setPreview(await api.previewControlPlaneArtifact(generated.id));
    } else {
      setPreviewArtifact(null);
      setPreview(null);
    }
  };

  const analyze = async () => {
    setBusy(true);
    try {
      const run = await api.createSqlConversionRun({
        name: form.name,
        workflow_type: "SQL_CONVERSION",
        source_dialect: form.source_dialect,
        target_dialect: form.target_dialect,
        safety_mode: form.safety_mode,
        artifact_ids: selectedArtifacts,
      });
      await api.analyzeSqlConversionRun(run.id);
      await openRun(run);
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  const translate = async () => {
    if (!selectedRun) return;
    setBusy(true);
    try {
      await api.translateSqlConversionRun(selectedRun.id);
      await openRun(selectedRun);
    } finally {
      setBusy(false);
    }
  };

  const counts = useMemo(() => messages.reduce((acc, message) => ({ ...acc, [message.severity]: (acc[message.severity] || 0) + 1 }), {}), [messages]);
  const visibleArtifacts = filterArtifactsForModule(artifacts, ["sql", "ddl", "txt", "md", "SOURCE_SQL", "SOURCE_DDL"], selectedRun?.id || "");
  const translatedArtifacts = runArtifacts.filter((artifact) => ["GENERATED_SQL", "GENERATED_DBT"].includes(artifact.artifact_category));
  const sourceArtifacts = runArtifacts.filter((artifact) => ["SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT"].includes(artifact.artifact_category));
  const sqlContextItems = [
    { label: "Selected run", value: selectedRun?.name || "No run selected" },
    { label: "Run ID", value: selectedRun?.id || "No run selected" },
    { label: "Status", value: selectedRun ? <StatusBadge status={selectedRun.status} /> : "No run selected" },
    { label: "Source dialect", value: selectedRun?.source_dialect || form.source_dialect },
    { label: "Source artifacts", value: sourceArtifacts.length },
    { label: "Converted artifacts", value: translatedArtifacts.length },
    { label: "Brain decisions", value: runDetail?.brain_review_decisions?.length ?? 0 },
    { label: "Validation status", value: runDetail?.validation?.validation_status || "not_run" },
    { label: "Safety mode", value: selectedRun?.safety_mode || form.safety_mode },
    { label: "Readiness score", value: report?.readiness_score ?? "NA" },
    { label: "Translation status", value: report?.translation_status || report?.translation?.status || "Not generated" },
  ];

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="SQL Conversion"
        subtitle="Analyze source SQL and DDL for Snowflake conversion readiness, persist findings, and generate translated artifacts only when a deterministic translation engine is available."
        status={selectedRun?.status}
        primaryAction={<button className="btn btn-primary" disabled={!selectedArtifacts.length || busy} onClick={analyze}>{busy ? "Running" : "Analyze"}</button>}
        secondaryAction={<div className="flex gap2"><button className="btn btn-ghost" disabled={!selectedRun || busy} onClick={translate}>Translate</button><button className="btn btn-ghost" disabled={!selectedRun || !setPage} onClick={() => setPage && setPage("run_detail")}>Run Detail</button></div>}
      />
      <OperationsAlertStrip
        items={(messages || []).filter((message) => ["ERROR", "FATAL", "WARN"].includes(message.severity)).map((message, index) => ({
          id: `${message.file_name || "sql"}-${index}`,
          title: message.message || message.rule_id || "SQL conversion message",
          status: message.severity,
          action: message.recommendation || "Review SQL message",
        }))}
        fallback={selectedRun ? "No blocking SQL conversion messages for the selected run." : "Create or select a SQL conversion run to populate blockers."}
      />
      <EnterpriseKpiRow items={[
        { label: "Run", value: selectedRun ? objectDisplayName(selectedRun) : "None", note: selectedRun ? selectedRun.safety_mode : "select or create", active: tab === "analyze", onClick: () => setTab("analyze") },
        { label: "Readiness", value: report?.readiness_score ?? "NA", note: "backend analysis", active: tab === "report", onClick: () => setTab("report") },
        { label: "Info", value: counts.INFO || 0, note: "parser findings", active: tab === "messages", onClick: () => setTab("messages") },
        { label: "Warnings", value: (counts.WARN || 0) + (counts.ERROR || 0) + (counts.FATAL || 0), note: "needs review", active: tab === "messages", onClick: () => setTab("messages") },
        { label: "Artifacts", value: translatedArtifacts.length, note: "generated outputs", active: tab === "artifacts", onClick: () => setTab("artifacts") },
        { label: "Status", value: selectedRun ? <StatusBadge status={selectedRun.status} /> : "Not selected", note: "conversion state", active: tab === "analyze", onClick: () => setTab("analyze") },
      ]} />
      <div className="ep-workspace">
        <div className="ep-list-panel">
          <div className="ep-list-head"><div><div className="ep-list-title">SQL review workspace</div><div className="ep-list-subtitle">Select a run and inspect source artifacts, converted SQL, messages, reports, and downloads.</div></div></div>
          {selectedRun ? (
            <div className="ep-code-grid" style={{ padding: 12 }}>
              <div className="ep-code-pane"><div className="ep-code-title">Original SQL / selected artifact</div><pre>{preview?.source_text || report?.source_sql || "Select or preview a source artifact to inspect original SQL."}</pre></div>
              <div className="ep-code-pane"><div className="ep-code-title">{previewArtifact ? `Converted: ${previewArtifact.original_filename}` : "Converted SQL"}</div><pre>{preview?.text || preview?.content || "No converted SQL preview is available yet."}</pre></div>
            </div>
          ) : (
            <div style={{ padding: 12 }}><EmptyState title="No SQL conversion run selected" message="Upload SQL/DDL artifacts, select them, and analyze to open a code-review workspace." compact /></div>
          )}
        </div>
        <ObjectDetailPanel title="Conversion evidence" subtitle={selectedRun ? "Warnings, unsupported features, report, and next action." : "Select a run to populate evidence."} status={selectedRun?.status}>
          <div className="ep-section-label">Top messages</div>
          {(messages || []).slice(0, 6).length ? (messages || []).slice(0, 6).map((message, index) => (
            <div key={index} className="ep-empty-compact"><StatusBadge status={message.severity} /> {message.message || message.rule_id || message.severity}</div>
          )) : <div className="ep-empty-compact">No conversion messages have been generated for this run yet.</div>}
          <div className="ep-section-label">Downloads</div>
          {translatedArtifacts.length ? translatedArtifacts.slice(0, 4).map((artifact) => <button key={artifact.id} className="btn btn-ghost btn-sm" onClick={() => api.downloadControlPlaneArtifact(artifact.id, artifact.original_filename)}>{artifact.original_filename}</button>) : <div className="ep-empty-compact">Review artifacts appear after translation.</div>}
        </ObjectDetailPanel>
      </div>
      <ErrorPanel error={error} />
      {loading ? <LoadingPanel label="Loading SQL conversion runs" /> : (
        <div className="pq-master-detail" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
          <div>
            <WorkspaceTabs
              active={tab}
              onChange={setTab}
              tabs={[
                { id: "intake", label: "Intake" },
                { id: "analyze", label: "Analyze" },
                { id: "translate", label: "Translate" },
                { id: "messages", label: "Messages" },
                { id: "artifacts", label: "Artifacts" },
                { id: "report", label: "Report" },
              ]}
            />
            {tab === "intake" ? (
              <div className="soft-grid mt4">
                <FileUploadDropzone onUploaded={refresh} accept=".sql,.ddl,.txt,.md" title="SQL intake" message="Upload SQL and DDL artifacts for analysis. No SQL executes by default." />
                <SectionCard title="Conversion setup" subtitle="Configure dialects, safety mode, and run metadata for this SQL conversion assessment.">
                  <Field label="Run name"><input className="fi" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
                  <div className="fr">
                    <Field label="Source dialect"><select className="fi" value={form.source_dialect} onChange={(event) => setForm({ ...form, source_dialect: event.target.value })}>{DIALECTS.map((dialect) => <option key={dialect}>{dialect}</option>)}</select></Field>
                    <Field label="Target dialect"><select className="fi" value={form.target_dialect} onChange={(event) => setForm({ ...form, target_dialect: event.target.value })}><option>snowflake</option></select></Field>
                  </div>
                  <Field label="Safety mode"><select className="fi" value={form.safety_mode} onChange={(event) => setForm({ ...form, safety_mode: event.target.value })}>{SAFETY_MODES.map((mode) => <option key={mode}>{mode}</option>)}</select></Field>
                  {!selectedArtifacts.length ? <DisabledReason>Select one or more SQL or DDL artifacts to enable analysis.</DisabledReason> : null}
                </SectionCard>
              </div>
            ) : null}
            {tab === "intake" ? <ArtifactSelector
              artifacts={visibleArtifacts || []}
              selected={selectedArtifacts}
              setSelected={setSelectedArtifacts}
              allowedTypes={["sql", "ddl", "txt", "md", "SOURCE_SQL", "SOURCE_DDL"]}
              selectedRunId={selectedRun?.id || ""}
              emptyAction={(
                <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-primary btn-sm" type="button" onClick={() => document.querySelector('input[type="file"]')?.click()}>Upload SQL/dbt project</button>
                  <button className="btn btn-ghost btn-sm" type="button" disabled>Select persisted artifact</button>
                </div>
              )}
            /> : null}
            {tab === "analyze" ? (
              <>
                <div className="stats-grid mt4">
                  <StatCard label="Files analyzed" value={report?.summary?.files ?? 0} />
                  <StatCard label="Statements analyzed" value={report?.summary?.statements ?? 0} />
                  <StatCard label="INFO" value={counts.INFO || 0} />
                  <StatCard label="WARN" value={counts.WARN || 0} />
                  <StatCard label="ERROR" value={counts.ERROR || 0} />
                  <StatCard label="FATAL" value={counts.FATAL || 0} />
                  <StatCard label="Readiness score" value={report?.readiness_score ?? "NA"} />
                </div>
                <SectionCard title="Analyze runs" subtitle="Persisted SQL conversion assessments." actions={<button className="btn btn-primary btn-sm" disabled={!selectedArtifacts.length || busy} onClick={analyze}>{busy ? "Running" : "Analyze"}</button>}>
                  <DataTable
                    rows={runs || []}
                    onRowClick={openRun}
                    emptyTitle="No SQL conversion runs yet"
                    emptyMessage="Upload SQL or DDL artifacts and run analysis to create a persisted conversion assessment."
                    columns={[
                      { key: "name", label: "Run name", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                      { key: "source_dialect", label: "Source" },
                      { key: "safety_mode", label: "Safety mode" },
                      { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                      { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                    ]}
                  />
                </SectionCard>
              </>
            ) : null}
            {tab === "translate" ? (
              <>
                <SectionCard title="Translation status" subtitle="Translation creates Snowflake SQL and dbt model artifacts when the deterministic engine supports the selected statements." actions={<button className="btn btn-primary btn-sm" disabled={!selectedRun || busy} onClick={translate}>Translate</button>}>
                  {report?.translation_note ? <div className="alert-info">{report.translation_note}</div> : null}
                  {!translatedArtifacts.length ? (
                    <EmptyState title="No converted artifacts generated yet" message="SQL analysis completed. Translation engine is not configured, so no Snowflake SQL or dbt output was generated." compact />
                  ) : (
                    <DataTable
                      rows={translatedArtifacts}
                      onRowClick={async (artifact) => {
                        setPreviewArtifact(artifact);
                        setPreview(await api.previewControlPlaneArtifact(artifact.id));
                      }}
                      columns={[
                        { key: "original_filename", label: "File", render: (row) => <span className="td-main">{row.original_filename}</span> },
                        { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                      ]}
                    />
                  )}
                </SectionCard>
                <CodeViewer title="Converted SQL preview" preview={preview} artifact={previewArtifact} />
              </>
            ) : null}
            {tab === "messages" ? (
              <SectionCard title="Messages" subtitle="Statement-level parser, severity, and recommendation output from the SQL analysis engine.">
                <DataTable
                  rows={messages}
                  emptyTitle="No messages yet"
                  emptyMessage="Analyze a SQL conversion run to populate INFO, WARN, ERROR, and FATAL messages."
                  columns={[
                    { key: "severity", label: "Severity", render: (row) => <SeverityBadge severity={row.severity} /> },
                    { key: "file_name", label: "File" },
                    { key: "statement_index", label: "Statement" },
                    { key: "statement_type", label: "Statement type" },
                    { key: "message", label: "Message" },
                    { key: "recommendation", label: "Recommendation" },
                  ]}
                />
              </SectionCard>
            ) : null}
            {tab === "artifacts" ? (
              <SectionCard title="Artifacts" subtitle="Snowflake SQL and dbt conversion outputs for the selected run appear here.">
                <DataTable
                  rows={translatedArtifacts}
                  onRowClick={async (artifact) => {
                    setPreviewArtifact(artifact);
                    setPreview(await api.previewControlPlaneArtifact(artifact.id));
                  }}
                  emptyTitle="No converted artifacts yet"
                  emptyMessage="Translation artifacts appear here after a successful translation pass."
                  columns={[
                    { key: "original_filename", label: "Artifact", render: (row) => <span className="td-main">{row.original_filename}</span> },
                    { key: "artifact_category", label: "Category" },
                    { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                  ]}
                />
              </SectionCard>
            ) : null}
            {tab === "report" ? <ReportPreview report={report} emptyMessage="Run SQL analysis to create a SQL Conversion Report." /> : null}
          </div>
          <div>
            <ContextRail title="SQL conversion context" items={sqlContextItems} />
            <CodeViewer title="Selected SQL artifact" preview={preview} artifact={previewArtifact} />
          </div>
        </div>
      )}
    </PageTransition>
  );
}

export function DbtConversionPage({ setPage = null }) {
  const { data: artifacts, refresh } = useAsyncLoader(() => api.listControlPlaneArtifacts(), []);
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.listConversionJobs(), []);
  const { data: projects, refresh: refreshProjects } = useAsyncLoader(() => api.listDbtProjects(), []);
  const [tab, setTab] = useState("conversion");
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [report, setReport] = useState(null);
  const [runArtifacts, setRunArtifacts] = useState([]);
  const [runDetail, setRunDetail] = useState(null);
  const [jobLogs, setJobLogs] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewArtifact, setPreviewArtifact] = useState(null);
  const [projectReport, setProjectReport] = useState(null);
  const [copilotQuestion, setCopilotQuestion] = useState("Is this Snowflake-ready?");
  const [copilotAnswer, setCopilotAnswer] = useState(null);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [aiPatch, setAiPatch] = useState(null);
  const [patchBusy, setPatchBusy] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [validationBusy, setValidationBusy] = useState(false);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [fileReviewTab, setFileReviewTab] = useState("summary");
  const [busy, setBusy] = useState(false);
  const [snowflakeValidation, setSnowflakeValidation] = useState({
    account: "",
    user: "",
    role: "",
    warehouse: "",
    database: "",
    schema: "",
    password: "",
  });
  const [form, setForm] = useState({
    name: "Snowflake dbt Conversion",
    dbt_project_name: "uma_migration",
    source_dialect: "auto_detect",
    target_type: "snowflake",
    default_database: "ANALYTICS",
    default_schema: "MARTS",
    dbt_profile_name: "",
    model_naming_convention: "snake_case",
    default_materialization: "view",
    safety_mode: "PLAN_ONLY",
  });

  const visibleArtifacts = filterArtifactsForModule(
    artifacts,
    ["sql", "ddl", "zip", "json", "SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT", "REQUIREMENTS"],
    selectedRun?.id || "",
  );
  const packageArtifact = (runArtifacts || []).find((artifact) => artifact.artifact_category === "CONVERSION_PACKAGE");
  const brainFiles = report?.conversion_context?.files || [];
  const reviewFiles = brainFilesFromReport(report);
  const selectedFile = reviewFiles[Math.min(selectedFileIndex, Math.max(reviewFiles.length - 1, 0))] || {};
  const brainTranscript = useMemo(() => buildUmaBrainReviewTranscript(report, selectedRun), [report, selectedRun]);
  const jobState = conversionJobState(report, selectedRun);
  const canDownloadPackage = selectedRun && packageArtifact && conversionDownloadAllowed(jobState);
  const groupedDownloads = downloadGroups(runArtifacts, canDownloadPackage);
  const aiMode = aiModeSummary(report);
  const productStatus = conversionProductStatus(jobState);
  const issueCards = modelIssueCards(selectedFile, jobState);
  const readyReason = readinessReason(jobState, reviewFiles);
  const canProposeAiPatch = selectedRun && selectedFile?.source_path && aiPatchProposalAllowed(report);
  const canValidateSnowflake = selectedRun && validationCredentialsComplete(snowflakeValidation);

  const openRun = async (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    const [nextReport, allArtifacts, jobs, nextDetail] = await Promise.all([
      api.getConversionJobReport(run.id),
      api.listControlPlaneArtifacts(),
      api.getControlPlaneRunJobs(run.id).catch(() => []),
      api.getControlPlaneRunDetail(run.id).catch(() => null),
    ]);
    const nextArtifacts = (allArtifacts || []).filter((artifact) => artifact.run_id === run.id);
    setReport(nextReport);
    setRunArtifacts(nextArtifacts);
    setRunDetail(nextDetail);
    setJobLogs(jobs || []);
    setCopilotAnswer(null);
    setAiPatch(null);
    setValidationResult(nextReport?.validation || null);
    setSelectedFileIndex(0);
    const generated = nextArtifacts.find((artifact) => ["GENERATED_SQL", "GENERATED_DBT"].includes(artifact.artifact_category));
    if (generated) {
      setPreviewArtifact(generated);
      setPreview(await api.previewControlPlaneArtifact(generated.id));
    } else {
      setPreviewArtifact(null);
      setPreview(null);
    }
  };

  const analyze = async () => {
    setBusy(true);
    try {
      const run = await api.createConversionJob({
        name: form.name,
        workflow_type: "SQL_DBT_TO_SNOWFLAKE",
        source_platform: form.source_dialect,
        source_dialect: form.source_dialect,
        target_type: form.target_type,
        target_dialect: "snowflake",
        safety_mode: form.safety_mode,
        artifact_ids: selectedArtifacts,
        input_type: inferConversionInputType(selectedArtifacts, artifacts || []),
        config: {
          dbt_project_name: form.dbt_project_name,
          default_database: form.default_database,
          default_schema: form.default_schema,
          dbt_profile_name: form.dbt_profile_name,
          model_naming_convention: form.model_naming_convention,
          default_materialization: form.default_materialization,
        },
      });
      await api.analyzeConversionJob(run.id);
      await openRun(run);
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!selectedRun) return;
    setBusy(true);
    try {
      await api.convertConversionJob(selectedRun.id);
      await refresh();
      await openRun(selectedRun);
    } finally {
      setBusy(false);
    }
  };

  const runBrain = async () => {
    if (!selectedRun) return;
    setBusy(true);
    try {
      const nextReport = await api.agenticConvertConversionJob(selectedRun.id, { provider: "auto" });
      setReport(nextReport);
      await refresh();
      await refreshRuns();
      await openRun(selectedRun);
      setTab("brain");
    } finally {
      setBusy(false);
    }
  };

  const askConversionCopilot = async (question = copilotQuestion) => {
    if (!selectedRun || !question.trim()) return;
    setCopilotBusy(true);
    try {
      setCopilotQuestion(question);
      setCopilotAnswer(await api.chatConversionJobCopilot(selectedRun.id, question));
    } finally {
      setCopilotBusy(false);
    }
  };

  const proposeAiPatch = async () => {
    if (!selectedRun || !selectedFile?.source_path || !canProposeAiPatch) return;
    setPatchBusy(true);
    try {
      const patch = await api.proposeConversionAiPatch(selectedRun.id, {
        selected_file: selectedFile.source_path || selectedFile.target_path,
        original_sql: selectedFile.original_sql,
        converted_sql: selectedFile.converted_sql,
        diff: selectedFile.diff || selectedFile.diff_summary?.diff,
        rules_applied: selectedFile.rules_applied || [],
        readiness_reasons: selectedFile.readiness_reasons || jobState.readiness_reasons || [],
        warnings: selectedFile.warnings || [],
        source_residue: selectedFile.source_residue || [],
        unsupported_features: selectedFile.unsupported_features || [],
        dbt_metadata: selectedFile.dbt_metadata || {},
        rag_context: selectedFile.rag_results || [],
      });
      setAiPatch(patch);
    } finally {
      setPatchBusy(false);
    }
  };

  const applyReviewedPatch = async () => {
    if (!selectedRun || !aiPatch?.patch_id || aiPatch.status !== "PROPOSED") return;
    setPatchBusy(true);
    try {
      await api.applyConversionAiPatch(selectedRun.id, aiPatch.patch_id, { confirmed: true });
      await openRun(selectedRun);
    } finally {
      setPatchBusy(false);
    }
  };

  const validateInSnowflake = async () => {
    if (!selectedRun || !canValidateSnowflake) return;
    setValidationBusy(true);
    try {
      const validation = await api.validateConversionJob(selectedRun.id, snowflakeValidation);
      setValidationResult(validation);
      await openRun(selectedRun);
    } finally {
      setValidationBusy(false);
    }
  };

  useEffect(() => {
    if (!selectedRun && runs?.length && tab === "conversion") {
      openRun(runs[0]);
    }
  }, [runs, selectedRun, tab]);

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="dbt Conversion"
        subtitle="Convert persisted SQL and dbt project artifacts into Snowflake-compatible SQL and dbt outputs offline, without requiring Snowflake credentials during conversion."
        status={jobState.status || selectedRun?.status}
        primaryAction={<button className="btn btn-primary" disabled={!selectedArtifacts.length || busy} onClick={analyze}>{busy ? "Running" : "Analyze conversion"}</button>}
        secondaryAction={<div className="flex gap2"><button className="btn btn-ghost" disabled={!selectedRun || busy} onClick={runBrain}>Run UMA brain</button><button className="btn btn-ghost" disabled={!selectedRun || busy} onClick={generate}>Convert to Snowflake</button><button className="btn btn-ghost" disabled={!selectedRun || !setPage} onClick={() => setPage && setPage("run_detail")}>Run Detail</button>{canDownloadPackage ? <button className="btn btn-ghost" onClick={() => api.downloadConversionJob(selectedRun.id)}>Download package</button> : null}</div>}
      />
      <div className="tabs">
        <div className={`tab ${tab === "conversion" ? "active" : ""}`} onClick={() => setTab("conversion")}>dbt Conversion</div>
        <div className={`tab ${tab === "brain" ? "active" : ""}`} onClick={() => setTab("brain")}>UMA Brain Review</div>
        <div className={`tab ${tab === "project" ? "active" : ""}`} onClick={() => setTab("project")}>Existing dbt Project Analysis</div>
      </div>
      {tab === "conversion" ? (
        <>
          <style>{`
            .conversion-review-shell{display:grid;gap:16px}
            .conversion-review-head{background:#fff;border:1px solid #d0d5dd;border-radius:8px;padding:18px;display:flex;gap:18px;align-items:flex-start;justify-content:space-between}
            .conversion-review-title{font-size:24px;font-weight:850;color:#182230;letter-spacing:0;line-height:1.2}
            .conversion-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
            .conversion-chip{border:1px solid #d0d5dd;border-radius:999px;padding:5px 10px;background:#f9fafb;color:#344054;font-size:12px;font-weight:750}
            .conversion-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}
            .review-workspace{display:grid;grid-template-columns:280px minmax(0,1fr) 340px;gap:14px;align-items:start}
            .workspace-panel{background:#fff;border:1px solid #d0d5dd;border-radius:8px;min-width:0}
            .workspace-panel-head{padding:14px 14px 10px;border-bottom:1px solid #eaecf0}
            .workspace-panel-title{font-weight:850;color:#182230}
            .workspace-panel-subtitle{font-size:12px;color:#667085;margin-top:4px;line-height:1.35}
            .workspace-panel-body{padding:14px}
            .file-list{display:grid;gap:8px}
            .file-row{border:1px solid #eaecf0;border-radius:8px;background:#fff;padding:10px;text-align:left;width:100%;cursor:pointer}
            .file-row.active{border-color:#38bdf8;background:#eff8ff}
            .file-name{font-weight:800;color:#182230;overflow-wrap:anywhere}
            .file-meta{font-size:12px;color:#667085;margin-top:4px}
            .review-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;border-bottom:1px solid #eaecf0;padding-bottom:10px}
            .review-tab{border:1px solid #d0d5dd;background:#fff;border-radius:999px;padding:7px 12px;font-weight:800;color:#344054;cursor:pointer}
            .review-tab.active{background:#182230;color:#fff;border-color:#182230}
            .issue-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
            .issue-card{border:1px solid #eaecf0;border-radius:8px;padding:12px;background:#fcfcfd}
            .issue-card.ready{border-color:#abefc6;background:#f6fef9}
            .issue-card.review{border-color:#fedf89;background:#fffcf5}
            .issue-card.blocked{border-color:#fecdca;background:#fffbfa}
            .issue-title{font-weight:850;color:#182230;margin-bottom:5px}
            .issue-detail{font-size:13px;color:#475467;line-height:1.45;overflow-wrap:anywhere}
            .evidence-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
            .evidence-item{border:1px solid #eaecf0;border-radius:8px;padding:10px;background:#fcfcfd}
            .download-list{display:grid;gap:8px}
            .download-row{display:flex;justify-content:space-between;gap:10px;align-items:center;border:1px solid #eaecf0;border-radius:8px;padding:9px;background:#fff}
            .copilot-answer{white-space:pre-wrap;background:#0b1220;color:#edf3ff;border-radius:8px;padding:12px;font-size:13px;line-height:1.45;max-height:280px;overflow:auto}
            .review-action-bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
            .action-note{font-size:12px;color:#667085;line-height:1.35}
            .validation-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
            .patch-panel{border:1px solid #d0d5dd;border-radius:8px;background:#f8fafc;padding:12px;display:grid;gap:8px}
            @media (max-width:1200px){.review-workspace{grid-template-columns:1fr}.conversion-kpis,.evidence-strip,.issue-grid{grid-template-columns:1fr}.conversion-review-head{display:block}.conversion-review-head .flex{margin-top:12px}}
          `}</style>
          <div className="conversion-review-shell">
            {!selectedRun ? (
              <>
                <div className="soft-grid">
                  <FileUploadDropzone onUploaded={refresh} accept=".sql,.ddl,.zip,.json" title="Upload SQL and dbt artifacts" message="Supported: SQL models, DDL, source mappings, data contracts, and dbt project zips." />
                  <SectionCard title="Create conversion job" subtitle="Conversion is offline. UMA does not connect to Snowflake or execute uploaded SQL.">
                    <Field label="Run name"><input className="fi" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
                    <div className="fr">
                      <Field label="Source dialect"><select className="fi" value={form.source_dialect} onChange={(event) => setForm({ ...form, source_dialect: event.target.value })}>{DIALECTS.map((dialect) => <option key={dialect}>{dialect}</option>)}</select></Field>
                      <Field label="Target platform"><select className="fi" value={form.target_type} onChange={(event) => setForm({ ...form, target_type: event.target.value })}><option>snowflake</option></select></Field>
                    </div>
                    <Field label="Safety mode"><select className="fi" value={form.safety_mode} onChange={(event) => setForm({ ...form, safety_mode: event.target.value })}>{SAFETY_MODES.map((mode) => <option key={mode}>{mode}</option>)}</select></Field>
                  </SectionCard>
                </div>
                <ArtifactSelector
                  artifacts={visibleArtifacts || []}
                  selected={selectedArtifacts}
                  setSelected={setSelectedArtifacts}
                  allowedTypes={["sql", "ddl", "zip", "json", "SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT"]}
                  selectedRunId={selectedRun?.id || ""}
                  emptyAction={(
                    <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                      <button className="btn btn-primary btn-sm" type="button" onClick={() => document.querySelector('input[type="file"]')?.click()}>Upload SQL/dbt project</button>
                      <button className="btn btn-ghost btn-sm" type="button" disabled>Select persisted artifact</button>
                    </div>
                  )}
                />
                <SectionCard title="Conversion jobs" subtitle="Open a job to review conversion quality, judge status, files, downloads, and Copilot guidance.">
                  <DataTable
                    rows={runs || []}
                    onRowClick={openRun}
                    emptyTitle="No conversion jobs yet"
                    emptyMessage="Upload or select source artifacts, then analyze a conversion."
                    columns={[
                      { key: "name", label: "Job", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                      { key: "source_dialect", label: "Source" },
                      { key: "target_dialect", label: "Target" },
                      { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                      { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                    ]}
                  />
                </SectionCard>
              </>
            ) : (
              <>
                <div className="conversion-review-head">
                  <div>
                    <div className="stat-label">Conversion Review Workspace</div>
                    <div className="conversion-review-title">{selectedRun.name}</div>
                    <div className="conversion-meta">
                      <span className="conversion-chip">Run ID: {selectedRun.id}</span>
                      <span className="conversion-chip">Source: {jobState.source_dialect || selectedRun.source_dialect || "auto_detect"}</span>
                      <span className="conversion-chip">Target: {jobState.target_dialect || selectedRun.target_dialect || "snowflake"}</span>
                      <span className="conversion-chip">Input: {jobState.input_type || "dbt_project"}</span>
                      <span className="conversion-chip">AI: {aiMode.mode}</span>
                    </div>
                  </div>
                  <div className="flex gap2" style={{ alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <StatusBadge status={productStatus} />
                    <span className="conversion-chip">Snowflake Ready: {jobState.snowflake_ready ? "Yes" : "No"}</span>
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={runBrain}>{busy ? "Running" : "Run UMA Brain"}</button>
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={generate}>{busy ? "Running" : "Convert"}</button>
                    <button className="btn btn-ghost btn-sm" disabled={!canProposeAiPatch || patchBusy} onClick={proposeAiPatch}>{patchBusy ? "Proposing" : "Propose AI Patch"}</button>
                    <button className="btn btn-ghost btn-sm" disabled={!canValidateSnowflake || validationBusy} onClick={validateInSnowflake}>{validationBusy ? "Validating" : "Run Snowflake Validation"}</button>
                    {canDownloadPackage ? <button className="btn btn-primary btn-sm" onClick={() => api.downloadConversionJob(selectedRun.id)}>Download Snowflake package</button> : null}
                  </div>
                </div>

                <SectionCard title="Run-linked dbt gates" subtitle="Model inventory, review, compile, validation, and package readiness are evaluated against the selected Migration Run.">
                  <SummaryList items={[
                    { label: "Canonical run", value: selectedRun.id },
                    { label: "Model inventory", value: `${reviewFiles.length || jobState.total_files || 0} model/file item${(reviewFiles.length || jobState.total_files || 0) === 1 ? "" : "s"}` },
                    { label: "Brain decisions", value: runDetail?.brain_review_decisions?.length ?? 0 },
                    { label: "Compile status", value: runDetail?.gates?.dbt_compile || validationResult?.validation_status || jobState.validation_status || "not_run" },
                    { label: "Snowflake validation", value: runDetail?.gates?.snowflake_validation || "blocked" },
                    { label: "Package gate", value: runDetail?.gates?.snowflake_ready_package || (canDownloadPackage ? "available" : "blocked") },
                    { label: "Package reason", value: runDetail?.package?.blocked_reason || readyReason },
                  ]} />
                </SectionCard>

                <div className="conversion-kpis">
                  <StatCard label="Files analyzed" value={jobState.total_files ?? reviewFiles.length ?? 0} />
                  <StatCard label="Files converted" value={jobState.converted_files_count ?? 0} />
                  <StatCard label="Files failed" value={jobState.failed_files_count ?? 0} />
                  <StatCard label="Requires review" value={jobState.requires_review_count ?? 0} />
                  <StatCard label="Rules applied" value={jobState.rules_applied_count ?? 0} />
                  <StatCard label="Judge status" value={jobState.judge_status ? <StatusBadge status={jobState.judge_status} /> : "Not run"} />
                </div>

                <div className="review-workspace">
                  <div className="workspace-panel">
                    <div className="workspace-panel-head">
                      <div className="workspace-panel-title">Files</div>
                      <div className="workspace-panel-subtitle">One row per input model. Status comes from the backend judge state.</div>
                    </div>
                    <div className="workspace-panel-body">
                      <div className="file-list">
                        {reviewFiles.length ? reviewFiles.map((file, index) => (
                          <button key={`${file.source_path || index}`} className={`file-row ${index === selectedFileIndex ? "active" : ""}`} onClick={() => { setSelectedFileIndex(index); setFileReviewTab("summary"); }}>
                            <div className="file-name">{fileDisplayName(file)}</div>
                            <div className="file-meta">{fileReviewStatus(file)} · {file.rules_applied?.length || 0} rules · residue {(file.source_residue || []).length ? (file.source_residue || []).join(", ") : "none"}</div>
                          </button>
                        )) : <EmptyState title="No file report yet" message="Run conversion or UMA Brain to populate model-level review." compact />}
                      </div>
                    </div>
                  </div>

                  <div className="workspace-panel">
                    <div className="workspace-panel-head">
                      <div className="workspace-panel-title">{fileDisplayName(selectedFile) || "Selected file review"}</div>
                      <div className="workspace-panel-subtitle">{readyReason}</div>
                    </div>
                    <div className="workspace-panel-body">
                      <div className="review-tabs">
                        {[
                          ["summary", "Summary"],
                          ["diff", "SQL Diff"],
                          ["converted", "Converted SQL"],
                          ["issues", "Issues"],
                          ["reports", "Reports"],
                        ].map(([id, label]) => <button key={id} className={`review-tab ${fileReviewTab === id ? "active" : ""}`} onClick={() => setFileReviewTab(id)}>{label}</button>)}
                      </div>

                      {fileReviewTab === "summary" ? (
                        <div className="conversion-review-shell">
                          <div className="evidence-strip">
                            <div className="evidence-item"><div className="stat-label">Rewrite count</div><div className="stat-value">{selectedFile.rules_applied?.length || 0}</div></div>
                            <div className="evidence-item"><div className="stat-label">Changed lines</div><div className="stat-value">{selectedFile.diff_summary?.changed_lines ?? jobState.diff_summary?.changed_lines ?? 0}</div></div>
                            <div className="evidence-item"><div className="stat-label">BigQuery residue</div><div className="stat-value">{(selectedFile.source_residue || []).length ? selectedFile.source_residue.join(", ") : "None"}</div></div>
                            <div className="evidence-item"><div className="stat-label">Readiness</div><div className="stat-value">{selectedFile.snowflake_ready ? "Ready" : "Not ready"}</div></div>
                          </div>
                          <div className="issue-grid">
                            {issueCards.slice(0, 4).map((card) => <div className={`issue-card ${card.tone}`} key={`${card.title}-${card.detail}`}><div className="issue-title">{card.title}</div><div className="issue-detail">{card.detail}</div></div>)}
                          </div>
                          <div className="issue-card review">
                            <div className="issue-title">Conversion evidence</div>
                            <div className="issue-detail">{selectedFile.rules_applied?.length || jobState.rules_applied_count || 0} rewrite rules applied. BigQuery residue {(selectedFile.source_residue || jobState.source_residue || []).length ? "remains" : "removed"}. Snowflake-ready package blocked because {readyReason.charAt(0).toLowerCase() + readyReason.slice(1)}</div>
                          </div>
                        </div>
                      ) : null}

                      {fileReviewTab === "diff" ? <pre className="pq-code-block">{selectedFile.diff || selectedFile.diff_summary?.diff || "No SQL diff available for this file yet."}</pre> : null}
                      {fileReviewTab === "converted" ? <pre className="pq-code-block">{selectedFile.converted_sql || preview?.text || "No converted SQL preview is available yet."}</pre> : null}
                      {fileReviewTab === "issues" ? <div className="issue-grid">{issueCards.map((card) => <div className={`issue-card ${card.tone}`} key={`${card.title}-${card.detail}`}><div className="issue-title">{card.title}</div><div className="issue-detail">{card.detail}</div></div>)}</div> : null}
                      {fileReviewTab === "reports" ? (
                        <div className="conversion-review-shell">
                          <DataTable
                            rows={(report?.file_reports || []).map((row, index) => ({ id: `${index}`, path: row.target_path, status: row.conversion_status, judge_status: row.judge_status, snowflake_ready: row.snowflake_ready }))}
                            emptyTitle="No report rows"
                            emptyMessage="Conversion report rows appear after conversion."
                            columns={[
                              { key: "path", label: "Output path", render: (row) => <span className="td-mono">{row.path}</span> },
                              { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                              { key: "judge_status", label: "Judge", render: (row) => <StatusBadge status={row.judge_status || "not_run"} /> },
                              { key: "snowflake_ready", label: "Ready", render: (row) => <StatusBadge status={Boolean(row.snowflake_ready)} /> },
                            ]}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="workspace-panel">
                    <div className="workspace-panel-head">
                      <div className="workspace-panel-title">Copilot</div>
                      <div className="workspace-panel-subtitle">Grounded in this job's SQL, diff, rules, judge result, residue, warnings, and dbt metadata.</div>
                    </div>
                    <div className="workspace-panel-body">
                      <div className="copilot-suggestion-grid">
                        {["Why is this still Requires Review?", "Why is this not Snowflake-ready?", "What did UMA convert?", "Show remaining risks", "Suggest dbt config improvements", "Explain the SQL diff", "Create a patch suggestion"].map((question) => (
                          <button key={question} className="copilot-suggestion-card" disabled={copilotBusy} onClick={() => askConversionCopilot(question)}>{question}</button>
                        ))}
                      </div>
                      <Field label="Question"><textarea className="fi" rows={4} value={copilotQuestion} onChange={(event) => setCopilotQuestion(event.target.value)} /></Field>
                      <button className="btn btn-primary" disabled={copilotBusy || !copilotQuestion.trim()} onClick={() => askConversionCopilot()}>{copilotBusy ? "Asking" : "Ask Copilot"}</button>
                      {copilotAnswer ? <div className="copilot-answer mt3">{copilotAnswer.answer}</div> : null}

                      <div className="divider" />
                      <div className="stat-label">AI Mode</div>
                      <ul className="review-list">
                        <li>{aiMode.mode}</li>
                        <li>{aiMode.rag}</li>
                        <li>{aiMode.review}</li>
                        <li>Provider: {aiMode.provider}</li>
                        <li>Model: {aiMode.model}</li>
                        <li>{aiMode.patch}</li>
                      </ul>
                      <div className="review-action-bar mt2">
                        <button className="btn btn-primary btn-sm" disabled={!canProposeAiPatch || patchBusy} onClick={proposeAiPatch}>{patchBusy ? "Proposing" : "Propose AI Patch"}</button>
                        {!canProposeAiPatch ? <span className="action-note">Disabled because no LLM provider is configured.</span> : <span className="action-note">Proposal only. UMA will not auto-apply AI patches.</span>}
                      </div>
                      {aiPatch ? (
                        <div className="patch-panel mt2">
                          <div className="issue-title">{aiPatch.status === "AI_UNAVAILABLE" ? "AI patch unavailable" : "AI patch proposal"}</div>
                          <div className="issue-detail">{aiPatch.proposal?.explanation || aiPatch.proposal?.risks?.join(", ") || "Patch proposal captured for review."}</div>
                          <pre className="pq-code-block" style={{ maxHeight: 180 }}>{aiPatch.proposal?.structured_diff || aiPatch.structured_diff || "No patch diff generated."}</pre>
                          {aiPatch.status === "PROPOSED" ? <button className="btn btn-ghost btn-sm" disabled={patchBusy} onClick={applyReviewedPatch}>{patchBusy ? "Applying" : "Approve patch and rerun judge"}</button> : null}
                          {aiPatch.status === "PROPOSED" ? <div className="action-note">Approval stores a patch artifact, reruns the deterministic judge, marks validation stale, and creates Brain Review follow-up when risk remains.</div> : null}
                        </div>
                      ) : null}

                      <div className="divider" />
                      <div className="stat-label">Snowflake Validation</div>
                      <div className="validation-grid mt2">
                        {["account", "user", "password", "role", "warehouse", "database", "schema"].map((field) => (
                          <input key={field} className="fi" type={field === "password" ? "password" : "text"} placeholder={formatLabel(field)} value={snowflakeValidation[field]} onChange={(event) => setSnowflakeValidation({ ...snowflakeValidation, [field]: event.target.value })} />
                        ))}
                      </div>
                      <div className="review-action-bar mt2">
                        <button className="btn btn-primary btn-sm" disabled={!canValidateSnowflake || validationBusy} onClick={validateInSnowflake}>{validationBusy ? "Validating" : "Run Snowflake Validation"}</button>
                        {!canValidateSnowflake ? <span className="action-note">Disabled until account, user, password or authenticator, role, warehouse, database, and schema are provided.</span> : <span className="action-note">Runs connection, permission, dbt compile, and safe EXPLAIN checks. It does not run models.</span>}
                      </div>
                      {validationResult ? (
                        <div className="patch-panel mt2">
                          <div className="issue-title">Validation: {formatLabel(validationResult.validation_status || validationResult.status)}</div>
                          <div className="issue-detail">{validationResult.message}</div>
                          {(validationResult.connection_readiness || []).length ? <div className="issue-detail">Connection checks: {(validationResult.connection_readiness || []).map((row) => `${formatLabel(row.check)} ${row.status}`).join(", ")}</div> : null}
                          {(validationResult.syntax_results || []).length ? <div className="issue-detail">EXPLAIN results: {(validationResult.syntax_results || []).map((row) => `${row.model}: ${row.status}`).join(", ")}</div> : null}
                          {(validationResult.compile_errors || []).length ? <div className="issue-detail">Compile errors: {validationResult.compile_errors.join(", ")}</div> : null}
                        </div>
                      ) : null}

                      <div className="divider" />
                      <div className="stat-label">Downloads</div>
                      <div className="download-list mt2">
                        <div className="text-muted">Review Artifacts</div>
                        {groupedDownloads.review.length ? groupedDownloads.review.map((artifact) => (
                          <div className="download-row" key={artifact.id}>
                            <span className="td-mono">{artifact.original_filename}</span>
                            <button className="btn btn-ghost btn-sm" onClick={() => api.downloadControlPlaneArtifact(artifact.id, artifact.original_filename)}>Download</button>
                          </div>
                        )) : <div className="text-muted">No review artifacts generated yet.</div>}
                        <div className="text-muted mt2">Snowflake-Ready Artifacts</div>
                        {groupedDownloads.snowflake.length ? groupedDownloads.snowflake.map((artifact) => (
                          <div className="download-row" key={artifact.id}>
                            <span className="td-mono">{artifact.original_filename}</span>
                            <button className="btn btn-primary btn-sm" onClick={() => api.downloadControlPlaneArtifact(artifact.id, artifact.original_filename)}>Download</button>
                          </div>
                        )) : <DisabledReason>Snowflake-ready package blocked until readiness gates pass. Reason: {readyReason}</DisabledReason>}
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
          <details className="mt4">
            <summary className="settings-title">Advanced Diagnostics</summary>
            <SectionCard title="Agent and job diagnostics" subtitle="Internal run logs and graph evidence are collapsed by default.">
                <DataTable
                  rows={(jobLogs || []).map((job) => ({
                    ...job,
                    log_text: job.logs_redacted || job.error_message || JSON.stringify(job.output_json || {}, null, 2),
                  }))}
                  emptyTitle="No diagnostics captured yet"
                  emptyMessage="Analyze conversion or run UMA Brain to persist diagnostic logs."
                  columns={[
                    { key: "module", label: "Module" },
                    { key: "phase", label: "Phase" },
                    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                    { key: "started_at", label: "Started", render: (row) => fmtDate(row.started_at || row.created_at) },
                    { key: "log_text", label: "Log", render: (row) => <pre className="pq-code-block" style={{ maxHeight: 160 }}>{row.log_text}</pre> },
                  ]}
                />
            </SectionCard>
          </details>
        </>
      ) : tab === "brain" ? (
        <div style={{ marginTop: 18 }}>
          {!selectedRun ? (
            <SectionCard title="Select a dbt conversion run" subtitle="UMA Brain review is generated from a specific conversion job, so pick a run here to inspect judge results, deterministic rewrites, RAG context, and specialist findings.">
              <DataTable
                rows={runs || []}
                onRowClick={openRun}
                emptyTitle="No conversion runs yet"
                emptyMessage="Create or upload a dbt conversion run first, then return here for the UMA Brain review."
                columns={[
                  { key: "name", label: "Run name", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                  { key: "source_dialect", label: "Source dialect" },
                  { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                  { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                ]}
              />
            </SectionCard>
          ) : !brainFiles.length ? (
            <SectionCard
              title="UMA Brain Review"
              subtitle="Run-level review output appears here after UMA Brain inspects the selected conversion."
              actions={<button className="btn btn-primary" disabled={busy} onClick={runBrain}>{busy ? "Running" : "Run UMA brain"}</button>}
            >
              <EmptyState title="Brain review not generated yet" message="Run UMA brain after analysis to populate source tables, target model, rules applied, RAG, and agent findings." compact />
            </SectionCard>
          ) : (
            <div className="uma-brain-transcript">
              <style>{`
                .uma-brain-transcript{display:grid;gap:16px;max-width:1400px;margin:0 auto 32px}
                .uma-brain-transcript .review-hero{background:#182230;color:#fff;border-radius:8px;padding:18px 22px;display:flex;gap:16px;align-items:flex-start;justify-content:space-between;box-shadow:0 8px 24px rgba(16,24,40,.12)}
                .uma-brain-transcript .review-hero h2{margin:0 0 6px;font-size:24px;letter-spacing:0}
                .uma-brain-transcript .review-hero p{margin:0;color:#d0d5dd;line-height:1.45;max-width:900px}
                .uma-brain-transcript .review-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
                .uma-brain-transcript .review-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
                .uma-brain-transcript .review-tile{background:#fff;border:1px solid #d0d5dd;border-radius:8px;padding:12px;min-width:0}
                .uma-brain-transcript .review-tile-label{font-size:12px;color:#667085;margin-bottom:6px}
                .uma-brain-transcript .review-tile-value{font-size:16px;font-weight:800;color:#182230;overflow-wrap:anywhere;line-height:1.25}
                .uma-brain-transcript .review-section{background:#fff;border:1px solid #d0d5dd;border-radius:8px;padding:16px;min-width:0}
                .uma-brain-transcript .review-section h3{margin:0 0 10px;font-size:17px;color:#182230}
                .uma-brain-transcript .review-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
                .uma-brain-transcript .review-list{margin:0;padding-left:18px;color:#344054}
                .uma-brain-transcript .review-list li{margin:7px 0;line-height:1.45}
                .uma-brain-transcript .file-review{border:1px solid #eaecf0;border-radius:8px;padding:14px;margin-top:12px;background:#fcfcfd}
                .uma-brain-transcript .file-review-head{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
                .uma-brain-transcript .file-review-title{font-weight:850;color:#182230;overflow-wrap:anywhere}
                .uma-brain-transcript .status-pill{display:inline-flex;align-items:center;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:800;border:1px solid #d0d5dd;background:#f9fafb;color:#344054;white-space:nowrap}
                .uma-brain-transcript .status-blocked{background:#fef3f2;color:#b42318;border-color:#fecdca}
                .uma-brain-transcript .status-review{background:#fffaeb;color:#b54708;border-color:#fedf89}
                .uma-brain-transcript .status-ready{background:#eff8ff;color:#175cd3;border-color:#b2ddff}
                .uma-brain-transcript .status-validated{background:#ecfdf3;color:#027a48;border-color:#abefc6}
                .uma-brain-transcript .kv-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:10px}
                .uma-brain-transcript .kv{background:#fff;border:1px solid #eaecf0;border-radius:6px;padding:9px;min-width:0}
                .uma-brain-transcript .kv-label{font-size:11px;color:#667085;margin-bottom:4px}
                .uma-brain-transcript .kv-value{font-size:13px;color:#182230;line-height:1.35;overflow-wrap:anywhere}
                .uma-brain-transcript .callout{border-left:4px solid #f79009;background:#fff8ed;padding:11px 13px;border-radius:6px;color:#53380c;line-height:1.45}
                .uma-brain-transcript details{background:#fff;border:1px solid #d0d5dd;border-radius:8px;padding:14px}
                .uma-brain-transcript summary{cursor:pointer;font-weight:850;color:#182230}
                .uma-brain-transcript .raw-json-title{margin:14px 0 8px;font-size:15px;color:#182230}
                .uma-brain-transcript .raw-json{margin:10px 0 0;white-space:pre-wrap;overflow:auto;max-height:420px;font-size:12px;line-height:1.45;background:#0b1220;color:#edf3ff;border-radius:8px;padding:14px}
                @media (max-width:1100px){.uma-brain-transcript .review-grid,.uma-brain-transcript .review-columns,.uma-brain-transcript .kv-grid{grid-template-columns:1fr}.uma-brain-transcript .review-hero{display:block}.uma-brain-transcript .review-actions{justify-content:flex-start;margin-top:12px}}
              `}</style>
              <div className="review-hero">
                <div>
                  <h2>UMA Brain Review Transcript</h2>
                  <p>Human-readable review generated from the run payload. This explains what UMA did, what UMA did not do, what is blocked or review-required, and the next validation steps before migration approval.</p>
                </div>
                <div className="review-actions">
                  <CopyButton value={brainTranscript.markdown} />
                  <button className="btn btn-ghost btn-sm" onClick={() => downloadClientText(`uma-brain-review-${selectedRun?.id || "run"}.md`, brainTranscript.markdown)}>Download markdown report</button>
                </div>
              </div>

              <div className="review-grid ux-transcript-section">
                {brainTranscript.summary.map((item) => (
                  <div className="review-tile" key={item.label}>
                    <div className="review-tile-label">{item.label}</div>
                    <div className="review-tile-value">{item.label === "Overall status" ? <span className={`status-pill ${item.value === "Blocked" ? "status-blocked" : item.value === "Requires Review" ? "status-review" : item.value === "Validated" ? "status-validated" : "status-ready"}`}>{item.value}</span> : item.value}</div>
                  </div>
                ))}
              </div>

              <div className="review-columns ux-transcript-section">
                <div className="review-section">
                  <h3>What UMA Did</h3>
                  <ul className="review-list">{brainTranscript.whatDid.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
                <div className="review-section">
                  <h3>What UMA Did Not Do</h3>
                  <ul className="review-list">{(brainTranscript.whatDidNot.length ? brainTranscript.whatDidNot : ["Nothing material was omitted according to this payload."]).map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              </div>

              <div className="review-section ux-transcript-section">
                <h3>File-by-file Review</h3>
                {brainTranscript.fileReviews.map((row) => (
                  <div className="file-review" key={row.name}>
                    <div className="file-review-head">
                      <div className="file-review-title">{row.name}</div>
                      <span className={`status-pill ${row.status === "Blocked" ? "status-blocked" : row.status === "Requires Review" ? "status-review" : row.status === "Validated" ? "status-validated" : "status-ready"}`}>{row.status}</span>
                    </div>
                    <div className="kv-grid">
                      <div className="kv"><div className="kv-label">Dialect detected</div><div className="kv-value">{row.dialect}</div></div>
                      <div className="kv"><div className="kv-label">Dialect detection confidence</div><div className="kv-value">{row.confidence.dialect}</div></div>
                      <div className="kv"><div className="kv-label">Conversion confidence</div><div className="kv-value">{row.confidence.conversion}</div></div>
                      <div className="kv"><div className="kv-label">Converted SQL ready</div><div className="kv-value">{row.convertedReady}</div></div>
                      <div className="kv"><div className="kv-label">Validation confidence</div><div className="kv-value">{row.confidence.validation}</div></div>
                      <div className="kv"><div className="kv-label">Production readiness</div><div className="kv-value">{row.confidence.production}</div></div>
                    </div>
                    <div className="review-columns">
                      <div>
                        <div className="kv-label">Main findings</div>
                        <ul className="review-list">{row.findings.map((finding) => <li key={finding}>{finding}</li>)}</ul>
                      </div>
                      <div>
                        <div className="kv-label">Why it matters</div>
                        <div className="kv-value">{row.why || "No additional risk rationale was attached."}</div>
                        <div className="kv-label mt3">Recommended action</div>
                        <div className="kv-value">{row.action || "Review the converted SQL before approval."}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="review-columns ux-transcript-section">
                <div className="review-section">
                  <h3>Critical Blockers</h3>
                  {brainTranscript.blockers.length ? <ul className="review-list">{brainTranscript.blockers.map((item) => <li key={item}>{item}</li>)}</ul> : <div className="kv-value">No critical blockers were detected.</div>}
                </div>
                <div className="review-section">
                  <h3>Review Required</h3>
                  {brainTranscript.reviewItems.length ? <ul className="review-list">{brainTranscript.reviewItems.map((item) => <li key={item}>{item}</li>)}</ul> : <div className="kv-value">No review-required items were detected.</div>}
                </div>
              </div>

              <div className="review-columns ux-transcript-section">
                <div className="review-section">
                  <h3>Validation Status</h3>
                  <ul className="review-list">{brainTranscript.validationStatus.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
                <div className="review-section">
                  <h3>AI/LLM Status</h3>
                  <ul className="review-list">{brainTranscript.llmStatus.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              </div>

              <div className="review-section ux-transcript-section">
                <h3>Recommended Next Actions</h3>
                <ul className="review-list">{brainTranscript.nextActions.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>

              <details>
                <summary>Advanced Details</summary>
                <div className="raw-json-title">Raw JSON</div>
                <button className="btn btn-ghost btn-sm" onClick={() => downloadClientText(`uma-brain-diagnostic-${selectedRun?.id || "run"}.json`, JSON.stringify(report, null, 2), "application/json")}>Download diagnostic payload</button>
                <pre className="raw-json">{JSON.stringify(report, null, 2)}</pre>
              </details>
            </div>
          )}
        </div>
      ) : (
        <div style={{ marginTop: 18 }}>
          <div className="soft-grid">
            <FileUploadDropzone onUploaded={refreshProjects} accept=".zip" artifactCategory="DBT_PROJECT" title="Upload existing dbt project zip" message="Static parsing only. UMA does not run dbt commands unless separately configured." />
            <SectionCard title="Existing project inventory" subtitle="Analyze a persisted project zip to inspect lineage, tests coverage, snapshots, macros, and risky incremental logic.">
              <DataTable
                rows={projects || []}
                onRowClick={async (project) => setProjectReport(await api.getDbtProjectReport(project.id))}
                emptyTitle="No dbt project zips uploaded yet"
                emptyMessage="Upload a dbt project archive to start static project analysis."
                emptyAction={(
                  <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                    <button className="btn btn-primary btn-sm" type="button" onClick={() => document.querySelector('input[type="file"]')?.click()}>Upload SQL/dbt project</button>
                    <button className="btn btn-ghost btn-sm" type="button" disabled>Select persisted artifact</button>
                  </div>
                )}
                columns={[
                  { key: "original_filename", label: "Project zip", render: (row) => <span className="td-main">{row.original_filename}</span> },
                  { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                  { key: "actions", label: "Analyze", render: (row) => <button className="btn btn-primary btn-sm" onClick={async (event) => { event.stopPropagation(); setProjectReport(await api.analyzeDbtProject(row.id)); }}>Analyze</button> },
                ]}
              />
            </SectionCard>
          </div>
          <div className="soft-grid mt4">
            <SectionCard title="Model inventory and lineage" subtitle="Static parsing extracts models, refs, and sources without running dbt build.">
              <DataTable
                rows={projectReport?.models || []}
                emptyTitle="No model inventory yet"
                emptyMessage="Analyze an uploaded dbt project zip to populate model inventory."
                columns={[
                  { key: "name", label: "Model", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                  { key: "path", label: "Path" },
                  { key: "refs", label: "Refs", render: (row) => row.refs?.join(", ") || "None" },
                  { key: "sources", label: "Sources", render: (row) => row.sources?.join(", ") || "None" },
                ]}
              />
            </SectionCard>
            <SectionCard title="Coverage and recommendations" subtitle="Missing tests and risky incremental patterns are flagged for human review.">
              <SummaryList items={[
                { label: "Models", value: projectReport?.model_count ?? 0 },
                { label: "Snapshots", value: projectReport?.snapshot_count ?? 0 },
                { label: "Macros", value: projectReport?.macro_count ?? 0 },
                { label: "Missing tests", value: projectReport?.missing_tests?.length ?? 0 },
              ]} />
              <div className="divider" />
              <DataTable
                rows={(projectReport?.recommendations || []).map((message, index) => ({ id: `${index}`, message }))}
                emptyTitle="No recommendations yet"
                emptyMessage="Analyze a project zip to generate recommendations."
                columns={[{ key: "message", label: "Recommendation" }]}
              />
            </SectionCard>
          </div>
        </div>
      )}
    </PageTransition>
  );
}

export function AnalyzerControlPage() {
  const { data: artifacts, refresh } = useAsyncLoader(() => api.listControlPlaneArtifacts(), []);
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.listAnalyzerRuns(), []);
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [report, setReport] = useState(null);
  const [components, setComponents] = useState([]);
  const [dependencies, setDependencies] = useState([]);
  const [activeAnalyzerKpi, setActiveAnalyzerKpi] = useState("components");
  const [busy, setBusy] = useState(false);
  const [analyzerType, setAnalyzerType] = useState("GENERIC_XML");
  const visibleArtifacts = filterArtifactsForModule(
    artifacts,
    ["xml", "json", "twb", "twbx", "ETL_XML", "TABLEAU"],
    selectedRun?.id || "",
  );

  const openRun = async (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    const [nextReport, nextComponents, nextDependencies] = await Promise.all([
      api.getAnalyzerReport(run.id),
      api.getAnalyzerComponents(run.id),
      api.getAnalyzerDependencies(run.id),
    ]);
    setReport(nextReport);
    setComponents(nextComponents);
    setDependencies(nextDependencies);
  };

  const scan = async () => {
    setBusy(true);
    try {
      const run = await api.createAnalyzerRun({ name: "ETL / BI Analyzer Run", artifact_ids: selectedArtifacts, analyzer_type: analyzerType, safety_mode: "PLAN_ONLY" });
      await api.scanAnalyzerRun(run.id);
      await openRun(run);
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page pq-page">
      <PageHeader
        title="ETL / BI Analyzer"
        subtitle="Extract ETL and BI components, dependencies, and migration complexity from persisted XML, Tableau, JSON, and related artifacts."
        status={selectedRun?.status}
        primaryAction={<button className="btn btn-primary" disabled={!selectedArtifacts.length || busy} onClick={scan}>{busy ? "Scanning" : "Run scan"}</button>}
      />
      <div className="soft-grid">
        <FileUploadDropzone onUploaded={refresh} accept=".xml,.twb,.twbx,.json,.yaml,.yml" title="Upload ETL and BI artifacts" />
        <SectionCard title="Analyzer setup" subtitle="Static parsing only. Use this module to discover dependencies and complexity before conversion work.">
          <Field label="Analyzer type"><select className="fi" value={analyzerType} onChange={(event) => setAnalyzerType(event.target.value)}>{["GENERIC_XML", "TABLEAU_XML", "GENERIC_JSON", "SSIS", "INFORMATICA", "DATASTAGE"].map((value) => <option key={value}>{value}</option>)}</select></Field>
        </SectionCard>
      </div>
      <ArtifactSelector artifacts={visibleArtifacts || []} selected={selectedArtifacts} setSelected={setSelectedArtifacts} allowedTypes={["xml", "json", "twb", "twbx", "ETL_XML", "TABLEAU"]} selectedRunId={selectedRun?.id || ""} />
      <div className="stats-grid">
        {[
          ["components", "Components", components.length, "inventory"],
          ["dependencies", "Dependencies", dependencies.length, "edges"],
          ["complexity", "Complexity score", report?.complexity_score ?? "NA", "selected run"],
        ].map(([id, label, value, note]) => (
          <button key={id} type="button" className={`stat-card is-clickable ${activeAnalyzerKpi === id ? "active" : ""}`} onClick={() => setActiveAnalyzerKpi(id)}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{value}</div>
            <div className="stat-change">{note}</div>
          </button>
        ))}
      </div>
      <SectionCard title={activeAnalyzerKpi === "dependencies" ? "Dependency evidence" : activeAnalyzerKpi === "complexity" ? "Complexity evidence" : "Component evidence"} subtitle="KPI-backed analyzer output from the selected persisted run.">
        {activeAnalyzerKpi === "dependencies" ? (
          <DataTable rows={dependencies} emptyTitle="No dependency edges yet" emptyMessage="Open or run an analyzer scan to populate dependency evidence." columns={[
            { key: "source_name", label: "Source", render: (row) => <span className="td-main">{row.source_name || row.source || objectDisplayName(row)}</span> },
            { key: "target_name", label: "Target", render: (row) => row.target_name || row.target || "Unknown" },
            { key: "dependency_type", label: "Type" },
          ]} />
        ) : activeAnalyzerKpi === "complexity" ? (
          <SummaryList items={[
            { label: "Complexity score", value: report?.complexity_score ?? "Not scored" },
            { label: "Components", value: components.length },
            { label: "Dependencies", value: dependencies.length },
            { label: "Selected run", value: selectedRun?.name || "None" },
            { label: "Analyzer type", value: analyzerType },
          ]} />
        ) : (
          <DataTable rows={components} emptyTitle="No component inventory yet" emptyMessage="Open or run an analyzer scan to inspect extracted components." columns={[
            { key: "component_type", label: "Type" },
            { key: "name", label: "Name", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
            { key: "source_file", label: "Source file" },
          ]} />
        )}
      </SectionCard>
      <div className="soft-grid">
        <SectionCard title="Analyzer runs"><DataTable rows={runs || []} onRowClick={openRun} emptyTitle="No analyzer runs yet" emptyMessage="Upload ETL or BI artifacts and run a scan." columns={[
          { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
          { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
          { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
        ]} /></SectionCard>
        <SectionCard title="Component inventory"><DataTable rows={components} emptyTitle="No component inventory yet" emptyMessage="Open an analyzer run to inspect extracted components." columns={[
          { key: "component_type", label: "Type" },
          { key: "name", label: "Name", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
          { key: "source_file", label: "Source file" },
        ]} /></SectionCard>
      </div>
    </div>
  );
}

export function ValidationControlPage() {
  const { data: connections } = useAsyncLoader(() => api.getConnections().catch(() => []), []);
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.listValidationControlRuns(), []);
  const [selectedRun, setSelectedRun] = useState(null);
  const [report, setReport] = useState(null);
  const [tab, setTab] = useState("plan");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "Validation Plan",
    source_connection_id: "",
    target_connection_id: "",
    tables: "",
    ignored_columns: "",
    validation_type: "row count",
    max_differences: 0,
    safety_mode: "VALIDATION_ONLY",
  });

  const plan = async () => {
    setBusy(true);
    try {
      const run = await api.createValidationControlRun({
        name: form.name,
        safety_mode: form.safety_mode,
        source_connection_id: form.source_connection_id || null,
        target_connection_id: form.target_connection_id || null,
        tables: form.tables.split(/\s+/).filter(Boolean),
        ignored_columns: form.ignored_columns.split(/\s+/).filter(Boolean),
        max_differences: Number(form.max_differences) || 0,
        config: { validation_type: form.validation_type },
      });
      const nextReport = await api.planValidationControlRun(run.id);
      setSelectedRun(run);
      setSelectedMigrationRun(run.id);
      setReport(nextReport);
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  const openRun = async (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    setReport(await api.getValidationControlReport(run.id));
  };

  const validationRows = validationResultRows(report);
  const validationChecks = buildValidationChecks(report);
  const generatedSql = sqlPreviewFromStatements((report?.tables || []).flatMap((table) => Object.values(table.queries || {})));
  const validationContextItems = [
    { label: "Latest run", value: selectedRun?.name || runs?.[0]?.name || "No validation run selected" },
    { label: "Run status", value: selectedRun ? <StatusBadge status={selectedRun.status} /> : "No validation run selected" },
    { label: "Safety mode", value: selectedRun?.safety_mode || form.safety_mode },
    { label: "Planned tables", value: report?.tables?.length ?? 0 },
    { label: "Validation type", value: form.validation_type },
    { label: "Execution state", value: report?.executed ? "Read-only validation executed" : "Plan only" },
    { label: "Report status", value: report ? "Generated" : "Not generated" },
    { label: "Recommended next action", value: report ? "Review SQL and result tolerances" : "Create a validation plan" },
  ];

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="Validation Plans"
        subtitle="Plan source-versus-target row, schema, and reconciliation checks. Planning is offline; execution requires explicit VALIDATION_ONLY approval."
        status={selectedRun?.status}
        primaryAction={<button className="btn btn-primary" onClick={plan} disabled={busy}>{busy ? "Planning" : "Plan validation"}</button>}
      />
      <OperationsAlertStrip
        items={validationChecks.filter((check) => ["failed", "blocked", "warning"].includes(check.status)).map((check, index) => ({
          id: `${check.label}-${index}`,
          title: check.label,
          status: check.status,
          action: check.status === "failed" || check.status === "blocked" ? "Send to Brain Review" : "Review evidence",
        }))}
        fallback={selectedRun ? "No validation failures are open for this plan." : "Create or select a validation plan to populate checks."}
      />
      <EnterpriseKpiRow items={[
        { label: "Plans", value: runs?.length || 0, note: "persisted plans", active: tab === "runs", onClick: () => setTab("runs") },
        { label: "Tables", value: report?.tables?.length ?? 0, note: "planned checks", active: tab === "plan", onClick: () => setTab("plan") },
        { label: "Results", value: validationRows.length, note: "rows returned", active: tab === "results", onClick: () => setTab("results") },
        { label: "Generated SQL", value: generatedSql?.text ? "Ready" : "None", note: "previewable", active: tab === "generated_sql", onClick: () => setTab("generated_sql") },
        { label: "Execution", value: report?.executed ? "Run" : "Plan", note: "validation mode", active: tab === "results", onClick: () => setTab("results") },
        { label: "Status", value: selectedRun ? <StatusBadge status={selectedRun.status} /> : "None", note: "selected plan", active: tab === "report", onClick: () => setTab("report") },
      ]} />
      <div className="ep-workspace" style={{ gridTemplateColumns: "minmax(0,1fr) 340px" }}>
        <div>
          <WorkspaceTabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "plan", label: "Plan" },
              { id: "generated_sql", label: "Generated SQL" },
              { id: "results", label: "Results" },
              { id: "runs", label: "Runs" },
              { id: "report", label: "Report" },
            ]}
          />
          <div className="mt4">
            {tab === "plan" ? (
              <SectionCard title="Validation plan inputs" subtitle="Choose connections, tables, and checks before generating SQL and report artifacts.">
                <div className="fr">
                  <Field label="Source connection"><select className="fi" value={form.source_connection_id} onChange={(event) => setForm({ ...form, source_connection_id: event.target.value })}><option value="">Select source</option>{(connections || []).map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}</select></Field>
                  <Field label="Target connection"><select className="fi" value={form.target_connection_id} onChange={(event) => setForm({ ...form, target_connection_id: event.target.value })}><option value="">Select target</option>{(connections || []).map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}</select></Field>
                </div>
                <Field label="Table list"><textarea className="fi" rows={5} value={form.tables} onChange={(event) => setForm({ ...form, tables: event.target.value })} /></Field>
                <Field label="Ignored columns"><input className="fi" value={form.ignored_columns} onChange={(event) => setForm({ ...form, ignored_columns: event.target.value })} /></Field>
                <div className="fr">
                  <Field label="Validation type"><select className="fi" value={form.validation_type} onChange={(event) => setForm({ ...form, validation_type: event.target.value })}>{VALIDATION_TYPES.map((value) => <option key={value}>{value}</option>)}</select></Field>
                  <Field label="Max differences"><input className="fi" type="number" value={form.max_differences} onChange={(event) => setForm({ ...form, max_differences: event.target.value })} /></Field>
                </div>
                <DisabledReason>No SQL executes while planning. Read-only execution requires configured source and target connections plus VALIDATION_ONLY or stronger safety mode.</DisabledReason>
              </SectionCard>
            ) : null}
            {tab === "generated_sql" ? (
              <CodeViewer title="Generated SQL preview" preview={generatedSql} artifact={null} />
            ) : null}
            {tab === "results" ? (
              <SectionCard title="Validation results" subtitle="Review differences and recommendations before deciding whether to execute read-only validation.">
                <DataTable
                  rows={validationRows}
                  emptyTitle="No validation results yet"
                  emptyMessage="Create a validation plan to preview comparisons. Execution remains blocked until explicitly approved."
                  columns={[
                    { key: "table", label: "Table", render: (row) => <span className="td-main">{row.table}</span> },
                    { key: "check_type", label: "Check type", render: (row) => row.check_type || row.validation_type || "row_count" },
                    { key: "source_value", label: "Source value", render: (row) => row.source_value ?? row.row_count_source ?? "Not executed" },
                    { key: "target_value", label: "Target value", render: (row) => row.target_value ?? row.row_count_target ?? "Not executed" },
                    { key: "status", label: "Status", render: (row) => <StatusBadge status={String(row.status || "NOT_EXECUTED").toUpperCase()} /> },
                    { key: "difference", label: "Difference", render: (row) => row.difference ?? row.diff_count ?? 0 },
                    { key: "recommendation", label: "Recommendation" },
                  ]}
                />
              </SectionCard>
            ) : null}
            {tab === "runs" ? (
              <SectionCard title="Persisted validation runs" subtitle="Review prior validation plans and their report artifacts.">
                <DataTable rows={runs || []} onRowClick={openRun} emptyTitle="No validation runs yet" emptyMessage="Plan validation to persist your first validation report." columns={[
                  { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                  { key: "safety_mode", label: "Safety mode" },
                  { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                  { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                ]} />
              </SectionCard>
            ) : null}
            {tab === "report" ? (
              <ReportPreview report={report} emptyMessage="No report generated yet. Create a validation plan to render the Validation Report." />
            ) : null}
          </div>
        </div>
        <div>
          <ContextRail title="Validation context" items={validationContextItems} />
          <SectionCard title="Execution guard" subtitle="Validation stays plan-first by default.">
            <div className="alert-info">Generated SQL is marked as not executed until you explicitly run validation in VALIDATION_ONLY mode with configured connections.</div>
          </SectionCard>
        </div>
      </div>
    </PageTransition>
  );
}

export function ProvisionControlPage() {
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.listProvisionRuns(), []);
  const [selectedRun, setSelectedRun] = useState(null);
  const [plan, setPlan] = useState(null);
  const [tab, setTab] = useState("architecture");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "Landing Zone Plan",
    safety_mode: "PLAN_ONLY",
    project_name: "UMA",
    environment: "prod",
    target_database: "UMA_MIGRATION_DB",
    raw_schema: "RAW",
    staging_schema: "STAGING",
    intermediate_schema: "INTERMEDIATE",
    marts_schema: "MARTS",
    audit_schema: "AUDIT",
    migration_warehouse: "MIGRATION_WH",
    validation_warehouse: "VALIDATION_WH",
    transformation_warehouse: "TRANSFORMATION_WH",
    admin_role: "UMA_ADMIN",
    engineer_role: "UMA_ENGINEER",
    analyst_role: "UMA_ANALYST",
    read_only_role: "UMA_READ_ONLY",
    resource_monitor: "",
  });

  const createPlan = async (connected) => {
    setBusy(true);
    try {
      const run = await api.createProvisionRun({
        name: form.name,
        safety_mode: form.safety_mode,
        config: form,
      });
      const nextPlan = connected ? await api.planProvisionConnected(run.id) : await api.planProvisionLocal(run.id);
      setSelectedRun(run);
      setSelectedMigrationRun(run.id);
      setPlan(nextPlan);
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  const openRun = async (run) => {
    setSelectedRun(run);
    setSelectedMigrationRun(run.id);
    setPlan(await api.getProvisionPlan(run.id));
  };

  const sqlPlanPreview = sqlPreviewFromStatements(plan?.statements || []);
  const provisionContextItems = [
    { label: "Latest run", value: selectedRun?.name || runs?.[0]?.name || "No plan selected" },
    { label: "Run status", value: selectedRun ? <StatusBadge status={selectedRun.status} /> : "No plan selected" },
    { label: "Safety mode", value: selectedRun?.safety_mode || form.safety_mode },
    { label: "Plan mode", value: plan?.mode ? formatLabel(plan.mode) : "Plan only" },
    { label: "Statements", value: plan?.statement_count ?? 0 },
    { label: "Approval", value: approved ? "Confirmed locally" : "Not approved" },
    { label: "Destructive ops", value: plan?.destructive_operations_blocked ? "Blocked" : "Not reported" },
    { label: "Recommended next action", value: plan ? "Review generated SQL and approval gate" : "Generate a provisioning plan" },
  ];

  return (
    <div className="page pq-page">
      <PageHeader
        title="Landing Zone Plan"
        subtitle="Generate plan-only Snowflake database, schema, warehouse, and role setup. Apply stays disabled by default and no DROP statements are emitted in v1."
        status={selectedRun?.status}
        primaryAction={<button className="btn btn-primary" disabled={busy} onClick={() => createPlan(false)}>{busy ? "Generating" : "Generate local plan"}</button>}
        secondaryAction={<button className="btn btn-ghost" disabled={busy} onClick={() => createPlan(true)}>Generate connected plan</button>}
      />
      <div className="pq-master-detail" style={{ gridTemplateColumns: "minmax(0,1fr) 320px" }}>
        <div>
          <WorkspaceTabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "architecture", label: "Architecture" },
              { id: "summary", label: "Resource Summary" },
              { id: "sql_plan", label: "Generated SQL" },
              { id: "approval", label: "Approval Gate" },
              { id: "runs", label: "Run History" },
            ]}
          />
          <div className="mt4">
            {tab === "architecture" ? (
              <SectionCard title="Provisioning inputs" subtitle="Plan databases, schemas, warehouses, roles, and optional resource monitors before approval.">
                {Object.entries({
                  project_name: "Project name",
                  environment: "Environment",
                  target_database: "Target database",
                  raw_schema: "Raw schema",
                  staging_schema: "Staging schema",
                  intermediate_schema: "Intermediate schema",
                  marts_schema: "Marts schema",
                  audit_schema: "Audit schema",
                  migration_warehouse: "Migration warehouse",
                  validation_warehouse: "Validation warehouse",
                  transformation_warehouse: "Transformation warehouse",
                  admin_role: "Admin role",
                  engineer_role: "Engineer role",
                  analyst_role: "Analyst role",
                  read_only_role: "Read only role",
                  resource_monitor: "Resource monitor",
                }).map(([key, label]) => <Field key={key} label={label}><input className="fi" value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></Field>)}
              </SectionCard>
            ) : null}
            {tab === "summary" ? (
              <ReportPreview title="Planned resources" report={plan?.resources ? { resources: plan.resources, mode: plan.mode, status: plan.status } : null} emptyMessage="No plan generated yet. Generate a local or connected plan to preview databases, schemas, warehouses, and roles." />
            ) : null}
            {tab === "sql_plan" ? (
              <CodeViewer title="Generated SQL plan" preview={sqlPlanPreview} artifact={null} />
            ) : null}
            {tab === "approval" ? (
              <SectionCard title="Approval gate" subtitle="Apply remains disabled by default and destructive operations are blocked in v1.">
                <ApprovalGate approved={approved} onToggle={setApproved} canApply={Boolean(selectedRun)} reason="Apply remains disabled until a plan exists and explicit approval is checked." />
                <div className="mt3">
                  <button className="btn btn-danger" disabled={!selectedRun || !approved} onClick={() => api.approveProvisionRun(selectedRun.id, true).then(() => api.applyProvisionRun(selectedRun.id)).then(setPlan)}>Apply disabled by default</button>
                </div>
                {!selectedRun || !approved ? <DisabledReason>Apply is blocked until a persisted plan exists and approval is explicitly granted.</DisabledReason> : null}
              </SectionCard>
            ) : null}
            {tab === "runs" ? (
              <SectionCard title="Provisioning runs" subtitle="Open a persisted plan to review its resources and SQL.">
                <DataTable rows={runs || []} onRowClick={openRun} emptyTitle="No provisioning runs yet" emptyMessage="Generate a Snowflake plan to create your first persisted provisioning run." columns={[
                  { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
                  { key: "safety_mode", label: "Safety mode" },
                  { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
                  { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
                ]} />
              </SectionCard>
            ) : null}
          </div>
        </div>
        <div>
          <ContextRail title="Provisioning context" items={provisionContextItems} />
          <SectionCard title="Provisioning guardrails" subtitle="Plan-first Snowflake resource design.">
            <div className="alert-info">No DROP statements are emitted in v1, and apply remains guarded even after approval until a Snowflake executor is configured.</div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

export function ArtifactFactoryPage({ setPage = null }) {
  const { data: artifacts, refresh } = useAsyncLoader(() => api.listControlPlaneArtifacts(), []);
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.listArtifactFactoryRuns(), []);
  const [selectedArtifacts, setSelectedArtifacts] = useState([]);
  const [activeArtifactKpi, setActiveArtifactKpi] = useState("runs");
  const [result, setResult] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewArtifact, setPreviewArtifact] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "dbt Model Creation",
    generation_type: "dbt staging model",
    project_name: "uma_migration",
    default_database: "ANALYTICS",
    default_schema: "STAGING",
    requirement: "",
    safety_mode: "PLAN_ONLY",
  });

  const visibleArtifacts = filterArtifactsForModule(
    artifacts,
    ["sql", "ddl", "json", "yaml", "yml", "zip", "SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT", "REQUIREMENTS", "REPORT"],
    result?.run?.id || "",
  );
  const selectedSourceArtifacts = visibleArtifacts.filter((artifact) => selectedArtifacts.includes(artifact.id));
  const generatedArtifacts = result?.artifacts || [];
  const artifactKpiTitles = {
    runs: "Artifact generation runs",
    selected: "Selected source artifacts",
    generated: "Generated artifacts in current run",
    type: "Generator configuration",
    preview: "Previewed artifact",
    safety: "Execution guard",
  };
  const artifactKpiRows = {
    runs: runs || [],
    selected: selectedSourceArtifacts,
    generated: generatedArtifacts,
    preview: previewArtifact ? [previewArtifact] : [],
  };
  const renderArtifactKpiDrilldown = () => {
    if (["type", "safety"].includes(activeArtifactKpi)) {
      return (
        <SectionCard title={artifactKpiTitles[activeArtifactKpi]} subtitle="Configuration behind the selected KPI.">
          <SummaryList items={[
            { label: "Generation type", value: form.generation_type },
            { label: "Project", value: form.project_name },
            { label: "Default database", value: form.default_database },
            { label: "Default schema", value: form.default_schema },
            { label: "Safety mode", value: form.safety_mode },
            { label: "Execution policy", value: "Plan-only. UMA does not execute generated SQL or dbt artifacts from this page." },
          ]} />
        </SectionCard>
      );
    }
    return (
      <SectionCard title={artifactKpiTitles[activeArtifactKpi]} subtitle="KPI-backed objects. Select artifacts below to preview or include in generation.">
        <DataTable
          rows={artifactKpiRows[activeArtifactKpi] || []}
          onRowClick={(row) => {
            if (row?.id && activeArtifactKpi !== "runs") {
              setPreviewArtifact(row);
              api.previewControlPlaneArtifact(row.id).then(setPreview).catch(() => {});
            }
          }}
          emptyTitle="No objects behind this KPI yet"
          emptyMessage="Run artifact generation or select source artifacts to populate this drilldown."
          columns={[
            { key: "original_filename", label: "Artifact", render: (row) => <span className="td-main">{row.original_filename || row.name || objectDisplayName(row)}</span> },
            { key: "artifact_category", label: "Type", render: (row) => row.artifact_category ? <StatusBadge status={row.artifact_category} /> : row.workflow_type || row.safety_mode || "Run" },
            { key: "status", label: "Status", render: (row) => row.status ? <StatusBadge status={row.status} /> : row.review_status || "Available" },
            { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
          ]}
        />
      </SectionCard>
    );
  };

  const generate = async () => {
    setBusy(true);
    try {
      const response = form.generation_type === "dbt project"
        ? await api.createArtifactFactoryDbtProject({ ...form, source_artifact_ids: selectedArtifacts })
        : await api.createArtifactFactoryDbtModels({ ...form, source_artifact_ids: selectedArtifacts });
      setResult(response);
      setSelectedMigrationRun(response.run.id);
      const generated = await api.getArtifactFactoryRunArtifacts(response.run.id);
      if (generated.length) {
        setPreviewArtifact(generated[0]);
        setPreview(await api.previewControlPlaneArtifact(generated[0].id));
      }
      await refreshRuns();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page pq-page">
      <PageHeader
        title="Generated Artifacts"
        subtitle="Generate plan-only dbt artifacts, Snowflake-ready migration assets, and reviewable deliverables from persisted source artifacts and migration outputs."
        primaryAction={<button className="btn btn-primary" disabled={!selectedArtifacts.length || busy} onClick={generate}>{busy ? "Generating" : "Generate"}</button>}
      />
      <OperationsAlertStrip
        items={(result?.artifacts || []).map((artifact) => ({
          id: artifact.id,
          title: artifact.original_filename,
          status: artifact.artifact_category,
          action: "Review generated artifact",
        }))}
        fallback="No generated artifacts are waiting for review."
      />
      <EnterpriseKpiRow items={[
        { label: "Runs", value: runs?.length || 0, note: "artifact generations", active: activeArtifactKpi === "runs", onClick: () => setActiveArtifactKpi("runs") },
        { label: "Selected sources", value: selectedArtifacts.length, note: "inputs", active: activeArtifactKpi === "selected", onClick: () => setActiveArtifactKpi("selected") },
        { label: "Generated", value: generatedArtifacts.length || 0, note: "current run", active: activeArtifactKpi === "generated", onClick: () => setActiveArtifactKpi("generated") },
        { label: "Type", value: form.generation_type, note: "selected generator", active: activeArtifactKpi === "type", onClick: () => setActiveArtifactKpi("type") },
        { label: "Preview", value: previewArtifact ? "Open" : "None", note: "selected artifact", active: activeArtifactKpi === "preview", onClick: () => setActiveArtifactKpi("preview") },
        { label: "Safety", value: form.safety_mode, note: "execution guard", active: activeArtifactKpi === "safety", onClick: () => setActiveArtifactKpi("safety") },
      ]} />
      {renderArtifactKpiDrilldown()}
      <div className="ep-workspace">
        <div>
        <SectionCard title="Artifact provenance" subtitle="Generated assets are grouped by source inputs, generator run, review state, and download action.">
            <DataTable
              rows={(result?.artifacts || []).map((artifact) => ({
                ...artifact,
                source_count: selectedArtifacts.length,
                source_chain: `${selectedArtifacts.length} source artifact${selectedArtifacts.length === 1 ? "" : "s"} -> ${form.generation_type}`,
                generated_by: form.generation_type,
                run_name: result?.run?.name,
                generation_job: result?.run?.id,
                review_decision: "Review required before execution",
                validation_state: "Not validated",
                report_state: result?.run?.id ? "Run report linked" : "No report",
              }))}
              emptyTitle="No generated artifacts yet"
              emptyMessage="Select source artifacts and generate dbt/SQL/report assets to populate provenance."
              columns={[
                { key: "original_filename", label: "Generated artifact", render: (row) => <span className="td-main">{row.original_filename}</span> },
                { key: "source_count", label: "Sources" },
                { key: "source_chain", label: "Source -> job" },
                { key: "run_name", label: "Run", render: (row) => <span className="td-main">{row.run_name}</span> },
                { key: "artifact_category", label: "Generated artifact", render: (row) => <StatusBadge status={row.artifact_category} /> },
                { key: "review_decision", label: "Review decision" },
                { key: "validation_state", label: "Validation" },
                { key: "report_state", label: "Report" },
                { key: "run_detail", label: "Run Detail", render: (row) => <button className="btn btn-ghost btn-sm" disabled={!setPage || !result?.run?.id} onClick={(event) => { event.stopPropagation(); setSelectedMigrationRun(result.run.id); setPage && setPage("run_detail"); }}>Open</button> },
                { key: "download", label: "Download", render: (row) => <button className="btn btn-ghost btn-sm" onClick={() => api.downloadControlPlaneArtifact(row.id, row.original_filename)}>Download</button> },
              ]}
            />
          </SectionCard>
        </div>
        <ObjectDetailPanel title={previewArtifact?.original_filename || "Artifact preview"} subtitle={previewArtifact ? "Selected generated artifact" : "Select or generate an artifact to preview."} status={previewArtifact?.artifact_category}>
          <CodeViewer title="Preview" preview={preview} artifact={previewArtifact} />
        </ObjectDetailPanel>
      </div>
      <div className="soft-grid">
        <SectionCard title="Generation types" subtitle="Choose the artifact workflow before configuring project defaults and source inputs.">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 12 }}>
            {ARTIFACT_FACTORY_GENERATION_TYPES.map((value) => (
              <button
                key={value}
                className={`btn ${form.generation_type === value ? "btn-primary" : "btn-ghost"}`}
                style={{ justifyContent: "flex-start", minHeight: 54 }}
                onClick={() => setForm({ ...form, generation_type: value })}
              >
                {value}
              </button>
            ))}
          </div>
        </SectionCard>
        <SectionCard title="Artifact generation setup" subtitle="dbt model creation is now a first-class workflow rather than a template list.">
          <Field label="Project name"><input className="fi" value={form.project_name} onChange={(event) => setForm({ ...form, project_name: event.target.value })} /></Field>
          <div className="fr">
            <Field label="Default database"><input className="fi" value={form.default_database} onChange={(event) => setForm({ ...form, default_database: event.target.value })} /></Field>
            <Field label="Default schema"><input className="fi" value={form.default_schema} onChange={(event) => setForm({ ...form, default_schema: event.target.value })} /></Field>
          </div>
          <Field label="Requirement or notes"><textarea className="fi" rows={4} value={form.requirement} onChange={(event) => setForm({ ...form, requirement: event.target.value })} /></Field>
          <DisabledReason>Generated Artifacts creates files and plans only. It does not execute SQL, dbt, or Snowflake provisioning.</DisabledReason>
        </SectionCard>
        <CodeViewer title="Generated artifact preview" preview={preview} artifact={previewArtifact} />
      </div>
      <ArtifactSelector artifacts={visibleArtifacts || []} selected={selectedArtifacts} setSelected={setSelectedArtifacts} />
      <div className="soft-grid mt4">
        <SectionCard title="Generated artifacts" subtitle="Persisted outputs can be previewed and downloaded after generation completes.">
          <DataTable
            rows={result?.artifacts || []}
            onRowClick={async (artifact) => {
              setPreviewArtifact(artifact);
              setPreview(await api.previewControlPlaneArtifact(artifact.id));
            }}
            emptyTitle="No generated artifacts yet"
            emptyMessage="Generate a dbt or migration artifact package to populate this table."
            columns={[
              { key: "artifact_category", label: "Artifact type" },
              { key: "original_filename", label: "File name", render: (row) => <span className="td-main">{row.original_filename}</span> },
              { key: "run_id", label: "Run", render: () => result?.run?.name || "Current run" },
              { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
              { key: "download", label: "Download", render: (row) => <button className="btn btn-ghost btn-sm" onClick={(event) => { event.stopPropagation(); api.downloadControlPlaneArtifact(row.id, row.original_filename); }}>Download</button> },
            ]}
          />
        </SectionCard>
        <SectionCard title="Generated artifact runs" subtitle="Generated artifacts are persisted and previewable after the run completes.">
          <DataTable rows={runs || []} emptyTitle="No generated artifact runs yet" emptyMessage="Generate dbt or migration artifacts to persist a first generated artifact run." columns={[
            { key: "name", label: "Run", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
            { key: "workflow_type", label: "Workflow type" },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
            { key: "run_detail", label: "Run Detail", render: (row) => <button className="btn btn-ghost btn-sm" disabled={!setPage} onClick={(event) => { event.stopPropagation(); setSelectedMigrationRun(row.id); setPage && setPage("run_detail"); }}>Open</button> },
          ]} />
        </SectionCard>
      </div>
    </div>
  );
}

export function ReportsPage({ setPage = null }) {
  const { data: reports, loading, error, refresh } = useAsyncLoader(() => api.listUnifiedReports(), []);
  const [preview, setPreview] = useState(null);
  const groupedReports = useMemo(() => {
    const groups = new Map();
    (reports || []).forEach((report) => {
      const key = report.run_id || report.id;
      const current = groups.get(key) || {
        id: key,
        run_id: report.run_id,
        run_name: report.run_name || report.metadata_json?.run_name || report.original_filename || "Report run",
        workflow_type: report.workflow_type || report.metadata_json?.workflow_type || "REPORT",
        created_at: report.created_at,
        reports: [],
      };
      current.reports.push(report);
      current.created_at = current.created_at || report.created_at;
      groups.set(key, current);
    });
    return Array.from(groups.values());
  }, [reports]);
  return (
    <div className="page pq-page">
      <PageHeader
        title="Reports"
        subtitle="Preview report artifacts generated by migration readiness, SQL conversion, dbt conversion, validation, advisor, provisioning, and replication workflows."
        primaryAction={<button className="btn btn-primary" onClick={refresh}>Refresh reports</button>}
      />
      <ErrorPanel error={error} />
      {loading ? <LoadingPanel label="Loading reports" /> : (
        <div className="ep-workspace">
          <SectionCard title="Reports by run" subtitle="Reports are grouped by migration/conversion/validation run so quality and evidence stay attached to the object that produced them.">
            <DataTable
              rows={groupedReports}
              onRowClick={async (row) => {
                if (row.run_id) setSelectedMigrationRun(row.run_id);
                setPreview(await api.previewUnifiedReport(row.run_id));
              }}
              emptyTitle="No reports generated yet"
              emptyMessage="Run Migration Intelligence, SQL Conversion, dbt Conversion, or Validation to create reports."
              emptyAction={setPage ? (
                <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage("orchestrator")}>Run assessment</button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("sql_conversion")}>Run conversion</button>
                </div>
              ) : null}
              columns={[
                { key: "run_name", label: "Run", render: (row) => <span className="td-main" style={{ overflowWrap: "anywhere" }}>{row.run_name}</span> },
                { key: "workflow_type", label: "Workflow" },
                { key: "reports", label: "Artifacts", render: (row) => row.reports.length },
                { key: "created_at", label: "Created time", render: (row) => fmtDate(row.created_at) },
                { key: "status", label: "Quality", render: (row) => <StatusBadge status={row.reports.some((item) => item.metadata_json?.generated === false) ? "DRAFT" : "COMPLETED"} /> },
                { key: "run_detail", label: "Run Detail", render: (row) => <button className="btn btn-ghost btn-sm" disabled={!row.run_id || !setPage} onClick={(event) => { event.stopPropagation(); setSelectedMigrationRun(row.run_id); setPage && setPage("run_detail"); }}>Open</button> },
                { key: "download", label: "Download", render: (row) => <button className="btn btn-ghost btn-sm" onClick={(event) => { event.stopPropagation(); api.downloadUnifiedReport(row.run_id); }}>Download</button> },
              ]}
            />
          </SectionCard>
          <ObjectDetailPanel
            title="Report preview"
            subtitle={preview?.run?.name || "Select a report group"}
            empty={!preview ? <EmptyState title="No report selected" message="Select a report artifact to render a formatted summary instead of a raw JSON block." compact /> : null}
          >
            {preview ? <ReportPreview title="Report preview" report={preview.report} emptyMessage="No report generated yet." /> : null}
          </ObjectDetailPanel>
        </div>
      )}
    </div>
  );
}

export function ReplicationPlanPage() {
  const { data: overview } = useAsyncLoader(() => api.getReplicationOverview().catch(() => null), []);
  const { data: connections } = useAsyncLoader(() => api.getReplicationConnections().catch(() => []), []);
  const { data: sources, refresh: refreshSources } = useAsyncLoader(() => api.getReplicationSources().catch(() => []), []);
  const { data: jobs, refresh: refreshJobs } = useAsyncLoader(() => api.getReplicationJobs().catch(() => []), []);
  const { data: runs, refresh: refreshRuns } = useAsyncLoader(() => api.getReplicationRuns().catch(() => []), []);
  const { data: readiness } = useAsyncLoader(() => api.getReplicationSnowflakeReadiness().catch(() => null), []);
  const [form, setForm] = useState({
    name: "",
    source_connection_id: "",
    destination_connection_id: "",
    sync_mode: "incremental",
    schedule: "manual",
    load_strategy: "incremental append",
  });
  const [selectedTableKeys, setSelectedTableKeys] = useState([]);
  const [activeReplicationKpi, setActiveReplicationKpi] = useState("sources");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [actionError, setActionError] = useState("");

  const sourceConnections = (connections || []).filter((connection) => ["source", "both"].includes(connection.role));
  const destinationConnections = (connections || []).filter((connection) => ["destination", "both"].includes(connection.role));
  const selectedSource = (sources || []).find((source) => source.connection_id === form.source_connection_id) || null;
  const availableTables = useMemo(() => {
    return (selectedSource?.schemas || []).flatMap((schema) =>
      (schema.tables || []).map((table) => ({
        key: `${table.schema_name || schema.name}.${table.table_name}`,
        schema_name: table.schema_name || schema.name,
        table_name: table.table_name,
        columns: table.columns || [],
      }))
    );
  }, [selectedSource]);
  const latestReplicationRun = (runs || [])[0] || null;
  const replicationTimeline = buildRunTimeline(latestReplicationRun, [], []);
  const replicationKpiTitles = {
    sources: "Configured replication sources",
    jobs: "Persisted replication jobs",
    runs: "Replication run history",
    readiness: "Snowflake target readiness",
    selected: "Selected table scope",
    latest: "Latest run evidence",
  };

  const syncModeForStrategy = (strategy) => {
    if (strategy === "full refresh") return "full_refresh";
    if (strategy === "CDC ready") return "cdc";
    return "incremental";
  };

  const toggleTable = (key) => {
    setSelectedTableKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  };

  const discoverSource = async () => {
    if (!form.source_connection_id) return;
    setBusy("discover");
    setActionError("");
    setMessage("");
    try {
      await api.discoverReplicationSource({ connection_id: form.source_connection_id, schema_limit: 8, table_limit: 100, include_columns: true });
      await refreshSources();
      setMessage("Source discovery refreshed.");
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const createJob = async () => {
    setBusy("create");
    setActionError("");
    setMessage("");
    try {
      if (!form.source_connection_id || !form.destination_connection_id) throw new Error("Select source and destination connections.");
      const chosenTables = availableTables.filter((table) => selectedTableKeys.includes(table.key));
      if (!chosenTables.length) throw new Error("Select at least one source table for the replication job.");
      const sourceConn = sourceConnections.find((connection) => connection.id === form.source_connection_id);
      const destinationConn = destinationConnections.find((connection) => connection.id === form.destination_connection_id);
      const payload = {
        name: form.name || `Replication - ${sourceConn?.name || "Source"} to ${destinationConn?.name || "Snowflake"}`,
        source_connection_id: form.source_connection_id,
        destination_connection_id: form.destination_connection_id,
        sync_mode: syncModeForStrategy(form.load_strategy),
        schedule: form.schedule,
        tables: chosenTables.map((table) => {
          const columnNames = (table.columns || []).map((column) => String(column.name || column.column_name || "").toLowerCase());
          const primary_key_columns = columnNames.includes("id") ? ["id"] : [];
          const watermark_column = columnNames.includes("updated_at") ? "updated_at" : columnNames.includes("event_ts") ? "event_ts" : columnNames.includes("created_at") ? "created_at" : null;
          return {
            schema_name: table.schema_name,
            table_name: table.table_name,
            target_schema: table.schema_name,
            target_table: table.table_name,
            selected: true,
            sync_mode: syncModeForStrategy(form.load_strategy),
            columns: table.columns || [],
            primary_key_columns,
            watermark_column,
          };
        }),
      };
      const created = await api.createReplicationJob(payload);
      await api.createReplicationJobPlan(created.id).catch(() => null);
      await Promise.all([refreshJobs(), refreshRuns()]);
      setMessage(`Replication job created: ${created.name}`);
      setSelectedTableKeys([]);
      setForm((current) => ({ ...current, name: "" }));
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setBusy("");
    }
  };

  return (
    <PageTransition className="page pq-page">
      <PageHeader
        title="Data Replication"
        subtitle="Keep replication focused on a Fivetran or Stitch style source-to-Snowflake plan: discover tables, select scope, create a persisted job, generate target DDL, and stage reconciliation before execution."
        primaryAction={<button className="btn btn-primary" disabled={busy === "create"} onClick={createJob}>{busy === "create" ? "Creating job" : "Create job"}</button>}
      />
      <OperationsAlertStrip
        items={(jobs || []).filter((job) => ["FAILED", "ERROR", "BLOCKED"].includes(String(job.status || "").toUpperCase())).map((job) => ({
          id: job.id,
          title: job.name,
          status: job.status,
          action: job.latest_error || "Open job and inspect failure",
        }))}
        fallback="No failed replication jobs are blocking the workspace."
      />
      <EnterpriseKpiRow items={[
        { label: "Sources", value: overview?.connection_count ?? 0, note: "configured endpoints", active: activeReplicationKpi === "sources", onClick: () => setActiveReplicationKpi("sources") },
        { label: "Jobs", value: jobs?.length ?? 0, note: "persisted definitions", active: activeReplicationKpi === "jobs", onClick: () => setActiveReplicationKpi("jobs") },
        { label: "Runs", value: runs?.length ?? 0, note: "execution records", active: activeReplicationKpi === "runs", onClick: () => setActiveReplicationKpi("runs") },
        { label: "Readiness", value: readiness?.status || "Unknown", note: "Snowflake target", active: activeReplicationKpi === "readiness", onClick: () => setActiveReplicationKpi("readiness") },
        { label: "Tables selected", value: selectedTableKeys.length, note: "new job scope", active: activeReplicationKpi === "selected", onClick: () => setActiveReplicationKpi("selected") },
        { label: "Latest run", value: latestReplicationRun ? <StatusBadge status={latestReplicationRun.status} /> : "None", note: "timeline evidence", active: activeReplicationKpi === "latest", onClick: () => setActiveReplicationKpi("latest") },
      ]} />
      <SectionCard title={replicationKpiTitles[activeReplicationKpi]} subtitle="KPI-backed replication objects and evidence.">
        {activeReplicationKpi === "sources" ? (
          <DataTable rows={connections || []} emptyTitle="No replication endpoints" emptyMessage="Create or test source and target connections before defining jobs." columns={[
            { key: "name", label: "Connection", render: (row) => <span className="td-main">{row.name}</span> },
            { key: "type", label: "Type" },
            { key: "role", label: "Role" },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status || row.health_status || "UNKNOWN"} /> },
          ]} />
        ) : activeReplicationKpi === "jobs" ? (
          <DataTable rows={jobs || []} emptyTitle="No replication jobs" emptyMessage="Select tables and create a persisted replication job." columns={[
            { key: "name", label: "Job", render: (row) => <span className="td-main">{row.name}</span> },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "latest_error", label: "Latest error" },
          ]} />
        ) : activeReplicationKpi === "runs" || activeReplicationKpi === "latest" ? (
          <DataTable rows={activeReplicationKpi === "latest" && latestReplicationRun ? [latestReplicationRun] : (runs || [])} emptyTitle="No run records" emptyMessage="Start a replication job to create run history." columns={[
            { key: "id", label: "Run", render: (row) => <span className="td-main">{String(row.id || "").slice(0, 10)}</span> },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "created_at", label: "Created", render: (row) => fmtDate(row.created_at) },
          ]} />
        ) : activeReplicationKpi === "selected" ? (
          <DataTable rows={availableTables.filter((table) => selectedTableKeys.includes(table.key))} emptyTitle="No selected tables" emptyMessage="Choose source tables below to populate the selected scope." columns={[
            { key: "schema_name", label: "Schema" },
            { key: "table_name", label: "Table", render: (row) => <span className="td-main">{row.table_name}</span> },
            { key: "columns", label: "Columns", render: (row) => row.columns?.length || 0 },
          ]} />
        ) : (
          <SummaryList items={[
            { label: "Readiness status", value: readiness?.status || "Unknown" },
            { label: "Readiness message", value: readiness?.message || "No Snowflake readiness check recorded." },
            { label: "Validation boundary", value: "Replication planning does not require Snowflake execution." },
          ]} />
        )}
      </SectionCard>
      {message ? <div className="alert-ok">{message}</div> : null}
      <ErrorPanel error={actionError} />
      <div className="ep-workspace">
        <SectionCard title="Latest run timeline" subtitle="Extract, stage, load, merge, validate, and report phases from the latest run.">
          <RunTimeline phases={replicationTimeline} />
        </SectionCard>
        <ObjectDetailPanel title="Replication actions" subtitle="Start/retry/cancel controls stay guarded by job state." status={latestReplicationRun?.status || "NOT_STARTED"}>
          <div className="ep-action-row">
            <button className="btn btn-primary btn-sm" disabled={!jobs?.length}>Start selected job</button>
            <button className="btn btn-ghost btn-sm" disabled={!jobs?.length}>Retry failed run</button>
            <button className="btn btn-ghost btn-sm" disabled>Cancel running job</button>
          </div>
          <div className="ep-empty-compact">Latest target readiness: {readiness?.message || readiness?.status || "No readiness check recorded."}</div>
        </ObjectDetailPanel>
      </div>
      <div className="ep-workspace">
        <SectionCard title="Configure replication job" subtitle="Choose persisted replication endpoints, discover source tables, and create a real backend job definition.">
          <div className="fr two-col">
            <Field label="Job name">
              <input className="fi" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Replication - Retail to Snowflake" />
            </Field>
            <Field label="Load strategy">
              <select className="fi" value={form.load_strategy} onChange={(event) => setForm({ ...form, load_strategy: event.target.value })}>{REPLICATION_STRATEGIES.map((value) => <option key={value}>{value}</option>)}</select>
            </Field>
            <Field label="Source connection">
              <select className="fi" value={form.source_connection_id} onChange={(event) => { setForm({ ...form, source_connection_id: event.target.value }); setSelectedTableKeys([]); }}>
                <option value="">Select source connection</option>
                {sourceConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}
              </select>
            </Field>
            <Field label="Target Snowflake connection">
              <select className="fi" value={form.destination_connection_id} onChange={(event) => setForm({ ...form, destination_connection_id: event.target.value })}>
                <option value="">Select target connection</option>
                {destinationConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}
              </select>
            </Field>
            <Field label="Schedule">
              <select className="fi" value={form.schedule} onChange={(event) => setForm({ ...form, schedule: event.target.value })}>
                <option value="manual">manual</option>
                <option value="0 * * * *">hourly</option>
                <option value="0 2 * * *">daily 2am</option>
                <option value="*/15 * * * *">every 15 minutes</option>
              </select>
            </Field>
          </div>
          <div className="pq-action-row" style={{ marginTop: 12 }}>
            <button className="btn btn-ghost" disabled={!form.source_connection_id || busy === "discover"} onClick={discoverSource}>
              {busy === "discover" ? "Discovering" : "Discover tables"}
            </button>
            <button className="btn btn-ghost" disabled={!availableTables.length} onClick={() => setSelectedTableKeys(availableTables.map((table) => table.key))}>Select all</button>
            <button className="btn btn-ghost" disabled={!selectedTableKeys.length} onClick={() => setSelectedTableKeys([])}>Clear selection</button>
          </div>
          <DisabledReason>Creating a replication job persists source, target, table selection, and sync strategy. No data movement starts until you explicitly plan or execute a run.</DisabledReason>
        </SectionCard>
        <SectionCard title="Discovered source tables" subtitle="Selected tables become the persisted scope of the new replication job.">
          {!availableTables.length ? <EmptyState title="No discovered tables yet" message="Select a source connection and run discovery to load source tables into the job configuration flow." compact /> : (
            <DataTable
              rows={availableTables}
              columns={[
                { key: "selected", label: "Use", render: (row) => <input type="checkbox" checked={selectedTableKeys.includes(row.key)} onChange={() => toggleTable(row.key)} /> },
                { key: "schema_name", label: "Schema" },
                { key: "table_name", label: "Table", render: (row) => <span className="td-main">{row.table_name}</span> },
                { key: "columns", label: "Columns", render: (row) => row.columns?.length ?? 0 },
              ]}
            />
          )}
        </SectionCard>
        <SectionCard title="Replication workflow" subtitle="Generate plans first. Execution only becomes available when the runtime is configured and safe.">
          <SummaryList items={[
            { label: "1", value: "Source connection" },
            { label: "2", value: "Target Snowflake connection" },
            { label: "3", value: "Discover tables" },
            { label: "4", value: "Create persisted job" },
            { label: "5", value: "Generate target DDL and reconciliation plan" },
            { label: "6", value: "Run only when execution engine is safe" },
          ]} />
          <DisabledReason>Replication execution uses the configured runtime only when it is available and approved for this job.</DisabledReason>
        </SectionCard>
        <SectionCard title="Persisted replication jobs" subtitle="These rows come from the backend replication control plane.">
          <DataTable rows={jobs || []} emptyTitle="No replication jobs yet" emptyMessage="Create replication connections and jobs in the backend-connected replication workflow before execution." columns={[
            { key: "name", label: "Job", render: (row) => <span className="td-main">{objectDisplayName(row)}</span> },
            { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
            { key: "load_strategy", label: "Load strategy" },
            { key: "tables", label: "Tables", render: (row) => row.table_count ?? 0 },
          ]} />
        </SectionCard>
      </div>
    </PageTransition>
  );
}

export function AdvisorControlPage() {
  const { data: connections } = useAsyncLoader(() => api.getConnections().catch(() => []), []);
  const { data: scans, refresh: refreshScans } = useAsyncLoader(() => api.listAdvisorScans(), []);
  const [report, setReport] = useState(null);
  const [checks, setChecks] = useState([]);
  const [form, setForm] = useState({ connection_id: "", dry_run: true });
  const [busy, setBusy] = useState(false);

  const runScan = async () => {
    setBusy(true);
    try {
      const scan = await api.createAdvisorScan({ ...form, categories: ["SECURITY", "COMPUTE", "STORAGE", "MIGRATION_READINESS"] });
      await api.runAdvisorScan(scan.id);
      setReport(await api.getAdvisorReport(scan.id));
      setChecks(await api.getAdvisorChecks(scan.id));
      await refreshScans();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page pq-page">
      <PageHeader title="Readiness Scan" subtitle="Optional connected Snowflake posture checks for security, compute, storage, and migration readiness. It does not apply changes." primaryAction={<button className="btn btn-primary" disabled={busy} onClick={runScan}>{busy ? "Scanning" : "Run scan"}</button>} />
      <div className="soft-grid">
        <SectionCard title="Advisor inputs">
          <Field label="Snowflake connection"><select className="fi" value={form.connection_id} onChange={(event) => setForm({ ...form, connection_id: event.target.value })}><option value="">Select Snowflake connection</option>{(connections || []).filter((connection) => connection.type === "snowflake").map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}</select></Field>
          <label className="settings-row"><span className="settings-key">Dry run</span><input type="checkbox" checked={form.dry_run} onChange={(event) => setForm({ ...form, dry_run: event.target.checked })} /></label>
          {!form.connection_id ? <DisabledReason>Select a Snowflake connection or run dry-run check validation.</DisabledReason> : null}
        </SectionCard>
        <SectionCard title="Scan scores">
          <SummaryList items={[
            { label: "Health", value: report ? (report?.scan?.health_score ?? "NA") : "NA" },
            { label: "Security", value: report ? (report?.scan?.security_score ?? "NA") : "NA" },
            { label: "Compute", value: report ? (report?.scan?.compute_score ?? "NA") : "NA" },
            { label: "Migration readiness", value: report ? (report?.scan?.migration_readiness_score ?? "NA") : "NA" },
          ]} />
        </SectionCard>
      </div>
      <SectionCard title="Readiness checks"><DataTable rows={checks} emptyTitle="No readiness results yet" emptyMessage="Run a readiness scan to persist Snowflake posture checks and recommendations." columns={[
        { key: "category", label: "Category" },
        { key: "check_name", label: "Check", render: (row) => <span className="td-main">{row.check_name}</span> },
        { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
        { key: "severity", label: "Severity", render: (row) => <SeverityBadge severity={row.severity} /> },
        { key: "recommendation", label: "Recommendation" },
      ]} /></SectionCard>
      <SectionCard title="Advisor scan history"><DataTable rows={scans || []} emptyTitle="No advisor scans yet" emptyMessage="Select a Snowflake connection and run a posture scan." columns={[
        { key: "id", label: "Scan", render: (row) => <span className="td-main">{row.id.slice(0, 8)}</span> },
        { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
        { key: "migration_readiness_score", label: "Readiness" },
      ]} /></SectionCard>
      <ReportPreview title="Advisor report" report={report} emptyMessage="No checks have been run yet." />
    </div>
  );
}

export function AICopilotControlPage() {
  const { data: providersPayload } = useAsyncLoader(() => api.getCopilotProviders().catch(() => ({ providers: [] })), []);
  const { data: activeProviderStatus, refresh: refreshActiveProvider } = useAsyncLoader(() => api.getAiProviderStatus().catch((err) => ({ active_provider: "offline_deterministic", available: false, error: getErrorMessage(err) })), []);
  const { data: ollamaHealth, refresh: refreshOllama } = useAsyncLoader(() => api.getOllamaHealth().catch((err) => ({ available: false, error: getErrorMessage(err) })), []);
  const { data: ragStatus, refresh: refreshRagStatus } = useAsyncLoader(() => api.getRagStatus().catch(() => ({ enabled: false, chunks: 0 })), []);
  const { data: toolRegistry } = useAsyncLoader(() => api.getInternalToolRegistryStatus().catch(() => ({ remote_mcp_server: false, honest_label: "Internal Tool Registry", tools: [] })), []);
  const { data: services } = useAsyncLoader(() => api.getCopilotSnowflakeServices().catch(() => ({})), []);
  const { data: runs } = useAsyncLoader(() => api.getControlPlaneRuns().catch(() => []), []);
  const [message, setMessage] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [copilotTab, setCopilotTab] = useState("workspace");
  const [activeCopilotKpi, setActiveCopilotKpi] = useState("mode");
  const [response, setResponse] = useState(null);
  const [busy, setBusy] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const providerList = Array.isArray(providersPayload?.providers) ? providersPayload.providers : [];
  const configuredProviders = providerList.filter((provider) => provider?.name !== "offline_deterministic" && (provider?.health?.status === "CONFIGURED" || provider?.health?.configured || provider?.selected));
  const activeProvider = activeProviderStatus || {};
  const ollamaReady = Boolean(ollamaHealth?.available);
  const ragReady = Boolean(ragStatus?.enabled && Number(ragStatus?.chunks || 0) > 0);
  const activeProviderAvailable = Boolean(activeProvider.available && activeProvider.chat_supported);
  const aiPatchReady = Boolean(activeProvider.patch_proposal_supported && activeProvider.chat_supported);
  const providerBackedCopilot = Boolean(ollamaReady || configuredProviders.length);
  const ask = async () => {
    if (!message.trim()) return;
    setBusy(true);
    try {
      const run = (runs || []).find((item) => item.id === selectedRunId);
      setResponse(await api.askCopilot({ message, provider: ollamaReady ? "ollama" : undefined, context: { selected_run_id: selectedRunId || null, run_id: selectedRunId || null, run_summary: run?.summary_json || null } }));
    } finally {
      setBusy(false);
    }
  };
  const indexSelectedRun = async () => {
    if (!selectedRunId) return;
    setIndexing(true);
    try {
      await api.indexRagRun(selectedRunId);
      await refreshRagStatus();
    } finally {
      setIndexing(false);
    }
  };
  const selectedRun = (runs || []).find((run) => run.id === selectedRunId);
  const copilotKpiPanel = {
    mode: [
      { label: "Active provider", value: activeProvider.active_provider || providersPayload?.selected_provider || "offline_deterministic" },
      { label: "Provider health", value: activeProvider.available ? "Available" : "Unavailable" },
      { label: "Model", value: activeProvider.model || "offline" },
      { label: "AI patch behavior", value: aiPatchReady ? "Proposal only; approval, judge, and validation gates required" : "Disabled because no chat-capable patch provider is configured" },
      { label: "Grounding", value: ragReady ? `RAG indexed (${ragStatus.chunks} chunks)` : "Selected UMA run plus deterministic context" },
      { label: "Unavailable reason", value: activeProvider.error || ragStatus?.unavailable_reason || "No blocker reported" },
    ],
    providers: providerList.map((provider) => ({
      label: provider.name || provider.provider || "Provider",
      value: provider.health?.status || (provider.health?.configured ? "CONFIGURED" : "NOT_CONFIGURED"),
    })),
    grounding: [
      { label: "Selected run", value: selectedRun?.name || "None selected" },
      { label: "Workflow", value: selectedRun?.workflow_type || "No run context" },
      { label: "Status", value: selectedRun?.status || "Not grounded" },
    ],
    patching: [
      { label: "AI patching", value: aiPatchReady ? "Enabled for proposals after provider response and explicit apply" : "Disabled - provider missing or lacks chat" },
      { label: "Auto-apply", value: "Never" },
      { label: "Required gate", value: "Judge reruns immediately; validation is marked stale until rerun" },
      { label: "Risk handling", value: "Risky accepted patches create Brain Review items" },
    ],
  };
  return (
    <div className="page pq-page">
      <PageHeader title="AI Copilot" subtitle="Use AI Copilot as a guided assistant over persisted UMA runs and artifacts. It should explain results, not replace the deterministic product workflow." />
      <OperationsAlertStrip
        items={!ollamaReady && !configuredProviders.length ? [{ id: "offline", title: ollamaHealth?.error || "No LLM provider configured", status: "AI_UNAVAILABLE", action: "AI patching disabled" }] : []}
        fallback={ollamaReady ? "Local Ollama is available. Answers remain grounded in local UMA RAG context." : "Provider-backed Copilot is configured. Answers remain grounded in selected UMA context."}
      />
      <EnterpriseKpiRow items={[
        { label: "Mode", value: activeProviderAvailable ? "Provider" : "Offline", note: activeProvider.local_private_mode ? "local/private" : "external provider", active: activeCopilotKpi === "mode", onClick: () => setActiveCopilotKpi("mode") },
        { label: "Providers", value: configuredProviders.length, note: "configured", active: activeCopilotKpi === "providers", onClick: () => setActiveCopilotKpi("providers") },
        { label: "RAG", value: ragStatus?.production_ready ? "Production" : ragReady ? "Dev indexed" : "Not ready", note: `${ragStatus?.chunks || 0} chunks · ${ragStatus?.effective_vector_store || "none"}`, active: activeCopilotKpi === "grounding", onClick: () => setActiveCopilotKpi("grounding") },
        { label: "AI patching", value: aiPatchReady ? "Advisory" : "Disabled", note: aiPatchReady ? "judge gated" : "provider missing", active: activeCopilotKpi === "patching", onClick: () => setActiveCopilotKpi("patching") },
      ]} />
      <WorkspaceTabs
        active={copilotTab}
        onChange={setCopilotTab}
        tabs={[
          { id: "workspace", label: "Workspace" },
          { id: "details", label: "Context details" },
          { id: "capabilities", label: "Capabilities" },
        ]}
      />
      {copilotTab === "capabilities" ? <SectionCard title="AI provider capability matrix" subtitle="Truthful runtime capabilities for the active provider. Disabled features stay disabled until the provider supports them.">
        <SummaryList items={[
          { label: "Active provider", value: activeProvider.active_provider || "offline_deterministic" },
          { label: "Provider health", value: activeProvider.available ? "available" : "unavailable" },
          { label: "Model", value: activeProvider.model || "offline" },
          { label: "Chat capability", value: activeProvider.chat_supported ? "supported" : "not supported" },
          { label: "Embedding capability", value: activeProvider.embeddings_supported ? "supported" : "not supported" },
          { label: "RAG capability", value: activeProvider.rag_supported && ragStatus?.production_ready ? "production ready" : ragStatus?.mode || "dev/local only" },
          { label: "AI patch capability", value: aiPatchReady ? "proposal only" : "disabled" },
          { label: "Local/private mode", value: activeProvider.local_private_mode ? "yes" : "no" },
          { label: "Unavailable reason", value: activeProvider.error || ragStatus?.unavailable_reason || "None" },
          { label: "Tool registry", value: `${toolRegistry?.honest_label || "Internal Tool Registry"} · remote MCP server: ${toolRegistry?.remote_mcp_server ? "yes" : "no"}` },
        ]} />
      </SectionCard> : null}
      {copilotTab === "details" ? <SectionCard title={`${activeCopilotKpi.slice(0, 1).toUpperCase()}${activeCopilotKpi.slice(1)} details`} subtitle="KPI-backed Copilot context and capability state.">
        <SummaryList items={(copilotKpiPanel[activeCopilotKpi] || []).length ? copilotKpiPanel[activeCopilotKpi] : [{ label: "Providers", value: "No configured provider records returned" }]} />
      </SectionCard> : null}
      {copilotTab === "workspace" ? <div className="ep-workspace" style={{ gridTemplateColumns: "minmax(0,1fr) 340px" }}>
        <SectionCard title="Copilot workspace" subtitle="Ask about a selected run, conversion warning, dbt recommendation, validation failure, or advisor finding.">
            <>
              {!providerBackedCopilot ? (
                <div className="alert-info">No LLM provider is configured. Offline deterministic Copilot is still available for grounded UMA navigation and summaries; AI patching and provider-backed answers stay disabled.</div>
              ) : null}
              <div className="soft-grid" style={{ marginBottom: 12 }}>
                <Field label="Selected run"><select className="fi" value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}><option value="">None</option>{(runs || []).map((run) => <option key={run.id} value={run.id}>{run.name}</option>)}</select></Field>
                <Field label="Active context"><input className="fi" value={selectedRun?.workflow_type || "No run selected"} readOnly /></Field>
              </div>
              <div className="ep-action-row mb3">
                <button className="btn btn-ghost btn-sm" disabled={!selectedRunId || indexing} onClick={indexSelectedRun}>{indexing ? "Indexing" : "Index selected run"}</button>
                <button className="btn btn-ghost btn-sm" onClick={() => { refreshOllama(); refreshRagStatus(); refreshActiveProvider(); }}>Refresh AI status</button>
              </div>
              <Field label="Question"><textarea className="fi" rows={6} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Summarize the selected run and explain the review items." /></Field>
              <div className="copilot-suggestion-grid">
                {COPILOT_SUGGESTIONS.map((suggestion) => (
                  <button key={suggestion} className="copilot-suggestion-card" onClick={() => setMessage(suggestion)}>
                    {suggestion}
                  </button>
                ))}
              </div>
              <div className="copilot-action-row">
                <button className="btn btn-primary" disabled={busy || !message.trim()} onClick={ask}>{busy ? "Asking" : "Ask Copilot"}</button>
                {!message.trim() ? <DisabledReason>Enter or choose a grounded question to ask Copilot.</DisabledReason> : null}
              </div>
              <div className="divider" />
              {response ? (
                <>
                  <SummaryList items={[
                    { label: "Provider", value: response.provider || "Unknown" },
                    { label: "Provider status", value: response.health?.status || "Unknown" },
                    { label: "Suggested action", value: response.proposed_action?.action_type || "None" },
                    { label: "Citations", value: response.citations?.length || response.source_context?.rag?.length || 0 },
                  ]} />
                  <SectionCard title="Response" subtitle="Grounded explanation from persisted UMA context.">
                    <div className="info-tile-value">{response.answer || "No answer returned."}</div>
                  </SectionCard>
                  <ReportPreview title="Grounding context" report={response.source_context} emptyMessage="No grounded context was attached to this response." />
                </>
              ) : <EmptyState title="No response yet" message="Submit a question to generate a grounded explanation from the configured copilot provider." compact />}
            </>
        </SectionCard>
        <div className="copilot-rail">
          <SectionCard title="Provider context" subtitle="Service health, provider readiness, grounding mode, and selected run context.">
            <SummaryList items={[
              { label: "LLM providers", value: configuredProviders.length || "Not configured" },
              { label: "Selected provider", value: ollamaReady ? "ollama" : configuredProviders.length ? providersPayload?.selected_provider || "configured" : "offline" },
              { label: "Ollama", value: ollamaReady ? `${ollamaHealth.chat_model} / ${ollamaHealth.embedding_model}` : ollamaHealth?.error || "Unavailable" },
              { label: "RAG", value: ragReady ? `${ragStatus.chunks} chunks indexed` : "No indexed chunks" },
              ...copilotServiceItems(services),
              { label: "Selected run", value: selectedRun?.name || "None" },
            ]} />
          </SectionCard>
          <SectionCard title="Safe usage" subtitle="Copilot should guide, not silently act.">
            <SummaryList items={[
              { label: "Allowed behavior", value: "Explain runs, warnings, recommendations, and failures" },
              { label: "Blocked by default", value: "Execution, provisioning apply, and unsafe mutations" },
              { label: "Fallback path", value: "Deterministic reports remain available without LLMs" },
            ]} />
          </SectionCard>
        </div>
      </div> : null}
    </div>
  );
}
