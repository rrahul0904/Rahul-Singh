from __future__ import annotations


def generate_snowflake_ddl(source_object: dict, source_type: str) -> dict:
    schema = source_object.get("schema") or "PUBLIC"
    name = source_object.get("name") or "UNKNOWN_OBJECT"
    target_name = f"{schema}_{name}".upper().replace(".", "_").replace("*", "ALL")
    ddl = (
        f"CREATE TABLE IF NOT EXISTS {target_name} (\n"
        "  ID NUMBER(38,0),\n"
        "  SOURCE_PAYLOAD VARIANT,\n"
        "  UPDATED_AT TIMESTAMP_NTZ,\n"
        "  _UMA_BATCH_ID VARCHAR,\n"
        "  _UMA_LOADED_AT TIMESTAMP_NTZ,\n"
        "  _UMA_IS_DELETED BOOLEAN\n"
        ");"
    )
    unsupported = []
    if source_type in {"teradata", "oracle", "sqlserver"}:
        unsupported.append("Stored procedure dialect conversion requires object source text")
    return {
        "source_object_name": f"{schema}.{name}",
        "source_object_type": source_object.get("type", "table"),
        "source_dialect": source_type,
        "target_dialect": "snowflake",
        "original_ddl": "",
        "converted_ddl": ddl,
        "conversion_confidence": 0.62 if unsupported else 0.78,
        "unsupported_features": unsupported,
        "manual_review_required": True,
        "review_status": "generated",
    }


def stage_ddl_for_review(conversions: list[dict]) -> dict:
    return {
        "staged_count": len(conversions),
        "review_status": "generated",
        "approval_gate": "required_before_execution",
    }
