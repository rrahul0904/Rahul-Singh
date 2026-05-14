import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Box,
  Brain,
  CheckCircle,
  Circle,
  Code,
  Command,
  Database,
  Factory,
  FileText,
  GitBranch,
  LayoutDashboard,
  Network,
  Pencil,
  Plug,
  PlusCircle,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Table2,
  Trash2,
  Users,
  Zap,
} from "lucide-react";
import SQLWorkspacePage from "./pages/SQLWorkspacePage.jsx";
import TablesCatalogPage from "./pages/TablesCatalogPage.jsx";
import DataReplicationPage from "./pages/DataReplicationPage.jsx";
import {
  AnimatedConnectionTest,
  ContextDrawer,
} from "./components/AnimatedMigrationExperience.jsx";
import {
  AICopilotControlPage,
  AnalyzerControlPage,
  AdvisorControlPage,
  ArtifactFactoryPage,
  BrainReviewPage,
  CommandCenterPage,
  DbtConversionPage,
  MigrationIntelligenceControlPage,
  MoreToolsPage,
  ProvisionControlPage,
  ReportsPage,
  ReplicationPlanPage,
  RunDetailPage,
  SqlConversionControlPage,
  ValidationControlPage,
} from "./pages/MigrationControlPlanePage.jsx";

// ─── API Client ──────────────────────────────────────────────
const API_BASE = import.meta.env.VITE_API_URL || "";

const TOKEN_KEY = "uma.accessToken";
const USER_KEY = "uma.currentUser";
const IMPERSONATOR_TOKEN_KEY = "uma.impersonatorAccessToken";
const IMPERSONATOR_USER_KEY = "uma.impersonatorUser";
const THEME_KEY = "uma.theme";
const THEME_VERSION_KEY = "uma.theme.version";
const THEME_VERSION = "2026-04-30-operator-console-polish";

function getStoredToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

function getStoredUser() {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

function saveSession(token, user) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function saveImpersonatorSession(token, user) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(IMPERSONATOR_TOKEN_KEY, token);
  window.localStorage.setItem(IMPERSONATOR_USER_KEY, JSON.stringify(user));
}

function getImpersonatorSession() {
  if (typeof window === "undefined") return null;
  const token = window.localStorage.getItem(IMPERSONATOR_TOKEN_KEY) || "";
  const rawUser = window.localStorage.getItem(IMPERSONATOR_USER_KEY);
  if (!token || !rawUser) return null;
  try {
    const user = JSON.parse(rawUser);
    return user?.role === "admin" ? { token, user } : null;
  } catch {
    return null;
  }
}

function clearImpersonatorSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(IMPERSONATOR_TOKEN_KEY);
  window.localStorage.removeItem(IMPERSONATOR_USER_KEY);
}

function clearSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  clearImpersonatorSession();
}

async function apiFetch(path, opts = {}) {
  const token = getStoredToken();
  const headers = { "Content-Type": "application/json", ...opts.headers };
  if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}/api${path}`, {
    headers,
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    if (res.status === 401) {
      clearSession();
      throw new Error(err.detail || "Authentication required");
    }
    throw new Error(err.detail || "API error");
  }
  if (res.status === 204) return null;
  return res.json();
}

const api = {
  // Auth
  bootstrapStatus:   ()         => apiFetch("/auth/bootstrap-status"),
  register:          (d)        => apiFetch("/auth/register", { method:"POST", body: JSON.stringify(d) }),
  login:             (d)        => apiFetch("/auth/login", { method:"POST", body: JSON.stringify(d) }),
  me:                ()         => apiFetch("/auth/me"),
  verifyEmail:       (token)    => apiFetch(`/auth/verify-email?token=${encodeURIComponent(token)}`),
  resendVerification:(email)    => apiFetch("/auth/resend-verification", { method:"POST", body: JSON.stringify({ email }) }),
  // Users (admin)
  listUsers:         ()         => apiFetch("/auth/users"),
  createUser:        (d)        => apiFetch("/auth/users", { method:"POST", body: JSON.stringify(d) }),
  updateUser:        (id, d)    => apiFetch(`/auth/users/${id}`, { method:"PATCH", body: JSON.stringify(d) }),
  deleteUser:        (id)       => apiFetch(`/auth/users/${id}`, { method:"DELETE" }),
  changePassword:    (d)        => apiFetch("/auth/change-password", { method:"POST", body: JSON.stringify(d) }),
  resetUserPassword: (id, d)    => apiFetch(`/auth/users/${id}/reset-password`, { method:"POST", body: JSON.stringify(d) }),
  impersonateUser:    (id)       => apiFetch(`/auth/impersonate/${id}`, { method:"POST" }),
  // Connections
  getConnections:    ()         => apiFetch("/connections"),
  getConnection:     (id)       => apiFetch(`/connections/${id}`),
  createConnection:  (d)        => apiFetch("/connections", { method:"POST", body: JSON.stringify(d) }),
  updateConnection:  (id, d)    => apiFetch(`/connections/${id}`, { method:"PUT", body: JSON.stringify(d) }),
  deleteConnection:  (id)       => apiFetch(`/connections/${id}`, { method:"DELETE" }),
  testConnection:    (id, d={})  => apiFetch(`/connections/${id}/test`, { method:"POST", body: JSON.stringify(d) }),
  testCredentials:   (d)        => apiFetch("/connections/test-credentials", { method:"POST", body: JSON.stringify(d) }),
  getRegistryStatus: ()         => apiFetch("/connections/registry-status"),
  // Jobs
  getJobs:           (p)        => apiFetch("/jobs" + (p ? "?"+new URLSearchParams(p) : "")),
  getJob:            (id)       => apiFetch(`/jobs/${id}`),
  createJob:         (d)        => apiFetch("/jobs", { method:"POST", body: JSON.stringify(d) }),
  executeJob:        (id)       => apiFetch(`/jobs/${id}/execute`, { method:"POST" }),
  cancelJob:         (id)       => apiFetch(`/jobs/${id}/cancel`, { method:"POST" }),
  deleteJob:         (id)       => apiFetch(`/jobs/${id}`, { method:"DELETE" }),
  getJobTasks:       (id)       => apiFetch(`/jobs/${id}/tasks`),
  addJobTask:        (id, d)    => apiFetch(`/jobs/${id}/tasks`, { method:"POST", body: JSON.stringify(d) }),
  getJobLogs:        (id, p)    => apiFetch(`/jobs/${id}/logs` + (p ? "?"+new URLSearchParams(p) : "")),
  getJobRuns:        (id)       => apiFetch(`/jobs/${id}/runs`),
  getJobRunDetail:   (id, rid)  => apiFetch(`/jobs/${id}/runs/${rid}`),
  getJobState:       (id)       => apiFetch(`/jobs/${id}/state`),
  getJobStats:       ()         => apiFetch("/jobs/stats/summary"),
  // Tables
  getTables:         (p)        => apiFetch("/tables" + (p ? "?"+new URLSearchParams(p) : "")),
  getTableStats:     ()         => apiFetch("/tables/stats"),
  getCatalogTables:  (p)        => apiFetch("/catalog/tables" + (p ? "?"+new URLSearchParams(p) : "")),
  getCatalogSummary: ()         => apiFetch("/catalog/tables/summary"),
  getCatalogTable:   (id)       => apiFetch(`/catalog/tables/${encodeURIComponent(id)}`),
  getCatalogColumns: (id)       => apiFetch(`/catalog/tables/${encodeURIComponent(id)}/columns`),
  getCatalogRuns:    (id)       => apiFetch(`/catalog/tables/${encodeURIComponent(id)}/runs`),
  getCatalogLineage: (id)       => apiFetch(`/catalog/tables/${encodeURIComponent(id)}/lineage`),
  // Validation
  getValidationRules:(p)        => apiFetch("/validation" + (p ? "?"+new URLSearchParams(p) : "")),
  createValidationRule:(d)      => apiFetch("/validation", { method:"POST", body: JSON.stringify(d) }),
  deleteValidationRule:(id)     => apiFetch(`/validation/${id}`, { method:"DELETE" }),
  runValidationRule: (id)       => apiFetch(`/validation/${id}/run`, { method:"POST" }),
  reconcileJob:      (d)        => apiFetch("/validation/reconcile", { method:"POST", body: JSON.stringify(d) }),
  // AI
  aiChat:            (messages) => apiFetch("/ai/chat", { method:"POST", body: JSON.stringify({ messages }) }),
  cortexAgent:       (message, context={}) => apiFetch("/ai/cortex-agent", { method:"POST", body: JSON.stringify({ message, context }) }),
  cortexAgentArchitecture: () => apiFetch("/ai/cortex-agent/architecture"),
  cortexAgentReadiness: () => apiFetch("/ai/cortex-agent/readiness"),
  codeGeneration:    (body)     => apiFetch("/ai/code-generation", { method:"POST", body: JSON.stringify(body) }),
  listCodeGenerationArtifacts: () => apiFetch("/ai/code-generation/artifacts"),
  getCodeGenerationArtifact: (id) => apiFetch(`/ai/code-generation/artifacts/${id}`),
  submitJudgePass: (id, body) => apiFetch(`/ai/code-generation/artifacts/${id}/judge-pass`, { method:"POST", body: JSON.stringify(body) }),
  reviseCodeGenerationArtifact: (id, body={}) => apiFetch(`/ai/code-generation/artifacts/${id}/revise`, { method:"POST", body: JSON.stringify(body) }),
  getCopilotProviders: () => apiFetch("/copilot/providers"),
  getAiProviderStatus: () => apiFetch("/ai/providers/status"),
  getOllamaHealth: () => apiFetch("/ai/providers/ollama/health"),
  getRagStatus: () => apiFetch("/rag/status"),
  indexRagRun: (id) => apiFetch(`/rag/index/run/${encodeURIComponent(id)}`, { method:"POST" }),
  searchRag: (params) => apiFetch("/rag/search" + (params ? "?"+new URLSearchParams(params) : "")),
  getCopilotSnowflakeServices: () => apiFetch("/copilot/snowflake-services"),
  queryCopilotSnowflakeService: (body) => apiFetch("/copilot/snowflake-services/query", { method:"POST", body: JSON.stringify(body) }),
  askCopilot:        (body) => apiFetch("/copilot/ask", { method:"POST", body: JSON.stringify(body) }),
  previewCopilotAction: (body) => apiFetch("/copilot/actions/preview", { method:"POST", body: JSON.stringify(body) }),
  executeCopilotAction: (body) => apiFetch("/copilot/actions/execute", { method:"POST", body: JSON.stringify(body) }),
  // Snowflake query execution
  snowflakeQuery:    (body)     => apiFetch("/snowflake/query", { method:"POST", body: JSON.stringify(body) }),
  listDatabases:     ()         => apiFetch("/snowflake/databases"),
  listSchemas:       (db)       => apiFetch(`/snowflake/schemas/${db}`),
  // Snowflake diagnostics
  diagnoseSnowflake: (body)     => apiFetch("/snowflake/diagnose", { method:"POST", body: JSON.stringify(body) }),
  snowflakeReadiness:(body)     => apiFetch("/snowflake/readiness", { method:"POST", body: JSON.stringify(body) }),
  createSnowflakeWorkspaceSession: (body) => apiFetch("/snowflake/workspace-session", { method:"POST", body: JSON.stringify(body) }),
  closeSnowflakeWorkspaceSession: (id) => apiFetch(`/snowflake/workspace-session/${encodeURIComponent(id)}`, { method:"DELETE" }),
  getSnowflakeWorkspaceSessionStatus: (connectionId="") => apiFetch("/snowflake/workspace-session/status" + (connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "")),
  heartbeatSnowflakeWorkspaceSession: (id) => apiFetch(`/snowflake/workspace-session/${encodeURIComponent(id)}/heartbeat`, { method:"POST" }),
  workspaceConnections: () => apiFetch("/workspace/connections"),
  workspaceDatabases: (id) => apiFetch(`/workspace/${encodeURIComponent(id)}/databases`),
  workspaceSchemas: (id, database="") => apiFetch(`/workspace/${encodeURIComponent(id)}/schemas` + (database ? `?database=${encodeURIComponent(database)}` : "")),
  workspaceTables: (id, database="", schemaName="") => apiFetch(`/workspace/${encodeURIComponent(id)}/tables?` + new URLSearchParams({ database, schema_name: schemaName })),
  workspaceColumns: (id, table, database="", schemaName="") => apiFetch(`/workspace/${encodeURIComponent(id)}/tables/${encodeURIComponent(table)}/columns?` + new URLSearchParams({ database, schema_name: schemaName })),
  workspacePreview: (id, body) => apiFetch(`/workspace/${encodeURIComponent(id)}/preview`, { method:"POST", body: JSON.stringify(body) }),
  workspaceQuery: (id, body) => apiFetch(`/workspace/${encodeURIComponent(id)}/query`, { method:"POST", body: JSON.stringify(body) }),
  // Schema drift
  driftCheck:        (body)     => apiFetch("/drift/check", { method:"POST", body: JSON.stringify(body) }),
  driftCheckAdHoc:   (body)     => apiFetch("/drift/check-adhoc", { method:"POST", body: JSON.stringify(body) }),
  driftApply:        (body)     => apiFetch("/drift/apply", { method:"POST", body: JSON.stringify(body) }),
  getControlPlaneRuns: () => apiFetch("/control-plane/runs"),
  linkRunScope:      (id, body) => apiFetch(`/control-plane/runs/${encodeURIComponent(id)}/link-scope`, { method:"POST", body: JSON.stringify(body) }),
  // AI extras
  aiSQL:             (body)     => apiFetch("/ai/sql", { method:"POST", body: JSON.stringify(body) }),
  aiExplainSQL:      (sql)      => apiFetch("/ai/explain-sql", { method:"POST", body: JSON.stringify({ sql }) }),
  aiLineage:         (t)        => apiFetch(`/ai/lineage/${encodeURIComponent(t)}`),
  // Health
  getHealth:         ()         => apiFetch("/health"),
  // Settings
  getSettings:       ()         => apiFetch("/settings"),
  saveSettings:      (d)        => apiFetch("/settings", { method:"PUT", body: JSON.stringify(d) }),
  getSettingsHistory:()         => apiFetch("/settings/history"),
  testEmail:         ()         => apiFetch("/settings/test-email", { method:"POST" }),
  testSlack:         ()         => apiFetch("/settings/test-slack", { method:"POST" }),
  // Managed syncs
  getSyncTemplates:  ()         => apiFetch("/syncs/templates"),
  getSyncOverview:   ()         => apiFetch("/syncs/overview"),
  getSyncProfiles:   ()         => apiFetch("/syncs/profiles"),
  getSyncProfile:    (id)       => apiFetch(`/syncs/profiles/${id}`),
  createSyncProfile: (d)        => apiFetch("/syncs/profiles", { method:"POST", body: JSON.stringify(d) }),
  updateSyncProfile: (id, d)    => apiFetch(`/syncs/profiles/${id}`, { method:"PATCH", body: JSON.stringify(d) }),
  deleteSyncProfile: (id)       => apiFetch(`/syncs/profiles/${id}`, { method:"DELETE" }),
  runSyncProfile:    (id)       => apiFetch(`/syncs/profiles/${id}/run`, { method:"POST" }),
  getSyncRuns:       (id)       => apiFetch(`/syncs/profiles/${id}/runs`),
  // Data replication control plane
  getReplicationOverview: () => apiFetch("/replication/overview"),
  getReplicationConnections: () => apiFetch("/replication/connections"),
  createReplicationConnection: (d) => apiFetch("/replication/connections", { method:"POST", body: JSON.stringify(d) }),
  testReplicationConnection: (id) => apiFetch(`/replication/connections/${id}/test`, { method:"POST" }),
  getReplicationSources: () => apiFetch("/replication/sources"),
  discoverReplicationSource: (d) => apiFetch("/replication/sources/discover", { method:"POST", body: JSON.stringify(d) }),
  getReplicationJobs: () => apiFetch("/replication/jobs"),
  getReplicationJob: (id) => apiFetch(`/replication/jobs/${id}`),
  createReplicationJob: (d) => apiFetch("/replication/jobs", { method:"POST", body: JSON.stringify(d) }),
  startReplicationJob: (id, d={}) => apiFetch(`/replication/jobs/${id}/start`, { method:"POST", body: JSON.stringify(d) }),
  pauseReplicationJob: (id) => apiFetch(`/replication/jobs/${id}/pause`, { method:"POST" }),
  resumeReplicationJob: (id) => apiFetch(`/replication/jobs/${id}/resume`, { method:"POST" }),
  cancelReplicationJob: (id) => apiFetch(`/replication/jobs/${id}/cancel`, { method:"POST" }),
  retryReplicationJob: (id) => apiFetch(`/replication/jobs/${id}/retry`, { method:"POST" }),
  getReplicationJobTables: (id) => apiFetch(`/replication/jobs/${id}/tables`),
  updateReplicationJobTables: (id, d) => apiFetch(`/replication/jobs/${id}/tables`, { method:"PUT", body: JSON.stringify(d) }),
  getReplicationJobPlan: (id) => apiFetch(`/replication/jobs/${id}/plan`),
  createReplicationJobPlan: (id) => apiFetch(`/replication/jobs/${id}/plan`, { method:"POST" }),
  getReplicationJobMapping: (id) => apiFetch(`/replication/jobs/${id}/mapping`),
  getReplicationJobEvents: (id) => apiFetch(`/replication/jobs/${id}/events`),
  getReplicationJobErrors: (id) => apiFetch(`/replication/jobs/${id}/errors`),
  getReplicationRuns: () => apiFetch("/replication/runs"),
  getReplicationRun: (id) => apiFetch(`/replication/runs/${id}`),
  getReplicationRunEvents: (id) => apiFetch(`/replication/runs/${id}/events`),
  getReplicationRunTables: (id) => apiFetch(`/replication/runs/${id}/tables`),
  getReplicationSnowflakeReadiness: () => apiFetch("/replication/snowflake/readiness"),
  checkReplicationSnowflakePermissions: (d) => apiFetch("/replication/snowflake/check-permissions", { method:"POST", body: JSON.stringify(d) }),
  // Agentic migration orchestrator
  getAgentRuns:      ()         => apiFetch("/agent-runs"),
  startAgentRun:     (d)        => apiFetch("/agent-runs/start", { method:"POST", body: JSON.stringify(d) }),
  getAgentRun:       (id)       => apiFetch(`/agent-runs/${id}`),
  getAgentSteps:     (id)       => apiFetch(`/agent-runs/${id}/steps`),
  getAgentToolCalls: (id)       => apiFetch(`/agent-runs/${id}/tool-calls`),
  approveAgentRun:   (id,d={approved:true}) => apiFetch(`/agent-runs/${id}/approve`, { method:"POST", body: JSON.stringify(d) }),
  retryAgentRun:     (id)       => apiFetch(`/agent-runs/${id}/retry`, { method:"POST" }),
  // Snowflake navigator
  navDatabases:      (id, auth={})       => apiFetch(`/snowflake/navigator/${id}/databases`, { method:"POST", body: JSON.stringify(auth) }),
  navSchemas:        (id,db,auth={})     => apiFetch(`/snowflake/navigator/${id}/schemas/${encodeURIComponent(db)}`, { method:"POST", body: JSON.stringify(auth) }),
  navTables:         (id,db,sch,auth={}) => apiFetch(`/snowflake/navigator/${id}/tables/${encodeURIComponent(db)}/${encodeURIComponent(sch)}`, { method:"POST", body: JSON.stringify(auth) }),
  navDescribe:       (id,db,sch,t,auth={})=> apiFetch(`/snowflake/navigator/${id}/describe/${encodeURIComponent(db)}/${encodeURIComponent(sch)}/${encodeURIComponent(t)}`, { method:"POST", body: JSON.stringify(auth) }),
  navPreview:        (id,db,sch,t,limit=50,auth={})=> apiFetch(`/snowflake/navigator/${id}/preview/${encodeURIComponent(db)}/${encodeURIComponent(sch)}/${encodeURIComponent(t)}?limit=${limit}`, { method:"POST", body: JSON.stringify(auth) }),
};

// ─── Hooks ───────────────────────────────────────────────────
function useApi(fn, deps = [], opts = {}) {
  const [data, setData]     = useState(opts.initialData ?? null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fn();
      setData(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => { refetch(); }, [refetch]);
  return { data, loading, error, refetch };
}

function usePoll(fn, interval = 5000, active = true) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!active) return;
    let mounted = true;
    const poll = async () => {
      try {
        const r = await fn();
        if (mounted) setData(r);
      } catch {}
    };
    poll();
    const id = setInterval(poll, interval);
    return () => { mounted = false; clearInterval(id); };
  }, [active, interval]);
  return data;
}

// ─── CSS ─────────────────────────────────────────────────────
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#101827;--bg1:#0c1422;--bg2:#121f31;--bg3:#1b2a40;
    --border:#2e4057;--border2:#456078;
    --text:#f4f8fb;--text2:#c8d6e4;--text3:#91a5b8;
    --accent:#4cc9f0;--accent2:#38bdf8;
    --green:#2dd4bf;--yellow:#f59e0b;--red:#ef4444;
    --purple:#8b5cf6;--orange:#f97316;
    --font-d:'Manrope',sans-serif;--font-h:'Space Grotesk',sans-serif;--font-m:'IBM Plex Mono',monospace;
    --r:8px;--rl:14px;
  }
  /* ── Light mode ───────────────────────────────────── */
  .theme-light{
    --bg:#EEF5F7;--bg1:#F8FBFC;--bg2:#FFFFFF;--bg3:#EAF1F6;
    --border:#CAD8E4;--border2:#AFC2D3;
    --text:#152033;--text2:#42556D;--text3:#718399;
    --accent:#2563EB;--accent2:#0F766E;
    --green:#0F766E;--yellow:#B7791F;--red:#B42318;
    --purple:#7C3AED;--orange:#D97706;
  }
  .theme-light body,.theme-light{background:#EEF5F7}
  .theme-light .card,.theme-light .sidebar,.theme-light .topbar{box-shadow:0 1px 3px rgba(15,26,44,.04)}
  .theme-light .hero{background:linear-gradient(135deg,#FFFFFF 0%,#F0F7FF 60%,#E8F4FF 100%);border-color:#D5DCE5}
  .theme-light .hero::after{background:radial-gradient(circle,rgba(0,102,204,.08) 0%,transparent 70%)}
  .theme-light .nav-item.active{background:rgba(0,102,204,.08);color:var(--accent);border-color:rgba(0,102,204,.2)}
  .theme-light tbody tr:hover{background:rgba(15,26,44,.025)}
  .theme-light .logo-icon{color:#FFFFFF}
  .theme-light .stat-card{box-shadow:0 1px 3px rgba(15,26,44,.04)}
  .theme-light .fi{background:#FFFFFF;border-color:#D5DCE5}
  .theme-light .fi:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(0,102,204,.1)}
  .theme-light .nbadge{color:#FFFFFF}
  .theme-light .modal{box-shadow:0 20px 60px rgba(15,26,44,.15)}
  .theme-light .alert-info{background:rgba(0,102,204,.06);border:1px solid rgba(0,102,204,.2);color:var(--accent)}
  .theme-light .card,
  .theme-light .modal,
  .theme-light .stat-card{
    background:#ffffff;
    border-color:#dbe5f0;
    color:#10213a;
    box-shadow:0 10px 26px rgba(15,26,44,.08);
  }
  .theme-light .card-header,
  .theme-light .tabs,
  .theme-light .filter-bar,
  .theme-light tbody tr{
    border-color:#dbe5f0;
  }
  .theme-light thead th{
    background:#edf3fa;
    color:#63748c;
    border-bottom-color:#dbe5f0;
  }
  .theme-light tbody td{
    color:#3c4a5c;
  }
  .theme-light tbody tr:hover{
    background:#f5f9fd;
  }
  .theme-light .td-main,
  .theme-light .card-title,
  .theme-light .modal-title,
  .theme-light .settings-title{
    color:#10213a;
  }
  .theme-light .td-mono,
  .theme-light .text-muted,
  .theme-light .row-subtext{
    color:#64748b;
  }
  .theme-light .info-tile,
  .theme-light .fg .fi,
  .theme-light .sw{
    background:#f6f9fd;
    border-color:#dbe5f0;
  }
  .theme-light .fi,
  .theme-light select,
  .theme-light input,
  .theme-light textarea{
    color:#10213a;
    background:#ffffff;
    border-color:#d5dce5;
  }
  .theme-light .badge.bgr{
    background:#eef3f8;
    color:#526176;
    border-color:#d6e0eb;
  }
  .theme-light .app{
    background:
      radial-gradient(1000px 520px at 12% -16%, rgba(37,99,235,.10), transparent 58%),
      radial-gradient(900px 520px at 96% 0%, rgba(15,118,110,.10), transparent 55%),
      linear-gradient(180deg,#f7fbfc 0%,#eef5f7 100%);
  }
  .theme-light .sidebar{
    background:linear-gradient(180deg,#ffffff 0%,#eef5f9 100%);
    border-right:1px solid #cddbe7;
  }
  .theme-light .logo-wrap,.theme-light .sidebar-bot{border-color:#e3ebf4}
  .theme-light .logo-name{color:#10213a}
  .theme-light .logo-sub{color:#6c7e95}
  .theme-light .nav-lbl{color:#7f8fa6}
  .theme-light .nav-item{color:#39506d}
  .theme-light .nav-item:hover{background:#eff5fc;color:#10213a}
  .theme-light .nav-item.active{background:#e9f4ff;color:#0a66cc;border-color:#cfe1f7}
  .theme-light .topbar{
    background:rgba(248,251,252,.92);
    border-bottom:1px solid #cddbe7;
    box-shadow:0 8px 22px rgba(37,67,97,.07);
  }
  .theme-light .topbar-title{color:#10213a}
  .theme-light .topbar-sub,.theme-light .topbar-status{color:#6c7e95}
  .theme-light .topbar-user,.theme-light .topbar-switcher{
    background:#f4f8fc;
    border-color:#d8e3ef;
  }
  .theme-light .topbar-email{color:#32465f}
  .theme-light .topbar-switcher .fi{
    background:#ffffff;
    border-color:#d8e3ef;
    color:#10213a;
  }
  .theme-light .page{background:transparent}
  .theme-light .agent-surface{
    background:#f7faff;
    color:#10213a;
  }
  .theme-light .agent-surface .card,
  .theme-light .agent-surface .stat-card{
    background:#ffffff;
    border-color:#dbe5f0;
    box-shadow:0 10px 24px rgba(15,26,44,.07);
  }
  .theme-light .agent-surface .pnode,
  .theme-light .agent-surface .info-tile,
  .theme-light .agent-surface .saved-query,
  .theme-light .agent-surface .agent-output-panel{
    background:#f6f9fd;
    border-color:#dbe5f0;
  }
  .theme-light .agent-surface .page-eyebrow{color:#0066cc}
  .theme-light .agent-surface pre,
  .theme-light .agent-surface code{
    background:#f3f7fc;
    color:#20344d;
    border-color:#dbe5f0;
  }
  .theme-light .agent-surface .ai-chip{
    background:#f2f0ff;
    border-color:#d9d2ff;
    color:#5b21b6;
  }
  .theme-light .agent-surface .ai-chip:hover{background:#e9e4ff}
  .agent-chat-grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;flex:1;min-height:0;padding:20px}
  .agent-work-grid{display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);gap:18px}
  .theme-light .dashboard-hero,
  .theme-light .dashboard-status-card,
  .theme-light .dashboard-operator-card,
  .theme-light .surface-panel,
  .theme-light .dashboard-copilot{
    background:linear-gradient(135deg,#0f1b2f 0%,#14233d 48%,#10213a 100%);
    border-color:#233b5e;
    box-shadow:0 20px 40px rgba(8,16,28,.22);
  }
  .theme-light .dashboard-mini-card{
    background:linear-gradient(180deg,#172942 0%,#14243b 100%);
    border-color:#2a446a;
    box-shadow:none;
  }
  .theme-light .dashboard-hero-title,
  .theme-light .dashboard-status-title,
  .theme-light .surface-panel-title,
  .theme-light .dashboard-operator-title{color:#f3f8ff}
  .theme-light .dashboard-hero-desc,
  .theme-light .dashboard-status-subtitle,
  .theme-light .dashboard-mini-note,
  .theme-light .dashboard-operator-note,
  .theme-light .surface-panel-subtitle,
  .theme-light .dashboard-copilot-desc{color:#aebed4}
  .theme-light .dashboard-mini-label,
  .theme-light .dashboard-operator-label,
  .theme-light .surface-panel table thead th{color:#7f95b5}
  .theme-light .dashboard-status-pill{
    background:rgba(0,229,160,.12);
    border-color:rgba(0,229,160,.22);
    color:#32e3ab;
  }
  .theme-light .tables-chip{
    background:rgba(255,255,255,.06);
    border-color:rgba(255,255,255,.12);
    color:#d2def0;
  }
  .theme-light .tables-note{
    background:rgba(23,198,255,.14);
    border:1px solid rgba(23,198,255,.16);
    color:#77d8ff;
  }
  .theme-light .surface-panel-header{
    background:linear-gradient(180deg,#182942 0%,#16253d 100%);
    border-bottom-color:#233b5e;
  }
  .theme-light .surface-panel table,
  .theme-light .surface-panel tbody{background:#10213a}
  .theme-light .surface-panel table thead th{
    background:#172741;
    border-bottom-color:#243b5e;
  }
  .theme-light .surface-panel table tbody td{color:#bdd0e6}
  .theme-light .surface-panel table tbody tr{border-bottom-color:#223754}
  .theme-light .surface-panel table tbody tr:hover{background:rgba(255,255,255,.03)}
  .theme-light .surface-panel .td-main{color:#f3f8ff}
  .theme-light .surface-panel .td-mono{color:#8ea3c2}
  .theme-light .dashboard-operator-foot{border-top-color:#223754;color:#96abc6}
  .theme-light .btn-ghost{color:#39506d;border-color:#bfd1e4;background:transparent}
  .theme-light .btn-ghost:hover{background:#edf4fb;color:#10213a}
  .theme-light .dashboard-hero .btn-ghost{
    color:#d4e1f2;
    border-color:#3b5374;
    background:rgba(255,255,255,.02);
  }
  .theme-light .dashboard-hero .btn-ghost:hover{
    background:#1d3150;
    color:#ffffff;
  }
  .theme-light .page-eyebrow{color:#0066cc}
  .sqlw-page{padding:0;min-height:calc(100vh - 64px);background:
    linear-gradient(180deg,#eef7f8 0%,#f7fbfd 42%,#eef5f8 100%)}
  .sqlw-head{height:64px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 22px;border-bottom:1px solid #cbdbe7;background:rgba(250,253,255,.74);backdrop-filter:blur(8px)}
  .sqlw-kicker{font-family:var(--font-m);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#64748b}
  .sqlw-title{font-size:19px;font-weight:850;color:#10213a;line-height:1.15}
  .sqlw-sub{font-size:12px;color:#607289;margin-top:2px}
  .sqlw-shell{height:calc(100vh - 150px);min-height:640px;margin:18px 22px 22px;border:1px solid #c7d7e4;border-radius:10px;overflow:hidden;background:#ffffff;box-shadow:0 22px 52px rgba(26,52,82,.14)}
  .sqlw-commandbar{height:54px;display:grid;grid-template-columns:300px minmax(0,1fr) 112px;align-items:center;border-bottom:1px solid #cbdbe7;background:linear-gradient(180deg,#f7fbfe 0%,#edf5fa 100%)}
  .sqlw-connection{height:100%;display:flex;align-items:center;padding:8px 10px;border-right:1px solid #cbdbe7;background:#f6fafc}
  .sqlw-context{display:flex;align-items:center;gap:8px;min-width:0;overflow:hidden;padding:8px 10px}
  .sqlw-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:8px 12px;border-left:1px solid #d8e4ee}
  .sqlw-body{height:calc(100% - 54px);display:grid;grid-template-columns:300px minmax(0,1fr) 280px;background:#f5f9fc}
  .sqlw-explorer,.sqlw-inspector{min-height:0;background:#fbfdff;display:flex;flex-direction:column}
  .sqlw-explorer{border-right:1px solid #cbdbe7}
  .sqlw-inspector{border-left:1px solid #cbdbe7}
  .sqlw-panel-head{height:42px;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 12px;border-bottom:1px solid #dbe6ef;background:#ffffff}
  .sqlw-panel-title{font-size:12px;font-weight:850;color:#19283c}
  .sqlw-scroll{min-height:0;overflow:auto}
  .sqlw-tree{font-size:12px;padding:8px}
  .sqlw-node{display:flex;align-items:center;gap:8px;height:30px;border-radius:7px;padding:0 8px;color:#33465f}
  .sqlw-node.depth1{padding-left:20px}.sqlw-node.depth2{padding-left:34px}.sqlw-node.depth3{padding-left:48px}
  .sqlw-table-row{display:flex;align-items:center;gap:8px;min-height:30px;border-radius:7px;padding:6px 8px 6px 62px;color:#22324a;cursor:pointer}
  .sqlw-table-row:hover{background:#eef5fb}
  .sqlw-table-row.active{background:#dfeeff;color:#0a58ca;font-weight:750}
  .sqlw-dot{width:7px;height:7px;border-radius:50%;background:#93a4b8;box-shadow:0 0 0 3px rgba(147,164,184,.13)}
  .sqlw-dot.green{background:#0f766e;box-shadow:0 0 0 3px rgba(15,118,110,.12)}
  .sqlw-main{min-width:0;min-height:0;display:grid;grid-template-rows:42px minmax(230px,1fr) 285px;background:#f8fbfd}
  .sqlw-tabs{display:flex;align-items:center;border-bottom:1px solid #d3e0eb;background:#ffffff}
  .sqlw-tab{height:42px;display:flex;align-items:center;gap:8px;padding:0 14px;border-right:1px solid #e0e9f1;font-size:12px;font-weight:760;color:#51647d;background:#ffffff}
  .sqlw-tab.active{color:#0a58ca;background:#f4f9ff;box-shadow:inset 0 -2px 0 #2563eb}
  .sqlw-tab-add{height:42px;width:40px;border:0;border-right:1px solid #e0e9f1;background:#ffffff;color:#64748b;font-weight:850;cursor:pointer}
  .sqlw-editor-area{min-height:0;display:grid;grid-template-rows:38px minmax(0,1fr);background:#fbfdff}
  .sqlw-editor-toolbar{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid #dbe6ef;background:#f7fbfe}
  .sqlw-editor-wrap{min-height:0;display:grid;grid-template-columns:50px minmax(0,1fr);background:#fbfdff}
  .sqlw-gutter{overflow:hidden;padding:14px 0;background:#f1f6fa;border-right:1px solid #dce7ef;color:#8a9aad;font-family:var(--font-m);font-size:12px;line-height:1.72;text-align:right}
  .sqlw-gutter div{height:20.64px;padding-right:12px}
  .sqlw-editor{width:100%;height:100%;resize:none;border:0;outline:0;background:#fbfdff;color:#132238;padding:14px 16px;font-family:var(--font-m);font-size:13px;line-height:1.72;tab-size:2}
  .sqlw-editor:focus{background:#ffffff}
  .sqlw-results{min-height:0;border-top:1px solid #cbdbe7;background:#ffffff;display:grid;grid-template-rows:40px minmax(0,1fr)}
  .sqlw-result-tabs{display:flex;align-items:center;border-bottom:1px solid #dbe6ef;background:#f7fbfe}
  .sqlw-result-tab{height:40px;border:0;border-right:1px solid #dbe6ef;background:transparent;padding:0 13px;font-size:12px;font-weight:780;color:#5a6d84;cursor:pointer}
  .sqlw-result-tab.active{background:#ffffff;color:#0a58ca;box-shadow:inset 0 -2px 0 #2563eb}
  .sqlw-result-meta{margin-left:auto;padding-right:12px;font-family:var(--font-m);font-size:11px;color:#708197}
  .sqlw-empty{display:grid;place-items:center;min-height:100%;color:#76879d;font-size:12px}
  .sqlw-inspector-body{padding:12px;display:flex;flex-direction:column;gap:12px}
  .sqlw-inspect-section{border:1px solid #dbe6ef;border-radius:8px;background:#ffffff;overflow:hidden}
  .sqlw-inspect-title{padding:9px 10px;border-bottom:1px solid #e3ebf3;background:#f8fbfe;font-size:11px;font-weight:850;text-transform:uppercase;letter-spacing:.04em;color:#63758b}
  .sqlw-kv{display:grid;grid-template-columns:88px minmax(0,1fr);gap:7px;padding:10px;font-size:12px;border-bottom:1px solid #edf2f7}
  .sqlw-kv:last-child{border-bottom:0}
  .sqlw-kv span:first-child{color:#77889e}
  .sqlw-kv span:last-child{color:#17263a;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .sqlw-statusline{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .sqlw-pill{display:inline-flex;align-items:center;gap:6px;height:24px;border-radius:999px;border:1px solid #d3e1ed;background:#f7fbfe;color:#3d526b;font-family:var(--font-m);font-size:10px;font-weight:700;padding:0 8px}
  .sqlw-pill.blue{border-color:#bfdbfe;background:#eff6ff;color:#1d4ed8}
  .sqlw-pill.green{border-color:#bde7df;background:#ecfdf8;color:#0f766e}
  .sqlw-pill.amber{border-color:#fde2a6;background:#fff8e6;color:#a16207}
  @media (max-width: 1220px){
    .sqlw-shell{margin:18px 18px 22px}
    .sqlw-body{grid-template-columns:300px minmax(0,1fr)}
    .sqlw-inspector{display:none}
    .sqlw-commandbar{grid-template-columns:300px minmax(0,1fr) 108px}
  }

  body{background:var(--bg);color:var(--text);font-family:var(--font-d);min-height:100vh;overflow-x:hidden;transition:background .2s,color .2s}
  ::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
  .app{display:flex;min-height:100vh;background:
    radial-gradient(900px 520px at 18% -12%, rgba(23,198,255,.08), transparent 64%),
    radial-gradient(820px 520px at 96% 8%, rgba(0,229,160,.07), transparent 58%),
    var(--bg);
    color:var(--text)}
  .sidebar{width:240px;min-width:240px;background:linear-gradient(180deg,rgba(15,26,43,.98) 0%,rgba(11,20,33,.98) 100%);border-right:1px solid var(--border);display:flex;flex-direction:column;position:fixed;height:100vh;z-index:100;backdrop-filter:blur(6px)}
  .logo-wrap{padding:24px 20px 16px;border-bottom:1px solid var(--border)}
  .logo-row{display:flex;align-items:center;gap:10px;margin-bottom:3px}
  .logo-icon{width:30px;height:30px;background:var(--accent);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800;color:var(--bg);font-family:var(--font-m)}
  .logo-name{font-size:14px;font-weight:700}
  .logo-sub{font-size:9px;color:var(--text3);letter-spacing:1.5px;text-transform:uppercase;font-family:var(--font-m);padding-left:40px}
  .nav{flex:1;padding:14px 10px;overflow-y:auto}
  .nav-section{margin-bottom:20px}
  .nav-lbl{font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#a4b4ca;padding:0 10px;margin-bottom:5px;font-family:var(--font-m)}
  .nav-item{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:var(--r);cursor:pointer;transition:all .15s;font-size:13px;font-weight:600;color:#c9d5e6;margin-bottom:2px;border:1px solid transparent}
  .nav-item:hover{background:#1b2d47;color:#ffffff}
  .nav-item.active{background:rgba(23,198,255,.14);color:#7be1ff;border-color:rgba(23,198,255,.28)}
  .nav-item .ni{width:16px;text-align:center;font-size:13px;flex-shrink:0}
  .nav-item .nav-caret{margin-left:auto;font-size:10px;color:inherit;opacity:.8}
  .nav-child-list{margin:2px 0 8px 25px;padding-left:8px;border-left:1px solid rgba(148,215,234,.28)}
  .nav-child{display:flex;align-items:center;gap:7px;padding:7px 8px;border-radius:8px;cursor:pointer;color:#b7c8dc;font-size:12px;font-weight:600;margin-bottom:2px;border:1px solid transparent}
  .nav-child:hover{background:#1b2d47;color:#ffffff}
  .nav-child.active{background:rgba(23,198,255,.1);color:#7be1ff;border-color:rgba(23,198,255,.2)}
  .nav-child .ni{width:13px;text-align:center;font-size:11px;flex-shrink:0}
  .nav-more{width:100%;background:transparent;text-align:left;font-family:var(--font-d)}
  .nbadge{margin-left:auto;background:var(--accent);color:var(--bg);font-size:9px;font-weight:700;padding:2px 6px;border-radius:20px;font-family:var(--font-m)}
  .nbadge.warn{background:var(--yellow)}.nbadge.err{background:var(--red)}
  .sidebar-bot{padding:14px 10px;border-top:1px solid var(--border)}
  .sdot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);display:inline-block;margin-right:6px}
  .main{margin-left:240px;flex:1;display:flex;flex-direction:column;min-height:100vh}
  .topbar{height:64px;background:rgba(15,26,43,.88);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 24px;gap:14px;position:sticky;top:0;z-index:50;backdrop-filter:blur(14px)}
  .topbar > div:first-child{flex:1 1 260px;min-width:180px}
  .topbar-title{font-size:15px;font-weight:800;flex:1;font-family:var(--font-h)}
  .topbar-sub{font-size:11px;color:#aab8cc;font-family:var(--font-m)}
  .topbar-controls{margin-left:auto;display:flex;align-items:center;gap:10px;flex:0 1 auto;min-width:0;justify-content:flex-end}
  .topbar-status{font-size:11px;color:#aab8cc;font-family:var(--font-m)}
  .topbar-user{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:999px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12)}
  .topbar-email{font-size:11px;color:#d6e0ee;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .topbar-switcher{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:999px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12)}
  .topbar-switcher .fi{width:clamp(150px,20vw,260px);padding:7px 10px;font-size:11px;background:#111f33;color:var(--text);border-color:#385374}
  .topbar-avatar{width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#6bbcff);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;color:#08121f;box-shadow:0 10px 18px rgba(23,198,255,.25)}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:var(--r);font-size:12px;font-weight:700;letter-spacing:.3px;cursor:pointer;border:none;transition:all .15s;font-family:var(--font-d)}
  .btn-primary{background:var(--accent);color:#041220}.btn-primary:hover{background:#4bd8ff;box-shadow:0 8px 18px rgba(23,198,255,.28)}
  .btn-ghost{background:rgba(255,255,255,.02);color:#d2deee;border:1px solid var(--border2)}.btn-ghost:hover{background:#1b2d47;color:#ffffff}
  .btn-danger{background:rgba(255,69,96,.1);color:var(--red);border:1px solid rgba(255,69,96,.2)}.btn-danger:hover{background:rgba(255,69,96,.2)}
  .btn-purple{background:var(--purple);color:#fff}.btn-purple:hover{background:#9470FF;box-shadow:0 0 16px rgba(124,92,255,.3)}
  .btn-sm{padding:5px 10px;font-size:11px}.btn-xs{padding:3px 8px;font-size:10px}.btn-icon{padding:6px}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .page{padding:28px 28px 40px;flex:1}
  .page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:22px}
  .page-header-copy{display:flex;flex-direction:column;gap:8px}
  .page-eyebrow{font-size:10px;font-weight:800;letter-spacing:1.8px;text-transform:uppercase;color:var(--accent);font-family:var(--font-m)}
  .page-title{font-size:34px;line-height:1.02;font-weight:800;font-family:var(--font-h)}
  .page-subtitle{font-size:14px;line-height:1.6;color:var(--text3);max-width:760px}
  .page-actions{display:flex;gap:10px;align-items:center}
  .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
  .stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--rl);padding:18px 20px;position:relative;overflow:hidden;transition:border-color .2s}
  .stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--al,var(--accent)),transparent);opacity:.6}
  .stat-label{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text3);font-family:var(--font-m);margin-bottom:6px}
  .stat-value{font-size:26px;font-weight:800;line-height:1;margin-bottom:3px}
  .stat-change{font-size:11px;color:var(--text3);font-family:var(--font-m)}.stat-change.up{color:var(--green)}
  .stat-icon{position:absolute;right:16px;top:16px;font-size:20px;opacity:.1}
  .hero{background:linear-gradient(135deg,#10213a 0%,#113053 44%,#0d1d35 100%);border:1px solid var(--border2);border-radius:var(--rl);padding:28px 32px;margin-bottom:24px;position:relative;overflow:hidden;box-shadow:0 14px 36px rgba(7,15,27,.32)}
  .hero::after{content:'';position:absolute;right:-60px;top:-60px;width:260px;height:260px;border-radius:50%;background:radial-gradient(circle,rgba(0,212,255,.07) 0%,transparent 70%);pointer-events:none}
  .hero-tag{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--accent);font-family:var(--font-m);font-weight:700;margin-bottom:8px}
  .hero-title{font-size:24px;font-weight:800;margin-bottom:7px;line-height:1.2}
  .hero-desc{font-size:12px;color:var(--text2);max-width:460px;line-height:1.6;margin-bottom:18px}
  .hero-actions{display:flex;gap:9px}
  .hero-stats{display:flex;gap:28px;margin-top:20px;padding-top:16px;border-top:1px solid var(--border)}
  .hs-val{font-size:18px;font-weight:800;color:var(--accent);font-family:var(--font-m)}
  .hs-lbl{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:1px;margin-top:2px}
  .card{background:linear-gradient(180deg,rgba(17,30,49,.96),rgba(13,24,40,.96));border:1px solid var(--border);border-radius:var(--rl);overflow:hidden;box-shadow:0 10px 28px rgba(4,10,18,.28);min-width:0}
  .card-header{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
  .card-title{font-size:13px;font-weight:700}
  table{width:100%;border-collapse:collapse}
  thead th{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#aab9ce;padding:10px 14px;text-align:left;font-family:var(--font-m);border-bottom:1px solid var(--border);background:#1b2d47}
  tbody tr{border-bottom:1px solid var(--border);transition:background .1s}
  tbody tr:last-child{border-bottom:none}
  tbody tr:hover{background:rgba(255,255,255,.04)}
  tbody td{padding:11px 14px;font-size:12px;color:var(--text2);vertical-align:middle}
  .td-main{color:var(--text);font-weight:500;font-size:13px}
  .td-mono{font-family:var(--font-m);font-size:11px}
  .badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;font-family:var(--font-m)}
  .bg{background:rgba(0,229,160,.12);color:var(--green);border:1px solid rgba(0,229,160,.2)}
  .by{background:rgba(255,184,0,.12);color:var(--yellow);border:1px solid rgba(255,184,0,.2)}
  .br{background:rgba(255,69,96,.12);color:var(--red);border:1px solid rgba(255,69,96,.2)}
  .bb{background:rgba(0,212,255,.12);color:var(--accent);border:1px solid rgba(0,212,255,.2)}
  .bp{background:rgba(124,92,255,.12);color:var(--purple);border:1px solid rgba(124,92,255,.2)}
  .bgr{background:rgba(174,190,212,.12);color:#c6d2e4;border:1px solid var(--border2)}
  .badge-dot::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor;display:inline-block}
  .spill{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;font-family:var(--font-m)}
  .filter-bar{display:flex;gap:9px;padding:12px 14px;border-bottom:1px solid var(--border)}
  .sw{position:relative;flex:1}
  .sw input{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:7px 11px 7px 30px;color:var(--text);font-size:12px;font-family:var(--font-d);outline:none;transition:border-color .15s}
  .sw input:focus{border-color:var(--accent2)}
  .sw input::placeholder{color:var(--text3)}
  .si{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--text3);font-size:12px}
  select{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:7px 11px;color:var(--text);font-size:12px;font-family:var(--font-d);outline:none;cursor:pointer;transition:border-color .15s}
  select:focus{border-color:var(--accent2)}
  .modal-ov{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(6px);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px}
  .modal{background:var(--bg2);border:1px solid var(--border2);border-radius:var(--rl);width:100%;max-width:520px;max-height:90vh;overflow-y:auto;animation:su .2s ease}
  .modal-lg{max-width:700px}
  @keyframes su{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
  .modal-hdr{padding:20px 22px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
  .modal-title{font-size:14px;font-weight:700}
  .modal-body{padding:18px 22px}
  .modal-foot{padding:14px 22px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:9px}
  .fg{margin-bottom:14px}
  .fl{font-size:10px;font-weight:700;color:var(--text2);letter-spacing:.5px;margin-bottom:5px;display:block;text-transform:uppercase;font-family:var(--font-m)}
  .fi{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:9px 12px;color:var(--text);font-size:12px;font-family:var(--font-d);outline:none;transition:border-color .15s}
  .fi:focus{border-color:var(--accent2)}
  .fi::placeholder{color:var(--text3)}
  .fr{display:grid;grid-template-columns:1fr 1fr;gap:11px}
  .fhint{font-size:10px;color:var(--text3);margin-top:4px;font-family:var(--font-m)}
  textarea.fi{resize:vertical;min-height:70px;font-family:var(--font-m);font-size:11px}
  .steps{display:flex;gap:0;margin-bottom:20px}
  .step{flex:1;display:flex;align-items:center}
  .sdot2{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid var(--border2);color:var(--text3);flex-shrink:0;font-family:var(--font-m);transition:all .2s}
  .step.active .sdot2{border-color:var(--accent);color:var(--accent);background:rgba(0,212,255,.1)}
  .step.done .sdot2{border-color:var(--green);background:var(--green);color:var(--bg)}
  .step-lbl{font-size:11px;color:var(--text3);margin-left:7px;white-space:nowrap}
  .step.active .step-lbl{color:var(--text)}
  .step-line{flex:1;height:1px;background:var(--border);margin:0 8px}
  .pipe{display:flex;align-items:center;gap:0;margin:16px 0}
  .pnode{background:var(--bg3);border:1px solid var(--border2);border-radius:var(--r);padding:10px 14px;text-align:center;min-width:100px}
  .pnode.active{border-color:var(--accent);background:rgba(0,212,255,.06)}
  .pnode.done{border-color:var(--green);background:rgba(0,229,160,.06)}
  .pnode.fail{border-color:var(--red);background:rgba(255,69,96,.06)}
  .plbl{font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--text3);font-family:var(--font-m);margin-bottom:3px}
  .pval{font-size:12px;font-weight:700}
  .parr{flex:1;height:1px;background:var(--border2);position:relative;margin:0 4px}
  .parr::after{content:'▶';position:absolute;right:-5px;top:50%;transform:translateY(-50%);color:var(--border2);font-size:7px}
  .tabs{display:flex;gap:8px;border-bottom:1px solid var(--border);padding:14px 18px;background:transparent;flex-wrap:wrap}
  .tab{padding:10px 14px;font-size:12px;font-weight:700;color:var(--text3);cursor:pointer;border:1px solid transparent;border-radius:999px;transition:all .15s;background:transparent}
  .tab:hover{color:var(--text);border-color:var(--border2);background:rgba(255,255,255,.05)}
  .tab.active{color:#fff;background:#16324d;border-color:#16324d;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06),0 8px 18px rgba(6,18,32,.12)}
  .log-row{display:grid;grid-template-columns:150px 55px 150px 1fr auto;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);font-size:11px;transition:background .1s}
  .log-row:hover{background:rgba(255,255,255,.04)}
  .ai-panel{background:linear-gradient(135deg,#0B1525,#0F1C35);border:1px solid rgba(124,92,255,.2);border-radius:var(--rl);padding:20px;margin-bottom:20px;position:relative;overflow:hidden}
  .ai-chip{background:rgba(124,92,255,.1);border:1px solid rgba(124,92,255,.2);color:var(--purple);padding:4px 10px;border-radius:20px;font-size:11px;cursor:pointer;transition:all .15s}
  .ai-chip:hover{background:rgba(124,92,255,.2)}
  .two-col{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
  .divider{height:1px;background:var(--border);margin:14px 0}
  .source-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}
  .stile{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:12px 10px;text-align:center;cursor:pointer;transition:all .15s}
  .stile:hover{border-color:var(--border2)}.stile.sel{border-color:var(--accent);background:rgba(0,212,255,.06)}
  .stile .ti{font-size:20px;margin-bottom:5px}.stile .tn{font-size:10px;font-weight:600;color:var(--text2)}
  .empty{text-align:center;padding:50px 20px;color:var(--text3)}
  .empty-icon{font-size:36px;margin-bottom:10px;opacity:.25}
  .empty-msg{font-size:12px}
  .alert-err{background:rgba(255,69,96,.08);border:1px solid rgba(255,69,96,.2);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--red);margin-bottom:14px}
  .alert-ok{background:rgba(0,229,160,.08);border:1px solid rgba(0,229,160,.2);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--green);margin-bottom:14px}
  .alert-info{background:rgba(0,212,255,.08);border:1px solid rgba(0,212,255,.2);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--accent);margin-bottom:14px}
  .table-scroll{width:100%;overflow-x:auto}
  .table-scroll table{min-width:760px}
  .table-scroll table td,.table-scroll table th{overflow-wrap:anywhere}
  .jobs-table table{min-width:980px}
  .validation-table table{min-width:1040px}
  .sync-profiles-table table{min-width:720px}
  .sync-runs-table table{min-width:760px}
  .soft-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .ep-alert-strip{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 0 12px;padding:13px 15px;border:1px solid var(--border);border-left:4px solid var(--green);border-radius:10px;background:var(--bg2)}
  .ep-alert-strip.has-blockers{border-left-color:var(--red);background:linear-gradient(90deg,rgba(255,69,96,.10),var(--bg2))}
  .ep-alert-kicker{font:800 10px/1 var(--font-m);letter-spacing:.12em;text-transform:uppercase;color:var(--text3)}
  .ep-alert-title{margin-top:5px;font-size:14px;font-weight:850;color:var(--text);line-height:1.35}
  .ep-alert-items{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
  .ep-alert-item{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--border);border-radius:10px;background:var(--bg);color:var(--text2);padding:8px 10px;font-size:12px;font-weight:750;cursor:pointer;max-width:420px;text-align:left}
  .ep-alert-item:hover,.ep-alert-item.active{border-color:var(--accent);box-shadow:0 8px 22px rgba(15,26,44,.08)}
  .ep-alert-action{display:inline-flex;align-items:center;gap:8px;min-height:36px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);padding:8px 12px;font:800 12px/1 var(--font-d);cursor:pointer;white-space:nowrap}
  .ep-alert-action:hover,.ep-alert-action.active{border-color:var(--accent);box-shadow:0 8px 22px rgba(15,26,44,.08)}
  .ep-alert-action.primary{background:var(--accent);border-color:var(--accent);color:#041220}
  .ep-alert-action.danger{border-color:rgba(255,69,96,.28);color:var(--red);background:rgba(255,69,96,.08)}
  .ep-alert-action.success{border-color:rgba(0,229,160,.25);color:var(--green);background:rgba(0,229,160,.08)}
  .ep-action-count{display:inline-flex;align-items:center;justify-content:center;min-width:22px;height:22px;padding:0 6px;border-radius:999px;background:currentColor;color:var(--bg);font:900 11px/1 var(--font-m)}
  .ep-alert-copy{display:grid;gap:2px;min-width:0}
  .ep-alert-copy strong{font-size:12px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .ep-alert-copy span{font-size:10px;color:var(--text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-transform:uppercase;letter-spacing:.06em}
  .ep-alert-ok{font-size:12px;color:var(--green);font-weight:800}
  .ep-kpi-row{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:0 0 12px}
  .ep-kpi{min-width:0;border:1px solid var(--border);border-radius:10px;background:var(--bg2);padding:11px 12px}
  button.ep-kpi,.ep-kpi.is-clickable,.stat-card.is-clickable,.info-tile.is-clickable,.tables-kpi.is-clickable{cursor:pointer;text-align:left;color:inherit;font:inherit;appearance:none}
  button.ep-kpi:hover,.ep-kpi.is-clickable:hover,.stat-card.is-clickable:hover,.info-tile.is-clickable:hover,.tables-kpi.is-clickable:hover{border-color:var(--accent);box-shadow:0 8px 22px rgba(15,26,44,.08);transform:translateY(-1px)}
  button.ep-kpi:focus-visible,.ep-kpi.is-clickable:focus-visible,.stat-card.is-clickable:focus-visible,.info-tile.is-clickable:focus-visible,.tables-kpi.is-clickable:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .ep-kpi.active,.stat-card.active,.info-tile.active,.tables-kpi.active{border-color:var(--accent);box-shadow:inset 0 0 0 1px rgba(23,198,255,.35)}
  .ep-kpi-label{font:800 10px/1 var(--font-m);letter-spacing:.1em;text-transform:uppercase;color:var(--text3)}
  .ep-kpi-value{margin-top:7px;font-size:22px;line-height:1.05;font-weight:900;color:var(--text);overflow-wrap:anywhere}
  .ep-kpi-note{margin-top:4px;font-size:11px;color:var(--text3);line-height:1.35}
  .ep-workspace{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:12px;align-items:start}
  .ep-workspace.wide-detail{grid-template-columns:minmax(0,1fr) 420px}
  .ep-list-panel,.ep-detail-panel,.ep-card{border:1px solid var(--border);border-radius:10px;background:var(--bg2);box-shadow:none;overflow:hidden}
  .ep-list-head,.ep-detail-head,.ep-card-header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:13px 14px;border-bottom:1px solid var(--border);background:rgba(255,255,255,.02)}
  .ep-list-title,.ep-detail-title{font-size:14px;font-weight:900;color:var(--text);line-height:1.25}
  .ep-list-subtitle,.ep-detail-subtitle{margin-top:4px;font-size:12px;color:var(--text3);line-height:1.4}
  .ep-detail-actions{padding:10px 12px;border-bottom:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap}
  .ep-detail-body{padding:12px;display:grid;gap:12px}
  .ep-section-label{font:850 10px/1 var(--font-m);letter-spacing:.1em;text-transform:uppercase;color:var(--text3);margin-bottom:7px}
  .ep-selected-row{background:rgba(23,198,255,.08)!important}
  .ep-empty-compact{border:1px dashed var(--border2);border-radius:10px;padding:14px;color:var(--text3);font-size:12px;line-height:1.45;background:var(--bg3)}
  .card.ep-card{border-radius:10px}
  .ep-card .card-header{padding:13px 14px}
  .ep-card > div:last-child{padding:12px!important}
  .ep-card table,.ep-list-panel table{font-size:12px}
  .ep-card th,.ep-card td,.ep-list-panel th,.ep-list-panel td{padding:8px 10px}
  .ep-tab-strip{display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--border);padding:8px 10px;background:var(--bg2)}
  .ep-tab{border:1px solid transparent;background:transparent;color:var(--text3);border-radius:8px;padding:7px 10px;font-size:12px;font-weight:800;cursor:pointer}
  .ep-tab.active{background:var(--bg);border-color:var(--border);color:var(--text)}
  .ep-code-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .ep-code-pane{min-width:0;border:1px solid var(--border);border-radius:10px;background:var(--bg3);overflow:hidden}
  .ep-code-title{padding:9px 10px;border-bottom:1px solid var(--border);font-size:12px;font-weight:850;color:var(--text2)}
  .ep-code-pane pre{margin:0;max-height:420px;overflow:auto;padding:12px;font:11px/1.5 var(--font-m);color:var(--text2)}
  .ep-queue{display:grid;grid-template-columns:320px minmax(0,1fr) 300px;gap:12px;align-items:start}
  .ep-queue-list{border:1px solid var(--border);border-radius:10px;background:var(--bg2);overflow:hidden}
  .ep-queue-item{width:100%;text-align:left;border:0;border-bottom:1px solid var(--border);background:transparent;color:var(--text);padding:11px 12px;cursor:pointer}
  .ep-queue-item.active{background:rgba(23,198,255,.08)}
  .ep-queue-name{font-weight:850;font-size:13px;line-height:1.35}
  .ep-queue-meta{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}
  .ep-detail-card{border:1px solid var(--border);border-radius:10px;background:var(--bg2);padding:14px}
  .ep-recommendation{border-left:3px solid var(--accent);background:var(--bg3);border-radius:8px;padding:12px;font-size:13px;line-height:1.5;color:var(--text2)}
  .ep-action-row{display:flex;gap:8px;flex-wrap:wrap}
  .ep-health-grid{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:12px;align-items:start}
  .ep-split-table{border:1px solid var(--border);border-radius:10px;background:var(--bg2);overflow:auto}
  .ep-split-table table{min-width:1120px}
  .ep-split-toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:10px;border-bottom:1px solid var(--border);background:rgba(255,255,255,.02)}
  .ep-split-toolbar .sw{flex:1;min-width:260px}
  .ep-row-actions{display:flex;align-items:center;gap:6px;white-space:nowrap}
  .ep-row-actions .btn-icon{width:32px;min-width:32px;height:32px;justify-content:center}
  .ep-split-table th:last-child,.ep-split-table td:last-child{width:88px}
  .ep-split-table th:nth-child(8),.ep-split-table td:nth-child(8){width:126px}
  .ep-split-table td:nth-child(8){white-space:nowrap}
  .ep-right-placeholder{border:1px dashed var(--border2);border-radius:10px;padding:16px;color:var(--text3);font-size:12px;line-height:1.5;background:var(--bg3)}
  @media (max-width:1280px){.ep-workspace,.ep-workspace.wide-detail,.ep-health-grid,.ep-queue{grid-template-columns:1fr}.ep-kpi-row{grid-template-columns:repeat(3,minmax(0,1fr))}.ep-code-grid{grid-template-columns:1fr}}
  @media (max-width:760px){.ep-alert-strip{display:grid}.ep-alert-items{justify-content:flex-start}.ep-kpi-row{grid-template-columns:1fr 1fr}}
  .info-tile{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:10px 12px;min-width:0}
  .info-tile-value{margin-top:6px;min-width:0;overflow-wrap:anywhere}
  .mi-hero-band{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(320px,.9fr);gap:16px;margin:12px 0 18px;padding:22px 24px;border-radius:22px;border:1px solid #cfe0ea;background:radial-gradient(1100px 260px at 5% -10%, rgba(13,110,253,.10), transparent 55%),radial-gradient(700px 180px at 100% 0%, rgba(15,118,110,.10), transparent 50%),linear-gradient(135deg,#f8fcff 0%,#eff7fb 52%,#f9fbfd 100%);box-shadow:0 18px 34px rgba(15,26,44,.06)}
  .mi-hero-copy{display:flex;flex-direction:column;gap:10px}
  .mi-hero-kicker{font-size:10px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#0f5b8d;font-family:var(--font-m)}
  .mi-hero-title{font-size:28px;line-height:1.18;font-weight:800;color:#10213a;max-width:760px}
  .mi-hero-note{font-size:13px;line-height:1.6;color:#53657b;max-width:760px}
  .mi-chip-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:2px}
  .mi-chip{display:inline-flex;align-items:center;padding:7px 12px;border-radius:999px;border:1px solid #c7d8e4;background:rgba(255,255,255,.76);font-size:11px;font-weight:700;color:#16324d;font-family:var(--font-m)}
  .mi-hero-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
  .mi-metric{padding:16px 16px 14px;border-radius:16px;border:1px solid #d5e4ee;background:rgba(255,255,255,.86);box-shadow:0 8px 16px rgba(15,26,44,.04)}
  .mi-metric-label{font-size:10px;font-weight:800;letter-spacing:1.7px;text-transform:uppercase;color:#5e7388;font-family:var(--font-m);margin-bottom:8px}
  .mi-metric-value{font-size:24px;font-weight:800;line-height:1.05;color:#10213a}
  .mi-metric-detail{font-size:11px;line-height:1.5;color:#61758a;margin-top:6px}
  .mi-workspace-shell{border:1px solid #d9e6ee;border-radius:20px;background:linear-gradient(180deg,#fbfdff,#f6fbfe);overflow:hidden;box-shadow:0 14px 28px rgba(15,26,44,.05)}
  .mi-workspace-header{padding:16px 18px 0}
  .mi-workspace-title{font-size:14px;font-weight:800;color:#10213a}
  .mi-workspace-subtitle{font-size:12px;line-height:1.5;color:#63748b;margin-top:4px}
  .mi-intake-grid{grid-template-columns:minmax(320px,.9fr) minmax(0,1.1fr)}
  .mi-upload-panel{display:flex;flex-direction:column;gap:14px}
  .mi-upload-guidance{padding:14px 16px;border:1px solid #d8e4ed;border-radius:16px;background:#f7fbfe}
  .mi-guidance-title{font-size:11px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;color:#48647b;font-family:var(--font-m);margin-bottom:8px}
  .mi-guidance-list{margin:0;padding-left:18px;color:#51667a;font-size:12px;line-height:1.7}
  .mi-guidance-list li + li{margin-top:6px}
  .copilot-hero{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(300px,.8fr);gap:16px;margin:14px 0 18px;padding:22px 24px;border-radius:22px;border:1px solid #d7e4ed;background:radial-gradient(900px 240px at 0% 0%, rgba(14,116,144,.10), transparent 55%),radial-gradient(700px 200px at 100% 0%, rgba(37,99,235,.08), transparent 50%),linear-gradient(135deg,#f8fcff 0%,#f1f8fb 52%,#fbfdff 100%);box-shadow:0 18px 32px rgba(15,26,44,.06)}
  .copilot-hero-copy{display:flex;flex-direction:column;gap:10px}
  .copilot-hero-kicker{font-size:10px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#0f5b8d;font-family:var(--font-m)}
  .copilot-hero-title{font-size:26px;line-height:1.22;font-weight:800;color:#10213a}
  .copilot-hero-note{font-size:13px;line-height:1.6;color:#55687b;max-width:760px}
  .copilot-hero-status{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
  .copilot-status-card{padding:15px 16px;border-radius:16px;border:1px solid #d6e3ec;background:rgba(255,255,255,.86);box-shadow:0 8px 16px rgba(15,26,44,.04)}
  .copilot-status-label{font-size:10px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;color:#61758a;font-family:var(--font-m);margin-bottom:7px}
  .copilot-status-value{font-size:21px;font-weight:800;color:#10213a;line-height:1.15}
  .copilot-grid{grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);gap:14px}
  .copilot-rail{display:flex;flex-direction:column;gap:14px}
  .copilot-suggestion-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:14px}
  .copilot-suggestion-card{border:1px solid #d7e3ed;background:#f7fbfe;border-radius:16px;padding:14px 14px;text-align:left;font-size:12px;font-weight:700;color:#17324a;line-height:1.45;cursor:pointer;transition:all .15s}
  .copilot-suggestion-card:hover{border-color:#b9d3e3;background:#ffffff;box-shadow:0 10px 18px rgba(15,26,44,.05)}
  .copilot-action-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .run-error{font-size:11px;color:var(--red);max-width:280px;white-space:normal;overflow-wrap:anywhere;line-height:1.45}
  .row-subtext{font-size:10px;color:var(--text3);overflow-wrap:anywhere;line-height:1.45}
  .tables-stage,.dashboard-stage{display:flex;flex-direction:column;gap:18px;max-width:1480px;margin:0 auto}
  .tables-stage{width:100%}
  .tables-hero{background:
    radial-gradient(1200px 280px at 10% -10%, rgba(23,198,255,.12), transparent 55%),
    radial-gradient(900px 280px at 100% 0%, rgba(124,92,255,.10), transparent 52%),
    linear-gradient(135deg, rgba(255,255,255,.96), rgba(246,250,255,.94));
    border:1px solid var(--border);
    border-radius:24px;
    padding:26px 28px 24px;
    box-shadow:0 14px 34px rgba(15,26,44,.08)}
  .tables-hero-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(360px,.9fr);gap:18px;align-items:stretch}
  .tables-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
  .tables-kpi{background:rgba(255,255,255,.84);border:1px solid rgba(213,220,229,.9);border-radius:18px;padding:18px 18px 16px;box-shadow:0 8px 18px rgba(15,26,44,.05)}
  .tables-kpi-label{font-size:10px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase;color:var(--text3);font-family:var(--font-m);margin-bottom:12px}
  .tables-kpi-value{font-size:32px;line-height:1;font-weight:800;font-family:var(--font-h);margin-bottom:8px}
  .tables-kpi-note{font-size:12px;color:var(--text3);line-height:1.45}
  .tables-surface{background:#111f34;border:1px solid #294260;border-radius:18px;overflow:hidden;box-shadow:0 16px 34px rgba(3,8,16,.24)}
  .tables-toolbar{display:flex;align-items:center;gap:12px;padding:16px 18px;background:#14243b;border-bottom:1px solid #294260}
  .tables-toolbar .sw input,.tables-toolbar select{background:#0f1d31;border-color:#355174;color:#e5edf8}
  .tables-toolbar .sw input::placeholder{color:#91a6c1}
  .tables-toolbar .sw input:focus,.tables-toolbar select:focus{border-color:rgba(23,198,255,.58);box-shadow:0 0 0 3px rgba(23,198,255,.12)}
  .tables-table table,.tables-table tbody{background:#111f34}
  .tables-table thead th{background:#172741;color:#9db0ca;border-bottom:1px solid #294260}
  .tables-table tbody td{padding:15px 16px;color:#c7d5e8}
  .tables-table tbody tr{border-bottom:1px solid #294260}
  .tables-table tbody tr:hover{background:#162842}
  .tables-table .td-main{font-size:14px;font-weight:800;color:#f3f8ff}
  .tables-table .td-mono{font-size:11px;color:#9db0ca}
  .theme-light .tables-surface{background:rgba(255,255,255,.94);border-color:rgba(213,220,229,.92);box-shadow:0 16px 34px rgba(15,26,44,.08)}
  .theme-light .tables-toolbar{background:linear-gradient(180deg,rgba(248,250,255,.98),rgba(243,247,253,.96));border-bottom-color:var(--border)}
  .theme-light .tables-toolbar .sw input,.theme-light .tables-toolbar select{background:#fff;border-color:#d6deea;color:#10213a}
  .theme-light .tables-toolbar .sw input::placeholder{color:#8da0b7}
  .theme-light .tables-toolbar .sw input:focus,.theme-light .tables-toolbar select:focus{border-color:rgba(0,102,204,.55);box-shadow:0 0 0 3px rgba(0,102,204,.10)}
  .theme-light .tables-table table,.theme-light .tables-table tbody{background:#fff}
  .theme-light .tables-table thead th{background:#f7f9fc;color:#64748b;border-bottom-color:#e5eaf1}
  .theme-light .tables-table tbody td{color:#415268}
  .theme-light .tables-table tbody tr{border-bottom-color:#ecf0f5}
  .theme-light .tables-table tbody tr:hover{background:rgba(0,102,204,.03)}
  .theme-light .tables-table .td-main{color:#142033}
  .theme-light .tables-table .td-mono{color:#64748b}
  .tables-empty{padding:46px 22px}
  .tables-note{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border-radius:999px;background:rgba(0,102,204,.07);color:var(--accent);font-size:11px;font-weight:700}
  .tables-chip{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.72);border:1px solid rgba(213,220,229,.95);color:var(--text2);font-size:11px;font-weight:700}
  .dashboard-hero{background:
    radial-gradient(760px 260px at 8% -8%, rgba(23,198,255,.12), transparent 58%),
    radial-gradient(620px 220px at 100% 0%, rgba(124,92,255,.10), transparent 52%),
    linear-gradient(135deg, rgba(255,255,255,.98), rgba(246,250,255,.95));
    border:1px solid var(--border);
    border-radius:18px;
    padding:22px 24px;
    box-shadow:0 16px 36px rgba(15,26,44,.08)}
  .dashboard-hero-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(420px,.7fr);gap:18px;align-items:stretch}
  .dashboard-hero-title{font-size:34px;line-height:1.08;font-weight:800;font-family:var(--font-h);letter-spacing:0;max-width:720px}
  .dashboard-hero-desc{font-size:14px;line-height:1.65;color:var(--text3);max-width:760px;margin-top:12px}
  .dashboard-hero-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
  .dashboard-chip-row{display:flex;gap:10px;flex-wrap:wrap;margin-top:0}
  .dashboard-chip{display:inline-flex;align-items:center;gap:8px;min-height:34px;padding:8px 13px;border-radius:999px;background:#102842;border:1px solid #3a5b82;color:#f3f8ff;font-size:12px;font-weight:850;line-height:1;font-family:var(--font-d);box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}
  .dashboard-chip::before{content:'';width:6px;height:6px;border-radius:999px;background:#8ea3c2}
  .dashboard-chip.ok{border-color:rgba(20,184,166,.36);background:rgba(20,184,166,.10);color:#81f3dc}
  .dashboard-chip.ok::before{background:#20e0bd;box-shadow:0 0 10px rgba(32,224,189,.45)}
  .dashboard-chip.danger{border-color:rgba(248,113,113,.42);background:rgba(248,113,113,.10);color:#ffb4b4}
  .dashboard-chip.danger::before{background:#ff6b6b;box-shadow:0 0 10px rgba(255,107,107,.45)}
  .dashboard-status-card{background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(247,250,255,.88));border:1px solid rgba(213,220,229,.94);border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:14px;box-shadow:0 12px 28px rgba(15,26,44,.06)}
  .dashboard-status-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
  .dashboard-status-title{font-size:18px;font-weight:800;font-family:var(--font-h);color:var(--text)}
  .dashboard-status-subtitle{font-size:12px;color:var(--text3);line-height:1.55;margin-top:4px}
  .dashboard-status-pill{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:rgba(4,120,87,.08);border:1px solid rgba(4,120,87,.14);font-size:11px;font-weight:800;color:var(--green);font-family:var(--font-m)}
  .dashboard-mini-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
  .dashboard-mini-card{background:#fff;border:1px solid #e3eaf3;border-radius:12px;padding:15px 16px 13px;box-shadow:0 8px 16px rgba(15,26,44,.04)}
  .dashboard-mini-label{font-size:10px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;color:var(--text3);font-family:var(--font-m);margin-bottom:10px}
  .dashboard-mini-value{font-size:30px;line-height:1;font-weight:800;font-family:var(--font-h)}
  .dashboard-mini-note{font-size:12px;color:var(--text3);margin-top:8px;line-height:1.45}
  .dashboard-stat-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
  .dashboard-operator-card{background:rgba(255,255,255,.96);border:1px solid rgba(213,220,229,.94);border-radius:14px;padding:18px 18px 16px;box-shadow:0 12px 26px rgba(15,26,44,.05)}
  .dashboard-operator-label{font-size:10px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;color:var(--text3);font-family:var(--font-m);margin-bottom:10px}
  .dashboard-operator-title{font-size:26px;line-height:1.02;font-weight:800;font-family:var(--font-h);color:var(--text)}
  .dashboard-operator-note{font-size:12px;color:var(--text3);line-height:1.55;margin-top:8px}
  .dashboard-operator-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:14px;padding-top:14px;border-top:1px solid #edf1f6;font-size:12px;color:var(--text2)}
  .surface-panel{background:rgba(255,255,255,.95);border:1px solid rgba(213,220,229,.94);border-radius:22px;overflow:hidden;box-shadow:0 14px 32px rgba(15,26,44,.08)}
  .surface-panel-header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:16px 18px;background:#14243b;border-bottom:1px solid #294260}
  .surface-panel-title{font-size:14px;font-weight:800;font-family:var(--font-h);color:var(--text)}
  .surface-panel-subtitle{font-size:12px;color:var(--text3);margin-top:3px}
  .surface-panel table,.surface-panel tbody{background:#fff}
  .surface-panel table thead th{background:#f7f9fc;color:#64748b;border-bottom:1px solid #e5eaf1}
  .surface-panel table tbody td{padding:15px 16px;color:#415268}
  .surface-panel table tbody tr{border-bottom:1px solid #ecf0f5}
  .surface-panel table tbody tr:hover{background:rgba(0,102,204,.03)}
  .surface-panel .td-main{font-size:14px;font-weight:700;color:#142033}
  .surface-panel .td-mono{font-size:11px;color:#64748b}
  .surface-panel-empty{padding:44px 20px}
  .surface-panel-body{padding:0}
  .dashboard-copilot{background:linear-gradient(135deg,#ffffff,#f7f1ff 55%,#eef4ff);border:1px solid rgba(186,164,255,.42);border-radius:24px;padding:20px 22px;box-shadow:0 16px 32px rgba(15,26,44,.08)}
  .dashboard-copilot-title{display:flex;align-items:center;gap:10px;margin-bottom:8px}
  .dashboard-copilot-desc{font-size:13px;line-height:1.7;color:var(--text2);margin-bottom:14px}
  .dashboard-hero,
  .dashboard-status-card,
  .dashboard-operator-card,
  .surface-panel,
  .dashboard-copilot{
    background:linear-gradient(135deg,#0f1b2f 0%,#14233d 52%,#10213a 100%);
    border-color:#233b5e;
    box-shadow:0 20px 40px rgba(8,16,28,.22);
  }
  .dashboard-mini-card{
    background:linear-gradient(180deg,#172942 0%,#14243b 100%);
    border-color:#2a446a;
    box-shadow:none;
  }
  .dashboard-hero-title,
  .dashboard-status-title,
  .surface-panel-title,
  .dashboard-operator-title{color:#f3f8ff}
  .dashboard-hero-desc,
  .dashboard-status-subtitle,
  .dashboard-mini-note,
  .dashboard-operator-note,
  .surface-panel-subtitle,
  .dashboard-copilot-desc{color:#aebed4}
  .dashboard-mini-label,
  .dashboard-operator-label,
  .surface-panel table thead th{color:#7f95b5}
  .surface-panel table,
  .surface-panel tbody{background:#10213a}
  .surface-panel-header{background:#14243b;border-bottom-color:#294260}
  .surface-panel table thead th{background:#172741;border-bottom-color:#243b5e}
  .surface-panel table tbody td{color:#bdd0e6}
  .surface-panel table tbody tr{border-bottom-color:#223754}
  .surface-panel table tbody tr:hover{background:rgba(255,255,255,.03)}
  .surface-panel .td-main{color:#f3f8ff}
  .surface-panel .td-mono{color:#8ea3c2}
  .dashboard-operator-foot{border-top-color:#223754;color:#96abc6}
  .theme-light .dashboard-hero{
    background:
      radial-gradient(760px 260px at 8% -8%, rgba(23,198,255,.12), transparent 58%),
      radial-gradient(620px 220px at 100% 0%, rgba(124,92,255,.10), transparent 52%),
      linear-gradient(135deg, rgba(255,255,255,.98), rgba(246,250,255,.95));
    border-color:#dbe5f0;
    box-shadow:0 16px 36px rgba(15,26,44,.08);
  }
  .theme-light .dashboard-status-card,
  .theme-light .dashboard-operator-card,
  .theme-light .surface-panel,
  .theme-light .dashboard-copilot{
    background:rgba(255,255,255,.96);
    border-color:rgba(213,220,229,.94);
    box-shadow:0 14px 32px rgba(15,26,44,.08);
  }
  .theme-light .dashboard-mini-card{background:#fff;border-color:#e3eaf3;box-shadow:0 8px 16px rgba(15,26,44,.04)}
  .theme-light .dashboard-hero-title,
  .theme-light .dashboard-status-title,
  .theme-light .surface-panel-title,
  .theme-light .dashboard-operator-title{color:#10213a}
  .theme-light .dashboard-hero-desc,
  .theme-light .dashboard-status-subtitle,
  .theme-light .dashboard-mini-note,
  .theme-light .dashboard-operator-note,
  .theme-light .surface-panel-subtitle,
  .theme-light .dashboard-copilot-desc{color:#64748b}
  .theme-light .surface-panel table,
  .theme-light .surface-panel tbody{background:#fff}
  .theme-light .surface-panel table thead th{background:#f7f9fc;color:#64748b;border-bottom-color:#e5eaf1}
  .theme-light .surface-panel table tbody td{color:#415268}
  .theme-light .surface-panel table tbody tr{border-bottom-color:#ecf0f5}
  .theme-light .surface-panel table tbody tr:hover{background:rgba(0,102,204,.03)}
  .theme-light .surface-panel .td-main{color:#142033}
  .theme-light .surface-panel .td-mono{color:#64748b}
  .theme-light .surface-panel-header{
    background:linear-gradient(180deg,rgba(248,250,255,.98),rgba(243,247,253,.96));
    border-bottom-color:#dbe5f0;
  }
  .theme-light .surface-panel-title{color:#10213a}
  .theme-light .dashboard-chip{background:#eef5fc;border-color:#c9d8e8;color:#243a55;box-shadow:none}
  .theme-light .dashboard-chip.ok{background:#e7f8f4;border-color:#a9ded2;color:#075f55}
  .theme-light .dashboard-chip.danger{background:#fff0f0;border-color:#f6bbbb;color:#a31818}
  .job-detail-page{background:linear-gradient(180deg,#0b1626 0%,#0f1d31 46%,#0b1626 100%);min-height:calc(100vh - 64px)}
  .job-back-row{margin-bottom:18px}
  .job-detail-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:18px}
  .job-title{font-size:22px;font-weight:850;color:#f3f8ff;line-height:1.2;margin-bottom:10px}
  .job-badge-row{display:flex;gap:8px;flex-wrap:wrap}
  .job-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
  .job-metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:18px}
  .job-metric-card{background:#13233a;border:1px solid #294260;border-radius:12px;padding:16px 18px;box-shadow:0 10px 24px rgba(3,8,16,.24)}
  .job-metric-label{font-size:10px;font-weight:850;letter-spacing:1.5px;text-transform:uppercase;color:#91a6c1;font-family:var(--font-m);margin-bottom:8px}
  .job-metric-value{font-size:22px;font-weight:850;font-family:var(--font-m)}
  .job-pipeline-card{background:#111f34;border-color:#294260;box-shadow:0 12px 28px rgba(3,8,16,.26)}
  .job-pipeline-card .card-header{background:#14243b;border-bottom-color:#294260;padding:16px 22px}
  .job-pipeline-body{padding:20px 24px}
  .job-pipeline-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:18px;padding-top:18px;border-top:1px solid #294260}
  .job-pipeline-summary-item{min-width:0}
  .job-summary-label{font-size:10px;font-weight:850;color:#91a6c1;letter-spacing:1.4px;text-transform:uppercase;font-family:var(--font-m);margin-bottom:6px}
  .job-summary-value{font-size:14px;font-weight:800;color:#f3f8ff;line-height:1.35}
  .job-detail-page .pnode{background:#14243b;border-color:#355174;min-width:132px;padding:12px 16px}
  .job-detail-page .pnode.done{border-color:#0f766e;background:rgba(15,118,110,.12)}
  .job-detail-page .pnode.fail{border-color:#e5484d;background:rgba(229,72,77,.12)}
  .job-detail-page .parr{background:#355174}
  .job-detail-page .parr::after{color:#6f88a8}
  .job-detail-page .tabs{background:#111f34;border-bottom-color:#294260}
  .job-detail-page .tab{font-size:13px;padding:13px 16px;color:#9db0ca}
  .job-detail-page .tab.active{color:#7be1ff;border-bottom-color:#17c6ff;background:#152842}
  .job-detail-page .filter-bar{background:#13233a;border-bottom-color:#294260;padding:14px 18px}
  .job-detail-page .log-row{grid-template-columns:160px 78px 160px minmax(180px,.6fr) minmax(260px,1fr) auto;gap:12px;padding:12px 18px;background:#111f34;border-bottom-color:#294260;font-size:12px}
  .job-detail-page .log-row:hover{background:#162842}
  .job-detail-page .card{background:#111f34;border-color:#294260;box-shadow:0 12px 28px rgba(3,8,16,.26)}
  .job-detail-page tbody td{font-size:13px;color:#c7d5e8}
  .job-detail-page thead th{background:#172741;color:#9db0ca;border-bottom-color:#294260}
  .theme-light .job-detail-page{background:linear-gradient(180deg,#eef7f8 0%,#f6fbfc 42%,#edf5f8 100%)}
  .theme-light .job-title{color:#10213a}
  .theme-light .job-metric-card{background:#fff;border-color:#cfdeea;box-shadow:0 8px 18px rgba(15,26,44,.05)}
  .theme-light .job-metric-label{color:#64748b}
  .theme-light .job-pipeline-card{background:#fff;border-color:#cfdeea;box-shadow:0 10px 22px rgba(15,26,44,.06)}
  .theme-light .job-pipeline-card .card-header{background:#fbfdff;border-bottom-color:#dbe6ef}
  .theme-light .job-pipeline-summary{border-top-color:#e2eaf3}
  .theme-light .job-summary-label{color:#64748b}
  .theme-light .job-summary-value{color:#142033}
  .theme-light .job-detail-page .pnode{background:#fbfdff;border-color:#b9ccdd}
  .theme-light .job-detail-page .pnode.done{border-color:#0f766e;background:#ecfdf8}
  .theme-light .job-detail-page .pnode.fail{border-color:#e5484d;background:#fff1f2}
  .theme-light .job-detail-page .parr{background:#b6c8da}
  .theme-light .job-detail-page .parr::after{color:#91a7bd}
  .theme-light .job-detail-page .tabs{background:#fff;border-bottom-color:#dbe6ef}
  .theme-light .job-detail-page .tab{color:#657892}
  .theme-light .job-detail-page .tab.active{color:#1d4ed8;border-bottom-color:#2563eb;background:#f7fbff}
  .theme-light .job-detail-page .filter-bar{background:#fbfdff;border-bottom-color:#dbe6ef}
  .theme-light .job-detail-page .log-row{background:#fff;border-bottom-color:#e1eaf3}
  .theme-light .job-detail-page .log-row:hover{background:#f6faff}
  .theme-light .job-detail-page .card{background:#fff;border-color:#cfdeea;box-shadow:0 10px 22px rgba(15,26,44,.06)}
  .theme-light .job-detail-page tbody td{color:#33465f}
  .theme-light .job-detail-page thead th{background:#f3f7fb;color:#60738d;border-bottom-color:#dbe6ef}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}.pulse{animation:pulse 2s infinite}
  @keyframes spin{to{transform:rotate(360deg)}}.spin{animation:spin .7s linear infinite;display:inline-block}
  .flex{display:flex}.fac{align-items:center}.fjb{justify-content:space-between}.gap2{gap:8px}.gap3{gap:12px}
  .mt2{margin-top:8px}.mt3{margin-top:12px}.mt4{margin-top:16px}.mb3{margin-bottom:12px}.mb4{margin-bottom:16px}.mb5{margin-bottom:20px}
  .text-accent{color:var(--accent)}.text-green{color:var(--green)}.text-red{color:var(--red)}.text-muted{color:var(--text3);font-size:12px}
  .text-success{color:var(--green)}.text-danger{color:var(--red)}.text-warning{color:var(--orange)}
  .font-mono{font-family:var(--font-m)}
  /* ── Workspace / Lineage / Drift / Settings ───────────────── */
  .sql-editor{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);font-family:var(--font-m);font-size:13px;color:var(--green);padding:16px;min-height:200px;resize:vertical;outline:none;width:100%;transition:border-color .15s;line-height:1.6}
  .sql-editor:focus{border-color:var(--accent2)}
  .result-table{overflow-x:auto}.result-table table{min-width:600px}
  .saved-query{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;cursor:pointer;transition:border-color .15s;margin-bottom:8px}
  .saved-query:hover{border-color:var(--border2)}
  .sq-name{font-size:13px;font-weight:600;margin-bottom:3px}.sq-sql{font-size:10px;font-family:var(--font-m);color:var(--text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .lineage-node{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:12px 16px;min-width:150px;text-align:center}
  .lineage-node.source{border-color:var(--accent2);background:rgba(0,212,255,.04)}
  .lineage-node.target{border-color:var(--green);background:rgba(0,229,160,.04)}
  .lineage-arrow{display:flex;align-items:center;color:var(--text3);font-size:18px;padding:0 8px}
  .drift-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--rl);padding:16px 18px;margin-bottom:12px;transition:border-color .15s}
  .drift-card.has-drift{border-color:rgba(255,184,0,.3);background:rgba(255,184,0,.03)}
  .drift-card.no-drift{border-color:rgba(0,229,160,.15)}
  .settings-title{font-size:13px;font-weight:700;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)}
  .settings-row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border)}
  .settings-row:last-child{border-bottom:none}
  .settings-key{font-size:12px;font-weight:600}.settings-desc{font-size:11px;color:var(--text3);margin-top:2px}
  .toggle{width:40px;height:22px;background:var(--border2);border-radius:11px;cursor:pointer;position:relative;transition:background .2s;flex-shrink:0}
  .toggle.on{background:var(--green)}
  .toggle::after{content:'';position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:white;transition:left .2s}
  .toggle.on::after{left:21px}
  .connector-matrix{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .conn-matrix-card{background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;display:flex;align-items:center;gap:10px}
  .conn-matrix-icon{font-size:18px;flex-shrink:0}.conn-matrix-name{font-size:12px;font-weight:600}.conn-matrix-status{margin-left:auto}
  /* ── Enterprise UX motion system ───────────────────────────── */
  :root{--motion-micro:150ms;--motion-page:220ms;--motion-panel:260ms;--motion-ease:cubic-bezier(.2,.8,.2,1)}
  @keyframes uxFadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
  @keyframes uxScaleIn{from{opacity:0;transform:scale(.985)}to{opacity:1;transform:scale(1)}}
  @keyframes uxProgress{from{transform:scaleX(0)}to{transform:scaleX(1)}}
  @keyframes uxSoftPulse{0%,100%{box-shadow:0 0 0 rgba(23,198,255,0)}50%{box-shadow:0 0 0 5px rgba(23,198,255,.08)}}
  .ux-page-transition{animation:uxFadeUp var(--motion-page) var(--motion-ease) both}
  .ux-card{background:linear-gradient(180deg,rgba(255,255,255,.9),rgba(246,251,253,.92));border:1px solid #b9e3ec;border-radius:8px;padding:16px;box-shadow:0 12px 30px rgba(15,63,79,.08);animation:uxFadeUp var(--motion-panel) var(--motion-ease) both;animation-delay:var(--ux-delay,0ms);color:#10213a}
  .app.theme-dark .ux-card{background:linear-gradient(180deg,rgba(18,38,48,.96),rgba(10,28,38,.96));border-color:#246476;color:#f0fbff}
  .ux-status{display:inline-flex;align-items:center;gap:6px;border-radius:999px;border:1px solid transparent;padding:3px 9px;font-family:var(--font-m);font-size:10px;font-weight:850;letter-spacing:.4px;text-transform:uppercase;white-space:nowrap}
  .ux-status::before{content:"";width:6px;height:6px;border-radius:999px;background:currentColor}
  .ux-status-success{background:#ecfdf3;color:#027a48;border-color:#abefc6}.ux-status-running{background:#eff8ff;color:#175cd3;border-color:#b2ddff;animation:uxSoftPulse 1.8s ease-in-out infinite}
  .ux-status-review,.ux-status-warning{background:#fffaeb;color:#b54708;border-color:#fedf89}.ux-status-danger{background:#fef3f2;color:#b42318;border-color:#fecdca}.ux-status-info{background:#eef4ff;color:#3538cd;border-color:#c7d7fe}.ux-status-neutral{background:#f2f4f7;color:#475467;border-color:#d0d5dd}
  .ux-journey-rail{display:grid;grid-template-columns:repeat(9,minmax(92px,1fr));gap:0;margin:0 0 18px;overflow:auto;padding:4px 0 10px}
  .ux-journey-stage{position:relative;display:grid;grid-template-columns:34px minmax(92px,1fr);gap:8px;align-items:start;min-width:124px;animation:uxFadeUp var(--motion-panel) var(--motion-ease) both;animation-delay:var(--ux-delay,0ms)}
  .ux-journey-node{width:30px;height:30px;border-radius:999px;display:grid;place-items:center;background:#f2f4f7;border:1px solid #d0d5dd;color:#475467;font-size:11px;font-weight:900;font-family:var(--font-m);position:relative;z-index:1}
  .ux-journey-success .ux-journey-node{background:#ecfdf3;color:#027a48;border-color:#7ce0af}.ux-journey-running .ux-journey-node{background:#eff8ff;color:#175cd3;border-color:#84caff;animation:uxSoftPulse 1.5s ease-in-out infinite}.ux-journey-review .ux-journey-node,.ux-journey-warning .ux-journey-node{background:#fffaeb;color:#b54708;border-color:#fedf89}.ux-journey-danger .ux-journey-node{background:#fef3f2;color:#b42318;border-color:#fecdca}
  .ux-journey-copy{min-width:0}.ux-journey-label{font-size:12px;font-weight:850;margin-bottom:6px;color:var(--text)}.ux-journey-detail{font-size:10px;color:var(--text3);line-height:1.35;margin-top:5px;max-width:160px}.ux-journey-line{position:absolute;left:30px;right:8px;top:15px;height:2px;background:#dbe7ee;z-index:0}
  .app.theme-dark .ux-journey-line{background:#255160}.ux-checklist{display:grid;gap:8px}.ux-check-row{display:grid;grid-template-columns:28px minmax(0,1fr) auto;gap:10px;align-items:center;padding:11px 12px;border:1px solid #dcebf1;border-radius:8px;background:#fbfdff;animation:uxFadeUp var(--motion-panel) var(--motion-ease) both;animation-delay:var(--ux-delay,0ms)}
  .app.theme-dark .ux-check-row{background:#0f2a35;border-color:#235566}.ux-check-icon{width:24px;height:24px;border-radius:999px;display:grid;place-items:center;background:#f2f4f7;color:#475467;font-weight:900}.ux-check-success .ux-check-icon{background:#ecfdf3;color:#027a48}.ux-check-running .ux-check-icon{background:#eff8ff;color:#175cd3;animation:spin .75s linear infinite}.ux-check-danger .ux-check-icon{background:#fef3f2;color:#b42318}.ux-check-warning .ux-check-icon{background:#fffaeb;color:#b54708}
  .ux-check-label{font-size:13px;font-weight:800;color:var(--text)}.ux-check-detail{font-size:11px;color:var(--text3);margin-top:2px;line-height:1.45}
  .ux-run-timeline{display:grid;gap:10px}.ux-run-phase{border:1px solid #dcebf1;border-radius:8px;padding:12px;background:#fbfdff;animation:uxScaleIn var(--motion-panel) var(--motion-ease) both;animation-delay:var(--ux-delay,0ms)}.app.theme-dark .ux-run-phase{background:#0f2a35;border-color:#235566}
  .ux-run-phase-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.ux-run-label{font-size:13px;font-weight:850;color:var(--text)}.ux-run-detail{font-size:11px;color:var(--text3);margin-top:3px}.ux-progress{height:6px;border-radius:999px;background:#e8f1f5;overflow:hidden;margin:11px 0 8px}.ux-progress span{display:block;height:100%;background:linear-gradient(90deg,#0891b2,#22c55e);transform-origin:left;animation:uxProgress var(--motion-panel) var(--motion-ease) both}.ux-run-meta{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--text3);font-size:11px;font-family:var(--font-m)}
  .ux-link-button{border:0;background:transparent;color:#0891b2;font-weight:800;cursor:pointer;padding:0}.ux-skeleton-wrap{display:grid;gap:10px}.ux-skeleton-row{display:grid;grid-template-columns:20px minmax(120px,1fr) 90px;gap:10px;align-items:center}.ux-skeleton-dot,.ux-skeleton-line,.ux-skeleton-short{height:12px;border-radius:999px;background:linear-gradient(90deg,#edf4f7,#d9e7ee,#edf4f7);background-size:200% 100%;animation:pulse 1.4s ease-in-out infinite}.ux-skeleton-dot{width:12px;height:12px}.ux-skeleton-short{max-width:90px}
  .ux-error-state{display:flex;gap:12px;padding:14px;border-radius:8px;background:#fef3f2;border:1px solid #fecdca;color:#7a271a}.ux-error-icon{width:26px;height:26px;border-radius:999px;background:#fee4e2;display:grid;place-items:center;font-weight:900}.ux-error-title{font-weight:900}.ux-error-message{font-size:12px;line-height:1.5;margin-top:3px}
  .ux-tool-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.ux-tool-card{display:flex;flex-direction:column;min-height:178px;transition:transform var(--motion-micro) var(--motion-ease),border-color var(--motion-micro),box-shadow var(--motion-micro)}.ux-tool-card:hover{transform:translateY(-2px);border-color:#68c7d9;box-shadow:0 16px 36px rgba(8,145,178,.14)}.ux-tool-disabled{opacity:.68}.ux-tool-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex:1}.ux-tool-name{font-size:16px;font-weight:900;margin-bottom:8px}.ux-tool-desc{font-size:13px;color:var(--text3);line-height:1.5}.ux-tool-foot{margin-top:18px}
  .ux-review-card{width:100%;text-align:left;border:1px solid #dcebf1;background:#fbfdff;border-radius:8px;padding:13px;cursor:pointer;display:grid;gap:8px;animation:uxFadeUp var(--motion-panel) var(--motion-ease) both;transition:border-color var(--motion-micro),transform var(--motion-micro)}.ux-review-card:hover,.ux-review-card.active{border-color:#38bdf8;transform:translateY(-1px)}.app.theme-dark .ux-review-card{background:#0f2a35;border-color:#235566}.ux-review-card-head{display:flex;gap:7px;flex-wrap:wrap}.ux-review-title{font-size:13px;font-weight:900;color:var(--text)}.ux-review-meta,.ux-review-finding,.ux-review-action{font-size:11px;line-height:1.45;color:var(--text3)}.ux-review-action{color:#0891b2;font-weight:800}
  .ux-transcript-section{animation:uxFadeUp var(--motion-panel) var(--motion-ease) both}.ux-capability-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px}.ux-capability{border:1px solid #dcebf1;border-radius:8px;padding:8px;background:#fbfdff}.ux-capability-label{font-size:10px;color:var(--text3);margin-bottom:5px}.ux-capability-value{font-size:12px;font-weight:900;color:var(--text)}
  @media (prefers-reduced-motion: reduce){*,*::before,*::after{animation-duration:1ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:1ms!important}.ux-card,.ux-page-transition,.ux-check-row,.ux-run-phase,.ux-review-card,.ux-journey-stage{animation:none!important}}
  @media (max-width:1100px){.ux-journey-rail{grid-template-columns:repeat(9,140px)}.ux-check-row{grid-template-columns:28px minmax(0,1fr)}.ux-check-row .ux-status{justify-self:start}}
  /* ── Product quality hardening components ─────────────────── */
  .pq-page{max-width:1680px;width:100%;margin:0 auto}
  .pq-command-cards{margin-bottom:18px}
  .pq-master-detail{display:grid;grid-template-columns:minmax(500px,1fr) minmax(340px,.58fr);gap:14px;align-items:start}
  .pq-detail-panel{background:#ffffff;border:1px solid #dbe5f0;border-radius:10px;box-shadow:0 14px 32px rgba(15,26,44,.08);overflow:hidden;min-width:0;color:#10213a}
  .pq-detail-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:18px;border-bottom:1px solid #e2eaf3;background:linear-gradient(180deg,#f9fbfe,#f3f7fb)}
  .pq-eyebrow{font-size:10px;font-weight:850;letter-spacing:1.4px;text-transform:uppercase;color:#2563eb;font-family:var(--font-m);margin-bottom:6px}
  .pq-detail-title{font-size:18px;font-weight:850;color:#10213a;line-height:1.2;overflow-wrap:anywhere}
  .pq-detail-subtitle{font-size:12px;line-height:1.5;color:#64748b;margin-top:5px;overflow-wrap:anywhere}
  .pq-detail-section{padding:16px 18px;border-bottom:1px solid #edf2f7}
  .pq-detail-section:last-child{border-bottom:0}
  .pq-detail-section-title{font-size:11px;font-weight:850;letter-spacing:1px;text-transform:uppercase;color:#64748b;font-family:var(--font-m);margin-bottom:12px}
  .pq-kpi-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .pq-code-block{white-space:pre-wrap;overflow:auto;max-height:380px;background:#f6f9fd;border:1px solid #dbe5f0;border-radius:8px;padding:12px;color:#20344d;font-family:var(--font-m);font-size:11px;line-height:1.6}
  .brain-code-compare{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;margin-top:12px}
  .brain-code-pane{min-width:0}
  .brain-code-head{display:flex;justify-content:space-between;gap:10px;align-items:center;font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);margin-bottom:6px}
  .brain-code-file{font-size:11px;color:var(--text2);margin-bottom:8px;overflow-wrap:anywhere}
  .brain-code-block{max-height:520px;min-height:320px;white-space:pre;overflow:auto}
  @media (max-width:1120px){.brain-code-compare{grid-template-columns:1fr}.brain-code-block{min-height:220px}}
  .pq-result-grid{max-width:100%;overflow:auto;border:1px solid #e3eaf3;border-radius:8px;background:#fff}
  .pq-result-grid table{min-width:720px}
  .pq-intel-grid .pq-result-grid table{min-width:100%;table-layout:fixed}
  .pq-intel-grid .pq-result-grid td,.pq-intel-grid .pq-result-grid th{white-space:normal;overflow-wrap:anywhere}
  .pq-result-grid thead th{background:#f7f9fc;color:#64748b;border-bottom:1px solid #e5eaf1}
  .pq-result-grid tbody td{color:#415268}
  .pq-empty-compact{padding:22px 14px}
  .pq-loading-panel{display:flex;align-items:center;justify-content:center;gap:9px;min-height:140px;color:var(--text3);font-size:12px}
  .pq-error-panel{margin:0 0 14px}
  .pq-action-row{display:flex;gap:8px;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid #edf2f7;background:#fbfdff}
  .pq-catalog-list,.pq-job-list{min-width:0}
  .pq-side-section{padding:16px 18px;border-top:1px solid var(--border)}
  .pq-list-button{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;text-align:left;background:transparent;border:0;border-bottom:1px solid var(--border);padding:12px 14px;color:var(--text2);cursor:pointer;font-family:var(--font-d)}
  .pq-list-button:hover{background:rgba(37,99,235,.08)}
  .pq-list-button span:first-child{font-size:12px;font-weight:780;color:var(--text)}
  .pq-list-button span:last-child{font-size:10px;color:var(--text3);font-family:var(--font-m)}
  .pq-intel-grid{display:grid;grid-template-columns:minmax(360px,.65fr) minmax(0,1fr);gap:18px}
  .pq-codegen-grid{display:grid;grid-template-columns:minmax(360px,430px) minmax(0,1fr);gap:18px;align-items:start}
  .pq-codegen-sidebar{min-width:0}
  .pq-review-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:14px}
  .pq-review-form .fg:nth-child(n+3){grid-column:1/-1}
  .pq-sqlw-shell{height:calc(100vh - 150px);min-height:660px}
  .pq-sqlw-body{height:100%;grid-template-columns:260px minmax(0,1fr) 260px}
  .pq-sql-main{grid-template-rows:minmax(310px,1fr) 300px}
  .pq-editor-toolbar{min-height:42px}
  .pq-sql-results{grid-template-rows:40px minmax(0,1fr)}
  .pq-explorer-picker{padding:12px;border-bottom:1px solid #dbe6ef;background:#fbfdff}
  .pq-connection-meta{display:flex;gap:8px;margin-top:8px}
  .pq-tree-select{padding:8px}
  .theme-dark .pq-detail-panel{background:linear-gradient(180deg,rgba(17,30,49,.96),rgba(13,24,40,.96));border-color:var(--border);color:var(--text)}
  .theme-dark .pq-detail-header{background:linear-gradient(180deg,#172942,#14243b);border-color:var(--border)}
  .theme-dark .pq-detail-title{color:var(--text)}
  .theme-dark .pq-detail-subtitle{color:var(--text3)}
  .theme-dark .pq-detail-section{border-color:var(--border)}
  .theme-dark .pq-code-block,.theme-dark .pq-result-grid{background:var(--bg3);border-color:var(--border);color:var(--text2)}
  .theme-dark .pq-result-grid thead th{background:#1b2d47;color:#aab9ce;border-bottom-color:var(--border)}
  .theme-dark .pq-result-grid tbody td{color:var(--text2)}
  .theme-dark .pq-action-row,.theme-dark .pq-explorer-picker{background:#14243b;border-color:#294260}
  .theme-dark .pq-loading-panel{color:#9db0ca}
  .theme-dark .sqlw-page{background:linear-gradient(180deg,#0b1626 0%,#0f1d31 46%,#0b1626 100%)}
  .theme-dark .sqlw-head{background:#0f1d31;border-bottom-color:#294260}
  .theme-dark .sqlw-title{color:#f3f8ff}
  .theme-dark .sqlw-sub,.theme-dark .sqlw-kicker{color:#9db0ca}
  .theme-dark .sqlw-shell{background:#111f34;border-color:#294260;box-shadow:0 22px 52px rgba(3,8,16,.32)}
  .theme-dark .sqlw-body,.theme-dark .sqlw-main{background:#0f1d31}
  .theme-dark .sqlw-explorer,.theme-dark .sqlw-inspector,.theme-dark .sqlw-panel-head,.theme-dark .sqlw-tabs,.theme-dark .sqlw-tab,.theme-dark .sqlw-tab-add,.theme-dark .sqlw-editor-area,.theme-dark .sqlw-editor-wrap,.theme-dark .sqlw-results,.theme-dark .sqlw-result-tabs{background:#111f34;border-color:#294260}
  .theme-dark .sqlw-panel-title{color:#f3f8ff}
  .theme-dark .sqlw-node,.theme-dark .sqlw-table-row{color:#c7d5e8}
  .theme-dark .sqlw-table-row:hover{background:#172b46}
  .theme-dark .sqlw-table-row.active{background:#17365c;color:#7be1ff}
  .theme-dark .sqlw-editor-toolbar{background:#14243b;border-bottom-color:#294260}
  .theme-dark .sqlw-gutter{background:#0f1d31;border-right-color:#294260;color:#6f88a8}
  .theme-dark .sqlw-editor{background:#111f34;color:#e5edf8}
  .theme-dark .sqlw-editor:focus{background:#13233a}
  .theme-dark .sqlw-result-tabs{border-bottom-color:#294260}
  .theme-dark .sqlw-result-tab{color:#9db0ca;border-right-color:#294260}
  .theme-dark .sqlw-result-tab.active{background:#14243b;color:#7be1ff}
  .theme-dark .sqlw-empty{color:#9db0ca}
  .theme-dark .sqlw-inspect-section{background:#111f34;border-color:#294260}
  .theme-dark .sqlw-inspect-title{background:#14243b;border-bottom-color:#294260;color:#9db0ca}
  .theme-dark .sqlw-kv{border-bottom-color:#294260}
  .theme-dark .sqlw-kv span:first-child{color:#9db0ca}
  .theme-dark .sqlw-kv span:last-child{color:#e5edf8}

  /* ── UI hardening layer: shared layout safety ─────────────── */
  #root,.app,.main,.page{min-width:0}
  .main{overflow-x:hidden}
  .page{width:100%;max-width:100%;overflow-x:hidden}
  .page > *, .pq-page, .dashboard-stage, .tables-stage, .agent-surface, .sqlw-page{min-width:0}
  .page-title,
  .hero-title,
  .dashboard-hero-title,
  .mi-hero-title,
  .copilot-hero-title,
  .tables-kpi-value,
  .stat-value,
  .job-title{
    overflow-wrap:anywhere;
    max-width:100%;
  }
  .page-title{font-size:clamp(24px,2.4vw,34px);line-height:1.12}
  .page-subtitle,.hero-desc,.mi-hero-note,.copilot-hero-note{max-width:72ch}
  .page-header,.card-header,.modal-hdr,.job-detail-head,.surface-panel-header{
    min-width:0;
  }
  .page-actions,.hero-actions,.modal-foot,.job-actions,.copilot-action-row{
    flex-wrap:wrap;
  }
  .card,.stat-card,.info-tile,.ux-card,.pq-detail-panel,.surface-panel,.tables-surface,.mi-workspace-shell,.copilot-status-card,.dashboard-operator-card{
    min-width:0;
    border-radius:8px;
  }
  .card-header,.surface-panel-header,.pq-detail-header{
    align-items:flex-start;
  }
  .card-title,.surface-panel-title,.pq-detail-title,.settings-title,.td-main{
    overflow-wrap:anywhere;
  }
  .text-muted,.row-subtext,.td-mono,.info-tile-value,.pq-detail-subtitle{
    overflow-wrap:anywhere;
  }
  table{table-layout:auto}
  th,td{max-width:420px}
  td,.td-main,.td-mono{overflow-wrap:anywhere}
  .table-scroll,.result-table,.pq-result-grid,.dashboard-table-wrap{
    max-width:100%;
    overflow:auto;
    -webkit-overflow-scrolling:touch;
  }
  .table-scroll table,.result-table table,.pq-result-grid table{
    min-width:min(760px, calc(100vw - 40px));
  }
  .filter-bar,.tables-toolbar,.pq-action-row{
    flex-wrap:wrap;
  }
  .filter-bar > *,.tables-toolbar > *,.pq-action-row > *{
    min-width:0;
  }
  .sw{min-width:180px}
  .fi,input,select,textarea,button{max-width:100%}
  .btn{min-height:34px;justify-content:center;white-space:normal;text-align:center;line-height:1.2}
  .btn-icon{width:34px;min-width:34px;white-space:nowrap}
  .badge,.spill,.ux-status,.uma-mini-badge{max-width:100%;white-space:normal;line-height:1.25}
  pre,code,.pq-code-block,.brain-code-block{
    max-width:100%;
    overflow:auto;
  }
  .stats-grid,.dashboard-stat-grid,.source-grid,.connector-matrix,.soft-grid,.fr,.pq-kpi-grid{
    min-width:0;
  }
  .stats-grid{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
  .dashboard-stat-grid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
  .source-grid,.connector-matrix{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
  .two-col{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
  .mi-hero-band,.copilot-hero,.tables-hero-grid,.pq-intel-grid,.pq-codegen-grid,.pq-master-detail{
    min-width:0;
  }
  .mi-hero-band,.copilot-hero{
    grid-template-columns:minmax(0,1fr);
    border-radius:12px;
  }
  .tables-hero{border-radius:12px;padding:22px}
  .tables-hero-grid{grid-template-columns:minmax(0,1fr)}
  .tables-kpis,.mi-hero-metrics,.copilot-hero-status{
    grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  }
  .pq-master-detail,.pq-intel-grid,.pq-codegen-grid{
    grid-template-columns:minmax(0,1fr);
  }
  .ux-journey-rail{
    padding-bottom:12px;
    scrollbar-width:thin;
  }
  .ux-journey-stage{min-width:136px}
  .pipe{overflow:auto;padding-bottom:8px}
  .pnode{min-width:116px}
  .lineage-node{min-width:128px}
  .modal{max-width:min(720px,calc(100vw - 32px))}
  .modal-lg{max-width:min(920px,calc(100vw - 32px))}
  .modal-body{min-width:0}
  .settings-row{gap:16px}
  .settings-row > div:first-child{min-width:0}
  .sqlw-shell,.pq-sqlw-shell{max-width:100%;min-width:0}
  .sqlw-commandbar,.sqlw-body,.pq-sqlw-body{min-width:0}
  .sqlw-main,.sqlw-explorer,.sqlw-inspector,.sqlw-editor-area,.sqlw-results{min-width:0}
  .sqlw-context,.sqlw-statusline,.sqlw-tabs,.sqlw-editor-toolbar,.pq-editor-toolbar{
    overflow:auto;
    scrollbar-width:thin;
  }
  .sqlw-tab,.sqlw-result-tab,.pq-editor-toolbar .btn{white-space:nowrap}

  /* ── UMA purple/white operating skin ─────────────────────── */
  .app.theme-dark,
  .app.theme-light{
    --bg:#2a145f;
    --bg1:#211047;
    --bg2:#ffffff;
    --bg3:#f6f2ff;
    --border:#ded6ff;
    --border2:#bba7ff;
    --text:#1b1434;
    --text2:#3f335f;
    --text3:#6c6286;
    --accent:#6d28d9;
    --accent2:#8b5cf6;
    --green:#047857;
    --yellow:#b7791f;
    --red:#b91c1c;
    --purple:#6d28d9;
    --orange:#c2410c;
    background:
      radial-gradient(900px 420px at 20% -10%, rgba(255,255,255,.20), transparent 58%),
      radial-gradient(920px 520px at 100% 10%, rgba(16,185,129,.12), transparent 56%),
      linear-gradient(180deg,#351779 0%,#241052 48%,#190b3a 100%);
    color:#1b1434;
  }
  .app.theme-dark body,
  .app.theme-light body{background:#241052}
  .app.theme-dark .sidebar,
  .app.theme-light .sidebar{
    background:linear-gradient(180deg,#2e126f 0%,#211047 56%,#170b35 100%);
    border-right:1px solid rgba(255,255,255,.22);
    box-shadow:18px 0 40px rgba(17,8,40,.18);
  }
  .app.theme-dark .topbar,
  .app.theme-light .topbar{
    background:rgba(35,16,79,.94);
    border-bottom:1px solid rgba(255,255,255,.22);
    box-shadow:0 12px 34px rgba(17,8,40,.20);
  }
  .app.theme-dark .logo-name,
  .app.theme-light .logo-name,
  .app.theme-dark .topbar-title,
  .app.theme-light .topbar-title{color:#ffffff}
  .app.theme-dark .logo-sub,
  .app.theme-light .logo-sub,
  .app.theme-dark .topbar-sub,
  .app.theme-light .topbar-sub,
  .app.theme-dark .nav-lbl,
  .app.theme-light .nav-lbl{color:#d8ccff}
  .app.theme-dark .logo-icon,
  .app.theme-light .logo-icon{
    background:#ffffff;
    color:#5b21b6;
  }
  .app.theme-dark .nav-item,
  .app.theme-light .nav-item{color:#eee8ff}
  .app.theme-dark .nav-item:hover,
  .app.theme-light .nav-item:hover{
    background:rgba(255,255,255,.12);
    color:#ffffff;
  }
  .app.theme-dark .nav-item.active,
  .app.theme-light .nav-item.active{
    background:#ffffff;
    border-color:#ffffff;
    color:#4c1d95;
    box-shadow:0 10px 24px rgba(0,0,0,.14);
  }
  .app.theme-dark .nav .nbadge,
  .app.theme-light .nav .nbadge{display:none}
  .app.theme-dark .sidebar-bot,
  .app.theme-light .sidebar-bot,
  .app.theme-dark .logo-wrap,
  .app.theme-light .logo-wrap{border-color:rgba(255,255,255,.18)}
  .app.theme-dark .topbar-user,
  .app.theme-light .topbar-user,
  .app.theme-dark .topbar-switcher,
  .app.theme-light .topbar-switcher{
    background:rgba(255,255,255,.12);
    border-color:rgba(255,255,255,.26);
  }
  .app.theme-dark .topbar-email,
  .app.theme-light .topbar-email,
  .app.theme-dark .topbar-status,
  .app.theme-light .topbar-status{color:#ffffff}
  .app.theme-dark .topbar-switcher .fi,
  .app.theme-light .topbar-switcher .fi{
    background:#ffffff;
    color:#1b1434;
    border-color:#d9ccff;
  }
  .app.theme-dark .topbar-avatar,
  .app.theme-light .topbar-avatar{
    background:#ffffff;
    color:#5b21b6;
    box-shadow:0 10px 24px rgba(255,255,255,.18);
  }
  .app.theme-dark .page,
  .app.theme-light .page{
    background:transparent;
    color:#1b1434;
  }
  .app.theme-dark .card,
  .app.theme-light .card,
  .app.theme-dark .modal,
  .app.theme-light .modal,
  .app.theme-dark .stat-card,
  .app.theme-light .stat-card,
  .app.theme-dark .surface-panel,
  .app.theme-light .surface-panel,
  .app.theme-dark .dashboard-hero,
  .app.theme-light .dashboard-hero,
  .app.theme-dark .dashboard-status-card,
  .app.theme-light .dashboard-status-card,
  .app.theme-dark .dashboard-mini-card,
  .app.theme-light .dashboard-mini-card,
  .app.theme-dark .dashboard-operator-card,
  .app.theme-light .dashboard-operator-card,
  .app.theme-dark .tables-hero,
  .app.theme-light .tables-hero,
  .app.theme-dark .tables-surface,
  .app.theme-light .tables-surface,
  .app.theme-dark .pq-detail-panel,
  .app.theme-light .pq-detail-panel{
    background:#ffffff;
    border-color:#ded6ff;
    color:#1b1434;
    box-shadow:0 20px 44px rgba(17,8,40,.18);
  }
  .app.theme-dark .card-header,
  .app.theme-light .card-header,
  .app.theme-dark .surface-panel-header,
  .app.theme-light .surface-panel-header,
  .app.theme-dark .tables-toolbar,
  .app.theme-light .tables-toolbar,
  .app.theme-dark .filter-bar,
  .app.theme-light .filter-bar,
  .app.theme-dark .tabs,
  .app.theme-light .tabs,
  .app.theme-dark .pq-action-row,
  .app.theme-light .pq-action-row,
  .app.theme-dark .pq-detail-header,
  .app.theme-light .pq-detail-header{
    background:#f4f0ff;
    border-color:#ded6ff;
    color:#1b1434;
  }
  .app.theme-dark .dashboard-hero-title,
  .app.theme-light .dashboard-hero-title,
  .app.theme-dark .dashboard-status-title,
  .app.theme-light .dashboard-status-title,
  .app.theme-dark .dashboard-operator-title,
  .app.theme-light .dashboard-operator-title,
  .app.theme-dark .surface-panel-title,
  .app.theme-light .surface-panel-title,
  .app.theme-dark .card-title,
  .app.theme-light .card-title,
  .app.theme-dark .page-title,
  .app.theme-light .page-title,
  .app.theme-dark .pq-detail-title,
  .app.theme-light .pq-detail-title,
  .app.theme-dark .td-main,
  .app.theme-light .td-main{color:#1b1434}
  .app.theme-dark .dashboard-hero-desc,
  .app.theme-light .dashboard-hero-desc,
  .app.theme-dark .dashboard-status-subtitle,
  .app.theme-light .dashboard-status-subtitle,
  .app.theme-dark .dashboard-mini-note,
  .app.theme-light .dashboard-mini-note,
  .app.theme-dark .dashboard-operator-note,
  .app.theme-light .dashboard-operator-note,
  .app.theme-dark .surface-panel-subtitle,
  .app.theme-light .surface-panel-subtitle,
  .app.theme-dark .text-muted,
  .app.theme-light .text-muted,
  .app.theme-dark .row-subtext,
  .app.theme-light .row-subtext,
  .app.theme-dark .pq-detail-subtitle,
  .app.theme-light .pq-detail-subtitle{color:#6c6286}
  .app.theme-dark .page-eyebrow,
  .app.theme-light .page-eyebrow,
  .app.theme-dark .dashboard-mini-label,
  .app.theme-light .dashboard-mini-label,
  .app.theme-dark .dashboard-operator-label,
  .app.theme-light .dashboard-operator-label,
  .app.theme-dark .stat-label,
  .app.theme-light .stat-label,
  .app.theme-dark .pq-eyebrow,
  .app.theme-light .pq-eyebrow,
  .app.theme-dark .pq-detail-section-title,
  .app.theme-light .pq-detail-section-title{color:#6d28d9}
  .app.theme-dark table,
  .app.theme-light table,
  .app.theme-dark tbody,
  .app.theme-light tbody,
  .app.theme-dark .surface-panel table,
  .app.theme-light .surface-panel table,
  .app.theme-dark .surface-panel tbody,
  .app.theme-light .surface-panel tbody,
  .app.theme-dark .tables-table table,
  .app.theme-light .tables-table table,
  .app.theme-dark .tables-table tbody,
  .app.theme-light .tables-table tbody{background:#ffffff}
  .app.theme-dark thead th,
  .app.theme-light thead th,
  .app.theme-dark .surface-panel table thead th,
  .app.theme-light .surface-panel table thead th,
  .app.theme-dark .tables-table thead th,
  .app.theme-light .tables-table thead th{
    background:#efe9ff;
    color:#5b4b79;
    border-bottom-color:#ded6ff;
  }
  .app.theme-dark tbody td,
  .app.theme-light tbody td,
  .app.theme-dark .surface-panel table tbody td,
  .app.theme-light .surface-panel table tbody td,
  .app.theme-dark .tables-table tbody td,
  .app.theme-light .tables-table tbody td{
    color:#31264b;
    border-bottom-color:#ece6ff;
  }
  .app.theme-dark tbody tr,
  .app.theme-light tbody tr,
  .app.theme-dark .surface-panel table tbody tr,
  .app.theme-light .surface-panel table tbody tr,
  .app.theme-dark .tables-table tbody tr,
  .app.theme-light .tables-table tbody tr{border-bottom-color:#ece6ff}
  .app.theme-dark tbody tr:hover,
  .app.theme-light tbody tr:hover,
  .app.theme-dark .surface-panel table tbody tr:hover,
  .app.theme-light .surface-panel table tbody tr:hover,
  .app.theme-dark .tables-table tbody tr:hover,
  .app.theme-light .tables-table tbody tr:hover{background:#faf8ff}
  .app.theme-dark .td-mono,
  .app.theme-light .td-mono,
  .app.theme-dark .tables-table .td-mono,
  .app.theme-light .tables-table .td-mono,
  .app.theme-dark .surface-panel .td-mono,
  .app.theme-light .surface-panel .td-mono{color:#5b4b79}
  .app.theme-dark .btn-primary,
  .app.theme-light .btn-primary{
    background:#6d28d9;
    color:#ffffff;
    border:1px solid #6d28d9;
  }
  .app.theme-dark .btn-primary:hover,
  .app.theme-light .btn-primary:hover{
    background:#5b21b6;
    box-shadow:0 10px 24px rgba(109,40,217,.24);
  }
  .app.theme-dark .btn-ghost,
  .app.theme-light .btn-ghost{
    background:#ffffff;
    color:#4c1d95;
    border:1px solid #bba7ff;
  }
  .app.theme-dark .btn-ghost:hover,
  .app.theme-light .btn-ghost:hover{
    background:#f4f0ff;
    color:#3b0764;
  }
  .app.theme-dark .badge,
  .app.theme-light .badge{font-weight:850}
  .app.theme-dark .bg,
  .app.theme-light .bg,
  .app.theme-dark .dashboard-chip.ok,
  .app.theme-light .dashboard-chip.ok{
    background:#dcfce7;
    border-color:#86efac;
    color:#047857;
  }
  .app.theme-dark .br,
  .app.theme-light .br,
  .app.theme-dark .dashboard-chip.danger,
  .app.theme-light .dashboard-chip.danger{
    background:#fee2e2;
    border-color:#fca5a5;
    color:#b91c1c;
  }
  .app.theme-dark .bb,
  .app.theme-light .bb,
  .app.theme-dark .bp,
  .app.theme-light .bp,
  .app.theme-dark .dashboard-chip,
  .app.theme-light .dashboard-chip{
    background:#f4f0ff;
    border-color:#c4b5fd;
    color:#5b21b6;
  }
  .app.theme-dark .bgr,
  .app.theme-light .bgr{
    background:#f6f2ff;
    border-color:#ded6ff;
    color:#5b4b79;
  }
  .app.theme-dark .dashboard-status-pill,
  .app.theme-light .dashboard-status-pill{
    background:#dcfce7;
    border-color:#86efac;
    color:#047857;
  }
  .app.theme-dark .sw,
  .app.theme-light .sw,
  .app.theme-dark .info-tile,
  .app.theme-light .info-tile,
  .app.theme-dark .pq-code-block,
  .app.theme-light .pq-code-block,
  .app.theme-dark .pq-result-grid,
  .app.theme-light .pq-result-grid{
    background:#f8f5ff;
    border-color:#ded6ff;
    color:#1b1434;
  }
  .app.theme-dark input,
  .app.theme-light input,
  .app.theme-dark select,
  .app.theme-light select,
  .app.theme-dark textarea,
  .app.theme-light textarea,
  .app.theme-dark .fi,
  .app.theme-light .fi,
  .app.theme-dark .tables-toolbar .sw input,
  .app.theme-light .tables-toolbar .sw input,
  .app.theme-dark .tables-toolbar select,
  .app.theme-light .tables-toolbar select{
    background:#ffffff;
    border-color:#cfc3ff;
    color:#1b1434;
  }
  .app.theme-dark input::placeholder,
  .app.theme-light input::placeholder,
  .app.theme-dark textarea::placeholder,
  .app.theme-light textarea::placeholder{color:#8a7ba8}
  .app.theme-dark input:focus,
  .app.theme-light input:focus,
  .app.theme-dark select:focus,
  .app.theme-light select:focus,
  .app.theme-dark textarea:focus,
  .app.theme-light textarea:focus,
  .app.theme-dark .fi:focus,
  .app.theme-light .fi:focus{
    border-color:#7c3aed;
    box-shadow:0 0 0 3px rgba(124,58,237,.14);
  }
  .app.theme-dark .sqlw-page,
  .app.theme-light .sqlw-page,
  .app.theme-dark .job-detail-page,
  .app.theme-light .job-detail-page,
  .app.theme-dark .agent-surface,
  .app.theme-light .agent-surface{
    background:transparent;
    color:#1b1434;
  }
  .app.theme-dark .sqlw-head,
  .app.theme-light .sqlw-head{
    background:#ffffff;
    border-bottom-color:#ded6ff;
  }
  .app.theme-dark .sqlw-title,
  .app.theme-light .sqlw-title,
  .app.theme-dark .sqlw-panel-title,
  .app.theme-light .sqlw-panel-title{color:#1b1434}
  .app.theme-dark .sqlw-sub,
  .app.theme-light .sqlw-sub,
  .app.theme-dark .sqlw-kicker,
  .app.theme-light .sqlw-kicker{color:#6c6286}
  .app.theme-dark .sqlw-shell,
  .app.theme-light .sqlw-shell,
  .app.theme-dark .sqlw-explorer,
  .app.theme-light .sqlw-explorer,
  .app.theme-dark .sqlw-inspector,
  .app.theme-light .sqlw-inspector,
  .app.theme-dark .sqlw-body,
  .app.theme-light .sqlw-body,
  .app.theme-dark .sqlw-main,
  .app.theme-light .sqlw-main,
  .app.theme-dark .sqlw-editor-area,
  .app.theme-light .sqlw-editor-area,
  .app.theme-dark .sqlw-results,
  .app.theme-light .sqlw-results{
    background:#ffffff;
    border-color:#ded6ff;
    color:#1b1434;
  }
  .app.theme-dark .sqlw-panel-head,
  .app.theme-light .sqlw-panel-head,
  .app.theme-dark .sqlw-editor-toolbar,
  .app.theme-light .sqlw-editor-toolbar,
  .app.theme-dark .sqlw-result-tabs,
  .app.theme-light .sqlw-result-tabs,
  .app.theme-dark .sqlw-tabs,
  .app.theme-light .sqlw-tabs,
  .app.theme-dark .sqlw-tab,
  .app.theme-light .sqlw-tab,
  .app.theme-dark .sqlw-tab-add,
  .app.theme-light .sqlw-tab-add{
    background:#f4f0ff;
    border-color:#ded6ff;
    color:#4c1d95;
  }
  .app.theme-dark .sqlw-editor-wrap,
  .app.theme-light .sqlw-editor-wrap,
  .app.theme-dark .sqlw-editor,
  .app.theme-light .sqlw-editor{
    background:#ffffff;
    color:#1b1434;
  }
  .app.theme-dark .sqlw-gutter,
  .app.theme-light .sqlw-gutter{
    background:#f4f0ff;
    border-right-color:#ded6ff;
    color:#6c6286;
  }
  .app.theme-dark .sqlw-result-tab.active,
  .app.theme-light .sqlw-result-tab.active,
  .app.theme-dark .sqlw-tab.active,
  .app.theme-light .sqlw-tab.active{
    background:#ffffff;
    color:#5b21b6;
  }
  .app.theme-dark .sqlw-node,
  .app.theme-light .sqlw-node,
  .app.theme-dark .sqlw-table-row,
  .app.theme-light .sqlw-table-row{color:#31264b}
  .app.theme-dark .sqlw-table-row:hover,
  .app.theme-light .sqlw-table-row:hover,
  .app.theme-dark .sqlw-table-row.active,
  .app.theme-light .sqlw-table-row.active{
    background:#f4f0ff;
    color:#4c1d95;
  }
  .app.theme-dark .sqlw-inspect-section,
  .app.theme-light .sqlw-inspect-section{
    background:#ffffff;
    border-color:#ded6ff;
  }
  .app.theme-dark .sqlw-inspect-title,
  .app.theme-light .sqlw-inspect-title{
    background:#f4f0ff;
    color:#5b4b79;
    border-bottom-color:#ded6ff;
  }
  .app.theme-dark .sqlw-kv,
  .app.theme-light .sqlw-kv{border-bottom-color:#ece6ff}
  .app.theme-dark .sqlw-kv span:first-child,
  .app.theme-light .sqlw-kv span:first-child{color:#6c6286}
  .app.theme-dark .sqlw-kv span:last-child,
  .app.theme-light .sqlw-kv span:last-child{color:#1b1434}
  /* ── Blue/teal operating skin override ───────────────────── */
  .app.theme-dark,
  .app.theme-light{
    --bg:#062f3a;
    --bg1:#042936;
    --bg2:#ffffff;
    --bg3:#f0fbfc;
    --border:#c9eaf0;
    --border2:#7dd3fc;
    --text:#102a32;
    --text2:#284854;
    --text3:#5f7882;
    --accent:#0891b2;
    --accent2:#14b8a6;
    --green:#047857;
    --yellow:#b7791f;
    --red:#b91c1c;
    --purple:#0e7490;
    --orange:#c2410c;
    background:
      radial-gradient(900px 420px at 20% -10%, rgba(255,255,255,.18), transparent 58%),
      radial-gradient(920px 520px at 100% 10%, rgba(20,184,166,.18), transparent 56%),
      linear-gradient(180deg,#0f5f72 0%,#063747 48%,#031f2a 100%);
    color:#102a32;
  }
  .app.theme-dark body,
  .app.theme-light body{background:#063747}
  .app.theme-dark .sidebar,
  .app.theme-light .sidebar{
    background:linear-gradient(180deg,#0f5f72 0%,#063747 56%,#031f2a 100%);
    border-right-color:rgba(255,255,255,.22);
  }
  .app.theme-dark .topbar,
  .app.theme-light .topbar{
    background:rgba(5,48,62,.94);
    border-bottom-color:rgba(255,255,255,.22);
  }
  .app.theme-dark .logo-icon,
  .app.theme-light .logo-icon{
    background:#ffffff;
    color:#0e7490;
  }
  .app.theme-dark .nav-item.active,
  .app.theme-light .nav-item.active{
    background:#ffffff;
    border-color:#ffffff;
    color:#0e7490;
  }
  .app.theme-dark .topbar-avatar,
  .app.theme-light .topbar-avatar{
    background:#ffffff;
    color:#0e7490;
  }
  .app.theme-dark .card,
  .app.theme-light .card,
  .app.theme-dark .modal,
  .app.theme-light .modal,
  .app.theme-dark .stat-card,
  .app.theme-light .stat-card,
  .app.theme-dark .surface-panel,
  .app.theme-light .surface-panel,
  .app.theme-dark .dashboard-hero,
  .app.theme-light .dashboard-hero,
  .app.theme-dark .dashboard-status-card,
  .app.theme-light .dashboard-status-card,
  .app.theme-dark .dashboard-mini-card,
  .app.theme-light .dashboard-mini-card,
  .app.theme-dark .dashboard-operator-card,
  .app.theme-light .dashboard-operator-card,
  .app.theme-dark .tables-hero,
  .app.theme-light .tables-hero,
  .app.theme-dark .tables-surface,
  .app.theme-light .tables-surface,
  .app.theme-dark .pq-detail-panel,
  .app.theme-light .pq-detail-panel{
    background:#ffffff;
    border-color:#c9eaf0;
    color:#102a32;
    box-shadow:0 20px 44px rgba(3,31,42,.20);
  }
  .app.theme-dark .card-header,
  .app.theme-light .card-header,
  .app.theme-dark .surface-panel-header,
  .app.theme-light .surface-panel-header,
  .app.theme-dark .tables-toolbar,
  .app.theme-light .tables-toolbar,
  .app.theme-dark .filter-bar,
  .app.theme-light .filter-bar,
  .app.theme-dark .tabs,
  .app.theme-light .tabs,
  .app.theme-dark .pq-action-row,
  .app.theme-light .pq-action-row,
  .app.theme-dark .pq-detail-header,
  .app.theme-light .pq-detail-header{
    background:#e8f8fb;
    border-color:#c9eaf0;
    color:#102a32;
  }
  .app.theme-dark .dashboard-hero-title,
  .app.theme-light .dashboard-hero-title,
  .app.theme-dark .dashboard-status-title,
  .app.theme-light .dashboard-status-title,
  .app.theme-dark .dashboard-operator-title,
  .app.theme-light .dashboard-operator-title,
  .app.theme-dark .surface-panel-title,
  .app.theme-light .surface-panel-title,
  .app.theme-dark .card-title,
  .app.theme-light .card-title,
  .app.theme-dark .page-title,
  .app.theme-light .page-title,
  .app.theme-dark .pq-detail-title,
  .app.theme-light .pq-detail-title,
  .app.theme-dark .td-main,
  .app.theme-light .td-main{color:#102a32}
  .app.theme-dark .dashboard-hero-desc,
  .app.theme-light .dashboard-hero-desc,
  .app.theme-dark .dashboard-status-subtitle,
  .app.theme-light .dashboard-status-subtitle,
  .app.theme-dark .dashboard-mini-note,
  .app.theme-light .dashboard-mini-note,
  .app.theme-dark .dashboard-operator-note,
  .app.theme-light .dashboard-operator-note,
  .app.theme-dark .surface-panel-subtitle,
  .app.theme-light .surface-panel-subtitle,
  .app.theme-dark .text-muted,
  .app.theme-light .text-muted,
  .app.theme-dark .row-subtext,
  .app.theme-light .row-subtext,
  .app.theme-dark .pq-detail-subtitle,
  .app.theme-light .pq-detail-subtitle{color:#5f7882}
  .app.theme-dark .page-eyebrow,
  .app.theme-light .page-eyebrow,
  .app.theme-dark .dashboard-mini-label,
  .app.theme-light .dashboard-mini-label,
  .app.theme-dark .dashboard-operator-label,
  .app.theme-light .dashboard-operator-label,
  .app.theme-dark .stat-label,
  .app.theme-light .stat-label,
  .app.theme-dark .pq-eyebrow,
  .app.theme-light .pq-eyebrow,
  .app.theme-dark .pq-detail-section-title{color:#0891b2}
  .app.theme-light .pq-detail-section-title{color:#0891b2}
  .app.theme-dark thead th,
  .app.theme-light thead th,
  .app.theme-dark .surface-panel table thead th,
  .app.theme-light .surface-panel table thead th,
  .app.theme-dark .tables-table thead th,
  .app.theme-light .tables-table thead th{
    background:#e0f4f8;
    color:#315866;
    border-bottom-color:#c9eaf0;
  }
  .app.theme-dark tbody td,
  .app.theme-light tbody td,
  .app.theme-dark .surface-panel table tbody td,
  .app.theme-light .surface-panel table tbody td,
  .app.theme-dark .tables-table tbody td,
  .app.theme-light .tables-table tbody td{
    color:#284854;
    border-bottom-color:#d8eef3;
  }
  .app.theme-dark tbody tr,
  .app.theme-light tbody tr,
  .app.theme-dark .surface-panel table tbody tr,
  .app.theme-light .surface-panel table tbody tr,
  .app.theme-dark .tables-table tbody tr,
  .app.theme-light .tables-table tbody tr{border-bottom-color:#d8eef3}
  .app.theme-dark tbody tr:hover,
  .app.theme-light tbody tr:hover,
  .app.theme-dark .surface-panel table tbody tr:hover,
  .app.theme-light .surface-panel table tbody tr:hover,
  .app.theme-dark .tables-table tbody tr:hover,
  .app.theme-light .tables-table tbody tr:hover{background:#f4fcfd}
  .app.theme-dark .td-mono,
  .app.theme-light .td-mono,
  .app.theme-dark .tables-table .td-mono,
  .app.theme-light .tables-table .td-mono,
  .app.theme-dark .surface-panel .td-mono,
  .app.theme-light .surface-panel .td-mono{color:#4f6f7b}
  .app.theme-dark .btn-primary,
  .app.theme-light .btn-primary{
    background:#0891b2;
    color:#ffffff;
    border:1px solid #0891b2;
  }
  .app.theme-dark .btn-primary:hover,
  .app.theme-light .btn-primary:hover{
    background:#0e7490;
    box-shadow:0 10px 24px rgba(8,145,178,.24);
  }
  .app.theme-dark .btn-ghost,
  .app.theme-light .btn-ghost{
    background:#ffffff;
    color:#0e7490;
    border:1px solid #7dd3fc;
  }
  .app.theme-dark .btn-ghost:hover,
  .app.theme-light .btn-ghost:hover{
    background:#e8f8fb;
    color:#155e75;
  }
  .app.theme-dark .bb,
  .app.theme-light .bb,
  .app.theme-dark .bp,
  .app.theme-light .bp,
  .app.theme-dark .dashboard-chip,
  .app.theme-light .dashboard-chip{
    background:#e0f4f8;
    border-color:#7dd3fc;
    color:#0e7490;
  }
  .app.theme-dark .bgr,
  .app.theme-light .bgr{
    background:#f0fbfc;
    border-color:#c9eaf0;
    color:#4f6f7b;
  }
  .app.theme-dark .sw,
  .app.theme-light .sw,
  .app.theme-dark .info-tile,
  .app.theme-light .info-tile,
  .app.theme-dark .pq-code-block,
  .app.theme-light .pq-code-block,
  .app.theme-dark .pq-result-grid,
  .app.theme-light .pq-result-grid{
    background:#f0fbfc;
    border-color:#c9eaf0;
    color:#102a32;
  }
  .app.theme-dark input,
  .app.theme-light input,
  .app.theme-dark select,
  .app.theme-light select,
  .app.theme-dark textarea,
  .app.theme-light textarea,
  .app.theme-dark .fi,
  .app.theme-light .fi,
  .app.theme-dark .tables-toolbar .sw input,
  .app.theme-light .tables-toolbar .sw input,
  .app.theme-dark .tables-toolbar select,
  .app.theme-light .tables-toolbar select{
    background:#ffffff;
    border-color:#addde6;
    color:#102a32;
  }
  .app.theme-dark input:focus,
  .app.theme-light input:focus,
  .app.theme-dark select:focus,
  .app.theme-light select:focus,
  .app.theme-dark textarea:focus,
  .app.theme-light textarea:focus,
  .app.theme-dark .fi:focus,
  .app.theme-light .fi:focus{
    border-color:#0891b2;
    box-shadow:0 0 0 3px rgba(8,145,178,.14);
  }
  .app.theme-dark .sqlw-head,
  .app.theme-light .sqlw-head,
  .app.theme-dark .sqlw-shell,
  .app.theme-light .sqlw-shell,
  .app.theme-dark .sqlw-explorer,
  .app.theme-light .sqlw-explorer,
  .app.theme-dark .sqlw-inspector,
  .app.theme-light .sqlw-inspector,
  .app.theme-dark .sqlw-body,
  .app.theme-light .sqlw-body,
  .app.theme-dark .sqlw-main,
  .app.theme-light .sqlw-main,
  .app.theme-dark .sqlw-editor-area,
  .app.theme-light .sqlw-editor-area,
  .app.theme-dark .sqlw-results,
  .app.theme-light .sqlw-results{
    background:#ffffff;
    border-color:#c9eaf0;
    color:#102a32;
  }
  .app.theme-dark .sqlw-panel-head,
  .app.theme-light .sqlw-panel-head,
  .app.theme-dark .sqlw-editor-toolbar,
  .app.theme-light .sqlw-editor-toolbar,
  .app.theme-dark .sqlw-result-tabs,
  .app.theme-light .sqlw-result-tabs,
  .app.theme-dark .sqlw-tabs,
  .app.theme-light .sqlw-tabs,
  .app.theme-dark .sqlw-tab,
  .app.theme-light .sqlw-tab,
  .app.theme-dark .sqlw-tab-add,
  .app.theme-light .sqlw-tab-add,
  .app.theme-dark .sqlw-gutter,
  .app.theme-light .sqlw-gutter,
  .app.theme-dark .sqlw-inspect-title,
  .app.theme-light .sqlw-inspect-title{
    background:#e8f8fb;
    border-color:#c9eaf0;
    color:#0e7490;
  }
  .app.theme-dark .sqlw-result-tab.active,
  .app.theme-light .sqlw-result-tab.active,
  .app.theme-dark .sqlw-tab.active,
  .app.theme-light .sqlw-tab.active,
  .app.theme-dark .sqlw-table-row:hover,
  .app.theme-light .sqlw-table-row:hover,
  .app.theme-dark .sqlw-table-row.active,
  .app.theme-light .sqlw-table-row.active{
    background:#e0f4f8;
    color:#0e7490;
  }
  /* ── Final split theme: light white/teal, dark navy/teal ─── */
  .app.theme-light{
    --bg:#eef9fb;--bg1:#f8fcfd;--bg2:#ffffff;--bg3:#f0fbfc;
    --border:#c9eaf0;--border2:#7dd3fc;
    --text:#102a32;--text2:#284854;--text3:#5f7882;
    --accent:#0891b2;--accent2:#14b8a6;
    background:
      radial-gradient(900px 420px at 14% -12%, rgba(20,184,166,.14), transparent 58%),
      radial-gradient(900px 520px at 100% 6%, rgba(8,145,178,.12), transparent 56%),
      linear-gradient(180deg,#f8fcfd 0%,#eef9fb 100%);
    color:#102a32;
  }
  .app.theme-dark{
    --bg:#061b24;--bg1:#041720;--bg2:#0b2631;--bg3:#102f3b;
    --border:#1f5261;--border2:#2b7183;
    --text:#f3fbfc;--text2:#d7ebef;--text3:#9cc3ce;
    --accent:#22d3ee;--accent2:#2dd4bf;
    background:
      radial-gradient(900px 420px at 16% -12%, rgba(34,211,238,.14), transparent 58%),
      radial-gradient(900px 520px at 100% 8%, rgba(45,212,191,.12), transparent 56%),
      linear-gradient(180deg,#082b38 0%,#061b24 52%,#041720 100%);
    color:#f3fbfc;
  }
  .app.theme-light .sidebar{
    background:linear-gradient(180deg,#ffffff 0%,#eef9fb 100%);
    border-right-color:#c9eaf0;
    box-shadow:14px 0 34px rgba(6,47,58,.08);
  }
  .app.theme-dark .sidebar{
    background:linear-gradient(180deg,#082b38 0%,#061b24 62%,#041720 100%);
    border-right-color:#1f5261;
    box-shadow:14px 0 34px rgba(0,0,0,.24);
  }
  .app.theme-light .topbar{
    background:rgba(255,255,255,.94);
    border-bottom-color:#c9eaf0;
    box-shadow:0 10px 28px rgba(6,47,58,.08);
  }
  .app.theme-dark .topbar{
    background:rgba(6,27,36,.94);
    border-bottom-color:#1f5261;
    box-shadow:0 10px 28px rgba(0,0,0,.24);
  }
  .app.theme-light .logo-name,
  .app.theme-light .topbar-title,
  .app.theme-light .nav-item,
  .app.theme-light .topbar-email,
  .app.theme-light .topbar-status{color:#102a32}
  .app.theme-dark .logo-name,
  .app.theme-dark .topbar-title,
  .app.theme-dark .nav-item,
  .app.theme-dark .topbar-email,
  .app.theme-dark .topbar-status{color:#f3fbfc}
  .app.theme-light .logo-sub,
  .app.theme-light .topbar-sub,
  .app.theme-light .nav-lbl{color:#5f7882}
  .app.theme-dark .logo-sub,
  .app.theme-dark .topbar-sub,
  .app.theme-dark .nav-lbl{color:#9cc3ce}
  .app.theme-light .logo-icon,
  .app.theme-light .topbar-avatar{background:#0891b2;color:#ffffff}
  .app.theme-dark .logo-icon,
  .app.theme-dark .topbar-avatar{background:#22d3ee;color:#041720}
  .app.theme-light .nav-item:hover{background:#e0f4f8;color:#0e7490}
  .app.theme-dark .nav-item:hover{background:#102f3b;color:#ffffff}
  .app.theme-light .nav-item.active{
    background:#e0f4f8;
    border-color:#7dd3fc;
    color:#0e7490;
  }
  .app.theme-dark .nav-item.active{
    background:#123c4b;
    border-color:#22d3ee;
    color:#67e8f9;
  }
  .app.theme-light .topbar-user,
  .app.theme-light .topbar-switcher{background:#f0fbfc;border-color:#c9eaf0}
  .app.theme-dark .topbar-user,
  .app.theme-dark .topbar-switcher{background:#102f3b;border-color:#1f5261}
  .app.theme-light .card,
  .app.theme-light .modal,
  .app.theme-light .stat-card,
  .app.theme-light .surface-panel,
  .app.theme-light .dashboard-hero,
  .app.theme-light .dashboard-status-card,
  .app.theme-light .dashboard-mini-card,
  .app.theme-light .dashboard-operator-card,
  .app.theme-light .tables-hero,
  .app.theme-light .tables-surface,
  .app.theme-light .pq-detail-panel,
  .app.theme-light .sqlw-shell,
  .app.theme-light .sqlw-explorer,
  .app.theme-light .sqlw-inspector,
  .app.theme-light .sqlw-body,
  .app.theme-light .sqlw-main,
  .app.theme-light .sqlw-editor-area,
  .app.theme-light .sqlw-results{
    background:#ffffff;
    border-color:#c9eaf0;
    color:#102a32;
    box-shadow:0 18px 38px rgba(6,47,58,.10);
  }
  .app.theme-dark .card,
  .app.theme-dark .modal,
  .app.theme-dark .stat-card,
  .app.theme-dark .surface-panel,
  .app.theme-dark .dashboard-hero,
  .app.theme-dark .dashboard-status-card,
  .app.theme-dark .dashboard-mini-card,
  .app.theme-dark .dashboard-operator-card,
  .app.theme-dark .tables-hero,
  .app.theme-dark .tables-surface,
  .app.theme-dark .pq-detail-panel,
  .app.theme-dark .sqlw-shell,
  .app.theme-dark .sqlw-explorer,
  .app.theme-dark .sqlw-inspector,
  .app.theme-dark .sqlw-body,
  .app.theme-dark .sqlw-main,
  .app.theme-dark .sqlw-editor-area,
  .app.theme-dark .sqlw-results{
    background:#0b2631;
    border-color:#1f5261;
    color:#f3fbfc;
    box-shadow:0 18px 38px rgba(0,0,0,.24);
  }
  .app.theme-light .card-header,
  .app.theme-light .surface-panel-header,
  .app.theme-light .tables-toolbar,
  .app.theme-light .filter-bar,
  .app.theme-light .tabs,
  .app.theme-light .pq-action-row,
  .app.theme-light .pq-detail-header,
  .app.theme-light .sqlw-head,
  .app.theme-light .sqlw-panel-head,
  .app.theme-light .sqlw-editor-toolbar,
  .app.theme-light .sqlw-result-tabs,
  .app.theme-light .sqlw-tabs,
  .app.theme-light .sqlw-tab,
  .app.theme-light .sqlw-tab-add,
  .app.theme-light .sqlw-gutter,
  .app.theme-light .sqlw-inspect-title{
    background:#f4f8fb;
    border-color:#d9e6ee;
    color:#17324a;
  }
  .app.theme-dark .card-header,
  .app.theme-dark .surface-panel-header,
  .app.theme-dark .tables-toolbar,
  .app.theme-dark .filter-bar,
  .app.theme-dark .tabs,
  .app.theme-dark .pq-action-row,
  .app.theme-dark .pq-detail-header,
  .app.theme-dark .sqlw-head,
  .app.theme-dark .sqlw-panel-head,
  .app.theme-dark .sqlw-editor-toolbar,
  .app.theme-dark .sqlw-result-tabs,
  .app.theme-dark .sqlw-tabs,
  .app.theme-dark .sqlw-tab,
  .app.theme-dark .sqlw-tab-add,
  .app.theme-dark .sqlw-gutter,
  .app.theme-dark .sqlw-inspect-title{
    background:#102f3b;
    border-color:#1f5261;
    color:#f3fbfc;
  }
  .app.theme-light .dashboard-hero-title,
  .app.theme-light .dashboard-status-title,
  .app.theme-light .dashboard-operator-title,
  .app.theme-light .surface-panel-title,
  .app.theme-light .card-title,
  .app.theme-light .page-title,
  .app.theme-light .pq-detail-title,
  .app.theme-light .td-main,
  .app.theme-light .sqlw-title,
  .app.theme-light .sqlw-panel-title{color:#102a32}
  .app.theme-dark .dashboard-hero-title,
  .app.theme-dark .dashboard-status-title,
  .app.theme-dark .dashboard-operator-title,
  .app.theme-dark .surface-panel-title,
  .app.theme-dark .card-title,
  .app.theme-dark .page-title,
  .app.theme-dark .pq-detail-title,
  .app.theme-dark .td-main,
  .app.theme-dark .sqlw-title,
  .app.theme-dark .sqlw-panel-title{color:#f3fbfc}
  .app.theme-light .text-muted,
  .app.theme-light .dashboard-hero-desc,
  .app.theme-light .surface-panel-subtitle,
  .app.theme-light .dashboard-mini-note,
  .app.theme-light .dashboard-operator-note,
  .app.theme-light .pq-detail-subtitle,
  .app.theme-light .sqlw-sub,
  .app.theme-light .sqlw-kicker{color:#5f7882}
  .app.theme-dark .text-muted,
  .app.theme-dark .dashboard-hero-desc,
  .app.theme-dark .surface-panel-subtitle,
  .app.theme-dark .dashboard-mini-note,
  .app.theme-dark .dashboard-operator-note,
  .app.theme-dark .pq-detail-subtitle,
  .app.theme-dark .sqlw-sub,
  .app.theme-dark .sqlw-kicker{color:#9cc3ce}
  .app.theme-light .page-eyebrow,
  .app.theme-light .dashboard-mini-label,
  .app.theme-light .dashboard-operator-label,
  .app.theme-light .stat-label,
  .app.theme-light .pq-eyebrow,
  .app.theme-light .pq-detail-section-title{color:#0891b2}
  .app.theme-dark .page-eyebrow,
  .app.theme-dark .dashboard-mini-label,
  .app.theme-dark .dashboard-operator-label,
  .app.theme-dark .stat-label,
  .app.theme-dark .pq-eyebrow,
  .app.theme-dark .pq-detail-section-title{color:#67e8f9}
  .app.theme-light table,
  .app.theme-light tbody,
  .app.theme-light .surface-panel table,
  .app.theme-light .surface-panel tbody,
  .app.theme-light .tables-table table,
  .app.theme-light .tables-table tbody{background:#ffffff}
  .app.theme-dark table,
  .app.theme-dark tbody,
  .app.theme-dark .surface-panel table,
  .app.theme-dark .surface-panel tbody,
  .app.theme-dark .tables-table table,
  .app.theme-dark .tables-table tbody{background:#0b2631}
  .app.theme-light thead th,
  .app.theme-light .surface-panel table thead th,
  .app.theme-light .tables-table thead th{background:#e0f4f8;color:#315866;border-bottom-color:#c9eaf0}
  .app.theme-dark thead th,
  .app.theme-dark .surface-panel table thead th,
  .app.theme-dark .tables-table thead th{background:#123c4b;color:#9cc3ce;border-bottom-color:#1f5261}
  .app.theme-light tbody td,
  .app.theme-light .surface-panel table tbody td,
  .app.theme-light .tables-table tbody td{color:#284854;border-bottom-color:#d8eef3}
  .app.theme-dark tbody td,
  .app.theme-dark .surface-panel table tbody td,
  .app.theme-dark .tables-table tbody td{color:#d7ebef;border-bottom-color:#1f5261}
  .app.theme-light input,
  .app.theme-light select,
  .app.theme-light textarea,
  .app.theme-light .fi,
  .app.theme-light .sw,
  .app.theme-light .sw input,
  .app.theme-light .sqlw-editor,
  .app.theme-light .sqlw-editor-wrap,
  .app.theme-light .pq-code-block,
  .app.theme-light .pq-result-grid{background:#ffffff;border-color:#addde6;color:#102a32}
  .app.theme-dark input,
  .app.theme-dark select,
  .app.theme-dark textarea,
  .app.theme-dark .fi,
  .app.theme-dark .sw,
  .app.theme-dark .sw input,
  .app.theme-dark .sqlw-editor,
  .app.theme-dark .sqlw-editor-wrap,
  .app.theme-dark .pq-code-block,
  .app.theme-dark .pq-result-grid{background:#061b24;border-color:#1f5261;color:#f3fbfc}
  .app.theme-light .btn-primary{background:#0891b2;border-color:#0891b2;color:#ffffff}
  .app.theme-dark .btn-primary{background:#22d3ee;border-color:#22d3ee;color:#041720}
  .app.theme-light .btn-ghost{background:#ffffff;color:#0e7490;border-color:#7dd3fc}
  .app.theme-dark .btn-ghost{background:#102f3b;color:#d7fbff;border-color:#2b7183}
  .dashboard-stage{width:100%;min-width:0}
  .dashboard-panel-padding{padding:18px}
  .dashboard-section-note{font-size:12px;line-height:1.55;color:var(--text3);margin-top:12px}
  .dashboard-table-wrap{width:100%;overflow:auto}
  .dashboard-table{min-width:620px;table-layout:fixed}
  .dashboard-table th,.dashboard-table td{vertical-align:middle}
  .dashboard-table .dashboard-col-name{width:42%}
  .dashboard-table .dashboard-col-source{width:24%}
  .dashboard-table .dashboard-col-status{width:18%}
  .dashboard-table .dashboard-col-data{width:16%}
  .dashboard-table .dashboard-col-conn-name{width:46%}
  .dashboard-table .dashboard-col-conn-type{width:27%}
  .dashboard-table .dashboard-col-health,
  .dashboard-table .dashboard-col-conn-health{width:27%}
  .dashboard-cell-main{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dashboard-health{display:flex;align-items:center;gap:8px;min-width:0}
  .dashboard-health-label{font-size:12px;text-transform:capitalize;font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dashboard-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;min-height:220px;padding:38px 22px;text-align:center}
  .dashboard-empty-icon{width:38px;height:38px;border-radius:999px;display:grid;place-items:center;background:rgba(34,211,238,.10);border:1px solid rgba(34,211,238,.22);color:var(--accent)}
  .dashboard-empty-title{font-size:14px;font-weight:850;color:var(--text)}
  .dashboard-empty-copy{max-width:360px;font-size:12px;line-height:1.55;color:var(--text3)}
  .dashboard-operator-title{min-height:32px;overflow-wrap:anywhere}
  .dashboard-operator-card{min-width:0}
  .dashboard-operator-foot span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .surface-panel-header > div{min-width:0}
  .surface-panel-title,.surface-panel-subtitle{overflow-wrap:anywhere}
  /* ── Page-by-page hardening pass ──────────────────────────── */
  a:focus-visible,
  button:focus-visible,
  input:focus-visible,
  select:focus-visible,
  textarea:focus-visible,
  .tab:focus-visible,
  .nav-item:focus-visible,
  .nav-child:focus-visible{
    outline:3px solid color-mix(in srgb,var(--accent) 55%,transparent);
    outline-offset:2px;
  }
  .page-header-copy,.page-actions,.card-header > div,.pq-detail-header > div{min-width:0}
  .page-actions{justify-content:flex-end}
  .page-actions > .flex{flex-wrap:wrap;min-width:0}
  .card-header{justify-content:space-between}
  .card-header > .btn,.card-header > .flex,.card-header > button{flex:0 0 auto}
  tbody tr.is-selected,
  tbody tr.is-selected:hover{
    background:color-mix(in srgb,var(--accent) 14%,transparent);
  }
  .tbl td,.tbl th{min-width:0}
  .tbl td:last-child{max-width:520px}
  .pq-master-detail{
    grid-template-columns:minmax(500px,1fr) minmax(340px,.58fr);
  }
  .pq-intel-grid{
    grid-template-columns:minmax(360px,.65fr) minmax(0,1fr);
  }
  .pq-codegen-grid{
    grid-template-columns:minmax(360px,430px) minmax(0,1fr);
  }
  .mi-hero-band{
    grid-template-columns:minmax(0,1.5fr) minmax(320px,.9fr);
  }
  .copilot-hero{
    grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr);
  }
  .sqlw-result-body{
    min-height:0;
    overflow:auto;
    background:var(--bg2);
    color:var(--text);
  }
  .app.theme-light .sqlw-result-body{background:#ffffff;color:#102a32}
  .app.theme-dark .sqlw-result-body{background:#0b2631;color:#f3fbfc}
  .sqlw-head > div{min-width:0}
  .sqlw-statusline{min-width:0}
  .sqlw-pill{max-width:100%;overflow:hidden;text-overflow:ellipsis}
  .sqlw-table-row,.sqlw-node,.pq-list-button{overflow-wrap:anywhere}
  .sqlw-table-row > span,.sqlw-node > span,.pq-list-button > span{min-width:0}
  .tables-toolbar select,.filter-bar select{min-width:150px}
  .settings-row{align-items:flex-start}
  .settings-desc{line-height:1.45}
  .modal-hdr{gap:12px}
  .modal-title{min-width:0;overflow-wrap:anywhere}
  .modal-body{overflow-wrap:anywhere}
  .ux-tool-card,.ux-review-card,.uma-decision-card,.uma-connector-card{
    min-width:0;
  }
  .ux-tool-name,.ux-tool-desc,.ux-review-title,.ux-review-meta,.ux-review-finding,.ux-review-action,
  .uma-decision-name,.uma-decision-desc,.uma-connector-name,.uma-connector-copy{
    overflow-wrap:anywhere;
  }
  .brain-code-block,.pq-code-block,.raw-json{
    tab-size:2;
  }
  @media (max-width:1320px){
    .pq-master-detail{grid-template-columns:minmax(0,1fr)}
    .pq-detail-panel{max-height:none}
  }
  @media (max-width:960px){
    .main{margin-left:220px}
    .sidebar{width:220px;min-width:220px}
    .topbar{height:auto;min-height:64px;align-items:flex-start;padding:12px 18px}
    .topbar-controls{flex-wrap:wrap}
    .page{padding:22px 20px 34px}
    .page-header{align-items:flex-start;flex-direction:column}
    .page-actions{width:100%;justify-content:flex-start}
    .page-actions > .btn,
    .page-actions > button{min-width:148px}
    .pq-intel-grid,.pq-codegen-grid,.mi-hero-band,.mi-intake-grid,.copilot-hero,.copilot-grid{
      grid-template-columns:1fr;
    }
  }
  @media (max-width:760px){
    .stats-grid,.dashboard-stat-grid,.source-grid,.connector-matrix,.soft-grid,.fr,.pq-kpi-grid{
      grid-template-columns:1fr;
    }
    .filter-bar,.tables-toolbar,.pq-action-row{
      flex-direction:column;
      align-items:stretch;
    }
    .filter-bar > .sw,.tables-toolbar > .sw,.filter-bar select,.tables-toolbar select{
      width:100%;
      min-width:0;
    }
    .sqlw-shell,.pq-sqlw-shell{
      height:auto;
      min-height:0;
      margin:12px 0 18px;
      overflow:visible;
    }
    .sqlw-body,.pq-sqlw-body{
      display:block;
      height:auto;
    }
    .sqlw-explorer{
      min-height:360px;
      border-right:0;
      border-bottom:1px solid var(--border);
    }
    .sqlw-main,.pq-sql-main{
      display:grid;
      grid-template-rows:minmax(340px,42vh) minmax(320px,44vh);
      min-height:680px;
    }
    .sqlw-inspector{display:none}
  }
  @media (max-width:1100px){.two-col,.agent-chat-grid,.agent-work-grid{grid-template-columns:1fr}.source-grid{grid-template-columns:repeat(3,1fr)}.stats-grid,.dashboard-stat-grid{grid-template-columns:repeat(2,1fr)}.tables-hero-grid,.dashboard-hero-grid{grid-template-columns:1fr}.tables-kpis,.dashboard-mini-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.job-detail-head{align-items:flex-start;flex-direction:column}.job-actions{justify-content:flex-start}.job-metric-grid,.job-pipeline-summary{grid-template-columns:1fr}.job-detail-page .log-row{grid-template-columns:1fr;overflow-wrap:anywhere}.job-detail-page .log-row span{min-width:0;white-space:normal}}
  @media (max-width:1120px){.pq-master-detail,.pq-intel-grid,.pq-codegen-grid,.mi-hero-band,.mi-intake-grid,.copilot-hero,.copilot-grid{grid-template-columns:1fr}.mi-hero-metrics,.copilot-hero-status{grid-template-columns:repeat(2,minmax(0,1fr))}.pq-sqlw-body{grid-template-columns:280px minmax(0,1fr)}.pq-sqlw-body .sqlw-inspector{display:none}}
  @media (max-width:720px){.surface-panel-header{align-items:stretch;flex-direction:column}.surface-panel-header .btn{width:100%;justify-content:center}.dashboard-panel-padding{padding:14px}.dashboard-table{min-width:560px}.dashboard-operator-foot{align-items:flex-start;flex-direction:column}.dashboard-operator-foot span{white-space:normal}.dashboard-section-note{margin-top:10px}}
  @media (max-width:520px){.app{flex-direction:column}.sidebar{position:relative;width:100%;min-width:0;height:auto;max-height:210px;overflow:auto;border-right:0;border-bottom:1px solid var(--border)}.logo-wrap{padding:14px 16px 10px}.logo-sub{padding-left:40px}.nav{display:flex;gap:8px;padding:10px;overflow-x:auto}.nav-section{min-width:170px;margin-bottom:0}.sidebar-bot{display:none}.main{margin-left:0}.page{padding:16px}.topbar{position:relative;padding:12px 14px;height:auto;min-height:58px;align-items:stretch;flex-direction:column;justify-content:center}.topbar-title{font-size:13px}.fr,.source-grid,.stats-grid,.dashboard-stat-grid,.tables-kpis,.dashboard-mini-grid,.soft-grid{grid-template-columns:1fr}.hero{padding:18px}.hero-title{font-size:19px}.hero-stats{gap:14px;flex-wrap:wrap}.pipe{flex-direction:column}.parr{width:1px;height:18px}.parr::after{right:50%;top:auto;bottom:-8px;transform:translateX(50%) rotate(90deg)}.filter-bar,.tables-toolbar,.page-header,.topbar-controls,.dashboard-hero-actions,.topbar-switcher{flex-direction:column;align-items:stretch}.log-row{grid-template-columns:1fr}.job-detail-page .log-row{display:block}.job-detail-page .log-row span{display:block;margin-bottom:6px}.page-title{font-size:28px}.tables-hero,.dashboard-hero{padding:20px}.tables-surface,.surface-panel,.dashboard-copilot,.dashboard-status-card,.dashboard-operator-card{border-radius:18px}.dashboard-hero-title{font-size:28px;line-height:1.12}.topbar-switcher .fi{width:100%}.topbar-email{max-width:none}.pq-sqlw-shell{height:auto;min-height:0;margin:12px 0;overflow:visible}.pq-sqlw-body{display:block;height:auto}.sqlw-explorer{min-height:420px;border-right:0;border-bottom:1px solid #cbdbe7}.pq-sql-main{display:grid;grid-template-rows:320px 300px;min-height:620px}.sqlw-editor-wrap{grid-template-columns:42px minmax(0,1fr)}.sqlw-inspector{display:none}.pq-editor-toolbar{overflow-x:auto}.pq-editor-toolbar .btn{white-space:nowrap}}
  @media (max-width:760px){
    .stats-grid,.dashboard-stat-grid,.source-grid,.connector-matrix,.soft-grid,.fr,.pq-kpi-grid,.tables-kpis,.dashboard-mini-grid,.mi-hero-metrics,.copilot-hero-status{
      grid-template-columns:1fr;
    }
    .page-actions,.filter-bar,.tables-toolbar,.pq-action-row,.topbar-controls,.topbar-switcher{
      flex-direction:column;
      align-items:stretch;
    }
    .page-actions .btn,.filter-bar .btn,.tables-toolbar .btn,.pq-action-row .btn,.topbar-controls .btn{
      width:100%;
    }
    .pq-sqlw-shell{
      height:auto;
      min-height:0;
      margin:12px 0 18px;
      overflow:visible;
    }
    .pq-sqlw-body{
      display:block;
      height:auto;
    }
    .pq-sql-main{
      display:grid;
      grid-template-rows:minmax(340px,42vh) minmax(320px,44vh);
      min-height:680px;
    }
  }

  /* ── Production UI polish layer ─────────────────────────────
     Consolidates the older experimental skins into one calmer,
     enterprise workbench surface across every UMA module. */
  .app.theme-light{
    --bg:#f3f7fb;
    --bg1:#ffffff;
    --bg2:#ffffff;
    --bg3:#f7fafc;
    --border:#d7e2ea;
    --border2:#b8cad7;
    --text:#132238;
    --text2:#33475f;
    --text3:#687c91;
    --accent:#1f7a9b;
    --accent2:#0f766e;
    --green:#0f7b55;
    --yellow:#a16207;
    --red:#b42318;
    --purple:#4f46e5;
    --orange:#c2410c;
    background:
      radial-gradient(980px 420px at 4% -8%, rgba(31,122,155,.10), transparent 60%),
      radial-gradient(860px 460px at 100% 0%, rgba(15,118,110,.09), transparent 56%),
      linear-gradient(180deg,#fbfdff 0%,#f3f7fb 100%);
    color:var(--text);
  }
  .app.theme-dark{
    --bg:#071521;
    --bg1:#0b1b2a;
    --bg2:#102131;
    --bg3:#152c3e;
    --border:#284255;
    --border2:#3b6075;
    --text:#f3f8fb;
    --text2:#d5e3eb;
    --text3:#94aaba;
    --accent:#5bb7d4;
    --accent2:#4fd1c5;
    background:
      radial-gradient(920px 420px at 8% -10%, rgba(91,183,212,.12), transparent 60%),
      radial-gradient(860px 460px at 100% 0%, rgba(79,209,197,.10), transparent 56%),
      linear-gradient(180deg,#0b1b2a 0%,#071521 100%);
    color:var(--text);
  }
  .app.theme-light .sidebar{
    background:linear-gradient(180deg,#ffffff 0%,#f4f8fb 100%);
    border-right:1px solid var(--border);
    box-shadow:10px 0 28px rgba(19,34,56,.06);
  }
  .app.theme-dark .sidebar{
    background:linear-gradient(180deg,#0c2030 0%,#081722 100%);
    border-right:1px solid var(--border);
  }
  .logo-wrap{padding:22px 18px 16px}
  .logo-icon{border-radius:8px}
  .logo-name{font-size:15px;font-weight:850}
  .nav{padding:16px 10px}
  .nav-lbl{margin:16px 10px 7px;letter-spacing:.18em}
  .nav-section:first-child .nav-lbl{margin-top:0}
  .nav-item,.nav-child{
    min-height:36px;
    border-radius:8px;
    font-weight:760;
  }
  .app.theme-light .nav-item,.app.theme-light .nav-child{color:#32465f}
  .app.theme-light .nav-item:hover,.app.theme-light .nav-child:hover{
    background:#eef6fa;
    color:#123047;
  }
  .app.theme-light .nav-item.active,.app.theme-light .nav-child.active{
    background:#e7f4f8;
    border-color:#b7dce8;
    color:#0f6380;
    box-shadow:inset 3px 0 0 #1f7a9b;
  }
  .app.theme-dark .nav-item.active,.app.theme-dark .nav-child.active{
    background:#143346;
    border-color:#3b7891;
    color:#c9f4ff;
    box-shadow:inset 3px 0 0 var(--accent);
  }
  .main{background:transparent}
  .topbar{
    min-height:64px;
    height:auto;
    padding:11px 24px;
  }
  .app.theme-light .topbar{
    background:rgba(255,255,255,.94);
    border-bottom:1px solid var(--border);
    box-shadow:0 8px 24px rgba(19,34,56,.07);
  }
  .app.theme-dark .topbar{
    background:rgba(8,23,34,.94);
    border-bottom:1px solid var(--border);
  }
  .topbar-title{font-size:15px;line-height:1.2}
  .topbar-sub{margin-top:2px}
  .topbar-controls{gap:8px;flex-wrap:wrap}
  .topbar-user,.topbar-switcher{
    border-radius:10px;
    min-height:36px;
  }
  .app.theme-light .topbar-user,.app.theme-light .topbar-switcher{
    background:#f7fafc;
    border-color:var(--border);
  }
  .page{padding:30px 32px 42px}
  .pq-page{max-width:1720px}
  .page-header{
    margin-bottom:20px;
    align-items:flex-start;
  }
  .page-title{
    font-size:clamp(28px,2.15vw,38px);
    line-height:1.08;
    letter-spacing:0;
  }
  .page-subtitle{
    font-size:14px;
    line-height:1.55;
    max-width:82ch;
  }
  .page-eyebrow,.stat-label,.pq-eyebrow,.pq-detail-section-title,
  .tables-kpi-label,.mi-metric-label,.copilot-status-label{
    letter-spacing:.16em;
  }
  .card,.stat-card,.surface-panel,.tables-surface,.tables-hero,
  .dashboard-status-card,.dashboard-mini-card,.dashboard-operator-card,
  .mi-hero-band,.mi-workspace-shell,.copilot-hero,.copilot-status-card,
  .pq-detail-panel,.ux-card,.info-tile,.modal{
    border-radius:8px;
    border-color:var(--border);
    box-shadow:0 10px 26px rgba(19,34,56,.08);
  }
  .app.theme-dark .card,.app.theme-dark .stat-card,.app.theme-dark .surface-panel,
  .app.theme-dark .tables-surface,.app.theme-dark .tables-hero,
  .app.theme-dark .dashboard-status-card,.app.theme-dark .dashboard-mini-card,
  .app.theme-dark .dashboard-operator-card,.app.theme-dark .mi-hero-band,
  .app.theme-dark .mi-workspace-shell,.app.theme-dark .copilot-hero,
  .app.theme-dark .copilot-status-card,.app.theme-dark .pq-detail-panel,
  .app.theme-dark .ux-card,.app.theme-dark .info-tile,.app.theme-dark .modal{
    box-shadow:0 14px 30px rgba(0,0,0,.22);
  }
  .card-header,.surface-panel-header,.pq-detail-header{
    min-height:54px;
    padding:16px 18px;
  }
  .app.theme-light .card-header,.app.theme-light .surface-panel-header,
  .app.theme-light .pq-detail-header,.app.theme-light .filter-bar,
  .app.theme-light .tabs,.app.theme-light .pq-action-row{
    background:#f7fafc;
    border-color:var(--border);
  }
  .app.theme-dark .card-header,.app.theme-dark .surface-panel-header,
  .app.theme-dark .pq-detail-header,.app.theme-dark .filter-bar,
  .app.theme-dark .tabs,.app.theme-dark .pq-action-row{
    background:#13293b;
    border-color:var(--border);
  }
  .stat-card{min-height:98px;padding:16px 18px}
  .stat-value{font-size:28px;letter-spacing:0}
  .stats-grid{gap:16px;margin-bottom:22px}
  .btn{
    border-radius:8px;
    min-height:36px;
    padding:8px 14px;
    font-weight:800;
    letter-spacing:0;
  }
  .btn-sm{min-height:32px;padding:6px 11px}
  .btn-xs{min-height:26px}
  .app.theme-light .btn-primary{
    background:#1f7a9b;
    border-color:#1f7a9b;
    color:#ffffff;
  }
  .app.theme-light .btn-primary:hover{background:#16647f}
  .app.theme-dark .btn-primary{
    background:#5bb7d4;
    border-color:#5bb7d4;
    color:#071521;
  }
  .btn-ghost{
    background:transparent;
    border-color:var(--border2);
  }
  .app.theme-light .btn-ghost{color:#1d6580}
  .app.theme-dark .btn-ghost{color:#d7f4fb}
  .badge,.spill,.ux-status,.dashboard-chip,.sqlw-pill{
    white-space:nowrap;
    border-radius:999px;
    line-height:1.1;
  }
  .badge{padding:5px 9px;font-size:10px}
  table{border-collapse:separate;border-spacing:0}
  thead th{
    padding:12px 16px;
    letter-spacing:.14em;
    white-space:normal;
    vertical-align:middle;
  }
  tbody td{padding:13px 16px;line-height:1.35}
  .app.theme-light thead th,
  .app.theme-light .surface-panel table thead th,
  .app.theme-light .tables-table thead th{
    background:#eef6fa;
    color:#4a6175;
    border-bottom-color:var(--border);
  }
  .app.theme-dark thead th,
  .app.theme-dark .surface-panel table thead th,
  .app.theme-dark .tables-table thead th{
    background:#143346;
    color:#a9bfcc;
    border-bottom-color:var(--border);
  }
  .app.theme-light tbody td{color:#33475f;border-bottom-color:#edf2f6}
  .app.theme-dark tbody td{color:#d5e3eb;border-bottom-color:#243f52}
  .app.theme-light tbody tr:hover{background:#f7fbfd}
  .app.theme-dark tbody tr:hover{background:#122b3d}
  .fi,input,select,textarea,.sw input{
    border-radius:8px;
    min-height:38px;
  }
  .app.theme-light input,.app.theme-light select,.app.theme-light textarea,
  .app.theme-light .fi,.app.theme-light .sw,.app.theme-light .sw input{
    background:#ffffff;
    border-color:#cfdce6;
    color:#132238;
  }
  .app.theme-dark input,.app.theme-dark select,.app.theme-dark textarea,
  .app.theme-dark .fi,.app.theme-dark .sw,.app.theme-dark .sw input{
    background:#0b1b2a;
    border-color:#38566a;
    color:#f3f8fb;
  }
  .tab{
    border-radius:8px;
    min-height:36px;
    padding:9px 14px;
  }
  .tab.active{
    background:var(--text);
    color:var(--bg2);
  }
  .app.theme-light .tab.active{background:#132238;color:#ffffff}
  .app.theme-dark .tab.active{background:#d7f4fb;color:#071521}
  .sqlw-shell,.pq-sqlw-shell{
    border-radius:8px;
    box-shadow:0 12px 30px rgba(19,34,56,.10);
  }
  .sqlw-commandbar,.sqlw-panel-head,.sqlw-tabs,.sqlw-editor-toolbar,.sqlw-result-tabs{
    background:var(--bg3);
    border-color:var(--border);
  }
  .sqlw-editor{font-size:13px}
  .dashboard-stage,.tables-stage,.agent-surface,.pq-page{min-width:0}
  .uma-cockpit{
    border-radius:8px;
    box-shadow:0 12px 30px rgba(19,34,56,.10);
  }
  .uma-cockpit h1{
    max-width:13ch;
    font-size:clamp(36px,3.4vw,56px);
  }
  .uma-topology-card{
    border-radius:8px;
    min-height:340px;
  }
  .uma-legend-line span{border-radius:999px}
  .empty,.tables-empty,.surface-panel-empty{
    min-height:220px;
    display:grid;
    place-items:center;
  }
  @media (max-width:1280px){
    .uma-cockpit h1{max-width:18ch}
    .uma-topology-card{min-height:310px}
  }
  @media (max-width:960px){
    .page{padding:22px 20px 34px}
    .topbar{padding:12px 18px}
  }
  @media (max-width:520px){
    .page{padding:16px}
    .page-title{font-size:28px}
  }

  /* ── Shell fixes: responsive navigation and topbar controls ─ */
  .topbar{
    min-height:64px;
    height:auto;
    flex-wrap:wrap;
    row-gap:8px;
  }
  .topbar > div:first-child{
    flex:1 1 240px;
    min-width:0;
  }
  .topbar-controls{
    flex:0 1 auto;
    flex-wrap:wrap;
    min-width:0;
  }
  .topbar-command{
    min-width:150px;
    max-width:190px;
    justify-content:flex-start;
    color:var(--text3);
  }
  .topbar-switcher{
    min-width:0;
  }
  .topbar-switcher .fi{
    width:clamp(140px,14vw,220px);
  }
  .topbar-user{
    min-width:0;
  }
  .topbar-avatar{
    flex:0 0 auto;
  }
  .dashboard-hero-actions .btn,
  .dashboard-operator-card .btn,
  .surface-panel-header .btn{
    min-width:0;
  }
  @media (max-width:1280px){
    .topbar{
      align-items:flex-start;
      padding-block:12px;
    }
    .topbar-controls{
      width:100%;
      justify-content:flex-start;
      margin-left:0;
    }
    .topbar-command{
      flex:1 1 190px;
      max-width:260px;
    }
  }
  @media (max-width:720px){
    .sidebar{
      position:relative;
      width:100%;
      min-width:0;
      height:auto;
      max-height:none;
      border-right:0;
      border-bottom:1px solid var(--border);
    }
    .logo-wrap{
      padding:16px 18px 12px;
    }
    .nav{
      display:flex;
      gap:12px;
      overflow:auto;
      padding:10px 12px 14px;
      scroll-snap-type:x proximity;
      -webkit-overflow-scrolling:touch;
    }
    .nav-section{
      min-width:178px;
      margin-bottom:0;
      scroll-snap-align:start;
    }
    .sidebar-bot{
      display:none;
    }
    .main{
      margin-left:0;
    }
    .topbar{
      position:relative;
      padding:14px 16px;
      min-height:0;
      align-items:stretch;
      flex-direction:column;
    }
    .topbar > div:first-child{
      flex:0 0 auto;
      width:100%;
      min-width:0;
    }
    .topbar-controls{
      width:100%;
      display:grid;
      grid-template-columns:1fr;
      gap:8px;
      align-items:stretch;
    }
    .topbar-controls > *,
    .topbar-command,
    .topbar-switcher,
    .topbar-user,
    .topbar-switcher .fi{
      width:100%;
      max-width:none;
    }
    .topbar-status{
      padding:0 2px;
    }
    .topbar-avatar{
      width:34px;
      justify-self:start;
    }
    .page-header{
      align-items:flex-start;
      flex-direction:column;
    }
    .dashboard-hero-actions,
    .uma-cockpit-actions{
      display:grid;
      grid-template-columns:1fr;
    }
    .dashboard-hero-actions .btn,
    .uma-cockpit-actions .btn,
    .surface-panel-header .btn{
      width:100%;
    }
    .ux-journey-rail,
    .pipe{
      max-width:100%;
      overflow-x:auto;
      overflow-y:hidden;
    }
  }

  .auth-shell{
    min-height:100vh;
    display:grid;
    grid-template-columns:minmax(0,1fr) minmax(380px,560px);
    align-items:stretch;
    background:
      radial-gradient(780px 420px at 18% 14%, rgba(91,183,212,.22), transparent 58%),
      linear-gradient(135deg,#071521 0%,#0b1b2a 48%,#102131 100%);
    color:#f3f8fb;
  }
  .auth-story{
    position:relative;
    min-width:0;
    display:flex;
    flex-direction:column;
    justify-content:flex-end;
    padding:56px;
    overflow:hidden;
  }
  .auth-story::before{
    content:"";
    position:absolute;
    inset:36px;
    border:1px solid rgba(255,255,255,.08);
    background:
      linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
    background-size:44px 44px;
    border-radius:8px;
    mask-image:linear-gradient(180deg,transparent,black 16%,black 92%,transparent);
  }
  .auth-story-copy{position:relative;z-index:1;max-width:620px}
  .auth-kicker{
    color:#67e8f9;
    font-family:var(--font-m);
    font-size:11px;
    font-weight:850;
    letter-spacing:.16em;
    text-transform:uppercase;
  }
  .auth-title{
    margin-top:14px;
    font-family:var(--font-h);
    font-size:clamp(34px,4vw,62px);
    line-height:1.02;
    font-weight:850;
    letter-spacing:0;
  }
  .auth-copy{
    margin-top:18px;
    max-width:58ch;
    color:#b7cbd8;
    font-size:15px;
    line-height:1.65;
  }
  .auth-panel-wrap{
    display:grid;
    place-items:center;
    padding:32px;
    background:rgba(7,21,33,.38);
    backdrop-filter:blur(16px);
  }
  .auth-panel{
    width:100%;
    max-width:520px;
    background:#ffffff;
    color:#132238;
    border:1px solid rgba(255,255,255,.72);
    border-radius:8px;
    padding:30px;
    box-shadow:0 24px 60px rgba(0,0,0,.28);
  }
  .auth-brand{display:flex;align-items:center;gap:11px;margin-bottom:22px}
  .auth-brand .logo-icon{background:#1f7a9b;color:#ffffff}
  .auth-brand-name{font-size:15px;font-weight:850;color:#132238}
  .auth-brand-sub{font-family:var(--font-m);font-size:10px;color:#687c91;letter-spacing:.08em}
  .auth-heading{font-family:var(--font-h);font-size:30px;font-weight:850;line-height:1.1;margin-bottom:7px;color:#132238}
  .auth-subtitle{margin-bottom:20px;color:#687c91;font-size:13px;line-height:1.55}
  .auth-tabs{display:flex;gap:8px;margin-bottom:20px}
  .auth-tabs .btn{min-width:92px}
  .auth-panel .btn-ghost{
    background:#ffffff;
    color:#1f7a9b;
    border-color:#b8cad7;
  }
  .auth-panel .btn-ghost:hover{
    background:#eef6fa;
    color:#16647f;
  }
  .auth-panel .fl{color:#52677d}
  .auth-panel .fi{
    min-height:42px;
    background:#f8fafc;
    border-color:#cfdce6;
    color:#132238;
  }
  .auth-panel .fi:focus{
    border-color:#1f7a9b;
    box-shadow:0 0 0 3px rgba(31,122,155,.14);
  }
  .auth-submit{display:flex;justify-content:flex-end;margin-top:20px}
  @media (max-width:900px){
    .auth-shell{grid-template-columns:1fr}
    .auth-story{display:none}
    .auth-panel-wrap{min-height:100vh}
  }
  @media (max-width:520px){
    .auth-panel-wrap{padding:18px}
    .auth-panel{padding:22px}
    .auth-tabs{flex-direction:column}
    .auth-tabs .btn,.auth-submit .btn{width:100%}
    .auth-submit{display:block}
  }

  /* ── Product-grade control plane redesign pass ─────────────
     Final cascade layer. Makes UMA read as an operational console:
     denser tables, strong object/detail workspaces, fewer pale cards,
     and persistent right-side evidence panels. */
  .app.theme-light{
    --bg:#eef2f6;
    --bg1:#f7f9fb;
    --bg2:#ffffff;
    --bg3:#f4f6f8;
    --border:#d6dde5;
    --border2:#aebbc8;
    --text:#111827;
    --text2:#273243;
    --text3:#667085;
    --accent:#2563eb;
    --accent2:#0f766e;
    --green:#047857;
    --yellow:#b7791f;
    --red:#b42318;
    --orange:#b45309;
    background:linear-gradient(180deg,#f9fafb 0%,#eef2f6 100%);
  }
  .app.theme-dark{
    --bg:#0a1019;
    --bg1:#0e1724;
    --bg2:#111c2b;
    --bg3:#162233;
    --border:#29384d;
    --border2:#45566d;
    --text:#f8fafc;
    --text2:#dbe5ef;
    --text3:#98a9bb;
    --accent:#60a5fa;
    --accent2:#34d399;
    background:linear-gradient(180deg,#0e1724 0%,#0a1019 100%);
  }
  .page{
    padding:24px 28px 36px;
  }
  .pq-page{
    max-width:1840px;
  }
  .page-header{
    padding:0 0 16px;
    margin-bottom:14px;
    border-bottom:1px solid var(--border);
  }
  .page-eyebrow{
    color:var(--accent)!important;
    font-size:10px;
    letter-spacing:.18em;
  }
  .page-title{
    color:var(--text)!important;
    font-size:clamp(24px,1.7vw,32px);
    line-height:1.1;
  }
  .page-subtitle{
    color:var(--text3)!important;
    font-size:13px;
    max-width:96ch;
  }
  .card,.stat-card,.surface-panel,.tables-surface,.tables-hero,
  .dashboard-status-card,.dashboard-mini-card,.dashboard-operator-card,
  .mi-hero-band,.mi-workspace-shell,.copilot-hero,.copilot-status-card,
  .pq-detail-panel,.ux-card,.info-tile,.modal,
  .ep-list-panel,.ep-detail-panel,.ep-card,.ep-queue-list,.ep-detail-card,
  .ep-split-table{
    background:var(--bg2)!important;
    border:1px solid var(--border)!important;
    border-radius:8px!important;
    box-shadow:0 1px 2px rgba(16,24,40,.06)!important;
  }
  .app.theme-dark .card,.app.theme-dark .stat-card,.app.theme-dark .surface-panel,
  .app.theme-dark .tables-surface,.app.theme-dark .tables-hero,
  .app.theme-dark .dashboard-status-card,.app.theme-dark .dashboard-mini-card,
  .app.theme-dark .dashboard-operator-card,.app.theme-dark .mi-hero-band,
  .app.theme-dark .mi-workspace-shell,.app.theme-dark .copilot-hero,
  .app.theme-dark .copilot-status-card,.app.theme-dark .pq-detail-panel,
  .app.theme-dark .ux-card,.app.theme-dark .info-tile,.app.theme-dark .modal,
  .app.theme-dark .ep-list-panel,.app.theme-dark .ep-detail-panel,
  .app.theme-dark .ep-card,.app.theme-dark .ep-queue-list,
  .app.theme-dark .ep-detail-card,.app.theme-dark .ep-split-table{
    box-shadow:0 1px 2px rgba(0,0,0,.28)!important;
  }
  .card-header,.surface-panel-header,.pq-detail-header,
  .ep-list-head,.ep-detail-head,.ep-card-header,.ep-split-toolbar,
  .tables-toolbar,.filter-bar,.tabs,.pq-action-row{
    background:var(--bg3)!important;
    border-color:var(--border)!important;
  }
  .ep-alert-strip{
    margin-bottom:10px;
    padding:12px 14px;
    background:var(--bg2)!important;
    border:1px solid var(--border)!important;
    border-left:5px solid var(--green)!important;
    border-radius:8px;
    box-shadow:0 1px 2px rgba(16,24,40,.05);
  }
  .ep-alert-strip.has-blockers{
    background:linear-gradient(90deg,rgba(180,35,24,.08),var(--bg2) 40%)!important;
    border-left-color:var(--red)!important;
  }
  .ep-alert-kicker,.ep-kpi-label,.stat-label,.pq-detail-section-title,
  .ep-section-label,.tables-kpi-label,.mi-metric-label,.copilot-status-label{
    color:var(--text3)!important;
    font-size:10px;
    letter-spacing:.14em;
  }
  .ep-alert-title,.ep-list-title,.ep-detail-title,.card-title,
  .surface-panel-title,.pq-detail-title,.td-main{
    color:var(--text)!important;
  }
  .ep-alert-item{
    background:var(--bg3)!important;
    border-color:var(--border)!important;
    border-radius:8px;
    padding:7px 9px;
  }
  .ep-alert-item:hover,.ep-alert-item.active{
    border-color:var(--accent)!important;
    box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--accent) 22%,transparent)!important;
  }
  .ep-alert-action{
    border-radius:8px;
    min-height:36px;
    background:var(--bg3)!important;
    border-color:var(--border)!important;
    box-shadow:none!important;
  }
  .ep-alert-action:hover,.ep-alert-action.active{
    border-color:var(--accent)!important;
    box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--accent) 22%,transparent)!important;
  }
  .ep-alert-action.primary{
    background:var(--accent)!important;
    border-color:var(--accent)!important;
    color:#041220!important;
  }
  .ep-alert-action.danger{
    background:color-mix(in srgb,var(--red) 8%,var(--bg3))!important;
    border-color:color-mix(in srgb,var(--red) 32%,var(--border))!important;
    color:var(--red)!important;
  }
  .ep-alert-action.success{
    background:color-mix(in srgb,var(--green) 8%,var(--bg3))!important;
    border-color:color-mix(in srgb,var(--green) 30%,var(--border))!important;
    color:var(--green)!important;
  }
  .ep-kpi-row{
    gap:6px;
    margin-bottom:10px;
  }
  .ep-kpi,.stat-card.is-clickable{
    min-height:88px;
    padding:11px 12px;
    background:var(--bg2)!important;
    border:1px solid var(--border)!important;
    border-radius:8px;
  }
  .ep-kpi.active,.stat-card.active,.info-tile.active,.tables-kpi.active{
    border-color:var(--accent)!important;
    box-shadow:inset 0 0 0 2px color-mix(in srgb,var(--accent) 22%,transparent)!important;
  }
  .ep-kpi-value{
    font-size:20px;
    letter-spacing:0;
  }
  .ep-workspace{
    grid-template-columns:minmax(680px,1fr) minmax(380px,440px);
    gap:10px;
  }
  .ep-workspace.wide-detail{
    grid-template-columns:minmax(760px,1fr) minmax(420px,500px);
  }
  .ep-detail-panel,.pq-detail-panel{
    position:sticky;
    top:82px;
    max-height:calc(100vh - 110px);
    overflow:auto;
  }
  .pq-master-detail{
    grid-template-columns:minmax(720px,1fr) minmax(420px,500px);
    gap:10px;
  }
  .ep-queue{
    grid-template-columns:minmax(280px,340px) minmax(540px,1fr) minmax(300px,360px);
    gap:10px;
  }
  .ep-queue-item{
    padding:10px 12px;
  }
  .ep-queue-item.active{
    background:color-mix(in srgb,var(--accent) 11%,var(--bg2));
    box-shadow:inset 3px 0 0 var(--accent);
  }
  .ep-code-grid{
    grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  }
  .ep-code-pane,.pq-code-block,.brain-code-block{
    background:#0f172a!important;
    border-color:#273449!important;
    color:#e5edf6!important;
  }
  .ep-code-title{
    background:#111827;
    color:#cbd5e1;
    border-bottom-color:#273449;
  }
  .app.theme-light table,.app.theme-light tbody,
  .app.theme-light .surface-panel table,.app.theme-light .surface-panel tbody,
  .app.theme-light .tables-table table,.app.theme-light .tables-table tbody,
  .app.theme-dark table,.app.theme-dark tbody,
  .app.theme-dark .surface-panel table,.app.theme-dark .surface-panel tbody,
  .app.theme-dark .tables-table table,.app.theme-dark .tables-table tbody{
    background:var(--bg2);
  }
  thead th{
    position:sticky;
    top:0;
    z-index:2;
    padding:9px 11px!important;
    font-size:10px!important;
    letter-spacing:.12em;
    text-transform:uppercase;
    color:var(--text3)!important;
    background:var(--bg3)!important;
    border-bottom:1px solid var(--border)!important;
  }
  tbody td{
    padding:9px 11px!important;
    font-size:12px!important;
    line-height:1.3;
    color:var(--text2)!important;
    border-bottom:1px solid var(--border)!important;
  }
  tbody tr:hover{
    background:color-mix(in srgb,var(--accent) 5%,var(--bg2))!important;
  }
  .table-scroll{
    max-height:min(62vh,760px);
    overflow:auto;
  }
  .table-scroll table{
    min-width:980px;
  }
  .pq-detail-section{
    padding:12px 14px;
  }
  .pq-kpi-grid{
    gap:8px;
  }
  .info-tile{
    padding:9px 10px;
    background:var(--bg3)!important;
  }
  .info-tile-value{
    font-size:13px;
    font-weight:800;
    color:var(--text)!important;
  }
  .btn{
    border-radius:7px;
    min-height:32px;
    padding:7px 11px;
    font-size:12px;
  }
  .btn-primary{
    background:var(--accent)!important;
    border-color:var(--accent)!important;
    color:#ffffff!important;
  }
  .app.theme-dark .btn-primary{
    color:#07111f!important;
  }
  .btn-ghost{
    background:var(--bg2)!important;
    border-color:var(--border2)!important;
    color:var(--text2)!important;
  }
  .tab{
    border-radius:7px;
    padding:8px 12px;
  }
  .tab.active{
    background:var(--text)!important;
    border-color:var(--text)!important;
    color:var(--bg2)!important;
  }
  .ux-journey-rail,.steps{
    display:none!important;
  }
  .uma-topology-card,.uma-context-graph,.uma-ambient-shell{
    display:none!important;
  }
  .mi-hero-band,.copilot-hero,.tables-hero{
    padding:14px 16px;
    background:var(--bg2)!important;
  }
  .mi-hero-title,.copilot-hero-title,.tables-hero .page-title{
    font-size:22px!important;
  }
  .empty,.tables-empty,.surface-panel-empty{
    min-height:120px;
  }
  @media (max-width:1320px){
    .ep-workspace,.ep-workspace.wide-detail,.pq-master-detail,.ep-queue{
      grid-template-columns:1fr;
    }
    .ep-detail-panel,.pq-detail-panel{
      position:relative;
      top:auto;
      max-height:none;
    }
  }

  /* ── Dark mode only: high-contrast enterprise console ───────
     Light mode is intentionally untouched. This final layer fixes
     low-contrast dark surfaces across legacy cards, new ep/pq panels,
     tables, drawers, SQL/code workspaces, forms, and status controls. */
  .app.theme-dark{
    --bg:#070b12;
    --bg1:#0b111c;
    --bg2:#101827;
    --bg3:#162033;
    --border:#2f4057;
    --border2:#4d637d;
    --text:#f8fafc;
    --text2:#e2e8f0;
    --text3:#a7b5c8;
    --accent:#38bdf8;
    --accent2:#2dd4bf;
    --green:#34d399;
    --yellow:#fbbf24;
    --red:#fb7185;
    --purple:#a78bfa;
    --orange:#fb923c;
    background:
      radial-gradient(900px 420px at 8% -10%, rgba(56,189,248,.13), transparent 60%),
      radial-gradient(780px 420px at 100% 0%, rgba(45,212,191,.10), transparent 55%),
      linear-gradient(180deg,#0b111c 0%,#070b12 100%)!important;
    color:var(--text)!important;
  }
  .app.theme-dark .main,
  .app.theme-dark .page,
  .app.theme-dark .agent-surface,
  .app.theme-dark .sqlw-page,
  .app.theme-dark .job-detail-page{
    background:transparent!important;
    color:var(--text)!important;
  }
  .app.theme-dark .sidebar{
    background:linear-gradient(180deg,#0d1624 0%,#090f19 100%)!important;
    border-right:1px solid #26364b!important;
    box-shadow:14px 0 32px rgba(0,0,0,.28)!important;
  }
  .app.theme-dark .topbar{
    background:rgba(9,15,25,.96)!important;
    border-bottom:1px solid #26364b!important;
    box-shadow:0 10px 28px rgba(0,0,0,.26)!important;
  }
  .app.theme-dark .logo-wrap,
  .app.theme-dark .sidebar-bot{
    border-color:#26364b!important;
  }
  .app.theme-dark .logo-name,
  .app.theme-dark .topbar-title,
  .app.theme-dark .page-title,
  .app.theme-dark .card-title,
  .app.theme-dark .settings-title,
  .app.theme-dark .surface-panel-title,
  .app.theme-dark .dashboard-hero-title,
  .app.theme-dark .dashboard-status-title,
  .app.theme-dark .dashboard-operator-title,
  .app.theme-dark .tables-title,
  .app.theme-dark .mi-hero-title,
  .app.theme-dark .copilot-hero-title,
  .app.theme-dark .pq-detail-title,
  .app.theme-dark .ep-list-title,
  .app.theme-dark .ep-detail-title,
  .app.theme-dark .ep-alert-title,
  .app.theme-dark .td-main,
  .app.theme-dark .info-tile-value,
  .app.theme-dark .sqlw-title,
  .app.theme-dark .sqlw-panel-title,
  .app.theme-dark .ux-tool-name,
  .app.theme-dark .ux-review-title,
  .app.theme-dark .ux-check-label,
  .app.theme-dark .ux-run-label,
  .app.theme-dark .dashboard-empty-title{
    color:var(--text)!important;
  }
  .app.theme-dark .logo-sub,
  .app.theme-dark .topbar-sub,
  .app.theme-dark .topbar-status,
  .app.theme-dark .page-subtitle,
  .app.theme-dark .text-muted,
  .app.theme-dark .row-subtext,
  .app.theme-dark .settings-desc,
  .app.theme-dark .surface-panel-subtitle,
  .app.theme-dark .dashboard-hero-desc,
  .app.theme-dark .dashboard-status-subtitle,
  .app.theme-dark .dashboard-mini-note,
  .app.theme-dark .dashboard-operator-note,
  .app.theme-dark .tables-subtitle,
  .app.theme-dark .pq-detail-subtitle,
  .app.theme-dark .ep-list-subtitle,
  .app.theme-dark .ep-detail-subtitle,
  .app.theme-dark .ep-kpi-note,
  .app.theme-dark .ep-alert-copy span,
  .app.theme-dark .sqlw-sub,
  .app.theme-dark .sqlw-kicker,
  .app.theme-dark .ux-tool-desc,
  .app.theme-dark .ux-review-meta,
  .app.theme-dark .ux-review-finding,
  .app.theme-dark .ux-check-detail,
  .app.theme-dark .ux-run-detail,
  .app.theme-dark .dashboard-empty-copy{
    color:var(--text3)!important;
  }
  .app.theme-dark .page-eyebrow,
  .app.theme-dark .nav-lbl,
  .app.theme-dark .stat-label,
  .app.theme-dark .pq-eyebrow,
  .app.theme-dark .pq-detail-section-title,
  .app.theme-dark .ep-section-label,
  .app.theme-dark .ep-kpi-label,
  .app.theme-dark .ep-alert-kicker,
  .app.theme-dark .tables-kpi-label,
  .app.theme-dark .dashboard-mini-label,
  .app.theme-dark .dashboard-operator-label,
  .app.theme-dark .mi-metric-label,
  .app.theme-dark .copilot-status-label{
    color:#8bdcff!important;
  }
  .app.theme-dark .logo-icon,
  .app.theme-dark .topbar-avatar{
    background:linear-gradient(135deg,#38bdf8,#2dd4bf)!important;
    color:#031018!important;
    box-shadow:0 10px 24px rgba(56,189,248,.20)!important;
  }
  .app.theme-dark .nav-item,
  .app.theme-dark .nav-child{
    color:#cbd5e1!important;
  }
  .app.theme-dark .nav-item:hover,
  .app.theme-dark .nav-child:hover{
    background:#152236!important;
    color:#ffffff!important;
  }
  .app.theme-dark .nav-item.active,
  .app.theme-dark .nav-child.active{
    background:#172a42!important;
    border-color:#3b82a0!important;
    color:#e0f7ff!important;
    box-shadow:inset 3px 0 0 var(--accent)!important;
  }
  .app.theme-dark .topbar-user,
  .app.theme-dark .topbar-switcher,
  .app.theme-dark .topbar-command{
    background:#111c2d!important;
    border-color:#334963!important;
    color:var(--text2)!important;
  }
  .app.theme-dark .topbar-email{
    color:var(--text2)!important;
  }
  .app.theme-dark .card,
  .app.theme-dark .modal,
  .app.theme-dark .stat-card,
  .app.theme-dark .surface-panel,
  .app.theme-dark .tables-surface,
  .app.theme-dark .tables-hero,
  .app.theme-dark .dashboard-hero,
  .app.theme-dark .dashboard-status-card,
  .app.theme-dark .dashboard-mini-card,
  .app.theme-dark .dashboard-operator-card,
  .app.theme-dark .mi-hero-band,
  .app.theme-dark .mi-workspace-shell,
  .app.theme-dark .copilot-hero,
  .app.theme-dark .copilot-status-card,
  .app.theme-dark .pq-detail-panel,
  .app.theme-dark .ux-card,
  .app.theme-dark .info-tile,
  .app.theme-dark .ep-list-panel,
  .app.theme-dark .ep-detail-panel,
  .app.theme-dark .ep-card,
  .app.theme-dark .ep-queue-list,
  .app.theme-dark .ep-detail-card,
  .app.theme-dark .ep-split-table,
  .app.theme-dark .conn-matrix-card,
  .app.theme-dark .saved-query,
  .app.theme-dark .lineage-node,
  .app.theme-dark .drift-card,
  .app.theme-dark .ux-check-row,
  .app.theme-dark .ux-run-phase,
  .app.theme-dark .ux-review-card,
  .app.theme-dark .ux-capability,
  .app.theme-dark .uma-decision-card,
  .app.theme-dark .uma-connector-card{
    background:#101827!important;
    border-color:#2f4057!important;
    color:var(--text)!important;
    box-shadow:0 1px 2px rgba(0,0,0,.34),0 16px 40px rgba(0,0,0,.18)!important;
  }
  .app.theme-dark .card-header,
  .app.theme-dark .surface-panel-header,
  .app.theme-dark .pq-detail-header,
  .app.theme-dark .ep-list-head,
  .app.theme-dark .ep-detail-head,
  .app.theme-dark .ep-card-header,
  .app.theme-dark .ep-split-toolbar,
  .app.theme-dark .tables-toolbar,
  .app.theme-dark .filter-bar,
  .app.theme-dark .tabs,
  .app.theme-dark .pq-action-row,
  .app.theme-dark .pq-explorer-picker,
  .app.theme-dark .sqlw-head,
  .app.theme-dark .sqlw-commandbar,
  .app.theme-dark .sqlw-panel-head,
  .app.theme-dark .sqlw-editor-toolbar,
  .app.theme-dark .sqlw-result-tabs,
  .app.theme-dark .sqlw-tabs,
  .app.theme-dark .sqlw-tab,
  .app.theme-dark .sqlw-tab-add,
  .app.theme-dark .sqlw-gutter,
  .app.theme-dark .sqlw-inspect-title{
    background:#162033!important;
    border-color:#2f4057!important;
    color:var(--text)!important;
  }
  .app.theme-dark .ep-alert-strip{
    background:#101827!important;
    border-color:#2f4057!important;
    border-left-color:var(--green)!important;
    box-shadow:0 1px 2px rgba(0,0,0,.34)!important;
  }
  .app.theme-dark .ep-alert-strip.has-blockers{
    background:linear-gradient(90deg,rgba(251,113,133,.14),#101827 42%)!important;
    border-left-color:var(--red)!important;
  }
  .app.theme-dark .ep-alert-item,
  .app.theme-dark .ep-alert-action,
  .app.theme-dark .ep-kpi,
  .app.theme-dark .stat-card.is-clickable,
  .app.theme-dark .soft-grid .info-tile{
    background:#111c2d!important;
    border-color:#334963!important;
    color:var(--text2)!important;
  }
  .app.theme-dark .ep-kpi.active,
  .app.theme-dark .stat-card.active,
  .app.theme-dark .info-tile.active,
  .app.theme-dark .tables-kpi.active,
  .app.theme-dark .ep-queue-item.active,
  .app.theme-dark .ux-review-card.active{
    background:#132a40!important;
    border-color:#38bdf8!important;
    box-shadow:inset 3px 0 0 #38bdf8!important;
  }
  .app.theme-dark table,
  .app.theme-dark tbody,
  .app.theme-dark .surface-panel table,
  .app.theme-dark .surface-panel tbody,
  .app.theme-dark .tables-table table,
  .app.theme-dark .tables-table tbody,
  .app.theme-dark .pq-result-grid table,
  .app.theme-dark .pq-result-grid tbody{
    background:#101827!important;
    color:var(--text2)!important;
  }
  .app.theme-dark thead th,
  .app.theme-dark .surface-panel table thead th,
  .app.theme-dark .tables-table thead th,
  .app.theme-dark .pq-result-grid thead th{
    background:#18243a!important;
    color:#b7c8db!important;
    border-bottom-color:#34465f!important;
  }
  .app.theme-dark tbody td,
  .app.theme-dark .surface-panel table tbody td,
  .app.theme-dark .tables-table tbody td,
  .app.theme-dark .pq-result-grid tbody td{
    color:#e2e8f0!important;
    border-bottom-color:#2a3a50!important;
  }
  .app.theme-dark tbody tr:hover,
  .app.theme-dark .surface-panel table tbody tr:hover,
  .app.theme-dark .tables-table tbody tr:hover,
  .app.theme-dark .pq-result-grid tbody tr:hover{
    background:#142238!important;
  }
  .app.theme-dark .td-mono,
  .app.theme-dark .tables-table .td-mono,
  .app.theme-dark .surface-panel .td-mono,
  .app.theme-dark .sq-sql{
    color:#b7c8db!important;
  }
  .app.theme-dark input,
  .app.theme-dark select,
  .app.theme-dark textarea,
  .app.theme-dark .fi,
  .app.theme-dark .sw,
  .app.theme-dark .sw input,
  .app.theme-dark .tables-toolbar .sw input,
  .app.theme-dark .tables-toolbar select,
  .app.theme-dark .topbar-switcher .fi{
    background:#0b111c!important;
    border-color:#3a506a!important;
    color:#f8fafc!important;
    box-shadow:none!important;
  }
  .app.theme-dark input::placeholder,
  .app.theme-dark textarea::placeholder{
    color:#7f90a5!important;
  }
  .app.theme-dark input:focus,
  .app.theme-dark select:focus,
  .app.theme-dark textarea:focus,
  .app.theme-dark .fi:focus,
  .app.theme-dark .sw input:focus{
    border-color:#38bdf8!important;
    box-shadow:0 0 0 3px rgba(56,189,248,.18)!important;
    outline:none!important;
  }
  .app.theme-dark .btn-primary{
    background:#38bdf8!important;
    border-color:#38bdf8!important;
    color:#031018!important;
  }
  .app.theme-dark .btn-primary:hover{
    background:#7dd3fc!important;
    border-color:#7dd3fc!important;
  }
  .app.theme-dark .btn-ghost{
    background:#111c2d!important;
    border-color:#405772!important;
    color:#e2e8f0!important;
  }
  .app.theme-dark .btn-ghost:hover{
    background:#17263b!important;
    border-color:#38bdf8!important;
    color:#ffffff!important;
  }
  .app.theme-dark .btn-icon{
    color:#e2e8f0!important;
  }
  .app.theme-dark button:disabled,
  .app.theme-dark .btn:disabled,
  .app.theme-dark input:disabled,
  .app.theme-dark select:disabled,
  .app.theme-dark textarea:disabled{
    background:#0e1726!important;
    border-color:#2a3a50!important;
    color:#7f90a5!important;
    opacity:1!important;
    cursor:not-allowed!important;
  }
  .app.theme-dark .btn-primary:disabled{
    background:#17263b!important;
    border-color:#3a506a!important;
    color:#cbd5e1!important;
  }
  .app.theme-dark .badge,
  .app.theme-dark .spill,
  .app.theme-dark .ux-status,
  .app.theme-dark .dashboard-chip,
  .app.theme-dark .sqlw-pill{
    border-color:#3a506a!important;
    color:var(--text2)!important;
  }
  .app.theme-dark .bg,
  .app.theme-dark .badge.bg,
  .app.theme-dark .dashboard-chip.ok,
  .app.theme-dark .ux-status-success{
    background:rgba(52,211,153,.14)!important;
    border-color:rgba(52,211,153,.45)!important;
    color:#86efac!important;
  }
  .app.theme-dark .bb,
  .app.theme-dark .bp,
  .app.theme-dark .badge.bb,
  .app.theme-dark .badge.bp,
  .app.theme-dark .dashboard-chip,
  .app.theme-dark .ux-status-info,
  .app.theme-dark .ux-status-running{
    background:rgba(56,189,248,.14)!important;
    border-color:rgba(56,189,248,.42)!important;
    color:#bae6fd!important;
  }
  .app.theme-dark .by,
  .app.theme-dark .badge.by,
  .app.theme-dark .ux-status-warning,
  .app.theme-dark .ux-status-review{
    background:rgba(251,191,36,.14)!important;
    border-color:rgba(251,191,36,.44)!important;
    color:#fde68a!important;
  }
  .app.theme-dark .br,
  .app.theme-dark .badge.br,
  .app.theme-dark .dashboard-chip.danger,
  .app.theme-dark .ux-status-danger{
    background:rgba(251,113,133,.15)!important;
    border-color:rgba(251,113,133,.45)!important;
    color:#fecdd3!important;
  }
  .app.theme-dark .bgr,
  .app.theme-dark .badge.bgr,
  .app.theme-dark .ux-status-neutral{
    background:#18243a!important;
    border-color:#34465f!important;
    color:#cbd5e1!important;
  }
  .app.theme-dark .alert-info{
    background:rgba(56,189,248,.12)!important;
    border-color:rgba(56,189,248,.36)!important;
    color:#bae6fd!important;
  }
  .app.theme-dark .alert-ok{
    background:rgba(52,211,153,.12)!important;
    border-color:rgba(52,211,153,.36)!important;
    color:#bbf7d0!important;
  }
  .app.theme-dark .alert-err{
    background:rgba(251,113,133,.13)!important;
    border-color:rgba(251,113,133,.40)!important;
    color:#fecdd3!important;
  }
  .app.theme-dark .tab{
    background:#111c2d!important;
    border-color:#334963!important;
    color:#cbd5e1!important;
  }
  .app.theme-dark .tab.active,
  .app.theme-dark .sqlw-tab.active,
  .app.theme-dark .sqlw-result-tab.active{
    background:#38bdf8!important;
    border-color:#38bdf8!important;
    color:#031018!important;
  }
  .app.theme-dark .pq-code-block,
  .app.theme-dark .brain-code-block,
  .app.theme-dark .ep-code-pane,
  .app.theme-dark .ep-code-pane pre,
  .app.theme-dark .sqlw-editor,
  .app.theme-dark .sql-editor,
  .app.theme-dark pre,
  .app.theme-dark code{
    background:#050a12!important;
    border-color:#26364b!important;
    color:#e6edf6!important;
  }
  .app.theme-dark .ep-code-title{
    background:#0b111c!important;
    color:#b7c8db!important;
    border-bottom-color:#26364b!important;
  }
  .app.theme-dark .sqlw-shell,
  .app.theme-dark .pq-sqlw-shell,
  .app.theme-dark .sqlw-explorer,
  .app.theme-dark .sqlw-inspector,
  .app.theme-dark .sqlw-body,
  .app.theme-dark .sqlw-main,
  .app.theme-dark .sqlw-editor-area,
  .app.theme-dark .sqlw-results,
  .app.theme-dark .sqlw-editor-wrap,
  .app.theme-dark .sqlw-inspect-section{
    background:#101827!important;
    border-color:#2f4057!important;
    color:var(--text)!important;
  }
  .app.theme-dark .sqlw-node,
  .app.theme-dark .sqlw-table-row{
    color:#dbe5ef!important;
  }
  .app.theme-dark .sqlw-node:hover,
  .app.theme-dark .sqlw-table-row:hover,
  .app.theme-dark .sqlw-table-row.active{
    background:#17263b!important;
    color:#e0f7ff!important;
  }
  .app.theme-dark .sqlw-kv{
    border-bottom-color:#2f4057!important;
  }
  .app.theme-dark .sqlw-kv span:first-child{
    color:#a7b5c8!important;
  }
  .app.theme-dark .sqlw-kv span:last-child{
    color:#f8fafc!important;
  }
  .app.theme-dark .empty,
  .app.theme-dark .tables-empty,
  .app.theme-dark .surface-panel-empty,
  .app.theme-dark .pq-empty-compact,
  .app.theme-dark .ep-empty-compact,
  .app.theme-dark .dashboard-empty{
    background:#111c2d!important;
    border-color:#334963!important;
    color:var(--text3)!important;
  }
  .app.theme-dark .modal-ov{
    background:rgba(2,6,12,.72)!important;
  }
  .app.theme-dark ::selection{
    background:rgba(56,189,248,.35);
    color:#ffffff;
  }
`;

// ─── Source Types ─────────────────────────────────────────────
const SRC = [
  { id:"bigquery",   name:"BigQuery",    icon:"🔷", color:"#4285F4" },
  { id:"redshift",   name:"Redshift",    icon:"🔴", color:"#DD344C" },
  { id:"sqlserver",  name:"SQL Server",  icon:"🟧", color:"#CC2927" },
  { id:"teradata",   name:"Teradata",    icon:"⬛", color:"#F37440" },
  { id:"salesforce", name:"Salesforce",  icon:"☁️", color:"#00A1E0" },
  { id:"s3",         name:"Amazon S3",   icon:"🪣", color:"#FF9900" },
  { id:"azureblob",  name:"Azure Blob",  icon:"🔵", color:"#0078D4" },
  { id:"adls",       name:"ADLS Gen2",   icon:"🌊", color:"#0078D4" },
  { id:"flatfile",   name:"Flat Files",  icon:"📄", color:"#6B7280" },
  { id:"snowflake",  name:"Snowflake",   icon:"❄️", color:"#29B5E8" },
  { id:"oracle",     name:"Oracle",      icon:"🔶", color:"#F80000" },
  { id:"postgres",   name:"PostgreSQL",  icon:"🐘", color:"#336791" },
];

// ─── Helpers ──────────────────────────────────────────────────
function src(type) { return SRC.find(s => s.id === type) || { name: type, icon:"⬜", color:"#4A5C75" }; }

function SourcePill({ type }) {
  const s = src(type);
  return (
    <span className="spill" style={{ background: s.color+"18", color: s.color, border: `1px solid ${s.color}30` }}>
      {s.icon} {s.name}
    </span>
  );
}

function StatusBadge({ status }) {
  const map = {
    SUCCEEDED:           ["bg badge-dot",  ""],
    RUNNING:             ["bb badge-dot",  ""],
    FAILED:              ["br badge-dot",  ""],
    PARTIALLY_SUCCEEDED: ["by badge-dot",  "Partial"],
    PENDING:             ["bgr badge-dot", ""],
    COMPLETED:           ["bg",            ""],
    PASS:                ["bg badge-dot",  ""],
    FAIL:                ["br badge-dot",  ""],
    WARNING:             ["by badge-dot",  ""],
    NOT_CONFIGURED:      ["bgr badge-dot", "Not configured"],
    NOT_CHECKED:         ["bgr badge-dot", "Not checked"],
    QUEUED:              ["bb badge-dot",  ""],
    PLANNED:             ["bb badge-dot",  ""],
    DRAFT:               ["bgr badge-dot", ""],
    READY:               ["bg badge-dot",  ""],
    PAUSED:              ["by badge-dot",  ""],
    CANCELLED:           ["bgr badge-dot", ""],
  };
  const [cls, lbl] = map[status] || ["bgr",""];
  return <span className={`badge ${cls}`}>{lbl || status?.charAt(0) + status?.slice(1).toLowerCase().replace(/_/g," ")}</span>;
}

function HealthDot({ health }) {
  const c = { healthy:"var(--green)", warn:"var(--yellow)", failed:"var(--red)" }[health] || "var(--text3)";
  return <span style={{ width:8,height:8,borderRadius:"50%",background:c,boxShadow:`0 0 5px ${c}`,display:"inline-block" }} />;
}

function connectionTestChecklist(conn, result, running = false) {
  const snowflake = conn?.type === "snowflake";
  const labels = snowflake
    ? ["Account reachable", "Role verified", "Warehouse usable", "Database/schema found", "Stage permission checked", "COPY INTO permission checked", "MERGE permission checked", "Validation permission checked"]
    : ["Host reachable", "TLS verified", "Authentication successful", "Schemas discovered", "Tables discovered", "Permissions checked", "Incremental capability checked"];
  const success = Boolean(result?.success);
  const failed = result && !success;
  return labels.map((label, index) => ({
    label,
    status: running
      ? (index < 2 ? "passed" : index === 2 ? "running" : "pending")
      : success
        ? "passed"
        : failed
          ? (index < 2 ? "passed" : index === 2 ? "failed" : "skipped")
          : "pending",
    detail: running
      ? "Checking live connection capability."
      : success
        ? "Verified or safely inferred from the connection test response."
        : failed
          ? (index === 2 ? (result?.diagnostic || result?.error || "Connection test failed.") : "Skipped after failure.")
          : "Waiting for a connection test.",
  }));
}

function Spinner() { return <span className="spin">↻</span>; }
function Loading() {
  return (
    <div style={{ padding:40, textAlign:"center", color:"var(--text3)", fontSize:13 }}>
      <Spinner />{" "}
      Loading migration state…
    </div>
  );
}
function ErrMsg({ msg }) { return <div className="alert-err">⚠ {msg}</div>; }

function DashboardEmpty({ icon, title, message, action }) {
  return (
    <div className="dashboard-empty">
      <div className="dashboard-empty-icon" aria-hidden="true">{icon}</div>
      <div>
        <div className="dashboard-empty-title">{title}</div>
        <div className="dashboard-empty-copy">{message}</div>
      </div>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

function fmt_duration(seconds) {
  if (!seconds) return "—";
  if (seconds < 60)  return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ${Math.round(seconds%60)}s`;
  return `${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m`;
}

function fmt_bytes(bytes) {
  if (!bytes) return "—";
  if (bytes < 1e6) return `${(bytes/1e3).toFixed(1)} KB`;
  if (bytes < 1e9) return `${(bytes/1e6).toFixed(1)} MB`;
  return `${(bytes/1e9).toFixed(2)} GB`;
}

function fmt_number(value) {
  if (value === null || value === undefined || value === "") return "—";
  return Number(value).toLocaleString();
}

function fmt_dt(value) {
  if (!value) return "—";
  try { return new Date(value).toLocaleString(); } catch { return value; }
}

function connRole(c) {
  return c?.connection_role || (c?.type === "snowflake" ? "target" : "source");
}

function canUseAsSource(c) {
  const role = connRole(c);
  return role === "source" || role === "both";
}

function canUseAsTarget(c) {
  const role = connRole(c);
  return role === "target" || role === "both";
}

function cron_hint(expr) {
  const map = {
    '*/15 * * * *': 'Every 15 minutes',
    '0 * * * *': 'Hourly',
    '0 2 * * *': 'Daily 2am',
    '0 2 * * 0': 'Weekly Sunday 2am',
  };
  return map[expr] || 'Custom cadence';
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

function Modal({ title, onClose, width=560, children }) {
  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" style={{ width, maxWidth:'calc(100vw - 32px)' }} onClick={e=>e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">{title}</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────
function Dashboard({ setPage }) {
  const { data: jobs, loading: jobsLoading } = useApi(() => api.getJobs({ limit: 8 }), []);
  const { data: conns, loading: connsLoading } = useApi(() => api.getConnections(), []);
  const { data: stats, loading: statsLoading } = useApi(() => api.getJobStats(), []);
  const { data: health } = useApi(() => api.getHealth(), []);
  const [activeKpi, setActiveKpi] = useState("project");
  const [selectedBlocker, setSelectedBlocker] = useState(null);

  const connectionRows = Array.isArray(conns) ? conns : [];
  const recentJobs = Array.isArray(jobs) ? jobs : [];
  const failedJobs = recentJobs.filter((job) => job.status === "FAILED");
  const runningJobs = recentJobs.filter((job) => job.status === "RUNNING");
  const reviewJobs = recentJobs.filter((job) => ["REQUIRES_REVIEW", "PARTIALLY_SUCCEEDED"].includes(job.status));
  const unhealthyConnections = connectionRows.filter((connection) => ["failed", "error", "unhealthy"].includes(String(connection.health || "").toLowerCase()));
  const healthyConnections = connectionRows.filter((connection) => String(connection.health || "").toLowerCase() === "healthy");
  const blockers = [
    ...failedJobs.map((job) => ({ ...job, id: `job-${job.id}`, source_id: job.id, title: job.name || "Untitled job", status: "FAILED", action: "Open run detail", page: "jobs", object_kind: "Migration Job" })),
    ...reviewJobs.map((job) => ({ ...job, id: `review-${job.id}`, source_id: job.id, title: job.name || "Review required", status: "REQUIRES_REVIEW", action: "Open review", page: "brain_review", object_kind: "Review Gate" })),
    ...unhealthyConnections.map((connection) => ({ ...connection, id: `conn-${connection.id}`, source_id: connection.id, title: connection.name || "Connection issue", status: "FAILED", action: "Fix connection", page: "connections", object_kind: "Connection" })),
  ].slice(0, 5);
  const activeBlocker = selectedBlocker && blockers.some((blocker) => blocker.id === selectedBlocker.id) ? selectedBlocker : blockers[0] || null;

  const totalGB = Number(stats?.total_gb || 0);
  const totalJobs = Number(stats?.total_jobs || recentJobs.length || 0);
  const loading = jobsLoading || connsLoading || statsLoading;
  const overviewKpis = [
    { id: "project", label: "Project health", value: failedJobs.length || unhealthyConnections.length ? "Blocked" : "Ready", note: `${failedJobs.length} failed runs` },
    { id: "connections", label: "Connections", value: `${healthyConnections.length}/${connectionRows.length || 0}`, note: "healthy endpoints" },
    { id: "running", label: "Running", value: runningJobs.length, note: "active jobs" },
    { id: "review", label: "Review", value: reviewJobs.length, note: "needs decision" },
    { id: "data", label: "Data moved", value: `${totalGB.toFixed(1)} GB`, note: "tracked loads" },
    { id: "runs", label: "Runs", value: totalJobs, note: "job definitions" },
  ];
  const overviewRows = {
    project: [...failedJobs, ...unhealthyConnections.map((connection) => ({ ...connection, name: connection.name, status: connection.health || connection.status || "FAILED", source_connection_type: connection.type, total_bytes_gb: 0, object_kind: "Connection" }))],
    connections: connectionRows.map((connection) => ({ ...connection, object_kind: "Connection", status: connection.health || connection.status || "UNKNOWN", total_bytes_gb: 0 })),
    running: runningJobs,
    review: reviewJobs,
    data: recentJobs.filter((job) => Number(job.total_bytes_gb || 0) > 0),
    runs: recentJobs,
  }[activeKpi] || recentJobs;
  const overviewTitle = overviewKpis.find((item) => item.id === activeKpi)?.label || "KPI";

  return (
    <div className="page pq-page">
      <div className="page-header">
        <div className="page-header-copy">
          <div className="page-eyebrow">Migration Control Plane</div>
          <div className="page-title">Command Center</div>
          <div className="page-subtitle">A live landing cockpit for blockers, failed runs, connection health, recent activity, and the next operator action.</div>
        </div>
        <div className="page-actions">
          <button className="btn btn-primary" onClick={() => setPage("dashboard")}>Open Run Board</button>
          <button className="btn btn-ghost" onClick={() => setPage("brain_review")}>Review Decisions</button>
        </div>
      </div>

      <div className={`ep-alert-strip ${blockers.length ? "has-blockers" : ""}`}>
        <div>
          <div className="ep-alert-kicker">{blockers.length ? `${blockers.length} blockers need attention` : "No active blockers"}</div>
          <div className="ep-alert-title">
            {activeBlocker?.title || "Current workspace is clear for the next planned action."}
          </div>
        </div>
        <div className="ep-alert-items">
          {blockers.length ? blockers.slice(0, 3).map((blocker) => (
            <button
              key={blocker.id}
              className={`ep-alert-item ${activeBlocker?.id === blocker.id ? "active" : ""}`}
              type="button"
              onClick={() => {
                setSelectedBlocker(blocker);
                setActiveKpi(blocker.object_kind === "Connection" ? "connections" : blocker.status === "REQUIRES_REVIEW" ? "review" : "project");
              }}
            >
              <StatusBadge status={blocker.status} />
              <span className="ep-alert-copy">
                <strong>{blocker.title}</strong>
                <span>{blocker.action}</span>
              </span>
            </button>
          )) : <span className="ep-alert-ok">Ready for review or validation planning</span>}
        </div>
      </div>

      {activeBlocker ? (
        <div className="ep-list-panel" style={{ marginBottom: 12 }}>
          <div className="ep-list-head">
            <div>
              <div className="ep-list-title">Priority blocker evidence</div>
              <div className="ep-list-subtitle">Opened from the blocker strip. This is the selected object behind the alert, not a decorative status.</div>
            </div>
            <StatusBadge status={activeBlocker.status} />
          </div>
          <div style={{ padding: 12 }}>
            <div className="pq-kpi-grid">
              <div className="info-tile"><div className="text-muted">Object</div><div className="info-tile-value">{activeBlocker.title}</div></div>
              <div className="info-tile"><div className="text-muted">Type</div><div className="info-tile-value">{activeBlocker.object_kind}</div></div>
              <div className="info-tile"><div className="text-muted">Status</div><div className="info-tile-value"><StatusBadge status={activeBlocker.status} /></div></div>
              <div className="info-tile"><div className="text-muted">Action</div><div className="info-tile-value">{activeBlocker.action}</div></div>
            </div>
            <div className="ep-action-row mt3">
              <button className="btn btn-primary btn-sm" type="button" onClick={() => setPage(activeBlocker.page)}>Open owning page</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("dashboard")}>Open Run Board</button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="ep-kpi-row">
        {overviewKpis.map((item) => (
          <button className={`ep-kpi ${activeKpi === item.id ? "active" : ""}`} type="button" key={item.label} onClick={() => setActiveKpi(item.id)}>
            <div className="ep-kpi-label">{item.label}</div>
            <div className="ep-kpi-value">{loading ? "..." : item.value}</div>
            <div className="ep-kpi-note">{item.note}</div>
          </button>
        ))}
      </div>

      <div className="ep-list-panel" style={{ marginBottom: 12 }}>
        <div className="ep-list-head">
          <div>
            <div className="ep-list-title">{overviewTitle} details</div>
            <div className="ep-list-subtitle">Opened from the Command Center KPI strip. Rows route to their owning page for deeper action.</div>
          </div>
          <StatusBadge status={activeKpi === "project" && overviewRows.length ? "REQUIRES_REVIEW" : "OPEN"} />
        </div>
        <div className="table-scroll">
          <table className="dashboard-table">
            <thead><tr><th>Name</th><th>Object</th><th>Status</th><th>Updated</th><th>Data</th><th>Action</th></tr></thead>
            <tbody>
              {overviewRows.map((row) => (
                <tr key={`${row.object_kind || "Job"}-${row.id || row.name}`}>
                  <td className="td-main">{row.name || "Untitled"}</td>
                  <td>{row.object_kind || "Job"}</td>
                  <td><StatusBadge status={row.status || row.health || "UNKNOWN"} /></td>
                  <td className="td-mono">{fmt_dt(row.started_at || row.created_at || row.updated_at || row.last_checked_at)}</td>
                  <td className="td-mono">{Number(row.total_bytes_gb || 0).toFixed(1)} GB</td>
                  <td><button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage(row.object_kind === "Connection" ? "connections" : "jobs")}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!overviewRows.length ? <DashboardEmpty icon={<CheckCircle size={16} />} title="No records for this KPI" message="This KPI has no matching backend records in the current workspace." /> : null}
        </div>
      </div>

      <div className="ep-workspace wide-detail">
        <div className="ep-list-panel">
          <div className="ep-list-head">
            <div>
              <div className="ep-list-title">Recent operational activity</div>
              <div className="ep-list-subtitle">Latest jobs from the backend, with failures and review states kept visible.</div>
            </div>
            <StatusBadge status={failedJobs.length ? "FAILED" : reviewJobs.length ? "REQUIRES_REVIEW" : "HEALTHY"} />
          </div>
          {jobsLoading ? <Loading /> : !recentJobs.length ? (
            <DashboardEmpty
              icon={<Zap size={18} />}
              title="No runs yet"
              message="Create or open a migration run to populate job status, evidence, and reports."
              action={<button className="btn btn-primary btn-sm" type="button" onClick={() => setPage("dashboard")}>Open Run Board</button>}
            />
          ) : (
            <div className="table-scroll">
              <table className="dashboard-table">
                <thead><tr><th>Job</th><th>Source</th><th>Status</th><th>Started</th><th>Data</th><th>Action</th></tr></thead>
                <tbody>
                  {recentJobs.map((job) => (
                    <tr key={job.id}>
                      <td className="td-main"><span className="dashboard-cell-main" title={job.name || "Untitled job"}>{job.name || "Untitled job"}</span></td>
                      <td><SourcePill type={job.source_connection_type || "postgresql"} /></td>
                      <td><StatusBadge status={job.status} /></td>
                      <td className="td-mono">{fmt_dt(job.started_at || job.created_at)}</td>
                      <td className="td-mono">{Number(job.total_bytes_gb || 0).toFixed(1)} GB</td>
                      <td><button className="btn btn-ghost btn-sm" type="button" onClick={() => setPage("jobs")}>Open</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="ep-detail-panel">
          <div className="ep-detail-head">
            <div>
              <div className="ep-detail-title">Next recommended action</div>
              <div className="ep-detail-subtitle">{health ? "API connected" : "API connection needs attention"}</div>
            </div>
            <StatusBadge status={blockers.length ? "REQUIRES_REVIEW" : "HEALTHY"} />
          </div>
          <div className="ep-detail-body">
            <div className="ep-recommendation">
              <strong>{blockers.length ? "Resolve blockers before validation." : "Workspace is ready for the next run review."}</strong>
              <div className="text-muted mt2">
                {blockers.length
                  ? "Open the failed run, Brain Review decision, or connection issue from this panel. The Run Board remains available for full evidence inspection."
                  : "Open the Run Board to inspect persisted runs, artifacts, report evidence, and readiness status."}
              </div>
            </div>
            <div className="divider" />
            <div className="ep-section-label">Connection health</div>
            {connsLoading ? <Loading /> : (
              <div className="table-scroll">
                <table className="tbl">
                  <thead><tr><th>Name</th><th>Type</th><th>Health</th></tr></thead>
                  <tbody>
                    {connectionRows.slice(0, 6).map((connection) => (
                      <tr key={connection.id}>
                        <td className="td-main">{connection.name || "Untitled connection"}</td>
                        <td><SourcePill type={connection.type} /></td>
                        <td><span className="flex fac gap2"><HealthDot health={connection.health} /> {connection.health || "unknown"}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="ep-action-row mt4">
              <button className="btn btn-primary btn-sm" onClick={() => setPage("dashboard")}>Open Run Board</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setPage("connections")}>Fix Connections</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CommandCenterShell({ setPage }) {
  const [view, setView] = useState("overview");
  const routeAwareSetPage = (nextPage) => {
    if (nextPage === "dashboard") {
      setView("run_board");
      return;
    }
    if (nextPage === "command") {
      setView("overview");
      return;
    }
    setPage(nextPage);
  };

  return (
    <div>
      <div className="page" style={{ paddingBottom: 0 }}>
        <div className="tabs" style={{ marginBottom: 0 }}>
          <button className={`tab ${view === "overview" ? "active" : ""}`} onClick={() => setView("overview")}>
            Overview
          </button>
          <button className={`tab ${view === "run_board" ? "active" : ""}`} onClick={() => setView("run_board")}>
            Run Board
          </button>
        </div>
      </div>
      {view === "overview" ? <Dashboard setPage={routeAwareSetPage} /> : <CommandCenterPage setPage={routeAwareSetPage} />}
    </div>
  );
}

// ─── Jobs ─────────────────────────────────────────────────────
function JobsPage() {
  const [search, setSearch]       = useState("");
  const [statusF, setStatusF]     = useState("");
  const [selectedJob, setSelected]= useState(null);
  const [showCreate, setCreate]   = useState(false);
  const [activeTab, setTab]       = useState("tasks");

  const { data: jobs, loading, error, refetch } = useApi(
    () => api.getJobs(statusF ? { status: statusF } : {}), [statusF]
  );

  const filtered = (jobs||[]).filter(j =>
    !search || j.name.toLowerCase().includes(search.toLowerCase())
  );

  if (selectedJob) return (
    <JobDetail job={selectedJob} onBack={() => setSelected(null)} onRefetch={refetch} />
  );

  return (
    <div className="page">
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title" style={{ fontSize:15 }}>Migration Jobs</div>
            <div className="text-muted mt2">Orchestrate source → Snowflake with full task visibility</div>
          </div>
          <button className="btn btn-primary" style={{ marginLeft:"auto" }} onClick={() => setCreate(true)}>+ New Job</button>
        </div>
        <div className="filter-bar">
          <div className="sw"><span className="si">🔍</span><input placeholder="Search job name…" value={search} onChange={e=>setSearch(e.target.value)} /></div>
          <select value={statusF} onChange={e=>setStatusF(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="SUCCEEDED">Succeeded</option>
            <option value="RUNNING">Running</option>
            <option value="FAILED">Failed</option>
            <option value="PARTIALLY_SUCCEEDED">Partially Succeeded</option>
            <option value="PENDING">Pending</option>
          </select>
          <button className="btn btn-ghost btn-sm" onClick={refetch}>↻ Refresh</button>
        </div>
        {error && <ErrMsg msg={error} />}
        {loading ? <Loading /> : !filtered.length ? (
          <div className="empty"><div className="empty-icon">⚡</div><div className="empty-msg">No jobs found. Create your first migration job.</div></div>
        ) : (
          <div className="table-scroll jobs-table">
            <table>
              <thead><tr><th>Job Name</th><th>Status</th><th>Started</th><th>Duration</th><th>Tasks</th><th>Data</th><th>Actions</th></tr></thead>
              <tbody>
                {filtered.map(j => (
                  <tr key={j.id} style={{ cursor:"pointer" }} onClick={() => setSelected(j)}>
                    <td className="td-main">{j.name}</td>
                    <td><StatusBadge status={j.status} /></td>
                    <td className="td-mono" style={{ fontSize:10 }}>{j.started_at ? new Date(j.started_at).toLocaleString() : "—"}</td>
                    <td className="td-mono">{j.load_duration_s ? fmt_duration((j.export_duration_s||0)+(j.stage_duration_s||0)+(j.load_duration_s||0)) : "—"}</td>
                    <td className="td-mono">{j.tasks_succeeded}/{j.task_count} <span style={{ color:"var(--red)" }}>{j.tasks_failed > 0 ? `· ${j.tasks_failed} failed` : ""}</span></td>
                    <td className="td-mono">{j.total_bytes_gb} GB</td>
                    <td onClick={e=>e.stopPropagation()}>
                      <div style={{ display:"flex", gap:5 }}>
                        <button className="btn btn-ghost btn-icon btn-sm" title="Run"
                          onClick={async () => { await api.executeJob(j.id); refetch(); }}>▶</button>
                        <button className="btn btn-danger btn-icon btn-sm" title="Delete"
                          onClick={async () => { await api.deleteJob(j.id); refetch(); }}>🗑</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {showCreate && <CreateJobModal onClose={() => { setCreate(false); refetch(); }} />}
    </div>
  );
}

// ─── Job Detail ───────────────────────────────────────────────
function JobDetail({ job: initialJob, onBack, onRefetch }) {
  const { data: job, refetch } = useApi(() => api.getJob(initialJob.id), [initialJob.id], { initialData: initialJob });
  const { data: tasks, refetch: rTasks } = useApi(() => api.getJobTasks(initialJob.id), [initialJob.id]);
  const { data: logs, refetch: rLogs }  = useApi(() => api.getJobLogs(initialJob.id, { limit:200 }), [initialJob.id]);
  const { data: runs, refetch: rRuns }  = useApi(() => api.getJobRuns(initialJob.id), [initialJob.id]);
  const { data: state, refetch: rState } = useApi(() => api.getJobState(initialJob.id), [initialJob.id]);
  const { data: validations, refetch: rValidations } = useApi(() => api.getValidationRules({ job_id: initialJob.id }), [initialJob.id]);
  const [tab, setTab]   = useState("tasks");
  const [levelF, setLF] = useState("");
  const [taskF, setTF]  = useState("");
  const [logSearch, setLS] = useState("");
  const [viewLog, setVL]  = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [cancelling, setCancelling] = useState(false);

  const isRunning = job?.status === "RUNNING";
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => { refetch(); rTasks(); rLogs(); rRuns(); rState(); rValidations(); }, 4000);
    return () => clearInterval(id);
  }, [isRunning]);

  const phaseMap = { EXPORTING:0, STAGING:1, LOADING:2, COMPLETED:2, FAILED:2, REAL_ENGINE_RUNNING:1 };
  const phase = phaseMap[job?.phase] ?? -1;

  const filteredLogs = (logs||[]).filter(l => {
    if (levelF && l.level !== levelF) return false;
    if (taskF  && l.task_ref !== taskF) return false;
    if (logSearch && !l.message.toLowerCase().includes(logSearch.toLowerCase()) && !l.event.toLowerCase().includes(logSearch.toLowerCase())) return false;
    return true;
  });

  const handleCancel = async () => {
    if (!confirm("Cancel this run? The engine will stop at the next table boundary.")) return;
    setCancelling(true);
    try { await api.cancelJob(job.id); refetch(); }
    catch (e) { alert(e.message); }
    setCancelling(false);
  };

  if (!job) return <Loading />;

  return (
    <div className="page job-detail-page">
      <div className="job-back-row">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← Back to Jobs</button>
      </div>
      <div className="job-detail-head">
        <div>
          <div className="job-title">{job.name}</div>
          <div className="job-badge-row">
            <StatusBadge status={job.status} />
            <span className="badge bb badge-dot">Executed</span>
            <span className="badge bgr">Phase: {job.phase}</span>
            <span className="badge bgr">Strategy: {job.load_strategy}</span>
          </div>
        </div>
        <div className="job-actions">
          <button className="btn btn-ghost btn-sm" onClick={() => { refetch(); rTasks(); rLogs(); rRuns(); rState(); rValidations(); }}>↻ Refresh</button>
          {isRunning ? (
            <button className="btn btn-ghost btn-sm" onClick={handleCancel} disabled={cancelling} style={{ color:"var(--red)", borderColor:"var(--red)" }}>
              {cancelling ? <Spinner/> : "■ Cancel"}
            </button>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={async()=>{ await api.executeJob(job.id); refetch(); rRuns(); }}>▶ Execute</button>
          )}
        </div>
      </div>

      {/* Metrics */}
      <div className="job-metric-grid">
        {[
          ["Export Duration",  fmt_duration(job.export_duration_s), phase===0?"var(--accent)":"var(--green)"],
          ["Stage Duration",   fmt_duration(job.stage_duration_s),  phase===1 ? "var(--accent)" : phase > 1 ? "var(--green)" : "var(--text3)"],
          ["Snowflake Load",   fmt_duration(job.load_duration_s),   phase===2&&job.status==="RUNNING"?"var(--accent)":"var(--green)"],
        ].map(([l,v,c]) => (
          <div key={l} className="job-metric-card">
            <div className="job-metric-label">{l}</div>
            <div className="job-metric-value" style={{ color:c }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Pipeline */}
      <div className="card mb4 job-pipeline-card" style={{ marginBottom:14 }}>
        <div className="card-header"><div className="card-title">Pipeline</div></div>
        <div className="job-pipeline-body">
          <div className="pipe">
            {[
              ["Export", fmt_duration(job.export_duration_s), phase>0?"done":phase===0&&isRunning?"active":""],
              ["Stage (S3)", fmt_duration(job.stage_duration_s), phase>1?"done":phase===1&&isRunning?"active":""],
              ["Snowflake Load", fmt_duration(job.load_duration_s), job.status==="FAILED"?"fail":job.status==="SUCCEEDED"||job.status==="PARTIALLY_SUCCEEDED"?"done":phase===2&&isRunning?"active":""],
            ].map(([lbl,val,cls],i) => (
              <>
                <div key={lbl} className={`pnode ${cls}`}>
                  <div className="plbl">{lbl}</div>
                  <div className={`pval ${cls==="done"?"text-green":cls==="active"?"text-accent":cls==="fail"?"text-red":""}`}>
                    {cls==="active" ? <span className="pulse">●</span> : val}
                  </div>
                </div>
                {i < 2 && <div className="parr" key={`arr${i}`} />}
              </>
            ))}
          </div>
          <div className="job-pipeline-summary">
            {[
              ["Rows Exported",    (job.total_rows_exported||0).toLocaleString()],
              ["Data Volume",      fmt_bytes(job.total_bytes)],
              ["Tasks",            `${job.tasks_succeeded}/${job.task_count} succeeded · ${job.tasks_failed} failed`],
            ].map(([l,v]) => (
              <div key={l} className="job-pipeline-summary-item">
                <div className="job-summary-label">{l}</div>
                <div className="job-summary-value">{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="card">
        <div className="tabs">
          {[
            ["tasks", "Tasks"],
            ["runs",  "Runs"],
            ["state", "State"],
            ["validation", "Validation"],
            ["logs",  "Logs"],
          ].map(([t,lbl])=>(
            <div key={t} className={`tab ${tab===t?"active":""}`} onClick={()=>setTab(t)}>
              {lbl}
              {t==="logs"  && logs?.length  ? <span style={{ marginLeft:5, fontSize:10, background:"var(--bg3)", padding:"1px 5px", borderRadius:10, color:"var(--text3)" }}>{logs.length}</span> : null}
              {t==="runs"  && runs?.length  ? <span style={{ marginLeft:5, fontSize:10, background:"var(--bg3)", padding:"1px 5px", borderRadius:10, color:"var(--text3)" }}>{runs.length}</span> : null}
              {t==="state" && state?.length ? <span style={{ marginLeft:5, fontSize:10, background:"var(--bg3)", padding:"1px 5px", borderRadius:10, color:"var(--text3)" }}>{state.length}</span> : null}
              {t==="validation" && validations?.length ? <span style={{ marginLeft:5, fontSize:10, background:"var(--bg3)", padding:"1px 5px", borderRadius:10, color:"var(--text3)" }}>{validations.length}</span> : null}
            </div>
          ))}
        </div>

        {tab==="tasks" && (
          <>
            <div className="filter-bar">
              <div className="sw"><span className="si">🔍</span><input placeholder="Search table…" /></div>
              <select><option>All Datasets</option></select>
              <select><option>All Statuses</option><option>SUCCEEDED</option><option>RUNNING</option><option>FAILED</option><option>PENDING</option></select>
            </div>
            {!tasks?.length ? <div className="empty"><div className="empty-icon">🗂</div><div className="empty-msg">No tasks. Add tasks to this job.</div></div> : (
              <table>
                <thead><tr><th>Dataset</th><th>Target Schema</th><th>Table</th><th>PK / Watermark</th><th>Rows</th><th>Size</th><th>Status</th></tr></thead>
                <tbody>
                  {tasks.map(t=>{
                    const cfg = t.config || {};
                    const pk  = (cfg.primary_key_columns||[]).join(",") || "—";
                    const wm  = cfg.watermark_column || "—";
                    return (
                      <tr key={t.id}>
                        <td className="td-mono">{t.source_dataset}</td>
                        <td className="td-mono">{t.target_schema}</td>
                        <td className="td-main">{t.source_table}</td>
                        <td className="td-mono" style={{ fontSize:10 }}>{pk} / {wm}</td>
                        <td className="td-mono">{(t.rows_exported||0).toLocaleString()}</td>
                        <td className="td-mono">{fmt_bytes(t.bytes_exported)}</td>
                        <td><StatusBadge status={t.status} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab==="runs" && (
          <>
            {!runs?.length ? <div className="empty"><div className="empty-icon">⏱</div><div className="empty-msg">No runs yet. Click ▶ Execute to start a migration.</div></div> : (
              <table>
                <thead><tr><th>Attempt</th><th>Status</th><th>Mode</th><th>Started</th><th>Duration</th><th>Extracted</th><th>Loaded</th><th>Merged</th><th>Deleted</th><th>Tasks</th><th></th></tr></thead>
                <tbody>
                  {runs.map(r=>{
                    const tc = r.task_counts || {};
                    return (
                      <tr key={r.id} style={{ cursor:"pointer" }} onClick={()=>setSelectedRun(r.id)}>
                        <td className="td-mono">#{r.attempt_number}</td>
                        <td><StatusBadge status={r.status} /></td>
                        <td className="td-mono" style={{ fontSize:10 }}>{r.mode}</td>
                        <td className="td-mono" style={{ fontSize:10 }}>{r.started_at?new Date(r.started_at).toLocaleString():"—"}</td>
                        <td className="td-mono">{fmt_duration(r.duration_s)}</td>
                        <td className="td-mono">{(r.rows_extracted||0).toLocaleString()}</td>
                        <td className="td-mono">{(r.rows_loaded||0).toLocaleString()}</td>
                        <td className="td-mono">{(r.rows_merged||0).toLocaleString()}</td>
                        <td className="td-mono" style={{ color:r.rows_deleted>0?"var(--yellow)":"var(--text3)" }}>{(r.rows_deleted||0).toLocaleString()}</td>
                        <td className="td-mono" style={{ fontSize:10 }}>
                          <span style={{ color:"var(--green)" }}>{tc.succeeded||0}✓</span>{" "}
                          {tc.failed>0 && <span style={{ color:"var(--red)" }}>{tc.failed}✗</span>}{" "}
                          {tc.running>0 && <span style={{ color:"var(--yellow)" }}>{tc.running}…</span>}
                          {" / "}{tc.total||0}
                        </td>
                        <td><button className="btn btn-ghost btn-xs" onClick={(e)=>{e.stopPropagation(); setSelectedRun(r.id);}}>View</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab==="state" && (
          <>
            {!state?.length ? <div className="empty"><div className="empty-icon">📍</div><div className="empty-msg">No watermark state yet. State is populated after first incremental run.</div></div> : (
              <table>
                <thead><tr><th>Table</th><th>Strategy</th><th>PK Columns</th><th>Watermark Col</th><th>Last Watermark</th><th>Last Success</th></tr></thead>
                <tbody>
                  {state.map(s=>(
                    <tr key={s.id}>
                      <td className="td-mono">{s.table_key}</td>
                      <td className="td-mono" style={{ fontSize:10 }}>{s.strategy}</td>
                      <td className="td-mono" style={{ fontSize:10 }}>{(s.primary_key_columns||[]).join(", ")||"—"}</td>
                      <td className="td-mono" style={{ fontSize:10 }}>{s.watermark_column||"—"}</td>
                      <td className="td-mono">{s.last_watermark_value||"—"}</td>
                      <td className="td-mono" style={{ fontSize:10 }}>{s.last_success_at?new Date(s.last_success_at).toLocaleString():"Never"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab==="validation" && (
          <>
            {!validations?.length ? <div className="empty"><div className="empty-icon">✓</div><div className="empty-msg">No validation results yet. Results are saved after a migration run completes table validation.</div></div> : (
              <table>
                <thead><tr><th>Name</th><th>Type</th><th>Source</th><th>Target</th><th>Delta</th><th>Status</th><th>Last Run</th></tr></thead>
                <tbody>
                  {validations.map(v=>(
                    <tr key={v.id}>
                      <td className="td-main">{v.name}</td>
                      <td><span className="badge bb" style={{ fontSize:9 }}>{v.rule_type}</span></td>
                      <td className="td-mono" style={{ fontSize:10 }}>{v.source_value || "—"}</td>
                      <td className="td-mono" style={{ fontSize:10 }}>{v.target_value || "—"}</td>
                      <td className="td-mono" style={{ color:v.status==="FAILED"?"var(--red)":"var(--text3)" }}>{v.delta || "—"}</td>
                      <td><StatusBadge status={v.status} /></td>
                      <td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(v.last_run)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        {tab==="logs" && (
          <>
            <div className="filter-bar">
              <select value={levelF} onChange={e=>setLF(e.target.value)}>
                <option value="">All Levels</option>
                <option value="INFO">Info</option>
                <option value="WARN">Warn</option>
                <option value="ERROR">Error</option>
              </select>
              <select value={taskF} onChange={e=>setTF(e.target.value)}>
                <option value="">All Tasks</option>
                {[...new Set((logs||[]).map(l=>l.task_ref).filter(Boolean))].map(t=>(
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <div className="sw"><span className="si">🔍</span><input placeholder="Search message…" value={logSearch} onChange={e=>setLS(e.target.value)} /></div>
            </div>
            {!filteredLogs.length ? <div className="empty"><div className="empty-icon">📋</div><div className="empty-msg">No logs yet.</div></div> : (
              filteredLogs.map((l,i)=>(
                <div key={i} className="log-row">
                  <span style={{ fontFamily:"var(--font-m)",fontSize:10,color:"var(--text3)" }}>{new Date(l.created_at).toLocaleString()}</span>
                  <span><span className={`badge ${l.level==="ERROR"?"br":l.level==="WARN"?"by":"bgr"}`} style={{ fontSize:9 }}>{l.level}</span></span>
                  <span style={{ fontFamily:"var(--font-m)",fontSize:10,color:"var(--text3)" }}>{l.task_ref||"—"}</span>
                  <span style={{ fontFamily:"var(--font-m)",fontSize:10,color:"var(--accent)" }}>{l.event}</span>
                  <span style={{ fontSize:11,color:"var(--text2)" }}>{l.message}</span>
                  {l.detail && <button className="btn btn-ghost btn-xs" onClick={()=>setVL(l)}>View</button>}
                </div>
              ))
            )}
          </>
        )}
      </div>

      {selectedRun && <RunDetailModal jobId={job.id} runId={selectedRun} onClose={()=>setSelectedRun(null)} />}
      {viewLog && (
        <div className="modal-ov" onClick={()=>setVL(null)}>
          <div className="modal" onClick={e=>e.stopPropagation()}>
            <div className="modal-hdr"><div className="modal-title">{viewLog.event}</div><button className="btn btn-ghost btn-icon btn-sm" onClick={()=>setVL(null)}>✕</button></div>
            <div className="modal-body">
              <div className="text-muted mb2" style={{ fontSize:11 }}>{viewLog.message}</div>
              <pre style={{ background:"var(--bg3)", padding:12, borderRadius:6, fontSize:11, overflow:"auto", maxHeight:400 }}>{viewLog.detail}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RunDetailModal({ jobId, runId, onClose }) {
  const { data, loading, error } = useApi(() => api.getJobRunDetail(jobId, runId), [jobId, runId]);
  const run = data?.run;
  const taskRuns = data?.task_runs || [];
  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{ maxWidth:900 }}>
        <div className="modal-hdr">
          <div className="modal-title">Run Detail{run ? ` — Attempt #${run.attempt_number}` : ""}</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {loading ? <Loading /> : error ? <ErrMsg msg={error} /> : run ? (
            <>
              <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:10, marginBottom:14 }}>
                {[
                  ["Status",   <StatusBadge status={run.status} />],
                  ["Mode",     run.mode],
                  ["Duration", fmt_duration(run.duration_s)],
                  ["Tasks",    taskRuns.length],
                ].map(([l,v],i)=>(
                  <div key={i} style={{ background:"var(--bg3)", border:"1px solid var(--border)", borderRadius:6, padding:10 }}>
                    <div style={{ fontSize:9, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase" }}>{l}</div>
                    <div style={{ fontSize:13, fontWeight:600, marginTop:3 }}>{v}</div>
                  </div>
                ))}
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:10, marginBottom:14 }}>
                {[
                  ["Extracted", (run.rows_extracted||0).toLocaleString()],
                  ["Loaded",    (run.rows_loaded||0).toLocaleString()],
                  ["Merged",    (run.rows_merged||0).toLocaleString()],
                  ["Deleted",   (run.rows_deleted||0).toLocaleString()],
                ].map(([l,v],i)=>(
                  <div key={i} style={{ background:"var(--bg3)", border:"1px solid var(--border)", borderRadius:6, padding:10 }}>
                    <div style={{ fontSize:9, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase" }}>{l}</div>
                    <div style={{ fontSize:13, fontWeight:600, fontFamily:"var(--font-m)", marginTop:3 }}>{v}</div>
                  </div>
                ))}
              </div>
              {run.error_message && (
                <div style={{ background:"var(--bg3)", border:"1px solid var(--red)", borderRadius:6, padding:10, marginBottom:14 }}>
                  <div style={{ fontSize:10, fontWeight:700, color:"var(--red)" }}>ERROR</div>
                  <div style={{ fontSize:11, fontFamily:"var(--font-m)", marginTop:3, whiteSpace:"pre-wrap" }}>{run.error_message}</div>
                </div>
              )}
              <div style={{ fontSize:11, fontWeight:700, color:"var(--text2)", marginBottom:6 }}>Per-table breakdown</div>
              {!taskRuns.length ? <div className="text-muted">No table runs recorded.</div> : (
                <table>
                  <thead><tr><th>Table</th><th>Status</th><th>Duration</th><th>Extracted</th><th>Loaded</th><th>Merged</th><th>Watermark</th></tr></thead>
                  <tbody>
                    {taskRuns.map(tr=>(
                      <tr key={tr.id}>
                        <td className="td-mono" style={{ fontSize:11 }}>{tr.table_key}</td>
                        <td><StatusBadge status={tr.status} /></td>
                        <td className="td-mono">{fmt_duration(tr.duration_s)}</td>
                        <td className="td-mono">{(tr.rows_extracted||0).toLocaleString()}</td>
                        <td className="td-mono">{(tr.rows_loaded||0).toLocaleString()}</td>
                        <td className="td-mono">{(tr.rows_merged||0).toLocaleString()}</td>
                        <td className="td-mono" style={{ fontSize:10 }}>{tr.watermark_start||"—"} → {tr.watermark_end||"—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}


// ─── Create Job Modal ─────────────────────────────────────────
function CreateJobModal({ onClose }) {
  const [step, setStep]   = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm]   = useState({
    name:"", source_connection_id:"", dest_connection_id:"",
    sf_warehouse:"", sf_database:"", sf_schema:"", sf_role:"",
    destination_mode:"internal", load_strategy:"full_load", file_format:"parquet", staging_area:"internal",
    tasks:[]
  });
  const [taskDraft, setTaskDraft] = useState({
    source_dataset:"public",
    source_table:"",
    target_schema:"",
    target_table:"",
    primary_key_columns:"",
    watermark_column:"",
    batch_size:"50000",
  });
  const [autoFilledConnectionId, setAutoFilledConnectionId] = useState("");
  const [loadingDest, setLoadingDest] = useState(false);
  const [destWarning, setDestWarning] = useState("");
  const [destTouched, setDestTouched] = useState({});

  const { data: conns } = useApi(() => api.getConnections(), []);
  const sources = (conns||[]).filter(c => canUseAsSource(c) && c.type !== "snowflake");
  const sfConns = (conns||[]).filter(c => c.type === "snowflake" && canUseAsTarget(c));

  const steps = ["Source","Destination","Config","Review"];

  const handleCreate = async () => {
    setSaving(true); setError("");
    try {
      const tasks = form.tasks.length ? form.tasks : (taskDraft.source_table ? [{
        source_dataset: taskDraft.source_dataset || "public",
        source_table: taskDraft.source_table,
        target_schema: taskDraft.target_schema || form.sf_schema,
        target_table: taskDraft.target_table || taskDraft.source_table,
        config: {
          primary_key_columns: taskDraft.primary_key_columns.split(",").map(s=>s.trim()).filter(Boolean),
          watermark_column: taskDraft.watermark_column || null,
          batch_size: Number(taskDraft.batch_size || 50000),
        },
      }] : []);
      await api.createJob({ ...form, tasks });
      onClose();
    } catch(e) {
      setError(e.message);
      setSaving(false);
    }
  };

  const setDestConnection = async (connectionId) => {
    setForm(prev => ({ ...prev, dest_connection_id: connectionId }));
    setDestWarning("");
    if (!connectionId) {
      setAutoFilledConnectionId("");
      return;
    }
    setLoadingDest(true);
    try {
      const conn = await api.getConnection(connectionId);
      const cfg = conn.config || {};
      const missing = ["warehouse", "database", "schema", "role"].filter(k => !cfg[k]);
      setForm(prev => {
        return {
          ...prev,
          dest_connection_id: connectionId,
          sf_warehouse: destTouched.sf_warehouse ? prev.sf_warehouse : (cfg.warehouse || ""),
          sf_database:  destTouched.sf_database  ? prev.sf_database  : (cfg.database  || ""),
          sf_schema:    destTouched.sf_schema    ? prev.sf_schema    : (cfg.schema    || ""),
          sf_role:      destTouched.sf_role      ? prev.sf_role      : (cfg.role      || ""),
        };
      });
      setAutoFilledConnectionId(connectionId);
      if (missing.length) setDestWarning(`Saved Snowflake connection is missing: ${missing.join(", ")}. Fill the empty fields before running.`);
    } catch (e) {
      setDestWarning(`Could not load Snowflake connection details: ${e.message}`);
    } finally {
      setLoadingDest(false);
    }
  };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal modal-lg" onClick={e=>e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">Create Migration Job</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="steps">
            {steps.map((s,i)=>(
              <div key={s} className={`step ${i===step?"active":i<step?"done":""}`}>
                <div className="sdot2">{i<step?"✓":i+1}</div>
                <div className="step-lbl">{s}</div>
                {i<steps.length-1 && <div className="step-line" />}
              </div>
            ))}
          </div>

          {error && <ErrMsg msg={error} />}

          {step===0 && (
            <>
              <div className="fg">
                <label className="fl">Job Name</label>
                <input className="fi" placeholder="e.g. postgres_retail_to_snowflake"
                  value={form.name} onChange={e=>setForm({...form,name:e.target.value})} />
              </div>
              <div className="fg">
                <label className="fl">Source Connection</label>
                <select className="fi" value={form.source_connection_id} onChange={e=>setForm({...form,source_connection_id:e.target.value})}>
                  <option value="">Select source…</option>
                  {sources.map(c=><option key={c.id} value={c.id}>{c.name} ({c.type})</option>)}
                </select>
              </div>
              <div style={{ fontSize:12, color:"var(--text3)", padding:"10px 12px", background:"var(--bg3)", borderRadius:"var(--r)", border:"1px solid var(--border)" }}>
                Don't see your source? <span style={{ color:"var(--accent)", cursor:"pointer" }}>Add a connection first →</span>
              </div>
            </>
          )}

          {step===1 && (
            <>
              <div style={{ background:"rgba(0,212,255,.06)", border:"1px solid rgba(0,212,255,.15)", borderRadius:"var(--r)", padding:"12px 14px", marginBottom:14 }}>
                <div style={{ fontSize:12, fontWeight:700, color:"var(--accent)", marginBottom:3 }}>❄️ Snowflake Destination</div>
                <div style={{ fontSize:11, color:"var(--text2)" }}>All jobs land in Snowflake. Configure your warehouse, database, schema, and role.</div>
              </div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Snowflake Connection</label>
                  <select className="fi" value={form.dest_connection_id} onChange={e=>setDestConnection(e.target.value)}>
                    <option value="">Select Snowflake…</option>
                    {sfConns.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                  {loadingDest && <div className="fhint">Loading saved Snowflake defaults…</div>}
                </div>
                <div className="fg">
                  <label className="fl">Warehouse</label>
                  <input className="fi" value={form.sf_warehouse} onChange={e=>{ setDestTouched(t=>({...t,sf_warehouse:true})); setForm({...form,sf_warehouse:e.target.value}); }} />
                </div>
              </div>
              {destWarning && <div className="alert-err" style={{ marginTop:10 }}>{destWarning}</div>}
              <div className="fr">
                <div className="fg">
                  <label className="fl">Database</label>
                  <input className="fi" value={form.sf_database} onChange={e=>{ setDestTouched(t=>({...t,sf_database:true})); setForm({...form,sf_database:e.target.value}); }} />
                </div>
                <div className="fg">
                  <label className="fl">Schema</label>
                  <input className="fi" value={form.sf_schema} onChange={e=>{ setDestTouched(t=>({...t,sf_schema:true})); setForm({...form,sf_schema:e.target.value}); }} />
                </div>
              </div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Role</label>
                  <input className="fi" value={form.sf_role} onChange={e=>{ setDestTouched(t=>({...t,sf_role:true})); setForm({...form,sf_role:e.target.value}); }} />
                </div>
                <div className="fg">
                  <label className="fl">Destination Mode</label>
                  <select className="fi" value={form.destination_mode} onChange={e=>setForm({...form,destination_mode:e.target.value})}>
                    <option value="internal">Internal Tables (default)</option>
                    <option value="external_stage">External Stage</option>
                    <option value="external_table">External Table</option>
                    <option value="iceberg">Iceberg / External Volume</option>
                  </select>
                </div>
              </div>
            </>
          )}

          {step===2 && (
            <>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Load Strategy</label>
                  <select className="fi" value={form.load_strategy} onChange={e=>setForm({...form,load_strategy:e.target.value})}>
                    <option value="full_load">Full Load (truncate + reload)</option>
                    <option value="incremental">Incremental (append)</option>
                    <option value="cdc">CDC (change data capture)</option>
                    <option value="upsert">Upsert (merge)</option>
                  </select>
                </div>
                <div className="fg">
                  <label className="fl">Staging Area</label>
                  <select className="fi" value={form.staging_area} onChange={e=>setForm({...form,staging_area:e.target.value})}>
                    <option value="s3">Amazon S3</option>
                    <option value="azure">Azure Blob</option>
                    <option value="gcs">Google Cloud Storage</option>
                    <option value="internal">Snowflake Internal Stage</option>
                  </select>
                </div>
              </div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">File Format</label>
                  <select className="fi" value={form.file_format} onChange={e=>setForm({...form,file_format:e.target.value})}>
                    <option value="parquet">Parquet (recommended)</option>
                    <option value="csv">CSV</option>
                    <option value="json">JSON</option>
                    <option value="avro">Avro</option>
                  </select>
                </div>
                <div className="fg">
                  <label className="fl">Schedule</label>
                  <select className="fi">
                    <option>Manual</option>
                    <option>Hourly</option>
                    <option>Daily at midnight</option>
                    <option>Custom cron</option>
                  </select>
                </div>
              </div>
              <div className="divider" />
              <div style={{ fontSize:12, fontWeight:800, marginBottom:10 }}>First Table Task</div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Source Schema / Dataset</label>
                  <input className="fi" value={taskDraft.source_dataset} onChange={e=>setTaskDraft({...taskDraft,source_dataset:e.target.value})} placeholder="raw" />
                </div>
                <div className="fg">
                  <label className="fl">Source Table</label>
                  <input className="fi" value={taskDraft.source_table} onChange={e=>setTaskDraft({...taskDraft,source_table:e.target.value,target_table:taskDraft.target_table||e.target.value})} placeholder="customers" />
                </div>
              </div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Target Schema</label>
                  <input className="fi" value={taskDraft.target_schema || form.sf_schema} onChange={e=>setTaskDraft({...taskDraft,target_schema:e.target.value})} placeholder={form.sf_schema || "RAW"} />
                </div>
                <div className="fg">
                  <label className="fl">Target Table</label>
                  <input className="fi" value={taskDraft.target_table} onChange={e=>setTaskDraft({...taskDraft,target_table:e.target.value})} placeholder="customers" />
                </div>
              </div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Primary Key Columns</label>
                  <input className="fi" value={taskDraft.primary_key_columns} onChange={e=>setTaskDraft({...taskDraft,primary_key_columns:e.target.value})} placeholder="customer_id" />
                  <div className="fhint">Required for incremental, CDC, and upsert MERGE.</div>
                </div>
                <div className="fg">
                  <label className="fl">Watermark Column</label>
                  <input className="fi" value={taskDraft.watermark_column} onChange={e=>setTaskDraft({...taskDraft,watermark_column:e.target.value})} placeholder="updated_at" />
                </div>
              </div>
            </>
          )}

          {step===3 && (
            <div style={{ background:"var(--bg3)", borderRadius:"var(--r)", padding:14 }}>
              <div style={{ fontSize:10,fontWeight:700,color:"var(--text3)",letterSpacing:1,textTransform:"uppercase",fontFamily:"var(--font-m)",marginBottom:10 }}>Job Summary</div>
              {[
                ["Name",        form.name || "(unnamed)"],
                ["Source",      sources.find(c=>c.id===form.source_connection_id)?.name || "Not selected"],
                ["Destination", "❄️ " + (sfConns.find(c=>c.id===form.dest_connection_id)?.name || "Snowflake")],
                ["Warehouse",   form.sf_warehouse],
                ["Database",    `${form.sf_database}.${form.sf_schema}`],
                ["Role",        form.sf_role],
                ["Strategy",    form.load_strategy],
                ["Format",      form.file_format],
                ["Task",        taskDraft.source_table ? `${taskDraft.source_dataset}.${taskDraft.source_table} → ${taskDraft.target_schema || form.sf_schema}.${taskDraft.target_table || taskDraft.source_table}` : "No task configured"],
              ].map(([k,v])=>(
                <div key={k} style={{ display:"flex",justifyContent:"space-between",padding:"6px 0",borderBottom:"1px solid var(--border)",fontSize:12 }}>
                  <span style={{ color:"var(--text3)" }}>{k}</span>
                  <span style={{ color:"var(--text)",fontWeight:600,fontFamily:"var(--font-m)" }}>{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={step===0?onClose:()=>setStep(s=>s-1)}>{step===0?"Cancel":"← Back"}</button>
          {step<3
            ? <button className="btn btn-primary" onClick={()=>setStep(s=>s+1)}>Continue →</button>
            : <button className="btn btn-primary" onClick={handleCreate} disabled={saving}>{saving?<Spinner/>:"✓ Create Job"}</button>
          }
        </div>
      </div>
    </div>
  );
}

// ─── Connections ──────────────────────────────────────────────
function ConnectionsPage() {
  const { data: conns, loading, error, refetch } = useApi(() => api.getConnections(), []);
  const [showNew, setNew] = useState(false);
  const [editing, setEditing] = useState(null);
  const [testing, setTest] = useState({});
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [healthFilter, setHealthFilter] = useState("all");
  const [connectionKpiFilter, setConnectionKpiFilter] = useState("all");
  const [viewing, setViewing] = useState(null);
  const [lastResult, setLastResult] = useState(null);
  const [activeTest, setActiveTest] = useState(null);
  const [mfaTest, setMfaTest] = useState(null);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaAuthMethod, setMfaAuthMethod] = useState("password_mfa");

  const rows = conns || [];
  const filtered = rows.filter(c => {
    const matchSearch = !search.trim() || [c.name, c.description, c.type].filter(Boolean).join(" ").toLowerCase().includes(search.toLowerCase());
    const matchType = typeFilter === "all" || c.type === typeFilter;
    const matchHealth = healthFilter === "all" || c.health === healthFilter;
    const matchKpi = connectionKpiFilter === "all" || (connectionKpiFilter === "source" ? canUseAsSource(c) : connectionKpiFilter === "target" ? canUseAsTarget(c) : true);
    return matchSearch && matchType && matchHealth && matchKpi;
  });

  const stats = {
    total: rows.length,
    sources: rows.filter(canUseAsSource).length,
    targets: rows.filter(canUseAsTarget).length,
    healthy: rows.filter(c=>c.health === 'healthy').length,
    failed: rows.filter(c=>c.health === 'failed').length,
    unknown: rows.filter(c=>!c.health || c.health === 'unknown' || c.health === 'warn').length,
  };
  const sourceRows = filtered.filter(canUseAsSource);
  const targetRows = filtered.filter(canUseAsTarget);
  const healthRows = filtered.slice(0, 8).map(c => ({
    connection: c,
    auth: c.credentials && Object.keys(c.credentials || {}).length ? "configured" : "needs_secret",
    network: c.health === "healthy" ? "reachable" : c.health === "failed" ? "failed" : "not_checked",
    secret: c.credentials && Object.keys(c.credentials || {}).length ? "stored" : "missing",
    permission: c.health === "healthy" ? "verified" : "not_verified",
    latestError: c.latest_error || c.error_message || (c.health === "failed" ? "Connection test failed. Open details and rerun diagnostics." : ""),
  }));

  const ConnectionTable = ({ rows: tableRows, empty }) => (
    !tableRows.length ? (
      <div className="empty" style={{ padding:24 }}><div className="empty-msg">{empty}</div></div>
    ) : (
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Role</th><th>Description</th><th>Last Tested</th><th>Health</th><th>Actions</th></tr></thead>
        <tbody>
          {tableRows.map(c=>(
            <tr key={`${c.id}-${empty}`}>
              <td className="td-main" style={{ cursor:'pointer' }} onClick={()=>openDetails(c.id)}>{c.name}</td>
              <td><SourcePill type={c.type} /></td>
              <td><span className="badge bb" style={{ fontSize:9, textTransform:"uppercase" }}>{connRole(c)}</span></td>
              <td style={{ color:"var(--text3)", fontSize:11 }}>{c.description || "—"}</td>
              <td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(c.last_tested)}</td>
              <td><div style={{ display:"flex", alignItems:"center", gap:6 }}><HealthDot health={c.health} /><span style={{ fontSize:11,color:c.health==="healthy"?"var(--green)":c.health==="failed"?"var(--red)":"var(--yellow)",textTransform:"capitalize" }}>{c.health || 'unknown'}</span></div></td>
              <td>
                <div className="ep-row-actions">
                  <button className="btn btn-ghost btn-icon btn-sm" title="Test connection" aria-label={`Test ${c.name}`} onClick={()=>handleTest(c)} disabled={testing[c.id]}>
                    {testing[c.id] ? <Spinner/> : <RefreshCw size={14} />}
                  </button>
                  <button className="btn btn-ghost btn-icon btn-sm" title="Edit connection" aria-label={`Edit ${c.name}`} onClick={()=>handleEdit(c.id)}>
                    <Pencil size={14} />
                  </button>
                  <button className="btn btn-danger btn-icon btn-sm" title="Delete connection" aria-label={`Delete ${c.name}`} onClick={()=>handleDelete(c.id)}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  );

  const runConnectionTest = async (conn, body = {}) => {
    setTest(t=>({...t,[conn.id]:true}));
    setActiveTest(conn);
    try {
      const r = await api.testConnection(conn.id, body);
      setLastResult({ connection: conn, result: r });
    } catch (e) {
      setLastResult({ connection: conn, result: { success:false, error:e.message, diagnostic:e.message } });
    }
    setTest(t=>({...t,[conn.id]:false}));
    setActiveTest(null);
    refetch();
  };

  const handleTest = async (conn) => {
    if (conn?.type === "snowflake") {
      setMfaCode("");
      setMfaAuthMethod(conn?.config?.auth_method || "password_mfa");
      setMfaTest(conn);
      return;
    }
    await runConnectionTest(conn);
  };

  const submitMfaTest = async () => {
    if (!mfaTest) return;
    const conn = mfaTest;
    const body = { auth_method: mfaAuthMethod };
    if (mfaAuthMethod === "password_mfa") body.mfa_passcode = mfaCode;
    setMfaTest(null);
    await runConnectionTest(conn, body);
    setMfaCode("");
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this connection?")) return;
    await api.deleteConnection(id);
    if (viewing?.id === id) setViewing(null);
    refetch();
  };

  const handleEdit = async (id) => {
    try {
      const full = await api.getConnection(id);
      setEditing(full);
    } catch(e) { alert("Couldn't load connection: " + e.message); }
  };

  const openDetails = async (id) => {
    try {
      const full = await api.getConnection(id);
      setViewing(full);
    } catch(e) { alert("Couldn't load connection: " + e.message); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-eyebrow">Data Plane</div>
          <div className="page-title">Connections</div>
          <div className="page-subtitle">Live source and Snowflake endpoint health, with auth, network, secret, permission, usage, and latest error evidence.</div>
        </div>
        <div className="page-actions"><button className="btn btn-primary" onClick={()=>setNew(true)}>+ New Connection</button></div>
      </div>

      <div className={`ep-alert-strip ${stats.failed ? "has-blockers" : ""}`}>
        <div>
          <div className="ep-alert-kicker">{stats.failed ? "Connection blockers" : "Connection posture"}</div>
          <div className="ep-alert-title">{stats.failed ? `${stats.failed} endpoint${stats.failed === 1 ? "" : "s"} failing health checks` : `${stats.healthy}/${stats.total || 0} endpoints healthy`}</div>
        </div>
        <div className="ep-alert-items">
          <button
            type="button"
            className={`ep-alert-action ${stats.failed ? "danger" : "success"} ${healthFilter === "failed" ? "active" : ""}`}
            onClick={() => {
              setConnectionKpiFilter("all");
              setTypeFilter("all");
              setHealthFilter(stats.failed ? "failed" : "all");
            }}
          >
            <span className="ep-action-count">{stats.failed}</span>
            <span>{stats.failed === 1 ? "Failed endpoint" : "Failed endpoints"}</span>
          </button>
          <button type="button" className="ep-alert-action primary" onClick={() => setNew(true)}>
            <PlusCircle size={15} />
            <span>Add endpoint</span>
          </button>
        </div>
      </div>

      <div className="ep-kpi-row">
        <button className={`ep-kpi ${connectionKpiFilter === "all" && typeFilter === "all" && healthFilter === "all" ? "active" : ""}`} type="button" onClick={() => { setConnectionKpiFilter("all"); setTypeFilter("all"); setHealthFilter("all"); }}><div className="ep-kpi-label">Connections</div><div className="ep-kpi-value">{stats.total}</div><div className="ep-kpi-note">registered endpoints</div></button>
        <button className={`ep-kpi ${connectionKpiFilter === "source" ? "active" : ""}`} type="button" onClick={() => { setConnectionKpiFilter("source"); setTypeFilter("all"); setHealthFilter("all"); }}><div className="ep-kpi-label">Sources</div><div className="ep-kpi-value">{stats.sources}</div><div className="ep-kpi-note">extractable endpoints</div></button>
        <button className={`ep-kpi ${connectionKpiFilter === "target" ? "active" : ""}`} type="button" onClick={() => { setConnectionKpiFilter("target"); setTypeFilter("all"); setHealthFilter("all"); }}><div className="ep-kpi-label">Targets</div><div className="ep-kpi-value">{stats.targets}</div><div className="ep-kpi-note">Snowflake/load targets</div></button>
        <button className={`ep-kpi ${healthFilter === "healthy" ? "active" : ""}`} type="button" onClick={() => { setConnectionKpiFilter("all"); setTypeFilter("all"); setHealthFilter("healthy"); }}><div className="ep-kpi-label">Healthy</div><div className="ep-kpi-value">{stats.healthy}</div><div className="ep-kpi-note">ready to use</div></button>
        <button className={`ep-kpi ${healthFilter === "failed" ? "active" : ""}`} type="button" onClick={() => { setConnectionKpiFilter("all"); setTypeFilter("all"); setHealthFilter("failed"); }}><div className="ep-kpi-label">Failed</div><div className="ep-kpi-value">{stats.failed}</div><div className="ep-kpi-note">fix required</div></button>
        <button className={`ep-kpi ${healthFilter === "unknown" ? "active" : ""}`} type="button" onClick={() => { setConnectionKpiFilter("all"); setTypeFilter("all"); setHealthFilter("unknown"); }}><div className="ep-kpi-label">Unknown</div><div className="ep-kpi-value">{stats.unknown}</div><div className="ep-kpi-note">test needed</div></button>
      </div>

      <div className="ep-health-grid">
        <div className="ep-split-table">
          <div className="ep-split-toolbar">
            <div className="sw"><span className="si">🔍</span><input placeholder="Search connections…" value={search} onChange={e=>setSearch(e.target.value)} /></div>
            <select value={typeFilter} onChange={e=>setTypeFilter(e.target.value)}><option value="all">All Types</option>{SRC.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <select value={healthFilter} onChange={e=>setHealthFilter(e.target.value)}><option value="all">All Health</option><option value="healthy">Healthy</option><option value="failed">Failed</option><option value="warn">Warning</option><option value="unknown">Unknown</option></select>
          </div>
          {error && <ErrMsg msg={error} />}
          {loading ? <Loading /> : !healthRows.length ? (
            <DashboardEmpty
              icon={<Plug size={18} />}
              title={rows.length ? "No connections match your filters." : "No endpoints configured"}
              message={rows.length ? "Adjust filters to see source and Snowflake endpoints." : "Add a source endpoint and a Snowflake target before running migration readiness, conversion validation, or package gates."}
              action={(
                <div className="flex gap2" style={{ justifyContent: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-primary btn-sm" onClick={()=>setNew({ type: "postgres", connection_role: "source" })}>Add source connection</button>
                  <button className="btn btn-ghost btn-sm" onClick={()=>setNew({ type: "snowflake", connection_role: "target" })}>Add Snowflake target</button>
                </div>
              )}
            />
          ) : (
            <table>
              <thead><tr><th>Connection</th><th>Type</th><th>Role</th><th>Auth</th><th>Network</th><th>Secret</th><th>Permissions</th><th>Last checked</th><th>Latest error</th><th>Actions</th></tr></thead>
              <tbody>{healthRows.map(({ connection, auth, network, secret, permission, latestError }) => (
                <tr key={`health-${connection.id}`} className={viewing?.id === connection.id ? "ep-selected-row" : ""} onClick={() => openDetails(connection.id)} style={{ cursor:"pointer" }}>
                  <td className="td-main">{connection.name}</td>
                  <td><SourcePill type={connection.type} /></td>
                  <td><span className="badge bb" style={{ fontSize:9, textTransform:"uppercase" }}>{connRole(connection)}</span></td>
                  <td><StatusBadge status={auth} /></td>
                  <td><StatusBadge status={network} /></td>
                  <td><StatusBadge status={secret} /></td>
                  <td><StatusBadge status={permission} /></td>
                  <td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(connection.last_tested)}</td>
                  <td className={latestError ? "run-error" : "text-muted"}>{latestError || "—"}</td>
                  <td>
                    <div className="ep-row-actions" onClick={(event) => event.stopPropagation()}>
                      <button className="btn btn-ghost btn-icon btn-sm" title="Test connection" aria-label={`Test ${connection.name}`} onClick={() => handleTest(connection)} disabled={testing[connection.id]}>
                        {testing[connection.id] ? <Spinner/> : <RefreshCw size={14} />}
                      </button>
                      <button className="btn btn-ghost btn-icon btn-sm" title="Edit connection" aria-label={`Edit ${connection.name}`} onClick={() => handleEdit(connection.id)}>
                        <Pencil size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>
        <aside className="ep-detail-panel">
          <div className="ep-detail-head">
            <div>
              <div className="ep-detail-title">{viewing?.name || "Select a connection"}</div>
              <div className="ep-detail-subtitle">{viewing ? `${viewing.type} · ${connRole(viewing)} · ${viewing.description || "No description"}` : "Connection detail appears here without leaving the health table."}</div>
            </div>
            {viewing ? <StatusBadge status={viewing.health || "UNKNOWN"} /> : null}
          </div>
          {viewing ? (
            <>
              <div className="ep-detail-actions">
                <button className="btn btn-primary btn-sm" onClick={()=>handleTest(viewing)}>Test</button>
                <button className="btn btn-ghost btn-sm" onClick={()=>handleEdit(viewing.id)}>Edit</button>
                <button className="btn btn-ghost btn-sm" disabled>View jobs</button>
              </div>
              <div className="ep-detail-body">
                <div className="ep-section-label">Health evidence</div>
                <table><tbody>{[
                  ["Type", <SourcePill type={viewing.type} />],
                  ["Role", connRole(viewing)],
                  ["Last tested", fmt_dt(viewing.last_tested)],
                  ["Auth", Object.keys(viewing.credentials || {}).length ? "Configured" : "Missing secret"],
                  ["Network", viewing.health === "healthy" ? "Reachable" : viewing.health === "failed" ? "Failed" : "Not checked"],
                  ["Permissions", viewing.health === "healthy" ? "Verified" : "Not verified"],
                ].map(([label, value])=><tr key={label}><td className="td-main">{label}</td><td>{value}</td></tr>)}</tbody></table>
                <div className="ep-section-label">Latest error</div>
                <div className="ep-empty-compact">{viewing.latest_error || viewing.error_message || (viewing.health === "failed" ? "Connection test failed. Edit settings or rerun diagnostics." : "No latest error recorded.")}</div>
                <div className="ep-section-label">Configuration</div>
                {!Object.keys(viewing.config || {}).length ? <div className="ep-empty-compact">No non-sensitive configuration captured.</div> : <table><tbody>{Object.entries(viewing.config || {}).map(([k,v])=><tr key={k}><td className="td-main">{k}</td><td className="td-mono" style={{ fontSize:10 }}>{String(v)}</td></tr>)}</tbody></table>}
              </div>
            </>
          ) : <div className="ep-detail-body"><div className="ep-right-placeholder">Select an endpoint to see auth, network, secret, permission, latest error, configuration, and actions.</div></div>}
        </aside>
      </div>

      <ContextDrawer
        open={false}
        title={viewing?.name || "Connection"}
        subtitle="Connection metadata, readiness path, actions, and masked configuration"
        status={viewing ? <span style={{ display:"inline-flex", alignItems:"center", gap:8 }}><HealthDot health={viewing.health} /><span style={{ textTransform:"capitalize" }}>{viewing.health || "unknown"}</span></span> : null}
        onClose={() => setViewing(null)}
        metadata={viewing ? [
          { label:"Type", value:<SourcePill type={viewing.type} /> },
          { label:"Role", value:<span className="badge bb" style={{ fontSize:9, textTransform:"uppercase" }}>{connRole(viewing)}</span> },
          { label:"Last tested", value:fmt_dt(viewing.last_tested) },
          { label:"Description", value:viewing.description || "-" },
        ] : []}
        history={viewing ? [
          { id:"opened", status:viewing.health === "healthy" ? "validated" : viewing.health === "failed" ? "blocked" : "review", title:"Connection opened", detail:"Review configuration and run a test before using in migration flows." },
          { id:"role", status:connRole(viewing) === "target" ? "active" : "validated", title:`${connRole(viewing)} connection`, detail:viewing.type === "snowflake" ? "Snowflake target path" : "Source extraction path" },
        ] : []}
        graph={viewing ? {
          nodes:[
            { id:"uma", label:"UMA", type:"Analysis Layer", x:14, y:50, status:"active" },
            { id:"auth", label:"Auth", type:"Validation Check", x:42, y:32, status:viewing.health === "failed" ? "blocked" : "review" },
            { id:"conn", label:viewing.name, type:viewing.type === "snowflake" ? "Snowflake Table" : "Source Database", x:70, y:50, status:viewing.health === "healthy" ? "completed" : viewing.health === "failed" ? "failed" : "warning" },
            { id:"flow", label:connRole(viewing) === "target" ? "Snowflake" : "Inventory", type:connRole(viewing) === "target" ? "Snowflake Table" : "Schema Scan", x:90, y:68, status:viewing.health === "healthy" ? "validated" : "pending" },
          ],
          edges:[
            { from:"uma", to:"auth", status:viewing.health === "failed" ? "blocked" : "active" },
            { from:"auth", to:"conn", status:viewing.health === "healthy" ? "validated" : viewing.health === "failed" ? "blocked" : "review" },
            { from:"conn", to:"flow", status:viewing.health === "healthy" ? "validated" : "review" },
          ],
        } : null}
        actions={viewing ? (
          <div style={{ display:"grid", gap:12 }}>
            <div>
              <div className="settings-title">Non-sensitive Config</div>
              {!Object.keys(viewing.config || {}).length ? <DashboardEmpty icon={<Settings size={16} />} title="No config captured." message="Save non-sensitive connection settings to display them here." /> : (
                <table>
                  <thead><tr><th>Key</th><th>Value</th></tr></thead>
                  <tbody>{Object.entries(viewing.config || {}).map(([k,v])=><tr key={k}><td className="td-main">{k}</td><td className="td-mono" style={{ fontSize:10 }}>{String(v)}</td></tr>)}</tbody>
                </table>
              )}
            </div>
            <div>
              <div className="settings-title">Credential Hints</div>
              {!Object.keys(viewing.credentials || {}).length ? <DashboardEmpty icon={<Settings size={16} />} title="No credential hints available." message="UMA only shows masked credential hints after they are saved." /> : (
                <table>
                  <thead><tr><th>Field</th><th>Stored</th></tr></thead>
                  <tbody>{Object.entries(viewing.credentials || {}).map(([k,v])=><tr key={k}><td className="td-main">{k}</td><td className="td-mono" style={{ fontSize:10 }}>{String(v)}</td></tr>)}</tbody>
                </table>
              )}
            </div>
            <div style={{ display:"flex", justifyContent:"flex-end", gap:8 }}>
              <button className="btn btn-ghost" onClick={()=>handleEdit(viewing.id)}>Edit</button>
              <button className="btn btn-primary" onClick={()=>handleTest(viewing)}>Run Test</button>
            </div>
          </div>
        ) : null}
      />

      {lastResult && (
        <Modal title={`Connection Test — ${lastResult.connection.name}`} onClose={()=>setLastResult(null)} width={680}>
          <div className={lastResult.result?.success ? 'alert-ok' : 'alert-err'}>
            {lastResult.result?.success ? '✓ Connection successful' : `✗ ${lastResult.result?.diagnostic || 'Connection failed'}`}
          </div>
          <AnimatedConnectionTest
            connection={lastResult.connection}
            result={lastResult.result}
            checks={connectionTestChecklist(lastResult.connection, lastResult.result, false)}
          />
          <div className="divider" />
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <div>
              <div className="settings-title">Summary</div>
              <div style={{ display:'grid', gap:10 }}>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Status</div><div style={{ marginTop:6 }}>{lastResult.result?.success ? 'Success' : 'Failed'}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Duration</div><div style={{ marginTop:6, fontFamily:'var(--font-m)' }}>{lastResult.result?.duration_ms ? `${lastResult.result.duration_ms} ms` : '—'}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Diagnostic</div><div style={{ marginTop:6, fontSize:12 }}>{lastResult.result?.diagnostic || '—'}</div></div>
              </div>
            </div>
            <div>
              <div className="settings-title">Raw Result</div>
              <pre style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:12, fontSize:11, color:'var(--text2)', fontFamily:'var(--font-m)', overflow:'auto', maxHeight:280 }}>
                {JSON.stringify(lastResult.result, null, 2)}
              </pre>
            </div>
          </div>
        </Modal>
      )}

      {activeTest && (
        <Modal title={`Testing ${activeTest.name}`} onClose={()=>{}} width={620}>
          <div className="alert-info">UMA is validating connection readiness step by step. No credentials or query results are displayed here.</div>
          <AnimatedConnectionTest
            connection={activeTest}
            running
            checks={connectionTestChecklist(activeTest, null, true)}
          />
        </Modal>
      )}

      {mfaTest && (
        <Modal title={`Snowflake Test — ${mfaTest.name}`} onClose={()=>{ setMfaTest(null); setMfaCode(""); }} width={460}>
          <div className="fg">
            <label className="fl">Authentication Method</label>
            <select className="fi" value={mfaAuthMethod} onChange={e=>{ setMfaAuthMethod(e.target.value); setMfaCode(""); }}>
              <option value="password">Password</option>
              <option value="password_mfa">Password + MFA</option>
              <option value="key_pair" disabled>Key Pair (coming soon)</option>
            </select>
          </div>
          {mfaAuthMethod === "password_mfa" && (
          <div className="fg">
            <label className="fl">MFA / TOTP Passcode</label>
            <input
              className="fi"
              type="password"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="Current 6-digit MFA code"
              value={mfaCode}
              onChange={e=>setMfaCode(e.target.value)}
              autoFocus
            />
            <div className="fhint">Used only for this test run. UMA does not save this code.</div>
          </div>
          )}
          <div style={{ display:"flex", justifyContent:"flex-end", gap:8, marginTop:16 }}>
            <button className="btn btn-ghost" onClick={()=>{ setMfaTest(null); setMfaCode(""); }}>Cancel</button>
            <button className="btn btn-primary" onClick={submitMfaTest} disabled={(mfaAuthMethod === "password_mfa" && !mfaCode.trim()) || testing[mfaTest.id]}>
              {testing[mfaTest.id] ? <Spinner/> : "Run Test"}
            </button>
          </div>
        </Modal>
      )}

      {showNew && <NewConnectionModal defaults={showNew === true ? null : showNew} onClose={()=>{ setNew(false); refetch(); }} />}
      {editing && <NewConnectionModal editing={editing} onClose={()=>{ setEditing(null); refetch(); }} />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// SNOWFLAKE DIAGNOSTIC PANEL
// Runs 7-step diagnostic: format → DNS → TCP → TLS → auth → role → warehouse.
// Shows per-step status with expandable detail. Downloadable JSON report for network teams.
// ══════════════════════════════════════════════════════════════
function SnowflakeDiagnosticPanel({ account, user, password, privateKey, privateKeyPassphrase, role, warehouse, authMethod, mfaPasscode }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [expanded, setExpanded] = useState({});

  const STEPS = [
    { id: "1_account_format",   label: "Account Identifier Format" },
    { id: "2_dns_resolution",    label: "DNS Resolution" },
    { id: "3_tcp_connectivity",  label: "TCP Port 443 Reachable" },
    { id: "4_tls_handshake",     label: "TLS Handshake" },
    { id: "5_authentication",    label: "Authentication" },
    { id: "6_role_access",       label: "Role Access" },
    { id: "7_warehouse_access",  label: "Warehouse Usage" },
  ];

  const run = async () => {
    if (!account) { setResult({ ok: false, error: "Enter account identifier first" }); return; }
    setRunning(true); setResult(null); setExpanded({});
    try {
      const body = { account, user, password, private_key: privateKey, private_key_passphrase: privateKeyPassphrase, role, warehouse, auth_method: authMethod };
      if (authMethod === "password_mfa") body.mfa_passcode = mfaPasscode;
      const r = await api.diagnoseSnowflake(body);
      setResult(r);
    } catch(e) {
      setResult({ ok: false, error: e.message });
    }
    setRunning(false);
  };

  const download = async () => {
    try {
      const body = { account, user, password, private_key: privateKey, private_key_passphrase: privateKeyPassphrase, role, warehouse, auth_method: authMethod };
      if (authMethod === "password_mfa") body.mfa_passcode = mfaPasscode;
      const token = (typeof window !== "undefined" ? window.localStorage.getItem("uma.accessToken") : "") || "";
      const base = typeof window !== "undefined"
        ? (window.location.hostname === "localhost" ? "http://localhost:8000" : "")
        : "";
      const resp = await fetch(base + "/api/snowflake/diagnose/download", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { "Authorization": `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      if (!resp.ok) { alert("Download failed: " + resp.status); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const acct = (account || "snowflake").replace(/[^a-zA-Z0-9_-]/g, "-");
      a.download = `uma-snowflake-diagnostic-${acct}-${Date.now()}.json`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch(e) {
      alert("Download failed: " + e.message);
    }
  };

  const statusColor = (s) => s === "ok" ? "var(--green)"
                           : s === "fail" ? "var(--red)"
                           : s === "warn" ? "var(--yellow)"
                           : s === "skip" ? "var(--text3)"
                           : "var(--text3)";
  const statusSym = (s) => s === "ok" ? "✓"
                          : s === "fail" ? "✗"
                          : s === "warn" ? "!"
                          : s === "skip" ? "—"
                          : "○";

  const byStep = {};
  (result?.checks || []).forEach(c => { byStep[c.step] = c; });

  return (
    <div style={{
      marginTop: 14,
      padding: 14,
      border: "1px solid var(--border)",
      borderRadius: "var(--r)",
      background: "var(--bg3)",
    }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 }}>
        <div>
          <div style={{ fontSize:12, fontWeight:700, color:"var(--text)" }}>Connection Diagnostics</div>
          <div style={{ fontSize:10, color:"var(--text3)", marginTop:2, fontFamily:"var(--font-m)" }}>
            Runs 7 checks: format → DNS → TCP → TLS → auth → role → warehouse
          </div>
        </div>
        <div style={{ display:"flex", gap:6 }}>
          {result && <button className="btn btn-ghost btn-sm" onClick={download}>⬇ Report</button>}
          <button className="btn btn-primary btn-sm" onClick={run} disabled={running || !account}>
            {running ? <Spinner/> : "Run Diagnostic"}
          </button>
        </div>
      </div>

      {running && (
        <div style={{ padding:20, textAlign:"center", color:"var(--text3)", fontSize:11 }}>
          Running checks… this may take 15–30 seconds
        </div>
      )}

      {result && result.summary && (
        <div style={{
          padding: "8px 10px", marginBottom: 10,
          fontSize: 11, borderRadius: "var(--r)",
          background: result.ok ? "rgba(0,229,160,.06)" : "rgba(255,69,96,.06)",
          border: `1px solid ${result.ok ? "rgba(0,229,160,.25)" : "rgba(255,69,96,.25)"}`,
          color: result.ok ? "var(--green)" : "var(--red)",
        }}>
          {result.ok ? "✓ " : "✗ "}{result.summary}
          {result.hostname && <span style={{ marginLeft:8, color:"var(--text3)", fontFamily:"var(--font-m)" }}>host: {result.hostname}</span>}
        </div>
      )}
      {result && result.error && !result.checks && (
        <div className="alert-err">✗ {result.error}</div>
      )}

      {result && (
        <div style={{ display:"flex", flexDirection:"column", gap:4 }}>
          {STEPS.map(step => {
            const c = byStep[step.id];
            const hasResult = !!c;
            const status = c?.status || "pending";
            const isExp = expanded[step.id];
            const hasDetail = c?.detail && Object.keys(c.detail || {}).length > 0;
            return (
              <div key={step.id} style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--r)",
                background: "var(--bg2)",
                opacity: hasResult ? 1 : 0.5,
              }}>
                <div
                  style={{ padding:"8px 12px", display:"flex", alignItems:"center", gap:10,
                           cursor: hasDetail ? "pointer" : "default" }}
                  onClick={()=>hasDetail && setExpanded(s=>({...s, [step.id]: !s[step.id]}))}
                >
                  <div style={{
                    width:22, height:22, borderRadius:"50%",
                    display:"flex", alignItems:"center", justifyContent:"center",
                    background: statusColor(status) + (status==="pending" ? "" : "22"),
                    color: statusColor(status),
                    fontSize:13, fontWeight:700,
                    border: `1px solid ${statusColor(status)}44`,
                    flexShrink:0,
                  }}>
                    {statusSym(status)}
                  </div>
                  <div style={{ flex:1, minWidth:0 }}>
                    <div style={{ fontSize:12, fontWeight:600, color:"var(--text)" }}>{step.label}</div>
                    {c?.message && (
                      <div style={{ fontSize:10, color:"var(--text3)", marginTop:2,
                                    fontFamily:"var(--font-m)", whiteSpace:"nowrap",
                                    overflow:"hidden", textOverflow:"ellipsis" }}>
                        {c.message}
                      </div>
                    )}
                  </div>
                  {c?.duration_ms != null && (
                    <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-m)" }}>{c.duration_ms}ms</span>
                  )}
                  {hasDetail && (
                    <span style={{ color:"var(--text3)", fontSize:10 }}>{isExp ? "▾" : "▸"}</span>
                  )}
                </div>
                {isExp && hasDetail && (
                  <div style={{
                    padding: "8px 12px 12px 44px",
                    fontSize: 10, fontFamily: "var(--font-m)",
                    borderTop: "1px solid var(--border)",
                    color: "var(--text2)",
                  }}>
                    {Object.entries(c.detail).map(([k, v]) => (
                      <div key={k} style={{ display:"flex", gap:8, padding:"2px 0" }}>
                        <span style={{ color:"var(--text3)", minWidth:110 }}>{k}:</span>
                        <span style={{
                          color: k === "hint" ? "var(--accent)" : "var(--text)",
                          fontStyle: k === "hint" ? "italic" : "normal",
                          wordBreak: "break-all",
                        }}>
                          {typeof v === "object" ? JSON.stringify(v) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!result && !running && (
        <div style={{ padding:16, textAlign:"center", color:"var(--text3)", fontSize:11 }}>
          Click <strong>Run Diagnostic</strong> to test connectivity step-by-step.<br/>
          Download the report to share with your network or Snowflake admin if something fails.
        </div>
      )}
    </div>
  );
}

function NewConnectionModal({ onClose, editing, defaults = null }) {
  const isEdit = !!editing;
  const [type, setType]   = useState(editing?.type || defaults?.type || "snowflake");
  const [form, setForm]   = useState({
    name: editing?.name || defaults?.name || "",
    connection_role: editing?.connection_role || defaults?.connection_role || ((editing?.type || defaults?.type) === "snowflake" ? "target" : "source"),
    description: editing?.description || defaults?.description || "",
  });
  const [creds, setCreds] = useState({});  // Only fields user actually edits
  const [cfg, setCfg]     = useState(editing?.config || {});
  const [authMethod, setAuthMethod] = useState(editing?.config?.auth_method || "password");
  const [mfaPasscode, setMfaPasscode] = useState("");
  const [saving, setSave] = useState(false);
  const [testing, setTest]= useState(false);
  // Single status object — never show both error+success
  const [status, setStatus] = useState(null);  // { kind: "ok"|"err"|"info", msg, detail? }

  const set = (f,v) => { setForm(p=>({...p,[f]:v})); setStatus(null); };
  const sc  = (f,v) => { setCreds(p=>({...p,[f]:v})); setStatus(null); };
  const sg  = (f,v) => { setCfg(p=>({...p,[f]:v})); setStatus(null); };
  const setSnowflakeAuthMethod = (v) => {
    setAuthMethod(v);
    setMfaPasscode("");
    setCfg(p => ({ ...p, auth_method: v }));
    setStatus(null);
  };

  // On type change, clear per-type state
  const onTypeChange = (newType) => {
    setType(newType);
    setForm(p => ({ ...p, connection_role: newType === "snowflake" ? "target" : "source" }));
    setCreds({});
    setCfg({});
    setAuthMethod("password");
    setMfaPasscode("");
    setStatus(null);
  };

  const buildPayload = () => ({
    name: form.name,
    type,
    connection_role: form.connection_role,
    description: form.description,
    credentials: creds,
    config: type === "snowflake" ? { ...cfg, auth_method: authMethod } : cfg,
  });

  const handleTest = async () => {
    if (!form.name) { setStatus({ kind:"err", msg:"Please enter a connection name first" }); return; }
    setTest(true); setStatus(null);
    try {
      const payload = buildPayload();
      if (type === "snowflake") {
        payload.auth_method = authMethod;
        if (authMethod === "password_mfa") payload.mfa_passcode = mfaPasscode;
      }
      const r = await api.testCredentials(payload);
      if (r.success) {
        const extras = [];
        if (r.account)        extras.push(`account: ${r.account}`);
        if (r.user)           extras.push(`user: ${r.user}`);
        if (r.warehouse)      extras.push(`warehouse: ${r.warehouse}`);
        if (r.role)           extras.push(`role: ${r.role}`);
        if (r.duration_ms)    extras.push(`${r.duration_ms}ms`);
        setStatus({
          kind: "ok",
          msg: "Connection successful",
          detail: extras.join(" · "),
        });
      } else {
        setStatus({
          kind: "err",
          msg: r.diagnostic || "Connection failed",
          detail: r.error || "",
        });
      }
    } catch (e) {
      setStatus({ kind:"err", msg: e.message });
    } finally {
      setTest(false);
    }
  };

  const handleSave = async () => {
    if (!form.name) { setStatus({ kind:"err", msg:"Please enter a connection name" }); return; }
    setSave(true); setStatus(null);
    try {
      if (isEdit) {
        // Only send credentials if user entered new ones
        const payload = { name: form.name, description: form.description, config: type === "snowflake" ? { ...cfg, auth_method: authMethod } : cfg };
        payload.connection_role = form.connection_role;
        if (type === "snowflake") payload.auth_method = authMethod;
        if (Object.keys(creds).length > 0) payload.credentials = creds;
        await api.updateConnection(editing.id, payload);
      } else {
        await api.createConnection(buildPayload());
      }
      onClose();
    } catch(e) {
      setStatus({ kind:"err", msg: e.message });
      setSave(false);
    }
  };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal modal-lg" onClick={e=>e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">{isEdit ? "Edit Connection" : "New Connection"}</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {status && (
            <div className={status.kind === "ok" ? "alert-ok" : status.kind === "info" ? "alert-info" : "alert-err"}>
              <div style={{ fontWeight: 600 }}>
                {status.kind === "ok" ? "✓ " : status.kind === "info" ? "ℹ " : "✗ "}
                {status.msg}
              </div>
              {status.detail && (
                <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4, fontFamily: "var(--font-m)" }}>
                  {status.detail}
                </div>
              )}
            </div>
          )}
          <div className="fr">
            <div className="fg">
              <label className="fl">Connection Name</label>
              <input className="fi" placeholder="e.g. Snowflake Prod" value={form.name} onChange={e=>set("name",e.target.value)} />
            </div>
            <div className="fg">
              <label className="fl">Type</label>
              <select className="fi" value={type} disabled={isEdit} onChange={e=>onTypeChange(e.target.value)}>
                {SRC.map(s=><option key={s.id} value={s.id}>{s.icon} {s.name}</option>)}
              </select>
            </div>
          </div>
          <div className="fg">
            <label className="fl">Description</label>
            <input className="fi" placeholder="Optional" value={form.description} onChange={e=>set("description",e.target.value)} />
          </div>
          <div className="fg">
            <label className="fl">Connection Role</label>
            <select className="fi" value={form.connection_role} onChange={e=>set("connection_role", e.target.value)}>
              <option value="source">Source</option>
              <option value="target">Target</option>
              <option value="both">Both</option>
            </select>
            <div className="fhint">Use Source for systems you extract from, Target for destinations like Snowflake, or Both for dual-use stores.</div>
          </div>
          {isEdit && (
            <div className="alert-info" style={{ margin: "10px 0" }}>
              <div style={{ fontSize: 11 }}>Leave credential fields blank to keep existing values. Fill them in to replace.</div>
            </div>
          )}
          <div className="divider" />

          {/* Dynamic credential fields */}
          {type==="snowflake" && <>
            <div className="fg">
              <label className="fl">Authentication Method</label>
              <select className="fi" value={authMethod} onChange={e=>setSnowflakeAuthMethod(e.target.value)}>
                <option value="password">Password</option>
                <option value="password_mfa">Password + MFA</option>
                <option value="key_pair">Key Pair / Private Key</option>
              </select>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Account Identifier</label><input className="fi" placeholder="orgname-accountname" value={cfg.account||""} onChange={e=>sg("account",e.target.value)} /><div className="fhint">Format: <code>orgname-accountname</code>, or <code>locator.region</code>. Not the full URL.</div></div>
              <div className="fg"><label className="fl">Warehouse</label><input className="fi" placeholder="COMPUTE_WH" value={cfg.warehouse||""} onChange={e=>sg("warehouse",e.target.value)} /></div>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Username</label><input className="fi" value={creds.user||""} onChange={e=>sc("user",e.target.value)} /></div>
              {authMethod !== "key_pair" ? <div className="fg"><label className="fl">Password</label><input className="fi" type="password" placeholder={isEdit ? "(unchanged)" : ""} value={creds.password||""} onChange={e=>sc("password",e.target.value)} /></div> : null}
            </div>
            {authMethod === "key_pair" && (
              <>
                <div className="fg">
                  <label className="fl">Private Key PEM</label>
                  <textarea className="fi" rows={7} placeholder={isEdit ? "(unchanged)" : "-----BEGIN PRIVATE KEY-----"} value={creds.private_key||""} onChange={e=>sc("private_key",e.target.value)} />
                  <div className="fhint">Paste the Snowflake user private key. UMA stores it encrypted and sends it only to Snowflake for key-pair authentication.</div>
                </div>
                <div className="fg">
                  <label className="fl">Private Key Passphrase</label>
                  <input className="fi" type="password" placeholder={isEdit ? "(unchanged if blank)" : "Optional"} value={creds.private_key_passphrase||""} onChange={e=>sc("private_key_passphrase",e.target.value)} />
                </div>
              </>
            )}
            {authMethod==="password_mfa" && (
              <div className="fg">
                <label className="fl">MFA / TOTP Passcode</label>
                <input className="fi" type="password" inputMode="numeric" autoComplete="one-time-code" placeholder="Current 6-digit MFA code" value={mfaPasscode} onChange={e=>{ setMfaPasscode(e.target.value); setStatus(null); }} />
                <div className="fhint">Used only for this test or diagnostic run. UMA does not save this code.</div>
              </div>
            )}
            <div className="fr">
              <div className="fg"><label className="fl">Database</label><input className="fi" placeholder="ANALYTICS_DB" value={cfg.database||""} onChange={e=>sg("database",e.target.value)} /></div>
              <div className="fg"><label className="fl">Role</label><input className="fi" placeholder="SYSADMIN" value={cfg.role||""} onChange={e=>sg("role",e.target.value)} /></div>
            </div>

            {/* Diagnostic panel */}
            <SnowflakeDiagnosticPanel
              account={cfg.account}
              user={creds.user}
              password={creds.password}
              privateKey={creds.private_key}
              privateKeyPassphrase={creds.private_key_passphrase}
              role={cfg.role}
              warehouse={cfg.warehouse}
              authMethod={authMethod}
              mfaPasscode={mfaPasscode}
            />
          </>}

          {type==="bigquery" && <>
            <div className="fg"><label className="fl">Service Account JSON</label><textarea className="fi" rows={5} placeholder="Paste full JSON key content…" value={creds.service_account_json||""} onChange={e=>sc("service_account_json",e.target.value)} /></div>
            <div className="fg"><label className="fl">Project ID (optional)</label><input className="fi" placeholder="Inferred from key if blank" value={cfg.project_id||""} onChange={e=>sg("project_id",e.target.value)} /></div>
          </>}

          {(type==="redshift"||type==="postgres"||type==="sqlserver"||type==="mysql"||type==="oracle"||type==="teradata"||type==="synapse") && <>
            <div className="fr">
              <div className="fg"><label className="fl">Host</label><input className="fi" value={cfg.host||""} onChange={e=>sg("host",e.target.value)} /></div>
              <div className="fg"><label className="fl">Port</label><input className="fi" placeholder={type==="redshift"?"5439":type==="sqlserver"?"1433":type==="mysql"?"3306":type==="oracle"?"1521":"5432"} value={cfg.port||""} onChange={e=>sg("port",e.target.value)} /></div>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Database</label><input className="fi" value={cfg.database||""} onChange={e=>sg("database",e.target.value)} /></div>
              <div className="fg"><label className="fl">Username</label><input className="fi" value={creds.user||""} onChange={e=>sc("user",e.target.value)} /></div>
            </div>
            <div className="fg"><label className="fl">Password</label><input className="fi" type="password" placeholder={isEdit ? "(unchanged)" : ""} value={creds.password||""} onChange={e=>sc("password",e.target.value)} /></div>
          </>}

          {type==="salesforce" && <>
            <div className="fg"><label className="fl">Instance URL</label><input className="fi" placeholder="https://mycompany.salesforce.com" value={cfg.instance_url||""} onChange={e=>sg("instance_url",e.target.value)} /></div>
            <div className="fr">
              <div className="fg"><label className="fl">Client ID</label><input className="fi" value={creds.client_id||""} onChange={e=>sc("client_id",e.target.value)} /></div>
              <div className="fg"><label className="fl">Client Secret</label><input className="fi" type="password" value={creds.client_secret||""} onChange={e=>sc("client_secret",e.target.value)} /></div>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Username</label><input className="fi" value={creds.username||""} onChange={e=>sc("username",e.target.value)} /></div>
              <div className="fg"><label className="fl">Password + Security Token</label><input className="fi" type="password" value={creds.password||""} onChange={e=>sc("password",e.target.value)} /></div>
            </div>
          </>}

          {(type==="s3") && <>
            <div className="fr">
              <div className="fg"><label className="fl">Bucket</label><input className="fi" value={cfg.bucket||""} onChange={e=>sg("bucket",e.target.value)} /></div>
              <div className="fg"><label className="fl">Region</label><input className="fi" placeholder="us-east-1" value={cfg.region||""} onChange={e=>sg("region",e.target.value)} /></div>
            </div>
            <div className="fg"><label className="fl">Prefix (optional)</label><input className="fi" placeholder="data/warehouse/" value={cfg.prefix||""} onChange={e=>sg("prefix",e.target.value)} /></div>
            <div className="fr">
              <div className="fg"><label className="fl">Access Key ID</label><input className="fi" value={creds.aws_access_key_id||""} onChange={e=>sc("aws_access_key_id",e.target.value)} /></div>
              <div className="fg"><label className="fl">Secret Access Key</label><input className="fi" type="password" value={creds.aws_secret_access_key||""} onChange={e=>sc("aws_secret_access_key",e.target.value)} /></div>
            </div>
            <div className="fg"><label className="fl">IAM Role ARN (for COPY INTO)</label><input className="fi" placeholder="arn:aws:iam::123:role/snowflake-role" value={creds.iam_role||""} onChange={e=>sc("iam_role",e.target.value)} /><div className="fhint">Used in Snowflake COPY INTO statement</div></div>
          </>}

          {(type==="azureblob"||type==="adls") && <>
            <div className="fr">
              <div className="fg"><label className="fl">Storage Account</label><input className="fi" value={cfg.account_name||""} onChange={e=>sg("account_name",e.target.value)} /></div>
              <div className="fg"><label className="fl">Container</label><input className="fi" value={cfg.container_name||""} onChange={e=>sg("container_name",e.target.value)} /></div>
            </div>
            <div className="fg"><label className="fl">Account Key</label><input className="fi" type="password" placeholder={isEdit ? "(unchanged)" : ""} value={creds.account_key||""} onChange={e=>sc("account_key",e.target.value)} /></div>
            <div className="fg"><label className="fl">Prefix (optional)</label><input className="fi" placeholder="data/" value={cfg.prefix||""} onChange={e=>sg("prefix",e.target.value)} /></div>
          </>}

          {type==="flatfile" && <>
            <div className="fg"><label className="fl">File Upload</label><input className="fi" type="text" placeholder="Upload via API endpoint /api/files/upload" /><div className="fhint">Supports: CSV, Parquet, JSON, JSONL, Avro, Excel (.xlsx)</div></div>
          </>}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-ghost" onClick={handleTest} disabled={testing}>{testing?<Spinner/>:"Test Connection"}</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>{saving?<Spinner/>: isEdit ? "Save Changes" : "Create Connection"}</button>
        </div>
      </div>
    </div>
  );
}

// ─── Tables ───────────────────────────────────────────────────
function TablesPage() {
  const [search, setS]  = useState("");
  const [datasetF, setD]= useState("");
  const [statusF, setSF]= useState("");
  const [sort, setSort] = useState("schema");
  const { data: tables, loading, error, refetch } = useApi(
    () => api.getCatalogTables({ search, schema:datasetF, status:statusF, sort, page_size:100 }).then(r=>r.items || []), [search, datasetF, statusF, sort]
  );
  const { data: stats } = useApi(() => api.getCatalogSummary(), []);

  const filtered = tables || [];
  const datasets = [...new Set((tables||[]).map(t=>t.schema).filter(Boolean))];
  const totalTables = stats?.total_tables ?? 0;
  const failedCount = stats?.failed ?? 0;
  const runningCount = stats?.running ?? 0;
  const successCount = stats?.succeeded ?? 0;

  return (
    <div className="page">
      <div className="tables-stage">
        <div className="page-header">
          <div className="page-header-copy">
            <div className="page-eyebrow">Data Explorer</div>
            <div className="page-title">Tables Command Center</div>
            <div className="page-subtitle">
              Review table-level migration outcomes, isolate problem datasets quickly,
              and keep schema quality visible without digging through job logs first.
            </div>
          </div>
          <div className="page-actions">
            <span className="tables-note">Live catalog view</span>
            <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
          </div>
        </div>

        <div className="tables-hero">
          <div className="tables-hero-grid">
            <div style={{ display:"flex", flexDirection:"column", justifyContent:"space-between", gap:18 }}>
              <div>
                <div className="tables-chip" style={{ marginBottom:14 }}>
                  <span className="sdot" style={{ marginRight:0 }} />
                  Operator-ready inventory
                </div>
                <div style={{ fontSize:24, lineHeight:1.15, fontWeight:800, fontFamily:"var(--font-h)", color:"var(--text)" }}>
                  One place to inspect dataset health, table readiness, and migration surface area.
                </div>
                <div style={{ marginTop:12, fontSize:13, lineHeight:1.7, color:"var(--text3)", maxWidth:620 }}>
                  This view is backed by UMA catalog records from configured jobs and replication sources:
                  crisp status totals, fast filtering, and a table list that stays readable at scale.
                </div>
              </div>
              <div style={{ display:"flex", gap:10, flexWrap:"wrap" }}>
                <span className="tables-chip">{datasets.length} datasets in scope</span>
                <span className="tables-chip">{filtered.length} rows visible</span>
                {failedCount > 0 && <span className="tables-chip text-danger">{failedCount} need attention</span>}
              </div>
            </div>
            <div className="tables-kpis">
              {[
                ["Total Tables", totalTables, "All mapped table assets", "var(--accent)", ""],
                ["Succeeded", successCount, "Stable and query-ready", "var(--green)", "SUCCEEDED"],
                ["Running", runningCount, "Actively moving data", "var(--orange)", "RUNNING"],
                ["Failed", failedCount, "Blocked or needs review", "var(--red)", "FAILED"],
              ].map(([label, value, note, color, nextStatus]) => (
                <button key={label} type="button" className={`tables-kpi is-clickable ${statusF === nextStatus ? "active" : ""}`} onClick={() => setSF(nextStatus)}>
                  <div className="tables-kpi-label">{label}</div>
                  <div className="tables-kpi-value" style={{ color }}>{value}</div>
                  <div className="tables-kpi-note">{note}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="tables-surface">
          <div className="tables-toolbar">
            <div className="sw">
              <span className="si">🔍</span>
              <input placeholder="Search tables, datasets, or targets…" value={search} onChange={e=>setS(e.target.value)} />
            </div>
            <select value={datasetF} onChange={e=>setD(e.target.value)}>
              <option value="">All Schemas</option>
              {datasets.map(d=><option key={d} value={d}>{d}</option>)}
            </select>
            <select value={statusF} onChange={e=>setSF(e.target.value)}>
              <option value="">All Statuses</option>
              <option value="SUCCEEDED">Succeeded</option>
              <option value="RUNNING">Running</option>
              <option value="FAILED">Failed</option>
              <option value="PENDING">Pending</option>
            </select>
            <select value={sort} onChange={e=>setSort(e.target.value)}>
              <option value="schema">Schema</option>
              <option value="table">Table</option>
              <option value="-last_sync_time">Last Sync</option>
              <option value="-estimated_bytes">Estimated Size</option>
            </select>
          </div>
          {error && <ErrMsg msg={error} />}
          {loading ? <Loading /> : !filtered.length ? (
            <div className="empty tables-empty"><div className="empty-icon">🗂</div><div className="empty-msg">No tables yet. Run a migration job to populate this view.</div></div>
          ) : (
            <div className="tables-table">
              <table>
                <thead><tr><th>Schema</th><th>Target</th><th>Table</th><th>Columns</th><th>Rows</th><th>Size</th><th>Status</th><th>Latest Error</th></tr></thead>
                <tbody>
                  {filtered.map((t,i)=>(
                    <tr key={i}>
                      <td className="td-mono">{t.schema}</td>
                      <td className="td-mono">{t.target_schema}.{t.target_table}</td>
                      <td className="td-main">{t.table}</td>
                      <td className="td-mono">{t.column_count || 0}</td>
                      <td className="td-mono">{(t.estimated_rows||0).toLocaleString()}</td>
                      <td className="td-mono">{((t.estimated_bytes||0)/1e6).toFixed(1)} MB</td>
                      <td><StatusBadge status={t.latest_migration_status || t.latest_replication_status || "UNKNOWN"} /></td>
                      <td className={t.latest_error ? "run-error" : "text-muted"}>{t.latest_error || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Validation ───────────────────────────────────────────────
function ValidationPage() {
  const { data: rules, loading, error, refetch } = useApi(() => api.getValidationRules(), []);
  const [showNew, setNew]   = useState(false);
  const [showRecon, setRecon] = useState(false);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [running, setRun]   = useState({});
  const [deleting, setDel]  = useState({});

  const handleRun = async (id) => {
    setRun(r=>({...r,[id]:true}));
    try { await api.runValidationRule(id); setTimeout(refetch, 800); }
    catch(e) { alert(e.message); }
    setRun(r=>({...r,[id]:false}));
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this rule?")) return;
    setDel(d=>({...d,[id]:true}));
    try { await api.deleteValidationRule(id); refetch(); }
    catch(e) { alert(e.message); }
    setDel(d=>({...d,[id]:false}));
  };

  const passed  = (rules||[]).filter(r=>r.status==="SUCCEEDED").length;
  const failed  = (rules||[]).filter(r=>r.status==="FAILED").length;
  const running2= (rules||[]).filter(r=>r.status==="RUNNING").length;
  const visibleRules = statusFilter === "ALL" ? (rules || []) : (rules || []).filter(r => r.status === statusFilter);

  return (
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>Validation Plans</div>
          <div className="text-muted mt2">Source ↔ target reconciliation · Row count · Checksum · Schema · Null/duplicate · Freshness</div>
        </div>
        <div style={{ display:"flex", gap:8 }}>
          <button className="btn btn-ghost" onClick={()=>setRecon(true)}>↻ Reconcile Job</button>
          <button className="btn btn-primary" onClick={()=>setNew(true)}>+ Add Check</button>
        </div>
      </div>

      <div className="stats-grid mb4">
        {[
          ["Passed", passed, "var(--green)", "SUCCEEDED"],
          ["Failed", failed, "var(--red)", "FAILED"],
          ["Running", running2, "var(--yellow)", "RUNNING"],
          ["Total", (rules || []).length, "var(--accent)", "ALL"],
        ].map(([l,v,c,nextFilter])=>(
          <button className={`stat-card is-clickable ${statusFilter === nextFilter ? "active" : ""}`} type="button" key={l} style={{ "--al":c }} onClick={() => setStatusFilter(nextFilter)}>
            <div className="stat-label">{l}</div>
            <div className="stat-value" style={{ fontSize:22,color:c }}>{loading?"…":v}</div>
          </button>
        ))}
      </div>

      <div className="card">
        {error && <ErrMsg msg={error} />}
        {loading ? <Loading /> : !rules?.length ? (
          <div className="empty"><div className="empty-icon">✓</div><div className="empty-msg">No validation rules yet. Use “Reconcile Job” to auto-create row-count checks for every table in a job.</div></div>
        ) : (
          <div className="table-scroll validation-table">
            <table>
              <thead><tr><th>Name</th><th>Table</th><th>Type</th><th>Source</th><th>Target</th><th>Delta</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead>
              <tbody>
                {visibleRules.map(r=>(
                  <tr key={r.id}>
                    <td className="td-mono" style={{ fontSize:11 }}>{r.name}</td>
                    <td className="td-mono" style={{ fontSize:11 }}>{r.target_table}</td>
                    <td><span className="badge bb" style={{ fontSize:9 }}>{r.rule_type}</span></td>
                    <td className="td-mono">{r.source_value||"—"}</td>
                    <td className="td-mono">{r.target_value||"—"}</td>
                    <td className="td-mono" style={{ color:r.status==="FAILED"?"var(--red)":"var(--text3)" }}>{r.delta||"—"}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="td-mono" style={{ fontSize:10 }}>{r.last_run?new Date(r.last_run).toLocaleString():"Never"}</td>
                    <td style={{ display:"flex", gap:4 }}>
                      <button className="btn btn-ghost btn-xs" onClick={()=>handleRun(r.id)} disabled={running[r.id]}>
                        {running[r.id]?<Spinner/>:"▶ Run"}
                      </button>
                      <button className="btn btn-ghost btn-xs" onClick={()=>handleDelete(r.id)} disabled={deleting[r.id]} style={{ color:"var(--red)" }}>
                        {deleting[r.id]?<Spinner/>:"✕"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visibleRules.length ? <div className="empty"><div className="empty-msg">No validation rules match the selected KPI filter.</div></div> : null}
          </div>
        )}
      </div>

      {showNew && <NewValidationModal onClose={()=>{ setNew(false); refetch(); }} />}
      {showRecon && <ReconcileJobModal onClose={()=>{ setRecon(false); refetch(); }} />}
    </div>
  );
}

function ReconcileJobModal({ onClose }) {
  const { data: jobs } = useApi(() => api.getJobs({ limit: 100 }), []);
  const [jobId, setJobId] = useState("");
  const [types, setTypes] = useState(["row_count"]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError]   = useState("");

  const toggleType = (t) => setTypes(ts => ts.includes(t) ? ts.filter(x=>x!==t) : [...ts, t]);

  const run = async () => {
    if (!jobId) { setError("Pick a job"); return; }
    if (!types.length) { setError("Pick at least one rule type"); return; }
    setRunning(true); setError(""); setResult(null);
    try {
      const r = await api.reconcileJob({ job_id: jobId, rule_types: types });
      setResult(r);
    } catch(e) { setError(e.message); }
    setRunning(false);
  };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{ maxWidth:780 }}>
        <div className="modal-hdr">
          <div className="modal-title">Reconcile Job</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="text-muted mb3" style={{ fontSize:11 }}>
            Auto-creates one rule per table in the job, runs them in parallel, and reports source-vs-target reconciliation.
            Checksum requires <code>primary_key_columns</code> on the task config.
          </div>
          <div className="fg">
            <label className="fl">Job</label>
            <select className="fi" value={jobId} onChange={e=>setJobId(e.target.value)}>
              <option value="">— Select a job —</option>
              {(jobs||[]).map(j=>(
                <option key={j.id} value={j.id}>{j.name} ({j.task_count} tasks · {j.load_strategy})</option>
              ))}
            </select>
          </div>
          <div className="fg">
            <label className="fl">Rule Types</label>
            <div style={{ display:"flex", gap:14 }}>
              <label style={{ display:"flex", alignItems:"center", gap:5, fontSize:12 }}>
                <input type="checkbox" checked={types.includes("row_count")} onChange={()=>toggleType("row_count")} />
                Row count
              </label>
              <label style={{ display:"flex", alignItems:"center", gap:5, fontSize:12 }}>
                <input type="checkbox" checked={types.includes("checksum")} onChange={()=>toggleType("checksum")} />
                Checksum (PK-bagged hash)
              </label>
            </div>
          </div>
          {error && <ErrMsg msg={error} />}
          {result && (
            <div style={{ background:"var(--bg3)", border:"1px solid var(--border)", borderRadius:6, padding:12, marginTop:12 }}>
              <div style={{ fontSize:12, fontWeight:700, marginBottom:6 }}>
                Created {result.rules_created} rule(s)
              </div>
              {Object.entries(result.summary_by_type||{}).map(([t,b])=>(
                <div key={t} style={{ fontSize:11, fontFamily:"var(--font-m)" }}>
                  {t}: <span style={{ color:"var(--green)" }}>{b.passed} passed</span>
                  {b.failed > 0 && <> · <span style={{ color:"var(--red)" }}>{b.failed} failed</span></>}
                </div>
              ))}
              <div style={{ marginTop:8, maxHeight:240, overflow:"auto" }}>
                {(result.rules||[]).map(r=>(
                  <div key={r.id} style={{ display:"grid", gridTemplateColumns:"1.5fr 1fr 1fr 1fr 0.6fr", gap:6, fontSize:10, padding:"3px 0", borderBottom:"1px solid var(--border)" }}>
                    <span className="td-mono">{r.target_table}</span>
                    <span className="td-mono">{r.rule_type}</span>
                    <span className="td-mono">src: {r.source_value||"—"}</span>
                    <span className="td-mono">tgt: {r.target_value||"—"}</span>
                    <span><StatusBadge status={r.status} /></span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          <button className="btn btn-primary" onClick={run} disabled={running || !jobId}>
            {running ? <><Spinner/> Reconciling…</> : "Run Reconciliation"}
          </button>
        </div>
      </div>
    </div>
  );
}

function NewValidationModal({ onClose }) {
  const [form, setForm] = useState({
    name:"", rule_type:"row_count", target_table:"",
    source_connection_id:"", source_dataset:"", source_table:"",
    primary_key_columns:"",
    source_query:"", target_query:"", threshold_pct:0,
  });
  const [saving, setSave] = useState(false);
  const [error, setError] = useState("");
  const { data: conns } = useApi(() => api.getConnections(), []);
  const set = (f,v) => setForm(p=>({...p,[f]:v}));
  const sourceConns = (conns||[]).filter(c=>c.type !== "snowflake");

  const submit = async () => {
    setSave(true); setError("");
    try {
      const payload = {
        ...form,
        primary_key_columns: form.primary_key_columns
          ? form.primary_key_columns.split(",").map(s=>s.trim()).filter(Boolean)
          : [],
      };
      // Strip empty optional fields so backend doesn't mistake "" for a real value.
      ["source_connection_id","source_dataset","source_table","source_query","target_query"].forEach(k=>{
        if (!payload[k]) delete payload[k];
      });
      await api.createValidationRule(payload);
      onClose();
    } catch(e) { setError(e.message); }
    setSave(false);
  };

  const showSourceFields = ["row_count","checksum"].includes(form.rule_type);
  const showPK = ["checksum","duplicate"].includes(form.rule_type);

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{ maxWidth:680 }}>
        <div className="modal-hdr"><div className="modal-title">New Validation Rule</div><button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button></div>
        <div className="modal-body">
          <div className="fr">
            <div className="fg"><label className="fl">Rule Name</label><input className="fi" value={form.name} onChange={e=>set("name",e.target.value)} /></div>
            <div className="fg"><label className="fl">Type</label>
              <select className="fi" value={form.rule_type} onChange={e=>set("rule_type",e.target.value)}>
                <option value="row_count">Row Count Parity</option>
                <option value="checksum">Checksum (PK-bagged hash)</option>
                <option value="schema">Schema Parity</option>
                <option value="null">Null Check</option>
                <option value="duplicate">Duplicate Key</option>
                <option value="freshness">Freshness SLA</option>
              </select>
            </div>
          </div>
          <div className="fg">
            <label className="fl">Target Table (Snowflake DB.SCHEMA.TABLE)</label>
            <input className="fi" placeholder="DATABASE.SCHEMA.TABLE" value={form.target_table} onChange={e=>set("target_table",e.target.value)} />
          </div>

          {showSourceFields && (
            <>
              <div className="text-muted mb2" style={{ fontSize:11, marginTop:6 }}>Source side (optional for row_count, required for checksum)</div>
              <div className="fr">
                <div className="fg">
                  <label className="fl">Source Connection</label>
                  <select className="fi" value={form.source_connection_id} onChange={e=>set("source_connection_id",e.target.value)}>
                    <option value="">— None —</option>
                    {sourceConns.map(c=>(
                      <option key={c.id} value={c.id}>{c.name} ({c.type})</option>
                    ))}
                  </select>
                </div>
                <div className="fg">
                  <label className="fl">Source Dataset / Schema</label>
                  <input className="fi" placeholder="raw" value={form.source_dataset} onChange={e=>set("source_dataset",e.target.value)} />
                </div>
                <div className="fg">
                  <label className="fl">Source Table</label>
                  <input className="fi" placeholder="customers" value={form.source_table} onChange={e=>set("source_table",e.target.value)} />
                </div>
              </div>
            </>
          )}

          {showPK && (
            <div className="fg">
              <label className="fl">Primary Key Columns (comma-separated)</label>
              <input className="fi" placeholder="id, tenant_id" value={form.primary_key_columns} onChange={e=>set("primary_key_columns",e.target.value)} />
            </div>
          )}

          {form.rule_type !== "checksum" && (
            <>
              <div className="fg"><label className="fl">Source Query (overrides connection-derived count)</label><textarea className="fi" rows={2} placeholder="SELECT COUNT(*) FROM source_table" value={form.source_query} onChange={e=>set("source_query",e.target.value)} /></div>
              <div className="fg"><label className="fl">Target Query (override)</label><textarea className="fi" rows={2} placeholder="SELECT COUNT(*) FROM snowflake_table" value={form.target_query} onChange={e=>set("target_query",e.target.value)} /></div>
            </>
          )}

          <div className="fg"><label className="fl">Threshold % (allowed delta)</label><input className="fi" type="number" value={form.threshold_pct} onChange={e=>set("threshold_pct",parseFloat(e.target.value)||0)} /></div>
          {error && <ErrMsg msg={error} />}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={saving} onClick={submit}>{saving?<Spinner/>:"Create Rule"}</button>
        </div>
      </div>
    </div>
  );
}

// ─── AI Copilot ───────────────────────────────────────────────
function AIPage() {
  const { data: copilotProviders } = useApi(() => api.getCopilotProviders().catch(()=>null), []);
  const [messages, setMessages] = useState([
    { role:"assistant", content:"UMA Copilot is available in grounded assistant mode. If no provider is configured, responses are limited to deterministic UMA state and AI patching remains disabled." }
  ]);
  const [query, setQuery]   = useState("");
  const [loading, setLoad]  = useState(false);
  const [agentState, setAgentState] = useState(null);
  const [provider, setProvider] = useState("auto");
  const [preview, setPreview] = useState(null);
  const [actionBusy, setActionBusy] = useState("");
  const endRef = useRef(null);
  const snowflakeServices = copilotProviders?.snowflake_services || {};
  const cortexServices = snowflakeServices?.cortex || {};
  const serviceRows = [
    ["Connection", snowflakeServices?.snowflake_connection?.status || "unknown"],
    ["Cortex LLM", cortexServices?.llm?.status || "unknown"],
    ["Analyst", cortexServices?.analyst?.status || "unknown"],
    ["Search", cortexServices?.search?.status || "unknown"],
    ["Document Search", cortexServices?.document_search?.status || "unknown"],
    ["Snowpark", snowflakeServices?.snowpark?.status || "unknown"],
    ["Query History", snowflakeServices?.intelligence?.query_history || "unknown"],
    ["Cost Intelligence", snowflakeServices?.intelligence?.cost_intelligence || "unknown"],
  ];

  const suggestions = [
    "Get migration project status",
    "Summarize the latest failed run",
    "Explain validation mismatch patterns",
    "Explain a Snowflake cost spike",
    "Search migration logs for validation errors",
    "Show Snowflake service health",
    "Search Cortex documents for validation runbooks",
    "Preview retry failed step",
  ];

  useEffect(() => {
    if (copilotProviders?.selected_provider) setProvider(copilotProviders.selected_provider);
  }, [copilotProviders?.selected_provider]);

  const formatCopilotReply = (res) => {
    const ctx = res.source_context || {};
    const action = res.proposed_action;
    return [
      res.answer || "No answer returned.",
      "",
      "Source context:",
      `- run_id: ${ctx.run_id || "none"}`,
      `- validation_id: ${ctx.validation_id || "none"}`,
      `- cost_estimate_id: ${ctx.cost_estimate_id || "none"}`,
      `- report_id: ${ctx.report_id || "none"}`,
      "",
      action ? `Proposed action: ${action.action_type} (${action.category})` : "Proposed action: none",
      `Provider: ${res.provider}`,
    ].join("\n");
  };

  const send = async (text) => {
    const msg = text || query;
    if (!msg.trim() || loading) return;
    setQuery("");
    const newMessages = [...messages, { role:"user", content:msg }];
    setMessages(newMessages);
    setLoad(true);
    setPreview(null);
    try {
      const res = await api.askCopilot({ provider, message: msg, context: { surface:"ai_copilot" } });
      setAgentState(res);
      setMessages(prev=>[...prev, { role:"assistant", content:formatCopilotReply(res) }]);
      if (res.proposed_action?.action_type) {
        const p = await api.previewCopilotAction({
          provider,
          action_type: res.proposed_action.action_type,
          payload: { surface:"ai_copilot" },
        });
        setPreview(p);
      }
    } catch(e) {
      setMessages(prev=>[...prev, { role:"assistant", content:`Error: ${e.message}` }]);
    }
    setLoad(false);
  };

  const executePreview = async () => {
    if (!preview || preview.category === "BLOCKED") return;
    setActionBusy("execute");
    try {
      const res = await api.executeCopilotAction({
        action_type: preview.action_type,
        payload: preview.payload || {},
        confirmed: preview.requires_confirmation,
      });
      setMessages(prev=>[...prev, { role:"assistant", content:`Action result: ${res.status}\n${res.message || ""}` }]);
      setPreview(null);
    } catch(e) {
      setMessages(prev=>[...prev, { role:"assistant", content:`Action failed: ${e.message}` }]);
    } finally {
      setActionBusy("");
    }
  };

  useEffect(() => { endRef.current?.scrollIntoView({ behavior:"smooth" }); }, [messages, loading]);

  return (
    <div className="agent-surface" style={{ display:"flex", flexDirection:"column", minHeight:"calc(100vh - 64px)", background:"var(--bg)", color:"var(--text)" }}>
      <div style={{ padding:"18px 24px 0", borderBottom:"1px solid var(--border)", background:"var(--bg2)" }}>
        <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:3 }}>
          <span style={{ fontSize:18 }}>✦</span>
          <span style={{ fontSize:15, fontWeight:800 }}>UMA Copilot</span>
          <span className="badge bp" style={{ fontSize:9 }}>OPTIONAL ADAPTERS</span>
          <span className="badge bgr" style={{ fontSize:9 }}>UMA APPROVAL GATED</span>
        </div>
        <div style={{ display:"flex", gap:10, alignItems:"center", paddingBottom:14, flexWrap:"wrap" }}>
          <div style={{ fontSize:11, color:"var(--text3)" }}>Grounded answers over UMA runs, validation, cost, logs, and reports. Providers never own migration execution.</div>
          <select value={provider} onChange={e=>setProvider(e.target.value)} style={{ width:150 }}>
            {(copilotProviders?.providers || [{ name:"auto", display_name:"Configured provider" }]).map(p=><option key={p.name} value={p.name}>{p.display_name || (p.name === "mock" ? "Offline Deterministic" : p.name)}</option>)}
          </select>
        </div>
      </div>

      <div className="agent-chat-grid">
        <div className="card" style={{ display:"flex", flexDirection:"column", minHeight:520 }}>
          <div style={{ flex:1, overflowY:"auto", padding:"20px 24px", display:"flex", flexDirection:"column", gap:14 }}>
            {messages.map((m,i)=>(
              <div key={i} style={{ display:"flex", gap:10, flexDirection:m.role==="user"?"row-reverse":"row" }}>
                <div style={{ width:28,height:28,borderRadius:"50%",background:m.role==="user"?"var(--accent)":"var(--purple)",display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,fontWeight:800,color:m.role==="user"?"var(--bg)":"#fff",flexShrink:0 }}>
                  {m.role==="user"?"U":"✦"}
                </div>
                <div style={{ background:m.role==="user"?"rgba(0,102,204,.07)":"var(--bg2)", border:`1px solid ${m.role==="user"?"rgba(0,102,204,.18)":"var(--border)"}`, borderRadius:"var(--rl)", padding:"11px 14px", maxWidth:"78%", fontSize:13, lineHeight:1.65, color:"var(--text)", whiteSpace:"pre-wrap" }}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div style={{ display:"flex", gap:10 }}>
                <div style={{ width:28,height:28,borderRadius:"50%",background:"var(--purple)",display:"flex",alignItems:"center",justifyContent:"center",fontSize:13 }}>✦</div>
                <div style={{ background:"var(--bg2)", border:"1px solid var(--border)", borderRadius:"var(--rl)", padding:"11px 14px" }}>
                  <span className="pulse" style={{ color:"var(--purple)" }}>Running local agent…</span>
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>

          <div style={{ padding:"12px 24px", borderTop:"1px solid var(--border)", background:"var(--bg2)" }}>
            <div style={{ display:"flex", flexWrap:"wrap", gap:7, marginBottom:10 }}>
              {suggestions.map(s=><span key={s} className="ai-chip" onClick={()=>send(s)}>{s}</span>)}
            </div>
            <div style={{ display:"flex", gap:9 }}>
              <input
                style={{ flex:1, background:"var(--bg3)", border:"1px solid rgba(124,92,255,.3)", borderRadius:"var(--r)", padding:"10px 13px", color:"var(--text)", fontSize:13, fontFamily:"var(--font-d)", outline:"none" }}
                placeholder="Ask about UMA runs, validation, cost, logs, Cortex, Snowpark, or Hermes…"
                aria-label="Ask UMA Copilot"
                value={query} onChange={e=>setQuery(e.target.value)}
                onKeyDown={e=>e.key==="Enter"&&!e.shiftKey&&send()}
              />
              <button className="btn btn-purple" onClick={()=>send()} disabled={loading || !query.trim()}>
                {loading?<Spinner/>:"Ask"}
              </button>
            </div>
            {preview && (
              <div style={{ marginTop:10, padding:12, border:"1px solid var(--border)", borderRadius:"var(--r)", background:"var(--bg3)" }}>
                <div style={{ display:"flex", justifyContent:"space-between", gap:10, alignItems:"center" }}>
                  <div>
                    <div style={{ fontWeight:800, fontSize:12 }}>Proposed Action: {preview.action_type}</div>
                    <div className="text-muted" style={{ fontSize:11 }}>{preview.reason}</div>
                  </div>
                  <span className={`badge ${preview.category==="BLOCKED"?"br":preview.requires_confirmation?"by":"bg"}`}>{preview.category}</span>
                </div>
                {preview.category !== "BLOCKED" && (
                  <button className="btn btn-primary btn-sm mt3" onClick={executePreview} disabled={actionBusy==="execute"}>
                    {actionBusy==="execute" ? "Executing..." : preview.requires_confirmation ? "Confirm via UMA" : "Run Read-Only Action"}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
          <div className="card" style={{ padding:16 }}>
            <div className="settings-title">Agent Runtime</div>
            <div className="info-tile mb3"><div className="text-muted">Provider</div><div className="info-tile-value">{agentState?.provider || provider}</div></div>
            <div className="info-tile mb3"><div className="text-muted">Health</div><div className="info-tile-value">{agentState?.health?.status || "not checked"}</div></div>
            <div className="info-tile"><div className="text-muted">Grounded</div><div className="info-tile-value">{agentState?.grounded === false ? "no" : "yes"}</div></div>
          </div>
          <div className="card" style={{ padding:16 }}>
            <div className="settings-title">Snowflake Intelligence</div>
            {serviceRows.map(([name,status])=>(
              <div className="settings-row" key={name}>
                <div>
                  <div className="settings-key">{name}</div>
                  <div className="settings-desc">{name === "Connection" ? (snowflakeServices?.snowflake_connection?.connection_name || "Snowflake connection") : "Safe read-only UMA service"}</div>
                </div>
                <span className={`badge ${String(status).includes("READY") || status==="AVAILABLE" ? "bg" : String(status).includes("REQUIRED") || String(status).includes("MISSING") ? "by" : "bgr"}`}>{status}</span>
              </div>
            ))}
          </div>
          <div className="card" style={{ padding:16 }}>
            <div className="settings-title">Safety Boundary</div>
            {[
              ["Orchestration", "UMA remains source of truth"],
              ["Cortex", "Intelligence over metadata, logs, docs"],
              ["Hermes", "Optional copilot adapter only"],
              ["Mutations", "Require confirmation and approval"],
              ["SQL", "No arbitrary direct execution"],
            ].map(([k,v])=>(
              <div className="settings-row" key={k}>
                <div><div className="settings-key">{k}</div><div className="settings-desc">{v}</div></div>
              </div>
            ))}
          </div>
          <div className="card" style={{ padding:16 }}>
            <div className="settings-title">Source Context</div>
            <div className="text-muted" style={{ fontSize:12, lineHeight:1.6 }}>
              Answers display run_id, validation_id, cost_estimate_id, and report_id when supplied by the selected workflow or action preview.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Legacy AgentOrchestratorPage archived during Migration Intelligence hardening.
// The active client-facing surface is `MigrationIntelligencePage`.

// ─── Scheduler ────────────────────────────────────────────────

function SchedulerPage() {
  const { data: overview, refetch: refetchOverview } = useApi(() => api.getReplicationOverview().catch(()=>null), []);
  const { data: connections, loading, refetch: refetchConnections } = useApi(() => api.getReplicationConnections().catch(()=>[]), []);
  const { data: sources, refetch: refetchSources } = useApi(() => api.getReplicationSources().catch(()=>[]), []);
  const { data: jobs, refetch: refetchJobs } = useApi(() => api.getReplicationJobs().catch(()=>[]), []);
  const { data: runs, refetch: refetchRuns } = useApi(() => api.getReplicationRuns().catch(()=>[]), []);
  const { data: readiness, refetch: refetchReadiness } = useApi(() => api.getReplicationSnowflakeReadiness().catch(()=>null), []);
  const [showNew, setShowNew] = useState(false);
  const [showJob, setShowJob] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [activeSchedulerKpi, setActiveSchedulerKpi] = useState("jobs");
  const [search, setSearch] = useState("");
  const [op, setOp] = useState("");
  const [connDraft, setConnDraft] = useState({
    name:"",
    connector_type:"postgres",
    role:"source",
    description:"",
    configText:"{}",
    credentialsText:"{}",
  });
  const [jobDraft, setJobDraft] = useState({
    name:"",
    source_connection_id:"",
    destination_connection_id:"",
    sync_mode:"incremental",
    schedule:"",
    tablesText:"public.customers",
  });
  const selectedJob = (jobs||[]).find(j => j.id === selectedJobId) || null;
  const selectedRun = (runs||[]).find(r => r.id === selectedRunId) || null;
  const { data: selectedTables, refetch: refetchSelectedTables } = useApi(() => selectedJobId ? api.getReplicationJobTables(selectedJobId).catch(()=>[]) : Promise.resolve([]), [selectedJobId]);
  const { data: selectedPlan, refetch: refetchSelectedPlan } = useApi(() => selectedJobId ? api.getReplicationJobPlan(selectedJobId).catch(()=>({ plans:[] })) : Promise.resolve({ plans:[] }), [selectedJobId]);
  const { data: selectedMapping, refetch: refetchSelectedMapping } = useApi(() => selectedJobId ? api.getReplicationJobMapping(selectedJobId).catch(()=>({ mappings:[] })) : Promise.resolve({ mappings:[] }), [selectedJobId]);
  const { data: selectedEvents, refetch: refetchSelectedEvents } = useApi(() => selectedJobId ? api.getReplicationJobEvents(selectedJobId).catch(()=>[]) : Promise.resolve([]), [selectedJobId]);
  const { data: selectedErrors, refetch: refetchSelectedErrors } = useApi(() => selectedJobId ? api.getReplicationJobErrors(selectedJobId).catch(()=>[]) : Promise.resolve([]), [selectedJobId]);
  const { data: runTables, refetch: refetchRunTables } = useApi(() => selectedRunId ? api.getReplicationRunTables(selectedRunId).catch(()=>[]) : Promise.resolve([]), [selectedRunId]);
  const { data: runEvents, refetch: refetchRunEvents } = useApi(() => selectedRunId ? api.getReplicationRunEvents(selectedRunId).catch(()=>[]) : Promise.resolve([]), [selectedRunId]);
  const sourceConnections = (connections||[]).filter(c => ["source","both"].includes(c.role || "both"));
  const targetConnections = (connections||[]).filter(c => ["destination","both"].includes(c.role || "both"));
  const destinations = readiness?.destinations || [];

  useEffect(() => {
    if (!selectedJobId && jobs?.length) setSelectedJobId(jobs[0].id);
    if (selectedJobId && jobs?.length && !jobs.some(j=>j.id === selectedJobId)) setSelectedJobId(jobs[0]?.id || "");
  }, [jobs, selectedJobId]);

  useEffect(() => {
    if (!selectedRunId && runs?.length) setSelectedRunId(runs[0].id);
    if (selectedRunId && runs?.length && !runs.some(r=>r.id === selectedRunId)) setSelectedRunId(runs[0]?.id || "");
  }, [runs, selectedRunId]);

  useEffect(() => {
    const hasActive = Boolean((runs||[]).some(r => ["QUEUED","PLANNED"].includes((r.status || "").toUpperCase())));
    if (!hasActive) return;
    const timer = setInterval(() => {
      refetchOverview();
      refetchJobs();
      refetchRuns();
      refetchSelectedTables();
      refetchRunTables();
      refetchRunEvents();
    }, 3000);
    return () => clearInterval(timer);
  }, [runs, refetchOverview, refetchJobs, refetchRuns, refetchSelectedTables, refetchRunTables, refetchRunEvents]);

  const refreshAll = async () => {
    await Promise.all([
      refetchOverview(), refetchConnections(), refetchSources(), refetchJobs(),
      refetchRuns(), refetchReadiness(), refetchSelectedTables(), refetchSelectedPlan(), refetchSelectedMapping(), refetchSelectedEvents(), refetchSelectedErrors(), refetchRunTables(), refetchRunEvents()
    ]);
  };

  const parseJson = (text, fallback = {}) => {
    try { return text.trim() ? JSON.parse(text) : fallback; }
    catch { throw new Error("Config and credentials must be valid JSON."); }
  };

  const parseTables = (text, syncMode) => {
    return text.split(/\n|,/).map(v=>v.trim()).filter(Boolean).map(v => {
      const parts = v.split(".");
      const schema_name = parts.length > 1 ? parts.slice(0, -1).join(".") : "public";
      const table_name = parts[parts.length - 1];
      return { schema_name, table_name, target_schema: schema_name, target_table: table_name, selected:true, sync_mode: syncMode, columns:[] };
    });
  };

  const createConnection = async () => {
    try {
      const payload = {
        name: connDraft.name,
        connector_type: connDraft.connector_type,
        role: connDraft.role,
        description: connDraft.description,
        config: parseJson(connDraft.configText, {}),
        credentials: parseJson(connDraft.credentialsText, {}),
      };
      await api.createReplicationConnection(payload);
      setShowNew(false);
      setConnDraft({ name:"", connector_type:"postgres", role:"source", description:"", configText:"{}", credentialsText:"{}" });
      await refreshAll();
    } catch(e) { alert("Create connection failed: " + e.message); }
  };

  const createJob = async () => {
    try {
      const payload = {
        name: jobDraft.name,
        source_connection_id: jobDraft.source_connection_id,
        destination_connection_id: jobDraft.destination_connection_id,
        sync_mode: jobDraft.sync_mode,
        schedule: jobDraft.schedule || null,
        tables: parseTables(jobDraft.tablesText, jobDraft.sync_mode),
      };
      const created = await api.createReplicationJob(payload);
      setShowJob(false);
      setJobDraft({ name:"", source_connection_id:"", destination_connection_id:"", sync_mode:"incremental", schedule:"", tablesText:"public.customers" });
      await refreshAll();
      if (created?.id) setSelectedJobId(created.id);
    } catch(e) { alert("Create job failed: " + e.message); }
  };

  const testConn = async (id) => {
    try { setOp(`test:${id}`); await api.testReplicationConnection(id); await refreshAll(); }
    catch(e) { alert("Health check failed: " + e.message); }
    finally { setOp(""); }
  };

  const discover = async (id) => {
    try { setOp(`discover:${id}`); await api.discoverReplicationSource({ connection_id:id, schema_limit:5, table_limit:50, include_columns:true }); await refreshAll(); }
    catch(e) { alert("Discovery failed: " + e.message); }
    finally { setOp(""); }
  };

  const jobAction = async (job, action, payload = {}) => {
    try {
      setOp(`${action}:${job.id}`);
      const calls = {
        start: api.startReplicationJob,
        pause: api.pauseReplicationJob,
        resume: api.resumeReplicationJob,
        cancel: api.cancelReplicationJob,
        retry: api.retryReplicationJob,
      };
      await calls[action](job.id, payload);
      await refreshAll();
    } catch(e) { alert(`${action} failed: ` + e.message); }
    finally { setOp(""); }
  };

  const planSelectedJob = async () => {
    if (!selectedJobId) return;
    try {
      setOp(`plan:${selectedJobId}`);
      await api.createReplicationJobPlan(selectedJobId);
      await refreshAll();
    } catch(e) { alert("Plan creation failed: " + e.message); }
    finally { setOp(""); }
  };

  const rows = jobs || [];
  const filtered = rows.filter(p => {
    const hay = [p.name, p.sync_mode, p.source_connection_name, p.destination_connection_name, p.status].filter(Boolean).join(' ').toLowerCase();
    return !search.trim() || hay.includes(search.toLowerCase());
  });

  return (
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div className="page-eyebrow">Govern / Operate</div>
          <div style={{ fontSize:24, fontWeight:800 }}>Scheduler</div>
          <div className="text-muted mt2">Manage recurring replication cadence, queued/planned runs, schedule health, retries, and run history. Use Data Replication for job operations and table-level movement evidence.</div>
        </div>
        <div style={{ display:"flex", gap:8 }}>
          <button className="btn btn-ghost" onClick={refreshAll}>Refresh</button>
          <button className="btn btn-ghost" onClick={()=>setShowNew(true)}>+ Connection</button>
          <button className="btn btn-primary" onClick={()=>setShowJob(true)}>+ Replication Job</button>
        </div>
      </div>

      <div className="stats-grid">
        <button className={`stat-card is-clickable ${activeSchedulerKpi === "connections" ? "active" : ""}`} type="button" onClick={() => setActiveSchedulerKpi("connections")}><div className="stat-label">Connections</div><div className="stat-value">{overview?.connection_count ?? 0}</div><div className="stat-change">endpoints used by schedules</div></button>
        <button className={`stat-card is-clickable ${activeSchedulerKpi === "jobs" ? "active" : ""}`} type="button" style={{'--al':'var(--green)'}} onClick={() => setActiveSchedulerKpi("jobs")}><div className="stat-label">Scheduled Jobs</div><div className="stat-value">{overview?.job_count ?? 0}</div><div className="stat-change">persisted cadence definitions</div></button>
        <button className={`stat-card is-clickable ${activeSchedulerKpi === "runs" ? "active" : ""}`} type="button" style={{'--al':'var(--accent)'}} onClick={() => setActiveSchedulerKpi("runs")}><div className="stat-label">Run History</div><div className="stat-value">{overview?.run_count ?? 0}</div><div className="stat-change">queued/planned executions</div></button>
        <button className={`stat-card is-clickable ${activeSchedulerKpi === "scope" ? "active" : ""}`} type="button" style={{'--al':'var(--orange)'}} onClick={() => setActiveSchedulerKpi("scope")}><div className="stat-label">Schedule Scope</div><div className="stat-value">{overview?.selected_table_count ?? 0}</div><div className="stat-change">{overview?.planned_table_count ? `${overview.planned_table_count} planned strategies` : overview?.latest_error ? `latest error: ${overview.latest_error}` : 'no data movement claimed'}</div></button>
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-header"><div className="card-title">{activeSchedulerKpi === "connections" ? "Scheduled endpoint details" : activeSchedulerKpi === "runs" ? "Queued/planned run history" : activeSchedulerKpi === "scope" ? "Selected schedule scope" : "Scheduled job definitions"}</div></div>
        <div className="table-scroll sync-runs-table">
          {activeSchedulerKpi === "connections" ? (
            <table><thead><tr><th>Name</th><th>Connector</th><th>Role</th><th>Health</th><th>Latest Error</th></tr></thead><tbody>{(connections || []).map(c => <tr key={c.id}><td className="td-main">{c.name}</td><td>{c.connector_type}</td><td>{c.role}</td><td><StatusBadge status={c.health?.status || c.status || "UNKNOWN"} /></td><td className={c.latest_error || c.health?.safe_error ? "run-error" : "text-muted"}>{c.latest_error || c.health?.safe_error || "—"}</td></tr>)}</tbody></table>
          ) : activeSchedulerKpi === "runs" ? (
            <table><thead><tr><th>Run</th><th>Job</th><th>Status</th><th>Created</th></tr></thead><tbody>{(runs || []).map(r => <tr key={r.id} onClick={() => setSelectedRunId(r.id)} style={{ cursor: "pointer" }}><td className="td-mono">{String(r.id || "").slice(0, 8)}</td><td>{(jobs || []).find(j => j.id === r.job_id)?.name || r.job_id || "—"}</td><td><StatusBadge status={r.status} /></td><td className="td-mono">{fmt_dt(r.created_at || r.started_at)}</td></tr>)}</tbody></table>
          ) : activeSchedulerKpi === "scope" ? (
            <table><thead><tr><th>Table</th><th>Mode</th><th>Status</th><th>Last Sync</th></tr></thead><tbody>{(selectedTables || []).map(t => <tr key={t.id}><td className="td-main">{t.schema_name}.{t.table_name}</td><td>{t.sync_mode}</td><td><StatusBadge status={t.status} /></td><td className="td-mono">{fmt_dt(t.last_sync_at)}</td></tr>)}</tbody></table>
          ) : (
            <table><thead><tr><th>Name</th><th>Mode</th><th>Status</th><th>Schedule</th><th>Tables</th></tr></thead><tbody>{(jobs || []).map(j => <tr key={j.id} onClick={() => setSelectedJobId(j.id)} style={{ cursor: "pointer" }}><td className="td-main">{j.name}</td><td>{j.sync_mode}</td><td><StatusBadge status={j.status} /></td><td>{j.schedule || "manual"}</td><td className="td-mono">{j.table_count || 0}</td></tr>)}</tbody></table>
          )}
        </div>
      </div>

      {showNew && (
        <Modal title="Create Replication Connection" onClose={()=>setShowNew(false)} width={760}>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
            <Field label="Name"><input className="fi" value={connDraft.name} onChange={e=>setConnDraft(d=>({...d,name:e.target.value}))} placeholder="e.g. Postgres Source Retail" /></Field>
            <Field label="Connector"><select className="fi" value={connDraft.connector_type} onChange={e=>setConnDraft(d=>({...d,connector_type:e.target.value}))}>{["postgres","mysql","redshift","sqlserver","oracle","snowflake","bigquery","salesforce","s3","rest","fivetran","stitch"].map(v=><option key={v} value={v}>{v}</option>)}</select></Field>
            <Field label="Role"><select className="fi" value={connDraft.role} onChange={e=>setConnDraft(d=>({...d,role:e.target.value}))}><option value="source">source</option><option value="destination">destination</option><option value="both">both</option></select></Field>
            <Field label="Description"><input className="fi" value={connDraft.description} onChange={e=>setConnDraft(d=>({...d,description:e.target.value}))} /></Field>
            <Field label="Config JSON"><textarea className="fi" rows={5} value={connDraft.configText} onChange={e=>setConnDraft(d=>({...d,configText:e.target.value}))} /></Field>
            <Field label="Credentials JSON"><textarea className="fi" rows={5} value={connDraft.credentialsText} onChange={e=>setConnDraft(d=>({...d,credentialsText:e.target.value}))} /></Field>
          </div>
          <div style={{ display:"flex", justifyContent:"flex-end", gap:8, marginTop:16 }}>
            <button className="btn btn-ghost" onClick={()=>setShowNew(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={createConnection}>Create Connection</button>
          </div>
        </Modal>
      )}

      {showJob && (
        <Modal title="Create Replication Job" onClose={()=>setShowJob(false)} width={760}>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
            <Field label="Name"><input className="fi" value={jobDraft.name} onChange={e=>setJobDraft(d=>({...d,name:e.target.value}))} placeholder="e.g. Retail raw tables" /></Field>
            <Field label="Sync Mode"><select className="fi" value={jobDraft.sync_mode} onChange={e=>setJobDraft(d=>({...d,sync_mode:e.target.value}))}><option value="full_refresh">full_refresh</option><option value="incremental">incremental</option><option value="cdc">cdc</option></select></Field>
            <Field label="Source"><select className="fi" value={jobDraft.source_connection_id} onChange={e=>setJobDraft(d=>({...d,source_connection_id:e.target.value}))}><option value="">Select source</option>{sourceConnections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Field label="Destination"><select className="fi" value={jobDraft.destination_connection_id} onChange={e=>setJobDraft(d=>({...d,destination_connection_id:e.target.value}))}><option value="">Select destination</option>{targetConnections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Field label="Schedule"><input className="fi" value={jobDraft.schedule} onChange={e=>setJobDraft(d=>({...d,schedule:e.target.value}))} placeholder="optional cron" /></Field>
            <Field label="Selected Tables" hint="One schema.table per line or comma-separated"><textarea className="fi" rows={6} value={jobDraft.tablesText} onChange={e=>setJobDraft(d=>({...d,tablesText:e.target.value}))} /></Field>
          </div>
          <div style={{ display:"flex", justifyContent:"flex-end", gap:8, marginTop:16 }}>
            <button className="btn btn-ghost" onClick={()=>setShowJob(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={createJob}>Create Job</button>
          </div>
        </Modal>
      )}

      <div className="two-col">
        <div className="card">
          <div className="card-header"><div className="card-title">Scheduled Sync Jobs</div></div>
          <div className="filter-bar">
            <div className="sw"><span className="si">🔍</span><input placeholder="Search jobs…" value={search} onChange={e=>setSearch(e.target.value)} /></div>
          </div>
          {loading ? <Loading/> : !filtered.length ? (
            <div className="empty"><div className="empty-icon">↻</div><div className="empty-msg">{rows.length ? 'No replication jobs match your filters.' : 'No replication jobs yet.'}</div></div>
          ) : (
            <div className="table-scroll sync-profiles-table">
              <table>
                <thead><tr><th>Name</th><th>Mode</th><th>Status</th><th>Tables</th><th>Last Sync</th></tr></thead>
                <tbody>
                  {filtered.map(p=>(
                    <tr key={p.id} style={{ background:selectedJobId===p.id?'rgba(0,212,255,.08)':'transparent', cursor:'pointer' }} onClick={()=>setSelectedJobId(p.id)}>
                      <td>
                        <div className="td-main">{p.name}</div>
                        <div className="row-subtext">{p.source_connection_name || 'source'} → {p.destination_connection_name || 'target'}</div>
                      </td>
                      <td>{p.sync_mode}</td>
                      <td><StatusBadge status={p.status} /></td>
                      <td className="td-mono">{p.table_count}</td>
                      <td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(p.last_sync_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card" style={{ padding:18 }}>
          {!selectedJob ? (
            <div className="empty"><div className="empty-icon">🕐</div><div className="empty-msg">Select a replication job to inspect selected tables and lifecycle state.</div></div>
          ) : (
            <>
              <div className="card-title" style={{ marginBottom:4 }}>{selectedJob.name}</div>
              <div className="text-muted mb4">{selectedJob.source_connection_name || 'source'} → {selectedJob.destination_connection_name || 'destination'}</div>
              <div className="soft-grid" style={{ marginBottom:14 }}>
                <div className="info-tile"><div className="text-muted">Mode</div><div className="info-tile-value">{selectedJob.sync_mode}</div></div>
                <div className="info-tile"><div className="text-muted">Status</div><div className="info-tile-value">{selectedJob.status}</div></div>
                <div className="info-tile"><div className="text-muted">Schedule</div><div className="info-tile-value font-mono" style={{ fontSize:11 }}>{selectedJob.schedule || "manual"}</div></div>
                <div className="info-tile"><div className="text-muted">Last Sync</div><div className="info-tile-value font-mono" style={{ fontSize:11 }}>{fmt_dt(selectedJob.last_sync_at)}</div></div>
                <div className="info-tile"><div className="text-muted">Latest Error</div><div className="info-tile-value">{selectedJob.latest_error || "—"}</div></div>
                <div className="info-tile"><div className="text-muted">Latest Run</div><div className="info-tile-value">{selectedJob.latest_run?.status || "—"}</div></div>
              </div>
              <div style={{ display:'flex', gap:8, marginBottom:14 }}>
                <button className="btn btn-ghost" onClick={planSelectedJob} disabled={op===`plan:${selectedJob.id}`}>{op===`plan:${selectedJob.id}` ? <Spinner/> : 'Plan strategy'}</button>
                <button className="btn btn-ghost" onClick={()=>{ refetchSelectedEvents(); refetchSelectedErrors(); }}>View Logs</button>
                <button className="btn btn-ghost" onClick={()=>refetchSelectedMapping()}>View Table Runs</button>
                <button className="btn btn-primary" onClick={()=>jobAction(selectedJob, "start")} disabled={op===`start:${selectedJob.id}`}>{op===`start:${selectedJob.id}` ? <Spinner/> : 'Start planned run'}</button>
                <button className="btn btn-primary" onClick={()=>jobAction(selectedJob, "start", { execute:true, provider:"auto" })} disabled={op===`start:${selectedJob.id}`}>{op===`start:${selectedJob.id}` ? <Spinner/> : 'Execute real sync'}</button>
                <button className="btn btn-ghost" onClick={()=>jobAction(selectedJob, "pause")} disabled={op===`pause:${selectedJob.id}`}>Pause</button>
                <button className="btn btn-ghost" onClick={()=>jobAction(selectedJob, "resume")} disabled={op===`resume:${selectedJob.id}`}>Resume</button>
                <button className="btn btn-ghost" onClick={()=>jobAction(selectedJob, "retry")} disabled={op===`retry:${selectedJob.id}`}>Retry</button>
                <button className="btn btn-danger" onClick={()=>jobAction(selectedJob, "cancel")} disabled={op===`cancel:${selectedJob.id}`}>Cancel</button>
              </div>
              <div className="settings-title">Selected Tables</div>
              {!selectedTables?.length ? <div className="empty" style={{ padding:20 }}><div className="empty-msg">No tables selected yet.</div></div> : (
                <div className="table-scroll sync-runs-table">
                  <table>
                    <thead><tr><th>Table</th><th>Mode</th><th>Status</th><th>Last Sync</th><th>Error</th></tr></thead>
                    <tbody>{selectedTables.map(t=><tr key={t.id}><td className="td-main">{t.schema_name}.{t.table_name}</td><td>{t.sync_mode}</td><td><StatusBadge status={t.status} /></td><td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(t.last_sync_at)}</td><td className={t.latest_error ? "run-error" : "text-muted"}>{t.latest_error || "—"}</td></tr>)}</tbody>
                  </table>
                </div>
              )}
              <div className="settings-title" style={{ marginTop:16 }}>Source-to-Target Mapping</div>
              {!selectedMapping?.mappings?.length ? <div className="empty" style={{ padding:20 }}><div className="empty-msg">No mapping metadata yet.</div></div> : (
                <div className="table-scroll sync-runs-table">
                  <table>
                    <thead><tr><th>Source Table</th><th>Target Table</th><th>Columns</th><th>PK</th><th>Watermark</th><th>Target Exists</th><th>Drift Policy</th></tr></thead>
                    <tbody>{selectedMapping.mappings.map(m=>(
                      <tr key={m.job_table_id}>
                        <td className="td-main">{m.source_schema}.{m.source_table}</td>
                        <td>{m.target_schema}.{m.target_table}</td>
                        <td className="td-mono">{m.column_mapping?.length || 0}</td>
                        <td>{(m.primary_key_columns || []).join(", ") || "—"}</td>
                        <td>{m.watermark_column || "—"}</td>
                        <td><StatusBadge status={m.target_exists} /></td>
                        <td>{m.schema_drift_policy}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
              <div className="settings-title" style={{ marginTop:16 }}>Latest Errors & Events</div>
              <div className="table-scroll sync-runs-table">
                <table>
                  <thead><tr><th>Time</th><th>Stage</th><th>Status</th><th>Safe Error / Message</th><th>Recommended Action</th></tr></thead>
                  <tbody>
                    {(selectedErrors||[]).slice(0,5).map(e=><tr key={e.id}><td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(e.created_at)}</td><td>{e.category}</td><td><StatusBadge status="FAILED" /></td><td className="run-error">{e.safe_error_message}</td><td>{e.recommended_action}</td></tr>)}
                    {(selectedEvents||[]).slice(0,5).map(e=><tr key={e.id}><td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(e.created_at)}</td><td>{e.event_type}</td><td><StatusBadge status={e.level} /></td><td>{e.message}</td><td>{e.event_json?.recommended_action || "Review event context."}</td></tr>)}
                  </tbody>
                </table>
              </div>
              <div className="settings-title" style={{ marginTop:16 }}>Table-Level Strategy</div>
              {!selectedPlan?.plans?.length ? <div className="empty" style={{ padding:20 }}><div className="empty-msg">No plan persisted yet. Use Plan strategy to derive load and write modes from metadata.</div></div> : (
                <div className="table-scroll sync-runs-table">
                  <table>
                    <thead><tr><th>Table</th><th>Target</th><th>Load</th><th>Write</th><th>Keys</th><th>Watermark</th><th>Risk</th></tr></thead>
                    <tbody>{selectedPlan.plans.map(p=>(
                      <tr key={p.id || p.job_table_id}>
                        <td className="td-main">{p.source_schema}.{p.source_object}</td>
                        <td>{p.target_database}.{p.target_schema}.{p.target_object}</td>
                        <td>{p.load_mode}</td>
                        <td>{p.write_mode}</td>
                        <td>{(p.primary_key_columns || []).join(", ") || "—"}</td>
                        <td>{p.watermark_column || "—"}</td>
                        <td><StatusBadge status={p.risk_level} /></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="two-col" style={{ marginTop:18 }}>
        <div className="card">
          <div className="card-header"><div className="card-title">Connections & Connector Health</div></div>
          <div className="table-scroll sync-profiles-table">
            <table>
              <thead><tr><th>Name</th><th>Connector</th><th>Role</th><th>Health</th><th>Latest Error</th><th>Actions</th></tr></thead>
              <tbody>{(connections||[]).map(c=>(
                <tr key={c.id}>
                  <td className="td-main">{c.name}</td>
                  <td>{c.connector_type}</td>
                  <td>{c.role}</td>
                  <td><StatusBadge status={c.health?.status || c.status || "NOT_CONFIGURED"} /></td>
                  <td className={c.latest_error || c.health?.safe_error ? "run-error" : "text-muted"}>{c.latest_error || c.health?.safe_error || "—"}</td>
                  <td><div style={{ display:"flex", gap:6 }}><button className="btn btn-ghost btn-sm" onClick={()=>testConn(c.id)} disabled={op===`test:${c.id}`}>{op===`test:${c.id}` ? <Spinner/> : "Test"}</button>{["source","both"].includes(c.role) && <button className="btn btn-ghost btn-sm" onClick={()=>discover(c.id)} disabled={op===`discover:${c.id}`}>{op===`discover:${c.id}` ? <Spinner/> : "Discover"}</button>}</div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">Sources & Destinations</div></div>
          <div className="soft-grid" style={{ padding:18 }}>
            <div className="info-tile"><div className="text-muted">Sources</div><div className="info-tile-value">{(sources||[]).length}</div></div>
            <div className="info-tile"><div className="text-muted">Destinations</div><div className="info-tile-value">{destinations.length}</div></div>
            <div className="info-tile"><div className="text-muted">Snowflake Readiness</div><div className="info-tile-value">{readiness?.status || "NOT_CHECKED"}</div><div className="text-muted mt2">{readiness?.message || "No readiness check recorded."}</div></div>
            <div className="info-tile"><div className="text-muted">Migration Intelligence / Cortex Agent</div><div className="info-tile-value">Control-plane context ready</div><div className="text-muted mt2">Jobs, health, errors, and planned runs are API-backed.</div></div>
          </div>
          {!!readiness?.latest_check?.details?.checks?.length && (
            <div className="table-scroll sync-runs-table" style={{ padding:"0 18px 18px" }}>
              <table>
                <thead><tr><th>Snowflake Check</th><th>Status</th><th>Message</th></tr></thead>
                <tbody>{readiness.latest_check.details.checks.slice(0,8).map(c=>(
                  <tr key={c.key}><td className="td-main">{c.label}</td><td><StatusBadge status={c.status} /></td><td>{c.message}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
          <div className="table-scroll sync-runs-table" style={{ padding:"0 18px 18px" }}>
            <table>
              <thead><tr><th>Source</th><th>Status</th><th>Reason</th><th>Discovered</th></tr></thead>
              <tbody>{(sources||[]).map(s=><tr key={s.id}><td className="td-main">{s.name}</td><td><StatusBadge status={s.discovery_status} /></td><td>{s.discovery_reason || "—"}</td><td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(s.discovered_at)}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="two-col" style={{ marginTop:18 }}>
        <div className="card">
          <div className="card-header"><div className="card-title">Job Runs</div></div>
          <div className="table-scroll sync-runs-table">
            <table>
              <thead><tr><th>Run</th><th>Status</th><th>Tables</th><th>Created</th><th>Error</th></tr></thead>
              <tbody>{(runs||[]).map(r=><tr key={r.id} style={{ background:selectedRunId===r.id?'rgba(0,212,255,.08)':'transparent', cursor:'pointer' }} onClick={()=>setSelectedRunId(r.id)}><td className="td-mono" style={{ fontSize:10 }}>{r.id.slice(0,8)}</td><td><StatusBadge status={r.status} /></td><td>{r.planned_tables}</td><td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(r.created_at)}</td><td className={r.latest_error ? "run-error" : "text-muted"}>{r.latest_error || "—"}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">Table Sync Status</div></div>
          {!selectedRun ? <div className="empty"><div className="empty-msg">Select a run to inspect planned table state.</div></div> : (
            <>
              <div className="table-scroll sync-runs-table">
                <table>
                  <thead><tr><th>Table</th><th>Status</th><th>Error</th></tr></thead>
                  <tbody>{(runTables||[]).map(t=><tr key={t.id}><td className="td-main">{t.schema_name}.{t.table_name}</td><td><StatusBadge status={t.status} /></td><td className={t.latest_error ? "run-error" : "text-muted"}>{t.latest_error || "—"}</td></tr>)}</tbody>
                </table>
              </div>
              <div className="settings-title" style={{ padding:"0 18px" }}>Run Events</div>
              <div className="table-scroll sync-runs-table">
                <table>
                  <thead><tr><th>Time</th><th>Level</th><th>Event</th><th>Message</th></tr></thead>
                  <tbody>{(runEvents||[]).map(e=><tr key={e.id}><td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(e.created_at)}</td><td>{e.level}</td><td>{e.event_type}</td><td>{e.message}</td></tr>)}</tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function WorkspacePage() {
  const { data: connections, refetch: refetchWorkspaceConnections } = useApi(() => api.workspaceConnections().catch(()=>[]), []);
  const [connectionId, setConnectionId] = useState("");
  const selectedConnection = (connections||[]).find(c => c.id === connectionId);
  const requiresSnowflakeSession = selectedConnection?.type === "snowflake" && selectedConnection?.mfa_required;
  const [workspaceSessionId, setWorkspaceSessionId] = useState("");
  const workspaceSessionRef = useRef("");
  const [workspaceSessionExpiresAt, setWorkspaceSessionExpiresAt] = useState("");
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [unlockAuthMethod, setUnlockAuthMethod] = useState("password_mfa");
  const [unlockMfaPasscode, setUnlockMfaPasscode] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [sessionMessage, setSessionMessage] = useState("");
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

  const [sql, setSql] = useState(`SELECT CURRENT_TIMESTAMP AS current_ts;`);
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [aiQuestion, setAiQ] = useState("");
  const [generating, setGen] = useState(false);
  const [tab, setTab] = useState("editor");
  const [resultTab, setResultTab] = useState("results");
  const [queryHistory, setQueryHistory] = useState([]);
  const filteredTables = (tables || []).filter(t => !objectFilter.trim() || String(t).toLowerCase().includes(objectFilter.toLowerCase()));
  const changeConnection = (nextId) => {
    const next = (connections || []).find(c => c.id === nextId);
    setConnectionId(nextId);
    setWorkspaceSessionId("");
    setWorkspaceSessionExpiresAt("");
    setSessionMessage("");
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
    setSql(next?.type === "snowflake" ? "SELECT CURRENT_TIMESTAMP() AS CURRENT_TS;" : "SELECT CURRENT_TIMESTAMP AS current_ts;");
  };
  const requireSession = () => {
    if (requiresSnowflakeSession && !workspaceSessionId) {
      setError("Snowflake MFA session expired. Unlock Snowflake and retry. No data was moved.");
      return false;
    }
    return true;
  };

  useEffect(() => {
    if (!connectionId && connections?.length) setConnectionId(connections[0].id);
  }, [connections, connectionId]);

  useEffect(() => {
    workspaceSessionRef.current = workspaceSessionId;
  }, [workspaceSessionId]);

  useEffect(() => {
    return () => {
      if (workspaceSessionRef.current) {
        api.closeSnowflakeWorkspaceSession(workspaceSessionRef.current).catch(()=>{});
      }
    };
  }, []);

  useEffect(() => {
    const previousSession = workspaceSessionRef.current;
    if (previousSession) api.closeSnowflakeWorkspaceSession(previousSession).catch(()=>{});
    setWorkspaceSessionId("");
    setWorkspaceSessionExpiresAt("");
    setSessionMessage("");
    setUnlockAuthMethod(selectedConnection?.mfa_required ? "password_mfa" : "password");
    setUnlockMfaPasscode("");
    setDbs([]); setSchemas([]); setTables([]);
    setDatabase(""); setSchemaName(""); setSelectedTable("");
    setError(""); setResults(null); setPreview(null); setTableMeta([]);
    setSql(selectedConnection?.type === "snowflake" ? "SELECT CURRENT_TIMESTAMP() AS CURRENT_TS;" : "SELECT CURRENT_TIMESTAMP AS current_ts;");
  }, [connectionId]);

  useEffect(() => {
    if (!connectionId || !requireSession()) return;
    let cancelled = false;
    setNavLoading("databases");
    setDbs([]); setSchemas([]); setTables([]);
    api.workspaceDatabases(connectionId).then(r => {
      if (cancelled) return;
      if (r.error) setError(r.error);
      setDbs(r.items || []);
    }).catch(e=>{ if (!cancelled) { setDbs([]); setError(e.message); } })
      .finally(()=>{ if (!cancelled) setNavLoading(""); });
    return () => { cancelled = true; };
  }, [connectionId, workspaceSessionId, requiresSnowflakeSession]);

  useEffect(() => {
    if (dbs?.length && (!database || !dbs.includes(database))) setDatabase(dbs[0]);
  }, [dbs, database]);

  useEffect(() => {
    if (!connectionId || !database || !requireSession()) return;
    let cancelled = false;
    setNavLoading("schemas");
    setSchemas([]); setTables([]);
    api.workspaceSchemas(connectionId, database).then(r => {
      if (cancelled) return;
      if (r.error) setError(r.error);
      setSchemas(r.items || []);
    }).catch(e=>{ if (!cancelled) { setSchemas([]); setError(e.message); } })
      .finally(()=>{ if (!cancelled) setNavLoading(""); });
    return () => { cancelled = true; };
  }, [connectionId, workspaceSessionId, database, requiresSnowflakeSession]);

  useEffect(() => {
    if (!schemas?.length) return;
    const preferred = selectedConnection?.schema || (selectedConnection?.type === "postgres" ? "raw" : "PUBLIC");
    const match = schemas.find(s => String(s).toLowerCase() === String(preferred).toLowerCase());
    if (!schemaName || !schemas.includes(schemaName)) setSchemaName(match || schemas[0]);
  }, [schemas, schemaName, selectedConnection?.schema, selectedConnection?.type]);

  useEffect(() => {
    if (!connectionId || !database || !schemaName || !requireSession()) return;
    let cancelled = false;
    setNavLoading("tables");
    setTables([]);
    api.workspaceTables(connectionId, database, schemaName).then(r => {
      if (cancelled) return;
      if (r.error) setError(r.error);
      setTables(r.items || []);
    }).catch(e=>{ if (!cancelled) { setTables([]); setError(e.message); } })
      .finally(()=>{ if (!cancelled) setNavLoading(""); });
    return () => { cancelled = true; };
  }, [connectionId, workspaceSessionId, database, schemaName, requiresSnowflakeSession]);

  const unlockWorkspaceSession = async () => {
    if (!connectionId) {
      setError("Select a Snowflake connection first.");
      return;
    }
    if (unlockAuthMethod === "password_mfa" && unlockMfaPasscode.trim().length < 6) {
      setError("Enter the current Snowflake MFA/TOTP code to unlock this workspace session.");
      return;
    }
    setUnlocking(true); setError("");
    try {
      const body = {
        connection_id: connectionId,
        auth_method: unlockAuthMethod,
        database,
        schema_name: schemaName,
      };
      if (unlockAuthMethod === "password_mfa") body.mfa_passcode = unlockMfaPasscode.trim();
      const r = await api.createSnowflakeWorkspaceSession(body);
      setWorkspaceSessionId(r.session_id);
      setWorkspaceSessionExpiresAt(r.expires_at || "");
      setSessionMessage(`Session active${r.ttl_minutes ? ` for about ${r.ttl_minutes} minutes` : ""}.`);
      setUnlockMfaPasscode("");
      setUnlockOpen(false);
      await refetchWorkspaceConnections();
    } catch(e) {
      setError(e.message);
    }
    setUnlocking(false);
  };

  const lockWorkspaceSession = async () => {
    const id = workspaceSessionId;
    setWorkspaceSessionId("");
    setWorkspaceSessionExpiresAt("");
    setSessionMessage("");
    setDbs([]); setSchemas([]); setTables([]);
    setDatabase(""); setSchemaName(""); setSelectedTable("");
    setObjectFilter("");
    if (id) api.closeSnowflakeWorkspaceSession(id).catch(()=>{});
    refetchWorkspaceConnections();
  };

  const inspectTable = async (table) => {
    if (!requireSession()) return;
    setSelectedTable(table);
    try {
      const [desc, prev] = await Promise.all([
        api.workspaceColumns(connectionId, table, database, schemaName),
        api.workspacePreview(connectionId, { database, schema_name:schemaName, table, limit:50, workspace_session_id:workspaceSessionId || null }),
      ]);
      if (desc.error || prev.error) throw new Error(desc.error || prev.error);
      setTableMeta(desc.columns || []);
      setPreview(prev);
      setSql(selectedConnection?.type === "postgres" ? `SELECT * FROM "${schemaName}"."${table}" LIMIT 100;` : `SELECT * FROM "${database}"."${schemaName}"."${table}" LIMIT 100;`);
      setTab("editor");
    } catch(e) { setError(e.message); }
  };

  const runQuery = async () => {
    if (!requireSession()) return;
    setRunning(true); setError(""); setResults(null);
    try {
      const r = await api.workspaceQuery(connectionId, { sql, database, schema_name: schemaName, max_rows: 1000, workspace_session_id:workspaceSessionId || null });
      if (!r.success) { setError(r.error || "Query failed"); setResults(null); }
      else setResults(r);
      setResultTab(r.success ? "results" : "messages");
      setQueryHistory(h => [{
        id: Date.now(),
        connection: selectedConnection?.name || "connection",
        status: r.success ? "SUCCEEDED" : "FAILED",
        rows: r.row_count || 0,
        ms: r.execution_time_ms || 0,
        sql,
        error: r.error || "",
        created_at: new Date().toISOString(),
      }, ...h].slice(0, 20));
    } catch(e) { setError(e.message); }
    setRunning(false);
  };

  const generateSQL = async () => {
    if (!aiQuestion.trim()) return;
    setGen(true); setError("");
    try {
      const res = await api.aiSQL({ question: aiQuestion, database: database || "ANALYTICS_DB", schema_name: schemaName || "RAW", mode: "openai" });
      setSql(res.sql || "-- Could not generate SQL. Try a different question.");
    } catch(e) { setError(e.message); }
    setGen(false);
  };

  return (
    <div className="page sqlw-page">
      <div className="sqlw-head">
        <div>
          <div className="sqlw-title">SQL Workspace</div>
          <div className="sqlw-sub">Browse objects, write SQL, inspect results, and review query history.</div>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          {selectedConnection?.type === "snowflake" && (
            workspaceSessionId ? (
              <button className="btn btn-ghost btn-sm" onClick={lockWorkspaceSession}>Disconnect</button>
            ) : (
              <button className="btn btn-ghost btn-sm" onClick={()=>setUnlockOpen(true)} disabled={!connectionId}>Connect</button>
            )
          )}
          <button className="btn btn-primary" onClick={runQuery} disabled={running || !connectionId || (requiresSnowflakeSession && !workspaceSessionId)}>
            {running ? <Spinner/> : "Run"}
          </button>
        </div>
      </div>

      <div className="sqlw-shell">
        <div className="sqlw-commandbar">
          <div className="sqlw-connection">
            <select className="fi" value={connectionId} style={{ height:36 }} onChange={e=>changeConnection(e.target.value)}>
              <option value="">Select connection</option>
              {(connections||[]).map(c=><option key={c.id} value={c.id}>{c.name} · {c.type?.toUpperCase()}</option>)}
            </select>
          </div>
          <div className="sqlw-context">
            <select className="fi" value={database} disabled={!connectionId || (requiresSnowflakeSession && !workspaceSessionId)} style={{ flex:"1 1 220px", minWidth:150, height:36 }} onChange={e=>{ setDatabase(e.target.value); setSchemaName(""); setSelectedTable(""); }}>
              <option value="">Database</option>
              {dbs.map(d=><option key={d} value={d}>{d}</option>)}
            </select>
            <select className="fi" value={schemaName} disabled={!database || (requiresSnowflakeSession && !workspaceSessionId)} style={{ flex:"0 1 170px", minWidth:120, height:36 }} onChange={e=>{ setSchemaName(e.target.value); setSelectedTable(""); }}>
              <option value="">Schema</option>
              {schemas.map(s=><option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="sqlw-actions">
            <button className="btn btn-primary btn-sm" onClick={runQuery} disabled={running || !connectionId || (requiresSnowflakeSession && !workspaceSessionId)}>{running ? <Spinner/> : "Run SQL"}</button>
          </div>
        </div>

        <div className="sqlw-body">
          <aside className="sqlw-explorer">
            <div className="sqlw-panel-head">
              <div className="sqlw-panel-title">Object Explorer</div>
              <button className="btn btn-ghost btn-sm" onClick={()=>connectionId && api.workspaceDatabases(connectionId).then(r=>setDbs(r.items||[])).catch(e=>setError(e.message))}>Refresh</button>
            </div>
            <div className="sqlw-scroll">
              <div className="sqlw-tree">
                {!connectionId ? (
                  <div className="sqlw-empty" style={{ minHeight:160 }}>Select a connection.</div>
                ) : (
                  <>
                    <div className="sqlw-node"><span className="sqlw-dot green" />{selectedConnection?.name || "Connection"}</div>
                    {!!database && <div className="sqlw-node depth1">{database}</div>}
                    {!!schemaName && <div className="sqlw-node depth2">{schemaName}</div>}
                    {requiresSnowflakeSession && !workspaceSessionId ? (
                      <div className="sqlw-node depth2" style={{ color:"#64748b" }}>Connect to browse objects.</div>
                    ) : navLoading === "tables" ? (
                      <div className="sqlw-node depth2" style={{ color:"#64748b" }}>Loading objects...</div>
                    ) : !tables.length ? (
                      <div className="sqlw-node depth2" style={{ color:"#64748b" }}>No objects loaded.</div>
                    ) : (
                      <>
                        <div style={{ padding:"8px 8px 10px 42px" }}>
                          <input className="fi" style={{ height:32, fontSize:12 }} placeholder="Filter objects" value={objectFilter} onChange={e=>setObjectFilter(e.target.value)} />
                        </div>
                        {filteredTables.map(t=>(
                          <div key={t} className={`sqlw-table-row ${selectedTable===t ? "active" : ""}`} onClick={()=>inspectTable(t)}>
                            <span style={{ color:"#8ea0b5" }}>▦</span>{t}
                          </div>
                        ))}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          </aside>

          <main className="sqlw-main">
            <div className="sqlw-tabs">
              <div className="sqlw-tab active">SQL Console 1</div>
              <button className="sqlw-tab-add" onClick={()=>setSql(selectedConnection?.type === "snowflake" ? "SELECT CURRENT_TIMESTAMP() AS CURRENT_TS;" : "SELECT CURRENT_TIMESTAMP AS current_ts;")}>+</button>
              <div className="sqlw-result-meta">{sql.split("\n").length} lines · {sql.length} chars</div>
            </div>

            <div className="sqlw-editor-area">
              <div className="sqlw-editor-toolbar">
                <button className="btn btn-primary btn-sm" onClick={runQuery} disabled={running || !connectionId || (requiresSnowflakeSession && !workspaceSessionId)}>{running ? <Spinner/> : "Run SQL"}</button>
                <button className="btn btn-ghost btn-sm" onClick={()=>setSql("")}>Clear</button>
                <button className="btn btn-ghost btn-sm" onClick={()=>setSql(selectedConnection?.type === "snowflake" ? "SELECT CURRENT_TIMESTAMP() AS CURRENT_TS;" : "SELECT CURRENT_TIMESTAMP AS current_ts;")}>New Query</button>
                {error && <span className="run-error" style={{ fontSize:12, marginLeft:8 }}>{error}</span>}
              </div>
              <div className="sqlw-editor-wrap">
                <div className="sqlw-gutter">
                  {sql.split("\n").map((_, idx)=><div key={idx}>{idx + 1}</div>)}
                </div>
                <textarea
                  className="sqlw-editor"
                  value={sql}
                  onChange={e=>setSql(e.target.value)}
                  onKeyDown={e=>{ if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); runQuery(); } }}
                  spellCheck={false}
                />
              </div>
            </div>

            <div className="sqlw-results">
              <div className="sqlw-result-tabs">
                {["results","messages","history","preview","columns"].map(id=>(
                  <button key={id} className={`sqlw-result-tab ${resultTab===id ? "active" : ""}`} onClick={()=>setResultTab(id)}>
                    {id === "results" ? "Results" : id === "messages" ? "Messages" : id === "history" ? "History" : id === "preview" ? "Preview" : "Columns"}
                  </button>
                ))}
                <div className="sqlw-result-meta">
                  {results ? `${results.row_count || 0} rows · ${results.execution_time_ms || 0} ms` : "No result set"}
                </div>
              </div>
              <div style={{ minHeight:0, overflow:"auto", background:"#ffffff" }}>
                {resultTab === "results" && (
                  !results ? <div className="sqlw-empty">Run a query to see a result grid.</div> :
                  results.error ? <div className="alert-err" style={{ margin:12 }}>{results.error}</div> : (
                    <div className="result-table">
                      <table>
                        <thead><tr>{results.columns.map(c=><th key={c}>{c}</th>)}</tr></thead>
                        <tbody>{(results.rows||[]).slice(0,300).map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j} className="td-mono">{cell===null?<span style={{color:"var(--text3)"}}>NULL</span>:String(cell)}</td>)}</tr>)}</tbody>
                      </table>
                    </div>
                  )
                )}
                {resultTab === "messages" && (
                  <div style={{ padding:12 }}>
                    {error ? <div className="alert-err">{error}</div> : results ? <div className="alert-info">Query completed. {results.row_count || 0} row(s) returned in {results.execution_time_ms || 0} ms.</div> : <div className="text-muted">No messages yet.</div>}
                  </div>
                )}
                {resultTab === "history" && (
                  <div className="result-table">
                    <table><thead><tr><th>Time</th><th>Connection</th><th>Status</th><th>Rows</th><th>ms</th><th>SQL</th></tr></thead><tbody>
                      {queryHistory.map(h=><tr key={h.id} onClick={()=>setSql(h.sql)} style={{ cursor:"pointer" }}><td className="td-mono">{fmt_dt(h.created_at)}</td><td>{h.connection}</td><td><StatusBadge status={h.status} /></td><td>{h.rows}</td><td>{h.ms}</td><td className="td-mono">{h.sql.slice(0,120)}</td></tr>)}
                    </tbody></table>
                    {!queryHistory.length && <div className="sqlw-empty">No query history yet.</div>}
                  </div>
                )}
                {resultTab === "preview" && (
                  !preview ? <div className="sqlw-empty">Select a table to preview rows.</div> : (
                    <div className="result-table"><table><thead><tr>{preview.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{preview.rows.slice(0,100).map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j} className="td-mono">{cell===null?"NULL":String(cell)}</td>)}</tr>)}</tbody></table></div>
                  )
                )}
                {resultTab === "columns" && (
                  !selectedTable ? <div className="sqlw-empty">Select a table to inspect columns.</div> : (
                    <div className="result-table"><table><thead><tr><th>Column</th><th>Type</th></tr></thead><tbody>{tableMeta.map((c,idx)=><tr key={idx}><td>{c.name}</td><td className="td-mono">{c.type}</td></tr>)}</tbody></table></div>
                  )
                )}
              </div>
            </div>
          </main>

          <aside className="sqlw-inspector">
            <div className="sqlw-panel-head">
              <div className="sqlw-panel-title">Inspector</div>
            </div>
            <div className="sqlw-inspector-body">
              <div className="sqlw-inspect-section">
                <div className="sqlw-inspect-title">Connection</div>
                <div className="sqlw-kv"><span>Name</span><span>{selectedConnection?.name || "None"}</span></div>
                <div className="sqlw-kv"><span>Engine</span><span>{selectedConnection?.type ? selectedConnection.type.toUpperCase() : "None"}</span></div>
                <div className="sqlw-kv"><span>Database</span><span>{database || "Not selected"}</span></div>
                <div className="sqlw-kv"><span>Schema</span><span>{schemaName || "Not selected"}</span></div>
              </div>
              <div className="sqlw-inspect-section">
                <div className="sqlw-inspect-title">Object</div>
                <div className="sqlw-kv"><span>Table</span><span>{selectedTable || "None selected"}</span></div>
                <div className="sqlw-kv"><span>Columns</span><span>{tableMeta.length || "Not loaded"}</span></div>
                <div className="sqlw-kv"><span>Preview</span><span>{preview?.row_count ?? "Not loaded"}</span></div>
              </div>
              <div className="sqlw-inspect-section">
                <div className="sqlw-inspect-title">Last Result</div>
                <div className="sqlw-kv"><span>Rows</span><span>{results?.row_count ?? "No result"}</span></div>
                <div className="sqlw-kv"><span>Time</span><span>{results?.execution_time_ms != null ? `${results.execution_time_ms} ms` : "No result"}</span></div>
                <div className="sqlw-kv"><span>Status</span><span>{error ? "Failed" : results ? "Completed" : "Idle"}</span></div>
              </div>
              {selectedConnection?.type === "snowflake" && (
                <div className="sqlw-inspect-section">
                  <div className="sqlw-inspect-title">Snowflake</div>
                  <div className="sqlw-kv"><span>State</span><span>{workspaceSessionId ? "Connected" : "Not connected"}</span></div>
                  <div className="sqlw-kv"><span>Expires</span><span>{workspaceSessionExpiresAt ? fmt_dt(workspaceSessionExpiresAt) : "Not connected"}</span></div>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>
      {unlockOpen && (
        <Modal title="Connect to Snowflake" onClose={()=>{ if (!unlocking) setUnlockOpen(false); }}>
          <Field label="Authentication Method">
            <select className="fi" value={unlockAuthMethod} onChange={e=>{ setUnlockAuthMethod(e.target.value); setUnlockMfaPasscode(""); setError(""); }}>
              <option value="password">Password</option>
              <option value="password_mfa">Password + verification code</option>
              <option value="key_pair" disabled>Key Pair (coming soon)</option>
            </select>
          </Field>
          {unlockAuthMethod === "password_mfa" && (
            <Field label="Verification Code" hint="Used once for this connection attempt. UMA does not save the code.">
              <input
                className="fi"
                type="password"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="Current 6-digit code"
                value={unlockMfaPasscode}
                onChange={e=>{ setUnlockMfaPasscode(e.target.value); setError(""); }}
                onKeyDown={e=>e.key==="Enter"&&unlockWorkspaceSession()}
                autoFocus
              />
            </Field>
          )}
          <div className="alert-info" style={{ marginTop:10 }}>
            This opens a live Snowflake connection for browsing and approved SQL workspace actions.
          </div>
          <div className="modal-foot" style={{ margin:"18px -22px -18px" }}>
            <button className="btn btn-ghost" onClick={()=>setUnlockOpen(false)} disabled={unlocking}>Cancel</button>
            <button className="btn btn-primary" onClick={unlockWorkspaceSession} disabled={unlocking || !connectionId}>
              {unlocking ? <Spinner/> : "Connect"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
// ══════════════════════════════════════════════════════════════
// LINEAGE — Data lineage graph per table
// ══════════════════════════════════════════════════════════════
function LineagePage() {
  const [search, setSearch] = useState("");
  const { data: jobs, loading } = useApi(() => api.getJobs({ limit: 50 }), []);
  const [selected, setSelected] = useState(null);
  const [lineage, setLineage] = useState(null);
  const [loadingLin, setLL] = useState(false);

  const fetchLineage = async (job) => {
    setSelected(job); setLL(true);
    try {
      const tasks = await api.getJobTasks(job.id);
      // Build lineage from tasks
      const lin = {
        target_schema: `${job.sf_database || "ANALYTICS_DB"}.${job.sf_schema || "RAW"}`,
        lineage: tasks.map(t => ({
          source_dataset: t.source_dataset,
          source_table: t.source_table,
          target_table: t.target_table,
          rows_transferred: t.rows_exported,
          load_strategy: job.load_strategy,
          job_name: job.name,
          ended_at: t.ended_at,
        })),
      };
      setLineage(lin);
    } catch(e) { console.error(e); }
    setLL(false);
  };

  const filtered = (jobs||[]).filter(j => !search || j.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="page">
      <div style={{ fontSize:17, fontWeight:800, marginBottom:4 }}>Data Lineage</div>
      <div className="text-muted mb5">Trace data movement from source systems into Snowflake</div>

      <div style={{ display:"grid", gridTemplateColumns:"280px 1fr", gap:18 }}>
        <div>
          <div className="sw mb3"><span className="si">🔍</span><input placeholder="Search jobs…" value={search} onChange={e=>setSearch(e.target.value)} /></div>
          <div className="card">
            <div style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", fontSize:10, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)" }}>Migration Jobs</div>
            {loading ? <Loading/> : !filtered.length ? <div className="empty"><div className="empty-icon">⚡</div><div className="empty-msg">No jobs yet</div></div> : filtered.slice(0,30).map(j=>(
              <div key={j.id} style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", cursor:"pointer", fontSize:12, background:selected?.id===j.id?"rgba(0,212,255,.06)":"", transition:"background .1s" }}
                onClick={()=>fetchLineage(j)}>
                <div style={{ fontWeight:500, color:selected?.id===j.id?"var(--accent)":"var(--text)" }}>{j.name}</div>
                <div style={{ fontSize:10, color:"var(--text3)", marginTop:2, fontFamily:"var(--font-m)" }}>
                  {j.task_count || 0} tasks · {(j.total_rows_exported||0).toLocaleString()} rows
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ padding:24, minHeight:400 }}>
          {loadingLin && <Loading />}
          {!loadingLin && !selected && <div className="empty"><div className="empty-icon">🔀</div><div className="empty-msg">Select a job to view its lineage graph</div></div>}
          {!loadingLin && selected && (
            <>
              <div style={{ fontSize:14, fontWeight:700, marginBottom:20 }}>{selected.name}</div>
              <div className="text-muted mt3 mb3">Lineage rows below come from the selected job tasks and latest row movement evidence.</div>
              {lineage?.lineage?.length ? lineage.lineage.map((l,i) => (
                <div key={i} style={{ display:"flex", alignItems:"center", gap:0, marginBottom:16, flexWrap:"wrap" }}>
                  <div className="lineage-node source">
                    <div style={{ fontSize:9, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)", marginBottom:4 }}>Source</div>
                    <div style={{ fontSize:12, fontWeight:600 }}>{l.source_dataset}</div>
                    <div style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>{l.source_table}</div>
                  </div>
                  <div className="lineage-arrow">→</div>
                  <div style={{ background:"var(--bg3)", border:"1px solid var(--border)", borderRadius:"var(--r)", padding:"10px 14px", minWidth:120, textAlign:"center" }}>
                    <div style={{ fontSize:9, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)", marginBottom:4 }}>Transform</div>
                    <div style={{ fontSize:11, fontWeight:600 }}>UMA</div>
                    <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-m)" }}>{l.load_strategy || "full_load"}</div>
                  </div>
                  <div className="lineage-arrow">→</div>
                  <div className="lineage-node target">
                    <div style={{ fontSize:9, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)", marginBottom:4 }}>Snowflake</div>
                    <div style={{ fontSize:12, fontWeight:600 }}>{lineage.target_schema}</div>
                    <div style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>{l.target_table}</div>
                    <div style={{ fontSize:10, color:"var(--green)", marginTop:2, fontFamily:"var(--font-m)" }}>{(l.rows_transferred||0).toLocaleString()} rows</div>
                  </div>
                </div>
              )) : <div className="text-muted">No lineage data — run this job to populate.</div>}

              <div style={{ marginTop:20, padding:14, background:"var(--bg3)", borderRadius:"var(--r)", border:"1px solid var(--border)" }}>
                <div style={{ fontSize:10, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)", marginBottom:8 }}>Job Summary</div>
                {[
                  ["Status",         selected.status],
                  ["Rows Migrated",  (selected.total_rows_exported||0).toLocaleString()],
                  ["Data Volume",    `${selected.total_bytes_gb||0} GB`],
                  ["Strategy",       selected.load_strategy || "full_load"],
                  ["Destination",    `${selected.sf_database||""}.${selected.sf_schema||""}`],
                ].map(([k,v])=>(
                  <div key={k} style={{ display:"flex", justifyContent:"space-between", fontSize:12, padding:"5px 0", borderBottom:"1px solid var(--border)" }}>
                    <span style={{ color:"var(--text3)" }}>{k}</span>
                    <span style={{ fontFamily:"var(--font-m)", color:"var(--text)" }}>{v}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// SCHEMA DRIFT — Detection & auto-fix UI
// ══════════════════════════════════════════════════════════════
function SchemaDriftPage({ setPage = null }) {
  const { data: jobs, loading } = useApi(() => api.getJobs({ limit:50 }), []);
  const { data: connections } = useApi(() => api.getConnections(), []);
  const { data: controlRuns } = useApi(() => api.getControlPlaneRuns().catch(() => []), []);
  const [mode, setMode] = useState("job");          // "job" | "adhoc"
  const [selected, setSelected] = useState(null);
  const [selectedMigrationRunId, setSelectedMigrationRunId] = useState(() => typeof window !== "undefined" ? window.localStorage.getItem("uma.selectedRunId") || "" : "");
  const [driftResults, setDrift] = useState([]);
  const [activeDriftKpi, setActiveDriftKpi] = useState("tables");
  const [checking, setCheck] = useState(false);
  const [error, setError] = useState("");
  const [adhoc, setAdhoc] = useState({
    source_connection_id: "",
    source_dataset: "",
    source_table: "",
    dest_connection_id: "",
    target_database: "",
    target_schema: "",
    target_table: "",
  });

  const sources = (connections || []).filter(c => c.type !== "snowflake");
  const sfConns = (connections || []).filter(c => c.type === "snowflake");
  const selectedMigrationRun = (controlRuns || []).find(run => run.id === selectedMigrationRunId) || null;

  const persistMigrationRun = (runId) => {
    setSelectedMigrationRunId(runId);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("uma.selectedRunId", runId);
      window.dispatchEvent(new CustomEvent("uma:selected-run-changed", { detail: { runId } }));
    }
  };

  const linkDriftScopeToRun = async (statusOverride = "", explicitScope = null, explicitResults = null) => {
    if (!selectedMigrationRunId) {
      setError("Select a Migration Run before linking schema drift evidence.");
      return;
    }
    const scope = explicitScope || selected || null;
    const evidenceRows = explicitResults || driftResults;
    const scopeName = scope?.name || (mode === "adhoc" ? `Ad-hoc: ${adhoc.source_table || "source"} -> ${adhoc.target_table || "target"}` : "Schema drift scope");
    const scopeId = scope?.id || `${mode}:${adhoc.source_connection_id || "source"}:${adhoc.source_table || "table"}:${adhoc.target_table || "target"}`;
    try {
      await api.linkRunScope(selectedMigrationRunId, {
        scope_type: "schema_drift",
        scope_id: scopeId,
        scope_name: scopeName,
        relationship: mode === "adhoc" ? "adhoc_schema_drift_scope" : "job_schema_drift_scope",
        metadata: {
          mode,
          status: statusOverride || (evidenceRows.some(row => row.has_drift) ? "requires_review" : "clean"),
          drift_count: evidenceRows.filter(row => row.has_drift).length,
          checked_tables: evidenceRows.length,
          source_table: adhoc.source_table,
          target_table: adhoc.target_table,
          message: driftResults.length ? "Latest schema drift check is linked to this migration run." : "Schema drift scope is linked; run a drift check to populate evidence.",
        },
      });
      if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("uma:selected-run-changed", { detail: { runId: selectedMigrationRunId } }));
    } catch (e) {
      setError(e.message);
    }
  };

  const checkDrift = async (job) => {
    setSelected(job); setCheck(true); setError(""); setDrift([]);
    try {
      const tasks = await api.getJobTasks(job.id);
      const nextDrift = tasks.map(t => ({
        table: t.source_table,
        target_schema: t.target_schema,
        long_text: t.long_text_columns || 0,
        status: t.status,
        has_drift: (t.long_text_columns || 0) > 0,
        drifts: (t.long_text_columns > 0) ? [
          { column_name: "Long text fields", drift_type: "long_text",
            note: `${t.long_text_columns} column${t.long_text_columns>1?"s":""} detected as VARCHAR(16777216) — may impact downstream query performance` }
        ] : [],
      }));
      setDrift(nextDrift);
      if (selectedMigrationRunId) await linkDriftScopeToRun(nextDrift.some(row => row.has_drift) ? "requires_review" : "clean", job, nextDrift);
    } catch(e) { setError(e.message); }
    setCheck(false);
  };

  const runAdHocCheck = async () => {
    if (!adhoc.source_connection_id || !adhoc.dest_connection_id || !adhoc.source_table || !adhoc.target_table) {
      setError("Please fill in all required fields"); return;
    }
    setCheck(true); setError(""); setDrift([]); setSelected({ name: `Ad-hoc: ${adhoc.source_table} → ${adhoc.target_table}` });
    try {
      const r = await api.driftCheckAdHoc(adhoc);
      const adhocScope = { name: `Ad-hoc: ${adhoc.source_table} -> ${adhoc.target_table}` };
      const nextDrift = [{
        table: adhoc.source_table,
        target_schema: `${adhoc.target_database}.${adhoc.target_schema}`,
        long_text: 0,
        status: "checked",
        has_drift: r.has_drift || false,
        drifts: (r.drifts || []).map(d => ({
          column_name: d.column_name || d.name || "(unnamed)",
          drift_type: d.drift_type || "changed",
          source_type: d.source_type,
          target_type: d.target_type,
          note: d.note || d.message,
        })),
        source_schema_count: (r.source_schema || []).length,
      }];
      setSelected(adhocScope);
      setDrift(nextDrift);
      if (selectedMigrationRunId) await linkDriftScopeToRun(r.has_drift ? "requires_review" : "clean", adhocScope, nextDrift);
    } catch(e) {
      setError(e.message);
    }
    setCheck(false);
  };

  const driftCount = driftResults.filter(d=>d.has_drift).length;
  const driftKpiRows = {
    tables: driftResults,
    drift: driftResults.filter(d => d.has_drift),
    autofix: driftResults.filter(d => d.drifts.some(x => x.drift_type === "added")),
    long_text: driftResults.filter(d => d.long_text > 0),
  };
  const driftKpiTitles = {
    tables: "Tables checked",
    drift: "Tables with drift detected",
    autofix: "Auto-fixable additive drift",
    long_text: "Long text column risk",
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-eyebrow">Validate</div>
          <div className="page-title">Schema Drift</div>
          <div className="page-subtitle">Select a job or ad-hoc source/target pair, inspect drift evidence, recommended DDL, and review-decision actions.</div>
        </div>
        <div className="page-actions"><button className="btn btn-primary" disabled={checking} onClick={mode === "adhoc" ? runAdHocCheck : () => selected && checkDrift(selected)}>{checking ? <Spinner/> : "Run drift check"}</button></div>
      </div>

      <div className={`ep-alert-strip ${driftCount ? "has-blockers" : ""}`}>
        <div>
          <div className="ep-alert-kicker">Latest drift state</div>
          <div className="ep-alert-title">{driftCount ? `${driftCount} table${driftCount === 1 ? "" : "s"} with drift` : selected || driftResults.length ? "No drift currently blocking the selected scope" : "Select a job or configure an ad-hoc check."}</div>
        </div>
        <div className="ep-alert-items">
          <button className="ep-alert-item" disabled={!driftCount}><StatusBadge status={driftCount ? "REQUIRES_REVIEW" : "HEALTHY"} /><span>Create review decision</span></button>
        </div>
      </div>

      <div className="ep-list-panel" style={{ marginBottom: 14 }}>
        <div className="ep-list-head">
          <div>
            <div className="ep-list-title">Selected Migration Run Context</div>
            <div className="ep-list-subtitle">Schema drift checks are linked to the selected run and selected replication/conversion scope.</div>
          </div>
          <StatusBadge status={selectedMigrationRun?.status || "NO_RUN"} />
        </div>
        <div style={{ padding:12, display:"grid", gridTemplateColumns:"minmax(220px,1fr) minmax(220px,1fr) auto auto", gap:10, alignItems:"end" }}>
          <div className="fg">
            <label className="fl">Migration run</label>
            <select className="fi" value={selectedMigrationRunId} onChange={e => persistMigrationRun(e.target.value)}>
              <option value="">Select canonical run...</option>
              {(controlRuns || []).map(run => <option key={run.id} value={run.id}>{run.name} · {run.status}</option>)}
            </select>
          </div>
          <div className="fg">
            <label className="fl">Selected drift scope</label>
            <input className="fi" value={selected?.name || (mode === "adhoc" ? `${adhoc.source_table || "source"} -> ${adhoc.target_table || "target"}` : "No scope selected")} readOnly />
          </div>
          <button className="btn btn-primary btn-sm" disabled={!selectedMigrationRunId} onClick={() => linkDriftScopeToRun()}>Link Drift Scope</button>
          <button className="btn btn-ghost btn-sm" disabled={!selectedMigrationRunId || !setPage} onClick={() => setPage && setPage("run_detail")}>Open Run Detail</button>
        </div>
      </div>

      <div className="ep-kpi-row">
        {[
          ["Tables Checked",   driftResults.length, "latest scope", "tables"],
          ["Drift Detected",   driftCount, "requires review", "drift"],
          ["Auto-fixable",     driftResults.filter(d=>d.drifts.some(x=>x.drift_type==="added")).length, "additive columns", "autofix"],
          ["Long Text Cols",   driftResults.reduce((a,d)=>a+d.long_text,0), "type risk", "long_text"],
        ].map(([l,v,c,kpi])=>(
          <button key={l} type="button" className={`ep-kpi ${activeDriftKpi === kpi ? "active" : ""}`} onClick={() => setActiveDriftKpi(kpi)}>
            <div className="ep-kpi-label">{l}</div>
            <div className="ep-kpi-value">{v}</div>
            <div className="ep-kpi-note">{c}</div>
          </button>
        ))}
      </div>
      <div className="ep-list-panel" style={{ marginBottom: 14 }}>
        <div style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", fontSize:10, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)" }}>{driftKpiTitles[activeDriftKpi]}</div>
        {(driftKpiRows[activeDriftKpi] || []).length ? (
          (driftKpiRows[activeDriftKpi] || []).slice(0, 8).map((row, index) => (
            <div key={`${row.table}-${index}`} style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", display:"grid", gridTemplateColumns:"minmax(0,1fr) auto", gap:12 }}>
              <div>
                <div className="td-main">{row.table}</div>
                <div className="row-subtext">{row.target_schema || selected?.name || "Selected scope"}</div>
              </div>
              <div style={{ display:"flex", gap:8, alignItems:"center" }}>
                {row.long_text ? <span className="badge by">{row.long_text} long text</span> : null}
                <StatusBadge status={row.has_drift ? "REQUIRES_REVIEW" : "CLEAN"} />
              </div>
            </div>
          ))
        ) : (
          <div className="empty"><div className="empty-msg">No drift evidence behind this KPI yet. Select a job or run an ad-hoc check.</div></div>
        )}
      </div>

      <div className="tabs" style={{ paddingLeft: 0, marginBottom: 14 }}>
        <div className={`tab ${mode==="job"?"active":""}`} onClick={()=>{ setMode("job"); setDrift([]); setSelected(null); }}>
          Check from Job ({(jobs||[]).length})
        </div>
        <div className={`tab ${mode==="adhoc"?"active":""}`} onClick={()=>{ setMode("adhoc"); setDrift([]); setSelected(null); }}>
          Ad-hoc Check
        </div>
      </div>

      {mode === "job" ? (
        <div className="ep-workspace" style={{ gridTemplateColumns:"300px minmax(0,1fr)" }}>
          <div className="ep-list-panel">
            <div style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", fontSize:10, fontWeight:700, color:"var(--text3)", letterSpacing:1, textTransform:"uppercase", fontFamily:"var(--font-m)" }}>Select Job</div>
            {loading ? <Loading/> : !(jobs||[]).length ? (
              <div style={{ padding:24, textAlign:"center", color:"var(--text3)", fontSize:12 }}>
                No migration jobs yet. Create one in <strong>Migration Jobs</strong>, or switch to <strong>Ad-hoc Check</strong>.
              </div>
            ) : (jobs||[]).slice(0,20).map(j=>(
              <div key={j.id} style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", cursor:"pointer", fontSize:12, background:selected?.id===j.id?"rgba(0,212,255,.06)":"", transition:"background .1s" }}
                onClick={()=>checkDrift(j)}>
                <div style={{ fontWeight:500, color:selected?.id===j.id?"var(--accent)":"var(--text)" }}>{j.name}</div>
                <div style={{ fontSize:10, color:"var(--text3)", marginTop:2, fontFamily:"var(--font-m)" }}>{j.task_count||0} tables</div>
              </div>
            ))}
          </div>

          <div>
            {error && <div className="alert-err">✗ {error}</div>}
            {checking && <div className="card" style={{ padding:40, textAlign:"center", color:"var(--text3)" }}><Spinner/> Checking schema drift…</div>}
            {!checking && !selected && <div className="card empty"><div className="empty-icon">🔬</div><div className="empty-msg">Select a job to check for schema drift</div></div>}
            {!checking && selected && !driftResults.length && <div className="card empty"><div className="empty-icon">✓</div><div className="empty-msg">No tasks to check</div></div>}
            {!checking && driftResults.map((d,i)=>(
              <div key={i} className={`drift-card ${d.has_drift?"has-drift":"no-drift"}`}>
                <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:d.has_drift?10:0 }}>
                  <div>
                    <div style={{ fontSize:13, fontWeight:600 }}>{d.table}</div>
                    <div style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>{d.target_schema}</div>
                  </div>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    {d.long_text > 0 && <span className="badge by" style={{ fontSize:9 }}>{d.long_text} long text</span>}
                    <span className={`badge ${d.has_drift?"by":"bg"}`} style={{ fontSize:9 }}>
                      {d.has_drift ? "ATTENTION" : "CLEAN"}
                    </span>
                  </div>
                </div>
                {d.drifts.map((dr,j)=>(
                  <div key={j} style={{ background:"rgba(255,184,0,.05)", border:"1px solid rgba(255,184,0,.1)", borderRadius:"var(--r)", padding:"8px 12px", marginTop:6 }}>
                    <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                      <div style={{ fontSize:12 }}>
                        <span style={{ fontFamily:"var(--font-m)", color:"var(--yellow)" }}>{dr.column_name}</span>
                        <span style={{ color:"var(--text3)", marginLeft:8 }}>{String(dr.drift_type).replace(/_/g," ")}</span>
                      </div>
                      {dr.drift_type === "added" && (
                        <button className="btn btn-ghost btn-xs" style={{ color:"var(--green)", borderColor:"rgba(0,229,160,.2)" }}>
                          Auto-fix (ALTER TABLE)
                        </button>
                      )}
                    </div>
                    {dr.note && <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-m)", marginTop:4 }}>{dr.note}</div>}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ display:"grid", gridTemplateColumns:"360px 1fr", gap:16 }}>
          <div className="card" style={{ padding:16 }}>
            <div style={{ fontSize:13, fontWeight:700, marginBottom:12 }}>Ad-hoc Drift Check</div>
            <div className="text-muted" style={{ fontSize:11, marginBottom:14 }}>
              Compare any source table's schema to a Snowflake target without creating a job first.
            </div>

            <div className="fg">
              <label className="fl">Source Connection</label>
              <select className="fi" value={adhoc.source_connection_id} onChange={e=>setAdhoc({...adhoc, source_connection_id:e.target.value})}>
                <option value="">— select source —</option>
                {sources.map(c=><option key={c.id} value={c.id}>{c.name} ({c.type})</option>)}
              </select>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Source Dataset / Schema</label><input className="fi" placeholder="raw" value={adhoc.source_dataset} onChange={e=>setAdhoc({...adhoc, source_dataset:e.target.value})} /></div>
              <div className="fg"><label className="fl">Source Table</label><input className="fi" placeholder="customers" value={adhoc.source_table} onChange={e=>setAdhoc({...adhoc, source_table:e.target.value})} /></div>
            </div>

            <div className="divider" style={{ margin:"10px 0" }} />

            <div className="fg">
              <label className="fl">Snowflake Target</label>
              <select className="fi" value={adhoc.dest_connection_id} onChange={e=>setAdhoc({...adhoc, dest_connection_id:e.target.value})}>
                <option value="">— select snowflake —</option>
                {sfConns.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="fg"><label className="fl">Target Database</label><input className="fi" placeholder="Database name" value={adhoc.target_database} onChange={e=>setAdhoc({...adhoc, target_database:e.target.value})} /></div>
            <div className="fr">
              <div className="fg"><label className="fl">Target Schema</label><input className="fi" placeholder="Schema name" value={adhoc.target_schema} onChange={e=>setAdhoc({...adhoc, target_schema:e.target.value})} /></div>
              <div className="fg"><label className="fl">Target Table</label><input className="fi" placeholder="Table name" value={adhoc.target_table} onChange={e=>setAdhoc({...adhoc, target_table:e.target.value})} /></div>
            </div>

            <button className="btn btn-primary" onClick={runAdHocCheck} disabled={checking} style={{ width:"100%", marginTop:10 }}>
              {checking ? <Spinner/> : "Run Drift Check"}
            </button>
          </div>

          <div>
            {error && <div className="alert-err">✗ {error}</div>}
            {checking && <div className="card" style={{ padding:40, textAlign:"center", color:"var(--text3)" }}><Spinner/> Comparing schemas…</div>}
            {!checking && !driftResults.length && !error && (
              <div className="card empty">
                <div className="empty-icon">🔬</div>
                <div className="empty-msg">Fill in source + target and run a drift check.</div>
              </div>
            )}
            {!checking && driftResults.map((d,i)=>(
              <div key={i} className={`drift-card ${d.has_drift?"has-drift":"no-drift"}`}>
                <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 }}>
                  <div>
                    <div style={{ fontSize:13, fontWeight:600 }}>{d.table}</div>
                    <div style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>→ {d.target_schema}</div>
                  </div>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    <span className={`badge ${d.has_drift?"by":"bg"}`} style={{ fontSize:9 }}>
                      {d.has_drift ? `${d.drifts.length} DRIFTS` : "NO DRIFT"}
                    </span>
                  </div>
                </div>
                {d.source_schema_count != null && (
                  <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-m)", marginBottom:10 }}>
                    Source has {d.source_schema_count} column{d.source_schema_count === 1 ? "" : "s"}
                  </div>
                )}
                {d.drifts.map((dr,j)=>(
                  <div key={j} style={{ background:"rgba(255,184,0,.05)", border:"1px solid rgba(255,184,0,.1)", borderRadius:"var(--r)", padding:"8px 12px", marginTop:6 }}>
                    <div style={{ fontSize:12 }}>
                      <span style={{ fontFamily:"var(--font-m)", color:"var(--yellow)" }}>{dr.column_name}</span>
                      <span style={{ color:"var(--text3)", marginLeft:8 }}>{String(dr.drift_type).replace(/_/g," ")}</span>
                    </div>
                    {(dr.source_type || dr.target_type) && (
                      <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-m)", marginTop:4 }}>
                        {dr.source_type && <>source: <code>{dr.source_type}</code></>}
                        {dr.source_type && dr.target_type && " · "}
                        {dr.target_type && <>target: <code>{dr.target_type}</code></>}
                      </div>
                    )}
                    {dr.note && <div style={{ fontSize:10, color:"var(--text3)", marginTop:4 }}>{dr.note}</div>}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// SETTINGS — Platform configuration & connector registry
// ══════════════════════════════════════════════════════════════

function SettingsPage({ currentUser }) {
  const { data: settings, loading, error, refetch } = useApi(() => api.getSettings(), []);
  const { data: history, refetch: refetchHistory } = useApi(() => api.getSettingsHistory().catch(()=>[]), []);
  const { data: health } = useApi(() => api.getHealth().catch(()=>null), []);
  const { data: connections } = useApi(() => api.getConnections().catch(()=>[]), []);
  const { data: registry } = useApi(() => api.getRegistryStatus().catch(()=>[]), []);
  const { data: copilotProviders, refetch: refetchCopilotProviders } = useApi(() => api.getCopilotProviders().catch(()=>null), []);
  const { data: aiProviderStatus, refetch: refetchAiProviderStatus } = useApi(() => api.getAiProviderStatus().catch(e=>({ available:false, error:e.message })), []);
  const { data: ollamaHealth, refetch: refetchOllamaHealth } = useApi(() => api.getOllamaHealth().catch(e=>({ available:false, error:e.message })), []);
  const { data: ragStatus, refetch: refetchRagStatus } = useApi(() => api.getRagStatus().catch(()=>({ enabled:false, chunks:0 })), []);
  const [saved, setSaved] = useState(false);
	  const [testing, setTesting] = useState("");
	  const [testingOllama, setTestingOllama] = useState(false);
	  const [copilotProvider, setCopilotProvider] = useState("");
	  const [copilotTest, setCopilotTest] = useState("");
	  const [ragRunId, setRagRunId] = useState("");
	  const [ragIndexing, setRagIndexing] = useState(false);
  const [passwordForm, setPasswordForm] = useState({ current_password:"", new_password:"", confirm_password:"" });
  const [passwordStatus, setPasswordStatus] = useState(null);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const snowflakeServices = copilotProviders?.snowflake_services || {};
  const cortexServices = snowflakeServices?.cortex || {};
  const ollamaProvider = (copilotProviders?.providers || []).find(p=>p.name==="ollama") || {};
  const ollamaConfig = copilotProviders?.ollama || {};
  const ragConfig = copilotProviders?.rag || {};
  const copilotServiceRows = [
    ["Connection", snowflakeServices?.snowflake_connection?.status || "unknown"],
    ["Cortex LLM", cortexServices?.llm?.status || "unknown"],
    ["Cortex Analyst", cortexServices?.analyst?.status || "unknown"],
    ["Cortex Search", cortexServices?.search?.status || "unknown"],
    ["Document Search", cortexServices?.document_search?.status || "unknown"],
    ["Snowpark", snowflakeServices?.snowpark?.status || "unknown"],
    ["Query History", snowflakeServices?.intelligence?.query_history || "unknown"],
    ["Cost Intelligence", snowflakeServices?.intelligence?.cost_intelligence || "unknown"],
  ];
  const readyCount = (registry || []).filter(c=>c.status==="ready").length;
  const registryIcons = {
    bigquery:"🔷", redshift:"🔴", snowflake:"❄️", sqlserver:"🟧", postgres:"🐘", mysql:"🐬", oracle:"🔶",
    teradata:"⬛", synapse:"🔷", salesforce:"☁️", zendesk:"🎫", hubspot:"🧡", stripe:"💳", jira:"🔵",
    s3:"🪣", adls:"🌊", gcs:"🟡", sftp:"📂", flatfile:"📄", kafka:"⚡", kinesis:"🌀", rest:"🔌",
    netsuite:"🟦", workday:"🟩", ga4:"📊"
  };

  const [form, setForm] = useState(null);
  useEffect(() => { if (settings) setForm(JSON.parse(JSON.stringify(settings))); }, [settings]);

  const toggle = (k) => setForm(f => ({ ...f, feature_flags: { ...f.feature_flags, [k]: !f.feature_flags[k] } }));
  const setSf = (k,v) => setForm(f => ({ ...f, snowflake_defaults: { ...f.snowflake_defaults, [k]: v } }));
  const setAlerts = (k,v) => setForm(f => ({ ...f, alerts: { ...f.alerts, [k]: v } }));
  const setAi = (k,v) => setForm(f => ({ ...f, ai: { ...f.ai, [k]: v } }));
  const setRag = (k,v) => setForm(f => ({ ...f, rag: { ...(f.rag || {}), [k]: v } }));
  const setTelemetry = (k,v) => setForm(f => ({ ...f, telemetry: { ...f.telemetry, [k]: v } }));

  const save = async () => {
    try {
      await api.saveSettings(form);
      setSaved(true);
      refetch(); refetchHistory();
      setTimeout(()=>setSaved(false), 2000);
    } catch (e) { alert("Save failed: " + e.message); }
  };

  const runTest = async (which) => {
    try {
      setTesting(which);
      const r = which === "email" ? await api.testEmail() : await api.testSlack();
      alert(r.message || "Queued");
    } catch (e) {
      alert(`${which} test failed: ${e.message}`);
    } finally {
      setTesting("");
    }
  };

  const changeOwnPassword = async () => {
    setPasswordStatus(null);
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordStatus({ kind:"err", msg:"New passwords do not match." });
      return;
    }
    try {
      setPasswordSaving(true);
      await api.changePassword({
        current_password: passwordForm.current_password,
        new_password: passwordForm.new_password,
      });
      setPasswordForm({ current_password:"", new_password:"", confirm_password:"" });
      setPasswordStatus({ kind:"ok", msg:"Password changed. Use the new password next time you sign in." });
    } catch(e) {
      setPasswordStatus({ kind:"err", msg:e.message });
    } finally {
      setPasswordSaving(false);
    }
  };

  useEffect(() => {
    if (copilotProviders?.selected_provider && !copilotProvider) {
      setCopilotProvider(copilotProviders.selected_provider);
    }
  }, [copilotProviders?.selected_provider, copilotProvider]);

  const testCopilotProvider = async () => {
    try {
      setCopilotTest("testing");
      await api.askCopilot({
        provider: copilotProvider || copilotProviders?.selected_provider || "auto",
        message: "Provider health check from settings",
        context: { surface: "settings" },
      });
      await refetchCopilotProviders();
      setCopilotTest("ok");
      setTimeout(()=>setCopilotTest(""), 1800);
    } catch(e) {
      setCopilotTest(e.message);
    }
  };

	  const testOllamaProvider = async () => {
	    try {
	      setTestingOllama(true);
	      await refetchOllamaHealth();
      await refetchCopilotProviders();
      await refetchRagStatus();
    } finally {
	      setTestingOllama(false);
	    }
	  };

	  const indexRagRunFromSettings = async () => {
	    if (!ragRunId.trim()) return;
	    try {
	      setRagIndexing(true);
	      await api.indexRagRun(ragRunId.trim());
	      await refetchRagStatus();
	    } catch (e) {
	      alert("RAG indexing failed: " + e.message);
	    } finally {
	      setRagIndexing(false);
	    }
	  };

  if (loading || !form) return <Loading/>;
  if (error) return <ErrMsg msg={error} />;

  return (
    <div className="page">
      <div style={{ fontSize:17, fontWeight:800, marginBottom:4 }}>Settings</div>
      <div className="text-muted mb5">Operational controls, Snowflake defaults, alerting, AI provider configuration, and audit history.</div>

      <div className="card mb4" style={{ padding:20 }}>
        <div className="settings-title">Password</div>
        <div className="text-muted mb3">Change the password for {currentUser?.email || "your account"}. Existing passwords cannot be recovered as plaintext.</div>
        {passwordStatus && <div className={passwordStatus.kind==="ok"?"alert-ok":"alert-err"}>{passwordStatus.kind==="ok"?"✓ ":"✗ "}{passwordStatus.msg}</div>}
        <div className="two-col" style={{ gap:14 }}>
          <div className="fg">
            <label className="fl">Current Password</label>
            <input className="fi" type="password" value={passwordForm.current_password} onChange={e=>setPasswordForm({...passwordForm, current_password:e.target.value})} />
          </div>
          <div className="fg">
            <label className="fl">New Password</label>
            <input className="fi" type="password" value={passwordForm.new_password} onChange={e=>setPasswordForm({...passwordForm, new_password:e.target.value})} placeholder="New password" />
            <div className="fhint">Minimum 12 chars, uppercase, lowercase, digit, special character.</div>
          </div>
          <div className="fg">
            <label className="fl">Confirm New Password</label>
            <input className="fi" type="password" value={passwordForm.confirm_password} onChange={e=>setPasswordForm({...passwordForm, confirm_password:e.target.value})} />
          </div>
          <div className="fg" style={{ justifyContent:"flex-end", display:"flex", alignItems:"flex-end" }}>
            <button className="btn btn-primary" onClick={changeOwnPassword} disabled={passwordSaving || !passwordForm.current_password || !passwordForm.new_password}>
              {passwordSaving ? <Spinner/> : "Change Password"}
            </button>
          </div>
        </div>
      </div>

      <div className="two-col mb4">
        <div className="card" style={{ padding:20 }}>
          <div className="settings-title">Feature Flags</div>
          {[
            { key:"auto_drift",       label:"Schema Drift Auto-Detection",  desc:"Detect source/target schema changes on each sync or migration run and surface a diff." },
            { key:"schema_auto_add",  label:"Auto-Add New Columns",         desc:"Allow additive columns to be propagated automatically when policy allows." },
            { key:"ai_copilot",       label:"AI Copilot",                   desc:"Enable SQL generation, failure explanation, and migration guidance." },
            { key:"email_alerts",     label:"Email Alerts",                 desc:"Send notifications for failed jobs, syncs, or policy violations." },
            { key:"slack_alerts",     label:"Slack Alerts",                 desc:"Post job and sync status into your configured Slack channel." },
            { key:"telemetry",        label:"Anonymous Telemetry",          desc:"Send anonymized usage metrics only when explicitly enabled." },
          ].map(s=>(
            <div key={s.key} className="settings-row">
              <div>
                <div className="settings-key">{s.label}</div>
                <div className="settings-desc">{s.desc}</div>
              </div>
              <div className={`toggle ${form.feature_flags[s.key]?"on":""}`} onClick={()=>toggle(s.key)} />
            </div>
          ))}
          <div style={{ marginTop:12, fontSize:12, color:"var(--text2)", lineHeight:1.6 }}>
            <strong>Lineage:</strong> derived from migration jobs, tasks, source/target mappings, and Snowflake execution context. <br/>
            <strong>Schema Drift:</strong> compares the latest discovered source schema against the destination structure and policy.
          </div>
        </div>

        <div className="card" style={{ padding:20 }}>
          <div className="settings-title">Snowflake Defaults</div>
          {[
            ["default_warehouse", "Default Warehouse"],
            ["default_database",  "Default Database"],
            ["default_schema",    "Default Schema"],
            ["default_role",      "Default Role"],
            ["file_format",       "File Format"],
            ["staging_area",      "Staging Area"],
          ].map(([key,label])=>(
            <div key={key} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
              <span style={{ fontSize:12, color:"var(--text2)" }}>{label}</span>
              <input className="fi" style={{ width:180, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }}
                value={form.snowflake_defaults[key] ?? ""} onChange={e=>setSf(key, e.target.value)} />
            </div>
          ))}
          <button className="btn btn-primary mt3" style={{ width:"100%" }} onClick={save}>
            {saved ? "✓ Saved" : "Save Settings"}
          </button>
        </div>
      </div>

      <div className="two-col mb4">
        <div className="card" style={{ padding:20 }}>
          <div className="settings-title">Alerts</div>
          {[
            ["email_provider","Email Provider"],["email_from","From Address"],["email_recipients","Default Recipients"],
            ["slack_channel","Slack Channel"],["slack_webhook","Slack Webhook URL"],
          ].map(([key,label])=>(
            <div key={key} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
              <span style={{ fontSize:12, color:"var(--text2)" }}>{label}</span>
              <input className="fi" style={{ width:220, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }}
                value={form.alerts[key] ?? ""} onChange={e=>setAlerts(key, e.target.value)} />
            </div>
          ))}
          <div style={{ display:"flex", gap:8, marginTop:12 }}>
            <button className="btn btn-ghost btn-sm" onClick={()=>runTest("email")} disabled={testing==="email"}>{testing==="email" ? "Testing..." : "Test Email"}</button>
            <button className="btn btn-ghost btn-sm" onClick={()=>runTest("slack")} disabled={testing==="slack"}>{testing==="slack" ? "Testing..." : "Test Slack"}</button>
          </div>
        </div>

        <div className="card" style={{ padding:20 }}>
          <div className="settings-title">AI Provider</div>
          <div className="settings-row">
            <div>
              <div className="settings-key">Mode</div>
              <div className="settings-desc">LLM output is advisory only. UMA judge gates and Brain Review remain the source of truth.</div>
            </div>
            <select value={form.ai.provider || "offline_deterministic"} onChange={e=>setAi("provider", e.target.value)} style={{ width:260 }}>
              <option value="offline_deterministic">Offline deterministic</option>
              <option value="openai_compatible_self_hosted">Self-hosted OpenAI-compatible</option>
              <option value="ollama_local">Ollama Local</option>
              <option value="openai">OpenAI</option>
              <option value="azure_openai">Azure OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="snowflake_cortex_later">Snowflake Cortex later</option>
            </select>
          </div>
	          {[
	            ["base_url","Base URL"],["model","Chat Model"],["max_tokens","Max Tokens"],["temperature","Temperature"],
	          ].map(([key,label])=>(
            <div key={key} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
              <span style={{ fontSize:12, color:"var(--text2)" }}>{label}</span>
              <input className="fi" style={{ width:260, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }}
                value={form.ai[key] ?? ""}
	                onChange={e=>setAi(key, e.target.value)} />
	            </div>
	          ))}
	          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
	            <span style={{ fontSize:12, color:"var(--text2)" }}>API key/token</span>
	            <input className="fi" type="password" disabled style={{ width:260, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }} placeholder="Set AI_API_KEY in backend environment" />
	          </div>
	          <div className="settings-row">
	            <div>
	              <div className="settings-key">Provider Status</div>
	              <div className="settings-desc">{aiProviderStatus?.error || aiProviderStatus?.model || "Offline deterministic"}</div>
            </div>
            <span className={`badge ${aiProviderStatus?.available ? "bg" : "bgr"}`}>{aiProviderStatus?.available ? "AVAILABLE" : "OFFLINE"}</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={refetchAiProviderStatus}>Test connection</button>
          <div className="settings-title mt4">RAG Settings</div>
          <div className="settings-row">
            <div><div className="settings-key">Enable RAG</div><div className="settings-desc">Indexes redacted UMA evidence for scoped retrieval.</div></div>
            <div className={`toggle ${(form.rag || {}).enabled ? "on" : ""}`} onClick={()=>setRag("enabled", !(form.rag || {}).enabled)} />
          </div>
	          {[
	            ["embedding_provider","Embedding Provider"],["embedding_model","Embedding Model"],["top_k","Top K"],
	          ].map(([key,label])=>(
	            <div key={key} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
	              <span style={{ fontSize:12, color:"var(--text2)" }}>{label}</span>
              <input className="fi" style={{ width:220, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }}
                value={(form.rag || {})[key] ?? ""}
	                onChange={e=>setRag(key, e.target.value)} />
	            </div>
	          ))}
	          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
	            <span style={{ fontSize:12, color:"var(--text2)" }}>Vector Store</span>
	            <select value={(form.rag || {}).vector_store || "keyword"} onChange={e=>setRag("vector_store", e.target.value)} style={{ width:220 }}>
	              <option value="keyword">keyword</option>
	              <option value="pgvector">pgvector</option>
	              <option value="qdrant">qdrant</option>
	              <option value="chroma">chroma</option>
	            </select>
	          </div>
	          <div className="settings-row">
	            <div><div className="settings-key">Indexed Artifacts</div><div className="settings-desc">Last index: {ragStatus?.last_indexed_time || "not recorded"} · Effective store: {ragStatus?.effective_vector_store || ragStatus?.vector_store || "keyword"}</div></div>
	            <span className="badge bp">{ragStatus?.indexed_artifact_count || ragStatus?.chunks || 0}</span>
	          </div>
	          <div style={{ display:"flex", gap:8, marginTop:10, flexWrap:"wrap", alignItems:"center" }}>
	            <input className="fi" style={{ width:220, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }} value={ragRunId} onChange={e=>setRagRunId(e.target.value)} placeholder="Run ID to index" />
	            <button className="btn btn-ghost btn-sm" onClick={indexRagRunFromSettings} disabled={ragIndexing || !ragRunId.trim()}>{ragIndexing ? "Indexing" : "Index current run"}</button>
	            <button className="btn btn-ghost btn-sm" onClick={indexRagRunFromSettings} disabled={ragIndexing || !ragRunId.trim()}>Re-index artifacts</button>
	          </div>
	          <div className="text-muted" style={{ fontSize:12, lineHeight:1.6, marginTop:12 }}>
	            Self-hosted model quality depends on the selected model and hardware. LLM output is advisory and must pass UMA judge gates.
	          </div>
          {[
            ["enabled","Telemetry Enabled"],["mode","Telemetry Mode"],["endpoint","Telemetry Endpoint"],
          ].map(([key,label])=>(
            <div key={key} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
              <span style={{ fontSize:12, color:"var(--text2)" }}>{label}</span>
              {key==="enabled" ? <div className={`toggle ${form.telemetry.enabled?"on":""}`} onClick={()=>setTelemetry("enabled", !form.telemetry.enabled)} />
                : <input className="fi" style={{ width:220, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }}
                    value={form.telemetry[key] ?? ""} onChange={e=>setTelemetry(key, e.target.value)} />}
            </div>
          ))}
        </div>
      </div>

      <div className="card mb4" style={{ padding:20 }}>
        <div className="settings-title">Copilot Settings</div>
        <div className="two-col" style={{ gap:14 }}>
          <div>
            <Field label="Provider">
              <select value={copilotProvider || copilotProviders?.selected_provider || "offline_deterministic"} onChange={e=>setCopilotProvider(e.target.value)}>
                {(copilotProviders?.providers || [
                  { name:"offline_deterministic", display_name:"Offline Deterministic" },
                  { name:"openai_compatible_self_hosted", display_name:"Self-hosted OpenAI-compatible" },
                  { name:"ollama_local", display_name:"Ollama Local" },
                  { name:"openai", display_name:"OpenAI" },
                  { name:"azure_openai", display_name:"Azure OpenAI" },
                  { name:"anthropic", display_name:"Anthropic" },
                  { name:"snowflake_cortex_later", display_name:"Snowflake Cortex later" },
                  { name:"cortex", display_name:"Snowflake Cortex" },
                  { name:"hermes", display_name:"Hermes Agent" },
                ]).map(p=><option key={p.name} value={p.name}>{p.display_name || p.name}</option>)}
              </select>
            </Field>
            <div className="settings-row">
              <div>
                <div className="settings-key">Ollama Local</div>
                <div className="settings-desc">Private local LLM and embeddings. UMA does not call external APIs when this provider is selected.</div>
              </div>
              <span className={`badge ${ollamaHealth?.available ? "bg" : "bgr"}`}>{ollamaHealth?.available ? "AVAILABLE" : "UNAVAILABLE"}</span>
            </div>
            <div className="settings-row">
              <div>
                <div className="settings-key">RAG Index</div>
                <div className="settings-desc">Indexes redacted UMA artifacts, reports, validation evidence, conversion output, and Brain Review decisions.</div>
              </div>
              <span className={`badge ${ragStatus?.enabled ? "bp" : "bgr"}`}>{ragStatus?.chunks || 0} CHUNKS</span>
            </div>
            <div className="settings-row">
              <div>
                <div className="settings-key">Cortex Intelligence</div>
                <div className="settings-desc">Uses Cortex Analyst/Search/LLM functions only through safe UMA context.</div>
              </div>
              <span className={`badge ${copilotProviders?.cortex_enabled ? "bg" : "bgr"}`}>{copilotProviders?.cortex_enabled ? "ENABLED" : "DISABLED"}</span>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={testCopilotProvider} disabled={copilotTest==="testing"}>
              {copilotTest==="testing" ? "Testing..." : "Test Provider"}
            </button>
            {copilotTest && copilotTest!=="testing" && <span style={{ marginLeft:10, fontSize:12, color:copilotTest==="ok"?"var(--green)":"var(--red)" }}>{copilotTest==="ok" ? "Provider responded" : copilotTest}</span>}
          </div>
          <div>
            <div className="info-tile mb3">
              <div className="text-muted">Ollama Base URL</div>
              <div className="info-tile-value">{ollamaHealth?.base_url || ollamaConfig.base_url || "http://localhost:11434"}</div>
            </div>
            <div className="info-tile mb3">
              <div className="text-muted">Chat Model</div>
              <div className="info-tile-value">{ollamaHealth?.chat_model || ollamaConfig.chat_model || "not configured"}</div>
            </div>
            <div className="info-tile mb3">
              <div className="text-muted">Embedding Model</div>
              <div className="info-tile-value">{ollamaHealth?.embedding_model || ollamaConfig.embedding_model || "not configured"}</div>
            </div>
            <div className="info-tile mb3">
              <div className="text-muted">RAG Store</div>
              <div className="info-tile-value">{ragStatus?.vector_store || ragConfig.vector_store || "local"}</div>
            </div>
            <div className="info-tile">
              <div className="text-muted">Ollama Detail</div>
              <div className="info-tile-value">{ollamaHealth?.error || ollamaProvider?.health?.status || "ready"}</div>
            </div>
          </div>
        </div>
        <div style={{ display:"flex", gap:8, marginTop:12, flexWrap:"wrap" }}>
          <button className="btn btn-ghost btn-sm" onClick={testOllamaProvider} disabled={testingOllama}>{testingOllama ? "Testing..." : "Test Ollama"}</button>
          <button className="btn btn-ghost btn-sm" onClick={()=>{ refetchRagStatus(); refetchCopilotProviders(); }}>Refresh RAG Status</button>
        </div>
        <div className="settings-title mt4">Snowflake Intelligence Services</div>
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))", gap:10 }}>
          {copilotServiceRows.map(([name,status])=>(
            <div className="info-tile" key={name}>
              <div className="text-muted">{name}</div>
              <div className="info-tile-value">{status}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card mb4" style={{ padding:20 }}>
        <div className="settings-title">Connector Registry — {readyCount} ready · {(connections||[]).length} configured</div>
        <div className="connector-matrix">
          {(registry || []).map(c=>{
            return (
            <div key={c.connector_key} className="conn-matrix-card">
              <div className="conn-matrix-icon">{registryIcons[c.connector_key] || "🔗"}</div>
              <div>
                <div className="conn-matrix-name">{c.display_name}</div>
                <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-m)" }}>
                  {c.connector_key} · source {c.source_count} · target {c.target_count} · configured {c.configured_count}
                </div>
              </div>
              <div className="conn-matrix-status">
                {c.has_configured_connection && <span className="badge bp" style={{ fontSize:9, marginRight:5 }}>CONFIGURED</span>}
                <span className={`badge ${c.status==="ready"?"bg":"bgr"}`} style={{ fontSize:9 }}>{c.status === "ready" ? "READY" : "COMING SOON"}</span>
              </div>
            </div>
          )})}
        </div>
      </div>

      <div className="card mb4" style={{ padding:20 }}>
        <div className="settings-title">Settings Audit History</div>
        {!history?.length ? (
          <div className="empty"><div className="empty-icon">📝</div><div className="empty-msg">No settings changes yet.</div></div>
        ) : (
          <table>
            <thead><tr><th>Section</th><th>Changed At</th><th>Changed By</th><th>Summary</th></tr></thead>
            <tbody>
              {history.slice(0,20).map(h=>(
                <tr key={h.id}>
                  <td className="td-main">{h.key}</td>
                  <td className="td-mono" style={{ fontSize:10 }}>{new Date(h.changed_at).toLocaleString()}</td>
                  <td>{h.changed_by || "system"}</td>
                  <td style={{ fontSize:11, color:"var(--text2)" }}>
                    Updated {h.key} settings
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ padding:20 }}>
        <div className="settings-title">Deployment</div>
        <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:14 }}>
          {[
            { label:"API Status",  value:health?"Online":"Offline",                                  icon:health?"✅":"❌" },
            { label:"Version",     value:health ? `UMA v${health.version}` : "UMA",                  icon:"📦" },
            { label:"Environment", value:health?.environment || "development",                         icon:"🌐" },
            { label:"Build",       value:health?.build_sha ? health.build_sha.slice(0,7) : "local",   icon:"🔖" },
            { label:"Started",     value:health?.timestamp ? fmt_dt(health.timestamp) : "—",          icon:"🕒" },
            { label:"Database",    value:"PostgreSQL 16",                                             icon:"🗄" },
            { label:"Queue",       value:"Redis 7 · ARQ",                                             icon:"⚡" },
            { label:"AI Model",    value:form.ai.model || "configured",                               icon:"✦" },
            { label:"Scheduler",   value:"Managed sync scheduler",                                    icon:"🕐" },
            { label:"Uptime",      value:health?.uptime_s ? fmt_duration(health.uptime_s) : "—",     icon:"⏱" },
            { label:"Build Time",  value:health?.build_time || "local build",                         icon:"🛠" },
          ].map(s=>(
            <div key={s.label} style={{ background:"var(--bg3)", border:"1px solid var(--border)", borderRadius:"var(--r)", padding:"12px 14px" }}>
              <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-m)", marginBottom:4 }}>{s.icon} {s.label}</div>
              <div style={{ fontSize:13, fontWeight:600 }}>{s.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


// ─── Nav ──────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════
// USERS — Admin user management
// ══════════════════════════════════════════════════════════════
function UsersPage({ currentUser }) {
  const { data: users, loading, error, refetch } = useApi(() => api.listUsers().catch(e => {
    if (e.message && e.message.includes("admin")) return null;
    throw e;
  }), []);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const isAdmin = currentUser?.role === "admin";
  const selfUser = (users || []).find(u => u.id === currentUser?.id);
  const bootstrapAdminSetup = !isAdmin && Boolean(selfUser) && selfUser.role !== "admin";

  const handleDelete = async (u) => {
    if (u.id === currentUser?.id) { alert("Cannot delete yourself"); return; }
    if (!confirm(`Delete user ${u.email}?`)) return;
    try { await api.deleteUser(u.id); refetch(); }
    catch(e) { alert("Delete failed: " + e.message); }
  };

  const promoteSelf = async () => {
    try {
      await api.updateUser(currentUser.id, { role: "admin" });
      alert("Admin role assigned. The session will refresh now.");
      window.location.reload();
    } catch(e) {
      alert("Admin setup failed: " + e.message);
    }
  };

  if (!isAdmin && loading) {
    return <div className="page"><Loading /></div>;
  }

  if (!isAdmin && !bootstrapAdminSetup) {
    return (
      <div className="page">
        <div className="card empty">
          <div className="empty-icon">🔒</div>
          <div className="empty-msg">User management requires admin role.</div>
          <div className="text-muted mt3">You're signed in as <code>{currentUser?.email}</code> with role <code>{currentUser?.role}</code>.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>Users</div>
          <div className="text-muted mt2">{isAdmin ? "Manage platform users and their permissions" : "Finish administrator setup for this environment"}</div>
        </div>
        {isAdmin ? <button className="btn btn-primary" onClick={()=>setShowAdd(true)}>+ Add User</button> : null}
      </div>

      {bootstrapAdminSetup && (
        <div className="alert-info" style={{ marginBottom:14 }}>
          <div style={{ fontWeight:800 }}>No administrator is configured yet.</div>
          <div style={{ marginTop:4 }}>Your email is verified. Assign yourself the admin role to complete setup.</div>
          <button className="btn btn-primary btn-sm" style={{ marginTop:10 }} onClick={promoteSelf}>Make me admin</button>
        </div>
      )}

      <div className="card">
        {loading ? <Loading/> : error ? <ErrMsg msg={error} /> : !users?.length ? (
          <div className="empty"><div className="empty-icon">👥</div><div className="empty-msg">No users yet.</div></div>
        ) : (
          <table>
            <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Last Login</th><th>Actions</th></tr></thead>
            <tbody>
              {users.map(u=>(
                <tr key={u.id}>
                  <td className="td-main">
                    {u.email}
                    {u.id === currentUser?.id && <span className="badge bg" style={{ marginLeft:6, fontSize:9 }}>YOU</span>}
                  </td>
                  <td>{u.name}</td>
                  <td>
                    <span className={`badge ${u.role==="admin"?"bp":u.role==="editor"?"bb":u.role==="operator"?"by":"bg"}`} style={{ fontSize:9, textTransform:"uppercase" }}>
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span style={{ color: u.is_active ? "var(--green)" : "var(--text3)", fontSize:11 }}>
                      {u.is_active ? "● Active" : "○ Disabled"}
                    </span>
                  </td>
                  <td className="td-mono" style={{ fontSize:10 }}>{u.last_login ? new Date(u.last_login).toLocaleString() : "Never"}</td>
                  <td>
                    <div style={{ display:"flex", gap:5 }}>
                      {isAdmin && <button className="btn btn-ghost btn-sm" onClick={()=>setEditUser(u)}>Edit</button>}
                      {isAdmin && u.id !== currentUser?.id && (
                        <button className="btn btn-danger btn-icon btn-sm" onClick={()=>handleDelete(u)}>🗑</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {isAdmin && showAdd && <AddUserModal onClose={()=>{ setShowAdd(false); refetch(); }} />}
      {isAdmin && editUser && <EditUserModal user={editUser} onClose={()=>{ setEditUser(null); refetch(); }} />}
    </div>
  );
}

function AddUserModal({ onClose }) {
  const [form, setForm] = useState({ email:"", name:"", password:"", role:"viewer" });
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true); setStatus(null);
    try {
      await api.createUser(form);
      onClose();
    } catch(e) {
      setStatus({ kind:"err", msg: e.message });
      setSaving(false);
    }
  };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">Add User</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {status && <div className={status.kind==="ok"?"alert-ok":"alert-err"}>{status.kind==="ok"?"✓ ":"✗ "}{status.msg}</div>}
          <div className="fg">
            <label className="fl">Email</label>
            <input className="fi" value={form.email} onChange={e=>setForm({...form, email:e.target.value})} placeholder="user@company.com" />
          </div>
          <div className="fg">
            <label className="fl">Name</label>
            <input className="fi" value={form.name} onChange={e=>setForm({...form, name:e.target.value})} placeholder="Full Name" />
          </div>
          <div className="fg">
            <label className="fl">Password</label>
            <input className="fi" type="password" value={form.password} onChange={e=>setForm({...form, password:e.target.value})} placeholder="Temporary password" />
            <div className="fhint">Minimum 12 chars, uppercase, lowercase, digit, special character.</div>
          </div>
          <div className="fg">
            <label className="fl">Role</label>
            <select className="fi" value={form.role} onChange={e=>setForm({...form, role:e.target.value})}>
              <option value="viewer">Viewer — read-only access</option>
              <option value="operator">Operator — can run jobs, view logs</option>
              <option value="editor">Editor — can create/edit jobs and connections</option>
              <option value="admin">Admin — full access, manage users</option>
            </select>
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? <Spinner/> : "Create User"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditUserModal({ user, onClose }) {
  const [form, setForm] = useState({ name: user.name, role: user.role, is_active: user.is_active });
  const [passwordForm, setPasswordForm] = useState({ new_password:"", confirm_password:"" });
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const save = async () => {
    setSaving(true); setStatus(null);
    try {
      await api.updateUser(user.id, form);
      onClose();
    } catch(e) {
      setStatus({ kind:"err", msg: e.message });
      setSaving(false);
    }
  };

  const resetPassword = async () => {
    setStatus(null);
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setStatus({ kind:"err", msg:"New passwords do not match." });
      return;
    }
    try {
      setResetting(true);
      await api.resetUserPassword(user.id, { new_password: passwordForm.new_password });
      setPasswordForm({ new_password:"", confirm_password:"" });
      setStatus({ kind:"ok", msg:`Password reset for ${user.email}.` });
    } catch(e) {
      setStatus({ kind:"err", msg:e.message });
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">Edit {user.email}</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {status && <div className={status.kind==="ok"?"alert-ok":"alert-err"}>{status.kind==="ok"?"✓ ":"✗ "}{status.msg}</div>}
          <div className="fg">
            <label className="fl">Name</label>
            <input className="fi" value={form.name} onChange={e=>setForm({...form, name:e.target.value})} />
          </div>
          <div className="fg">
            <label className="fl">Role</label>
            <select className="fi" value={form.role} onChange={e=>setForm({...form, role:e.target.value})}>
              <option value="viewer">Viewer</option>
              <option value="operator">Operator</option>
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="fg">
            <label className="fl">Status</label>
            <div style={{ display:"flex", gap:10, alignItems:"center", padding:"8px 0" }}>
              <div className={`toggle ${form.is_active?"on":""}`} onClick={()=>setForm({...form, is_active: !form.is_active})} />
              <span style={{ fontSize:12 }}>{form.is_active ? "Active — user can sign in" : "Disabled — cannot sign in"}</span>
            </div>
          </div>
          <div className="divider" />
          <div className="settings-title">Password Reset</div>
          <div className="text-muted mb3">Set a new password for this user. Existing passwords cannot be recovered as plaintext.</div>
          <div className="fg">
            <label className="fl">New Password</label>
            <input className="fi" type="password" value={passwordForm.new_password} onChange={e=>setPasswordForm({...passwordForm, new_password:e.target.value})} placeholder="New password" />
            <div className="fhint">Minimum 12 chars, uppercase, lowercase, digit, special character.</div>
          </div>
          <div className="fg">
            <label className="fl">Confirm New Password</label>
            <input className="fi" type="password" value={passwordForm.confirm_password} onChange={e=>setPasswordForm({...passwordForm, confirm_password:e.target.value})} />
          </div>
          <button className="btn btn-danger" onClick={resetPassword} disabled={resetting || !passwordForm.new_password}>
            {resetting ? <Spinner/> : "Reset Password"}
          </button>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? <Spinner/> : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

const NAV = [
  { section:"COMMAND", items:[
    { id:"command",     label:"Command Center",  icon:"▦" },
    { id:"run_detail",  label:"Migration Run",   icon:"◎" },
  ]},
  { section:"DATA", items:[
    { id:"connections", label:"Connections",      icon:"🔗" },
    { id:"workspace",   label:"SQL Workspace",    icon:"▣" },
    { id:"tables",      label:"Tables / Inventory", icon:"🗂" },
  ]},
  { section:"UMA INTELLIGENCE", items:[
    { id:"orchestrator",label:"Migration Intelligence", icon:"⬢" },
    { id:"brain_review", label:"UMA Brain Review", icon:"◉" },
    { id:"ai",          label:"AI Copilot",       icon:"✦" },
  ]},
  { section:"MIGRATE", items:[
    { id:"sql_conversion", label:"SQL Conversion", icon:"⌁" },
    { id:"dbt_conversion", label:"dbt Conversion", icon:"⋄" },
    { id:"replication_plan", label:"Data Replication", icon:"↻" },
    { id:"artifact_factory", label:"Generated Artifacts", icon:"◫" },
  ]},
  { section:"VALIDATE", items:[
    { id:"validation_center", label:"Validation Center", icon:"✓" },
    { id:"drift",       label:"Schema Drift",     icon:"🔬" },
    { id:"reports", label:"Reports", icon:"▤" },
  ]},
  { section:"GOVERN / OPERATE", items:[
    { id:"lineage",     label:"Data Lineage",     icon:"🔀" },
    { id:"jobs",        label:"Runs / Jobs",      icon:"▥" },
    { id:"scheduler",   label:"Scheduler",        icon:"◷" },
  ]},
  { section:"MORE TOOLS", items:[
    { id:"more_tools", label:"More Tools", icon:"+", children:[
      { id:"etl_analyzer", label:"ETL / BI Analyzer", icon:"◇" },
      { id:"snowflake_advisor", label:"Readiness Scan", icon:"◌" },
      { id:"snowflake_provision", label:"Landing Zone Plan", icon:"▣" },
    ] },
  ]},
  { section:"ADMIN", items:[
    { id:"users",       label:"Users",            icon:"👥", adminOnly: true, bootstrapVisible: true },
    { id:"settings",    label:"Settings",         icon:"⚙" },
  ]},
];

function AuthShell({ mode, setMode, form, setForm, loading, error, onLogin, onRegister, registrationInfo, bootstrapAvailable }) {
  const set = (field, value) => setForm(prev => ({ ...prev, [field]: value }));
  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState("");
  const registrationUnavailable = false;
  const authMode = mode;
  const resend = async () => {
    setResending(true); setResendMsg("");
    try {
      const r = await api.resendVerification(form.email);
      setResendMsg(r.dev_verification_url ? `Dev verification URL: ${r.dev_verification_url}` : (r.message || "Verification email sent."));
    } catch(e) {
      setResendMsg(e.message);
    } finally {
      setResending(false);
    }
  };
  return (
    <>
      <style>{CSS}</style>
      <div className="auth-shell">
        <div className="auth-story">
          <div className="auth-story-copy">
            <div className="auth-kicker">Unified Migration Accelerator</div>
            <div className="auth-title">Migration workbench for governed Snowflake delivery.</div>
            <div className="auth-copy">
              UMA keeps source evidence, conversion status, validation results, replication jobs, review decisions, and reports in one operational control plane.
            </div>
          </div>
        </div>
        <div className="auth-panel-wrap">
        <div className="auth-panel">
          <div className="auth-brand">
            <div className="logo-icon">U</div>
            <div>
              <div className="auth-brand-name">UMA Platform</div>
              <div className="auth-brand-sub">Unified Migration Accelerator</div>
            </div>
          </div>
          <div className="auth-heading">{authMode === "login" ? "Sign in" : "Register"}</div>
          <div className="auth-subtitle">
            {authMode === "login"
              ? "Use your admin credentials to access the platform."
              : "Create your UMA Platform account. A verification email will be sent before access is enabled."}
          </div>
          <div className="auth-tabs">
            <button className={`btn ${authMode === "login" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("login")}>Login</button>
            <button className={`btn ${authMode === "register" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("register")}>Register</button>
          </div>
          {error && <ErrMsg msg={error} />}
          {authMode === "register" && registrationUnavailable && !error && (
            <div className="alert-info" style={{ marginBottom:14 }}>
              Registration is currently managed by an administrator. Use Login if you already have an account.
            </div>
          )}
          {registrationInfo && (
            <div className="alert-info" style={{ marginBottom:14 }}>
              <div style={{ fontWeight:700 }}>Check your email</div>
              <div style={{ fontSize:11, marginTop:4 }}>We sent a verification link to <code>{form.email}</code>.</div>
              {registrationInfo.dev_verification_url && (
                <div style={{ fontSize:11, marginTop:8, wordBreak:"break-all" }}>
                  Dev verification URL: <a style={{ color:"var(--accent)" }} href={registrationInfo.dev_verification_url}>{registrationInfo.dev_verification_url}</a>
                </div>
              )}
              <div style={{ display:"flex", gap:8, alignItems:"center", marginTop:10 }}>
                <button className="btn btn-ghost btn-sm" onClick={resend} disabled={resending}>{resending ? <Spinner/> : "Resend verification"}</button>
                {resendMsg && <span style={{ fontSize:10, color:"var(--text3)" }}>{resendMsg}</span>}
              </div>
            </div>
          )}
          <div className="fg">
            <label className="fl">Email</label>
            <input className="fi" value={form.email} onChange={e => set("email", e.target.value)} placeholder="you@company.com" />
          </div>
          {authMode === "register" && (
            <div className="fg">
              <label className="fl">Name</label>
              <input className="fi" value={form.name} onChange={e => set("name", e.target.value)} placeholder="Your Name" />
            </div>
          )}
          <div className="fg">
            <label className="fl">Password</label>
            <input className="fi" type="password" value={form.password} onChange={e => set("password", e.target.value)} placeholder="Temporary password" />
            {authMode === "register" && <div className="fhint">Minimum 12 chars, uppercase, lowercase, digit, and special character.</div>}
          </div>
          <div className="auth-submit">
            <button className="btn btn-primary" onClick={authMode === "login" ? onLogin : onRegister} disabled={loading || (authMode === "register" && registrationUnavailable)}>
              {loading ? <Spinner /> : authMode === "login" ? "Sign In" : "Create Account"}
            </button>
          </div>
        </div>
        </div>
      </div>
    </>
  );
}

function VerifyEmailPage() {
  const [status, setStatus] = useState("checking");
  const [message, setMessage] = useState("Verifying your email…");
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token") || "";
    if (!token) {
      setStatus("failed");
      setMessage("Verification token is missing.");
      return;
    }
    api.verifyEmail(token)
      .then(r => {
        setStatus("success");
        setMessage(r.message || "Email verified successfully.");
      })
      .catch(e => {
        setStatus("failed");
        setMessage(e.message || "Verification failed.");
      });
  }, []);
  return (
    <>
      <style>{CSS}</style>
      <div style={{ minHeight:"100vh", display:"grid", placeItems:"center", padding:24, background:"var(--bg)" }}>
        <div className="card" style={{ maxWidth:520, width:"100%", textAlign:"center", padding:28 }}>
          <div className="empty-icon" style={{ color:status==="success"?"var(--green)":status==="failed"?"var(--red)":"var(--accent)" }}>
            {status==="checking" ? <Spinner/> : status==="success" ? "✓" : "✗"}
          </div>
          <div style={{ fontSize:22, fontWeight:800, marginTop:12 }}>
            {status==="success" ? "Email verified" : status==="failed" ? "Verification failed" : "Checking verification"}
          </div>
          <div className="text-muted mt2">{message}</div>
          <button className="btn btn-primary" style={{ marginTop:18 }} onClick={()=>{ window.location.href="/"; }}>Return to UMA</button>
        </div>
      </div>
    </>
  );
}

const PAGE_TITLES = {
  run_detail:"Migration Run",
  command:"Command Center",
  connections:"Connections",
  orchestrator:"Migration Intelligence",
  brain_review:"UMA Brain Review",
  sql_conversion:"SQL Conversion",
  dbt_conversion:"dbt Conversion",
  etl_analyzer:"ETL / BI Analyzer",
  replication_plan:"Data Replication",
  validation_center:"Validation Plans",
  snowflake_advisor:"Readiness Scan",
  snowflake_provision:"Landing Zone Plan",
  artifact_factory:"Generated Artifacts",
  reports:"Reports",
  more_tools:"More Tools",
  ai:"AI Copilot",
  settings:"Settings",
  dashboard:"Run Board", jobs:"Migration Jobs", tables:"Data Explorer", workspace:"SQL Workspace", validation:"Validation", lineage:"Data Lineage", drift:"Schema Drift", scheduler:"Scheduler", users:"User Management",
};
const PAGE_SUBTITLES = {
  run_detail:"Canonical run evidence, blockers, gates, artifacts, and next action",
  command:"Overview, readiness, and full run capture in one control plane",
  connections:"Manage source and destination connectivity",
  orchestrator:"Discover and assess migration readiness",
  brain_review:"Decision workbench for migration risks, blockers, and generated artifacts",
  sql_conversion:"Analyze SQL readiness for Snowflake",
  dbt_conversion:"Generate dbt artifacts for Snowflake without executing them",
  etl_analyzer:"Extract ETL and BI components and dependencies",
  replication_plan:"Operate source-to-Snowflake replication jobs, run timelines, table status, and errors",
  validation_center:"Plan row counts, schema checks, and reconciliation after conversion",
  snowflake_advisor:"Optional Snowflake posture checks for connected accounts",
  snowflake_provision:"Optional plan-only Snowflake database, schema, role, and warehouse setup",
  artifact_factory:"Generated dbt and migration files",
  reports:"Unified report artifacts",
  more_tools:"Organized lower-frequency tools, diagnostics, and previews",
  ai:"Copilot for persisted runs and artifacts",
  settings:"Configuration, policies, alerts, and registry",
  dashboard:"All persisted runs, statuses, artifacts, and report access", jobs:"Build, run, and monitor migration jobs", tables:"Browse migrated tables and job-level table state", workspace:"Connector-aware SQL workbench", validation:"Data quality and reconciliation rules", lineage:"Trace data movement across jobs and targets", drift:"Detect and remediate schema changes", scheduler:"Manage recurring sync schedules, queued runs, retries, and cadence health", users:"User and role management",
};

// ─── App ──────────────────────────────────────────────────────
export default function App() {
  const isVerifyRoute = typeof window !== "undefined" && window.location.pathname === "/verify-email";
  const [page, setPage] = useState("command");
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ email:"", name:"", password:"" });
  const [authToken, setAuthToken] = useState(() => getStoredToken());
  const [authUser, setAuthUser] = useState(() => getStoredUser());
  const [authLoading, setAuthLoading] = useState(() => Boolean(getStoredToken()));
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authError, setAuthError] = useState("");
  const [bootstrapStatus, setBootstrapStatus] = useState(null);
  const [registrationInfo, setRegistrationInfo] = useState(null);
  const [selectedSwitchUserId, setSelectedSwitchUserId] = useState("");
  const [showAdvancedNav] = useState(true);
  const [expandedNav, setExpandedNav] = useState({});
  const [impersonatorSession, setImpersonatorSession] = useState(() => getImpersonatorSession());
  const [selectedRunContext, setSelectedRunContext] = useState(null);
  const [selectedRunContextError, setSelectedRunContextError] = useState("");
  const { data: health } = useApi(() => api.getHealth().catch(()=>null), []);
  const { data: switchableUsers } = useApi(() => authUser?.role === "admin" ? api.listUsers().catch(()=>[]) : Promise.resolve([]), [authUser?.role]);
  const { data: navBootstrapStatus } = useApi(() => authUser ? api.bootstrapStatus().catch(()=>null) : Promise.resolve(null), [authUser?.id, authUser?.role]);
  const adminBootstrapOpen = Boolean(authUser && authUser.role !== "admin" && navBootstrapStatus?.admin_count === 0);
  const availableImpersonations = (switchableUsers || []).filter(u => u?.is_active && u.id !== authUser?.id);

  const loadSelectedRunContext = useCallback(async () => {
    if (typeof window === "undefined" || !authToken) return;
    const runId = window.localStorage.getItem("uma.selectedRunId");
    if (!runId) {
      setSelectedRunContext(null);
      setSelectedRunContextError("");
      return;
    }
    try {
      const detail = await apiFetch(`/control-plane/runs/${encodeURIComponent(runId)}/detail`);
      setSelectedRunContext(detail);
      setSelectedRunContextError("");
    } catch (err) {
      setSelectedRunContext(null);
      setSelectedRunContextError(err.message || "Unable to load selected run");
    }
  }, [authToken]);

  useEffect(() => {
    loadSelectedRunContext();
    const handler = () => loadSelectedRunContext();
    window.addEventListener("storage", handler);
    window.addEventListener("uma:selected-run-changed", handler);
    return () => {
      window.removeEventListener("storage", handler);
      window.removeEventListener("uma:selected-run-changed", handler);
    };
  }, [loadSelectedRunContext, page]);

  useEffect(() => {
    let mounted = true;
    if (!authToken) {
      setAuthLoading(false);
      return;
    }
    setAuthLoading(true);
    api.me()
      .then((user) => {
        if (!mounted) return;
        setAuthUser(user);
        saveSession(authToken, user);
      })
      .catch(() => {
        if (!mounted) return;
        clearSession();
        setAuthToken("");
        setAuthUser(null);
      })
      .finally(() => {
        if (mounted) setAuthLoading(false);
      });
    return () => { mounted = false; };
  }, [authToken]);

  useEffect(() => {
    if (authToken && authUser) return;
    let mounted = true;
    api.bootstrapStatus()
      .then((status) => {
        if (!mounted) return;
        setBootstrapStatus(status);
        if (status?.bootstrap_available === false) {
          setAuthMode("login");
        }
      })
      .catch(() => {
        if (mounted) setBootstrapStatus(null);
      });
    return () => { mounted = false; };
  }, [authToken, authUser]);

  const finishAuth = (resp) => {
    saveSession(resp.access_token, resp.user);
    setAuthToken(resp.access_token);
    setAuthUser(resp.user);
    setAuthError("");
  };

  const handleLogin = async () => {
    setAuthSubmitting(true); setAuthError("");
    try {
      const resp = await api.login({ email: authForm.email, password: authForm.password });
      clearImpersonatorSession();
      setImpersonatorSession(null);
      setRegistrationInfo(null);
      finishAuth(resp);
    } catch (e) {
      setAuthError(e.message);
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleRegister = async () => {
    setAuthSubmitting(true); setAuthError("");
    try {
      const resp = await api.register({ email: authForm.email, name: authForm.name, password: authForm.password });
      const verificationPending = Boolean(resp?.email_verification_sent || resp?.email_verification_skipped || resp?.dev_verification_url);
      setRegistrationInfo(verificationPending ? resp : null);
      if (resp?.access_token && !verificationPending) {
        finishAuth(resp);
      } else {
        setAuthMode("login");
      }
    } catch (e) {
      if (String(e.message || "").toLowerCase().includes("first admin already exists")) {
        setAuthMode("login");
        setBootstrapStatus({ bootstrap_available: false, user_count: 1 });
      }
      setAuthError(e.message);
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleLogout = () => {
    clearSession();
    setImpersonatorSession(null);
    setAuthToken("");
    setAuthUser(null);
    setAuthForm({ email:"", name:"", password:"" });
    setAuthMode("login");
  };

  const handleImpersonate = async (userId) => {
    if (!userId) return;
    try {
      if (authUser?.role === "admin" && authToken) {
        saveImpersonatorSession(authToken, authUser);
        setImpersonatorSession({ token: authToken, user: authUser });
      }
      const resp = await api.impersonateUser(userId);
      finishAuth(resp);
      setSelectedSwitchUserId("");
      setPage("command");
    } catch (e) { alert("Switch user failed: " + e.message); }
  };

  const handleReturnToAdmin = () => {
    const original = getImpersonatorSession();
    if (!original) {
      alert("Original admin session is no longer available. Please log in as admin again.");
      return;
    }
    saveSession(original.token, original.user);
    clearImpersonatorSession();
    setImpersonatorSession(null);
    setAuthToken(original.token);
    setAuthUser(original.user);
    setSelectedSwitchUserId("");
    setPage("command");
  };

  // ─── Theme (light/dark) ───────────────────────────────────
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "light";
    const storedVersion = window.localStorage.getItem(THEME_VERSION_KEY);
    const storedTheme = window.localStorage.getItem(THEME_KEY);
    if (storedVersion !== THEME_VERSION) {
      window.localStorage.setItem(THEME_VERSION_KEY, THEME_VERSION);
      window.localStorage.setItem(THEME_KEY, "light");
      return "light";
    }
    return storedTheme || "light";
  });
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_KEY, next);
      window.localStorage.setItem(THEME_VERSION_KEY, THEME_VERSION);
    }
  };

  const pages = {
    run_detail:  <RunDetailPage setPage={setPage} />,
    dashboard:   <CommandCenterPage setPage={setPage} />,
    command:     <CommandCenterShell setPage={setPage} />,
    jobs:        <JobsPage />,
    tables:      <TablesCatalogPage setPage={setPage} />,
    workspace:   <SQLWorkspacePage />,
    connections: <ConnectionsPage />,
    validation:  <ValidationPage />,
    validation_center: <ValidationControlPage />,
    lineage:     <LineagePage />,
    drift:       <SchemaDriftPage setPage={setPage} />,
    scheduler:   <SchedulerPage />,
    replication_plan: <DataReplicationPage setPage={setPage} />,
    orchestrator:<MigrationIntelligenceControlPage />,
    brain_review:<BrainReviewPage setPage={setPage} />,
    sql_conversion: <SqlConversionControlPage setPage={setPage} />,
    dbt_conversion: <DbtConversionPage setPage={setPage} />,
    etl_analyzer: <AnalyzerControlPage />,
    snowflake_advisor: <AdvisorControlPage />,
    snowflake_provision: <ProvisionControlPage />,
    artifact_factory: <ArtifactFactoryPage setPage={setPage} />,
    reports: <ReportsPage setPage={setPage} />,
    more_tools: <MoreToolsPage setPage={setPage} />,
    ai:          <AICopilotControlPage />,
    users:       <UsersPage currentUser={authUser} />,
    settings:    <SettingsPage currentUser={authUser} />,
  };
  const advancedActive = NAV.some(section => section.advanced && section.items.some(item => item.id === page));
  const canSeeNavItem = (item) => !item.adminOnly || authUser?.role === "admin" || (item.bootstrapVisible && adminBootstrapOpen);
  const commandItems = NAV.flatMap(section => section.items.flatMap(item => [item, ...(item.children || [])]))
    .filter(canSeeNavItem)
    .filter(item => `${item.label} ${PAGE_SUBTITLES[item.id] || ""}`.toLowerCase().includes(commandQuery.toLowerCase()));

  if (authLoading) {
    return (
      <>
        <style>{CSS}</style>
        <div style={{ minHeight:"100vh", display:"grid", placeItems:"center", background:"var(--bg)" }}>
          <div className="card" style={{ width: 360, textAlign:"center" }}>
            <div style={{ marginBottom: 12 }}><Spinner /></div>
            <div style={{ fontWeight: 700 }}>Checking session…</div>
          </div>
        </div>
      </>
    );
  }

  if (isVerifyRoute) {
    return <VerifyEmailPage />;
  }

  if (!authToken || !authUser) {
    return <AuthShell mode={authMode} setMode={setAuthMode} form={authForm} setForm={setAuthForm} loading={authSubmitting} error={authError} onLogin={handleLogin} onRegister={handleRegister} registrationInfo={registrationInfo} bootstrapAvailable={bootstrapStatus?.bootstrap_available} />;
  }

  return (
    <>
      <style>{CSS}</style>
      <div className={`app theme-${theme}`}>
        <aside className="sidebar">
          <div className="logo-wrap">
            <div className="logo-row">
              <div className="logo-icon">U</div>
              <div className="logo-name">UMA Platform</div>
            </div>
            <div className="logo-sub">Unified Migration Accelerator</div>
          </div>
          <nav className="nav">
            {NAV.map(section=>{
              if (section.advanced && !showAdvancedNav && !advancedActive) return null;
              const visibleItems = section.items.filter(canSeeNavItem);
              if (!visibleItems.length) return null;
              return (
                <div className="nav-section" key={section.section}>
                  <div className="nav-lbl">{section.section}</div>
                  {visibleItems.map(item=>{
                    const children = (item.children || []).filter(canSeeNavItem);
                    const childActive = children.some(child => child.id === page);
                    const expanded = children.length && (expandedNav[item.id] || childActive);
                    return (
                      <div key={item.id}>
                        <div
                          className={`nav-item ${page===item.id || childActive ? "active" : ""}`}
                          onClick={() => {
                            setPage(item.id);
                            if (children.length) setExpandedNav(prev => ({ ...prev, [item.id]: !expanded }));
                          }}
                        >
                          <span className="ni">{item.icon}</span>
                          {item.label}
                          {item.badge && <span className="nbadge">{item.badge}</span>}
                          {children.length ? <span className="nav-caret">{expanded ? "▾" : "▸"}</span> : null}
                        </div>
                        {expanded ? (
                          <div className="nav-child-list">
                            {children.map(child => (
                              <div key={child.id} className={`nav-child ${page===child.id ? "active" : ""}`} onClick={() => setPage(child.id)}>
                                <span className="ni">{child.icon}</span>
                                {child.label}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </nav>
          <div className="sidebar-bot">
            <div style={{ fontSize:11, color:"var(--text3)", display:"flex", alignItems:"center" }}>
              <span className={health?"sdot":"sdot"} style={{ background:health?"var(--green)":"var(--red)", boxShadow:`0 0 5px ${health?"var(--green)":"var(--red)"}` }} />
              <span>{health ? "API Connected" : "API Offline"}</span>
            </div>
            <div style={{ fontSize:10, color:"var(--text3)", marginTop:6, fontFamily:"var(--font-m)" }}>{`UMA v${health?.version || "1.2.0"} · ${(health?.environment || "self-hosted")}`}</div>
          </div>
        </aside>

        <div className="main">
          <header className="topbar">
            <div>
              <div className="topbar-title">{PAGE_TITLES[page]}</div>
              <div className="topbar-sub">{`Connector workbench · ${(health?.environment || "development")} · v${health?.version || "1.2.0"}${health?.build_sha ? ` · ${health.build_sha.slice(0,7)}` : ""}`}</div>
            </div>
            <div className="topbar-controls">
              <button
                className="btn btn-ghost btn-sm topbar-command"
                onClick={() => { setCommandQuery(""); setCommandOpen(true); }}
                title="Open command palette"
              >
                <Search size={14} />
                <span>Search UMA</span>
              </button>
              <button className="btn btn-ghost btn-sm btn-icon"
                onClick={toggleTheme}
                title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
                {theme === "dark" ? "☀" : "☾"}
              </button>
              <span className="topbar-status">
                {health ? <span style={{ color:"var(--green)" }}>● Online</span> : <span style={{ color:"var(--red)" }}>● Offline</span>}
              </span>
              <div className="topbar-user">
                <div className="topbar-email">{authUser.email}</div>
                <span className={`badge ${authUser.role==="admin"?"bp":authUser.role==="editor"?"bb":authUser.role==="operator"?"by":"bg"}`} style={{ fontSize:8, marginLeft:5, textTransform:"uppercase" }}>
                  {authUser.role}
                </span>
              </div>
              {authUser.role === "admin" && (
                <div className="topbar-switcher">
                  <select
                    className="fi"
                    value={selectedSwitchUserId}
                    onChange={e=>setSelectedSwitchUserId(e.target.value)}
                  >
                    <option value="">Switch user…</option>
                    {availableImpersonations.map(u => (
                      <option key={u.id} value={u.id}>{u.email} ({u.role})</option>
                    ))}
                  </select>
                  <button
                    className="btn btn-primary btn-sm"
                    disabled={!selectedSwitchUserId}
                    onClick={()=>handleImpersonate(selectedSwitchUserId)}
                  >
                    Switch
                  </button>
                </div>
              )}
              {authUser.role !== "admin" && impersonatorSession?.user?.role === "admin" && (
                <div className="topbar-switcher">
                  <div className="topbar-email" title={impersonatorSession.user.email}>
                    Admin: {impersonatorSession.user.email}
                  </div>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleReturnToAdmin}
                  >
                    Back to admin
                  </button>
                </div>
              )}
              <button className="btn btn-ghost btn-sm" onClick={handleLogout}>Logout</button>
              <div className="topbar-avatar" title={authUser.name || authUser.email}>{(authUser.name || authUser.email || 'U').slice(0,1).toUpperCase()}</div>
            </div>
          </header>
          {authToken && authUser ? (
            <div style={{ margin: "12px 20px 0", border: "1px solid var(--border)", borderRadius: 8, background: "var(--bg2)", padding: "10px 12px", display: "grid", gridTemplateColumns: "minmax(220px,1.4fr) repeat(5,minmax(110px,1fr)) auto", gap: 10, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: "var(--text3)", letterSpacing: 1, textTransform: "uppercase", fontFamily: "var(--font-m)" }}>Selected Migration Run</div>
                <div className="td-main" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{selectedRunContext?.run?.name || selectedRunContextError || "No run selected"}</div>
              </div>
              <div><div className="stat-label">Status</div><div>{selectedRunContext ? <StatusBadge status={selectedRunContext.run_status} /> : "None"}</div></div>
              <div><div className="stat-label">Source</div><div className="td-mono" style={{ fontSize: 11 }}>{selectedRunContext?.source_target?.source_dialect || "n/a"}</div></div>
              <div><div className="stat-label">Target</div><div className="td-mono" style={{ fontSize: 11 }}>{selectedRunContext?.source_target?.target_dialect || "snowflake"}</div></div>
              <div><div className="stat-label">Readiness</div><div className="td-main">{selectedRunContext?.readiness_score ?? "n/a"}</div></div>
              <div><div className="stat-label">Blockers</div><div className="td-main">{selectedRunContext?.blockers?.length ?? 0}</div></div>
              <button className="btn btn-ghost btn-sm" disabled={!selectedRunContext} onClick={() => setPage("run_detail")}>Run Detail</button>
              <div style={{ gridColumn: "1 / -1", color: "var(--text3)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                Next action: {selectedRunContext?.next_recommended_action || "Select a run from Command Center or a module workspace."}
              </div>
            </div>
          ) : null}
          {commandOpen && (
            <Modal title="Command palette" onClose={() => setCommandOpen(false)} width={680}>
              <input
                className="fi"
                autoFocus
                placeholder="Search pages, tools, diagnostics, reports..."
                value={commandQuery}
                onChange={(event) => setCommandQuery(event.target.value)}
              />
              <div style={{ display: "grid", gap: 8, marginTop: 14 }}>
                {commandItems.slice(0, 10).map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className="btn btn-ghost"
                    style={{ justifyContent: "space-between", textAlign: "left" }}
                    onClick={() => { setPage(item.id); setCommandOpen(false); }}
                  >
                    <span><span className="ni">{item.icon}</span> {item.label}</span>
                    <span className="text-muted" style={{ fontSize: 11 }}>{PAGE_SUBTITLES[item.id] || "Open page"}</span>
                  </button>
                ))}
              </div>
            </Modal>
          )}
          <div style={{ flex:1 }}>
            {pages[page]}
          </div>
        </div>
      </div>
    </>
  );
}
