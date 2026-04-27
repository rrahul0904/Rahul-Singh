import React, { useState, useEffect, useRef, useCallback } from "react";

// ─── API Client ──────────────────────────────────────────────
const API_BASE = typeof window !== "undefined"
  ? (window.location.hostname === "localhost" ? "http://localhost:8000" : "")
  : "";

const TOKEN_KEY = "uma.accessToken";
const USER_KEY = "uma.currentUser";

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

function clearSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
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
  impersonateUser:    (id)       => apiFetch(`/auth/impersonate/${id}`, { method:"POST" }),
  // Connections
  getConnections:    ()         => apiFetch("/connections"),
  getConnection:     (id)       => apiFetch(`/connections/${id}`),
  createConnection:  (d)        => apiFetch("/connections", { method:"POST", body: JSON.stringify(d) }),
  updateConnection:  (id, d)    => apiFetch(`/connections/${id}`, { method:"PUT", body: JSON.stringify(d) }),
  deleteConnection:  (id)       => apiFetch(`/connections/${id}`, { method:"DELETE" }),
  testConnection:    (id)       => apiFetch(`/connections/${id}/test`, { method:"POST" }),
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
  // Validation
  getValidationRules:(p)        => apiFetch("/validation" + (p ? "?"+new URLSearchParams(p) : "")),
  createValidationRule:(d)      => apiFetch("/validation", { method:"POST", body: JSON.stringify(d) }),
  deleteValidationRule:(id)     => apiFetch(`/validation/${id}`, { method:"DELETE" }),
  runValidationRule: (id)       => apiFetch(`/validation/${id}/run`, { method:"POST" }),
  reconcileJob:      (d)        => apiFetch("/validation/reconcile", { method:"POST", body: JSON.stringify(d) }),
  // AI
  aiChat:            (messages) => apiFetch("/ai/chat", { method:"POST", body: JSON.stringify({ messages }) }),
  // Snowflake query execution
  snowflakeQuery:    (body)     => apiFetch("/snowflake/query", { method:"POST", body: JSON.stringify(body) }),
  listDatabases:     ()         => apiFetch("/snowflake/databases"),
  listSchemas:       (db)       => apiFetch(`/snowflake/schemas/${db}`),
  // Snowflake diagnostics
  diagnoseSnowflake: (body)     => apiFetch("/snowflake/diagnose", { method:"POST", body: JSON.stringify(body) }),
  // Schema drift
  driftCheck:        (body)     => apiFetch("/drift/check", { method:"POST", body: JSON.stringify(body) }),
  driftCheckAdHoc:   (body)     => apiFetch("/drift/check-adhoc", { method:"POST", body: JSON.stringify(body) }),
  driftApply:        (body)     => apiFetch("/drift/apply", { method:"POST", body: JSON.stringify(body) }),
  // AI extras
  aiSQL:             (body)     => apiFetch("/ai/sql", { method:"POST", body: JSON.stringify(body) }),
  aiExplainSQL:      (sql)      => apiFetch("/ai/explain-sql", { method:"POST", body: JSON.stringify({ sql }) }),
  aiLineage:         (t)        => apiFetch(`/ai/lineage/${encodeURIComponent(t)}`),
  // Health
  getHealth:         ()         => apiFetch("/health"),
  // Demo / local bootstrap
  getDemoStatus:     ()         => apiFetch("/demo/status"),
  bootstrapDemo:     ()         => apiFetch("/demo/bootstrap", { method:"POST" }),
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
  // Snowflake navigator
  navDatabases:      (id)       => apiFetch(`/snowflake/navigator/${id}/databases`),
  navSchemas:        (id,db)    => apiFetch(`/snowflake/navigator/${id}/schemas/${encodeURIComponent(db)}`),
  navTables:         (id,db,sch)=> apiFetch(`/snowflake/navigator/${id}/tables/${encodeURIComponent(db)}/${encodeURIComponent(sch)}`),
  navDescribe:       (id,db,sch,t)=> apiFetch(`/snowflake/navigator/${id}/describe/${encodeURIComponent(db)}/${encodeURIComponent(sch)}/${encodeURIComponent(t)}`),
  navPreview:        (id,db,sch,t,limit=50)=> apiFetch(`/snowflake/navigator/${id}/preview/${encodeURIComponent(db)}/${encodeURIComponent(sch)}/${encodeURIComponent(t)}?limit=${limit}`),
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
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&family=Sora:wght@500;600;700;800&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#09111d;--bg2:#0f1a2b;--bg3:#15243a;
    --border:#223651;--border2:#2f4667;
    --text:#ecf2fb;--text2:#9cb0cb;--text3:#617897;
    --accent:#17c6ff;--accent2:#0a8fbf;
    --green:#00E5A0;--yellow:#FFB800;--red:#FF4560;
    --purple:#7C5CFF;--orange:#FF6B35;
    --font-d:'Inter',sans-serif;--font-h:'Sora',sans-serif;--font-m:'JetBrains Mono',monospace;
    --r:8px;--rl:14px;
  }
  /* ── Light mode ───────────────────────────────────── */
  .theme-light{
    --bg:#F6F8FB;--bg2:#FFFFFF;--bg3:#F1F4F9;
    --border:#E1E6EE;--border2:#D5DCE5;
    --text:#0F1A2C;--text2:#3C4A5C;--text3:#6B7A8F;
    --accent:#0066CC;--accent2:#003D7A;
    --green:#047857;--yellow:#B45309;--red:#B91C1C;
    --purple:#6D28D9;--orange:#EA580C;
  }
  .theme-light body,.theme-light{background:#F6F8FB}
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
  .nav-lbl{font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text3);padding:0 10px;margin-bottom:5px;font-family:var(--font-m)}
  .nav-item{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:var(--r);cursor:pointer;transition:all .15s;font-size:13px;font-weight:500;color:var(--text2);margin-bottom:2px;border:1px solid transparent}
  .nav-item:hover{background:var(--bg3);color:var(--text)}
  .nav-item.active{background:rgba(0,212,255,.08);color:var(--accent);border-color:rgba(0,212,255,.15)}
  .nav-item .ni{width:16px;text-align:center;font-size:13px;flex-shrink:0}
  .nbadge{margin-left:auto;background:var(--accent);color:var(--bg);font-size:9px;font-weight:700;padding:2px 6px;border-radius:20px;font-family:var(--font-m)}
  .nbadge.warn{background:var(--yellow)}.nbadge.err{background:var(--red)}
  .sidebar-bot{padding:14px 10px;border-top:1px solid var(--border)}
  .sdot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);display:inline-block;margin-right:6px}
  .main{margin-left:240px;flex:1;display:flex;flex-direction:column;min-height:100vh}
  .topbar{height:58px;background:rgba(15,26,43,.85);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 24px;gap:14px;position:sticky;top:0;z-index:50;backdrop-filter:blur(8px)}
  .topbar-title{font-size:15px;font-weight:800;flex:1;font-family:var(--font-h)}
  .topbar-sub{font-size:11px;color:var(--text3);font-family:var(--font-m)}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:var(--r);font-size:12px;font-weight:700;letter-spacing:.3px;cursor:pointer;border:none;transition:all .15s;font-family:var(--font-d)}
  .btn-primary{background:var(--accent);color:#041220}.btn-primary:hover{background:#4bd8ff;box-shadow:0 8px 18px rgba(23,198,255,.28)}
  .btn-ghost{background:transparent;color:var(--text2);border:1px solid var(--border2)}.btn-ghost:hover{background:var(--bg3);color:var(--text)}
  .btn-danger{background:rgba(255,69,96,.1);color:var(--red);border:1px solid rgba(255,69,96,.2)}.btn-danger:hover{background:rgba(255,69,96,.2)}
  .btn-purple{background:var(--purple);color:#fff}.btn-purple:hover{background:#9470FF;box-shadow:0 0 16px rgba(124,92,255,.3)}
  .btn-sm{padding:5px 10px;font-size:11px}.btn-xs{padding:3px 8px;font-size:10px}.btn-icon{padding:6px}
  .btn:disabled{opacity:.4;cursor:not-allowed}
  .page{padding:24px;flex:1}
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
  .card{background:linear-gradient(180deg,rgba(17,30,49,.96),rgba(13,24,40,.96));border:1px solid var(--border);border-radius:var(--rl);overflow:hidden;box-shadow:0 10px 28px rgba(4,10,18,.28)}
  .card-header{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
  .card-title{font-size:13px;font-weight:700}
  table{width:100%;border-collapse:collapse}
  thead th{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text3);padding:10px 14px;text-align:left;font-family:var(--font-m);border-bottom:1px solid var(--border);background:var(--bg3)}
  tbody tr{border-bottom:1px solid var(--border);transition:background .1s}
  tbody tr:last-child{border-bottom:none}
  tbody tr:hover{background:rgba(255,255,255,.012)}
  tbody td{padding:11px 14px;font-size:12px;color:var(--text2);vertical-align:middle}
  .td-main{color:var(--text);font-weight:500;font-size:13px}
  .td-mono{font-family:var(--font-m);font-size:11px}
  .badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;font-family:var(--font-m)}
  .bg{background:rgba(0,229,160,.12);color:var(--green);border:1px solid rgba(0,229,160,.2)}
  .by{background:rgba(255,184,0,.12);color:var(--yellow);border:1px solid rgba(255,184,0,.2)}
  .br{background:rgba(255,69,96,.12);color:var(--red);border:1px solid rgba(255,69,96,.2)}
  .bb{background:rgba(0,212,255,.12);color:var(--accent);border:1px solid rgba(0,212,255,.2)}
  .bp{background:rgba(124,92,255,.12);color:var(--purple);border:1px solid rgba(124,92,255,.2)}
  .bgr{background:rgba(138,155,181,.1);color:var(--text3);border:1px solid var(--border)}
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
  .tabs{display:flex;gap:1px;border-bottom:1px solid var(--border);padding:0 18px}
  .tab{padding:10px 14px;font-size:12px;font-weight:600;color:var(--text3);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s;margin-bottom:-1px}
  .tab:hover{color:var(--text)}.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
  .log-row{display:grid;grid-template-columns:150px 55px 150px 1fr auto;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);font-size:11px;transition:background .1s}
  .log-row:hover{background:rgba(255,255,255,.012)}
  .ai-panel{background:linear-gradient(135deg,#0B1525,#0F1C35);border:1px solid rgba(124,92,255,.2);border-radius:var(--rl);padding:20px;margin-bottom:20px;position:relative;overflow:hidden}
  .ai-chip{background:rgba(124,92,255,.1);border:1px solid rgba(124,92,255,.2);color:var(--purple);padding:4px 10px;border-radius:20px;font-size:11px;cursor:pointer;transition:all .15s}
  .ai-chip:hover{background:rgba(124,92,255,.2)}
  .two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}
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
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}.pulse{animation:pulse 2s infinite}
  @keyframes spin{to{transform:rotate(360deg)}}.spin{animation:spin .7s linear infinite;display:inline-block}
  .flex{display:flex}.fac{align-items:center}.fjb{justify-content:space-between}.gap2{gap:8px}.gap3{gap:12px}
  .mt2{margin-top:8px}.mt3{margin-top:12px}.mt4{margin-top:16px}.mb3{margin-bottom:12px}.mb4{margin-bottom:16px}.mb5{margin-bottom:20px}
  .text-accent{color:var(--accent)}.text-green{color:var(--green)}.text-red{color:var(--red)}.text-muted{color:var(--text3);font-size:12px}
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
  };
  const [cls, lbl] = map[status] || ["bgr",""];
  return <span className={`badge ${cls}`}>{lbl || status?.charAt(0) + status?.slice(1).toLowerCase().replace(/_/g," ")}</span>;
}

function HealthDot({ health }) {
  const c = { healthy:"var(--green)", warn:"var(--yellow)", failed:"var(--red)" }[health] || "var(--text3)";
  return <span style={{ width:8,height:8,borderRadius:"50%",background:c,boxShadow:`0 0 5px ${c}`,display:"inline-block" }} />;
}

function Spinner() { return <span className="spin">↻</span>; }
function Loading() { return <div style={{ padding:40, textAlign:"center", color:"var(--text3)", fontSize:13 }}><Spinner /> Loading…</div>; }
function ErrMsg({ msg }) { return <div className="alert-err">⚠ {msg}</div>; }

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
  const { data: jobs,  loading: jl } = useApi(() => api.getJobs({ limit: 5 }), []);
  const { data: conns, loading: cl } = useApi(() => api.getConnections(), []);
  const { data: stats, loading: sl } = useApi(() => api.getJobStats(), []);
  const { data: health } = useApi(() => api.getHealth(), []);

  const totalGB    = stats?.total_gb || 0;
  const totalJobs  = stats?.total_jobs || 0;
  const totalConns = conns?.length || 0;
  const recentJobs = (jobs || []).filter(j => !(j?.name || "").startsWith("Demo · "));

  return (
    <div className="page">
      <div className="hero">
        <div className="hero-tag">UMA Platform</div>
        <div className="hero-title">Unified Migration Accelerator<br/>for Snowflake</div>
        <div className="hero-desc">Orchestrate any-source → Snowflake migration with managed ingestion, real-time monitoring, and AI-assisted transformation — self-hosted on your cloud.</div>
        <div className="hero-actions">
          <button className="btn btn-primary" onClick={() => setPage("jobs")}>Manage Jobs</button>
          <button className="btn btn-ghost"   onClick={() => setPage("connections")}>Configure Sources</button>
        </div>
        <div className="hero-stats">
          <div><div className="hs-val">{totalConns}</div><div className="hs-lbl">Connections</div></div>
          <div><div className="hs-val">{totalJobs}</div><div className="hs-lbl">Total Jobs</div></div>
          <div><div className="hs-val">{totalGB.toFixed(1)} GB</div><div className="hs-lbl">Data Migrated</div></div>
          <div><div className="hs-val" style={{ color: health ? "var(--green)" : "var(--red)" }}>{health ? "Online" : "—"}</div><div className="hs-lbl">API Status</div></div>
        </div>
      </div>

      <div className="stats-grid">
        {[
          { label:"Total Jobs",     val: totalJobs,          change:"all time",        icon:"⚡", col:"var(--accent)" },
          { label:"Succeeded",      val: jobs?.filter(j=>j.status==="SUCCEEDED").length||0, change:"recent", icon:"✅", col:"var(--green)" },
          { label:"Data Migrated",  val: `${totalGB} GB`,    change:"across all jobs", icon:"📦", col:"var(--yellow)" },
          { label:"Connections",    val: totalConns,         change:"active sources",  icon:"🔗", col:"var(--purple)" },
        ].map(s => (
          <div className="stat-card" key={s.label} style={{ "--al": s.col }}>
            <div className="stat-icon">{s.icon}</div>
            <div className="stat-label">{s.label}</div>
            <div className="stat-value" style={{ color: s.col }}>{sl || jl ? "…" : s.val}</div>
            <div className="stat-change">{s.change}</div>
          </div>
        ))}
      </div>

      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Recent Jobs</div>
            <button className="btn btn-ghost btn-sm" onClick={() => setPage("jobs")}>View all →</button>
          </div>
          {jl ? <Loading /> : !recentJobs.length ? <div className="empty"><div className="empty-icon">⚡</div><div className="empty-msg">No jobs yet. Create one to get started.</div></div> : (
            <table>
              <thead><tr><th>Job</th><th>Source</th><th>Status</th><th>Data</th></tr></thead>
              <tbody>
                {recentJobs.slice(0,6).map(j => (
                  <tr key={j.id}>
                    <td className="td-main" style={{ maxWidth:160, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{j.name}</td>
                    <td><SourcePill type={j.source_connection_type || "bigquery"} /></td>
                    <td><StatusBadge status={j.status} /></td>
                    <td className="td-mono">{j.total_bytes_gb || 0} GB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Connections</div>
            <button className="btn btn-ghost btn-sm" onClick={() => setPage("connections")}>Manage →</button>
          </div>
          {cl ? <Loading /> : !conns?.length ? <div className="empty"><div className="empty-icon">🔗</div><div className="empty-msg">No connections yet.</div></div> : (
            <table>
              <thead><tr><th>Name</th><th>Type</th><th>Health</th></tr></thead>
              <tbody>
                {conns.slice(0,6).map(c => (
                  <tr key={c.id}>
                    <td className="td-main">{c.name}</td>
                    <td><SourcePill type={c.type} /></td>
                    <td><div style={{ display:"flex",alignItems:"center",gap:6 }}><HealthDot health={c.health} /><span style={{ fontSize:11, color: c.health==="healthy"?"var(--green)":"var(--yellow)", textTransform:"capitalize" }}>{c.health}</span></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div style={{ marginTop:18 }}>
        <div className="ai-panel">
          <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:3 }}>
            <span style={{ fontSize:17 }}>✦</span>
            <span style={{ fontSize:13, fontWeight:700, color:"var(--purple)" }}>UMA AI Copilot</span>
            <span className="badge bp" style={{ marginLeft:4, fontSize:9 }}>LIVE</span>
          </div>
          <div style={{ fontSize:12, color:"var(--text2)", marginBottom:10 }}>Ask anything about your data — generate SQL, explain job failures, validate row counts.</div>
          <div style={{ display:"flex", flexWrap:"wrap", gap:7 }}>
            {["Why did my last job fail?","Generate COPY INTO for accounts","Show row count parity","Suggest indexes for tickets table"].map(c=>(
              <span key={c} className="ai-chip" onClick={() => setPage("ai")}>{c}</span>
            ))}
          </div>
        </div>
      </div>
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

  const filtered = (jobs||[])
    .filter(j => !(j?.name || "").startsWith("Demo · "))
    .filter(j =>
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
    <div className="page">
      <div style={{ marginBottom:18 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← Back to Jobs</button>
      </div>
      <div className="flex fac fjb mb4">
        <div>
          <div style={{ fontSize:18, fontWeight:800, marginBottom:7 }}>{job.name}</div>
          <div style={{ display:"flex", gap:7 }}>
            <StatusBadge status={job.status} />
            <span className="badge bb badge-dot">Executed</span>
            <span className="badge bgr">Phase: {job.phase}</span>
            <span className="badge bgr">Strategy: {job.load_strategy}</span>
          </div>
        </div>
        <div style={{ display:"flex", gap:7 }}>
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
      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:12, marginBottom:16 }}>
        {[
          ["Export Duration",  fmt_duration(job.export_duration_s), phase===0?"var(--accent)":"var(--green)"],
          ["Stage Duration",   fmt_duration(job.stage_duration_s),  phase===1?"var(--accent)":"phase>1?'var(--green)':'var(--text3)'"],
          ["Snowflake Load",   fmt_duration(job.load_duration_s),   phase===2&&job.status==="RUNNING"?"var(--accent)":"var(--green)"],
        ].map(([l,v,c]) => (
          <div key={l} style={{ background:"var(--bg3)", border:"1px solid var(--border)", borderRadius:"var(--r)", padding:14 }}>
            <div style={{ fontSize:10, fontWeight:700, letterSpacing:1, textTransform:"uppercase", color:"var(--text3)", fontFamily:"var(--font-m)", marginBottom:5 }}>{l}</div>
            <div style={{ fontSize:20, fontWeight:800, fontFamily:"var(--font-m)", color:c }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Pipeline */}
      <div className="card mb4" style={{ marginBottom:14 }}>
        <div className="card-header"><div className="card-title">Pipeline</div></div>
        <div style={{ padding:"16px 20px" }}>
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
          <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:14, marginTop:14 }}>
            {[
              ["Rows Exported",    (job.total_rows_exported||0).toLocaleString()],
              ["Data Volume",      fmt_bytes(job.total_bytes)],
              ["Tasks",            `${job.tasks_succeeded}/${job.task_count} succeeded · ${job.tasks_failed} failed`],
            ].map(([l,v]) => (
              <div key={l}><div style={{ fontSize:10,fontWeight:700,color:"var(--text3)",letterSpacing:1,textTransform:"uppercase",fontFamily:"var(--font-m)",marginBottom:3 }}>{l}</div><div style={{ fontSize:13,fontWeight:600 }}>{v}</div></div>
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
                <input className="fi" placeholder="e.g. salesforce_full_load_prod"
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
                  <input className="fi" value={taskDraft.source_dataset} onChange={e=>setTaskDraft({...taskDraft,source_dataset:e.target.value})} placeholder="public" />
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
  const [viewing, setViewing] = useState(null);
  const [lastResult, setLastResult] = useState(null);

  const rows = conns || [];
  const filtered = rows.filter(c => {
    const matchSearch = !search.trim() || [c.name, c.description, c.type].filter(Boolean).join(" ").toLowerCase().includes(search.toLowerCase());
    const matchType = typeFilter === "all" || c.type === typeFilter;
    const matchHealth = healthFilter === "all" || c.health === healthFilter;
    return matchSearch && matchType && matchHealth;
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
                <div style={{ display:"flex", gap:5 }}>
                  <button className="btn btn-ghost btn-sm" onClick={()=>handleTest(c)} disabled={testing[c.id]}>
                    {testing[c.id] ? <Spinner/> : "Test"}
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={()=>openDetails(c.id)}>View</button>
                  <button className="btn btn-ghost btn-sm" onClick={()=>handleEdit(c.id)}>Edit</button>
                  <button className="btn btn-danger btn-icon btn-sm" onClick={()=>handleDelete(c.id)}>🗑</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  );

  const handleTest = async (conn) => {
    setTest(t=>({...t,[conn.id]:true}));
    try {
      const r = await api.testConnection(conn.id);
      setLastResult({ connection: conn, result: r });
    } catch (e) {
      setLastResult({ connection: conn, result: { success:false, error:e.message, diagnostic:e.message } });
    }
    setTest(t=>({...t,[conn.id]:false}));
    refetch();
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
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>Connections</div>
          <div className="text-muted mt2">Manage source credentials and Snowflake targets with live health checks and masked configuration details.</div>
        </div>
        <button className="btn btn-primary" onClick={()=>setNew(true)}>+ New Connection</button>
      </div>

      <div className="stats-grid">
        <div className="stat-card"><div className="stat-label">Connections</div><div className="stat-value">{stats.total}</div><div className="stat-change">registered endpoints</div></div>
        <div className="stat-card" style={{'--al':'var(--accent)'}}><div className="stat-label">Sources</div><div className="stat-value text-accent">{stats.sources}</div><div className="stat-change">usable as sources</div></div>
        <div className="stat-card" style={{'--al':'var(--purple)'}}><div className="stat-label">Targets</div><div className="stat-value">{stats.targets}</div><div className="stat-change">usable as targets</div></div>
        <div className="stat-card" style={{'--al':'var(--green)'}}><div className="stat-label">Healthy</div><div className="stat-value text-green">{stats.healthy}</div><div className="stat-change">ready to use</div></div>
      </div>

      <div className="card">
        <div className="filter-bar">
          <div className="sw"><span className="si">🔍</span><input placeholder="Search connections…" value={search} onChange={e=>setSearch(e.target.value)} /></div>
          <select value={typeFilter} onChange={e=>setTypeFilter(e.target.value)}><option value="all">All Types</option>{SRC.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <select value={healthFilter} onChange={e=>setHealthFilter(e.target.value)}><option value="all">All Health</option><option value="healthy">Healthy</option><option value="failed">Failed</option><option value="warn">Warning</option><option value="unknown">Unknown</option></select>
        </div>
        {error && <ErrMsg msg={error} />}
        {loading ? <Loading /> : !filtered.length ? (
          <div className="empty"><div className="empty-icon">🔗</div><div className="empty-msg">{rows.length ? 'No connections match your filters.' : 'No connections yet. Add your first source or Snowflake target.'}</div></div>
        ) : (
          <div style={{ display:"grid", gap:18 }}>
            <section>
              <div className="settings-title">Source Connections</div>
              <ConnectionTable rows={sourceRows} empty="No source connections match your filters." />
            </section>
            <section>
              <div className="settings-title">Target Connections</div>
              <ConnectionTable rows={targetRows} empty="No target connections match your filters." />
            </section>
          </div>
        )}
      </div>

      {viewing && (
        <Modal title={`Connection Details — ${viewing.name}`} onClose={()=>setViewing(null)} width={780}>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <div>
              <div className="settings-title">Overview</div>
              <div style={{ display:'grid', gap:10 }}>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}>
                  <div className="text-muted">Type</div>
                  <div style={{ marginTop:6 }}><SourcePill type={viewing.type} /></div>
                </div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}>
                  <div className="text-muted">Role</div>
                  <div style={{ marginTop:6 }}><span className="badge bb" style={{ fontSize:9, textTransform:"uppercase" }}>{connRole(viewing)}</span></div>
                </div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}>
                  <div className="text-muted">Health</div>
                  <div style={{ marginTop:6, display:'flex', alignItems:'center', gap:8 }}><HealthDot health={viewing.health} /><span style={{ textTransform:'capitalize' }}>{viewing.health || 'unknown'}</span></div>
                </div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}>
                  <div className="text-muted">Last Tested</div>
                  <div style={{ marginTop:6, fontFamily:'var(--font-m)', fontSize:11 }}>{fmt_dt(viewing.last_tested)}</div>
                </div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}>
                  <div className="text-muted">Description</div>
                  <div style={{ marginTop:6, fontSize:12 }}>{viewing.description || '—'}</div>
                </div>
              </div>
            </div>
            <div>
              <div className="settings-title">Non-sensitive Config</div>
              {!Object.keys(viewing.config || {}).length ? <div className="empty" style={{ padding:24 }}><div className="empty-msg">No config captured.</div></div> : (
                <table>
                  <thead><tr><th>Key</th><th>Value</th></tr></thead>
                  <tbody>{Object.entries(viewing.config || {}).map(([k,v])=><tr key={k}><td className="td-main">{k}</td><td className="td-mono" style={{ fontSize:10 }}>{String(v)}</td></tr>)}</tbody>
                </table>
              )}
              <div className="settings-title" style={{ marginTop:14 }}>Credential Hints</div>
              {!Object.keys(viewing.credentials || {}).length ? <div className="empty" style={{ padding:24 }}><div className="empty-msg">No credential hints available.</div></div> : (
                <table>
                  <thead><tr><th>Field</th><th>Stored</th></tr></thead>
                  <tbody>{Object.entries(viewing.credentials || {}).map(([k,v])=><tr key={k}><td className="td-main">{k}</td><td className="td-mono" style={{ fontSize:10 }}>{String(v)}</td></tr>)}</tbody>
                </table>
              )}
            </div>
          </div>
          <div style={{ display:'flex', justifyContent:'flex-end', gap:8, marginTop:16 }}>
            <button className="btn btn-ghost" onClick={()=>handleEdit(viewing.id)}>Edit</button>
            <button className="btn btn-primary" onClick={()=>handleTest(viewing)}>Run Test</button>
          </div>
        </Modal>
      )}

      {lastResult && (
        <Modal title={`Connection Test — ${lastResult.connection.name}`} onClose={()=>setLastResult(null)} width={680}>
          <div className={lastResult.result?.success ? 'alert-ok' : 'alert-err'}>
            {lastResult.result?.success ? '✓ Connection successful' : `✗ ${lastResult.result?.diagnostic || 'Connection failed'}`}
          </div>
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

      {showNew && <NewConnectionModal onClose={()=>{ setNew(false); refetch(); }} />}
      {editing && <NewConnectionModal editing={editing} onClose={()=>{ setEditing(null); refetch(); }} />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// SNOWFLAKE DIAGNOSTIC PANEL
// Runs 7-step diagnostic: format → DNS → TCP → TLS → auth → role → warehouse.
// Shows per-step status with expandable detail. Downloadable JSON report for network teams.
// ══════════════════════════════════════════════════════════════
function SnowflakeDiagnosticPanel({ account, user, password, role, warehouse }) {
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
      const body = { account, user, password, role, warehouse };
      const r = await api.diagnoseSnowflake(body);
      setResult(r);
    } catch(e) {
      setResult({ ok: false, error: e.message });
    }
    setRunning(false);
  };

  const download = async () => {
    try {
      const body = { account, user, password, role, warehouse };
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

function NewConnectionModal({ onClose, editing }) {
  const isEdit = !!editing;
  const [type, setType]   = useState(editing?.type || "snowflake");
  const [form, setForm]   = useState({
    name: editing?.name || "",
    connection_role: editing?.connection_role || (editing?.type === "snowflake" ? "target" : "source"),
    description: editing?.description || "",
  });
  const [creds, setCreds] = useState({});  // Only fields user actually edits
  const [cfg, setCfg]     = useState(editing?.config || {});
  const [saving, setSave] = useState(false);
  const [testing, setTest]= useState(false);
  // Single status object — never show both error+success
  const [status, setStatus] = useState(null);  // { kind: "ok"|"err"|"info", msg, detail? }

  const set = (f,v) => { setForm(p=>({...p,[f]:v})); setStatus(null); };
  const sc  = (f,v) => { setCreds(p=>({...p,[f]:v})); setStatus(null); };
  const sg  = (f,v) => { setCfg(p=>({...p,[f]:v})); setStatus(null); };

  // On type change, clear per-type state
  const onTypeChange = (newType) => {
    setType(newType);
    setForm(p => ({ ...p, connection_role: newType === "snowflake" ? "target" : "source" }));
    setCreds({});
    setCfg({});
    setStatus(null);
  };

  const buildPayload = () => ({
    name: form.name,
    type,
    connection_role: form.connection_role,
    description: form.description,
    credentials: creds,
    config: cfg,
  });

  const handleTest = async () => {
    if (!form.name) { setStatus({ kind:"err", msg:"Please enter a connection name first" }); return; }
    setTest(true); setStatus(null);
    try {
      const r = await api.testCredentials(buildPayload());
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
        const payload = { name: form.name, description: form.description, config: cfg };
        payload.connection_role = form.connection_role;
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
            <div className="fr">
              <div className="fg"><label className="fl">Account Identifier</label><input className="fi" placeholder="orgname-accountname" value={cfg.account||""} onChange={e=>sg("account",e.target.value)} /><div className="fhint">Format: <code>orgname-accountname</code>, or <code>locator.region</code>. Not the full URL.</div></div>
              <div className="fg"><label className="fl">Warehouse</label><input className="fi" placeholder="COMPUTE_WH" value={cfg.warehouse||""} onChange={e=>sg("warehouse",e.target.value)} /></div>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Username</label><input className="fi" value={creds.user||""} onChange={e=>sc("user",e.target.value)} /></div>
              <div className="fg"><label className="fl">Password</label><input className="fi" type="password" placeholder={isEdit ? "(unchanged)" : ""} value={creds.password||""} onChange={e=>sc("password",e.target.value)} /></div>
            </div>
            <div className="fr">
              <div className="fg"><label className="fl">Database</label><input className="fi" placeholder="ANALYTICS_DB" value={cfg.database||""} onChange={e=>sg("database",e.target.value)} /></div>
              <div className="fg"><label className="fl">Role</label><input className="fi" placeholder="SYSADMIN" value={cfg.role||""} onChange={e=>sg("role",e.target.value)} /></div>
            </div>

            {/* Diagnostic panel */}
            <SnowflakeDiagnosticPanel
              account={cfg.account}
              user={creds.user}
              password={creds.password}
              role={cfg.role}
              warehouse={cfg.warehouse}
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
  const { data: tables, loading, error, refetch } = useApi(
    () => api.getTables(statusF?{status:statusF}:{}), [statusF]
  );
  const { data: stats } = useApi(() => api.getTableStats(), []);

  const filtered = (tables||[]).filter(t =>
    (!search || t.table.toLowerCase().includes(search.toLowerCase())) &&
    (!datasetF || t.dataset === datasetF)
  );
  const datasets = [...new Set((tables||[]).map(t=>t.dataset))];

  return (
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>Tables Command Center</div>
          <div className="text-muted mt2">Curate dataset scope, schema alignment, catalog standards</div>
        </div>
      </div>

      <div className="stats-grid mb4">
        {[
          ["Total Tables",  Object.values(stats||{}).reduce((a,b)=>a+b,0), "var(--accent)"],
          ["Succeeded",     (stats||{})["SUCCEEDED"]||0,  "var(--green)"],
          ["Running",       (stats||{})["RUNNING"]||0,    "var(--yellow)"],
          ["Failed",        (stats||{})["FAILED"]||0,     "var(--red)"],
        ].map(([l,v,c])=>(
          <div className="stat-card" key={l} style={{ "--al":c }}>
            <div className="stat-label">{l}</div>
            <div className="stat-value" style={{ fontSize:22,color:c }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="filter-bar">
          <div className="sw"><span className="si">🔍</span><input placeholder="Search tables…" value={search} onChange={e=>setS(e.target.value)} /></div>
          <select value={datasetF} onChange={e=>setD(e.target.value)}>
            <option value="">All Datasets</option>
            {datasets.map(d=><option key={d} value={d}>{d}</option>)}
          </select>
          <select value={statusF} onChange={e=>setSF(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="SUCCEEDED">Succeeded</option>
            <option value="RUNNING">Running</option>
            <option value="FAILED">Failed</option>
            <option value="PENDING">Pending</option>
          </select>
        </div>
        {error && <ErrMsg msg={error} />}
        {loading ? <Loading /> : !filtered.length ? (
          <div className="empty"><div className="empty-icon">🗂</div><div className="empty-msg">No tables yet. Run a migration job to populate this view.</div></div>
        ) : (
          <table>
            <thead><tr><th>Dataset</th><th>Target Schema</th><th>Table</th><th>Long Text</th><th>Rows</th><th>Size</th><th>Status</th></tr></thead>
            <tbody>
              {filtered.map((t,i)=>(
                <tr key={i}>
                  <td className="td-mono">{t.dataset}</td>
                  <td className="td-mono">{t.target_schema}</td>
                  <td className="td-main">{t.table}</td>
                  <td style={{ color:t.long_text_columns>0?"var(--yellow)":"var(--text3)" }}>{t.long_text_columns}</td>
                  <td className="td-mono">{(t.rows_exported||0).toLocaleString()}</td>
                  <td className="td-mono">{t.size}</td>
                  <td><StatusBadge status={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ─── Validation ───────────────────────────────────────────────
function ValidationPage() {
  const { data: rules, loading, error, refetch } = useApi(() => api.getValidationRules(), []);
  const [showNew, setNew]   = useState(false);
  const [showRecon, setRecon] = useState(false);
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

  return (
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>Validation Center</div>
          <div className="text-muted mt2">Source ↔ target reconciliation · Row count · Checksum · Schema · Null/duplicate · Freshness</div>
        </div>
        <div style={{ display:"flex", gap:8 }}>
          <button className="btn btn-ghost" onClick={()=>setRecon(true)}>↻ Reconcile Job</button>
          <button className="btn btn-primary" onClick={()=>setNew(true)}>+ Add Check</button>
        </div>
      </div>

      <div className="stats-grid mb4">
        {[["Passed",passed,"var(--green)"],["Failed",failed,"var(--red)"],["Running",running2,"var(--yellow)"],["Total",(rules||[]).length,"var(--accent)"]].map(([l,v,c])=>(
          <div className="stat-card" key={l} style={{ "--al":c }}>
            <div className="stat-label">{l}</div>
            <div className="stat-value" style={{ fontSize:22,color:c }}>{loading?"…":v}</div>
          </div>
        ))}
      </div>

      <div className="card">
        {error && <ErrMsg msg={error} />}
        {loading ? <Loading /> : !rules?.length ? (
          <div className="empty"><div className="empty-icon">✓</div><div className="empty-msg">No validation rules yet. Use “Reconcile Job” to auto-create row-count checks for every table in a job.</div></div>
        ) : (
          <table>
            <thead><tr><th>Name</th><th>Table</th><th>Type</th><th>Source</th><th>Target</th><th>Delta</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead>
            <tbody>
              {rules.map(r=>(
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
            <input className="fi" placeholder="ANALYTICS_DB.RAW.users" value={form.target_table} onChange={e=>set("target_table",e.target.value)} />
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
                  <input className="fi" placeholder="public" value={form.source_dataset} onChange={e=>set("source_dataset",e.target.value)} />
                </div>
                <div className="fg">
                  <label className="fl">Source Table</label>
                  <input className="fi" placeholder="users" value={form.source_table} onChange={e=>set("source_table",e.target.value)} />
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
  const [messages, setMessages] = useState([
    { role:"assistant", content:"Hello! I'm UMA AI — your Snowflake migration copilot. Ask me to explain job failures, generate COPY INTO statements, check row parity, or anything about your data pipeline." }
  ]);
  const [query, setQuery]   = useState("");
  const [loading, setLoad]  = useState(false);
  const endRef = useRef(null);

  const suggestions = [
    "Why did my last job fail?",
    "Generate COPY INTO for salesforce.accounts",
    "Show row count parity query",
    "What tables have long text column issues?",
    "Suggest Snowflake indexes for tickets table",
    "Explain CDC vs full load strategies",
  ];

  const send = async (text) => {
    const msg = text || query;
    if (!msg.trim() || loading) return;
    setQuery("");
    const newMessages = [...messages, { role:"user", content:msg }];
    setMessages(newMessages);
    setLoad(true);
    try {
      const res = await api.aiChat(newMessages.map(m=>({ role:m.role, content:m.content })));
      setMessages(prev=>[...prev, { role:"assistant", content:res.reply }]);
    } catch(e) {
      setMessages(prev=>[...prev, { role:"assistant", content:`Error: ${e.message}` }]);
    }
    setLoad(false);
  };

  useEffect(() => { endRef.current?.scrollIntoView({ behavior:"smooth" }); }, [messages, loading]);

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"calc(100vh - 58px)" }}>
      <div style={{ padding:"18px 24px 0", borderBottom:"1px solid var(--border)", background:"var(--bg2)" }}>
        <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:3 }}>
          <span style={{ fontSize:18 }}>✦</span>
          <span style={{ fontSize:15, fontWeight:800 }}>UMA AI Copilot</span>
          <span className="badge bp" style={{ fontSize:9 }}>LIVE · OpenAI</span>
        </div>
        <div style={{ fontSize:11, color:"var(--text3)", paddingBottom:14 }}>Context-aware across all your jobs, connections, and migration history</div>
      </div>

      <div style={{ flex:1, overflowY:"auto", padding:"20px 24px", display:"flex", flexDirection:"column", gap:14 }}>
        {messages.map((m,i)=>(
          <div key={i} style={{ display:"flex", gap:10, flexDirection:m.role==="user"?"row-reverse":"row" }}>
            <div style={{ width:28,height:28,borderRadius:"50%",background:m.role==="user"?"var(--accent)":"var(--purple)",display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,fontWeight:800,color:m.role==="user"?"var(--bg)":"#fff",flexShrink:0 }}>
              {m.role==="user"?"U":"✦"}
            </div>
            <div style={{ background:m.role==="user"?"rgba(0,212,255,.07)":"var(--bg2)", border:`1px solid ${m.role==="user"?"rgba(0,212,255,.18)":"var(--border)"}`, borderRadius:"var(--rl)", padding:"11px 14px", maxWidth:"74%", fontSize:13, lineHeight:1.65, color:"var(--text)", whiteSpace:"pre-wrap" }}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display:"flex", gap:10 }}>
            <div style={{ width:28,height:28,borderRadius:"50%",background:"var(--purple)",display:"flex",alignItems:"center",justifyContent:"center",fontSize:13 }}>✦</div>
            <div style={{ background:"var(--bg2)", border:"1px solid var(--border)", borderRadius:"var(--rl)", padding:"11px 14px" }}>
              <span className="pulse" style={{ color:"var(--purple)" }}>Thinking…</span>
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
            placeholder="Ask about jobs, generate SQL, explain failures…"
            value={query} onChange={e=>setQuery(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&!e.shiftKey&&send()}
          />
          <button className="btn btn-purple" onClick={()=>send()} disabled={loading || !query.trim()}>
            {loading?<Spinner/>:"→ Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Scheduler ────────────────────────────────────────────────

function SchedulerPage() {
  const { data: overview, refetch: refetchOverview } = useApi(() => api.getSyncOverview().catch(()=>null), []);
  const { data: profiles, loading, refetch } = useApi(() => api.getSyncProfiles().catch(()=>[]), []);
  const { data: templates } = useApi(() => api.getSyncTemplates().catch(()=>[]), []);
  const { data: connections } = useApi(() => api.getConnections().catch(()=>[]), []);
  const [showNew, setShowNew] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [op, setOp] = useState("");
  const [draft, setDraft] = useState({ name:"", source_connection_id:"", dest_connection_id:"", mode:"incremental", cadence:"0 * * * *", schema_drift_policy:"warn", destination_mode:"internal" });
  const { data: runs, refetch: refetchRuns } = useApi(() => selectedId ? api.getSyncRuns(selectedId).catch(()=>[]) : Promise.resolve([]), [selectedId]);

  useEffect(() => {
    if (!selectedId && profiles?.length) setSelectedId(profiles[0].id);
    if (selectedId && profiles?.length && !profiles.some(p=>p.id === selectedId)) setSelectedId(profiles[0]?.id || "");
  }, [profiles, selectedId]);

  const refreshAll = async () => {
    await Promise.all([refetch(), refetchOverview(), refetchRuns()]);
  };

  const applyTemplate = (tpl) => {
    setDraft(d => ({ ...d, mode: tpl.mode, cadence: tpl.cadence, schema_drift_policy: tpl.schema_drift_policy || d.schema_drift_policy, destination_mode: tpl.destination_mode || d.destination_mode }));
  };

  const createProfile = async () => {
    try {
      const created = await api.createSyncProfile(draft);
      setShowNew(false);
      setDraft({ name:"", source_connection_id:"", dest_connection_id:"", mode:"incremental", cadence:"0 * * * *", schema_drift_policy:"warn", destination_mode:"internal" });
      await refreshAll();
      if (created?.id) setSelectedId(created.id);
    } catch(e) { alert("Create sync failed: " + e.message); }
  };

  const runProfile = async (id) => {
    try {
      setOp(`run:${id}`);
      const res = await api.runSyncProfile(id);
      if (!res.success && res.error_message) alert(res.error_message);
      await refreshAll();
    } catch(e) { alert("Run failed: " + e.message); }
    finally { setOp(""); }
  };

  const toggleProfile = async (profile) => {
    try {
      setOp(`toggle:${profile.id}`);
      await api.updateSyncProfile(profile.id, { is_active: !profile.is_active });
      await refreshAll();
    } catch(e) { alert("Update failed: " + e.message); }
    finally { setOp(""); }
  };

  const deleteProfile = async (profile) => {
    if (!confirm(`Delete sync profile "${profile.name}"?`)) return;
    try {
      setOp(`delete:${profile.id}`);
      await api.deleteSyncProfile(profile.id);
      await refreshAll();
    } catch(e) { alert("Delete failed: " + e.message); }
    finally { setOp(""); }
  };

  const rows = profiles || [];
  const filtered = rows.filter(p => {
    const hay = [p.name, p.mode, p.source_connection_name, p.dest_connection_name].filter(Boolean).join(' ').toLowerCase();
    const searchOk = !search.trim() || hay.includes(search.toLowerCase());
    const statusOk = statusFilter === 'all' || (statusFilter === 'active' ? p.is_active : !p.is_active);
    return searchOk && statusOk;
  });
  const selected = rows.find(p => p.id === selectedId) || null;

  return (
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>Managed Syncs</div>
          <div className="text-muted mt2">Fivetran/Stitch-style sync profiles with cadence, drift policy, activation controls, and run history.</div>
        </div>
        <button className="btn btn-primary" onClick={()=>setShowNew(true)}>+ New Sync Profile</button>
      </div>

      <div className="stats-grid">
        <div className="stat-card"><div className="stat-label">Profiles</div><div className="stat-value">{overview?.profile_count ?? 0}</div><div className="stat-change">managed sync definitions</div></div>
        <div className="stat-card" style={{'--al':'var(--green)'}}><div className="stat-label">Active</div><div className="stat-value text-green">{overview?.active_profiles ?? 0}</div><div className="stat-change">running on cadence</div></div>
        <div className="stat-card" style={{'--al':'var(--accent)'}}><div className="stat-label">Runs</div><div className="stat-value">{overview?.run_count ?? 0}</div><div className="stat-change">executions recorded</div></div>
        <div className="stat-card" style={{'--al':'var(--orange)'}}><div className="stat-label">Rows Synced</div><div className="stat-value">{overview ? fmt_number(overview.rows_synced) : 0}</div><div className="stat-change">{overview?.next_run_at ? `next ${fmt_dt(overview.next_run_at)}` : 'no active cadence'}</div></div>
      </div>

      {showNew && (
        <Modal title="Create Sync Profile" onClose={()=>setShowNew(false)} width={860}>
          <div className="settings-title">Templates</div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:10, marginBottom:16 }}>
            {(templates||[]).map(t=>(
              <div key={t.id} onClick={()=>applyTemplate(t)} style={{ cursor:'pointer', background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'12px 14px' }}>
                <div style={{ fontSize:13, fontWeight:700 }}>{t.label}</div>
                <div className="text-muted mt2" style={{ fontFamily:'var(--font-m)' }}>{t.mode} · {t.cadence}</div>
              </div>
            ))}
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
            <Field label="Name"><input className="fi" value={draft.name} onChange={e=>setDraft(d=>({...d,name:e.target.value}))} placeholder="e.g. Salesforce → Snowflake incremental" /></Field>
            <Field label="Mode">
              <select className="fi" value={draft.mode} onChange={e=>setDraft(d=>({...d,mode:e.target.value}))}>
                <option value="full_refresh">full_refresh</option>
                <option value="incremental">incremental</option>
                <option value="cdc">cdc</option>
              </select>
            </Field>
            <Field label="Source Connection">
              <select className="fi" value={draft.source_connection_id} onChange={e=>setDraft(d=>({...d,source_connection_id:e.target.value}))}>
                <option value="">Select source</option>
                {(connections||[]).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Destination Connection">
              <select className="fi" value={draft.dest_connection_id} onChange={e=>setDraft(d=>({...d,dest_connection_id:e.target.value}))}>
                <option value="">Select destination</option>
                {(connections||[]).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
            <Field label="Cadence" hint={cron_hint(draft.cadence)}><input className="fi" value={draft.cadence} onChange={e=>setDraft(d=>({...d,cadence:e.target.value}))} /></Field>
            <Field label="Drift Policy">
              <select className="fi" value={draft.schema_drift_policy} onChange={e=>setDraft(d=>({...d,schema_drift_policy:e.target.value}))}>
                <option value="warn">warn</option><option value="auto_add">auto_add</option><option value="block">block</option>
              </select>
            </Field>
            <Field label="Destination Mode">
              <select className="fi" value={draft.destination_mode} onChange={e=>setDraft(d=>({...d,destination_mode:e.target.value}))}>
                <option value="internal">internal</option><option value="external_stage">external_stage</option><option value="iceberg">iceberg</option>
              </select>
            </Field>
          </div>
          <div style={{ display:"flex", justifyContent:"flex-end", gap:8, marginTop:16 }}>
            <button className="btn btn-ghost" onClick={()=>setShowNew(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={createProfile}>Create Sync Profile</button>
          </div>
        </Modal>
      )}

      <div className="two-col">
        <div className="card">
          <div className="card-header"><div className="card-title">Profiles</div></div>
          <div className="filter-bar">
            <div className="sw"><span className="si">🔍</span><input placeholder="Search profiles…" value={search} onChange={e=>setSearch(e.target.value)} /></div>
            <select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)}><option value="all">All statuses</option><option value="active">Active</option><option value="paused">Paused</option></select>
          </div>
          {loading ? <Loading/> : !filtered.length ? (
            <div className="empty"><div className="empty-icon">🔁</div><div className="empty-msg">{rows.length ? 'No sync profiles match your filters.' : 'No sync profiles yet.'}</div></div>
          ) : (
            <table>
              <thead><tr><th>Name</th><th>Mode</th><th>Cadence</th><th>State</th><th>Last Run</th></tr></thead>
              <tbody>
                {filtered.map(p=>(
                  <tr key={p.id} style={{ background:selectedId===p.id?'rgba(0,212,255,.04)':'transparent', cursor:'pointer' }} onClick={()=>setSelectedId(p.id)}>
                    <td>
                      <div className="td-main">{p.name}</div>
                      <div style={{ fontSize:10, color:'var(--text3)' }}>{p.source_connection_name || 'source'} → {p.dest_connection_name || 'target'}</div>
                    </td>
                    <td>{p.mode}</td>
                    <td className="td-mono" style={{ fontSize:10 }}>{p.cadence}</td>
                    <td>{p.is_active ? <span className="badge bg">Active</span> : <span className="badge bgr">Paused</span>}</td>
                    <td>{p.last_run ? <StatusBadge status={p.last_run.status} /> : <span className="text-muted">Never</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card" style={{ padding:18 }}>
          {!selected ? (
            <div className="empty"><div className="empty-icon">🕐</div><div className="empty-msg">Select a sync profile to inspect cadence, drift policy, and run history.</div></div>
          ) : (
            <>
              <div className="card-title" style={{ marginBottom:4 }}>{selected.name}</div>
              <div className="text-muted mb4">{selected.source_connection_name || 'source'} → {selected.dest_connection_name || 'destination'}</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:14 }}>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Mode</div><div style={{ marginTop:6 }}>{selected.mode}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">State</div><div style={{ marginTop:6 }}>{selected.is_active ? 'Active' : 'Paused'}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Cadence</div><div style={{ marginTop:6, fontFamily:'var(--font-m)', fontSize:11 }}>{selected.cadence}</div><div className="text-muted mt2">{cron_hint(selected.cadence)}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Next Run</div><div style={{ marginTop:6, fontFamily:'var(--font-m)', fontSize:11 }}>{fmt_dt(selected.next_run_at)}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Drift Policy</div><div style={{ marginTop:6 }}>{selected.schema_drift_policy}</div></div>
                <div style={{ background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'10px 12px' }}><div className="text-muted">Runs</div><div style={{ marginTop:6 }}>{selected.run_count} total · {selected.failed_runs} failed</div></div>
              </div>
              <div style={{ display:'flex', gap:8, marginBottom:14 }}>
                <button className="btn btn-primary" onClick={()=>runProfile(selected.id)} disabled={op===`run:${selected.id}`}>{op===`run:${selected.id}` ? <Spinner/> : 'Run now'}</button>
                <button className="btn btn-ghost" onClick={()=>toggleProfile(selected)} disabled={op===`toggle:${selected.id}`}>{selected.is_active ? 'Pause' : 'Resume'}</button>
                <button className="btn btn-danger" onClick={()=>deleteProfile(selected)} disabled={op===`delete:${selected.id}`}>Delete</button>
              </div>
              <div className="settings-title">Recent Runs</div>
              {!runs?.length ? <div className="empty" style={{ padding:20 }}><div className="empty-msg">No runs recorded yet.</div></div> : (
                <table>
                  <thead><tr><th>Status</th><th>Rows</th><th>Bytes</th><th>Started</th><th>Error</th></tr></thead>
                  <tbody>
                    {runs.slice(0,8).map(r=>(
                      <tr key={r.id}>
                        <td><StatusBadge status={r.status} /></td>
                        <td className="td-mono">{fmt_number(r.rows_synced)}</td>
                        <td className="td-mono">{fmt_bytes(r.bytes_synced)}</td>
                        <td className="td-mono" style={{ fontSize:10 }}>{fmt_dt(r.started_at)}</td>
                        <td style={{ fontSize:11, color:r.error_message?'var(--red)':'var(--text3)' }}>{r.error_message || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function WorkspacePage() {
  const { data: connections } = useApi(() => api.getConnections().catch(()=>[]), []);
  const snowflakeConnections = (connections||[]).filter(c => c.type === "snowflake");
  const [connectionId, setConnectionId] = useState("");
  const [database, setDatabase] = useState("");
  const [schemaName, setSchemaName] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [dbs, setDbs] = useState([]);
  const [schemas, setSchemas] = useState([]);
  const [tables, setTables] = useState([]);
  const [tableMeta, setTableMeta] = useState([]);
  const [preview, setPreview] = useState(null);

  const [sql, setSql] = useState(`-- UMA Workspace — Snowflake SQL Editor\nSELECT CURRENT_WAREHOUSE(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_SCHEMA();`);
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [aiQuestion, setAiQ] = useState("");
  const [generating, setGen] = useState(false);
  const [tab, setTab] = useState("editor");

  useEffect(() => {
    if (!connectionId && snowflakeConnections.length) setConnectionId(snowflakeConnections[0].id);
  }, [snowflakeConnections, connectionId]);

  useEffect(() => {
    if (!connectionId) return;
    api.navDatabases(connectionId).then(r => setDbs(r.items || [])).catch(()=>setDbs([]));
  }, [connectionId]);

  useEffect(() => {
    if (!connectionId || !database) return;
    api.navSchemas(connectionId, database).then(r => setSchemas(r.items || [])).catch(()=>setSchemas([]));
  }, [connectionId, database]);

  useEffect(() => {
    if (!connectionId || !database || !schemaName) return;
    api.navTables(connectionId, database, schemaName).then(r => setTables(r.items || [])).catch(()=>setTables([]));
  }, [connectionId, database, schemaName]);

  const inspectTable = async (table) => {
    setSelectedTable(table);
    try {
      const [desc, prev] = await Promise.all([
        api.navDescribe(connectionId, database, schemaName, table),
        api.navPreview(connectionId, database, schemaName, table, 50),
      ]);
      setTableMeta(desc.columns || []);
      setPreview(prev);
      setSql(`SELECT * FROM "${database}"."${schemaName}"."${table}" LIMIT 100;`);
      setTab("editor");
    } catch(e) { setError(e.message); }
  };

  const runQuery = async () => {
    setRunning(true); setError(""); setResults(null);
    try {
      const r = await api.snowflakeQuery({ sql, connection_id: connectionId, database, schema_name: schemaName, max_rows: 1000 });
      if (!r.success) { setError(r.error || "Query failed"); setResults(null); }
      else setResults(r);
      setTab("results");
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
    <div className="page">
      <div className="flex fac fjb mb5">
        <div>
          <div style={{ fontSize:17, fontWeight:800 }}>SQL Workspace</div>
          <div className="text-muted mt2">DBeaver-style Snowflake navigator, table preview, and AI-assisted querying.</div>
        </div>
      </div>

      <div className="ai-panel mb4">
        <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:10 }}>
          <span style={{ fontSize:15 }}>✦</span>
          <span style={{ fontSize:12, fontWeight:700, color:"var(--purple)" }}>AI SQL Generator</span>
          <span className="badge bp" style={{ fontSize:9 }}>Copilot</span>
        </div>
        <div style={{ display:"flex", gap:9 }}>
          <input
            style={{ flex:1, background:"var(--bg3)", border:"1px solid rgba(124,92,255,.3)", borderRadius:"var(--r)", padding:"9px 12px", color:"var(--text)", fontSize:12, fontFamily:"var(--font-d)", outline:"none" }}
            placeholder="Describe what you want to query in plain English…"
            value={aiQuestion} onChange={e=>setAiQ(e.target.value)}
            onKeyDown={e=>e.key==="Enter"&&generateSQL()}
          />
          <button className="btn btn-purple" onClick={generateSQL} disabled={generating || !aiQuestion.trim()}>
            {generating ? <Spinner/> : "✦ Generate"}
          </button>
        </div>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"280px 1fr 320px", gap:16 }}>
        <div className="card" style={{ padding:14 }}>
          <div className="settings-title">Navigator</div>
          <Field label="Connection">
            <select className="fi" value={connectionId} onChange={e=>{ setConnectionId(e.target.value); setDatabase(""); setSchemaName(""); setSelectedTable(""); }}>
              <option value="">Select Snowflake connection</option>
              {snowflakeConnections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Database">
            <select className="fi" value={database} onChange={e=>{ setDatabase(e.target.value); setSchemaName(""); setSelectedTable(""); }}>
              <option value="">Select database</option>
              {dbs.map(d=><option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
          <Field label="Schema">
            <select className="fi" value={schemaName} onChange={e=>{ setSchemaName(e.target.value); setSelectedTable(""); }}>
              <option value="">Select schema</option>
              {schemas.map(s=><option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
          <div className="divider" />
          <div style={{ fontSize:11, color:"var(--text3)", marginBottom:8, fontFamily:"var(--font-m)" }}>Tables</div>
          <div style={{ maxHeight:420, overflow:"auto" }}>
            {!tables.length ? <div className="text-muted" style={{ fontSize:12 }}>No tables loaded yet.</div> :
              tables.map(t=>(
                <div key={t} onClick={()=>inspectTable(t)}
                  style={{ padding:"8px 10px", marginBottom:4, border:"1px solid var(--border)", borderRadius:"var(--r)", cursor:"pointer", background:selectedTable===t?"rgba(0,212,255,.06)":"var(--bg3)" }}>
                  <div style={{ fontSize:12, fontWeight:600 }}>{t}</div>
                </div>
              ))
            }
          </div>
        </div>

        <div>
          <div className="tabs" style={{ paddingLeft:0 }}>
            <div className={`tab ${tab==="editor"?"active":""}`} onClick={()=>setTab("editor")}>Editor</div>
            <div className={`tab ${tab==="results"?"active":""}`} onClick={()=>setTab("results")}>Results</div>
          </div>
          {tab==="editor" && (
            <div className="card" style={{ borderRadius:"0 var(--r) var(--r) var(--r)", borderTop:"none" }}>
              <textarea className="sql-editor" style={{ borderRadius:0, borderLeft:"none", borderRight:"none", borderTop:"none" }}
                value={sql} onChange={e=>setSql(e.target.value)} rows={16} spellCheck={false} />
              {error && <div className="alert-err" style={{ margin:"10px 14px" }}>⚠ {error}</div>}
              <div style={{ display:"flex", alignItems:"center", gap:9, padding:"10px 14px" }}>
                <button className="btn btn-primary" onClick={runQuery} disabled={running || !connectionId}>
                  {running ? <Spinner/> : "▶ Run Query"}
                </button>
                <span style={{ marginLeft:"auto", fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>
                  {sql.split("\n").length} lines · {sql.length} chars
                </span>
              </div>
            </div>
          )}
          {tab==="results" && (
            <div className="card" style={{ borderRadius:"0 var(--r) var(--r) var(--r)", borderTop:"none" }}>
              {!results ? (
                <div className="empty"><div className="empty-icon">▶</div><div className="empty-msg">Run a query to see results</div></div>
              ) : results.error ? (
                <div className="alert-err" style={{ margin:14 }}>⚠ {results.error}</div>
              ) : (
                <>
                  <div style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", fontSize:11, color:"var(--text3)", display:"flex", gap:16 }}>
                    <span>{results.row_count} rows</span>
                    <span>{results.columns.length} columns</span>
                    <span>{results.execution_time_ms}ms</span>
                  </div>
                  <div className="result-table">
                    <table>
                      <thead><tr>{results.columns.map(c=><th key={c}>{c}</th>)}</tr></thead>
                      <tbody>
                        {results.rows.slice(0,100).map((row,i)=>(
                          <tr key={i}>{row.map((cell,j)=><td key={j} className="td-mono">{cell===null?<span style={{color:"var(--text3)"}}>NULL</span>:String(cell)}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        <div className="card" style={{ padding:14 }}>
          <div className="settings-title">Table Details</div>
          {!selectedTable ? <div className="text-muted" style={{ fontSize:12 }}>Select a table to preview structure and sample rows.</div> : (
            <>
              <div style={{ marginBottom:10 }}>
                <div style={{ fontSize:13, fontWeight:700 }}>{selectedTable}</div>
                <div style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>{database}.{schemaName}</div>
              </div>
              <div style={{ maxHeight:180, overflow:"auto", marginBottom:12 }}>
                <table>
                  <thead><tr><th>Column</th><th>Type</th></tr></thead>
                  <tbody>
                    {tableMeta.map((c, idx)=><tr key={idx}><td>{c.name}</td><td className="td-mono">{c.type}</td></tr>)}
                  </tbody>
                </table>
              </div>
              <div className="divider" />
              <div style={{ fontSize:11, color:"var(--text3)", marginBottom:8, fontFamily:"var(--font-m)" }}>Preview</div>
              {!preview ? <div className="text-muted" style={{ fontSize:12 }}>No preview loaded.</div> : (
                <div style={{ maxHeight:220, overflow:"auto" }}>
                  <table>
                    <thead><tr>{preview.columns.map(c=><th key={c}>{c}</th>)}</tr></thead>
                    <tbody>{preview.rows.slice(0,20).map((row, i)=><tr key={i}>{row.map((cell,j)=><td key={j} className="td-mono">{cell===null?"NULL":String(cell)}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
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
function SchemaDriftPage() {
  const { data: jobs, loading } = useApi(() => api.getJobs({ limit:50 }), []);
  const { data: connections } = useApi(() => api.getConnections(), []);
  const [mode, setMode] = useState("job");          // "job" | "adhoc"
  const [selected, setSelected] = useState(null);
  const [driftResults, setDrift] = useState([]);
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

  const checkDrift = async (job) => {
    setSelected(job); setCheck(true); setError(""); setDrift([]);
    try {
      const tasks = await api.getJobTasks(job.id);
      setDrift(tasks.map(t => ({
        table: t.source_table,
        target_schema: t.target_schema,
        long_text: t.long_text_columns || 0,
        status: t.status,
        has_drift: (t.long_text_columns || 0) > 0,
        drifts: (t.long_text_columns > 0) ? [
          { column_name: "Long text fields", drift_type: "long_text",
            note: `${t.long_text_columns} column${t.long_text_columns>1?"s":""} detected as VARCHAR(16777216) — may impact downstream query performance` }
        ] : [],
      })));
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
      setDrift([{
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
      }]);
    } catch(e) {
      setError(e.message);
    }
    setCheck(false);
  };

  const driftCount = driftResults.filter(d=>d.has_drift).length;

  return (
    <div className="page">
      <div style={{ fontSize:17, fontWeight:800, marginBottom:4 }}>Schema Drift Detection</div>
      <div className="text-muted mb5">Detect column additions, removals, and type changes between source and Snowflake</div>

      <div className="stats-grid mb4">
        {[
          ["Tables Checked",   driftResults.length,                                                                   "var(--accent)"],
          ["Drift Detected",   driftCount,                                                                            driftCount>0?"var(--yellow)":"var(--green)"],
          ["Auto-fixable",     driftResults.filter(d=>d.drifts.some(x=>x.drift_type==="added")).length,               "var(--green)"],
          ["Long Text Cols",   driftResults.reduce((a,d)=>a+d.long_text,0),                                           "var(--purple)"],
        ].map(([l,v,c])=>(
          <div key={l} className="stat-card" style={{ "--al":c }}>
            <div className="stat-label">{l}</div>
            <div className="stat-value" style={{ fontSize:22,color:c }}>{v}</div>
          </div>
        ))}
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
        <div style={{ display:"grid", gridTemplateColumns:"240px 1fr", gap:16 }}>
          <div className="card">
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
              <div className="fg"><label className="fl">Source Dataset / Schema</label><input className="fi" placeholder="e.g. finance_core" value={adhoc.source_dataset} onChange={e=>setAdhoc({...adhoc, source_dataset:e.target.value})} /></div>
              <div className="fg"><label className="fl">Source Table</label><input className="fi" placeholder="e.g. accounts" value={adhoc.source_table} onChange={e=>setAdhoc({...adhoc, source_table:e.target.value})} /></div>
            </div>

            <div className="divider" style={{ margin:"10px 0" }} />

            <div className="fg">
              <label className="fl">Snowflake Target</label>
              <select className="fi" value={adhoc.dest_connection_id} onChange={e=>setAdhoc({...adhoc, dest_connection_id:e.target.value})}>
                <option value="">— select snowflake —</option>
                {sfConns.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="fg"><label className="fl">Target Database</label><input className="fi" placeholder="ANALYTICS_DB" value={adhoc.target_database} onChange={e=>setAdhoc({...adhoc, target_database:e.target.value})} /></div>
            <div className="fr">
              <div className="fg"><label className="fl">Target Schema</label><input className="fi" placeholder="RAW" value={adhoc.target_schema} onChange={e=>setAdhoc({...adhoc, target_schema:e.target.value})} /></div>
              <div className="fg"><label className="fl">Target Table</label><input className="fi" placeholder="accounts" value={adhoc.target_table} onChange={e=>setAdhoc({...adhoc, target_table:e.target.value})} /></div>
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

function SettingsPage() {
  const { data: settings, loading, error, refetch } = useApi(() => api.getSettings(), []);
  const { data: history, refetch: refetchHistory } = useApi(() => api.getSettingsHistory().catch(()=>[]), []);
  const { data: health } = useApi(() => api.getHealth().catch(()=>null), []);
  const { data: connections } = useApi(() => api.getConnections().catch(()=>[]), []);
  const { data: registry } = useApi(() => api.getRegistryStatus().catch(()=>[]), []);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState("");
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

  if (loading || !form) return <Loading/>;
  if (error) return <ErrMsg msg={error} />;

  return (
    <div className="page">
      <div style={{ fontSize:17, fontWeight:800, marginBottom:4 }}>Settings</div>
      <div className="text-muted mb5">Operational controls, Snowflake defaults, alerting, AI provider configuration, and audit history.</div>

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
          <div className="settings-title">AI & Telemetry</div>
          {[
            ["provider","AI Provider"],["model","Primary Model"],["fallback_model","Secondary Model"],["budget_usd_limit","Budget Limit (USD)"],
          ].map(([key,label])=>(
            <div key={key} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"9px 0", borderBottom:"1px solid var(--border)" }}>
              <span style={{ fontSize:12, color:"var(--text2)" }}>{label}</span>
              <input className="fi" style={{ width:220, padding:"5px 9px", fontFamily:"var(--font-m)", fontSize:11 }}
                value={key === "provider" ? "openai" : (form.ai[key] ?? "")}
                onChange={e=>setAi(key, e.target.value)}
                readOnly={key === "provider"} />
            </div>
          ))}
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
            { label:"Demo Mode",   value:health?.demo_mode ? "Enabled" : "Disabled",                 icon:"🎭" },
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

  const handleDelete = async (u) => {
    if (u.id === currentUser?.id) { alert("Cannot delete yourself"); return; }
    if (!confirm(`Delete user ${u.email}?`)) return;
    try { await api.deleteUser(u.id); refetch(); }
    catch(e) { alert("Delete failed: " + e.message); }
  };

  if (currentUser?.role !== "admin") {
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
          <div className="text-muted mt2">Manage platform users and their permissions</div>
        </div>
        <button className="btn btn-primary" onClick={()=>setShowAdd(true)}>+ Add User</button>
      </div>

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
                      <button className="btn btn-ghost btn-sm" onClick={()=>setEditUser(u)}>Edit</button>
                      {u.id !== currentUser?.id && (
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

      {showAdd && <AddUserModal onClose={()=>{ setShowAdd(false); refetch(); }} />}
      {editUser && <EditUserModal user={editUser} onClose={()=>{ setEditUser(null); refetch(); }} />}
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
            <input className="fi" type="password" value={form.password} onChange={e=>setForm({...form, password:e.target.value})} placeholder="ChangeMeNow!2026" />
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
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);

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

  return (
    <div className="modal-ov" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">Edit {user.email}</div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {status && <div className="alert-err">✗ {status.msg}</div>}
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
  { section:"Platform", items:[
    { id:"dashboard",   label:"Dashboard",       icon:"⬡" },
    { id:"jobs",        label:"Migration Jobs",   icon:"⚡" },
    { id:"workspace",   label:"SQL Workspace",    icon:"⌨" },
  ]},
  { section:"Data", items:[
    { id:"connections", label:"Connections",      icon:"🔗" },
    { id:"tables",      label:"Tables",           icon:"🗂" },
    { id:"validation",  label:"Validation",       icon:"✓" },
    { id:"lineage",     label:"Lineage",          icon:"🔀" },
    { id:"drift",       label:"Schema Drift",     icon:"🔬" },
    { id:"scheduler",   label:"Scheduler",        icon:"🕐" },
  ]},
  { section:"Intelligence", items:[
    { id:"ai",          label:"AI Copilot",       icon:"✦", badge:"LIVE" },
  ]},
  { section:"Admin", items:[
    { id:"users",       label:"Users",            icon:"👥", adminOnly: true },
    { id:"settings",    label:"Settings",         icon:"⚙" },
  ]},
];

function AuthShell({ mode, setMode, form, setForm, loading, error, onLogin, onRegister, registrationInfo }) {
  const set = (field, value) => setForm(prev => ({ ...prev, [field]: value }));
  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState("");
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
      <div style={{ minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", padding:24, background:"var(--bg)" }}>
        <div style={{ width:"100%", maxWidth:560, background:"var(--bg2)", border:"1px solid var(--border)", borderRadius:"var(--rl)", padding:28, boxShadow:"0 18px 60px rgba(0,0,0,.35)" }}>
          <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:10 }}>
            <div className="logo-icon">U</div>
            <div>
              <div style={{ fontWeight:800 }}>UMA Platform</div>
              <div className="topbar-sub">Unified Migration Accelerator</div>
            </div>
          </div>
          <div style={{ fontSize:24, fontWeight:800, marginBottom:6 }}>{mode === "login" ? "Sign in" : "Create first admin"}</div>
          <div className="text-muted" style={{ marginBottom:18 }}>
            {mode === "login"
              ? "Use your admin credentials to access the platform."
              : "Bootstrap the first administrator account for this environment."}
          </div>
          <div style={{ display:"flex", gap:8, marginBottom:18 }}>
            <button className={`btn ${mode === "login" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("login")}>Login</button>
            <button className={`btn ${mode === "register" ? "btn-primary" : "btn-ghost"}`} onClick={() => setMode("register")}>First Admin</button>
          </div>
          {error && <ErrMsg msg={error} />}
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
          {mode === "register" && (
            <div className="fg">
              <label className="fl">Name</label>
              <input className="fi" value={form.name} onChange={e => set("name", e.target.value)} placeholder="Your Name" />
            </div>
          )}
          <div className="fg">
            <label className="fl">Password</label>
            <input className="fi" type="password" value={form.password} onChange={e => set("password", e.target.value)} placeholder="ChangeMeNow!2026" />
            {mode === "register" && <div className="fhint">Minimum 12 chars, uppercase, lowercase, digit, and special character.</div>}
          </div>
          <div style={{ display:"flex", justifyContent:"flex-end", marginTop:18 }}>
            <button className="btn btn-primary" onClick={mode === "login" ? onLogin : onRegister} disabled={loading}>
              {loading ? <Spinner /> : mode === "login" ? "Sign In" : "Create Admin"}
            </button>
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
  dashboard:"Overview", jobs:"Migration Jobs", tables:"Data Explorer", workspace:"SQL Workspace",
  connections:"Connections", validation:"Validation", lineage:"Data Lineage",
  drift:"Schema Drift", scheduler:"Managed Syncs", ai:"AI Copilot",
  users:"User Management", settings:"Settings",
};
const PAGE_SUBTITLES = {
  dashboard:"Snowflake migration control plane", jobs:"Build, run, and monitor migration jobs", tables:"Browse migrated tables and job-level table state", workspace:"Query and inspect Snowflake with AI assistance", connections:"Manage source and destination connectivity", validation:"Data quality and reconciliation rules", lineage:"Trace data movement across jobs and targets", drift:"Detect and remediate schema changes", scheduler:"Manage recurring syncs and run history", ai:"Copilot for SQL and migration operations", users:"Admin-only access control", settings:"Configuration, policies, alerts, and registry",
};

// ─── App ──────────────────────────────────────────────────────
export default function App() {
  const isVerifyRoute = typeof window !== "undefined" && window.location.pathname === "/verify-email";
  const [page, setPage] = useState("dashboard");
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ email:"", name:"", password:"" });
  const [authToken, setAuthToken] = useState(() => getStoredToken());
  const [authUser, setAuthUser] = useState(() => getStoredUser());
  const [authLoading, setAuthLoading] = useState(() => Boolean(getStoredToken()));
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authError, setAuthError] = useState("");
  const [registrationInfo, setRegistrationInfo] = useState(null);
  const [selectedSwitchUserId, setSelectedSwitchUserId] = useState("");
  const { data: health } = useApi(() => api.getHealth().catch(()=>null), []);
  const { data: switchableUsers } = useApi(() => authUser?.role === "admin" ? api.listUsers().catch(()=>[]) : Promise.resolve([]), [authUser?.role]);
  const availableImpersonations = (switchableUsers || []).filter(u => u?.is_active && u.id !== authUser?.id);

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
      setRegistrationInfo(resp);
      setAuthMode("login");
    } catch (e) {
      setAuthError(e.message);
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleLogout = () => {
    clearSession();
    setAuthToken("");
    setAuthUser(null);
    setAuthForm({ email:"", name:"", password:"" });
    setAuthMode("login");
  };

  const handleImpersonate = async (userId) => {
    if (!userId) return;
    try {
      const resp = await api.impersonateUser(userId);
      finishAuth(resp);
      setSelectedSwitchUserId("");
      setPage("dashboard");
    } catch (e) { alert("Switch user failed: " + e.message); }
  };

  // ─── Theme (light/dark) ───────────────────────────────────
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "dark";
    return window.localStorage.getItem("uma.theme") || "dark";
  });
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (typeof window !== "undefined") window.localStorage.setItem("uma.theme", next);
  };

  const pages = {
    dashboard:   <Dashboard setPage={setPage} />,
    jobs:        <JobsPage />,
    tables:      <TablesPage />,
    workspace:   <WorkspacePage />,
    connections: <ConnectionsPage />,
    validation:  <ValidationPage />,
    lineage:     <LineagePage />,
    drift:       <SchemaDriftPage />,
    scheduler:   <SchedulerPage />,
    ai:          <AIPage />,
    users:       <UsersPage currentUser={authUser} />,
    settings:    <SettingsPage currentUser={authUser} />,
  };

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
    return <AuthShell mode={authMode} setMode={setAuthMode} form={authForm} setForm={setAuthForm} loading={authSubmitting} error={authError} onLogin={handleLogin} onRegister={handleRegister} registrationInfo={registrationInfo} />;
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
              const visibleItems = section.items.filter(i => !i.adminOnly || authUser?.role === "admin");
              if (!visibleItems.length) return null;
              return (
                <div className="nav-section" key={section.section}>
                  <div className="nav-lbl">{section.section}</div>
                  {visibleItems.map(item=>(
                    <div key={item.id} className={`nav-item ${page===item.id?"active":""}`} onClick={()=>setPage(item.id)}>
                      <span className="ni">{item.icon}</span>
                      {item.label}
                      {item.badge && <span className="nbadge">{item.badge}</span>}
                    </div>
                  ))}
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
              <div className="topbar-sub">{`Snowflake-native · ${(health?.environment || "development")} · v${health?.version || "1.2.0"}${health?.build_sha ? ` · ${health.build_sha.slice(0,7)}` : ""}`}</div>
            </div>
            <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:10 }}>
              <button className="btn btn-ghost btn-sm btn-icon"
                onClick={toggleTheme}
                title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
                {theme === "dark" ? "☀" : "☾"}
              </button>
              <span style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-m)" }}>
                {health ? <span style={{ color:"var(--green)" }}>● Online</span> : <span style={{ color:"var(--red)" }}>● Offline</span>}
              </span>
              <div style={{ fontSize:11, color:"var(--text2)" }}>
                {authUser.email}
                <span className={`badge ${authUser.role==="admin"?"bp":authUser.role==="editor"?"bb":authUser.role==="operator"?"by":"bg"}`} style={{ fontSize:8, marginLeft:5, textTransform:"uppercase" }}>
                  {authUser.role}
                </span>
              </div>
              {authUser.role === "admin" && (
                <>
                  <select
                    className="fi"
                    style={{ width:220, padding:"6px 10px", fontSize:11 }}
                    value={selectedSwitchUserId}
                    onChange={e=>setSelectedSwitchUserId(e.target.value)}
                  >
                    <option value="">Switch user…</option>
                    {availableImpersonations.map(u => (
                      <option key={u.id} value={u.id}>{u.email} ({u.role})</option>
                    ))}
                  </select>
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={!selectedSwitchUserId}
                    onClick={()=>handleImpersonate(selectedSwitchUserId)}
                  >
                    Switch
                  </button>
                </>
              )}
              <button className="btn btn-ghost btn-sm" onClick={handleLogout}>Logout</button>
              <div title={authUser.name || authUser.email} style={{ width:28,height:28,borderRadius:"50%",background:"var(--accent)",display:"flex",alignItems:"center",justifyContent:"center",fontSize:12,fontWeight:800,color:"var(--bg)" }}>{(authUser.name || authUser.email || 'U').slice(0,1).toUpperCase()}</div>
            </div>
          </header>
          <div style={{ flex:1 }}>
            {pages[page]}
          </div>
        </div>
      </div>
    </>
  );
}
