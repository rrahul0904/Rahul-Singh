import React, { useMemo, useState } from "react";

const TONE = {
  active: { color: "#2563eb", label: "Active" },
  validated: { color: "#059669", label: "Validated" },
  review: { color: "#d97706", label: "Needs review" },
  blocked: { color: "#dc2626", label: "Blocked" },
  idle: { color: "#94a3b8", label: "Not started" },
};

function tone(status = "idle") {
  const key = String(status || "idle").toLowerCase();
  if (["complete", "completed", "success", "succeeded", "healthy", "validated"].includes(key)) return "validated";
  if (["failed", "error", "blocked", "critical"].includes(key)) return "blocked";
  if (["warning", "warn", "review", "requires_review", "needs_rework", "in_review"].includes(key)) return "review";
  if (["active", "running", "started"].includes(key)) return "active";
  return "idle";
}

function statusColor(status) {
  return TONE[tone(status)].color;
}

export function ProductMotionStyles() {
  return (
    <style>{`
      .uma-product-shell{display:grid;gap:18px}
      .uma-cockpit{position:relative;overflow:hidden;border:1px solid rgba(37,99,235,.14);border-radius:18px;background:linear-gradient(135deg,#ffffff 0%,#f8fbff 45%,#eef8fb 100%);box-shadow:0 18px 44px rgba(15,23,42,.08)}
      .uma-cockpit::before{content:"";position:absolute;inset:0;background:linear-gradient(rgba(14,165,233,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(14,165,233,.07) 1px,transparent 1px);background-size:44px 44px;mask-image:linear-gradient(90deg,transparent,black 12%,black 88%,transparent);pointer-events:none}
      .uma-cockpit-inner{position:relative;z-index:1;display:grid;grid-template-columns:minmax(320px,.95fr) minmax(360px,1.05fr);gap:18px;padding:24px;min-width:0}
      .uma-kicker{display:inline-flex;align-items:center;gap:8px;color:#0284c7;font:800 11px/1 var(--font-m);letter-spacing:.13em;text-transform:uppercase}
      .uma-kicker::before{content:"";width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 14px rgba(34,197,94,.65)}
      .uma-cockpit h1{max-width:12ch;margin:12px 0 10px;color:#0f2537;font:900 clamp(30px,3.2vw,42px)/1.04 var(--font-h);letter-spacing:0;overflow-wrap:normal}
      .uma-cockpit-copy{max-width:640px;color:#52697e;font-size:15px;line-height:1.6}
      .uma-cockpit-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
      .uma-action-card{margin-top:20px;padding:16px;border:1px solid rgba(37,99,235,.14);border-radius:16px;background:rgba(255,255,255,.74);backdrop-filter:blur(12px)}
      .uma-action-title{font-size:13px;font-weight:900;color:#0f2537}
      .uma-action-body{margin-top:5px;color:#64748b;font-size:12px;line-height:1.5}
      .uma-metric-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin-top:18px}
      .uma-metric{min-width:0;padding:12px;border:1px solid rgba(15,23,42,.08);border-radius:14px;background:#fff}
      .uma-metric-label{font:800 10px/1 var(--font-m);letter-spacing:.1em;text-transform:uppercase;color:#64748b}
      .uma-metric-value{margin-top:7px;font-size:clamp(19px,1.5vw,22px);line-height:1.08;font-weight:900;color:#0f2537;overflow-wrap:break-word}
      .uma-metric-note{margin-top:4px;color:#64748b;font-size:11px;line-height:1.35;overflow-wrap:anywhere}
      .uma-topology-card{position:relative;min-height:330px;border:1px solid rgba(37,99,235,.12);border-radius:16px;background:rgba(255,255,255,.72);box-shadow:inset 0 0 0 1px rgba(255,255,255,.65);overflow:hidden}
      .uma-topology-card::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 42% 42%,rgba(37,99,235,.12),transparent 32%),radial-gradient(circle at 78% 55%,rgba(20,184,166,.10),transparent 27%);pointer-events:none}
      .uma-topology-head{position:absolute;left:16px;top:14px;right:16px;z-index:3;display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
      .uma-topology-title{font-weight:900;color:#0f2537}
      .uma-topology-sub{margin-top:3px;font-size:11px;color:#64748b}
      .uma-object-pill{display:inline-flex;align-items:center;gap:7px;padding:5px 9px;border:1px solid rgba(37,99,235,.14);border-radius:999px;background:rgba(255,255,255,.75);font:800 10px/1 var(--font-m);color:#475569;text-transform:uppercase;letter-spacing:.08em}
      .uma-topology-svg{position:absolute;inset:0;width:100%;height:100%;z-index:1}
      .uma-topology-path{fill:none;stroke-width:1.8;stroke-linecap:round;stroke-dasharray:7 11;opacity:.78;animation:umaPathMove 18s linear infinite}
      .uma-topology-path.active{stroke:#2563eb;filter:drop-shadow(0 0 5px rgba(37,99,235,.35))}
      .uma-topology-path.validated{stroke:#059669;filter:drop-shadow(0 0 4px rgba(5,150,105,.28))}
      .uma-topology-path.review{stroke:#d97706;filter:drop-shadow(0 0 4px rgba(217,119,6,.30))}
      .uma-topology-path.blocked{stroke:#dc2626;stroke-width:2.4;filter:drop-shadow(0 0 5px rgba(220,38,38,.36))}
      .uma-flow-packet{filter:drop-shadow(0 0 8px currentColor);opacity:.86}
      .uma-topology-node{cursor:pointer;transition:opacity 160ms ease, transform 160ms ease}
      .uma-topology-node:hover{opacity:1}
      .uma-node-halo{opacity:.16;animation:umaHalo 2.4s ease-in-out infinite}
      .uma-node-core{fill:#fff;stroke-width:1.2;filter:drop-shadow(0 6px 12px rgba(15,23,42,.12))}
      .uma-topology-node-label{fill:#0f2537;font-family:var(--font-d);font-size:2.35px;font-weight:900;line-height:1}
      .uma-topology-node-type{fill:#64748b;font-family:var(--font-m);font-size:1.45px;font-weight:800;line-height:1;letter-spacing:.03em;text-transform:uppercase}
      .uma-node-chip{fill:rgba(255,255,255,.9);stroke:rgba(15,23,42,.08);stroke-width:.25}
      .uma-legend-line{position:absolute;left:16px;right:16px;bottom:14px;z-index:3;display:flex;flex-wrap:wrap;gap:8px}
      .uma-legend-line span{display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border:1px solid rgba(15,23,42,.08);border-radius:999px;background:rgba(255,255,255,.74);font-size:10px;color:#475569}
      .uma-legend-line i{width:8px;height:8px;border-radius:50%;display:inline-block}
      .uma-workbench{display:grid;grid-template-columns:minmax(310px,.72fr) minmax(0,1.28fr);gap:18px;align-items:start}
      .uma-workbench-panel{border:1px solid var(--border);border-radius:18px;background:var(--bg2);box-shadow:0 14px 40px rgba(15,23,42,.06);overflow:hidden}
      .uma-workbench-head{padding:16px 18px;border-bottom:1px solid var(--border);background:linear-gradient(180deg,rgba(255,255,255,.04),transparent)}
      .uma-workbench-title{font-size:14px;font-weight:900;color:var(--text)}
      .uma-workbench-sub{margin-top:4px;font-size:12px;color:var(--text3);line-height:1.45}
      .uma-decision-list{display:grid;gap:10px;padding:14px}
      .uma-decision-card{width:100%;text-align:left;border:1px solid var(--border);border-radius:14px;background:var(--bg);padding:13px;cursor:pointer;transition:border-color 140ms ease,box-shadow 140ms ease,transform 140ms ease}
      .uma-decision-card:hover,.uma-decision-card.active{border-color:rgba(37,99,235,.48);box-shadow:0 10px 28px rgba(37,99,235,.10);transform:translateY(-1px)}
      .uma-decision-meta{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:8px}
      .uma-mini-badge{display:inline-flex;align-items:center;gap:5px;padding:4px 7px;border-radius:999px;border:1px solid var(--border);font:800 9px/1 var(--font-m);letter-spacing:.06em;text-transform:uppercase;color:var(--text3)}
      .uma-mini-badge::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--badge-color,#94a3b8)}
      .uma-decision-name{font-size:13px;font-weight:900;color:var(--text);line-height:1.3}
      .uma-decision-desc{margin-top:5px;color:var(--text3);font-size:12px;line-height:1.45}
      .uma-transcript-grid{display:grid;gap:12px;padding:14px}
      .uma-transcript-card{border:1px solid var(--border);border-radius:14px;background:var(--bg);padding:14px;animation:umaReveal 180ms ease both;animation-delay:calc(var(--i,0) * 45ms)}
      .uma-transcript-row{display:flex;justify-content:space-between;gap:12px;align-items:center}
      .uma-transcript-label{font:900 12px/1 var(--font-d);color:var(--text)}
      .uma-transcript-copy{margin-top:8px;color:var(--text3);font-size:12px;line-height:1.55}
      .uma-file-review{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;padding:10px;border:1px solid var(--border);border-radius:12px;background:var(--bg3)}
      .uma-file-name{font-weight:850;color:var(--text);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .uma-file-note{margin-top:3px;color:var(--text3);font-size:11px}
      .uma-connector-hero{display:grid;grid-template-columns:minmax(0,.92fr) minmax(380px,1.08fr);gap:18px;margin-bottom:18px}
      .uma-connector-gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
      .uma-connector-card{padding:14px;border:1px solid var(--border);border-radius:16px;background:var(--bg2);box-shadow:0 10px 28px rgba(15,23,42,.05)}
      .uma-connector-name{font-weight:900;color:var(--text)}
      .uma-connector-copy{margin-top:6px;color:var(--text3);font-size:12px;line-height:1.45}
      .uma-checklist{display:grid;gap:8px}
      .uma-check-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;gap:9px;align-items:center;padding:10px;border:1px solid var(--border);border-radius:12px;background:var(--bg)}
      .uma-check-icon{width:22px;height:22px;border-radius:8px;display:grid;place-items:center;background:rgba(37,99,235,.10);color:#2563eb;font-weight:900}
      @keyframes umaPathMove{to{stroke-dashoffset:-180}}
      @keyframes umaHalo{50%{opacity:.32;transform:scale(.94)}}
      @keyframes umaReveal{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
      @media (prefers-reduced-motion: reduce){.uma-topology-path,.uma-node-halo,.uma-transcript-card{animation:none!important}.uma-flow-packet{display:none}}
      @media (max-width:1280px){.uma-cockpit-inner{grid-template-columns:1fr}.uma-cockpit h1{max-width:18ch}.uma-topology-card{min-height:300px}}
      @media (max-width:1100px){.uma-connector-hero,.uma-workbench{grid-template-columns:1fr}.uma-metric-strip{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media (max-width:640px){.uma-cockpit-inner{padding:18px}.uma-cockpit h1{font-size:30px;max-width:12ch}.uma-cockpit-actions .btn{width:100%;justify-content:center}.uma-metric-strip{grid-template-columns:1fr}.uma-topology-card{min-height:280px}.uma-topology-head{position:relative;left:auto;right:auto;top:auto;padding:14px}.uma-legend-line{position:relative;left:auto;right:auto;bottom:auto;padding:0 14px 14px}.uma-topology-svg{top:58px;height:calc(100% - 108px)}}
    `}</style>
  );
}

export function MigrationTopologyCanvas({ nodes = [], edges = [], onNodeClick }) {
  const [hovered, setHovered] = useState("");
  const hasLiveNodes = Array.isArray(nodes) && nodes.length > 0;
  const nodeMap = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  const connected = useMemo(() => {
    if (!hovered) return new Set();
    const ids = new Set([hovered]);
    edges.forEach(([from, to]) => {
      if (from === hovered) ids.add(to);
      if (to === hovered) ids.add(from);
    });
    return ids;
  }, [edges, hovered]);

  return (
    <div className="uma-topology-card">
      <ProductMotionStyles />
      <div className="uma-topology-head">
        <div>
          <div className="uma-topology-title">Live workflow objects</div>
          <div className="uma-topology-sub">Counts come from current connections, runs, review items, validation, and reports.</div>
        </div>
        {!hasLiveNodes ? <span className="uma-object-pill">No object selected</span> : null}
      </div>
      {!hasLiveNodes ? (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: 24, zIndex: 2 }}>
          <div style={{ maxWidth: 360, textAlign: "center", color: "#64748b", fontSize: 13, lineHeight: 1.55 }}>
            Select or create a migration run to populate source, conversion, review, validation, and report nodes.
          </div>
        </div>
      ) : null}
      <svg className="uma-topology-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        <defs>
          {edges.map(([fromId, toId], index) => {
            const from = nodeMap[fromId];
            const to = nodeMap[toId];
            if (!from || !to) return null;
            const bend = Math.abs(to.x - from.x) * .28;
            return <path key={`path-${index}`} id={`uma-topology-path-${index}`} d={`M ${from.x} ${from.y} C ${from.x + bend} ${from.y}, ${to.x - bend} ${to.y}, ${to.x} ${to.y}`} />;
          })}
        </defs>
        {edges.map(([fromId, toId, status], index) => {
          const from = nodeMap[fromId];
          const to = nodeMap[toId];
          if (!from || !to) return null;
          const edgeTone = tone(status);
          const bend = Math.abs(to.x - from.x) * .28;
          const active = !hovered || connected.has(fromId) || connected.has(toId);
          return (
            <g key={`${fromId}-${toId}`} opacity={active ? 1 : .16}>
              <path className={`uma-topology-path ${edgeTone}`} d={`M ${from.x} ${from.y} C ${from.x + bend} ${from.y}, ${to.x - bend} ${to.y}, ${to.x} ${to.y}`} stroke={statusColor(status)} />
              {edgeTone !== "idle" ? (
                <circle r={1.1} className="uma-flow-packet" fill="currentColor" style={{ color: statusColor(status) }}>
                  <animateMotion dur={`${4.8 + (index % 3) * .7}s`} repeatCount="indefinite" begin={`${index * .22}s`}>
                    <mpath href={`#uma-topology-path-${index}`} />
                  </animateMotion>
                </circle>
              ) : null}
            </g>
          );
        })}
      </svg>
      <svg className="uma-topology-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
        {nodes.map((node) => {
          const nodeTone = tone(node.status);
          const active = !hovered || connected.has(node.id);
          return (
            <g
              key={node.id}
              className="uma-topology-node"
              opacity={active ? 1 : .28}
              onMouseEnter={() => setHovered(node.id)}
              onMouseLeave={() => setHovered("")}
              onClick={() => onNodeClick?.(node)}
              transform={`translate(${node.x} ${node.y})`}
            >
              <circle className="uma-node-halo" r="5.8" fill={statusColor(node.status)} />
              <circle className="uma-node-core" r="3.1" stroke={statusColor(node.status)} />
              <rect className="uma-node-chip" x="-10" y="5.4" width="20" height="8" rx="3.2" />
              <text className="uma-topology-node-label" x="0" y="9.2" textAnchor="middle" dominantBaseline="middle">{node.label}</text>
              <text className="uma-topology-node-type" x="0" y="12.2" textAnchor="middle" dominantBaseline="middle">{node.type}</text>
              {nodeTone === "blocked" ? <circle r="1.2" cx="4.1" cy="-3.7" fill="#dc2626" /> : null}
            </g>
          );
        })}
      </svg>
      <div className="uma-legend-line">
        {Object.entries(TONE).slice(0, 4).map(([key, value]) => <span key={key}><i style={{ background: value.color }} />{value.label}</span>)}
      </div>
    </div>
  );
}

export function CommandCenterCockpit({ stats, connections = [], jobs = [], health, setPage }) {
  const totalConns = connections.length;
  const healthyConns = connections.filter((c) => c.health === "healthy").length;
  const failedJobs = jobs.filter((j) => j.status === "FAILED").length;
  const runningJobs = jobs.filter((j) => j.status === "RUNNING").length;
  const succeededJobs = jobs.filter((j) => j.status === "SUCCEEDED").length;
  const successRate = jobs.length ? Math.round((succeededJobs / jobs.length) * 100) : 0;
  const reviewJobs = jobs.filter((j) => ["REQUIRES_REVIEW", "APPROVAL_REQUIRED"].includes(j.status)).length;
  const topologyNodes = [
    { id: "connections", label: `${healthyConns}/${totalConns}`, type: "Connections", x: 12, y: 48, status: totalConns ? (healthyConns === totalConns ? "validated" : "review") : "idle" },
    { id: "runs", label: String(jobs.length), type: "Runs", x: 32, y: 30, status: runningJobs ? "active" : jobs.length ? "validated" : "idle" },
    { id: "conversion", label: String(jobs.filter((j) => String(j.workflow_type || "").includes("CONVERSION")).length), type: "Conversion", x: 52, y: 48, status: reviewJobs ? "review" : jobs.length ? "validated" : "idle" },
    { id: "review", label: String(reviewJobs + failedJobs), type: "Review", x: 72, y: 32, status: failedJobs ? "blocked" : reviewJobs ? "review" : "validated" },
    { id: "reports", label: String(succeededJobs), type: "Reports", x: 88, y: 62, status: succeededJobs ? "validated" : "idle" },
  ];
  const topologyEdges = [
    ["connections", "runs", totalConns ? "validated" : "idle"],
    ["runs", "conversion", jobs.length ? "active" : "idle"],
    ["conversion", "review", failedJobs ? "blocked" : reviewJobs ? "review" : "validated"],
    ["review", "reports", succeededJobs ? "validated" : "review"],
  ];
  const metrics = [
    { label: "Project health", value: failedJobs ? "Blocked" : health ? "Operational" : "Offline", note: failedJobs ? `${failedJobs} failed runs` : "control plane reachable", color: failedJobs ? "#dc2626" : "#059669" },
    { label: "Connections", value: `${healthyConns}/${totalConns}`, note: "healthy endpoints", color: totalConns ? "#2563eb" : "#94a3b8" },
    { label: "Data moved", value: `${Number(stats?.total_gb || 0).toFixed(1)} GB`, note: "tracked loads", color: "#7c3aed" },
    { label: "Success rate", value: `${successRate}%`, note: jobs.length ? "recent jobs" : "no runs yet", color: failedJobs ? "#dc2626" : "#059669" },
  ];
  return (
    <div className="uma-cockpit">
      <ProductMotionStyles />
      <div className="uma-cockpit-inner">
        <div>
          <div className="uma-kicker">Live migration cockpit</div>
          <h1>Snowflake migration control plane</h1>
          <div className="uma-cockpit-copy">
            UMA shows what is moving, what is blocked, what needs review, and which evidence can be trusted before cutover.
          </div>
          <div className="uma-cockpit-actions">
            <button className="btn btn-primary" onClick={() => setPage("dashboard")}>Open run board</button>
            <button className="btn btn-ghost" onClick={() => setPage("brain_review")}>Resolve blockers</button>
            <button className="btn btn-ghost" onClick={() => setPage("connections")}>Connector setup</button>
          </div>
          <div className="uma-action-card">
            <div className="uma-action-title">Next recommended action</div>
            <div className="uma-action-body">{failedJobs ? "Open failed runs and Brain Review decisions before running validation again." : jobs.length ? "Continue with validation evidence and report generation." : "Create or open a migration run so UMA can show blockers, evidence, and reports."}</div>
          </div>
          <div className="uma-metric-strip">
            {metrics.map((metric) => (
              <div className="uma-metric" key={metric.label}>
                <div className="uma-metric-label">{metric.label}</div>
                <div className="uma-metric-value" style={{ color: metric.color }}>{metric.value}</div>
                <div className="uma-metric-note">{metric.note}</div>
              </div>
            ))}
          </div>
        </div>
        <MigrationTopologyCanvas nodes={topologyNodes} edges={topologyEdges} onNodeClick={(node) => {
          if (node.id === "connections") setPage("connections");
          if (node.id === "runs") setPage("dashboard");
          if (node.id === "conversion") setPage("dbt_conversion");
          if (node.id === "review") setPage("brain_review");
          if (node.id === "reports") setPage("reports");
        }} />
      </div>
    </div>
  );
}

export function BrainDecisionWorkbench({ items = [], selected, onSelect, comparison, comparisonLoading, comparisonError, actions }) {
  const rows = items;
  if (!rows.length) {
    return (
      <div className="uma-workbench">
        <ProductMotionStyles />
        <div className="uma-workbench-panel">
          <div className="uma-workbench-head">
            <div className="uma-workbench-title">Decision inbox</div>
            <div className="uma-workbench-sub">Open Brain Review decisions will appear here after conversion, validation, or artifact review creates a blocker.</div>
          </div>
          <div style={{ padding: 18, color: "var(--text3)", fontSize: 12, lineHeight: 1.6 }}>
            No open decisions. Run UMA Brain Review on a selected migration object or open a conversion job with review blockers.
          </div>
        </div>
      </div>
    );
  }
  const current = selected || rows[0];
  const sourceName = comparison?.source_artifact?.original_filename || current?.source_object || "Source evidence";
  const targetName = comparison?.generated_artifact?.original_filename || current?.target_object || "Generated artifact";
  const transcript = [
    { title: "Run Summary", status: current?.status || "IN_REVIEW", body: `${current?.workflow_type || "Migration workflow"} produced evidence that requires human judgment before it is considered migration-ready.` },
    { title: "What UMA Did", status: "ACTIVE", body: `Linked ${sourceName} to ${targetName}, created a decision record, and preserved source/target evidence for reviewer approval.` },
    { title: "What UMA Did Not Do", status: "WARNING", body: "UMA did not claim Snowflake validation, production deployment, or cutover readiness without explicit evidence." },
    { title: "Critical Blockers", status: current?.severity || "INFO", body: current?.reason || current?.description || "No critical blocker text was attached to this decision." },
    { title: "Recommended Next Actions", status: "IN_REVIEW", body: current?.recommendation || "Compare source and generated artifacts, approve safe output, or send it back for rework." },
  ];
  return (
    <div className="uma-workbench">
      <ProductMotionStyles />
      <div className="uma-workbench-panel">
        <div className="uma-workbench-head">
          <div className="uma-workbench-title">Evidence requiring judgment</div>
          <div className="uma-workbench-sub">Prioritized decisions, blockers, generated artifacts, and validation findings.</div>
        </div>
        <div className="uma-decision-list">
          {rows.map((item) => (
            <button key={item.id} type="button" className={`uma-decision-card ${current?.id === item.id ? "active" : ""}`} onClick={() => onSelect?.(item)}>
              <div className="uma-decision-meta">
                <span className="uma-mini-badge" style={{ "--badge-color": statusColor(item.severity) }}>{item.severity || "MEDIUM"}</span>
                <span className="uma-mini-badge" style={{ "--badge-color": statusColor(item.status) }}>{item.status || "NEW"}</span>
              </div>
              <div className="uma-decision-name">{item.title || item.summary || item.description || "Migration decision"}</div>
              <div className="uma-decision-desc">{item.source_object || "Source evidence"} → {item.target_object || "Snowflake target"}</div>
            </button>
          ))}
        </div>
      </div>
      <div className="uma-workbench-panel">
        <div className="uma-workbench-head">
          <div className="uma-workbench-title">Readable Brain Review transcript</div>
          <div className="uma-workbench-sub">Default view is reviewer-ready. Raw payloads stay under Advanced Details.</div>
        </div>
        <div className="uma-transcript-grid">
          {transcript.map((section, index) => (
            <div className="uma-transcript-card" key={section.title} style={{ "--i": index }}>
              <div className="uma-transcript-row">
                <div className="uma-transcript-label">{section.title}</div>
                <span className="uma-mini-badge" style={{ "--badge-color": statusColor(section.status) }}>{String(section.status).replace(/_/g, " ")}</span>
              </div>
              <div className="uma-transcript-copy">{section.body}</div>
            </div>
          ))}
          <div className="uma-transcript-card" style={{ "--i": 6 }}>
            <div className="uma-transcript-row">
              <div className="uma-transcript-label">File-by-file Review</div>
              <span className="uma-mini-badge" style={{ "--badge-color": statusColor(current?.status) }}>{current?.item_type || "Evidence"}</span>
            </div>
            <div className="uma-file-review mt3">
              <div>
                <div className="uma-file-name">{sourceName}</div>
                <div className="uma-file-note">{comparisonLoading ? "Loading comparison..." : comparisonError || "Source evidence available for review."}</div>
              </div>
              <span className="uma-mini-badge" style={{ "--badge-color": statusColor(current?.severity) }}>{current?.severity || "INFO"}</span>
            </div>
            <div className="uma-file-review mt2">
              <div>
                <div className="uma-file-name">{targetName}</div>
                <div className="uma-file-note">Generated artifact requires explicit approval before downstream trust.</div>
              </div>
              <span className="uma-mini-badge" style={{ "--badge-color": statusColor(current?.status) }}>{current?.status || "NEW"}</span>
            </div>
          </div>
          {actions ? <div className="uma-transcript-card" style={{ "--i": 7 }}>{actions}</div> : null}
          {comparison ? (
            <details className="uma-transcript-card" style={{ "--i": 8 }}>
              <summary className="uma-transcript-label">Advanced Details / Raw JSON</summary>
              <pre className="pq-code-block mt3">{JSON.stringify(comparison, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ConnectorReadinessShowcase({ connections = [], onOpen }) {
  const connectors = [
    { name: "Postgres", status: "Ready", copy: "Golden-path source for inventory, full load, and watermark-style sync." },
    { name: "Snowflake", status: "Ready", copy: "Target setup, permission preflight, warehouse validation, and load readiness." },
    { name: "BigQuery", status: "Preview", copy: "SQL dialect and artifact conversion support; validate before customer cutover." },
    { name: "dbt", status: "Beta", copy: "Model detection, Jinja preservation, refs/sources, and generated Snowflake output." },
  ];
  const checks = [
    ["Network reachability", connections.length ? "validated" : "review"],
    ["Service authentication", connections.some((c) => c.health === "healthy") ? "validated" : "review"],
    ["Secret manager readiness", "review"],
    ["Least-privilege permissions", "review"],
  ];
  return (
    <div className="uma-connector-hero">
      <ProductMotionStyles />
      <div className="uma-workbench-panel">
        <div className="uma-workbench-head">
          <div className="uma-workbench-title">Connector gallery</div>
          <div className="uma-workbench-sub">Choose a source or target, then complete readiness checks before migration execution.</div>
        </div>
        <div className="uma-connector-gallery" style={{ padding: 14 }}>
          {connectors.map((connector) => (
            <button key={connector.name} className="uma-connector-card" type="button" onClick={() => onOpen?.(connector.name)}>
              <div className="uma-decision-meta">
                <span className="uma-mini-badge" style={{ "--badge-color": statusColor(connector.status === "Ready" ? "validated" : "review") }}>{connector.status}</span>
              </div>
              <div className="uma-connector-name">{connector.name}</div>
              <div className="uma-connector-copy">{connector.copy}</div>
            </button>
          ))}
        </div>
      </div>
      <div className="uma-workbench-panel">
        <div className="uma-workbench-head">
          <div className="uma-workbench-title">Production readiness</div>
          <div className="uma-workbench-sub">Human MFA belongs in login. Background workers require service auth, scoped roles, and secret references.</div>
        </div>
        <div className="uma-checklist" style={{ padding: 14 }}>
          {checks.map(([label, status]) => (
            <div className="uma-check-row" key={label}>
              <span className="uma-check-icon" style={{ color: statusColor(status), background: `${statusColor(status)}18` }}>{tone(status) === "validated" ? "✓" : "!"}</span>
              <span className="uma-file-name">{label}</span>
              <span className="uma-mini-badge" style={{ "--badge-color": statusColor(status) }}>{TONE[tone(status)].label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
