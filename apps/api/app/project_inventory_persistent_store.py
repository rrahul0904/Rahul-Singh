from __future__ import annotations

from datetime import datetime

from .project_inventory_models import InventoryItem, Project, ProjectCreate, ProjectSummary
from .stateful_storage import load_records, save_records

PROJECTS_FILE = "projects.json"
INVENTORY_FILE = "inventory.json"


class PersistentProjectInventoryStore:
    def __init__(self) -> None:
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        if not load_records(PROJECTS_FILE):
            save_records(
                PROJECTS_FILE,
                [
                    Project(
                        id="prj_prologis01",
                        name="Prologis Leasing Migration",
                        description="Migration of leasing analytics workloads into Snowflake.",
                        source_platform="Teradata",
                        target_platform="Snowflake",
                        owner="Rahul",
                        status="In Validation",
                        progress=72,
                        created_at=datetime.utcnow(),
                    ).model_dump(mode="json"),
                    Project(
                        id="prj_revops01",
                        name="RevOps Modernization",
                        description="Migration of reporting datasets into Databricks.",
                        source_platform="SQL Server",
                        target_platform="Databricks",
                        owner="Rahul",
                        status="In Conversion",
                        progress=48,
                        created_at=datetime.utcnow(),
                    ).model_dump(mode="json"),
                ],
            )
        if not load_records(INVENTORY_FILE):
            save_records(
                INVENTORY_FILE,
                [
                    InventoryItem(id="inv_001", project_id="prj_prologis01", object_type="Table", schema_name="leasing", object_name="tenant_dim", status="Discovered", complexity="Low").model_dump(),
                    InventoryItem(id="inv_002", project_id="prj_prologis01", object_type="Table", schema_name="leasing", object_name="lease_fact", status="Needs Review", complexity="High").model_dump(),
                    InventoryItem(id="inv_003", project_id="prj_revops01", object_type="View", schema_name="sales", object_name="revenue_rollup", status="Needs Review", complexity="High").model_dump(),
                ],
            )

    def list_projects(self) -> list[Project]:
        return [Project(**row) for row in load_records(PROJECTS_FILE)]

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project.from_create(payload)
        rows = load_records(PROJECTS_FILE)
        rows.append(project.model_dump(mode="json"))
        save_records(PROJECTS_FILE, rows)
        return project

    def get_project(self, project_id: str) -> Project | None:
        return next((project for project in self.list_projects() if project.id == project_id), None)

    def list_inventory_for_project(self, project_id: str) -> list[InventoryItem]:
        return [InventoryItem(**row) for row in load_records(INVENTORY_FILE) if row["project_id"] == project_id]

    def get_summary(self, project_id: str) -> ProjectSummary | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        items = self.list_inventory_for_project(project_id)
        return ProjectSummary(
            project_id=project.id,
            project_name=project.name,
            total_inventory_items=len(items),
            discovered_tables=sum(1 for item in items if item.object_type == "Table"),
            discovered_views=sum(1 for item in items if item.object_type == "View"),
            items_needing_review=sum(1 for item in items if item.status == "Needs Review"),
        )


store = PersistentProjectInventoryStore()
