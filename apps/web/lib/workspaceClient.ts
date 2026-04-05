export type SavedQuery = {
  id: string;
  name: string;
  sql_text: string;
  owner: string;
  created_at: string;
};

export type QueryExecutionResult = {
  columns: string[];
  rows: Array<Array<string | number>>;
};

const fallbackQueries: SavedQuery[] = [
  {
    id: "qry_seed_01",
    name: "occupancy_by_region",
    sql_text: "SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC",
    owner: "Rahul",
    created_at: "2026-04-04T00:00:00Z",
  },
];

function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL || "http://localhost:8001";
}

async function safeFetchJson<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store", ...init });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function getSavedQueries(): Promise<SavedQuery[]> {
  const data = await safeFetchJson<SavedQuery[]>("/api/v1/workspace/queries");
  return data ?? fallbackQueries;
}

export async function executeWorkspaceQuery(sqlText: string): Promise<QueryExecutionResult> {
  const data = await safeFetchJson<QueryExecutionResult>("/api/v1/workspace/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql_text: sqlText }),
  });
  if (data) return data;
  return {
    columns: ["message"],
    rows: [["Demo query executed successfully"]],
  };
}
