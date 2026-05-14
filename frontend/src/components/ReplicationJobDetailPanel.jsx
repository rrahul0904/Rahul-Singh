import React from "react";
import EmptyState from "./EmptyState.jsx";
import ResultGrid from "./ResultGrid.jsx";
import StatusBadge from "./StatusBadge.jsx";
import { fmtDate, fmtNumber } from "./format.js";

function value(...items) {
  return items.find((item) => item !== undefined && item !== null && item !== "") ?? "Not recorded";
}

export default function ReplicationJobDetailPanel({
  job,
  selectedTables = [],
  plan = { plans: [] },
  mapping = { mappings: [] },
  events = [],
  errors = [],
  latestRun = null,
  runTables = [],
  runEvents = [],
  onPlan,
  onStart,
  onRetry,
  busy = "",
}) {
  if (!job) {
    return <div className="pq-detail-panel"><EmptyState title="Select a replication job" message="Job detail shows source, target, selected tables, mapping, plan, latest run, errors, events, and retry controls." /></div>;
  }

  const plans = plan?.plans || [];
  const mappings = mapping?.mappings || [];
  const createPlanRows = plans.map((item) => ({
    table: `${value(item.source_schema)}.${value(item.source_object)}`,
    target: `${value(item.target_database)}.${value(item.target_schema)}.${value(item.target_object)}`,
    load_mode: value(item.load_mode),
    write_mode: value(item.write_mode),
    primary_key: (item.primary_key_columns || []).join(", ") || "Not recorded",
    watermark: value(item.watermark_column),
    target_exists: value(item.target_exists, item.target_status),
    create_on_first_run: value(item.create_on_first_run, item.create_table_sql ? "Planned" : "Not recorded"),
  }));

  return (
    <div className="pq-detail-panel">
      <div className="pq-detail-header">
        <div>
          <div className="pq-eyebrow">Replication Job Detail</div>
          <div className="pq-detail-title">{job.name}</div>
          <div className="pq-detail-subtitle">{value(job.source_connection_name, "source")} → {value(job.destination_connection_name, "target")}</div>
        </div>
        <StatusBadge status={job.status || "UNKNOWN"} />
      </div>

      <div className="pq-action-row">
        <button className="btn btn-ghost btn-sm" onClick={onPlan} disabled={busy === `plan:${job.id}`}>{busy === `plan:${job.id}` ? <span className="spin">↻</span> : "Plan strategy"}</button>
        <button className="btn btn-primary btn-sm" onClick={onStart} disabled={busy === `start:${job.id}`}>{busy === `start:${job.id}` ? <span className="spin">↻</span> : "Start planned run"}</button>
        <button className="btn btn-ghost btn-sm" onClick={onRetry} disabled={busy === `retry:${job.id}`}>{busy === `retry:${job.id}` ? <span className="spin">↻</span> : "Retry"}</button>
      </div>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Overview</div>
        <div className="pq-kpi-grid">
          <div className="info-tile"><div className="text-muted">Source Connection</div><div className="info-tile-value">{value(job.source_connection_name)}</div></div>
          <div className="info-tile"><div className="text-muted">Target Connection</div><div className="info-tile-value">{value(job.destination_connection_name)}</div></div>
          <div className="info-tile"><div className="text-muted">Load Mode</div><div className="info-tile-value">{value(job.sync_mode)}</div></div>
          <div className="info-tile"><div className="text-muted">Write Mode</div><div className="info-tile-value">{value(job.write_mode, plans[0]?.write_mode)}</div></div>
          <div className="info-tile"><div className="text-muted">Selected Tables</div><div className="info-tile-value">{fmtNumber(job.table_count || selectedTables.length || 0)}</div></div>
          <div className="info-tile"><div className="text-muted">Latest Error</div><div className={job.latest_error ? "run-error info-tile-value" : "info-tile-value"}>{job.latest_error || "None recorded"}</div></div>
        </div>
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Selected Schemas/Tables</div>
        <ResultGrid
          columns={["table", "sync_mode", "status", "last_sync", "latest_error"]}
          rows={selectedTables.map((table) => ({
            table: `${table.schema_name}.${table.table_name}`,
            sync_mode: value(table.sync_mode),
            status: value(table.status),
            last_sync: fmtDate(table.last_sync_at),
            latest_error: table.latest_error || "None recorded",
          }))}
          emptyTitle="No tables selected"
          emptyMessage="Selected schemas and tables are required before a replication plan can be trusted."
        />
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Table Mapping</div>
        <ResultGrid
          columns={["source_table", "target_table", "columns", "primary_key", "watermark", "target_exists"]}
          rows={mappings.map((item) => ({
            source_table: `${value(item.source_schema)}.${value(item.source_table)}`,
            target_table: `${value(item.target_schema)}.${value(item.target_table)}`,
            columns: fmtNumber(item.column_mapping?.length || 0),
            primary_key: (item.primary_key_columns || []).join(", ") || "Not recorded",
            watermark: value(item.watermark_column),
            target_exists: value(item.target_exists),
          }))}
          emptyTitle="No mapping metadata"
          emptyMessage="Mapping details will appear when the API returns persisted source-to-target mapping records."
        />
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Column Mapping</div>
        <ResultGrid
          columns={["table", "source_column", "target_column", "transform"]}
          rows={mappings.flatMap((item) => (item.column_mapping || []).map((column) => ({
            table: `${value(item.source_schema)}.${value(item.source_table)}`,
            source_column: value(column.source_column, column.source),
            target_column: value(column.target_column, column.target),
            transform: value(column.transform, column.expression, "Direct"),
          })))}
          emptyTitle="No column mapping persisted"
        />
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Primary Key / Watermark / Create-On-First-Run Plan</div>
        <ResultGrid
          columns={["table", "target", "load_mode", "write_mode", "primary_key", "watermark", "target_exists", "create_on_first_run"]}
          rows={createPlanRows}
          emptyTitle="No table-level strategy"
          emptyMessage="Use Plan strategy to derive target existence, create-on-first-run, key, watermark, load, and write mode details from real metadata."
        />
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Latest Run</div>
        {latestRun ? (
          <div className="pq-kpi-grid">
            <div className="info-tile"><div className="text-muted">Run</div><div className="info-tile-value font-mono">{value(latestRun.id)}</div></div>
            <div className="info-tile"><div className="text-muted">Status</div><div className="info-tile-value"><StatusBadge status={latestRun.status} /></div></div>
            <div className="info-tile"><div className="text-muted">Planned Tables</div><div className="info-tile-value">{fmtNumber(latestRun.planned_tables || runTables.length || 0)}</div></div>
            <div className="info-tile"><div className="text-muted">Created</div><div className="info-tile-value font-mono" style={{ fontSize: 11 }}>{fmtDate(latestRun.created_at)}</div></div>
          </div>
        ) : (
          <EmptyState compact title="No real execution record" message="UMA is not claiming data moved for this job until a replication run record exists." />
        )}
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Execution Timeline</div>
        <ResultGrid
          columns={["timestamp", "phase", "status", "duration", "rows", "bytes", "error", "retry"]}
          rows={[...events, ...runEvents].slice(0, 20).map((event) => ({
            timestamp: fmtDate(event.created_at || event.started_at || event.completed_at),
            phase: value(event.event_type, event.category, event.phase),
            status: value(event.level, event.status),
            duration: event.duration_ms ? `${fmtNumber(event.duration_ms)} ms` : value(event.duration_seconds ? `${event.duration_seconds}s` : ""),
            rows: fmtNumber(event.rows || event.row_count || event.rows_loaded || 0),
            bytes: fmtNumber(event.bytes || event.bytes_loaded || event.size_bytes || 0),
            error: value(event.safe_error_message, event.error_message, event.message),
            retry: event.retryable === true ? "Retry available" : event.retry_count ? `${event.retry_count} retries` : "—",
          }))}
          emptyTitle="No timeline events recorded"
          emptyMessage="Replication events will show timestamp, phase, status, rows, bytes, errors, and retry signals once a run starts."
        />
        <div className="mt3">
          <ResultGrid
            columns={["table", "status", "latest_error"]}
            rows={runTables.map((table) => ({
              table: `${table.schema_name}.${table.table_name}`,
              status: value(table.status),
              latest_error: table.latest_error || "None recorded",
            }))}
            emptyTitle="No table run records"
          />
        </div>
      </section>

      <section className="pq-detail-section">
        <div className="pq-detail-section-title">Latest Errors</div>
        <ResultGrid
          columns={["time", "stage", "message", "recommended_action"]}
          rows={errors.map((error) => ({
            time: fmtDate(error.created_at),
            stage: value(error.category, error.event_type),
            message: value(error.safe_error_message, error.message),
            recommended_action: value(error.recommended_action, String(error.safe_error_message || error.message || "").toLowerCase().includes("schema") ? "Open target connection settings and confirm database/schema permissions." : "Review connection, table mapping, and latest event context."),
          }))}
          emptyTitle="No latest errors"
        />
      </section>
    </div>
  );
}
