import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api";
import EmptyState from "../components/EmptyState.jsx";
import ErrorPanel from "../components/ErrorPanel.jsx";
import LoadingPanel from "../components/LoadingPanel.jsx";
import ReplicationJobDetailPanel from "../components/ReplicationJobDetailPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { compactId, fmtDate, fmtNumber, getErrorMessage } from "../components/format.js";

export default function DataReplicationPage({ setPage = null }) {
  const [overview, setOverview] = useState(null);
  const [connections, setConnections] = useState([]);
  const [sources, setSources] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [runs, setRuns] = useState([]);
  const [readiness, setReadiness] = useState(null);
  const [umaRuns, setUmaRuns] = useState([]);
  const [selectedUmaRunId, setSelectedUmaRunId] = useState(() => (typeof window !== "undefined" ? window.localStorage.getItem("uma.selectedRunId") || "" : ""));
  const [selectedJobId, setSelectedJobId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedTables, setSelectedTables] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState({ plans: [] });
  const [selectedMapping, setSelectedMapping] = useState({ mappings: [] });
  const [selectedEvents, setSelectedEvents] = useState([]);
  const [selectedErrors, setSelectedErrors] = useState([]);
  const [runTables, setRunTables] = useState([]);
  const [runEvents, setRunEvents] = useState([]);
  const [search, setSearch] = useState("");
  const [activeKpi, setActiveKpi] = useState("jobs");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedJobId) || null, [jobs, selectedJobId]);
  const selectedUmaRun = useMemo(() => umaRuns.find((run) => run.id === selectedUmaRunId) || null, [umaRuns, selectedUmaRunId]);
  const selectedRun = useMemo(() => {
    const directRun = runs.find((run) => run.id === selectedRunId && (!selectedJobId || run.job_id === selectedJobId));
    return directRun || runs.find((run) => run.job_id === selectedJobId) || null;
  }, [runs, selectedRunId, selectedJobId]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [overviewResult, connectionRows, sourceRows, jobRows, runRows, readinessResult] = await Promise.all([
        api.getReplicationOverview().catch(() => null),
        api.getReplicationConnections().catch(() => []),
        api.getReplicationSources().catch(() => []),
        api.getReplicationJobs().catch(() => []),
        api.getReplicationRuns().catch(() => []),
        api.getReplicationSnowflakeReadiness().catch(() => null),
      ]);
      const runContextRows = await api.getControlPlaneRuns().catch(() => []);
      setOverview(overviewResult);
      setConnections(connectionRows || []);
      setSources(sourceRows || []);
      setJobs(jobRows || []);
      setRuns(runRows || []);
      setReadiness(readinessResult);
      setUmaRuns(runContextRows || []);
      if (!selectedUmaRunId && runContextRows?.length) setSelectedUmaRunId((typeof window !== "undefined" && window.localStorage.getItem("uma.selectedRunId")) || runContextRows[0].id);
      if (!selectedJobId && jobRows?.length) setSelectedJobId(jobRows[0].id);
      if (!selectedRunId && runRows?.length) setSelectedRunId(runRows[0].id);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [selectedJobId, selectedRunId, selectedUmaRunId]);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  useEffect(() => {
    if (!selectedJobId) return;
    let cancelled = false;
    Promise.all([
      api.getReplicationJobTables(selectedJobId).catch(() => []),
      api.getReplicationJobPlan(selectedJobId).catch(() => ({ plans: [] })),
      api.getReplicationJobMapping(selectedJobId).catch(() => ({ mappings: [] })),
      api.getReplicationJobEvents(selectedJobId).catch(() => []),
      api.getReplicationJobErrors(selectedJobId).catch(() => []),
    ]).then(([tables, plan, mapping, events, errors]) => {
      if (cancelled) return;
      setSelectedTables(tables || []);
      setSelectedPlan(plan || { plans: [] });
      setSelectedMapping(mapping || { mappings: [] });
      setSelectedEvents(events || []);
      setSelectedErrors(errors || []);
    });
    return () => { cancelled = true; };
  }, [selectedJobId]);

  useEffect(() => {
    if (!selectedRun?.id) {
      setRunTables([]);
      setRunEvents([]);
      return;
    }
    let cancelled = false;
    Promise.all([
      api.getReplicationRunTables(selectedRun.id).catch(() => []),
      api.getReplicationRunEvents(selectedRun.id).catch(() => []),
    ]).then(([tables, events]) => {
      if (cancelled) return;
      setRunTables(tables || []);
      setRunEvents(events || []);
    });
    return () => { cancelled = true; };
  }, [selectedRun?.id]);

  const jobAction = async (job, action) => {
    setBusy(`${action}:${job.id}`);
    setError("");
    try {
      if (action === "start") await api.startReplicationJob(job.id);
      if (action === "retry") await api.retryReplicationJob(job.id);
      if (action === "plan") await api.createReplicationJobPlan(job.id);
      await refreshAll();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setBusy("");
    }
  };

  const persistUmaRunSelection = (runId) => {
    setSelectedUmaRunId(runId);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("uma.selectedRunId", runId);
      window.dispatchEvent(new CustomEvent("uma:selected-run-changed", { detail: { runId } }));
    }
  };

  const linkSelectedJobToUmaRun = async () => {
    if (!selectedUmaRunId || !selectedJobId) return;
    setBusy(`link:${selectedJobId}`);
    setError("");
    try {
      await api.linkReplicationToRun(selectedUmaRunId, { job_id: selectedJobId, relationship: "replication_scope" });
      if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("uma:selected-run-changed", { detail: { runId: selectedUmaRunId } }));
      await refreshAll();
    } catch (linkError) {
      setError(getErrorMessage(linkError));
    } finally {
      setBusy("");
    }
  };

  const filteredJobs = jobs.filter((job) => {
    const haystack = [job.name, job.sync_mode, job.source_connection_name, job.destination_connection_name, job.status, job.latest_error].filter(Boolean).join(" ").toLowerCase();
    return !search.trim() || haystack.includes(search.toLowerCase());
  });

  const cards = [
    { id: "connections", label: "Connections", value: overview?.connection_count ?? connections.length, note: "replication endpoints" },
    { id: "jobs", label: "Jobs", value: overview?.job_count ?? jobs.length, note: "persisted definitions" },
    { id: "runs", label: "Runs", value: overview?.run_count ?? runs.length, note: "real execution records" },
    { id: "tables", label: "Selected Tables", value: overview?.selected_table_count ?? 0, note: overview?.planned_table_count ? `${overview.planned_table_count} planned strategies` : "no data movement claimed" },
    { id: "selected-job", label: "Selected job", value: selectedJob ? "Open" : "None", note: selectedJob?.status || "choose a job" },
    { id: "events", label: "Run events", value: runEvents.length, note: "latest timeline" },
  ];

  const drilldownTitle = {
    connections: "Replication endpoint details",
    jobs: "Replication job definitions",
    runs: "Execution run records",
    tables: "Selected table scope",
    "selected-job": "Selected job evidence",
    events: "Latest run events",
  }[activeKpi] || "Replication details";

  const renderKpiDrilldown = () => {
    if (activeKpi === "connections") {
      return (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Name</th><th>Connector</th><th>Role</th><th>Status</th><th>Latest error</th></tr></thead>
            <tbody>{connections.map((connection) => (
              <tr key={connection.id}>
                <td className="td-main">{connection.name}</td>
                <td>{connection.connector_type || connection.type}</td>
                <td>{connection.role || "not recorded"}</td>
                <td><StatusBadge status={connection.health?.status || connection.status || "UNKNOWN"} /></td>
                <td className={connection.latest_error || connection.health?.safe_error ? "run-error" : "text-muted"}>{connection.latest_error || connection.health?.safe_error || "None recorded"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      );
    }
    if (activeKpi === "runs") {
      return (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Run</th><th>Job</th><th>Status</th><th>Created</th><th>Tables</th></tr></thead>
            <tbody>{runs.map((run) => (
              <tr key={run.id} onClick={() => { setSelectedRunId(run.id); if (run.job_id) setSelectedJobId(run.job_id); }} style={{ cursor: "pointer" }}>
                <td className="td-mono">{compactId(run.id)}</td>
                <td>{jobs.find((job) => job.id === run.job_id)?.name || run.job_id || "Not recorded"}</td>
                <td><StatusBadge status={run.status || "UNKNOWN"} /></td>
                <td>{fmtDate(run.created_at || run.started_at)}</td>
                <td className="td-mono">{fmtNumber(run.planned_tables || run.table_count || 0)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      );
    }
    if (activeKpi === "tables") {
      return (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Table</th><th>Sync mode</th><th>Status</th><th>Last sync</th><th>Latest error</th></tr></thead>
            <tbody>{selectedTables.map((table) => (
              <tr key={table.id || `${table.schema_name}.${table.table_name}`}>
                <td className="td-main">{table.schema_name}.{table.table_name}</td>
                <td>{table.sync_mode || "not recorded"}</td>
                <td><StatusBadge status={table.status || "UNKNOWN"} /></td>
                <td>{fmtDate(table.last_sync_at)}</td>
                <td className={table.latest_error ? "run-error" : "text-muted"}>{table.latest_error || "None recorded"}</td>
              </tr>
            ))}</tbody>
          </table>
          {!selectedTables.length ? <EmptyState compact title="No selected tables for current job" message="Select a job with persisted table scope to inspect table-level status." /> : null}
        </div>
      );
    }
    if (activeKpi === "selected-job") {
      return selectedJob ? (
        <div className="pq-kpi-grid">
          <div className="info-tile"><div className="text-muted">Job</div><div className="info-tile-value">{selectedJob.name}</div></div>
          <div className="info-tile"><div className="text-muted">Status</div><div className="info-tile-value"><StatusBadge status={selectedJob.status} /></div></div>
          <div className="info-tile"><div className="text-muted">Source</div><div className="info-tile-value">{selectedJob.source_connection_name || "Not recorded"}</div></div>
          <div className="info-tile"><div className="text-muted">Target</div><div className="info-tile-value">{selectedJob.destination_connection_name || "Not recorded"}</div></div>
          <div className="info-tile"><div className="text-muted">Latest error</div><div className={selectedJob.latest_error ? "run-error info-tile-value" : "info-tile-value"}>{selectedJob.latest_error || "None recorded"}</div></div>
          <div className="info-tile"><div className="text-muted">Latest run</div><div className="info-tile-value">{selectedRun?.id ? compactId(selectedRun.id) : "No run"}</div></div>
        </div>
      ) : <EmptyState compact title="No selected job" message="Select a replication job to open job evidence." />;
    }
    if (activeKpi === "events") {
      const events = [...selectedEvents, ...runEvents];
      return (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Time</th><th>Phase</th><th>Status</th><th>Rows</th><th>Message</th></tr></thead>
            <tbody>{events.map((event, index) => (
              <tr key={`${event.id || `${event.created_at}-${event.event_type}`}-${index}`}>
                <td>{fmtDate(event.created_at || event.started_at || event.completed_at)}</td>
                <td>{event.event_type || event.phase || event.category || "Not recorded"}</td>
                <td><StatusBadge status={event.level || event.status || "INFO"} /></td>
                <td className="td-mono">{fmtNumber(event.rows || event.row_count || event.rows_loaded || 0)}</td>
                <td>{event.safe_error_message || event.error_message || event.message || "No message recorded"}</td>
              </tr>
            ))}</tbody>
          </table>
          {!events.length ? <EmptyState compact title="No run events" message="Events appear when a replication run or job emits timeline entries." /> : null}
        </div>
      );
    }
    return (
      <div className="table-scroll">
        <table>
          <thead><tr><th>Job</th><th>Mode</th><th>Status</th><th>Tables</th><th>Latest error</th></tr></thead>
          <tbody>{jobs.map((job) => (
            <tr key={job.id} onClick={() => { setSelectedJobId(job.id); const run = runs.find((item) => item.job_id === job.id); if (run) setSelectedRunId(run.id); }} style={{ cursor: "pointer" }}>
              <td className="td-main">{job.name}</td>
              <td>{job.sync_mode || "not recorded"}</td>
              <td><StatusBadge status={job.status || "UNKNOWN"} /></td>
              <td className="td-mono">{fmtNumber(job.table_count || 0)}</td>
              <td className={job.latest_error ? "run-error" : "text-muted"}>{job.latest_error || "None recorded"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="page pq-page">
      <div className="page-header">
        <div className="page-header-copy">
          <div className="page-eyebrow">Replication Control Plane</div>
          <div className="page-title">Data Replication</div>
          <div className="page-subtitle">Operational job details with explicit source/target, mappings, target readiness, events, latest errors, and run evidence.</div>
        </div>
        <div className="page-actions"><button className="btn btn-ghost" onClick={refreshAll}>Refresh</button></div>
      </div>

      <ErrorPanel error={error} />

      <div className="ep-list-panel" style={{ marginBottom: 12 }}>
        <div className="ep-list-head">
          <div>
            <div className="ep-list-title">Selected Migration Run Context</div>
            <div className="ep-list-subtitle">Replication evidence linked here appears on the canonical Migration Run Detail page.</div>
          </div>
          <StatusBadge status={selectedUmaRun?.status || "NO_RUN"} />
        </div>
        <div style={{ padding: 12, display: "grid", gridTemplateColumns: "minmax(220px,1fr) minmax(220px,1fr) auto auto", gap: 10, alignItems: "end" }}>
          <div className="fg">
            <label className="fl">Migration run</label>
            <select className="fi" value={selectedUmaRunId} onChange={(event) => persistUmaRunSelection(event.target.value)}>
              <option value="">Select canonical run...</option>
              {umaRuns.map((run) => <option key={run.id} value={run.id}>{run.name} · {run.status}</option>)}
            </select>
          </div>
          <div className="fg">
            <label className="fl">Selected replication job</label>
            <input className="fi" value={selectedJob ? `${selectedJob.name} · ${selectedJob.status}` : "Select a replication job"} readOnly />
          </div>
          <button className="btn btn-primary btn-sm" disabled={!selectedUmaRunId || !selectedJobId || busy.startsWith("link:")} onClick={linkSelectedJobToUmaRun}>
            {busy.startsWith("link:") ? "Linking" : "Link to Run Detail"}
          </button>
          <button className="btn btn-ghost btn-sm" disabled={!selectedUmaRunId || !setPage} onClick={() => setPage && setPage("run_detail")}>
            Open Run Detail
          </button>
        </div>
      </div>

      <div className={`ep-alert-strip ${selectedJob?.latest_error ? "has-blockers" : ""}`}>
        <div>
          <div className="ep-alert-kicker">Replication operations</div>
          <div className="ep-alert-title">{selectedJob?.latest_error || selectedJob ? `Selected job: ${selectedJob.name}` : "Select a replication job to inspect timeline, errors, and table-level state."}</div>
        </div>
        <div className="ep-alert-items">
          <button className="ep-alert-item" disabled={!selectedJob} onClick={() => selectedJob && jobAction(selectedJob, "plan")}><StatusBadge status="PLAN_ONLY" /><span>Generate plan</span></button>
          <button className="ep-alert-item" disabled={!selectedJob} onClick={() => selectedJob && jobAction(selectedJob, "start")}><StatusBadge status="READY" /><span>Start</span></button>
          <button className="ep-alert-item" disabled={!selectedJob} onClick={() => selectedJob && jobAction(selectedJob, "retry")}><StatusBadge status="RETRY" /><span>Retry</span></button>
        </div>
      </div>

      <div className="ep-kpi-row">
        {cards.map((card) => (
          <button className={`ep-kpi ${activeKpi === card.id ? "active" : ""}`} type="button" key={card.id} onClick={() => setActiveKpi(card.id)}>
            <div className="ep-kpi-label">{card.label}</div>
            <div className="ep-kpi-value">{fmtNumber(card.value)}</div>
            <div className="ep-kpi-note">{card.note}</div>
          </button>
        ))}
      </div>

      <div className="ep-list-panel" style={{ marginBottom: 12 }}>
        <div className="ep-list-head">
          <div>
            <div className="ep-list-title">{drilldownTitle}</div>
            <div className="ep-list-subtitle">Opened from the KPI strip. Select rows where available to update the job/run detail panel.</div>
          </div>
          <StatusBadge status={activeKpi === "connections" && readiness?.status ? readiness.status : selectedJob?.status || "OPEN"} />
        </div>
        <div style={{ padding: 12 }}>
          {renderKpiDrilldown()}
        </div>
      </div>

      <div className="ep-workspace wide-detail">
        <div className="ep-list-panel pq-job-list">
          <div className="ep-list-head">
            <div>
              <div className="ep-list-title">Replication jobs</div>
              <div className="ep-list-subtitle">Click a job to inspect execution timeline, table-level status, latest error, and fix actions.</div>
            </div>
          </div>
          <div className="ep-split-toolbar">
            <div className="sw"><span className="si">⌕</span><input placeholder="Search jobs, connections, status, or errors" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
          </div>
          {loading ? <LoadingPanel label="Loading replication jobs" /> : !filteredJobs.length ? (
            <EmptyState title="No replication jobs" message={jobs.length ? "No jobs match the current search." : "Create or discover replication jobs to populate this control plane."} />
          ) : (
            <div className="table-scroll sync-profiles-table">
              <table>
                <thead><tr><th>Job</th><th>Mode</th><th>Status</th><th>Tables</th><th>Latest Run</th></tr></thead>
                <tbody>
                  {filteredJobs.map((job) => (
                    <tr key={job.id} className={selectedJobId === job.id ? "is-selected" : ""} onClick={() => { setSelectedJobId(job.id); const run = runs.find((item) => item.job_id === job.id); if (run) setSelectedRunId(run.id); }} style={{ cursor: "pointer" }}>
                      <td><div className="td-main">{job.name}</div><div className="row-subtext">{job.source_connection_name || "source"} → {job.destination_connection_name || "target"}</div></td>
                      <td>{job.sync_mode}</td>
                      <td><StatusBadge status={job.status || "UNKNOWN"} /></td>
                      <td className="td-mono">{fmtNumber(job.table_count || 0)}</td>
                      <td><div className="td-mono" style={{ fontSize: 10 }}>{job.latest_run?.id ? compactId(job.latest_run.id) : "No run"}</div><div className="row-subtext">{fmtDate(job.last_sync_at)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="pq-side-section">
            <div className="pq-detail-section-title">Connections & Readiness</div>
            <div className="pq-kpi-grid">
              <div className="info-tile"><div className="text-muted">Sources</div><div className="info-tile-value">{fmtNumber(sources.length)}</div></div>
              <div className="info-tile"><div className="text-muted">Endpoints</div><div className="info-tile-value">{fmtNumber(connections.length)}</div></div>
              <div className="info-tile"><div className="text-muted">Snowflake Readiness</div><div className="info-tile-value">{readiness?.status || "NOT_CHECKED"}</div></div>
              <div className="info-tile"><div className="text-muted">Readiness Message</div><div className="info-tile-value">{readiness?.message || "No readiness check recorded."}</div></div>
            </div>
          </div>
        </div>

        <ReplicationJobDetailPanel
          job={selectedJob}
          selectedTables={selectedTables}
          plan={selectedPlan}
          mapping={selectedMapping}
          events={selectedEvents}
          errors={selectedErrors}
          latestRun={selectedRun}
          runTables={runTables}
          runEvents={runEvents}
          onPlan={() => selectedJob && jobAction(selectedJob, "plan")}
          onStart={() => selectedJob && jobAction(selectedJob, "start")}
          onRetry={() => selectedJob && jobAction(selectedJob, "retry")}
          busy={busy}
        />
      </div>
    </div>
  );
}
