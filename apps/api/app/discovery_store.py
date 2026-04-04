from __future__ import annotations

from .discovery_models import DiscoveryResult, DiscoveryRun, DiscoveryRunCreate, DiscoveryRunSummary


class DiscoveryStore:
    def __init__(self) -> None:
        self.runs: list[DiscoveryRun] = [
            DiscoveryRun.from_create(
                DiscoveryRunCreate(
                    project_id="prj_prologis01",
                    source_platform="Teradata",
                    connector_type="metadata-scan",
                    initiated_by="Rahul",
                )
            )
        ]
        self.runs[0].status = "Completed"
        self.results: list[DiscoveryResult] = [
            DiscoveryResult(id="res_001", run_id=self.runs[0].id, object_type="Table", schema_name="leasing", object_name="tenant_dim", complexity="Low", dependency_count=1),
            DiscoveryResult(id="res_002", run_id=self.runs[0].id, object_type="Table", schema_name="leasing", object_name="lease_fact", complexity="High", dependency_count=4),
            DiscoveryResult(id="res_003", run_id=self.runs[0].id, object_type="View", schema_name="mart", object_name="occupancy_by_region", complexity="Medium", dependency_count=2),
        ]

    def list_runs(self) -> list[DiscoveryRun]:
        return self.runs

    def create_run(self, payload: DiscoveryRunCreate) -> DiscoveryRun:
        run = DiscoveryRun.from_create(payload)
        self.runs.append(run)
        return run

    def get_run(self, run_id: str) -> DiscoveryRun | None:
        return next((run for run in self.runs if run.id == run_id), None)

    def list_results(self, run_id: str) -> list[DiscoveryResult]:
        return [result for result in self.results if result.run_id == run_id]

    def get_summary(self, run_id: str) -> DiscoveryRunSummary | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        results = self.list_results(run_id)
        return DiscoveryRunSummary(
            run_id=run.id,
            object_count=len(results),
            high_complexity_count=sum(1 for item in results if item.complexity == "High"),
            dependency_edges=sum(item.dependency_count for item in results),
        )


store = DiscoveryStore()
