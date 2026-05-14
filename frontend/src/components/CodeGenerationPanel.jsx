import React, { useEffect, useState } from "react";
import * as api from "../api";
import EmptyState from "./EmptyState.jsx";
import ErrorPanel from "./ErrorPanel.jsx";
import ResultGrid from "./ResultGrid.jsx";
import StatusBadge from "./StatusBadge.jsx";
import { fmtDate, getErrorMessage } from "./format.js";

function parseJson(text) {
  if (!text.trim()) return {};
  return JSON.parse(text);
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

export default function CodeGenerationPanel() {
  const [artifacts, setArtifacts] = useState([]);
  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const [draft, setDraft] = useState({
    generation_type: "DDL",
    prompt: "",
    source_code: "",
    metadataText: "{}",
  });
  const [reviewDraft, setReviewDraft] = useState({
    score: 3,
    status: "NEEDS_IMPROVEMENT",
    improvementText: "",
    blockingText: "",
    notes: "",
  });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const loadArtifacts = async () => {
    try {
      const rows = await api.listCodeGenerationArtifacts().catch(() => []);
      setArtifacts(rows || []);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    }
  };

  useEffect(() => { loadArtifacts(); }, []);

  const openArtifact = async (artifact) => {
    setError("");
    setSelectedArtifact(artifact);
    try {
      const detail = artifact.id ? await api.getCodeGenerationArtifact(artifact.id).catch(() => artifact) : artifact;
      setSelectedArtifact(detail);
    } catch (detailError) {
      setError(getErrorMessage(detailError));
    }
  };

  const generate = async () => {
    setBusy("generate");
    setError("");
    try {
      const result = await api.codeGeneration({
        generation_type: draft.generation_type,
        prompt: draft.prompt,
        source_code: draft.source_code,
        metadata: parseJson(draft.metadataText),
      });
      setSelectedArtifact(result);
      await loadArtifacts();
    } catch (generateError) {
      setError(getErrorMessage(generateError));
    } finally {
      setBusy("");
    }
  };

  const submitJudgePass = async () => {
    if (!selectedArtifact?.id) return;
    setBusy("judge");
    setError("");
    try {
      const result = await api.submitJudgePass(selectedArtifact.id, {
        score: Number(reviewDraft.score),
        status: reviewDraft.status,
        improvement_points: reviewDraft.improvementText.split("\n").map((item) => item.trim()).filter(Boolean),
        blocking_issues: reviewDraft.blockingText.split("\n").map((item) => item.trim()).filter(Boolean),
        notes: reviewDraft.notes,
      });
      setSelectedArtifact(result);
      await loadArtifacts();
    } catch (judgeError) {
      setError(getErrorMessage(judgeError));
    } finally {
      setBusy("");
    }
  };

  const revise = async () => {
    if (!selectedArtifact?.id) return;
    setBusy("revise");
    setError("");
    try {
      const result = await api.reviseCodeGenerationArtifact(selectedArtifact.id, {});
      setSelectedArtifact(result);
      await loadArtifacts();
    } catch (reviseError) {
      setError(getErrorMessage(reviseError));
    } finally {
      setBusy("");
    }
  };

  const artifact = selectedArtifact;
  const tdd = artifact?.technical_design_document || {};
  const assessment = artifact?.automated_assessment || artifact?.judge_pass_review || {};

  return (
    <div className="pq-codegen-grid">
      <div className="card pq-codegen-sidebar">
        <div className="card-header"><div><div className="card-title">Generate Review Artifact</div><div className="row-subtext">Generation creates review material only. It does not execute generated code.</div></div></div>
        <div style={{ padding: 16 }}>
          <ErrorPanel error={error} />
          <div className="fg">
            <label className="fl">Generation Type</label>
            <select className="fi" value={draft.generation_type} onChange={(event) => setDraft((state) => ({ ...state, generation_type: event.target.value }))}>
              <option value="DDL">DDL</option>
              <option value="DML">DML</option>
              <option value="SQL">SQL</option>
              <option value="DBT_MODEL">dbt Model</option>
              <option value="DBT_PROJECT">dbt Project</option>
              <option value="AIRFLOW_DAG">Airflow DAG</option>
              <option value="SQL_TO_PYSPARK">SQL to PySpark</option>
              <option value="PYTHON_TO_SNOWPARK">Python to Snowpark</option>
              <option value="PLSQL_TO_STORED_PROCEDURE">PL/SQL to Stored Procedure</option>
            </select>
          </div>
          <div className="fg"><label className="fl">Source Input / Request</label><textarea className="fi" rows={4} value={draft.prompt} onChange={(event) => setDraft((state) => ({ ...state, prompt: event.target.value }))} /></div>
          <div className="fg"><label className="fl">Source Code</label><textarea className="fi" rows={8} value={draft.source_code} onChange={(event) => setDraft((state) => ({ ...state, source_code: event.target.value }))} placeholder="Paste source SQL, Python, PL/SQL, BTEQ, or ETL code." /></div>
          <div className="fg"><label className="fl">Basis Metadata JSON</label><textarea className="fi" rows={5} value={draft.metadataText} onChange={(event) => setDraft((state) => ({ ...state, metadataText: event.target.value }))} /></div>
          <button className="btn btn-primary" style={{ width: "100%" }} onClick={generate} disabled={busy === "generate"}>{busy === "generate" ? <span className="spin">↻</span> : "Generate Review Artifact"}</button>
        </div>
        <div className="pq-side-section">
          <div className="pq-detail-section-title">Recent Artifacts</div>
          {!artifacts.length ? <EmptyState compact title="No saved artifacts" /> : artifacts.slice(0, 8).map((item) => (
            <button key={item.id} className="pq-list-button" onClick={() => openArtifact(item)}>
              <span>{item.generation_type || "Artifact"} · {item.status || "Generated"}</span>
              <span>{fmtDate(item.created_at)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="pq-detail-panel">
        {!artifact ? (
          <EmptyState title="Select or generate an artifact" message="Artifact detail will show source input, generated code, TDD, assessment, Judge Pass, revisions, approval status, and generation basis." />
        ) : (
          <>
            <div className="pq-detail-header">
              <div>
                <div className="pq-eyebrow">Code Generation / TDD / Judge Pass</div>
                <div className="pq-detail-title">{artifact.generation_type || "Generated Artifact"}</div>
                <div className="pq-detail-subtitle">Basis: {String(artifact.basis_for_generation || "user_prompt_only").replace(/_/g, " ")} · Revision v{artifact.revision_number || 1}</div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <StatusBadge status={artifact.approval_status || artifact.status || "DRAFT"} />
                <StatusBadge status="NOT_CHECKED" label="Generated code executed: No" />
              </div>
            </div>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Source Input</div>
              <pre className="pq-code-block">{artifact.prompt || artifact.source_input || draft.prompt || "No prompt persisted."}</pre>
              {artifact.source_code && <pre className="pq-code-block mt3">{artifact.source_code}</pre>}
            </section>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Generated Code</div>
              <pre className="pq-code-block">{artifact.generated_code || "No generated code persisted."}</pre>
            </section>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Technical Design Document</div>
              <div className="pq-kpi-grid">
                <div className="info-tile"><div className="text-muted">Objective</div><div className="info-tile-value">{tdd.objective || "Not recorded"}</div></div>
                <div className="info-tile"><div className="text-muted">Approval Status</div><div className="info-tile-value">{artifact.approval_status || artifact.status || "Not reviewed"}</div></div>
              </div>
              <ResultGrid
                columns={["section", "detail"]}
                rows={[
                  ...list(tdd.scope).map((item, index) => ({ section: `Scope ${index + 1}`, detail: item })),
                  ...list(tdd.assumptions).map((item, index) => ({ section: `Assumption ${index + 1}`, detail: item })),
                  ...list(tdd.validation_plan).map((item, index) => ({ section: `Validation ${index + 1}`, detail: item })),
                ]}
                emptyTitle="No TDD detail persisted"
              />
            </section>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Automated Assessment</div>
              <div className="pq-kpi-grid">
                <div className="info-tile"><div className="text-muted">Initial Score</div><div className="info-tile-value">{assessment.initial_score ?? assessment.score ?? "Not scored"}</div></div>
                <div className="info-tile"><div className="text-muted">Status</div><div className="info-tile-value">{assessment.status || "Not assessed"}</div></div>
                <div className="info-tile"><div className="text-muted">Execution</div><div className="info-tile-value">Generated code executed: No</div></div>
                <div className="info-tile"><div className="text-muted">Basis</div><div className="info-tile-value">{artifact.basis_for_generation || "user_prompt_only"}</div></div>
              </div>
            </section>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Human Judge Pass Review</div>
              <ResultGrid
                columns={["type", "item"]}
                rows={[
                  ...list(assessment.improvement_points).map((item) => ({ type: "Improvement point", item })),
                  ...list(assessment.blocking_issues).map((item) => ({ type: "Blocking issue", item })),
                  ...list(artifact.latest_review?.improvement_points).map((item) => ({ type: "Human improvement", item })),
                  ...list(artifact.latest_review?.blocking_issues).map((item) => ({ type: "Human blocking issue", item })),
                ]}
                emptyTitle="No Judge Pass issues recorded"
              />
              <div className="pq-review-form">
                <div className="fg"><label className="fl">Score</label><select className="fi" value={reviewDraft.score} onChange={(event) => setReviewDraft((state) => ({ ...state, score: event.target.value }))}>{[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score}</option>)}</select></div>
                <div className="fg"><label className="fl">Status</label><select className="fi" value={reviewDraft.status} onChange={(event) => setReviewDraft((state) => ({ ...state, status: event.target.value }))}><option value="NEEDS_IMPROVEMENT">NEEDS_IMPROVEMENT</option><option value="APPROVED_WITH_NOTES">APPROVED_WITH_NOTES</option><option value="APPROVED">APPROVED</option><option value="BLOCKED">BLOCKED</option></select></div>
                <div className="fg"><label className="fl">Improvement Points</label><textarea className="fi" rows={3} value={reviewDraft.improvementText} onChange={(event) => setReviewDraft((state) => ({ ...state, improvementText: event.target.value }))} /></div>
                <div className="fg"><label className="fl">Blocking Issues</label><textarea className="fi" rows={3} value={reviewDraft.blockingText} onChange={(event) => setReviewDraft((state) => ({ ...state, blockingText: event.target.value }))} /></div>
                <div className="fg"><label className="fl">Notes</label><textarea className="fi" rows={3} value={reviewDraft.notes} onChange={(event) => setReviewDraft((state) => ({ ...state, notes: event.target.value }))} /></div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="btn btn-primary" onClick={submitJudgePass} disabled={busy === "judge" || !artifact.id}>{busy === "judge" ? <span className="spin">↻</span> : "Save Judge Pass"}</button>
                  <button className="btn btn-ghost" onClick={revise} disabled={busy === "revise" || !artifact.id}>{busy === "revise" ? <span className="spin">↻</span> : "Regenerate Revised Artifact"}</button>
                </div>
              </div>
            </section>

            <section className="pq-detail-section">
              <div className="pq-detail-section-title">Revision History</div>
              <ResultGrid
                columns={["revision", "status", "created"]}
                rows={list(artifact.revision_history).map((revision) => ({ revision: `v${revision.revision_number}`, status: revision.status, created: fmtDate(revision.created_at) }))}
                emptyTitle="No revision history"
              />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
