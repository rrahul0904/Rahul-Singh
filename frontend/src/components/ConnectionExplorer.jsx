import React from "react";
import EmptyState from "./EmptyState.jsx";
import LoadingPanel from "./LoadingPanel.jsx";

export default function ConnectionExplorer({
  connections = [],
  connectionId = "",
  onConnectionChange,
  selectedConnection,
  database = "",
  schemaName = "",
  databases = [],
  schemas = [],
  tables = [],
  selectedTable = "",
  objectFilter = "",
  onObjectFilterChange,
  onDatabaseChange,
  onSchemaChange,
  onTableSelect,
  onRefresh,
  loading = "",
}) {
  const filteredTables = tables.filter((table) => !objectFilter.trim() || String(table).toLowerCase().includes(objectFilter.toLowerCase()));

  return (
    <aside className="sqlw-explorer ux-page-transition">
      <div className="sqlw-panel-head">
        <div className="sqlw-panel-title">Connection Explorer</div>
        <button className="btn btn-ghost btn-sm" onClick={onRefresh} disabled={!connectionId}>Refresh</button>
      </div>
      <div className="pq-explorer-picker">
        <select className="fi" value={connectionId} onChange={(e) => onConnectionChange(e.target.value)}>
          <option value="">Select connection</option>
          {connections.map((connection) => (
            <option key={connection.id} value={connection.id}>
              {connection.name} · {String(connection.type || connection.connector_type || "connection").toUpperCase()}
            </option>
          ))}
        </select>
      </div>
      <div className="sqlw-scroll">
        {!connectionId ? (
          <EmptyState compact title="Select a connection" message="Stored queryable connections appear here." />
        ) : (
          <div className="sqlw-tree">
            <div className="sqlw-node"><span className="sqlw-dot green" />{selectedConnection?.name || "Connection"}</div>
            <div className="pq-tree-select">
              <label className="fl">Database</label>
              <select className="fi" value={database} onChange={(e) => onDatabaseChange(e.target.value)} disabled={loading === "databases"}>
                <option value="">Select database</option>
                {databases.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </div>
            <div className="pq-tree-select">
              <label className="fl">Schema</label>
              <select className="fi" value={schemaName} onChange={(e) => onSchemaChange(e.target.value)} disabled={!database || loading === "schemas"}>
                <option value="">Select schema</option>
                {schemas.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </div>
            {loading === "tables" ? (
              <LoadingPanel label="Loading objects" />
            ) : !schemaName ? (
              <EmptyState compact title="Choose a schema" message="Tables load after database and schema are selected." />
            ) : (
              <>
                <div style={{ padding: "8px 8px 10px" }}>
                  <input className="fi" style={{ height: 34, fontSize: 12 }} placeholder="Filter tables" value={objectFilter} onChange={(e) => onObjectFilterChange(e.target.value)} />
                </div>
                {!filteredTables.length ? (
                  <EmptyState compact title="No tables found" message="Try another schema or clear the filter." />
                ) : filteredTables.map((table) => (
                  <div key={table} className={`sqlw-table-row ${selectedTable === table ? "active" : ""}`} style={{ animation: "uxFadeUp var(--motion-panel) var(--motion-ease) both" }} onClick={() => onTableSelect(table)}>
                    <span style={{ color: "#8ea0b5" }}>▦</span>{table}
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
