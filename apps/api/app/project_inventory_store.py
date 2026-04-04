from __future__ import annotations

from collections import Counter

from .project_inventory_models import InventoryItem, Project, ProjectCreate, ProjectSummary


class ProjectInventoryStore:
    def __init__(self) -> None:
        self.projects: list[Project] = [
            Project(
                id="prj_prologis01",
                name="Prologis Leasing Migration",
                description="Migration of leasing analytics workloads into Snowflake.",
                source_platform="Teradata",
                target_platform="Snowflake",
                owner="Rahul",
                status="In Validation",
                progress=72,
                created_at=Project.from_create(
                    ProjectCreate(
                        name="seed",
                        description="",
                        source_platform="Teradata",
                        target_platform="Snowflake",
                        owner="seed",
                    )
                ).created_at,
            ),
            Project(
                id="prj_revops01",
                name="RevOps Modernization",
                description="Migration of reporting datasets into Databricks.",
                source_platform="SQL Server",
                target_platform="Databricks",
                owner="Rahul",
                status="In Conversion",
                progress=48,
                created_at=Project.from_create(
                    ProjectCreate(
                        name="seed2",
                        description="",
                        source_platform="SQL Server",
                        target_platform="Databricks",
                        owner="seed",
                    )
                ).created_at,
            ),
        ]
        self.inventory: list[InventoryItem] = [
            InventoryItem(id="inv_001", project_id="prj_prologis01", object_type="Table", schema_name="leasing", object_name="tenant_dim", status="Discovered", complexity="Low"),
            InventoryItem(id="inv_002", project_id="prj_prologis01", object_type="Table", schema_name="leasing", object_name="lease_fact", status="Needs Review", complexity="High"),
            InventoryItem(id="inv_003", project_id="prj_prologis01", object_type="View", schema_name="mart", object_name="occupancy_by_region", status="Discovered", complexity="Medium"),
            InventoryItem(id="inv_004", project_id="prj_revops01", object_type="Table", schema_name="sales", object_name="opportunity_fact", status="Discovered", complexity="Medium"),
            InventoryItem(id="inv_005", project_id="prj_revops01", object_type="View", schema_name="sales", object_name="revenue_rollup", status="Needs Review", complexity="High"),
        ]

    def list_projects(self) -> list[Project]:
        return self.projects

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project.from_create(payload)
        self.projects.append(project)
        return project

    def get_project(self, project_id: str) -> Project | None:
        return next((project for project in self.projects if project.id == project_id), None)

    def list_inventory_for_project(self, project_id: str) -> list[InventoryItem]:
        return [item for item in self.inventory if item.project_id == project_id]

    def get_summary(self, project_id: str) -> ProjectSummary | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        items = self.list_inventory_for_project(project_id)
        counts = Counter(item.object_type for item in items)
        review_count = sum(1 for item in items if item.status == "Needs Review")
        return ProjectSummary(
            project_id=project.id,
            project_name=project.name,
            total_inventory_items=len(items),
            discovered_tables=counts.get("Table", 0),
            discovered_views=counts.get("View", 0),
            items_needing_review=review_count,
        )


store = ProjectInventoryStore()
