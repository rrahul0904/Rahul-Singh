from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_data_file(name: str) -> Path:
    path = BASE_DATA_DIR / name
    if not path.exists():
        path.write_text("[]", encoding="utf-8")
    return path


def load_records(name: str) -> list[dict[str, Any]]:
    path = get_data_file(name)
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    return json.loads(raw)


def save_records(name: str, rows: list[dict[str, Any]]) -> None:
    path = get_data_file(name)
    path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
