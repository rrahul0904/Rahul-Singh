export type ConversionItem = {
  id: string;
  project_id: string;
  source_object_name: string;
  source_type: string;
  target_type: string;
  status: "Draft" | "Review" | "Approved" | "Blocked";
  risk: "Low" | "Medium" | "High";
  created_by: string;
  created_at: string;
};

const fallbackItems: ConversionItem[] = [
  {
    id: "cnv_seed_01",
    project_id: "prj_prologis01",
    source_object_name: "tenant_revenue_rollup",
    source_type: "Teradata View",
    target_type: "Snowflake SQL",
    status: "Review",
    risk: "Medium",
    created_by: "Rahul",
    created_at: "2026-04-04T00:00:00Z",
  },
  {
    id: "cnv_seed_02",
    project_id: "prj_revops01",
    source_object_name: "lease_expiry_projection",
    source_type: "ADF Pipeline",
    target_type: "Databricks Job",
    status: "Approved",
    risk: "Low",
    created_by: "Rahul",
    created_at: "2026-04-04T00:00:00Z",
  }
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

export async function getConversionItems(): Promise<ConversionItem[]> {
  const data = await safeFetchJson<ConversionItem[]>("/api/v1/conversion/items");
  return data ?? fallbackItems;
}
