from __future__ import annotations

from .safety import requires_approval


def execute_approved_ddl_plan(*, approved: bool, ddl_count: int) -> dict:
    if not approved or requires_approval("execute_approved_ddl"):
        return {
            "status": "WAITING_FOR_APPROVAL" if not approved else "STAGED_ONLY",
            "executed": False,
            "ddl_count": ddl_count,
            "message": "DDL execution is gated; this local slice stages execution metadata only.",
        }
    return {"status": "EXECUTED", "executed": True, "ddl_count": ddl_count}
