from __future__ import annotations

from typing import Any


def normalize_chunk_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    base = {
        "run_id": None,
        "artifact_id": None,
        "job_id": None,
        "artifact_type": None,
        "file_path": None,
        "source_dialect": None,
        "target_dialect": None,
        "model_name": None,
        "created_at": None,
        "content_hash": None,
        "redaction_applied": True,
        "decision_status": None,
        "validation_status": None,
    }
    base.update({key: value for key, value in (metadata or {}).items() if value is not None})
    return base
