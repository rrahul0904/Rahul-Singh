from __future__ import annotations

from .discovery_models import DiscoveryResult, DiscoveryRun, DiscoveryRunCreate, DiscoveryRunSummary
from .stateful_storage import load_records, save_records

DISCOVERY_RUNS_FILE = "discovery_runs.json"
DISCOVERY_RESULTS_FILE = "discovery_results.json"


class PersistentDiscoveryStore:
    def __init__(self) -> None:
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        if not load_records(DISCOVERY_RUNS_FILE):
            seed_run = DiscoveryRun.from_create(
                DiscoveryRunCreate(
                    project_id="prj_prologis01",
                    source_platform="Teradata",
                    connector_type="metadata-scan",
                    initiated_by="Rahul",
                )
            )
            seed_run.status = "Completed"
            save_records(DISCOVERY_RUNS_FILE, [seed_run.model_dump(mode="json")])
            save_records(
                DISCOVERY_RESULTS_FILE,
                [
                    DiscoveryResult(id="res_001", run_id=seed_run.id, object_type="Table", schema_name="leasing", object_name="tenant_dim", complexity="Low", dependency_count=1).model_dump(),
                    DiscoveryResult(id="res_002", run_id=seed_run.id, object_type="Table", schema_name="leasing", object_name="lease_fact", complexity="High", dependency_count=4).model_dump(),
                    DiscoveryResult(id="res_003", run_id=seed_run.id, object_type="View", schema_name="mart", object_name="occupancy_by_region", complexity="Medium", dependency_count=2).model_dump(),
                ],
            )

    def list_runs(self) -> list[DiscoveryRun]:
        return [DiscoveryRun(**row) for row in load_records(DISCOVERY_RUNS_FILE)]

    def create_run(self, payload: DiscoveryRunCreate) -> DiscoveryRun:
        run = DiscoveryRun.from_create(payload)
        rows = load_records(DISCOVERY_RUNS_FILE)
        rows.append(run.model_dump(mode="json"))
        save_records(DISCOVERY_RUNS_FILE, rows)
        return run

    def get_run(self, run_id: str) -> DiscoveryRun | None:
        return next((run for run in self.list_runs() if run.id == run_id), None)

    def list_results(self, run_id: str) -> list[DiscoveryResult]:
        return [DiscoveryResult(**row) for row in load_records(DISCOVERY_RESULTS_FILE) if row["run_id"] == run_id]

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


store = PersistentDiscoveryStore()
