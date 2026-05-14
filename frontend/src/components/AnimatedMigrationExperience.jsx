import React, { useEffect, useMemo, useState } from "react";

const STATUS_TONE = {
  active: "active",
  running: "active",
  completed: "validated",
  complete: "validated",
  succeeded: "validated",
  validated: "validated",
  pass: "validated",
  warning: "review",
  warn: "review",
  review: "review",
  requires_review: "review",
  blocked: "blocked",
  failed: "blocked",
  fail: "blocked",
  error: "blocked",
};

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(Boolean(query.matches));
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

function usePageVisible() {
  const [visible, setVisible] = useState(() => typeof document === "undefined" ? true : !document.hidden);
  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}

function tone(status) {
  return STATUS_TONE[String(status || "inactive").toLowerCase()] || "idle";
}

function nodeIcon(type = "") {
  const key = String(type).toLowerCase();
  if (key.includes("snowflake")) return "SF";
  if (key.includes("brain")) return "BR";
  if (key.includes("validation")) return "VA";
  if (key.includes("report")) return "RP";
  if (key.includes("sql")) return "SQL";
  if (key.includes("dbt")) return "dbt";
  if (key.includes("etl")) return "ETL";
  if (key.includes("table")) return "TB";
  if (key.includes("schema")) return "SC";
  return "DB";
}

function graphFromLiveInput(nodes, edges) {
  const safeNodes = Array.isArray(nodes) ? nodes : [];
  const safeEdges = Array.isArray(edges) ? edges : [];
  return { nodes: safeNodes, edges: safeEdges };
}

export function AnimatedMigrationStyles() {
  return (
    <style>{`
      .uma-motion-shell{position:relative;overflow:hidden;border:1px solid rgba(120,150,190,.22);border-radius:18px;background:linear-gradient(135deg,rgba(8,18,34,.88),rgba(10,31,54,.78));box-shadow:0 18px 44px rgba(3,8,16,.20)}
      .uma-motion-shell::before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(72,152,255,.08),rgba(45,212,191,.08)),linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:100% 100%,42px 42px,42px 42px;opacity:.7;pointer-events:none}
      .uma-motion-canvas{position:relative;min-height:260px;padding:18px;color:#eef7ff}
      .uma-ambient-shell{position:relative;min-height:328px;overflow:hidden;border:1px solid rgba(124,160,208,.22);border-radius:18px;background:radial-gradient(circle at 45% 46%,rgba(88,166,255,.22),transparent 29%),radial-gradient(circle at 82% 36%,rgba(45,212,191,.12),transparent 23%),linear-gradient(135deg,#07101d 0%,#0d1b2d 48%,#08111e 100%);box-shadow:0 22px 54px rgba(3,8,16,.28)}
      .uma-ambient-shell::before{content:"";position:absolute;inset:0;background:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:44px 44px;mask-image:linear-gradient(90deg,transparent,black 13%,black 87%,transparent);opacity:.78;pointer-events:none}
      .uma-ambient-shell::after{content:"";position:absolute;inset:-40%;background:conic-gradient(from 130deg,transparent,rgba(88,166,255,.12),transparent 22%,rgba(45,212,191,.08),transparent 38%);animation:umaAmbientSweep 16s linear infinite;opacity:.42;pointer-events:none}
      .uma-ambient-svg{position:absolute;inset:0;width:100%;height:100%;z-index:1}
      .uma-ambient-copy{position:absolute;left:22px;top:18px;z-index:3;max-width:min(430px,62%)}
      .uma-ambient-kicker{display:inline-flex;align-items:center;gap:8px;padding:5px 9px;border:1px solid rgba(156,180,216,.24);border-radius:999px;background:rgba(5,12,22,.52);color:#adc1da;font:800 10px/1 var(--font-m);letter-spacing:.08em;text-transform:uppercase;backdrop-filter:blur(10px)}
      .uma-ambient-title{margin-top:14px;color:#f5f9ff;font:900 clamp(20px,2.5vw,31px)/1.06 var(--font-h);letter-spacing:0;text-shadow:0 6px 22px rgba(0,0,0,.25)}
      .uma-ambient-sub{margin-top:9px;color:#aabbd0;font-size:12px;line-height:1.55;max-width:390px}
      .uma-ambient-stage{position:absolute;right:22px;top:18px;z-index:3;display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid rgba(88,166,255,.24);border-radius:999px;background:rgba(8,18,32,.48);color:#d9e9ff;font-size:11px;font-weight:850;backdrop-filter:blur(10px)}
      .uma-ambient-stage i{width:7px;height:7px;border-radius:50%;background:#58a6ff;box-shadow:0 0 14px rgba(88,166,255,.9);animation:umaAmbientPulse 1.9s ease-in-out infinite}
      .uma-ambient-path{fill:none;stroke:rgba(147,174,213,.20);stroke-width:1.5;stroke-linecap:round;stroke-dasharray:7 10;animation:umaDash 18s linear infinite}
      .uma-ambient-active{stroke:#58a6ff;stroke-width:1.8;filter:drop-shadow(0 0 5px rgba(88,166,255,.40))}
      .uma-ambient-validated{stroke:#2dd4bf;filter:drop-shadow(0 0 5px rgba(45,212,191,.34))}
      .uma-ambient-review{stroke:#f59e0b;filter:drop-shadow(0 0 5px rgba(245,158,11,.34))}
      .uma-ambient-blocked{stroke:#ef4444;filter:drop-shadow(0 0 5px rgba(239,68,68,.36))}
      .uma-ambient-node{filter:drop-shadow(0 10px 18px rgba(0,0,0,.34));animation:umaSoftRise 420ms ease both;animation-delay:calc(var(--i,0) * 70ms)}
      .uma-ambient-node circle.core{fill:#0d1c31;stroke:rgba(187,209,239,.42);stroke-width:1.2}
      .uma-ambient-node circle.ring{fill:none;stroke:rgba(88,166,255,.20);stroke-width:10;opacity:.42;animation:umaAmbientPulse 2.8s ease-in-out infinite}
      .uma-ambient-node.validated circle.ring{stroke:rgba(45,212,191,.24)}.uma-ambient-node.review circle.ring{stroke:rgba(245,158,11,.26)}.uma-ambient-node.blocked circle.ring{stroke:rgba(239,68,68,.26)}
      .uma-ambient-node text{font-family:var(--font-m);font-size:10px;font-weight:850;fill:#eaf4ff;letter-spacing:.04em}
      .uma-ambient-node text.sub{font-size:8px;fill:#8da3bf;font-weight:700}
      .uma-ambient-node .badge-bg{fill:rgba(8,18,32,.72);stroke:rgba(168,192,225,.16);stroke-width:1}
      .uma-ambient-packet{opacity:.86;filter:drop-shadow(0 0 8px currentColor)}
      .uma-ambient-hotspot{fill:rgba(239,68,68,.18);stroke:#ef4444;stroke-width:1.2;filter:drop-shadow(0 0 9px rgba(239,68,68,.45));animation:umaAmbientPulse 1.7s ease-in-out infinite}
      .uma-ambient-review-dot{fill:rgba(245,158,11,.20);stroke:#f59e0b;stroke-width:1.2;filter:drop-shadow(0 0 9px rgba(245,158,11,.42));animation:umaAmbientPulse 2.1s ease-in-out infinite}
      .uma-ambient-footer{position:absolute;left:22px;right:22px;bottom:18px;z-index:3;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
      .uma-ambient-metric{min-width:0;padding:10px 12px;border:1px solid rgba(160,184,216,.18);border-radius:13px;background:rgba(7,15,27,.52);backdrop-filter:blur(12px)}
      .uma-ambient-metric-label{font-size:9px;color:#8fa6c0;text-transform:uppercase;letter-spacing:.08em;font-family:var(--font-m);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .uma-ambient-metric-value{margin-top:4px;color:#edf6ff;font-size:13px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .uma-motion-label{position:absolute;left:18px;top:16px;z-index:3;display:inline-flex;gap:8px;align-items:center;padding:5px 9px;border:1px solid rgba(156,180,216,.28);border-radius:999px;background:rgba(10,20,36,.52);color:#b8c9df;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      .uma-motion-stage{position:absolute;right:18px;top:16px;z-index:3;color:#d6e6ff;font-size:11px;font-weight:800}
      .uma-graph-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
      .uma-edge{fill:none;stroke:rgba(154,180,215,.28);stroke-width:1.6;stroke-linecap:round;stroke-dasharray:8 8;animation:umaDash 10s linear infinite}
      .uma-edge-active{stroke:#58a6ff;filter:drop-shadow(0 0 5px rgba(88,166,255,.42))}
      .uma-edge-validated{stroke:#2dd4bf;filter:drop-shadow(0 0 5px rgba(45,212,191,.32))}
      .uma-edge-review{stroke:#f59e0b;filter:drop-shadow(0 0 5px rgba(245,158,11,.32))}
      .uma-edge-blocked{stroke:#ef4444;filter:drop-shadow(0 0 5px rgba(239,68,68,.34))}
      .uma-packet{filter:drop-shadow(0 0 6px currentColor);opacity:.8}
      .uma-node{position:absolute;z-index:2;transform:translate(-50%,-50%);min-width:112px;max-width:148px;padding:9px 10px;border:1px solid rgba(157,184,222,.26);border-radius:14px;background:rgba(10,21,37,.74);box-shadow:0 12px 28px rgba(3,8,16,.28);backdrop-filter:blur(12px);animation:umaNodeIn 220ms ease both;animation-delay:calc(var(--i,0) * 60ms);font-family:var(--font-d);text-align:left;cursor:pointer;color:inherit}
      .uma-node::after{content:"";position:absolute;inset:-1px;border-radius:inherit;border:1px solid transparent;pointer-events:none}
      .uma-node-active::after{border-color:rgba(88,166,255,.72);box-shadow:0 0 18px rgba(88,166,255,.18)}
      .uma-node-validated::after{border-color:rgba(45,212,191,.64)}
      .uma-node-review::after{border-color:rgba(245,158,11,.72)}
      .uma-node-blocked::after{border-color:rgba(239,68,68,.70)}
      .uma-node-head{display:flex;align-items:center;gap:8px}
      .uma-node-glyph{width:28px;height:28px;display:grid;place-items:center;border-radius:10px;background:rgba(88,166,255,.14);color:#cce3ff;font-size:10px;font-family:var(--font-m);font-weight:900}
      .uma-node-validated .uma-node-glyph{background:rgba(45,212,191,.14);color:#8ff4e5}
      .uma-node-review .uma-node-glyph{background:rgba(245,158,11,.15);color:#ffd289}
      .uma-node-blocked .uma-node-glyph{background:rgba(239,68,68,.15);color:#ffadad}
      .uma-node-label{font-size:12px;font-weight:900;line-height:1.15;color:#f3f8ff}
      .uma-node-type{font-size:9px;color:#99acc6;margin-top:3px;font-family:var(--font-m);text-transform:uppercase;letter-spacing:.06em}
      .uma-graph-wrap{position:relative;min-height:360px;border:1px solid var(--border);border-radius:16px;background:linear-gradient(135deg,rgba(12,24,42,.92),rgba(14,35,57,.84));overflow:hidden}
      .uma-graph-wrap .uma-motion-canvas{min-height:360px}
      .uma-legend{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:10px;color:var(--text3)}
      .uma-legend span{display:inline-flex;align-items:center;gap:5px}
      .uma-legend i{width:9px;height:9px;border-radius:50%;display:inline-block;background:#74839a}
      .uma-legend .active i{background:#58a6ff}.uma-legend .validated i{background:#2dd4bf}.uma-legend .review i{background:#f59e0b}.uma-legend .blocked i{background:#ef4444}
      .uma-feed{display:grid;gap:8px}
      .uma-feed-item{display:grid;grid-template-columns:26px minmax(0,1fr);gap:8px;align-items:start;padding:9px 10px;border:1px solid rgba(135,162,201,.18);border-radius:12px;background:rgba(255,255,255,.04);animation:umaSlideIn 200ms ease both;animation-delay:calc(var(--i,0) * 55ms)}
      .uma-feed-dot{width:22px;height:22px;border-radius:8px;display:grid;place-items:center;font-size:11px;font-weight:900;background:rgba(88,166,255,.14);color:#8fc7ff}
      .uma-feed-validated .uma-feed-dot{background:rgba(45,212,191,.14);color:#74eadc}.uma-feed-review .uma-feed-dot{background:rgba(245,158,11,.16);color:#ffd084}.uma-feed-blocked .uma-feed-dot{background:rgba(239,68,68,.15);color:#ffb0b0}
      .uma-feed-title{font-size:12px;font-weight:850;color:var(--text2)}
      .uma-feed-detail{font-size:10px;color:var(--text3);margin-top:2px}
      .uma-empty-visual{position:relative;width:min(260px,100%);height:112px;margin:0 auto 14px}
      .uma-empty-visual .uma-mini-node{position:absolute;width:42px;height:42px;border-radius:14px;display:grid;place-items:center;border:1px solid rgba(132,164,208,.32);background:rgba(88,166,255,.08);font-size:10px;font-weight:900;color:var(--text2)}
      .uma-empty-visual .n1{left:18px;top:34px}.uma-empty-visual .n2{left:110px;top:16px}.uma-empty-visual .n3{right:18px;top:34px}
      .uma-empty-visual svg{position:absolute;inset:0;width:100%;height:100%}
      .uma-context-overlay{position:fixed;inset:0;z-index:300;background:rgba(3,8,16,.28);animation:umaFade 160ms ease both}
      .uma-context-drawer{position:absolute;right:0;top:0;height:100%;width:min(440px,100vw);background:var(--bg2);border-left:1px solid var(--border);box-shadow:-18px 0 44px rgba(3,8,16,.28);padding:18px;overflow:auto;animation:umaDrawer 240ms ease both}
      .uma-context-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:14px}
      .uma-context-title{font-size:18px;font-weight:900;color:var(--text)}
      .uma-context-sub{font-size:12px;color:var(--text3);margin-top:3px}
      .uma-context-card{border:1px solid var(--border);border-radius:12px;padding:12px;background:var(--bg3);margin-bottom:10px;animation:umaSlideIn 180ms ease both}
      .uma-transform-card{display:grid;grid-template-columns:minmax(0,1fr) 56px minmax(0,1fr);gap:10px;align-items:center}
      .uma-code-card{min-height:112px;border:1px solid var(--border);border-radius:12px;background:var(--bg3);padding:12px;overflow:hidden}
      .uma-code-line{height:8px;border-radius:99px;background:linear-gradient(90deg,rgba(156,180,216,.35),rgba(88,166,255,.18));margin-bottom:8px;animation:umaCodePulse 1.8s ease-in-out infinite}
      .uma-transform-arrow{height:2px;background:#58a6ff;position:relative}.uma-transform-arrow::after{content:"";position:absolute;right:-1px;top:-4px;border-left:8px solid #58a6ff;border-top:5px solid transparent;border-bottom:5px solid transparent}
      .uma-brain-transcript{display:grid;gap:10px}
      .uma-transcript-section{border:1px solid var(--border);border-radius:12px;background:var(--bg3);padding:12px;animation:umaSlideIn 220ms ease both;animation-delay:calc(var(--i,0) * 70ms)}
      .uma-transcript-title{display:flex;justify-content:space-between;gap:10px;align-items:center;font-size:12px;font-weight:900;color:var(--text2)}
      .uma-transcript-body{font-size:12px;color:var(--text3);line-height:1.55;margin-top:7px}
      @keyframes umaDash{to{stroke-dashoffset:-160}}
      @keyframes umaNodeIn{from{opacity:0;transform:translate(-50%,-46%) scale(.96)}to{opacity:1;transform:translate(-50%,-50%) scale(1)}}
      @keyframes umaSlideIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
      @keyframes umaFade{from{opacity:0}to{opacity:1}}
      @keyframes umaDrawer{from{transform:translateX(18px);opacity:.88}to{transform:translateX(0);opacity:1}}
      @keyframes umaCodePulse{50%{opacity:.48;transform:scaleX(.92)}}
      @keyframes umaAmbientSweep{to{transform:rotate(360deg)}}
      @keyframes umaAmbientPulse{50%{opacity:.52;transform:scale(.96)}}
      @keyframes umaSoftRise{from{opacity:0;transform:translateY(5px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
      @media (prefers-reduced-motion: reduce){.uma-edge,.uma-node,.uma-feed-item,.uma-context-overlay,.uma-context-drawer,.uma-context-card,.uma-transcript-section,.uma-code-line,.uma-ambient-shell::after,.uma-ambient-path,.uma-ambient-node,.uma-ambient-node circle.ring,.uma-ambient-stage i,.uma-ambient-hotspot,.uma-ambient-review-dot{animation:none!important}.uma-packet,.uma-ambient-packet{display:none}}
      .theme-light .uma-motion-shell,.theme-light .uma-graph-wrap{background:linear-gradient(135deg,#f8fbff,#eef8fb);box-shadow:0 16px 36px rgba(15,26,44,.08)}
      .theme-light .uma-ambient-shell{background:radial-gradient(circle at 46% 45%,rgba(88,166,255,.18),transparent 30%),radial-gradient(circle at 80% 34%,rgba(45,212,191,.12),transparent 24%),linear-gradient(135deg,#f8fbff,#edf6fb);box-shadow:0 16px 36px rgba(15,26,44,.10)}
      .theme-light .uma-ambient-title{color:#10213a;text-shadow:none}.theme-light .uma-ambient-sub{color:#50657c}.theme-light .uma-ambient-kicker,.theme-light .uma-ambient-stage,.theme-light .uma-ambient-metric{background:rgba(255,255,255,.66);color:#425a74}.theme-light .uma-ambient-node circle.core{fill:#ffffff}.theme-light .uma-ambient-node text{fill:#10213a}.theme-light .uma-ambient-node text.sub{fill:#64748b}
      .theme-light .uma-motion-label{background:rgba(255,255,255,.72);color:#4d647e}
      .theme-light .uma-node{background:rgba(255,255,255,.82);box-shadow:0 10px 26px rgba(15,26,44,.10)}
      .theme-light .uma-node-label{color:#10213a}.theme-light .uma-node-type{color:#64748b}
    `}</style>
  );
}

export function GraphLegend() {
  return (
    <div className="uma-legend" aria-label="Migration graph legend">
      <span className="active"><i /> Active</span>
      <span className="validated"><i /> Validated</span>
      <span className="review"><i /> Requires review</span>
      <span className="blocked"><i /> Blocked</span>
      <span><i /> Not started</span>
    </div>
  );
}

function EdgeLayer({ nodes, edges, reducedMotion }) {
  const byId = useMemo(() => Object.fromEntries(nodes.map((node) => [node.id, node])), [nodes]);
  return (
    <svg className="uma-graph-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        {edges.map((edge, index) => {
          const from = byId[edge.from];
          const to = byId[edge.to];
          if (!from || !to) return null;
          const mid = Math.abs(to.x - from.x) * 0.25;
          return (
            <path
              key={`def-${index}`}
              id={`uma-edge-path-${edge.from}-${edge.to}-${index}`}
              d={`M ${from.x} ${from.y} C ${from.x + mid} ${from.y}, ${to.x - mid} ${to.y}, ${to.x} ${to.y}`}
            />
          );
        })}
      </defs>
      {edges.map((edge, index) => {
        const from = byId[edge.from];
        const to = byId[edge.to];
        if (!from || !to) return null;
        const edgeTone = tone(edge.status);
        const mid = Math.abs(to.x - from.x) * 0.25;
        const path = `M ${from.x} ${from.y} C ${from.x + mid} ${from.y}, ${to.x - mid} ${to.y}, ${to.x} ${to.y}`;
        return (
          <g key={`${edge.from}-${edge.to}-${index}`}>
            <path className={`uma-edge uma-edge-${edgeTone}`} d={path} />
            {!reducedMotion && edgeTone !== "idle" ? (
              <circle r={3} className="uma-packet" fill="currentColor" style={{ color: edgeTone === "validated" ? "#2dd4bf" : edgeTone === "review" ? "#f59e0b" : edgeTone === "blocked" ? "#ef4444" : "#58a6ff" }}>
                <animateMotion dur={`${4.2 + (index % 3) * 0.7}s`} repeatCount="indefinite" begin={`${index * 0.26}s`}>
                  <mpath href={`#uma-edge-path-${edge.from}-${edge.to}-${index}`} />
                </animateMotion>
              </circle>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

export function MigrationNode({ node, index = 0, onClick }) {
  const nodeTone = tone(node.status);
  return (
    <button
      type="button"
      className={`uma-node uma-node-${nodeTone}`}
      style={{ left: `${node.x}%`, top: `${node.y}%`, "--i": index }}
      onClick={() => onClick?.(node)}
      title={`${node.label}: ${node.type}`}
    >
      <div className="uma-node-head">
        <span className="uma-node-glyph">{nodeIcon(node.type)}</span>
        <span>
          <div className="uma-node-label">{node.label}</div>
          <div className="uma-node-type">{node.type}</div>
        </span>
      </div>
    </button>
  );
}

export function AnimatedMigrationCanvas({
  sources = [],
  targets = [],
  activeStage = "UMA Intelligence",
  blockers = 0,
  reviewItems = 0,
  validationStatus = "not_started",
  reducedMotion,
  nodes,
  edges,
  onNodeClick,
}) {
  const prefersReduced = useReducedMotion();
  const pageVisible = usePageVisible();
  const isReduced = (reducedMotion ?? prefersReduced) || !pageVisible;
  const graph = useMemo(() => {
    if (nodes?.length || edges?.length) return graphFromLiveInput(nodes, edges);
    const sourceRows = sources.length ? sources : [{ name: "Postgres" }, { name: "SQL/dbt" }];
    const targetRows = targets.length ? targets : [{ name: "Snowflake" }];
    const generatedNodes = [
      ...sourceRows.slice(0, 3).map((source, index) => ({
        id: `source-${index}`,
        label: source.name || source.label || `Source ${index + 1}`,
        type: index === 1 ? "SQL File" : "Source Database",
        x: 9,
        y: 24 + index * 22,
        status: index === 0 ? "completed" : reviewItems ? "requires_review" : "active",
      })),
      { id: "uma", label: "UMA Intelligence", type: "Analysis Layer", x: 42, y: 38, status: "active" },
      { id: "brain", label: "Brain Review", type: "Review Queue", x: 62, y: 24, status: blockers ? "blocked" : reviewItems ? "requires_review" : "completed" },
      ...targetRows.slice(0, 2).map((target, index) => ({
        id: `target-${index}`,
        label: target.name || target.label || "Snowflake",
        type: "Snowflake Table",
        x: 84,
        y: 32 + index * 24,
        status: validationStatus === "completed" ? "validated" : blockers ? "blocked" : "active",
      })),
      { id: "validation", label: "Validation", type: "Validation Check", x: 62, y: 66, status: validationStatus || "warning" },
      { id: "report", label: "Report", type: "Report", x: 88, y: 72, status: validationStatus === "completed" ? "completed" : "pending" },
    ];
    const generatedEdges = generatedNodes
      .filter((node) => node.id.startsWith("source-"))
      .map((node) => ({ from: node.id, to: "uma", status: node.status === "requires_review" ? "review" : "active" }))
      .concat([
        { from: "uma", to: "brain", status: blockers ? "blocked" : reviewItems ? "review" : "active" },
        { from: "brain", to: "target-0", status: blockers ? "blocked" : reviewItems ? "review" : "active" },
        { from: "target-0", to: "validation", status: validationStatus === "completed" ? "validated" : validationStatus === "failed" ? "blocked" : "review" },
        { from: "validation", to: "report", status: validationStatus === "completed" ? "validated" : "review" },
      ]);
    return { nodes: generatedNodes, edges: generatedEdges };
  }, [sources, targets, blockers, reviewItems, validationStatus, nodes, edges]);

  return (
    <div className="uma-motion-shell">
      <AnimatedMigrationStyles />
      <div className="uma-motion-canvas">
        <div className="uma-motion-label">
          <span>Live migration map</span>
        </div>
        <div className="uma-motion-stage">{activeStage}</div>
        <EdgeLayer nodes={graph.nodes} edges={graph.edges} reducedMotion={isReduced} />
        {graph.nodes.map((node, index) => (
          <MigrationNode key={node.id} node={node} index={index} onClick={onNodeClick} />
        ))}
      </div>
    </div>
  );
}

export function AnimatedMigrationGraph({ nodes, edges, selectedId, onNodeClick, height = 360 }) {
  const reduced = useReducedMotion();
  const pageVisible = usePageVisible();
  const graph = graphFromLiveInput(nodes, edges);
  const visibleNodes = graph.nodes.map((node) => selectedId && node.id === selectedId ? { ...node, status: "active" } : node);
  return (
    <div className="uma-graph-wrap" style={{ minHeight: height }}>
      <AnimatedMigrationStyles />
      <div className="uma-motion-canvas" style={{ minHeight: height }}>
        <div className="uma-motion-label">Live workflow graph</div>
        {!visibleNodes.length ? (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: 22, color: "var(--text3)", textAlign: "center", fontSize: 12, lineHeight: 1.5 }}>
            Select an object with lineage or run evidence to populate the workflow graph.
          </div>
        ) : null}
        <EdgeLayer nodes={visibleNodes} edges={graph.edges} reducedMotion={reduced || !pageVisible} />
        {visibleNodes.map((node, index) => <MigrationNode key={node.id} node={node} index={index} onClick={onNodeClick} />)}
      </div>
    </div>
  );
}

export function AnimatedActivityFeed({ events = [], title = "Activity feed", onOpen }) {
  return (
    <div>
      <AnimatedMigrationStyles />
      <div className="flex fjb fac mb3">
        <div className="settings-title" style={{ margin: 0 }}>{title}</div>
        <GraphLegend />
      </div>
      <div className="uma-feed">
        {(events || []).slice(0, 8).map((event, index) => {
          const eventTone = tone(event.status);
          return (
            <button key={event.id || index} type="button" className={`uma-feed-item uma-feed-${eventTone}`} style={{ "--i": index }} onClick={() => onOpen?.(event)}>
              <span className="uma-feed-dot">{eventTone === "validated" ? "✓" : eventTone === "blocked" ? "!" : eventTone === "review" ? "!" : "•"}</span>
              <span>
                <div className="uma-feed-title">{event.title}</div>
                {event.detail ? <div className="uma-feed-detail">{event.detail}</div> : null}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function AnimatedConnectionTest({ connection, result, running = false, checks = [] }) {
  const success = Boolean(result?.success);
  const graphNodes = [
    { id: "uma", label: "UMA", type: "Analysis Layer", x: 18, y: 50, status: running ? "active" : success ? "completed" : result ? "failed" : "pending" },
    { id: "network", label: "Network", type: "Validation Check", x: 48, y: 28, status: running ? "active" : success ? "completed" : result ? "completed" : "pending" },
    { id: "auth", label: "Auth", type: "Validation Check", x: 48, y: 68, status: running ? "active" : success ? "completed" : result ? "failed" : "pending" },
    { id: "target", label: connection?.name || "Endpoint", type: connection?.type === "snowflake" ? "Snowflake Table" : "Source Database", x: 82, y: 50, status: running ? "active" : success ? "completed" : result ? "failed" : "pending" },
  ];
  const graphEdges = [
    { from: "uma", to: "network", status: running ? "active" : success ? "validated" : "review" },
    { from: "network", to: "target", status: running ? "active" : success ? "validated" : "review" },
    { from: "uma", to: "auth", status: running ? "active" : success ? "validated" : result ? "blocked" : "idle" },
    { from: "auth", to: "target", status: running ? "active" : success ? "validated" : result ? "blocked" : "idle" },
  ];
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <AnimatedMigrationGraph nodes={graphNodes} edges={graphEdges} height={190} />
      <AnimatedValidationChecklist checks={checks} />
    </div>
  );
}

export function AnimatedValidationChecklist({ checks = [] }) {
  return (
    <div>
      <AnimatedMigrationStyles />
      <div className="ux-checklist">
        {checks.map((check, index) => {
          const checkTone = tone(check.status);
          return (
            <div className={`ux-check-row ux-check-${checkTone === "validated" ? "success" : checkTone === "blocked" ? "danger" : checkTone === "review" ? "warning" : checkTone}`} key={`${check.label}-${index}`} style={{ "--ux-delay": `${index * 60}ms` }}>
              <span className="ux-check-icon">{checkTone === "validated" ? "✓" : checkTone === "blocked" ? "!" : checkTone === "review" ? "!" : checkTone === "active" ? "↻" : "•"}</span>
              <div className="ux-check-main">
                <div className="ux-check-label">{check.label}</div>
                {check.detail ? <div className="ux-check-detail">{check.detail}</div> : null}
              </div>
              <span className={`ux-status ux-status-${checkTone === "validated" ? "success" : checkTone === "blocked" ? "danger" : checkTone === "review" ? "warning" : checkTone}`}>{check.statusLabel || String(check.status || "pending").replace(/_/g, " ")}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SqlTransformAnimation({ sourceLabel = "Source SQL", targetLabel = "Snowflake SQL", status = "active" }) {
  return (
    <div className="uma-transform-card">
      <AnimatedMigrationStyles />
      <div className="uma-code-card" aria-label={sourceLabel}>
        <div className="stat-label">{sourceLabel}</div>
        <div className="uma-code-line" style={{ width: "88%" }} />
        <div className="uma-code-line" style={{ width: "64%" }} />
        <div className="uma-code-line" style={{ width: "76%" }} />
      </div>
      <div className={`uma-transform-arrow uma-edge-${tone(status)}`} />
      <div className="uma-code-card" aria-label={targetLabel}>
        <div className="stat-label">{targetLabel}</div>
        <div className="uma-code-line" style={{ width: "72%" }} />
        <div className="uma-code-line" style={{ width: "84%" }} />
        <div className="uma-code-line" style={{ width: "58%" }} />
      </div>
    </div>
  );
}

export function AnimatedBrainTranscript({ item, comparison, sections }) {
  const rows = sections || [
    { title: "Blocker first", status: item?.severity || "INFO", body: item?.reason || item?.description || "No blocker selected." },
    { title: "What UMA did", status: "ACTIVE", body: `Analyzed ${item?.source_object || item?.source_file || "the source artifact"} and linked it to ${item?.target_object || "a Snowflake target artifact"}.` },
    { title: "What UMA did not do", status: "WARNING", body: "UMA did not deploy generated SQL or claim Snowflake validation unless a validation run records that evidence." },
    { title: "Recommended next action", status: item?.status || "IN_REVIEW", body: item?.recommendation || "Review the evidence, validate the target artifact, then approve or request rework." },
  ];
  return (
    <div className="uma-brain-transcript">
      <AnimatedMigrationStyles />
      {rows.map((section, index) => (
        <div className="uma-transcript-section" key={section.title} style={{ "--i": index }}>
          <div className="uma-transcript-title">
            <span>{section.title}</span>
            <span className={`ux-status ux-status-${tone(section.status) === "validated" ? "success" : tone(section.status) === "blocked" ? "danger" : tone(section.status) === "review" ? "warning" : "info"}`}>{String(section.status || "INFO").replace(/_/g, " ")}</span>
          </div>
          <div className="uma-transcript-body">{section.body}</div>
        </div>
      ))}
      {comparison ? (
        <details className="uma-transcript-section">
          <summary className="uma-transcript-title">Advanced Details</summary>
          <pre className="pq-code-block">{JSON.stringify(comparison, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}

export function AnimatedEmptyState({ title = "Nothing to show yet", message = "", action = null, compact = false, type = "default" }) {
  const labels = type === "reports"
    ? ["EV", "UMA", "RP"]
    : type === "validation"
      ? ["TB", "VA", "BR"]
      : type === "review"
        ? ["SRC", "UMA", "OK"]
        : ["SRC", "UMA", "SF"];
  return (
    <div className={`empty ${compact ? "pq-empty-compact" : ""}`}>
      <AnimatedMigrationStyles />
      <div className="uma-empty-visual" aria-hidden="true">
        <svg viewBox="0 0 260 112">
          <path className="uma-edge uma-edge-active" d="M60 56 C90 18 124 18 142 34" />
          <path className={`uma-edge ${type === "review" ? "uma-edge-validated" : "uma-edge-review"}`} d="M148 38 C174 56 190 58 218 56" />
        </svg>
        <div className="uma-mini-node n1">{labels[0]}</div>
        <div className="uma-mini-node n2">{labels[1]}</div>
        <div className="uma-mini-node n3">{labels[2]}</div>
      </div>
      <div className="empty-msg" style={{ fontWeight: 800, color: "var(--text2)" }}>{title}</div>
      {message ? <div className="text-muted mt2" style={{ fontSize: 12, maxWidth: 420, marginInline: "auto" }}>{message}</div> : null}
      {action ? <div className="mt3">{action}</div> : null}
    </div>
  );
}

export function ContextDrawer({ open, title, subtitle, status, metadata = [], history = [], graph, actions = null, onClose }) {
  if (!open) return null;
  return (
    <div className="uma-context-overlay" onClick={onClose}>
      <AnimatedMigrationStyles />
      <aside className="uma-context-drawer" onClick={(event) => event.stopPropagation()}>
        <div className="uma-context-head">
          <div>
            <div className="uma-context-title">{title}</div>
            {subtitle ? <div className="uma-context-sub">{subtitle}</div> : null}
          </div>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose}>x</button>
        </div>
        {status ? <div className="uma-context-card"><div className="stat-label">Status</div><div className="info-tile-value">{status}</div></div> : null}
        {graph ? <div className="uma-context-card"><AnimatedMigrationGraph {...graph} height={210} /></div> : null}
        {metadata.length ? (
          <div className="uma-context-card">
            <div className="settings-title">Metadata</div>
            <div className="soft-grid">
              {metadata.map((item, index) => (
                <div key={index} className="info-tile">
                  <div className="stat-label">{item.label}</div>
                  <div className="info-tile-value">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {history.length ? (
          <div className="uma-context-card">
            <div className="settings-title">History</div>
            <AnimatedActivityFeed events={history} title="Related activity" />
          </div>
        ) : null}
        {actions ? <div className="uma-context-card">{actions}</div> : null}
      </aside>
    </div>
  );
}
