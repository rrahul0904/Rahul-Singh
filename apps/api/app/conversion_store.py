from __future__ import annotations

from .conversion_models import ConversionItem, ConversionItemCreate, ConversionSummary


class ConversionStore:
    def __init__(self) -> None:
        self.items: list[ConversionItem] = [
            ConversionItem.from_create(
                ConversionItemCreate(
                    project_id="prj_prologis01",
                    source_object_name="tenant_revenue_rollup",
                    source_type="Teradata View",
                    target_type="Snowflake SQL",
                    created_by="Rahul",
                )
            ),
            ConversionItem.from_create(
                ConversionItemCreate(
                    project_id="prj_revops01",
                    source_object_name="lease_expiry_projection",
                    source_type="ADF Pipeline",
                    target_type="Databricks Job",
                    created_by="Rahul",
                )
            ),
        ]
        self.items[0].status = "Review"
        self.items[0].risk = "Medium"
        self.items[1].status = "Approved"
        self.items[1].risk = "Low"

    def list_items(self) -> list[ConversionItem]:
        return self.items

    def create_item(self, payload: ConversionItemCreate) -> ConversionItem:
        item = ConversionItem.from_create(payload)
        self.items.append(item)
        return item

    def get_item(self, item_id: str) -> ConversionItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def get_summary(self, item_id: str) -> ConversionSummary | None:
        item = self.get_item(item_id)
        if item is None:
            return None
        return ConversionSummary(
            item_id=item.id,
            source_object_name=item.source_object_name,
            status=item.status,
            risk=item.risk,
            source_type=item.source_type,
            target_type=item.target_type,
        )


store = ConversionStore()
