from __future__ import annotations

from .stateful_storage import load_records, save_records
from .workspace_models import ExecuteQueryRequest, QueryExecutionResult, SavedQuery, SavedQueryCreate

QUERIES_FILE = "workspace_queries.json"


class PersistentWorkspaceStore:
    def __init__(self) -> None:
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        if not load_records(QUERIES_FILE):
            save_records(
                QUERIES_FILE,
                [
                    SavedQuery.from_create(
                        SavedQueryCreate(
                            name="occupancy_by_region",
                            sql_text="SELECT region, occupancy_rate FROM mart_occupancy ORDER BY occupancy_rate DESC",
                            owner="Rahul",
                        )
                    ).model_dump(mode="json")
                ],
            )

    def list_queries(self) -> list[SavedQuery]:
        return [SavedQuery(**row) for row in load_records(QUERIES_FILE)]

    def create_query(self, payload: SavedQueryCreate) -> SavedQuery:
        query = SavedQuery.from_create(payload)
        rows = load_records(QUERIES_FILE)
        rows.append(query.model_dump(mode="json"))
        save_records(QUERIES_FILE, rows)
        return query

    def get_query(self, query_id: str) -> SavedQuery | None:
        return next((query for query in self.list_queries() if query.id == query_id), None)

    def execute(self, payload: ExecuteQueryRequest) -> QueryExecutionResult:
        sql = payload.sql_text.lower()
        if "occupancy" in sql:
            return QueryExecutionResult(columns=["region", "occupancy_rate"], rows=[["West", 96.1], ["South", 92.8], ["Midwest", 90.7]])
        if "tenant" in sql and "revenue" in sql:
            return QueryExecutionResult(columns=["tenant_name", "total_revenue"], rows=[["Amazon", 12400000], ["FedEx", 11750000], ["Target", 9650000]])
        return QueryExecutionResult(columns=["message"], rows=[["Persistent demo query executed successfully"]])


store = PersistentWorkspaceStore()
