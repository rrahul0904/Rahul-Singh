from __future__ import annotations

from .workspace_models import ExecuteQueryRequest, QueryExecutionResult, SavedQuery, SavedQueryCreate


class WorkspaceStore:
    def __init__(self) -> None:
        self.queries: list[SavedQuery] = [
            SavedQuery.from_create(
                SavedQueryCreate(
                    name="occupancy_by_region",
                    sql_text="SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC",
                    owner="Rahul",
                )
            )
        ]

    def list_queries(self) -> list[SavedQuery]:
        return self.queries

    def create_query(self, payload: SavedQueryCreate) -> SavedQuery:
        query = SavedQuery.from_create(payload)
        self.queries.append(query)
        return query

    def get_query(self, query_id: str) -> SavedQuery | None:
        return next((query for query in self.queries if query.id == query_id), None)

    def execute(self, payload: ExecuteQueryRequest) -> QueryExecutionResult:
        sql = payload.sql_text.lower()
        if "occupancy" in sql:
            return QueryExecutionResult(columns=["region", "occupancy_rate"], rows=[["West", 96.1], ["South", 92.8], ["Midwest", 90.7]])
        if "tenant" in sql and "revenue" in sql:
            return QueryExecutionResult(columns=["tenant_name", "total_revenue"], rows=[["Amazon", 12400000], ["FedEx", 11750000], ["Target", 9650000]])
        return QueryExecutionResult(columns=["message"], rows=[["Demo query executed successfully"]])


store = WorkspaceStore()
