export type DiscoveryRun = {
  id: string;
  project_id: string;
  source_platform: string;
  connector_type: string;
  status: "Created" | "Running" | "Completed" | "Failed";
  initiated_by: string;
  created_at: string;
};

export type DiscoveryResult = {
  id: string;
  run_id: string;
  object_type: string;
  schema_name: string;
  object_name: string;
  complexity: "Low" | "Medium" | "High";
  dependency_count: number;
};

export type DiscoverySummary = {
  run_id: string;
  object_count: number;
  high_complexity_count: number;
  dependency_edges: number;
};

const fallbackRunId = "run_seed_demo";

const fallbackRuns: DiscoveryRun[] = [
  {
    id: fallbackRunId,
    project_id: "prj_prologis01",
    source_platform: "Teradata",
    connector_type: "metadata-scan",
    status: "Completed",
    initiated_by: "Rahul",
    created_at: "2026-04-04T00:00:00Z",
  },
];

const fallbackResults: DiscoveryResult[] = [
  {
    id: "res_001",
    run_id: fallbackRunId,
    object_type: "Table",
    schema_name: "leasing",
    object_name: "tenant_dim",
    complexity: "Low",
    dependency_count: 1,
  },
  {
    id: "res_002",
    run_id: fallbackRunId,
    object_type: "Table",
    schema_name: "leasing",
    object_name: "lease_fact",
    complexity: "High",
    dependency_count: 4,
  },
  {
    id: "res_003",
    run_id: fallbackRunId,
    object_type: "View",
    schema_name: "mart",
    object_name: "occupancy_by_region",
    complexity: "Medium",
    dependency_count: 2,
  },
];

function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL || "http://localhost:8001";
}

async function safeFetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function getDiscoveryRuns(): Promise<DiscoveryRun[]> {
  const data = await safeFetchJson<DiscoveryRun[]>("/api/v1/discovery/runs");
  return data ?? fallbackRuns;
}

export async function getDiscoveryRun(runId: string): Promise<DiscoveryRun | null> {
  const data = await safeFetchJson<DiscoveryRun>(`/api/v1/discovery/runs/${runId}`);
  return data ?? fallbackRuns.find((run) => run.id === runId) ?? null;
}

export async function getDiscoveryResults(runId: string): Promise<DiscoveryResult[]> {
  const data = await safeFetchJson<DiscoveryResult[]>(`/api/v1/discovery/runs/${runId}/results`);
  return data ?? fallbackResults.filter((item) => item.run_id === runId);
}

export async function getDiscoverySummary(runId: string): Promise<DiscoverySummary | null> {
  const data = await safeFetchJson<DiscoverySummary>(`/api/v1/discovery/runs/${runId}/summary`);
  if (data) return data;
  const results = fallbackResults.filter((item) => item.run_id === runId);
  if (!results.length) return null;
  return {
    run_id: runId,
    object_count: results.length,
    high_complexity_count: results.filter((item) => item.complexity === "High").length,
    dependency_edges: results.reduce((sum, item) => sum + item.dependency_count, 0),
  };
}
