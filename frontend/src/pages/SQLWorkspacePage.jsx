import React, { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "../api";
import ConnectionExplorer from "../components/ConnectionExplorer.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorPanel from "../components/ErrorPanel.jsx";
import ResultGrid from "../components/ResultGrid.jsx";
import { MotionChecklist, PageTransition, SkeletonState } from "../components/EnterpriseUX.jsx";
import { getErrorMessage, fmtDate } from "../components/format.js";

function isReadOnlyStatement(sql) {
  const normalized = String(sql || "").trim().replace(/^--.*$/gm, "").trim().toLowerCase();
  return /^(select|with|show|describe|desc|explain)\b/.test(normalized);
}

function defaultSql(connection) {
  return connection?.type === "snowflake"
    ? "SELECT CURRENT_TIMESTAMP() AS CURRENT_TS;"
    : "SELECT CURRENT_TIMESTAMP AS current_ts;";
}

export default function SQLWorkspacePage() {
  const [connections, setConnections] = useState([]);
  const [connectionId, setConnectionId] = useState("");
  const selectedConnection = useMemo(() => connections.find((connection) => connection.id === connectionId), [connections, connectionId]);
  const isSourceConnection = Boolean(selectedConnection && selectedConnection.type !== "snowflake");

  const [workspaceSessionId, setWorkspaceSessionId] = useState("");
  const [database, setDatabase] = useState("");
  const [schemaName, setSchemaName] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [dbs, setDbs] = useState([]);
  const [schemas, setSchemas] = useState([]);
  const [tables, setTables] = useState([]);
  const [tableMeta, setTableMeta] = useState([]);
  const [preview, setPreview] = useState(null);
  const [objectFilter, setObjectFilter] = useState("");
  const [navLoading, setNavLoading] = useState("");
  const [sql, setSql] = useState(defaultSql(null));
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [resultTab, setResultTab] = useState("results");
  const [queryHistory, setQueryHistory] = useState([]);
  const [loadingConnections, setLoadingConnections] = useState(true);
  const executionMode = isSourceConnection ? "SOURCE_READ_ONLY" : selectedConnection?.type === "snowflake" ? "SNOWFLAKE_ROLE_GUARDED" : "READ_ONLY";
  const queryProgressChecks = [
    { label: "Connection selected", status: connectionId ? "passed" : "pending", detail: selectedConnection?.name || "Choose a connection first." },
    { label: "Permission mode evaluated", status: connectionId ? "passed" : "pending", detail: executionMode },
    { label: "SQL safety checked", status: running ? "running" : isReadOnlyStatement(sql) ? "passed" : "warning", detail: isReadOnlyStatement(sql) ? "Read-only statement." : "Write-capable SQL requires confirmation before execution." },
    { label: "Query execution", status: running ? "running" : results ? "passed" : error ? "failed" : "pending", detail: results ? `${results.row_count || 0} rows returned.` : error || "Waiting to run." },
    { label: "Audit trail captured", status: queryHistory.length ? "passed" : "pending", detail: queryHistory.length ? `${queryHistory.length} browser-session events.` : "History appears after execution." },
  ];

  const loadConnections = useCallback(async () => {
    setLoadingConnections(true);
    try {
      const rows = await api.workspaceConnections().catch(() => api.getConnections());
      setConnections(Array.isArray(rows) ? rows : []);
      if (!connectionId && rows?.length) setConnectionId(rows[0].id);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoadingConnections(false);
    }
  }, [connectionId]);

  useEffect(() => { loadConnections(); }, [loadConnections]);

  const clearContext = useCallback((connection) => {
    setWorkspaceSessionId("");
    setDatabase("");
    setSchemaName("");
    setSelectedTable("");
    setDbs([]);
    setSchemas([]);
    setTables([]);
    setTableMeta([]);
    setPreview(null);
    setResults(null);
    setError("");
    setObjectFilter("");
    setResultTab("results");
    setSql(defaultSql(connection));
  }, []);

  const changeConnection = (nextId) => {
    const next = connections.find((connection) => connection.id === nextId);
    setConnectionId(nextId);
    clearContext(next);
  };

  useEffect(() => {
    if (!selectedConnection || selectedConnection.type !== "snowflake") {
      setWorkspaceSessionId("");
      return;
    }
    let cancelled = false;
    const existing = selectedConnection.session;
    if (existing?.session_id) {
      setWorkspaceSessionId(existing.session_id);
      return;
    }
    api.getSnowflakeWorkspaceSessionStatus(selectedConnection.id)
      .then((response) => {
        if (cancelled) return;
        const active = (response.sessions || []).find((session) => session.status === "ACTIVE");
        setWorkspaceSessionId(active?.session_id || "");
      })
      .catch(() => {
        if (!cancelled) {
          setWorkspaceSessionId("");
        }
      });
    return () => { cancelled = true; };
  }, [selectedConnection]);

  const canBrowse = Boolean(connectionId);

  const refreshDatabases = useCallback(async () => {
    if (!canBrowse) return;
    setNavLoading("databases");
    setError("");
    try {
      const response = await api.workspaceDatabases(connectionId);
      setDbs(response.items || []);
      setSchemas([]);
      setTables([]);
      if (response.error) setError(response.error);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
      setDbs([]);
    } finally {
      setNavLoading("");
    }
  }, [canBrowse, connectionId]);

  useEffect(() => { refreshDatabases(); }, [refreshDatabases]);

  useEffect(() => {
    if (dbs.length && (!database || !dbs.includes(database))) setDatabase(dbs[0]);
  }, [dbs, database]);

  useEffect(() => {
    if (!canBrowse || !database) return;
    let cancelled = false;
    setNavLoading("schemas");
    setSchemas([]);
    setTables([]);
    api.workspaceSchemas(connectionId, database)
      .then((response) => {
        if (cancelled) return;
        setSchemas(response.items || []);
        if (response.error) setError(response.error);
      })
      .catch((loadError) => { if (!cancelled) setError(getErrorMessage(loadError)); })
      .finally(() => { if (!cancelled) setNavLoading(""); });
    return () => { cancelled = true; };
  }, [canBrowse, connectionId, database]);

  useEffect(() => {
    if (!schemas.length) return;
    const preferred = selectedConnection?.schema || (selectedConnection?.type === "postgres" ? "raw" : "PUBLIC");
    const match = schemas.find((item) => String(item).toLowerCase() === String(preferred).toLowerCase());
    if (!schemaName || !schemas.includes(schemaName)) setSchemaName(match || schemas[0]);
  }, [schemas, schemaName, selectedConnection]);

  useEffect(() => {
    if (!canBrowse || !database || !schemaName) return;
    let cancelled = false;
    setNavLoading("tables");
    setTables([]);
    api.workspaceTables(connectionId, database, schemaName)
      .then((response) => {
        if (cancelled) return;
        setTables(response.items || []);
        if (response.error) setError(response.error);
      })
      .catch((loadError) => { if (!cancelled) setError(getErrorMessage(loadError)); })
      .finally(() => { if (!cancelled) setNavLoading(""); });
    return () => { cancelled = true; };
  }, [canBrowse, connectionId, database, schemaName]);

  const inspectTable = async (table) => {
    if (!canBrowse) {
      setError("Select a connection before browsing objects.");
      return;
    }
    setSelectedTable(table);
    setError("");
    try {
      const [columns, previewRows] = await Promise.all([
        api.workspaceColumns(connectionId, table, database, schemaName),
        api.workspacePreview(connectionId, { database, schema_name: schemaName, table, limit: 50, workspace_session_id: workspaceSessionId || null }),
      ]);
      if (columns.error || previewRows.error) throw new Error(columns.error || previewRows.error);
      setTableMeta(columns.columns || []);
      setPreview(previewRows);
      setSql(selectedConnection?.type === "postgres"
        ? `SELECT * FROM "${schemaName}"."${table}" LIMIT 100;`
        : `SELECT * FROM "${database}"."${schemaName}"."${table}" LIMIT 100;`);
      setResultTab("preview");
    } catch (inspectError) {
      setError(getErrorMessage(inspectError));
    }
  };

  const runQuery = async () => {
    if (!connectionId) {
      setError("Select a connection before running SQL.");
      return;
    }
    if (isSourceConnection && !isReadOnlyStatement(sql)) {
      setError("Source connections are read-only in SQL Workspace. Use SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN.");
      setResultTab("messages");
      return;
    }
    if (!isSourceConnection && !isReadOnlyStatement(sql)) {
      const confirmed = window.confirm(
        "This query may write to the selected Snowflake target. UMA will audit the execution in this browser session. Continue only if your role and migration approval allow this change."
      );
      if (!confirmed) {
        setError("Write-capable query was cancelled before execution.");
        setResultTab("messages");
        return;
      }
    }
    setRunning(true);
    setError("");
    setResults(null);
    try {
      const result = await api.workspaceQuery(connectionId, { sql, database, schema_name: schemaName, max_rows: 1000, workspace_session_id: workspaceSessionId || null });
      if (!result.success) throw new Error(result.error || "Query failed.");
      setResults(result);
      setResultTab("results");
      setQueryHistory((history) => [{
        id: Date.now(),
        connection: selectedConnection?.name || "connection",
        status: "SUCCEEDED",
        rows: result.row_count || 0,
        ms: result.execution_time_ms || 0,
        execution_mode: executionMode,
        sql,
        created_at: new Date().toISOString(),
      }, ...history].slice(0, 30));
    } catch (queryError) {
      const message = getErrorMessage(queryError);
      setError(message);
      setResultTab("messages");
      setQueryHistory((history) => [{
        id: Date.now(),
        connection: selectedConnection?.name || "connection",
        status: "FAILED",
        rows: 0,
        ms: 0,
        execution_mode: executionMode,
        sql,
        error: message,
        created_at: new Date().toISOString(),
      }, ...history].slice(0, 30));
    } finally {
      setRunning(false);
    }
  };

  return (
    <PageTransition className="page sqlw-page">
      <div className="sqlw-head">
        <div>
          <div className="sqlw-title">SQL Workspace</div>
          <div className="sqlw-sub">Browse objects, run SQL, and inspect results from the selected connection.</div>
        </div>
      </div>

      <div className="sqlw-shell pq-sqlw-shell">
        <div className="sqlw-body pq-sqlw-body">
          <ConnectionExplorer
            connections={connections}
            connectionId={connectionId}
            onConnectionChange={changeConnection}
            selectedConnection={selectedConnection}
            database={database}
            schemaName={schemaName}
            databases={dbs}
            schemas={schemas}
            tables={tables}
            selectedTable={selectedTable}
            objectFilter={objectFilter}
            onObjectFilterChange={setObjectFilter}
            onDatabaseChange={(next) => { setDatabase(next); setSchemaName(""); setSelectedTable(""); setResults(null); setPreview(null); }}
            onSchemaChange={(next) => { setSchemaName(next); setSelectedTable(""); setResults(null); setPreview(null); }}
            onTableSelect={inspectTable}
            onRefresh={refreshDatabases}
            loading={navLoading}
          />

          <main className="sqlw-main pq-sql-main">
            <div className="sqlw-editor-area">
              <div className="sqlw-editor-toolbar pq-editor-toolbar">
                <button className="btn btn-primary btn-sm" onClick={runQuery} disabled={running || !connectionId}>{running ? <span className="spin">↻</span> : "Run SQL"}</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setSql(defaultSql(selectedConnection))}>New Query</button>
                <button className="btn btn-ghost btn-sm" onClick={() => setSql("")}>Clear</button>
                <span className="sqlw-pill">{sql.split("\n").length} lines</span>
              </div>
              <div className="sqlw-editor-wrap">
                <div className="sqlw-gutter">{sql.split("\n").map((_, index) => <div key={index}>{index + 1}</div>)}</div>
                <textarea
                  className="sqlw-editor"
                  value={sql}
                  onChange={(event) => setSql(event.target.value)}
                  onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); runQuery(); } }}
                  spellCheck={false}
                />
              </div>
            </div>

            <div className="sqlw-results pq-sql-results">
              <div className="sqlw-result-tabs">
                {["results", "messages", "history", "preview", "columns"].map((id) => (
                  <button key={id} className={`sqlw-result-tab ${resultTab === id ? "active" : ""}`} onClick={() => setResultTab(id)}>
                    {id.charAt(0).toUpperCase() + id.slice(1)}
                  </button>
                ))}
                <div className="sqlw-result-meta">{results ? `${results.row_count || 0} rows · ${results.execution_time_ms || 0} ms` : "No result set"}</div>
              </div>
              <div className="sqlw-result-body">
                {resultTab === "results" && (
                  running ? <div style={{ padding: 14 }}><MotionChecklist checks={queryProgressChecks} /><div className="mt3"><SkeletonState rows={5} title="Loading SQL results" /></div></div> : <ResultGrid columns={results?.columns || []} rows={results?.rows || []} emptyTitle="Run a query to see results" emptyMessage="The grid renders real result columns and rows from the selected connection." />
                )}
                {resultTab === "messages" && (
                  <div style={{ padding: 14 }}>
                    {error ? <ErrorPanel error={error} title="Query did not run" /> : results ? <div className="alert-info">Query completed. {results.row_count || 0} row(s) returned in {results.execution_time_ms || 0} ms.</div> : <EmptyState compact title="No messages" message="Query errors and completion details will appear here." />}
                  </div>
                )}
                {resultTab === "history" && (
                  <ResultGrid
                    columns={["time", "connection", "status", "rows", "ms", "sql"]}
                    rows={queryHistory.map((item) => ({ time: fmtDate(item.created_at), connection: item.connection, status: `${item.status} · ${item.execution_mode}`, rows: item.rows, ms: item.ms, sql: item.sql.slice(0, 160) }))}
                    emptyTitle="No query history"
                    emptyMessage="Queries run in this browser session will appear here as the local operator audit trail."
                  />
                )}
                {resultTab === "preview" && (
                  <ResultGrid columns={preview?.columns || []} rows={preview?.rows || []} emptyTitle="Select a table to preview rows" emptyMessage="Preview uses the selected database, schema, and table." />
                )}
                {resultTab === "columns" && (
                  <ResultGrid
                    columns={["name", "type"]}
                    rows={tableMeta.map((column) => ({ name: column.name || column.column_name, type: column.type || column.data_type }))}
                    emptyTitle="Select a table to inspect columns"
                  />
                )}
              </div>
            </div>
          </main>

          <aside className="sqlw-inspector">
            <div className="sqlw-panel-head"><div className="sqlw-panel-title">Object Inspector</div></div>
            <div className="sqlw-inspector-body">
              <div className="sqlw-inspect-section">
                <div className="sqlw-inspect-title">Connection</div>
                <div className="sqlw-kv"><span>Name</span><span>{selectedConnection?.name || "None"}</span></div>
                <div className="sqlw-kv"><span>Engine</span><span>{selectedConnection?.type || "None"}</span></div>
                <div className="sqlw-kv"><span>Database</span><span>{database || "Not selected"}</span></div>
                <div className="sqlw-kv"><span>Schema</span><span>{schemaName || "Not selected"}</span></div>
              </div>
              <div className="sqlw-inspect-section">
                <div className="sqlw-inspect-title">Table Details</div>
                <div className="sqlw-kv"><span>Table</span><span>{selectedTable || "None selected"}</span></div>
                <div className="sqlw-kv"><span>Columns</span><span>{tableMeta.length || "Not loaded"}</span></div>
                <div className="sqlw-kv"><span>Preview</span><span>{preview?.row_count ?? "Not loaded"}</span></div>
              </div>
              <div className="sqlw-inspect-section">
                <div className="sqlw-inspect-title">Last Result</div>
                <div className="sqlw-kv"><span>Rows</span><span>{results?.row_count ?? "No result"}</span></div>
                <div className="sqlw-kv"><span>Time</span><span>{results?.execution_time_ms != null ? `${results.execution_time_ms} ms` : "No result"}</span></div>
                <div className="sqlw-kv"><span>Status</span><span>{error ? "Needs attention" : results ? "Completed" : "Idle"}</span></div>
              </div>
            </div>
          </aside>
        </div>
      </div>

    </PageTransition>
  );
}
