export type StatefulProjectCreate = {
  name: string;
  description: string;
  source_platform: string;
  target_platform: "Snowflake" | "Databricks";
  owner: string;
};

export type StatefulSavedQueryCreate = {
  name: string;
  sql_text: string;
  owner: string;
};

function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_STATEFUL_API_BASE_URL || "http://localhost:8003";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function createStatefulProject(payload: StatefulProjectCreate) {
  return requestJson("/api/stateful/v1/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createStatefulQuery(payload: StatefulSavedQueryCreate) {
  return requestJson("/api/stateful/v1/workspace/queries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeStatefulQuery(sqlText: string) {
  return requestJson("/api/stateful/v1/workspace/execute", {
    method: "POST",
    body: JSON.stringify({ sql_text: sqlText }),
  });
}
