from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .conversion_models import ConversionItem, ConversionItemCreate, ConversionSummary
from .conversion_persistent_store import store

router = APIRouter(prefix="/api/stateful/v1/conversion", tags=["conversion-workbench-stateful"])


@router.get("/items", response_model=list[ConversionItem])
def list_items() -> list[ConversionItem]:
    return store.list_items()


@router.post("/items", response_model=ConversionItem, status_code=status.HTTP_201_CREATED)
def create_item(payload: ConversionItemCreate) -> ConversionItem:
    return store.create_item(payload)


@router.get("/items/{item_id}", response_model=ConversionItem)
def get_item(item_id: str) -> ConversionItem:
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversion item not found")
    return item


@router.get("/items/{item_id}/summary", response_model=ConversionSummary)
def get_item_summary(item_id: str) -> ConversionSummary:
    summary = store.get_summary(item_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversion item not found")
    return summary
