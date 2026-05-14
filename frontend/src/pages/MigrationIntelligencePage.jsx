import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api";
import CodeGenerationPanel from "../components/CodeGenerationPanel.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorPanel from "../components/ErrorPanel.jsx";
import LoadingPanel from "../components/LoadingPanel.jsx";
import ResultGrid from "../components/ResultGrid.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { fmtBytes, fmtDate, getErrorMessage } from "../components/format.js";

export const SUPPORTED_UPLOAD_EXTENSIONS = [".sql", ".txt", ".md", ".pdf"];
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const DISCLOSURE_ROWS = [
  { label: "OpenAI called", key: "openai_called", forcedNo: false },
  { label: "Snowflake Cortex called", key: "snowflake_cortex_called", forcedNo: false },
  { label: "Snowflake SQL executed", key: "snowflake_sql_executed", forcedNo: false },
  { label: "Uploaded SQL executed", key: "uploaded_sql_executed", forcedNo: true },
  { label: "Generated code executed", key: "generated_code_executed", forcedNo: true },
  { label: "DDL/DML executed", key: "ddl_executed", forcedNo: true },
  { label: "Data moved", key: "data_moved", forcedNo: true },
];

function yesNo(value) {
  return value ? "Yes" : "No";
}

function normalizeStatus(status) {
  const value = String(status || "").toUpperCase();
  if (value === "COMPLETED" || value === "SUCCEEDED" || value === "SUCCESS") return "Completed";
  if (value === "FAILED" || value === "ERROR") return "Failed";
  if (value === "BLOCKED") return "Blocked";
  if (value === "NEEDS_REVIEW") return "Needs review";
  if (value === "RUNNING") return "Running";
  if (value === "QUEUED") return "Queued";
  return status || "Unknown";
}

function formatFindingSeverity(value) {
  return String(value || "UNKNOWN").replace(/_/g, " ");
}

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function sectionByTitle(report, title) {
  return asList(report?.report_json?.sections).find((section) => section?.title === title) || null;
}

function parseInventoryObjects(report) {
  const inventory = sectionByTitle(report, "SQL / Procedure / DDL Inventory");
  const values = { tables: [], views: [], procedures: [] };
  asList(inventory?.content).forEach((line) => {
    if (typeof line !== "string") return;
    const [label, rawValue] = line.split(":");
    const key = String(label || "").trim().toLowerCase();
    const value = String(rawValue || "").trim();
    if (!value || value === "None detected") return;
    if (key === "tables") values.tables = value.split(",").map((item) => item.trim()).filter(Boolean);
    if (key === "views") values.views = value.split(",").map((item) => item.trim()).filter(Boolean);
    if (key === "procedures") values.procedures = value.split(",").map((item) => item.trim()).filter(Boolean);
  });
  return values;
}

function reportFlags(report, preview) {
  return preview?.flags || report?.report_json?.flags || {};
}

function disclosureRows(record) {
  return DISCLOSURE_ROWS.map((row) => ({
    action: row.label,
    value: row.forcedNo ? "No" : yesNo(record?.[row.key]),
  }));
}

function triggerSelection(setter, value, checked) {
  setter((current) => {
    const next = new Set(current);
    if (checked) next.add(value);
    else next.delete(value);
    return Array.from(next);
  });
}

function inventoryLineMap(report) {
  const inventory = sectionByTitle(report, "SQL / Procedure / DDL Inventory");
  return asList(inventory?.content).reduce((acc, line) => {
    if (typeof line !== "string") return acc;
    const [label, ...rest] = line.split(":");
    acc[String(label || "").trim()] = rest.join(":").trim();
    return acc;
  }, {});
}

function reportNextActions(report) {
  return asList(sectionByTitle(report, "Recommended Next Actions")?.content);
}

function reportBlockers(report) {
  return asList(sectionByTitle(report, "Blockers")?.content);
}

function reportReplicationAssessment(report) {
  return asList(sectionByTitle(report, "Data Replication Assessment")?.content);
}

function sourceObjectSummary(report) {
  const objects = parseInventoryObjects(report);
  return [...objects.tables, ...objects.views, ...objects.procedures];
}

function hasGeneratedCodeRecommendation(report) {
  const inventory = inventoryLineMap(report);
  const procedureCount = Number(String(inventory["Procedure/BTEQ chunks"] || "0").split(" ")[0]);
  const ddlCount = Number(String(inventory["DDL chunks"] || "0").split(" ")[0]);
  const hasProcedures = (parseInventoryObjects(report).procedures || []).length > 0;
  return procedureCount > 0 || hasProcedures || ddlCount > 0;
}

function extensionForFile(file) {
  const name = String(file?.name || "");
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
}

function validateUploadFiles(files) {
  for (const file of files) {
    const ext = extensionForFile(file);
    if (!SUPPORTED_UPLOAD_EXTENSIONS.includes(ext)) {
      return `Unsupported file type \`${ext || "unknown"}\`. Upload .sql, .txt, .md, or text-based .pdf files only.`;
    }
    if (!Number.isFinite(file.size) || file.size <= 0) {
      return `\`${file.name}\` is empty. Upload a non-empty artifact.`;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return `\`${file.name}\` exceeds the ${Math.round(MAX_UPLOAD_BYTES / (1024 * 1024))} MB upload limit for this MVP.`;
    }
  }
  return "";
}

function pickExistingId(rows, selectedId) {
  if (!selectedId) return rows?.[0]?.id || "";
  return rows.some((row) => row.id === selectedId) ? selectedId : rows?.[0]?.id || "";
}

function pickExistingReportId(runs, selectedRunId, selectedReportId) {
  const reportIds = runs.map((run) => run.report_id).filter(Boolean);
  if (selectedReportId && reportIds.includes(selectedReportId)) return selectedReportId;
  const selectedRunReportId = runs.find((run) => run.id === selectedRunId)?.report_id;
  if (selectedRunReportId) return selectedRunReportId;
  return reportIds[0] || "";
}

export default function MigrationIntelligencePage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [connections, setConnections] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [runs, setRuns] = useState([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState("");
  const [artifactDetail, setArtifactDetail] = useState(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState(null);
  const [runSteps, setRunSteps] = useState([]);
  const [runFindings, setRunFindings] = useState([]);
  const [selectedReportId, setSelectedReportId] = useState("");
  const [reportDetail, setReportDetail] = useState(null);
  const [reportPreview, setReportPreview] = useState(null);
  const [selectedArtifactIds, setSelectedArtifactIds] = useState([]);
  const [runDraft, setRunDraft] = useState({
    source_connection_id: "",
    target_connection_id: "",
    agent_mode: "deterministic_local",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const sourceConnections = useMemo(
    () => connections.filter((connection) => String(connection.type || "").toLowerCase() !== "snowflake"),
    [connections],
  );
  const targetConnections = useMemo(
    () => connections.filter((connection) => String(connection.type || "").toLowerCase() === "snowflake"),
    [connections],
  );
  const selectedRun = runDetail || runs.find((run) => run.id === selectedRunId) || runs[0] || null;
  const latestRun = runs[0] || null;
  const selectedReport = reportDetail;
  const currentArtifact = artifactDetail || artifacts.find((artifact) => artifact.id === selectedArtifactId) || null;

  const loadArtifact = useCallback(async (artifactId) => {
    if (!artifactId) {
      setArtifactDetail(null);
      return;
    }
    try {
      const detail = await api.getIntelligenceArtifact(artifactId);
      setArtifactDetail(detail);
      setSelectedArtifactId(artifactId);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    }
  }, []);

  const loadRun = useCallback(async (runId) => {
    if (!runId) {
      setRunDetail(null);
      setRunSteps([]);
      setRunFindings([]);
      return;
    }
    try {
      const [detail, steps, findings] = await Promise.all([
        api.getIntelligenceRun(runId),
        api.getIntelligenceRunSteps(runId),
        api.getIntelligenceRunFindings(runId),
      ]);
      setRunDetail(detail);
      setRunSteps(steps || []);
      setRunFindings(findings || []);
      setSelectedRunId(runId);
      if (detail?.report_id) setSelectedReportId(detail.report_id);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    }
  }, []);

  const loadReport = useCallback(async (reportId) => {
    if (!reportId) {
      setReportDetail(null);
      setReportPreview(null);
      return;
    }
    try {
      const [detail, preview] = await Promise.all([
        api.getIntelligenceReport(reportId),
        api.previewIntelligenceReport(reportId),
      ]);
      setReportDetail(detail);
      setReportPreview(preview);
      setSelectedReportId(reportId);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    }
  }, []);

  const refresh = useCallback(async (options = {}) => {
    const preferredArtifactId = options.preferredArtifactId || "";
    const preferredRunId = options.preferredRunId || "";
    const preferredReportId = options.preferredReportId || "";
    const preferredArtifactIds = Array.isArray(options.preferredArtifactIds) ? options.preferredArtifactIds : [];
    setLoading(true);
    setError("");
    try {
      const [connectionRows, artifactRows, runRows] = await Promise.all([
        api.getConnections().catch(() => []),
        api.listIntelligenceArtifacts(),
        api.listIntelligenceRuns(),
      ]);
      setConnections(connectionRows || []);
      setArtifacts(artifactRows || []);
      setRuns(runRows || []);

      const validArtifactIds = new Set((artifactRows || []).map((artifact) => artifact.id));
      const nextSelectedArtifactIds = preferredArtifactIds.length
        ? preferredArtifactIds.filter((id) => validArtifactIds.has(id))
        : selectedArtifactIds.filter((id) => validArtifactIds.has(id));
      setSelectedArtifactIds(nextSelectedArtifactIds);

      const nextArtifactId = pickExistingId(
        artifactRows || [],
        preferredArtifactId && validArtifactIds.has(preferredArtifactId) ? preferredArtifactId : selectedArtifactId,
      );
      if (nextArtifactId) await loadArtifact(nextArtifactId);
      else setArtifactDetail(null);

      const nextRunId = pickExistingId(runRows || [], preferredRunId || selectedRunId);
      if (nextRunId) {
        await loadRun(nextRunId);
      } else {
        setRunDetail(null);
        setRunSteps([]);
        setRunFindings([]);
        setSelectedRunId("");
      }

      const nextReportId = pickExistingReportId(runRows || [], nextRunId, preferredReportId || selectedReportId);
      if (nextReportId) await loadReport(nextReportId);
      else {
        setReportDetail(null);
        setReportPreview(null);
        setSelectedReportId("");
      }
    } catch (refreshError) {
      setError(getErrorMessage(refreshError));
    } finally {
      setLoading(false);
    }
  }, [loadArtifact, loadReport, loadRun, selectedArtifactId, selectedArtifactIds, selectedReportId, selectedRunId]);

  useEffect(() => {
    refresh();
    // Initial load only. Later refreshes are user-triggered or action-triggered.
  }, []);

  useEffect(() => {
    if (selectedRun?.report_id && selectedRun.report_id !== selectedReportId) {
      loadReport(selectedRun.report_id);
    }
  }, [loadReport, selectedReportId, selectedRun]);

  const uploadFiles = async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    const validationError = validateUploadFiles(files);
    if (validationError) {
      setError(validationError);
      event.target.value = "";
      return;
    }
    setBusy("upload");
    setError("");
    try {
      const uploadedIds = [];
      for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        const created = await api.uploadIntelligenceArtifact(formData);
        if (created?.id) uploadedIds.push(created.id);
      }
      await refresh({
        preferredArtifactId: uploadedIds[0] || "",
        preferredArtifactIds: [...selectedArtifactIds, ...uploadedIds],
      });
    } catch (uploadError) {
      setError(getErrorMessage(uploadError));
    } finally {
      event.target.value = "";
      setBusy("");
    }
  };

  const runIntelligence = async () => {
    if (!selectedArtifactIds.length) {
      setError("Select at least one uploaded artifact before starting a run.");
      return;
    }
    setBusy("run");
    setError("");
    try {
      const created = await api.createIntelligenceRun({
        selected_artifact_ids: selectedArtifactIds,
        source_connection_id: runDraft.source_connection_id || null,
        target_connection_id: runDraft.target_connection_id || null,
        agent_mode: runDraft.agent_mode || "deterministic_local",
      });
      await refresh({
        preferredRunId: created.id,
        preferredReportId: created.report_id || "",
        preferredArtifactIds: selectedArtifactIds,
      });
      setActiveTab("agent-runs");
    } catch (runError) {
      setError(getErrorMessage(runError));
    } finally {
      setBusy("");
    }
  };

  const downloadReport = async (format) => {
    const reportId = selectedReport?.id || selectedRun?.report_id || latestRun?.report_id;
    if (!reportId) {
      setError("No persisted report is available to download.");
      return;
    }
    setBusy(`download:${format}`);
    setError("");
    try {
      await api.downloadIntelligenceReport(reportId, format);
    } catch (downloadError) {
      setError(getErrorMessage(downloadError));
    } finally {
      setBusy("");
    }
  };

  const overviewCards = [
    { label: "Artifacts", value: artifacts.length },
    { label: "Runs", value: runs.length },
    { label: "Latest run", value: latestRun ? normalizeStatus(latestRun.status) : "No runs" },
    { label: "Latest report", value: selectedReport?.id ? "Available" : "Not generated" },
  ];

  const selectedRunDisclosure = disclosureRows(selectedRun);
  const sourceObjects = sourceObjectSummary(selectedReport);
  const replicationSignals = reportReplicationAssessment(selectedReport);
  const generatedCodeHint = hasGeneratedCodeRecommendation(selectedReport);
  const previewFlags = reportFlags(selectedReport, reportPreview);

  return (
    <div className="page pq-page agent-surface">
      <div className="page-header">
        <div className="page-header-copy">
          <div className="page-eyebrow">Migration Intelligence</div>
          <div className="page-title">Migration Intelligence</div>
          <div className="page-subtitle">Deterministic local heuristic analysis backed by `/api/intelligence`, persisted reports, and explicit no-execution disclosure.</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={refresh} disabled={loading || !!busy}>Refresh</button>
        </div>
      </div>

      <ErrorPanel error={error} />

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <button className={`btn ${activeTab === "overview" ? "btn-primary" : "btn-ghost"}`} onClick={() => setActiveTab("overview")}>Overview</button>
        <button className={`btn ${activeTab === "uploads" ? "btn-primary" : "btn-ghost"}`} onClick={() => setActiveTab("uploads")}>Uploads</button>
        <button className={`btn ${activeTab === "agent-runs" ? "btn-primary" : "btn-ghost"}`} onClick={() => setActiveTab("agent-runs")}>Agent Runs</button>
        <button className={`btn ${activeTab === "report-preview" ? "btn-primary" : "btn-ghost"}`} onClick={() => setActiveTab("report-preview")}>Report Preview</button>
        <button className={`btn ${activeTab === "codegen" ? "btn-primary" : "btn-ghost"}`} onClick={() => setActiveTab("codegen")}>Code Generation / Judge Pass</button>
      </div>

      {loading && !artifacts.length && !runs.length ? <LoadingPanel label="Loading Migration Intelligence" /> : null}

      {activeTab === "codegen" ? <CodeGenerationPanel /> : null}

      {activeTab === "overview" ? (
        <>
          <div className="pq-intel-grid">
            <div className="card" style={{ padding: 16 }}>
              <div className="settings-title">Current Surface</div>
              <div className="pq-kpi-grid">
                {overviewCards.map((card) => (
                  <div key={card.label} className="info-tile">
                    <div className="text-muted">{card.label}</div>
                    <div className="info-tile-value">{card.value}</div>
                  </div>
                ))}
              </div>
              <div className="helper-note" style={{ marginTop: 12 }}>
                Report content is generated from uploaded artifacts and UMA metadata only. This deterministic local heuristic flow does not execute uploaded SQL, generated SQL, generated code, DDL, or data movement.
              </div>
            </div>

            <div className="card" style={{ padding: 16 }}>
              <div className="settings-title">Honesty Guardrails</div>
              <ResultGrid
                columns={["statement", "status"]}
                rows={[
                  { statement: "Deterministic local heuristic run", status: "Yes" },
                  { statement: "No OpenAI/Cortex call unless configured", status: "Shown per run" },
                  { statement: "Uploaded SQL executed", status: "No" },
                  { statement: "Generated code executed", status: "No" },
                  { statement: "DDL/DML executed", status: "No" },
                  { statement: "Data moved", status: "No" },
                ]}
                emptyTitle="No disclosure rows"
              />
            </div>
          </div>

          <div className="pq-intel-grid mt4">
            <div className="card" style={{ padding: 16 }}>
              <div className="settings-title">Latest Run Disclosure</div>
              {!selectedRun ? (
                <EmptyState compact title="No run selected" message="Start a run from Uploads to populate persisted disclosure." />
              ) : (
                <ResultGrid columns={["action", "value"]} rows={selectedRunDisclosure} emptyTitle="No run disclosure" />
              )}
            </div>

            <div className="card" style={{ padding: 16 }}>
              <div className="settings-title">Latest Report Signals</div>
              {!selectedReport ? (
                <EmptyState compact title="No report generated" message="A report preview appears after a persisted intelligence run completes." />
              ) : (
                <ResultGrid
                  columns={["signal", "value"]}
                  rows={[
                    { signal: "Detected source objects", value: sourceObjects.length ? sourceObjects.join(", ") : "None detected" },
                    { signal: "Replication impact", value: replicationSignals.join(" | ") || "No replication impact statements persisted." },
                    { signal: "Code Generation recommendation", value: generatedCodeHint ? "Use Code Generation for reviewed DDL/code follow-up." : "No DDL/code recommendation detected." },
                  ]}
                  emptyTitle="No report signals"
                />
              )}
            </div>
          </div>
        </>
      ) : null}

      {activeTab === "uploads" ? (
        <div className="pq-master-detail">
          <div className="card pq-job-list">
            <div className="card-header">
              <div>
                <div className="card-title">Uploaded Artifacts</div>
                <div className="row-subtext">Upload `.sql`, `.txt`, `.md`, or text-based `.pdf` files for deterministic local heuristic analysis.</div>
              </div>
            </div>
            <div style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
              <label className="btn btn-primary" style={{ width: "100%", textAlign: "center", cursor: busy === "upload" ? "progress" : "pointer" }}>
                {busy === "upload" ? <span className="spin">↻</span> : "Upload artifacts"}
                <input
                  type="file"
                  accept=".sql,.txt,.md,.pdf"
                  multiple
                  onChange={uploadFiles}
                  disabled={busy === "upload"}
                  data-testid="artifact-upload-input"
                  style={{ display: "none" }}
                />
              </label>
              <div className="helper-note" style={{ marginTop: 8 }}>
                Supported types: `.sql`, `.txt`, `.md`, `.pdf`. Empty files are rejected. Max size: {Math.round(MAX_UPLOAD_BYTES / (1024 * 1024))} MB per file.
              </div>
            </div>
            {!artifacts.length ? <EmptyState title="No uploaded artifacts" message="Upload real source artifacts to start an intelligence run." /> : artifacts.map((artifact) => (
              <label key={artifact.id} className="pq-list-button" style={{ alignItems: "flex-start", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={selectedArtifactIds.includes(artifact.id)}
                    onChange={(event) => triggerSelection(setSelectedArtifactIds, artifact.id, event.target.checked)}
                  />
                  <button
                    className="btn btn-ghost btn-sm"
                    type="button"
                    onClick={() => loadArtifact(artifact.id)}
                    style={{ padding: 0, border: "none", background: "transparent" }}
                  >
                    {artifact.file_name}
                  </button>
                </div>
                <span>{artifact.file_type || artifact.mime_type || "unknown"} · {fmtBytes(artifact.size_bytes)}</span>
                <span>{artifact.classification || "UNCLASSIFIED"} · {artifact.language_guess || artifact.source_system_guess || "Unknown source"}</span>
                <span><StatusBadge status={artifact.extraction_status || "UNKNOWN"} label={artifact.extraction_status || "Unknown"} /></span>
              </label>
            ))}
          </div>

          <div className="pq-detail-panel">
            <div className="pq-detail-header">
              <div>
                <div className="pq-eyebrow">Uploads</div>
                <div className="pq-detail-title">{currentArtifact?.file_name || "Artifact detail"}</div>
                <div className="pq-detail-subtitle">Selection drives real `POST /api/intelligence/runs` requests using deterministic local heuristic processing.</div>
              </div>
            </div>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Run Selection</div>
              <div className="pq-kpi-grid">
                <div className="info-tile"><div className="text-muted">Selected artifacts</div><div className="info-tile-value">{selectedArtifactIds.length}</div></div>
                <div className="info-tile"><div className="text-muted">Agent mode</div><div className="info-tile-value">{runDraft.agent_mode}</div></div>
                <div className="info-tile"><div className="text-muted">Uploaded SQL executed</div><div className="info-tile-value">No</div></div>
                <div className="info-tile"><div className="text-muted">Data moved</div><div className="info-tile-value">No</div></div>
              </div>
              <div className="helper-note" style={{ marginTop: 12 }}>
                Deterministic local heuristic mode only. No OpenAI, Cortex, Snowflake SQL, uploaded SQL, or generated code execution is performed in this flow.
              </div>
              <div className="fr mt3">
                <div className="fg">
                  <label className="fl">Source Connection</label>
                  <select className="fi" value={runDraft.source_connection_id} onChange={(event) => setRunDraft((current) => ({ ...current, source_connection_id: event.target.value }))}>
                    <option value="">No source selected</option>
                    {sourceConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} ({connection.type})</option>)}
                  </select>
                </div>
                <div className="fg">
                  <label className="fl">Snowflake Connection</label>
                  <select className="fi" value={runDraft.target_connection_id} onChange={(event) => setRunDraft((current) => ({ ...current, target_connection_id: event.target.value }))}>
                    <option value="">No Snowflake selected</option>
                    {targetConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="fg mt3">
                <label className="fl">Agent Mode</label>
                <select className="fi" value={runDraft.agent_mode} onChange={(event) => setRunDraft((current) => ({ ...current, agent_mode: event.target.value }))}>
                  <option value="deterministic_local">deterministic_local</option>
                </select>
              </div>
              <button className="btn btn-primary mt3" onClick={runIntelligence} disabled={busy === "run" || !selectedArtifactIds.length} data-testid="run-intelligence-button">
                {busy === "run" ? <span className="spin">↻</span> : "Run intelligence"}
              </button>
            </section>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Artifact Detail</div>
              {!currentArtifact ? (
                <EmptyState compact title="Select an artifact" message="Artifact detail shows persisted extraction, classification, and preview fields from the backend." />
              ) : (
                <>
                  <ResultGrid
                    columns={["field", "value"]}
                    rows={[
                      { field: "File name", value: currentArtifact.file_name },
                      { field: "Type", value: currentArtifact.file_type || currentArtifact.mime_type || "Unknown" },
                      { field: "Size", value: fmtBytes(currentArtifact.size_bytes) },
                      { field: "Extraction status", value: currentArtifact.extraction_status || currentArtifact.extraction?.extraction_status || "Unknown" },
                      { field: "Classification", value: currentArtifact.classification || "Unknown" },
                      { field: "Language guess", value: currentArtifact.language_guess || "Unknown" },
                      { field: "Source system guess", value: currentArtifact.source_system_guess || "Unknown" },
                      { field: "Uploaded", value: fmtDate(currentArtifact.created_at) },
                    ]}
                    emptyTitle="No artifact detail"
                  />
                  <div className="pq-detail-section-title" style={{ marginTop: 16 }}>Extracted Text Preview</div>
                  <pre className="pq-code-block">{currentArtifact.extracted_text_preview || currentArtifact.extraction?.extracted_text_preview || currentArtifact.error_message || "No extracted text preview persisted."}</pre>
                  {currentArtifact.error_message ? <div className="helper-note run-error">Backend extraction error: {currentArtifact.error_message}</div> : null}
                  <div className="pq-detail-section-title" style={{ marginTop: 16 }}>Detected Chunks</div>
                  <ResultGrid
                    columns={["heading", "statement", "object"]}
                    rows={asList(currentArtifact.chunks).map((chunk) => ({
                      heading: chunk.heading || `Chunk ${chunk.chunk_index}`,
                      statement: chunk.statement_type || chunk.chunk_type || "Unknown",
                      object: chunk.object_name || "Not detected",
                    }))}
                    emptyTitle="No extracted chunks"
                    emptyMessage="Non-SQL artifacts may persist without chunk-level object extraction."
                  />
                </>
              )}
            </section>
          </div>
        </div>
      ) : null}

      {activeTab === "agent-runs" ? (
        <div className="pq-master-detail">
          <div className="card pq-job-list">
            <div className="card-header">
              <div>
                <div className="card-title">Run History</div>
                <div className="row-subtext">Persisted intelligence runs from `GET /api/intelligence/runs`.</div>
              </div>
            </div>
            {!runs.length ? <EmptyState title="No intelligence runs" message="Run intelligence from Uploads after selecting real artifacts." /> : runs.map((run) => (
              <button
                key={run.id}
                className="pq-list-button"
                onClick={() => loadRun(run.id)}
                style={{ background: selectedRun?.id === run.id ? "rgba(37,99,235,.08)" : undefined }}
              >
                <span>{normalizeStatus(run.status)} · {run.agent_mode || "deterministic_local"}</span>
                <span>{(run.selected_artifact_ids || []).length} artifact(s)</span>
                <span>{fmtDate(run.started_at)}</span>
              </button>
            ))}
          </div>

          <div className="pq-detail-panel">
            {!selectedRun ? (
              <EmptyState title="Select a run" message="Run detail shows persisted steps, findings, blockers, report linkage, and call disclosure." />
            ) : (
              <>
                <div className="pq-detail-header">
                    <div>
                      <div className="pq-eyebrow">Agent Run</div>
                      <div className="pq-detail-title">{selectedRun.id}</div>
                    <div className="pq-detail-subtitle">Deterministic local heuristic run detail backed by persisted intelligence records.</div>
                    </div>
                  <StatusBadge status={selectedRun.status} label={normalizeStatus(selectedRun.status)} />
                </div>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Run Summary</div>
                  <ResultGrid
                    columns={["field", "value"]}
                    rows={[
                      { field: "Run status", value: normalizeStatus(selectedRun.status) },
                      { field: "Agent mode", value: selectedRun.agent_mode || "deterministic_local" },
                      { field: "Started", value: fmtDate(selectedRun.started_at) },
                      { field: "Completed", value: fmtDate(selectedRun.completed_at) },
                      { field: "Selected artifacts", value: (selectedRun.selected_artifact_ids || []).map((id) => artifacts.find((artifact) => artifact.id === id)?.file_name || id).join(", ") || "None recorded" },
                      { field: "Latest error", value: selectedRun.latest_error || "None recorded" },
                      { field: "Report ID", value: selectedRun.report_id || "Not generated" },
                    ]}
                    emptyTitle="No run summary"
                  />
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Execution Disclosure</div>
                  <ResultGrid columns={["action", "value"]} rows={selectedRunDisclosure} emptyTitle="No disclosure" />
                  <div className="helper-note" style={{ marginTop: 12 }}>Uploaded SQL executed, generated code executed, DDL/DML executed, and data moved must remain `No` for this UI flow.</div>
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Step List</div>
                  <ResultGrid
                    columns={["sequence", "step", "status", "started", "completed", "error"]}
                    rows={runSteps.map((step) => ({
                      sequence: step.sequence,
                      step: step.step_name,
                      status: normalizeStatus(step.status),
                      started: fmtDate(step.started_at),
                      completed: fmtDate(step.completed_at),
                      error: step.error_message || "None",
                    }))}
                    emptyTitle="No run steps"
                  />
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Findings</div>
                  <ResultGrid
                    columns={["severity", "type", "title", "recommended_action"]}
                    rows={runFindings.map((finding) => ({
                      severity: formatFindingSeverity(finding.severity),
                      type: finding.finding_type,
                      title: finding.title,
                      recommended_action: finding.recommended_action || "No action recorded",
                    }))}
                    emptyTitle="No findings recorded"
                  />
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Blockers</div>
                  <ResultGrid
                    columns={["blocker", "evidence"]}
                    rows={runFindings.filter((finding) => finding.finding_type === "BLOCKER").map((finding) => ({
                      blocker: finding.title,
                      evidence: asList(finding.evidence).join(" | ") || finding.description || "No evidence recorded",
                    }))}
                    emptyTitle="No blockers recorded"
                  />
                </section>
              </>
            )}
          </div>
        </div>
      ) : null}

      {activeTab === "report-preview" ? (
        <div className="pq-master-detail">
          <div className="card pq-job-list">
            <div className="card-header">
              <div>
                <div className="card-title">Available Reports</div>
                <div className="row-subtext">Reports are sourced from persisted deterministic local heuristic output. No static report data is injected.</div>
              </div>
            </div>
            {!runs.filter((run) => run.report_id).length ? <EmptyState title="No reports generated" message="Complete an intelligence run to persist report content and downloads." /> : runs.filter((run) => run.report_id).map((run) => (
              <button
                key={run.id}
                className="pq-list-button"
                onClick={() => {
                  setSelectedRunId(run.id);
                  loadRun(run.id);
                  loadReport(run.report_id);
                }}
                style={{ background: selectedReportId === run.report_id ? "rgba(37,99,235,.08)" : undefined }}
              >
                <span>{run.report_id}</span>
                <span>{normalizeStatus(run.status)}</span>
                <span>{fmtDate(run.completed_at || run.started_at)}</span>
              </button>
            ))}
          </div>

          <div className="pq-detail-panel">
            {!selectedReport ? (
              <EmptyState title="Select a report" message="Report preview shows the latest persisted report sections and real download endpoints." />
            ) : (
              <>
                <div className="pq-detail-header">
                  <div>
                    <div className="pq-eyebrow">Report Preview</div>
                    <div className="pq-detail-title">{selectedReport.title || selectedReport.id}</div>
                    <div className="pq-detail-subtitle">Generated from uploaded artifacts and UMA metadata by a deterministic local heuristic pass. No uploaded SQL or generated code was executed.</div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <button className="btn btn-ghost" onClick={() => downloadReport("md")} disabled={!selectedReport?.id || busy === "download:md"}>{busy === "download:md" ? <span className="spin">↻</span> : "Download MD"}</button>
                    <button className="btn btn-ghost" onClick={() => downloadReport("pdf")} disabled={!selectedReport?.id || busy === "download:pdf"}>{busy === "download:pdf" ? <span className="spin">↻</span> : "Download PDF"}</button>
                    <button className="btn btn-primary" onClick={() => downloadReport("docx")} disabled={!selectedReport?.id || busy === "download:docx"} data-testid="download-docx-button">{busy === "download:docx" ? <span className="spin">↻</span> : "Download DOCX"}</button>
                  </div>
                </div>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Latest Report</div>
                  <ResultGrid
                    columns={["field", "value"]}
                    rows={[
                      { field: "Report ID", value: selectedReport.id },
                      { field: "Run ID", value: selectedReport.run_id },
                      { field: "Generated", value: fmtDate(selectedReport.created_at) },
                      { field: "OpenAI called", value: yesNo(previewFlags.openai_called) },
                      { field: "Snowflake Cortex called", value: yesNo(previewFlags.snowflake_cortex_called) },
                      { field: "Snowflake SQL executed", value: yesNo(previewFlags.snowflake_sql_executed) },
                      { field: "Uploaded SQL executed", value: "No" },
                      { field: "Generated code executed", value: "No" },
                      { field: "Data moved", value: "No" },
                    ]}
                    emptyTitle="No report summary"
                  />
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Product Connection</div>
                  <ResultGrid
                    columns={["field", "value"]}
                    rows={[
                      { field: "Detected source objects", value: sourceObjects.length ? sourceObjects.join(", ") : "None detected" },
                      { field: "Suggested replication impact", value: replicationSignals.join(" | ") || "No replication impact lines persisted." },
                      { field: "Suggested next action", value: "Create replication plan from report" },
                      { field: "Code Generation recommendation", value: generatedCodeHint ? "Use Code Generation for reviewed DDL/code follow-up." : "No DDL/code signal detected." },
                    ]}
                    emptyTitle="No product connection signals"
                  />
                  <button className="btn btn-ghost mt3" disabled>Create replication plan from report (coming later)</button>
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Report Sections</div>
                  <div style={{ display: "grid", gap: 12 }}>
                    {asList(selectedReport.report_json?.sections).map((section) => (
                      <details key={section.title} className="card" style={{ padding: 16 }} open={section.title === "Executive Summary"}>
                        <summary style={{ cursor: "pointer", fontWeight: 700 }}>{section.title}</summary>
                        <div style={{ marginTop: 12 }}>
                          <ResultGrid
                            columns={["line"]}
                            rows={asList(section.content).map((line) => ({ line }))}
                            emptyTitle={`No ${section.title} content`}
                          />
                        </div>
                      </details>
                    ))}
                  </div>
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Markdown Preview</div>
                  <pre className="pq-code-block">{reportPreview?.report_markdown || selectedReport.report_markdown || "No markdown preview persisted."}</pre>
                </section>

                <section className="pq-detail-section">
                  <div className="pq-detail-section-title">Quick Links</div>
                  <ResultGrid
                    columns={["section", "status"]}
                    rows={[
                      { section: "Executive Summary", status: sectionByTitle(selectedReport, "Executive Summary") ? "Present" : "Missing" },
                      { section: "Inputs Analyzed", status: sectionByTitle(selectedReport, "Inputs Analyzed") ? "Present" : "Missing" },
                      { section: "Findings", status: runFindings.length ? "Present via run findings" : "No run findings loaded" },
                      { section: "Recommendations", status: sectionByTitle(selectedReport, "Recommended Next Actions") ? "Present" : "Missing" },
                      { section: "TDD", status: sectionByTitle(selectedReport, "Technical Design Document") ? "Present" : "Missing" },
                      { section: "Judge Pass scaffold", status: sectionByTitle(selectedReport, "Judge Pass Review Scaffold") ? "Present" : "Missing" },
                      { section: "Appendix / Evidence", status: sectionByTitle(selectedReport, "Appendix: Evidence") ? "Present" : "Missing" },
                    ]}
                    emptyTitle="No quick links"
                  />
                </section>
              </>
            )}
          </div>
        </div>
      ) : null}

      {!["overview", "uploads", "agent-runs", "report-preview", "codegen"].includes(activeTab) ? <EmptyState title="Unknown tab" /> : null}
    </div>
  );
}
