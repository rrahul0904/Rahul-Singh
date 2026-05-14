from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from core.config import settings
from services.ai import AiProviderRouter
from services.ai.provider_router import parse_provider_json


SUPPORTED_CODE_GENERATION_TYPES = {
    "DDL": "Generate Snowflake-oriented DDL from a table description or source SQL.",
    "DML": "Generate review-only DML from a requested mutation pattern.",
    "SQL": "Generate review-only SQL from a business question.",
    "DBT_MODEL": "Convert SQL into a Snowflake-ready dbt model.",
    "DBT_PROJECT": "Generate a small dbt project scaffold from migration requirements.",
    "AIRFLOW_DAG": "Convert migration orchestration requirements into an Airflow DAG scaffold.",
    "SQL_TO_PYSPARK": "Convert SQL into a PySpark DataFrame/SQL scaffold.",
    "PYTHON_TO_SNOWPARK": "Convert Python data logic into a Snowpark Python scaffold.",
    "PLSQL_TO_STORED_PROCEDURE": "Convert PL/SQL intent into a Snowflake Scripting stored procedure scaffold.",
}

AI_CODE_GENERATION_SYSTEM = """You generate review-only migration code for UMA.
Return JSON only with these keys:
generated_code, source_language, target_language, technical_design_document, judge_pass_review, safety_notes.
The generated code must be complete enough for human review, must not contain credentials or secrets, and must never claim execution readiness.
For SQL/dbt/Airflow conversions preserve source logic, call out assumptions, and include validation steps in the technical design document."""


@dataclass(frozen=True)
class CodeGenerationResult:
    generation_type: str
    source_language: str
    target_language: str
    generated_code: str
    technical_design_document: dict[str, Any]
    judge_pass_review: dict[str, Any]
    safety_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_type": self.generation_type,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "generated_code": self.generated_code,
            "technical_design_document": self.technical_design_document,
            "judge_pass_review": self.judge_pass_review,
            "safety_notes": self.safety_notes,
            "execution_ready": False,
        }


def _clean(value: str | None, fallback: str = "") -> str:
    return (value or fallback).strip()


def _fenced_source(source: str) -> str:
    return source.strip() if source.strip() else "-- Source was not provided. Replace placeholders before review."


def _generate_code(kind: str, prompt: str, source: str, metadata: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    table = _clean(metadata.get("table_name"), "TABLE_NAME")
    database = _clean(metadata.get("database"), "DATABASE_NAME")
    schema = _clean(metadata.get("schema"), "SCHEMA_NAME")
    target = f"{database}.{schema}.{table}".upper()

    if kind == "DDL":
        return (
            "SQL",
            "Snowflake SQL",
            f"""CREATE TABLE IF NOT EXISTS {target} (
    ID NUMBER(38,0) NOT NULL,
    PAYLOAD VARIANT,
    _UMA_LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);""",
            ["DDL is staged for review only; it is not executed by this endpoint."],
        )
    if kind == "DML":
        return (
            "SQL",
            "Snowflake SQL",
            f"""-- Review before execution. Replace predicates with approved business keys.
MERGE INTO {target} AS tgt
USING STAGING.{table.upper()}_STAGE AS src
ON tgt.ID = src.ID
WHEN MATCHED THEN UPDATE SET
    PAYLOAD = src.PAYLOAD
WHEN NOT MATCHED THEN INSERT (ID, PAYLOAD)
VALUES (src.ID, src.PAYLOAD);""",
            ["DML is generated as a staged review artifact; no INSERT/UPDATE/MERGE is run."],
        )
    if kind == "SQL":
        return (
            "Natural language",
            "Snowflake SQL",
            f"""SELECT
    *
FROM {target}
LIMIT 100;""",
            ["Generated SQL is read-only by default unless the user explicitly selects DML."],
        )
    if kind == "DBT_MODEL":
        source_sql = _fenced_source(source)
        model_name = _clean(metadata.get("model_name") or metadata.get("table_name"), "uma_model")
        materialization = _clean(metadata.get("materialization"), "view")
        return (
            "SQL",
            "dbt SQL",
            f"""{{{{ config(materialized='{materialization}') }}}}

-- Review source-to-target semantic parity before dbt build.
with source_data as (
    {source_sql}
)

select *
from source_data""",
            [f"dbt model `{model_name}` is a review scaffold; validate refs/sources and materialization before deployment."],
        )
    if kind == "DBT_PROJECT":
        project_name = _clean(metadata.get("project_name"), "uma_migration")
        return (
            "SQL / requirements",
            "dbt project",
            f"""# {project_name}

dbt_project.yml
models/
  staging/
    stg_review_required.sql
  schema.yml
  sources.yml

-- stg_review_required.sql
{{{{ config(materialized='view') }}}}
select 1 as placeholder_review_required""",
            ["dbt project scaffold requires model-by-model validation before dbt build."],
        )
    if kind == "AIRFLOW_DAG":
        dag_id = _clean(metadata.get("dag_id") or metadata.get("table_name"), "uma_migration_pipeline")
        return (
            "Migration requirements",
            "Airflow Python DAG",
            f'''from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator


def validate_inputs(**context):
    # Replace with source readiness checks.
    return "inputs_validated"


def run_plan_only_conversion(**context):
    # Call UMA conversion APIs or invoke approved migration tasks here.
    return "conversion_planned"


with DAG(
    dag_id="{dag_id}",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    tags=["uma", "migration", "review-only"],
) as dag:
    start = EmptyOperator(task_id="start")
    validate = PythonOperator(task_id="validate_inputs", python_callable=validate_inputs)
    convert = PythonOperator(task_id="run_plan_only_conversion", python_callable=run_plan_only_conversion)
    finish = EmptyOperator(task_id="finish")

    start >> validate >> convert >> finish''',
            ["Airflow DAG is a review scaffold; wire approved connections, retries, and secrets through Airflow configuration."],
        )
    if kind == "SQL_TO_PYSPARK":
        source_sql = _fenced_source(source)
        return (
            "SQL",
            "PySpark",
            f'''from pyspark.sql import functions as F

# Source SQL captured for traceability:
source_sql = """{source_sql}"""

source_df = spark.sql(source_sql)

result_df = (
    source_df
    .withColumn("_uma_converted_at", F.current_timestamp())
)

result_df.show()''',
            ["PySpark code is a conversion scaffold; validate source SQL semantics and table bindings."],
        )
    if kind == "PYTHON_TO_SNOWPARK":
        return (
            "Python",
            "Snowpark Python",
            f'''from snowflake.snowpark import Session
from snowflake.snowpark import functions as F


def run(session: Session):
    df = session.table("{target}")
    result = (
        df.group_by(F.col("DEPT"))
        .agg(
            F.count(F.lit(1)).alias("EMPLOYEE_COUNT"),
            F.avg(F.col("SALARY")).alias("AVG_SALARY"),
        )
        .sort(F.col("AVG_SALARY").desc())
    )
    return result''',
            ["Credentials are not embedded; pass an approved Snowpark session at runtime."],
        )
    if kind == "PLSQL_TO_STORED_PROCEDURE":
        return (
            "PL/SQL",
            "Snowflake Scripting",
            f"""CREATE OR REPLACE PROCEDURE PROCESS_ORDER(P_ORDER_ID NUMBER)
RETURNS STRING
LANGUAGE SQL
AS
$$
DECLARE
    V_TOTAL_AMOUNT NUMBER(10,2) DEFAULT 0;
    V_CUSTOMER_ID NUMBER;
BEGIN
    SELECT CUSTOMER_ID INTO :V_CUSTOMER_ID
    FROM ORDERS
    WHERE ORDER_ID = :P_ORDER_ID;

    FOR ITEM IN (
        SELECT PRODUCT_ID, QUANTITY
        FROM ORDER_ITEMS
        WHERE ORDER_ID = :P_ORDER_ID
    ) DO
        LET V_PRICE NUMBER(10,2);
        LET V_CURRENT_STOCK NUMBER;

        SELECT PRICE, CURRENT_STOCK INTO :V_PRICE, :V_CURRENT_STOCK
        FROM PRODUCTS
        WHERE PRODUCT_ID = ITEM.PRODUCT_ID;

        V_TOTAL_AMOUNT := V_TOTAL_AMOUNT + (ITEM.QUANTITY * V_PRICE);

        UPDATE PRODUCTS
        SET CURRENT_STOCK = CURRENT_STOCK - ITEM.QUANTITY
        WHERE PRODUCT_ID = ITEM.PRODUCT_ID;

        IF (V_CURRENT_STOCK - ITEM.QUANTITY < 10) THEN
            INSERT INTO STOCK_ALERTS (PRODUCT_ID, ALERT_DATE)
            VALUES (ITEM.PRODUCT_ID, CURRENT_TIMESTAMP());
        END IF;
    END FOR;

    UPDATE ORDERS
    SET TOTAL_AMOUNT = :V_TOTAL_AMOUNT
    WHERE ORDER_ID = :P_ORDER_ID;

    INSERT INTO ORDER_HISTORY (ORDER_ID, CUSTOMER_ID, ORDER_DATE, TOTAL_AMOUNT)
    SELECT ORDER_ID, CUSTOMER_ID, ORDER_DATE, TOTAL_AMOUNT
    FROM ORDERS
    WHERE ORDER_ID = :P_ORDER_ID;

    RETURN 'ORDER PROCESSED';
END;
$$;""",
            ["Procedure DDL is staged only; transaction behavior and exception semantics need human review."],
        )
    return (
        "Unknown",
        "Review artifact",
        f"-- Unsupported generation type: {kind}\n-- Request: {prompt}",
        ["Unsupported generation type; no executable artifact produced."],
    )


def _tdd(kind: str, prompt: str, source_language: str, target_language: str, safety_notes: list[str]) -> dict[str, Any]:
    return {
        "overview": f"Generate a {target_language} artifact for {kind} from the supplied request/source.",
        "objective": _clean(prompt, f"Create a reviewed {kind} artifact for migration engineering."),
        "scope": [
            "Understand source intent and side effects.",
            "Generate target code as a review artifact.",
            "Preserve business logic where source semantics are clear.",
            "Call out manual review areas before execution.",
        ],
        "assumptions": [
            "Generated code is not executed automatically.",
            "Credentials and secrets are supplied only through approved runtime configuration.",
            "DDL/DML/procedure output requires human approval before use.",
        ],
        "source_language": source_language,
        "target_language": target_language,
        "testing_plan": [
            "Run syntax validation in a non-production environment.",
            "Compare row counts and key business outputs against the source.",
            "Review transaction behavior, exception handling, and permissions.",
        ],
        "safety_notes": safety_notes,
    }


def _judge(kind: str, source: str, generated_code: str) -> dict[str, Any]:
    score = 3 if source.strip() else 2
    if kind in {"DDL", "SQL"}:
        score += 1
    return {
        "scale": "1-5",
        "initial_score": min(score, 4),
        "status": "NEEDS_HUMAN_REVIEW",
        "criteria": [
            {"name": "Logic equivalence", "score": min(score, 4), "notes": "Review source-to-target semantic parity."},
            {"name": "Functionality coverage", "score": min(score + 1, 4), "notes": "Core operation scaffold is present."},
            {"name": "Safety and execution gates", "score": 5, "notes": "Artifact is generated only; no execution is performed."},
            {"name": "Production readiness", "score": 3, "notes": "Requires environment-specific validation and approval."},
        ],
        "improvement_points": [
            "Validate identifiers, data types, and schema names against discovered metadata.",
            "Confirm transaction/error-handling parity with the source platform.",
            "Add unit/integration tests around representative input and output records.",
        ],
        "human_review_required": True,
    }


def generate_code_artifact(
    generation_type: str,
    prompt: str = "",
    source_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = generation_type.strip().upper()
    metadata = metadata or {}
    source_language, target_language, code, safety_notes = _generate_code(kind, prompt, source_code, metadata)
    result = CodeGenerationResult(
        generation_type=kind,
        source_language=source_language,
        target_language=target_language,
        generated_code=code,
        technical_design_document=_tdd(kind, prompt, source_language, target_language, safety_notes),
        judge_pass_review=_judge(kind, source_code, code),
        safety_notes=safety_notes + ["No secrets are returned.", "No SQL, DDL, DML, or procedure is executed."],
    )
    payload = result.to_dict()
    if metadata.get("previous_artifact_id"):
        basis = "previous_artifact_revision"
    elif metadata.get("live_catalog_table_id") or metadata.get("catalog"):
        basis = "live_catalog_metadata"
    elif source_code.strip():
        basis = "pasted_source_code"
    else:
        basis = "user_prompt_only"
    payload["basis_for_generation"] = basis
    payload["revision_history"] = []
    return payload


def _truthy_ai_flag(metadata: dict[str, Any]) -> bool:
    value = metadata.get("use_ai", metadata.get("llm_enabled", True))
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "offline"}
    return value is not False


def _bounded_payload(value: Any, limit: int = 30000) -> str:
    text = json.dumps(value, indent=2, default=str)
    return text[:limit]


def _merge_ai_payload(base: dict[str, Any], ai_payload: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    generated_code = str(ai_payload.get("generated_code") or "").strip()
    if generated_code:
        base["generated_code"] = generated_code
    if ai_payload.get("source_language"):
        base["source_language"] = str(ai_payload["source_language"])
    if ai_payload.get("target_language"):
        base["target_language"] = str(ai_payload["target_language"])
    if isinstance(ai_payload.get("technical_design_document"), dict):
        base["technical_design_document"] = ai_payload["technical_design_document"]
    if isinstance(ai_payload.get("judge_pass_review"), dict):
        review = ai_payload["judge_pass_review"]
        review.setdefault("scale", "1-5")
        review.setdefault("status", "NEEDS_HUMAN_REVIEW")
        review.setdefault("human_review_required", True)
        base["judge_pass_review"] = review
    notes = ai_payload.get("safety_notes")
    if isinstance(notes, list):
        base["safety_notes"] = [str(item) for item in notes if str(item).strip()]
    elif isinstance(notes, str) and notes.strip():
        base["safety_notes"] = [notes.strip()]
    base["safety_notes"] = list(dict.fromkeys([*base.get("safety_notes", []), "Generated with provider-backed AI; no code was executed."]))
    base["ai_provider_name"] = provider
    base["ai_model_name"] = model
    base["ai_available"] = True
    base["llm_status"] = "AI_GENERATED"
    base["execution_ready"] = False
    return base


async def generate_code_artifact_with_ai(
    generation_type: str,
    prompt: str = "",
    source_code: str = "",
    metadata: dict[str, Any] | None = None,
    provider_name: str | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    base = generate_code_artifact(generation_type, prompt, source_code, metadata)
    if not _truthy_ai_flag(metadata):
        base.update({"ai_available": False, "llm_status": "AI_DISABLED"})
        return base

    router = AiProviderRouter(provider_name or metadata.get("provider"))
    status = await router.status()
    base.update({
        "ai_provider_name": status.active_provider,
        "ai_model_name": status.model,
        "ai_available": bool(status.chat_supported),
        "llm_status": "AI_READY" if status.chat_supported else "AI_UNAVAILABLE",
    })
    if not status.chat_supported:
        base["ai_error"] = status.error or "No chat-capable AI provider is configured."
        return base

    request_payload = {
        "generation_type": base["generation_type"],
        "prompt": prompt,
        "source_code": source_code[:20000],
        "metadata": metadata,
        "deterministic_baseline": {
            "source_language": base["source_language"],
            "target_language": base["target_language"],
            "generated_code": base["generated_code"][:12000],
            "technical_design_document": base["technical_design_document"],
            "judge_pass_review": base["judge_pass_review"],
        },
        "constraints": [
            "Return JSON only.",
            "Do not include credentials, secrets, or environment values.",
            "Do not execute or mark the artifact execution-ready.",
            "Keep the output reviewable and migration-focused.",
        ],
    }
    response = await router.chat(
        [{"role": "user", "content": _bounded_payload(request_payload)}],
        system=AI_CODE_GENERATION_SYSTEM,
        json_mode=True,
        max_tokens=min(settings.AI_MAX_TOKENS or 1800, int(metadata.get("ai_max_tokens") or 1800)),
        temperature=settings.AI_TEMPERATURE,
    )
    if not response.available:
        base.update({"ai_available": False, "llm_status": "AI_CALL_FAILED", "ai_error": response.error})
        return base
    try:
        parsed = parse_provider_json(response.content)
    except Exception as exc:
        base.update({"ai_available": False, "llm_status": "AI_PARSE_FAILED", "ai_error": str(exc)})
        return base
    return _merge_ai_payload(base, parsed, response.provider or status.active_provider, response.model or status.model)
