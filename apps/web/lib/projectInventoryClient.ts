export type Project = {
  id: string;
  name: string;
  description: string;
  source_platform: string;
  target_platform: "Snowflake" | "Databricks";
  owner: string;
  status: string;
  progress: number;
  created_at: string;
};

export type ProjectSummary = {
  project_id: string;
  project_name: string;
  total_inventory_items: number;
  discovered_tables: number;
  discovered_views: number;
  items_needing_review: number;
};

export type InventoryItem = {
  id: string;
  project_id: string;
  object_type: string;
  schema_name: string;
  object_name: string;
  status: string;
  complexity: "Low" | "Medium" | "High";
};

const fallbackProjects: Project[] = [
  {
    id: "prj_prologis01",
    name: "Prologis Leasing Migration",
    description: "Migration of leasing analytics workloads into Snowflake.",
    source_platform: "Teradata",
    target_platform: "Snowflake",
    owner: "Rahul",
    status: "In Validation",
    progress: 72,
    created_at: "2026-04-04T00:00:00Z",
  },
  {
    id: "prj_revops01",
    name: "RevOps Modernization",
    description: "Migration of reporting datasets into Databricks.",
    source_platform: "SQL Server",
    target_platform: "Databricks",
    owner: "Rahul",
    status: "In Conversion",
    progress: 48,
    created_at: "2026-04-04T00:00:00Z",
  },
];

const fallbackInventory: InventoryItem[] = [
  { id: "inv_001", project_id: "prj_prologis01", object_type: "Table", schema_name: "leasing", object_name: "tenant_dim", status: "Discovered", complexity: "Low" },
  { id: "inv_002", project_id: "prj_prologis01", object_type: "Table", schema_name: "leasing", object_name: "lease_fact", status: "Needs Review", complexity: "High" },
  { id: "inv_003", project_id: "prj_prologis01", object_type: "View", schema_name: "mart", object_name: "occupancy_by_region", status: "Discovered", complexity: "Medium" },
  { id: "inv_004", project_id: "prj_revops01", object_type: "Table", schema_name: "sales", object_name: "opportunity_fact", status: "Discovered", complexity: "Medium" },
  { id: "inv_005", project_id: "prj_revops01", object_type: "View", schema_name: "sales", object_name: "revenue_rollup", status: "Needs Review", complexity: "High" },
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

export async function getProjects(): Promise<Project[]> {
  const data = await safeFetchJson<Project[]>("/api/v1/projects");
  return data ?? fallbackProjects;
}

export async function getProject(projectId: string): Promise<Project | null> {
  const data = await safeFetchJson<Project>(`/api/v1/projects/${projectId}`);
  return data ?? fallbackProjects.find((project) => project.id === projectId) ?? null;
}

export async function getProjectSummary(projectId: string): Promise<ProjectSummary | null> {
  const data = await safeFetchJson<ProjectSummary>(`/api/v1/projects/${projectId}/summary`);
  if (data) return data;
  const project = fallbackProjects.find((item) => item.id === projectId);
  if (!project) return null;
  const items = fallbackInventory.filter((item) => item.project_id === projectId);
  return {
    project_id: project.id,
    project_name: project.name,
    total_inventory_items: items.length,
    discovered_tables: items.filter((item) => item.object_type === "Table").length,
    discovered_views: items.filter((item) => item.object_type === "View").length,
    items_needing_review: items.filter((item) => item.status === "Needs Review").length,
  };
}

export async function getProjectInventory(projectId: string): Promise<InventoryItem[]> {
  const data = await safeFetchJson<InventoryItem[]>(`/api/v1/projects/${projectId}/inventory`);
  return data ?? fallbackInventory.filter((item) => item.project_id === projectId);
}
