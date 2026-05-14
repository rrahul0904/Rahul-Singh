import React from "react";
import EmptyState from "./EmptyState.jsx";
import ResultGrid from "./ResultGrid.jsx";
import StatusBadge from "./StatusBadge.jsx";
import { asArray, fmtBytes, fmtDate, fmtNumber } from "./format.js";

function value(...items) {
  return items.find((item) => item !== undefined && item !== null && item !== "") ?? "Not recorded";
}

function safeJson(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function Section({ title, children }) {
  return (
    <section className="pq-detail-section">
      <div className="pq-detail-section-title">{title}</div>
      {children}
    </section>
  );
}

export default function CatalogTableDetailPanel({ table, detail, columns = [], runs = [], lineage = null, loading = false }) {
  if (!table) {
    return (
      <div className="pq-detail-panel">
        <EmptyState title="Select a table" message="Click a catalog row to open overview, columns, mapping, runs, errors, lineage, DDL, and drift details." />
      </div>
    );
  }

  const record = detail || table;
  const columnRows = asArray(columns, asArray(record.columns));
  const runRows = asArray(runs, asArray(record.latest_runs, asArray(record.runs)));
  const mappingRows = asArray(record.source_to_target_mapping, asArray(record.mappings));
  const errorRows = asArray(record.latest_errors, asArray(record.errors)).filter(Boolean);
  const lineageRows = asArray(lineage, asArray(lineage?.items, asArray(record.lineage)));
  const ddl = value(record.generated_ddl, record.ddl, record.snowflake_ddl, "");
  const drift = value(record.schema_drift, record.drift, "");

  return (
    <div className="pq-detail-panel">
      <div className="pq-detail-header">
        <div>
          <div className="pq-eyebrow">Catalog Table Detail</div>
          <div className="pq-detail-title">{value(record.schema, record.source_schema)}.{value(record.table, record.table_name, record.source_table)}</div>
          <div className="pq-detail-subtitle">{value(record.target_schema)}.{value(record.target_table)} · {fmtNumber(value(record.estimated_rows, record.row_count, 0))} rows · {fmtBytes(value(record.estimated_bytes, record.bytes, 0))}</div>
        </div>
        <StatusBadge status={value(record.latest_migration_status, record.latest_replication_status, record.status, "UNKNOWN")} />
      </div>

      {loading && <div className="text-muted mb3">Loading latest catalog detail...</div>}

      <Section title="Overview">
        <div className="pq-kpi-grid">
          <div className="info-tile"><div className="text-muted">Source</div><div className="info-tile-value">{value(record.source_connection_name, record.source_system, record.source_type)}</div></div>
          <div className="info-tile"><div className="text-muted">Target</div><div className="info-tile-value">{value(record.target_connection_name, record.target_database, "Snowflake")}</div></div>
          <div className="info-tile"><div className="text-muted">Columns</div><div className="info-tile-value">{fmtNumber(value(record.column_count, columnRows.length, 0))}</div></div>
          <div className="info-tile"><div className="text-muted">Latest Sync</div><div className="info-tile-value font-mono" style={{ fontSize: 11 }}>{fmtDate(value(record.last_sync_at, record.latest_run_at, record.updated_at, ""))}</div></div>
        </div>
      </Section>

      <Section title="Columns">
        <ResultGrid
          columns={["name", "type", "nullable", "ordinal_position"]}
          rows={columnRows.map((column, index) => ({
            name: value(column.name, column.column_name),
            type: value(column.type, column.data_type),
            nullable: value(column.nullable, column.is_nullable, "Not recorded"),
            ordinal_position: value(column.ordinal_position, column.position, index + 1),
          }))}
          emptyTitle="No column metadata"
          emptyMessage="Column records have not been persisted for this table."
        />
      </Section>

      <Section title="Source-To-Target Mapping">
        <ResultGrid
          columns={["source", "target", "transform", "notes"]}
          rows={mappingRows.map((mapping) => ({
            source: value(mapping.source_column, mapping.source, `${value(record.schema, record.source_schema)}.${value(record.table, record.table_name)}`),
            target: value(mapping.target_column, mapping.target, `${value(record.target_schema)}.${value(record.target_table)}`),
            transform: value(mapping.transform, mapping.expression, "Direct"),
            notes: value(mapping.notes, mapping.reason, "API-backed mapping record"),
          }))}
          emptyTitle="No mapping persisted"
          emptyMessage="No source-to-target mapping record is available for this table."
        />
      </Section>

      <Section title="Latest Runs">
        <ResultGrid
          columns={["run", "status", "rows", "started", "finished"]}
          rows={runRows.map((run) => ({
            run: value(run.id, run.run_id),
            status: value(run.status),
            rows: fmtNumber(value(run.rows_loaded, run.row_count, 0)),
            started: fmtDate(value(run.started_at, run.created_at, "")),
            finished: fmtDate(value(run.finished_at, run.completed_at, "")),
          }))}
          emptyTitle="No execution run recorded"
          emptyMessage="UMA is not claiming data movement for this table until a real run record exists."
        />
      </Section>

      <Section title="Latest Errors">
        <ResultGrid
          columns={["time", "stage", "message", "recommended_action"]}
          rows={errorRows.map((item) => ({
            time: fmtDate(value(item.created_at, item.time, "")),
            stage: value(item.category, item.stage, item.event_type),
            message: value(item.safe_error_message, item.message, item.error),
            recommended_action: value(item.recommended_action, "Review catalog and run logs."),
          }))}
          emptyTitle="No latest errors"
          emptyMessage="No persisted error records are attached to this catalog table."
        />
      </Section>

      <Section title="Lineage">
        <ResultGrid
          columns={["from", "relation", "to"]}
          rows={lineageRows.map((item) => ({
            from: value(item.from, item.source, item.source_object),
            relation: value(item.relation, item.kind, "feeds"),
            to: value(item.to, item.target, item.target_object),
          }))}
          emptyTitle="No lineage persisted"
          emptyMessage="Lineage will appear when API records source, job, and target relationships."
        />
      </Section>

      <Section title="Generated DDL">
        {ddl ? (
          <pre className="pq-code-block">{ddl}</pre>
        ) : (
          <EmptyState compact title="No generated DDL available" message="No persisted DDL artifact is attached to this table." />
        )}
      </Section>

      <Section title="Schema Drift">
        {drift && drift !== "Not recorded" ? (
          <pre className="pq-code-block">{safeJson(drift)}</pre>
        ) : (
          <EmptyState compact title="No drift result available" message="Schema drift has not been checked or persisted for this table." />
        )}
      </Section>
    </div>
  );
}
