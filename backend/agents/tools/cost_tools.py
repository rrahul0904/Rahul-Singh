from __future__ import annotations


def estimate_snowflake_cost(*, data_volume_tb: float, migration_type: str, object_count: int) -> dict:
    volume = max(float(data_volume_tb or 0), 0.01)
    warehouse = "XSMALL" if volume < 0.25 else "SMALL" if volume < 1 else "MEDIUM"
    multiplier = 1.8 if migration_type in {"incremental", "cdc"} else 1.25
    estimated_credits = round(max(0.05, volume * multiplier * 8 + object_count * 0.02), 2)
    return {
        "warehouse_recommendation": warehouse,
        "estimated_credits": estimated_credits,
        "estimated_storage_tb": volume,
        "estimated_cortex_credits": 0.0,
        "confidence": "low" if data_volume_tb <= 0 else "medium",
        "pending_actuals": ["query_history", "copy_history", "task_history", "cortex_usage", "spcs_usage"],
    }


def snowflake_intelligence_plan() -> dict:
    return {
        "cortex_search": {
            "status": "planned",
            "indexes": ["migration_plans", "ddl_conversions", "validation_failures", "runbooks", "error_logs"],
        },
        "cortex_analyst": {
            "status": "planned",
            "semantic_views": ["migration_status", "migration_cost", "validation_quality"],
        },
        "spcs": {
            "status": "planned",
            "runtime": "UMA deterministic workflow worker container",
        },
        "snowflake_tasks": {
            "status": "planned",
            "jobs": ["scheduled_validation", "cdc_polling", "cost_reconciliation"],
        },
    }
