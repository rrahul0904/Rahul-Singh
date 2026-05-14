import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MigrationIntelligencePage from "./MigrationIntelligencePage.jsx";

vi.mock("../api", () => ({
  getConnections: vi.fn(),
  listIntelligenceArtifacts: vi.fn(),
  getIntelligenceArtifact: vi.fn(),
  uploadIntelligenceArtifact: vi.fn(),
  createIntelligenceRun: vi.fn(),
  listIntelligenceRuns: vi.fn(),
  getIntelligenceRun: vi.fn(),
  getIntelligenceRunSteps: vi.fn(),
  getIntelligenceRunFindings: vi.fn(),
  getIntelligenceReport: vi.fn(),
  previewIntelligenceReport: vi.fn(),
  downloadIntelligenceReport: vi.fn(),
}));

const api = await import("../api");

function buildArtifact(id, fileName) {
  return {
    id,
    file_name: fileName,
    file_type: "sql",
    mime_type: "text/plain",
    size_bytes: 24,
    extraction_status: "CLASSIFIED",
    classification: "SQL",
    language_guess: "sql",
    source_system_guess: "Generic SQL",
    extracted_text_preview: "CREATE TABLE raw.orders (id INT);",
    chunks: [],
    created_at: "2026-04-29T12:00:00",
  };
}

function buildRun(id, reportId, selectedArtifactIds = []) {
  return {
    id,
    report_id: reportId,
    status: "COMPLETED",
    agent_mode: "deterministic_local",
    selected_artifact_ids: selectedArtifactIds,
    openai_called: false,
    snowflake_cortex_called: false,
    snowflake_sql_executed: false,
    uploaded_sql_executed: false,
    generated_code_executed: false,
    ddl_executed: false,
    data_moved: false,
    latest_error: null,
    started_at: "2026-04-29T12:00:00",
    completed_at: "2026-04-29T12:05:00",
  };
}

function buildReport(id, runId, title) {
  return {
    id,
    run_id: runId,
    title,
    created_at: "2026-04-29T12:05:00",
    report_markdown: `# ${title}\n`,
    report_json: {
      flags: {
        openai_called: false,
        snowflake_cortex_called: false,
        snowflake_sql_executed: false,
      },
      sections: [
        { title: "Executive Summary", content: ["Summary"] },
        { title: "Inputs Analyzed", content: ["orders.sql"] },
        { title: "SQL / Procedure / DDL Inventory", content: ["Tables: raw.orders", "Views: None detected", "Procedures: None detected"] },
        { title: "Recommended Next Actions", content: ["Review output"] },
        { title: "Technical Design Document", content: ["TDD"] },
        { title: "Judge Pass Review Scaffold", content: ["Scaffold"] },
        { title: "Appendix: Evidence", content: ["Evidence"] },
      ],
    },
  };
}

function configureApi({
  artifacts = [buildArtifact("artifact-1", "orders.sql")],
  runs = [],
  reports = {},
  previews = {},
} = {}) {
  api.getConnections.mockResolvedValue([]);
  api.listIntelligenceArtifacts.mockResolvedValue(artifacts);
  api.listIntelligenceRuns.mockResolvedValue(runs);
  api.getIntelligenceArtifact.mockImplementation(async (id) => artifacts.find((artifact) => artifact.id === id) || null);
  api.uploadIntelligenceArtifact.mockImplementation(async () => buildArtifact("artifact-uploaded", "new.sql"));
  api.createIntelligenceRun.mockResolvedValue(buildRun("run-created", "report-created", artifacts.map((artifact) => artifact.id)));
  api.getIntelligenceRun.mockImplementation(async (id) => runs.find((run) => run.id === id) || buildRun(id, null, artifacts.map((artifact) => artifact.id)));
  api.getIntelligenceRunSteps.mockResolvedValue([]);
  api.getIntelligenceRunFindings.mockResolvedValue([]);
  api.getIntelligenceReport.mockImplementation(async (id) => reports[id] || buildReport(id, "run-1", `Report ${id}`));
  api.previewIntelligenceReport.mockImplementation(async (id) => previews[id] || { report_markdown: `# ${id}\n`, flags: { openai_called: false, snowflake_cortex_called: false, snowflake_sql_executed: false } });
  api.downloadIntelligenceReport.mockResolvedValue("report.docx");
}

describe("MigrationIntelligencePage", () => {
  beforeEach(() => {
    configureApi();
  });

  afterEach(() => {
    vi.clearAllMocks();
    cleanup();
  });

  it("validates upload selection and sends multipart upload for supported files", async () => {
    render(<MigrationIntelligencePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Uploads" }));

    const input = screen.getByTestId("artifact-upload-input");
    fireEvent.change(input, { target: { files: [new File([""], "empty.sql", { type: "text/plain" })] } });
    expect(await screen.findByText(/is empty\. Upload a non-empty artifact/i)).toBeInTheDocument();

    api.uploadIntelligenceArtifact.mockResolvedValueOnce(buildArtifact("artifact-2", "uploaded.sql"));
    api.listIntelligenceArtifacts.mockResolvedValueOnce([
      buildArtifact("artifact-2", "uploaded.sql"),
      buildArtifact("artifact-1", "orders.sql"),
    ]);
    fireEvent.change(input, { target: { files: [new File(["select 1;"], "uploaded.sql", { type: "text/plain" })] } });

    await waitFor(() => expect(api.uploadIntelligenceArtifact).toHaveBeenCalledTimes(1));
    const sentFormData = api.uploadIntelligenceArtifact.mock.calls[0][0];
    expect(sentFormData.get("file").name).toBe("uploaded.sql");
    expect((await screen.findAllByText("uploaded.sql")).length).toBeGreaterThan(0);
  });

  it("keeps the run button disabled until an artifact is selected", async () => {
    render(<MigrationIntelligencePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Uploads" }));

    const runButton = await screen.findByTestId("run-intelligence-button");
    expect(runButton).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(runButton).toBeEnabled());
  });

  it("switches report preview when a different persisted report is selected", async () => {
    const runA = buildRun("run-a", "report-a", ["artifact-1"]);
    const runB = buildRun("run-b", "report-b", ["artifact-1"]);
    configureApi({
      runs: [runA, runB],
      reports: {
        "report-a": buildReport("report-a", "run-a", "Report A"),
        "report-b": buildReport("report-b", "run-b", "Report B"),
      },
      previews: {
        "report-a": { report_markdown: "# Report A\n", flags: { openai_called: false, snowflake_cortex_called: false, snowflake_sql_executed: false } },
        "report-b": { report_markdown: "# Report B\n", flags: { openai_called: false, snowflake_cortex_called: false, snowflake_sql_executed: false } },
      },
    });

    render(<MigrationIntelligencePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Report Preview" }));

    expect(await screen.findByText("Report A")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /report-b/i }));
    expect(await screen.findByText("Report B")).toBeInTheDocument();
  });

  it("disables the download button while a download is in progress", async () => {
    let resolveDownload;
    api.listIntelligenceRuns.mockResolvedValue([buildRun("run-a", "report-a", ["artifact-1"])]);
    api.getIntelligenceRun.mockResolvedValue(buildRun("run-a", "report-a", ["artifact-1"]));
    api.getIntelligenceReport.mockResolvedValue(buildReport("report-a", "run-a", "Report A"));
    api.previewIntelligenceReport.mockResolvedValue({ report_markdown: "# Report A\n", flags: { openai_called: false, snowflake_cortex_called: false, snowflake_sql_executed: false } });
    api.downloadIntelligenceReport.mockImplementation(() => new Promise((resolve) => { resolveDownload = resolve; }));

    render(<MigrationIntelligencePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Report Preview" }));

    const downloadButton = await screen.findByTestId("download-docx-button");
    fireEvent.click(downloadButton);
    await waitFor(() => expect(downloadButton).toBeDisabled());

    resolveDownload("report-a.docx");
    await waitFor(() => expect(downloadButton).toBeEnabled());
  });
});
