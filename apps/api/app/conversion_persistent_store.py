from __future__ import annotations

from .conversion_models import ConversionItem, ConversionItemCreate, ConversionSummary
from .stateful_storage import load_records, save_records

CONVERSION_ITEMS_FILE = "conversion_items.json"


class PersistentConversionStore:
    def __init__(self) -> None:
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        if not load_records(CONVERSION_ITEMS_FILE):
            item1 = ConversionItem.from_create(
                ConversionItemCreate(
                    project_id="prj_prologis01",
                    source_object_name="tenant_revenue_rollup",
                    source_type="Teradata View",
                    target_type="Snowflake SQL",
                    created_by="Rahul",
                )
            )
            item1.status = "Review"
            item1.risk = "Medium"
            item2 = ConversionItem.from_create(
                ConversionItemCreate(
                    project_id="prj_revops01",
                    source_object_name="lease_expiry_projection",
                    source_type="ADF Pipeline",
                    target_type="Databricks Job",
                    created_by="Rahul",
                )
            )
            item2.status = "Approved"
            item2.risk = "Low"
            save_records(CONVERSION_ITEMS_FILE, [item1.model_dump(mode="json"), item2.model_dump(mode="json")])

    def list_items(self) -> list[ConversionItem]:
        return [ConversionItem(**row) for row in load_records(CONVERSION_ITEMS_FILE)]

    def create_item(self, payload: ConversionItemCreate) -> ConversionItem:
        item = ConversionItem.from_create(payload)
        rows = load_records(CONVERSION_ITEMS_FILE)
        rows.append(item.model_dump(mode="json"))
        save_records(CONVERSION_ITEMS_FILE, rows)
        return item

    def get_item(self, item_id: str) -> ConversionItem | None:
        return next((item for item in self.list_items() if item.id == item_id), None)

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


store = PersistentConversionStore()
