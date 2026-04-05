export type ValidationRun = {
  id: string;
  project_id: string;
  source_env: string;
  target_env: string;
  status: "Created" | "Running" | "Completed" | "Failed";
  initiated_by: string;
  created_at: string;
};

export type ValidationResult = {
  id: string;
  run_id: string;
  object_name: string;
  rule_type: string;
  severity: "Low" | "Medium" | "High";
  result_status: "Passed" | "Warning" | "Failed";
};

const fallbackRuns: ValidationRun[] = [
  {
    id: "val_seed_01",
    project_id: "prj_prologis01",
    source_env: "bigquery-test",
    target_env: "snowflake-test",
    status: "Completed",
    initiated_by: "Rahul",
    created_at: "2026-04-04T00:00:00Z"
  }
];

const fallbackResults: ValidationResult[] = [
  { id: "vr_001", run_id: "val_seed_01", object_name: "tenant_dim", rule_type: "row_count_parity", severity: "High", result_status: "Failed" },
  { id: "vr_002", run_id: "val_seed_01", object_name: "lease_fact", rule_type: "schema_match", severity: "Medium", result_status: "Warning" },
  { id: "vr_003", run_id: "val_seed_01", object_name: "occupancy_by_region", rule_type: "null_check", severity: "Low", result_status: "Passed" }
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

export async function getValidationRuns(): Promise<ValidationRun[]> {
  const data = await safeFetchJson<ValidationRun[]>("/api/v1/validation/runs");
  return data ?? fallbackRuns;
}

export async function getValidationResults(runId: string): Promise<ValidationResult[]> {
  const data = await safeFetchJson<ValidationResult[]>(`/api/v1/validation/runs/${runId}/results`);
  return data ?? fallbackResults.filter((item) => item.run_id === runId);
}
