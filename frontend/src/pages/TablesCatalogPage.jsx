import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api";
import CatalogTableDetailPanel from "../components/CatalogTableDetailPanel.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorPanel from "../components/ErrorPanel.jsx";
import LoadingPanel from "../components/LoadingPanel.jsx";
import ResultGrid from "../components/ResultGrid.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { fmtBytes, fmtDate, fmtNumber, getErrorMessage } from "../components/format.js";

function tableId(table) {
  return table.id || table.catalog_id || table.table_id || `${table.schema || table.source_schema || ""}.${table.table || table.table_name || table.source_table || ""}`;
}

export default function TablesCatalogPage({ setPage = null }) {
  const [search, setSearch] = useState("");
  const [connection, setConnection] = useState("");
  const [database, setDatabase] = useState("");
  const [schema, setSchema] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("schema");
  const [summary, setSummary] = useState(null);
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [columns, setColumns] = useState([]);
  const [runs, setRuns] = useState([]);
  const [lineage, setLineage] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summaryResult, tableResult] = await Promise.all([
        api.getCatalogSummary().catch(() => null),
        api.getCatalogTables({ search, schema, status, sort, page_size: 100 }),
      ]);
      setSummary(summaryResult);
      setTables(tableResult.items || tableResult || []);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [search, schema, status, sort]);

  useEffect(() => { loadCatalog(); }, [loadCatalog]);

  const connections = useMemo(() => {
    const values = new Set(tables.map((table) => table.source_connection_name || table.connection_name || table.source_type).filter(Boolean));
    return Array.from(values).sort();
  }, [tables]);

  const databases = useMemo(() => {
    const values = new Set(tables.map((table) => table.database || table.source_database || table.target_database).filter(Boolean));
    return Array.from(values).sort();
  }, [tables]);

  const schemas = useMemo(() => {
    const values = new Set(tables.map((table) => table.schema || table.source_schema).filter(Boolean));
    return Array.from(values).sort();
  }, [tables]);

  const visibleTables = useMemo(() => tables.filter((table) => {
    const tableConnection = table.source_connection_name || table.connection_name || table.source_type || "";
    const tableDatabase = table.database || table.source_database || table.target_database || "";
    return (!connection || tableConnection === connection) && (!database || tableDatabase === database);
  }), [tables, connection, database]);
  const tableAttentionRows = useMemo(() => {
    const failed = visibleTables.filter((table) => ["FAILED", "ERROR", "BLOCKED"].includes(String(table.latest_migration_status || table.latest_replication_status || table.status || "").toUpperCase()));
    const unmapped = visibleTables.filter((table) => !(table.target_table || table.target_schema));
    const noSchema = visibleTables.filter((table) => !(table.column_count || table.columns?.length));
    const noRun = visibleTables.filter((table) => !(table.last_sync_at || table.latest_run_at || table.latest_migration_status || table.latest_replication_status));
    return [
      ...failed.slice(0, 4).map((table) => ({ ...table, issue: "Failed latest run", action: "Open errors and retry after fixing mapping/connection" })),
      ...unmapped.slice(0, 4).map((table) => ({ ...table, issue: "Unmapped target", action: "Create or confirm source-to-target mapping" })),
      ...noSchema.slice(0, 4).map((table) => ({ ...table, issue: "No schema metadata", action: "Run discovery or refresh catalog metadata" })),
      ...noRun.slice(0, 4).map((table) => ({ ...table, issue: "No latest run", action: "Attach to replication or migration job" })),
    ].filter((row, index, all) => all.findIndex((item) => tableId(item) === tableId(row) && item.issue === row.issue) === index).slice(0, 8);
  }, [visibleTables]);

  const openDetail = async (table) => {
    setSelected(table);
    setDetail(table);
    setColumns([]);
    setRuns([]);
    setLineage(null);
    setDetailLoading(true);
    const id = tableId(table);
    try {
      const [detailResult, columnResult, runResult, lineageResult] = await Promise.all([
        api.getCatalogTable(id).catch(() => table),
        api.getCatalogColumns(id).catch(() => []),
        api.getCatalogRuns(id).catch(() => []),
        api.getCatalogLineage(id).catch(() => null),
      ]);
      setDetail(detailResult);
      setColumns(columnResult.items || columnResult.columns || columnResult || []);
      setRuns(runResult.items || runResult.runs || runResult || []);
      setLineage(lineageResult);
    } catch (detailError) {
      setError(getErrorMessage(detailError));
    } finally {
      setDetailLoading(false);
    }
  };

  const cards = [
    ["Total Tables", summary?.total_tables ?? 0, "API catalog inventory", "var(--accent)", ""],
    ["Succeeded", summary?.succeeded ?? 0, "Tables with successful latest run", "var(--green)", "SUCCEEDED"],
    ["Running", summary?.running ?? 0, "Tables with active latest run", "var(--orange)", "RUNNING"],
    ["Failed", summary?.failed ?? 0, "Tables needing operator review", "var(--red)", "FAILED"],
  ];

  return (
    <div className="page pq-page">
      <div className="page-header">
        <div className="page-header-copy">
          <div className="page-eyebrow">Live Catalog</div>
          <div className="page-title">Tables Catalog</div>
          <div className="page-subtitle">API-backed inventory for table health, mappings, latest runs, errors, lineage, generated DDL, and drift signals.</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-ghost" onClick={loadCatalog}>Refresh</button>
        </div>
      </div>

      <ErrorPanel error={error} />

      <div className="stats-grid pq-command-cards">
        {cards.map(([label, value, note, color, nextStatus]) => (
          <button className={`stat-card is-clickable ${status === nextStatus ? "active" : ""}`} type="button" key={label} style={{ "--al": color }} onClick={() => setStatus(nextStatus)}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{fmtNumber(value)}</div>
            <div className="stat-change">{note}</div>
          </button>
        ))}
      </div>

      <div className="pq-master-detail">
        <div className="tables-surface pq-catalog-list">
          <div className="tables-toolbar">
            <div className="sw">
              <span className="si">⌕</span>
              <input placeholder="Search tables, schemas, targets, or errors" value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>
            <select value={connection} onChange={(event) => setConnection(event.target.value)}>
              <option value="">All connections</option>
              {connections.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <select value={database} onChange={(event) => setDatabase(event.target.value)}>
              <option value="">All databases</option>
              {databases.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <select value={schema} onChange={(event) => setSchema(event.target.value)}>
              <option value="">All schemas</option>
              {schemas.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">All statuses</option>
              <option value="SUCCEEDED">Succeeded</option>
              <option value="RUNNING">Running</option>
              <option value="FAILED">Failed</option>
              <option value="PENDING">Pending</option>
            </select>
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="schema">Schema</option>
              <option value="table">Table</option>
              <option value="-last_sync_time">Last Sync</option>
              <option value="-estimated_bytes">Estimated Size</option>
            </select>
          </div>
          {loading ? <LoadingPanel label="Loading catalog" /> : !visibleTables.length ? (
            <EmptyState
              title="No tables discovered"
              message="Run metadata discovery from a configured source connection to populate the live catalog."
              action={setPage ? (
                <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage("replication_plan")}>Run metadata discovery</button>
                  <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("connections")}>Configure connection</button>
                </div>
              ) : null}
            />
          ) : (
            <div className="table-scroll tables-table">
              <table>
                <thead>
                  <tr><th>Source Table</th><th>Target</th><th>Columns</th><th>Rows</th><th>Size</th><th>Status</th><th>Latest Sync</th><th>Latest Error</th></tr>
                </thead>
                <tbody>
                  {visibleTables.map((table) => {
                    const id = tableId(table);
                    const active = tableId(selected || {}) === id;
                    return (
                      <tr key={id} className={active ? "is-selected" : ""} onClick={() => openDetail(table)} style={{ cursor: "pointer" }}>
                        <td>
                          <div className="td-main">{table.schema || table.source_schema || "unknown"}.{table.table || table.table_name || table.source_table || "table"}</div>
                          <div className="row-subtext">{table.source_connection_name || table.source_type || "source metadata"}</div>
                        </td>
                        <td className="td-mono">{table.target_schema || "target"}.{table.target_table || table.table || table.table_name || "table"}</td>
                        <td className="td-mono">{fmtNumber(table.column_count || 0)}</td>
                        <td className="td-mono">{fmtNumber(table.estimated_rows || table.row_count || 0)}</td>
                        <td className="td-mono">{fmtBytes(table.estimated_bytes || table.bytes || 0)}</td>
                        <td><StatusBadge status={table.latest_migration_status || table.latest_replication_status || table.status || "UNKNOWN"} /></td>
                        <td className="td-mono" style={{ fontSize: 10 }}>{fmtDate(table.last_sync_at || table.latest_run_at)}</td>
                        <td className={table.latest_error ? "run-error" : "text-muted"}>{table.latest_error || "None recorded"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {selected ? (
          <CatalogTableDetailPanel table={selected} detail={detail} columns={columns} runs={runs} lineage={lineage} loading={detailLoading} />
        ) : (
          <div className="pq-detail-panel">
            <div className="pq-detail-header">
              <div>
                <div className="pq-eyebrow">Catalog Attention</div>
                <div className="pq-detail-title">Tables needing review</div>
                <div className="pq-detail-subtitle">Failed, unmapped, schema-missing, and no-run tables appear here before a row is selected.</div>
              </div>
            </div>
            <ResultGrid
              columns={["table", "issue", "status", "latest_error", "action"]}
              rows={tableAttentionRows.map((table) => ({
                table: `${table.schema || table.source_schema || "unknown"}.${table.table || table.table_name || table.source_table || "table"}`,
                issue: table.issue,
                status: table.latest_migration_status || table.latest_replication_status || table.status || "UNKNOWN",
                latest_error: table.latest_error || "None recorded",
                action: table.action,
              }))}
              emptyTitle="No catalog attention items"
              emptyMessage="Failed, unmapped, schema-missing, and no-run tables will appear here. Select any table for full detail."
            />
          </div>
        )}
      </div>
    </div>
  );
}
