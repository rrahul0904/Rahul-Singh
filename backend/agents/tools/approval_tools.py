from __future__ import annotations


def approval_payload(*, ddl_count: int, load_strategy: str) -> dict:
    return {
        "approval_type": "ddl_execution",
        "requires_approval": True,
        "reason": "Generated Snowflake DDL and execution jobs must be reviewed before DDL/DML runs.",
        "ddl_count": ddl_count,
        "load_strategy": load_strategy,
        "blocked_tools": ["execute_approved_ddl", "create_load_job", "run_validation"],
    }
