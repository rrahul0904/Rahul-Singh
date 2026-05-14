from __future__ import annotations


def build_validation_strategy(discovered_objects: list[dict]) -> list[dict]:
    checks = [
        "row_count",
        "schema_match",
        "duplicate_primary_key",
        "null_count",
        "min_max_watermark",
        "checksum_hash",
        "business_rule",
    ]
    return [
        {
            "object": f"{obj.get('schema')}.{obj.get('name')}",
            "checks": checks,
            "status": "SKIPPED",
            "reason": "Validation waits for approved DDL and migrated target rows.",
        }
        for obj in discovered_objects
    ]
