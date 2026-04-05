from __future__ import annotations

from .stateful_storage import load_records, save_records
from .validation_models import ValidationResult, ValidationRun, ValidationRunCreate, ValidationSummary

VALIDATION_RUNS_FILE = "validation_runs.json"
VALIDATION_RESULTS_FILE = "validation_results.json"


class PersistentValidationStore:
    def __init__(self) -> None:
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        if not load_records(VALIDATION_RUNS_FILE):
            run = ValidationRun.from_create(
                ValidationRunCreate(
                    project_id="prj_prologis01",
                    source_env="bigquery-test",
                    target_env="snowflake-test",
                    initiated_by="Rahul",
                )
            )
            run.status = "Completed"
            save_records(VALIDATION_RUNS_FILE, [run.model_dump(mode="json")])
            save_records(
                VALIDATION_RESULTS_FILE,
                [
                    ValidationResult(id="vr_001", run_id=run.id, object_name="tenant_dim", rule_type="row_count_parity", severity="High", result_status="Failed").model_dump(),
                    ValidationResult(id="vr_002", run_id=run.id, object_name="lease_fact", rule_type="schema_match", severity="Medium", result_status="Warning").model_dump(),
                    ValidationResult(id="vr_003", run_id=run.id, object_name="occupancy_by_region", rule_type="null_check", severity="Low", result_status="Passed").model_dump(),
                ],
            )

    def list_runs(self) -> list[ValidationRun]:
        return [ValidationRun(**row) for row in load_records(VALIDATION_RUNS_FILE)]

    def create_run(self, payload: ValidationRunCreate) -> ValidationRun:
        run = ValidationRun.from_create(payload)
        rows = load_records(VALIDATION_RUNS_FILE)
        rows.append(run.model_dump(mode="json"))
        save_records(VALIDATION_RUNS_FILE, rows)
        return run

    def get_run(self, run_id: str) -> ValidationRun | None:
        return next((run for run in self.list_runs() if run.id == run_id), None)

    def list_results(self, run_id: str) -> list[ValidationResult]:
        return [ValidationResult(**row) for row in load_records(VALIDATION_RESULTS_FILE) if row["run_id"] == run_id]

    def get_summary(self, run_id: str) -> ValidationSummary | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        results = self.list_results(run_id)
        return ValidationSummary(
            run_id=run.id,
            passed_count=sum(1 for item in results if item.result_status == "Passed"),
            warning_count=sum(1 for item in results if item.result_status == "Warning"),
            failed_count=sum(1 for item in results if item.result_status == "Failed"),
        )


store = PersistentValidationStore()
