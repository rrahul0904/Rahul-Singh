from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import zipfile

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models import ControlPlaneArtifact, ControlPlaneRun
from services.control_plane import (
    ControlPlaneService,
    normalize_status,
    parse_sql_semantic,
    read_artifact_text,
    redact_secrets,
    score_from_counts,
    semantic_sql_features,
    semantic_statement_type,
    split_sql_statements,
    statement_type,
    utcnow,
)
from services.ai import AiProviderRouter
from services.ai.provider_router import parse_provider_json


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return cleaned or "model"


def _artifact_tables(stmt: str, source_dialect: str) -> list[str]:
    parsed, _ = parse_sql_semantic(stmt, source_dialect)
    return semantic_sql_features(parsed).get("tables", [])


def _infer_materialization(sql_text: str) -> tuple[str, list[str]]:
    lowered = sql_text.lower()
    warnings = []
    if re.search(r"\bmerge\b|\bupsert\b", lowered):
        warnings.append("MERGE or UPSERT logic inferred; review incremental merge keys before deployment.")
        return "incremental", warnings
    if re.search(r"\bappend\b|\binsert\s+into\b", lowered):
        warnings.append("Append-style writes inferred; confirm incremental cursor strategy.")
        return "incremental", warnings
    if re.search(r"\b(sum|count|avg|min|max)\s*\(", lowered):
        return "table", warnings
    if re.search(r"\btemporary\b|\btemp\b", lowered):
        warnings.append("Temporary table chain detected; split into staging and intermediate models.")
        return "view", warnings
    return "view", warnings


def _dbt_project_tree(project_name: str, models: list[dict], includes_snapshot: bool) -> list[str]:
    tree = [
        "dbt_project.yml",
        "models/sources.yml",
        "models/schema.yml",
    ]
    for model in models:
        tree.append(f"models/{model['layer']}/{model['name']}.sql")
    if includes_snapshot:
        tree.append("snapshots/source_history.sql")
    return tree


def _source_yaml_block(source: str) -> str:
    parts = [part.strip('"').lower() for part in source.split(".") if part]
    source_name = parts[-2] if len(parts) > 1 else "raw"
    table_name = parts[-1] if parts else "table"
    return f"  - name: {source_name}\n    tables:\n      - name: {table_name}\n"


def _zip_entries(artifact: ControlPlaneArtifact) -> list[str]:
    path = Path(artifact.storage_path)
    if not path.exists():
        return []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return sorted(zf.namelist())
    except Exception:
        return []


def _read_zip_text(artifact: ControlPlaneArtifact, name: str, max_bytes: int = 2_000_000) -> str:
    path = Path(artifact.storage_path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return zf.read(name)[:max_bytes].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _dbt_refs(sql_text: str) -> list[str]:
    return sorted(set(re.findall(r"ref\(['\"]([^'\"]+)['\"]\)", sql_text)))


def _dbt_sources(sql_text: str) -> list[str]:
    return sorted(set(":".join(match) for match in re.findall(r"source\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]+)['\"]\)", sql_text)))


def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


async def _ai_dbt_model_map(run: ControlPlaneRun, project_name: str, candidates: list[dict]) -> tuple[dict[str, str], dict]:
    router = AiProviderRouter((run.config_json or {}).get("provider"))
    status = await router.status()
    provider_info = {
        "provider": status.active_provider,
        "model": status.model,
        "available": bool(status.chat_supported),
        "status": "AI_READY" if status.chat_supported else "AI_UNAVAILABLE",
    }
    if not status.chat_supported:
        if status.error:
            provider_info["error"] = status.error
        return {}, provider_info
    model_inputs = [
        {
            "name": candidate.get("name"),
            "path": f"models/{candidate.get('layer', 'staging')}/{candidate.get('name', 'model')}.sql",
            "materialization": candidate.get("materialization") or "view",
            "sources": candidate.get("sources") or [],
            "source_sql": str(candidate.get("source_sql") or "")[:5000],
            "requirement": (run.config_json or {}).get("requirement") or "",
        }
        for candidate in candidates[:8]
    ]
    payload = {
        "project_name": project_name,
        "source_dialect": run.source_dialect,
        "target_platform": run.target_type or "snowflake",
        "models": model_inputs,
        "instructions": [
            "Generate Snowflake-ready dbt model SQL for each item.",
            "Return JSON only: {\"models\": [{\"name\": string, \"sql\": string}], \"warnings\": []}.",
            "Preserve source logic where possible and keep dbt Jinja valid.",
            "Do not include credentials, profiles, or secret values.",
            "Generated SQL is review-only and must not execute external side effects.",
        ],
    }
    response = await router.chat(
        [{"role": "user", "content": json.dumps(payload, indent=2, default=str)[:30000]}],
        system="Generate review-only dbt model SQL for a Snowflake migration. Return compact JSON only.",
        json_mode=True,
        max_tokens=2200,
        temperature=0.1,
    )
    if not response.available:
        provider_info.update({"available": False, "status": "AI_CALL_FAILED", "error": response.error})
        return {}, provider_info
    try:
        parsed = parse_provider_json(response.content)
    except Exception as exc:
        provider_info.update({"available": False, "status": "AI_PARSE_FAILED", "error": str(exc)})
        return {}, provider_info
    generated = {}
    for item in parsed.get("models") or []:
        name = str(item.get("name") or "").strip()
        sql_text = _strip_code_fence(str(item.get("sql") or ""))
        if name and sql_text:
            generated[name] = sql_text + "\n"
    provider_info.update({"status": "AI_GENERATED", "generated_model_count": len(generated), "warnings": parsed.get("warnings") or []})
    return generated, provider_info


@dataclass
class DbtConversionService:
    db: AsyncSession

    def __post_init__(self) -> None:
        self.common = ControlPlaneService(self.db)

    async def analyze(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> dict:
        job = await self.common.create_job(run.id, "DBT_CONVERSION", "ANALYZE")
        model_candidates = []
        warnings = []
        inventory = []
        for artifact in artifacts:
            if artifact.file_type == "zip" or artifact.artifact_category == "DBT_PROJECT":
                entries = _zip_entries(artifact)
                inventory.append({
                    "artifact_id": artifact.id,
                    "file_name": artifact.original_filename,
                    "artifact_type": "DBT_PROJECT",
                    "entries": entries[:120],
                    "status": "READY_FOR_STATIC_ANALYSIS",
                })
                continue
            text = redact_secrets(read_artifact_text(artifact))
            statements = split_sql_statements(text) if text.strip() else []
            statement_models = []
            for index, stmt, line_start, line_end in statements:
                tables = _artifact_tables(stmt, run.source_dialect)
                materialization, stmt_warnings = _infer_materialization(stmt)
                warnings.extend(stmt_warnings)
                name = _sanitize_name(Path(artifact.original_filename).stem)
                layer = "staging"
                if materialization == "incremental":
                    layer = "intermediate"
                if re.search(r"\b(sum|count|avg|min|max)\s*\(", stmt.lower()):
                    layer = "marts"
                statement_models.append({
                    "statement_index": index,
                    "name": f"{name}_{index + 1}" if len(statements) > 1 else name,
                    "layer": layer,
                    "materialization": materialization,
                    "line_range": [line_start, line_end],
                    "sources": tables[:20],
                    "source_sql": stmt[:20000],
                })
            inventory.append({
                "artifact_id": artifact.id,
                "file_name": artifact.original_filename,
                "artifact_type": artifact.artifact_category,
                "statement_count": len(statements),
                "model_candidates": len(statement_models),
                "status": "READY_FOR_REVIEW" if statement_models else "REQUIRES_CONFIGURATION",
            })
            model_candidates.extend(statement_models)
        if not model_candidates and (run.config_json or {}).get("requirement"):
            model_candidates.append({
                "statement_index": 0,
                "name": _sanitize_name((run.config_json or {}).get("generation_type") or run.name),
                "layer": "staging",
                "materialization": (run.config_json or {}).get("default_materialization") or "view",
                "line_range": [1, 1],
                "sources": [],
            })
            warnings.append("Artifact Factory used requirement-only generation; assumptions must be reviewed before deployment.")
        severity_counts = {
            "INFO": len(model_candidates),
            "WARN": len(warnings),
            "ERROR": 0,
            "FATAL": 0,
        }
        project_name = (run.config_json or {}).get("dbt_project_name") or _sanitize_name(run.name)
        report = {
            "run_id": run.id,
            "workflow_type": run.workflow_type,
            "dbt_project_name": project_name,
            "target_platform": run.target_type or "snowflake",
            "source_dialect": run.source_dialect,
            "analysis_status": "COMPLETED",
            "generated_artifact_count": 0,
            "inventory": inventory,
            "model_candidates": model_candidates[:120],
            "project_tree_preview": _dbt_project_tree(project_name, model_candidates[:40], any("snapshot" in w.lower() for w in warnings)),
            "review_items": [{"severity": "WARN", "message": w} for w in sorted(set(warnings))],
            "dbt_suitability_score": score_from_counts(max(len(model_candidates), 1), severity_counts),
            "warnings_count": len(warnings),
            "errors_count": 0,
            "next_actions": [
                "Review inferred model boundaries and materializations.",
                "Generate dbt artifacts when the project configuration looks correct.",
                "Inspect existing dbt project analysis separately for uploaded project archives.",
            ],
        }
        run.status = normalize_status(severity_counts)
        run.current_phase = "ANALYZED"
        run.started_at = run.started_at or utcnow()
        run.completed_at = utcnow()
        run.summary_json = report
        run.metrics_json = {
            "generated_artifact_count": 0,
            "warnings_count": len(warnings),
            "errors_count": 0,
            "dbt_suitability_score": report["dbt_suitability_score"],
        }
        await self.common.store_json_artifact(run.id, "REPORT", "dbt-conversion-report.json", report, run.created_by)
        await self.common.finish_job(job, "COMPLETED", report)
        await self.db.commit()
        return report

    async def generate(self, run: ControlPlaneRun) -> dict:
        report = run.summary_json or {}
        candidates = report.get("model_candidates") or []
        if not candidates:
            raise HTTPException(409, "Analyze the dbt conversion run before generating artifacts.")
        job = await self.common.create_job(run.id, "DBT_CONVERSION", "GENERATE")
        project_name = (run.config_json or {}).get("dbt_project_name") or report.get("dbt_project_name") or _sanitize_name(run.name)
        default_schema = (run.config_json or {}).get("default_schema") or "analytics"
        default_database = (run.config_json or {}).get("default_database") or "SNOWFLAKE_DB"
        generated = []
        sources = sorted({table for candidate in candidates for table in candidate.get("sources", [])})
        ai_models, ai_generation = await _ai_dbt_model_map(run, project_name, candidates)
        models_yaml = []
        for candidate in candidates[:40]:
            sql_lines = [
                "{{ config(materialized='" + candidate["materialization"] + "') }}",
                "",
                "-- Assumptions are preserved for human review before deployment.",
            ]
            if candidate.get("sources"):
                first_source = candidate["sources"][0]
                table_name = first_source.split(".")[-1].strip('"').lower()
                source_name = (first_source.split(".")[-2].strip('"').lower() if "." in first_source else "raw")
                sql_lines.extend([
                    f"select *",
                    f"from {{{{ source('{source_name}', '{table_name}') }}}}",
                ])
            else:
                sql_lines.append("select 1 as placeholder_review_required")
            sql_text = "\n".join(sql_lines) + "\n"
            sql_text = ai_models.get(candidate["name"]) or sql_text
            model_path = f"models/{candidate['layer']}/{candidate['name']}.sql"
            artifact = await self.common.store_text_artifact(run.id, "GENERATED_DBT", model_path, sql_text, run.created_by, "text/sql")
            generated.append({
                "artifact_id": artifact.id,
                "path": model_path,
                "materialization": candidate["materialization"],
                "ai_generated": candidate["name"] in ai_models,
            })
            models_yaml.append(
                "  - name: {name}\n"
                "    description: Generated by UMA for review.\n"
                "    tests:\n"
                "      - not_null:\n"
                "          column_name: id\n".format(name=candidate["name"])
            )
        dbt_project_yml = (
            f"name: {project_name}\n"
            "version: '1.0.0'\n"
            "config-version: 2\n"
            f"profile: {(run.config_json or {}).get('dbt_profile_name') or project_name}\n"
            "model-paths: ['models']\n"
            "snapshot-paths: ['snapshots']\n"
            "models:\n"
            f"  {project_name}:\n"
            f"    +database: {default_database}\n"
            f"    +schema: {default_schema}\n"
        )
        sources_yml = "version: 2\nsources:\n" + "".join(_source_yaml_block(source) for source in sources[:40])
        schema_yml = "version: 2\nmodels:\n" + "".join(models_yaml[:40])
        await self.common.store_text_artifact(run.id, "GENERATED_DBT", "dbt_project.yml", dbt_project_yml, run.created_by, "application/yaml")
        await self.common.store_text_artifact(run.id, "GENERATED_DBT", "models/sources.yml", sources_yml or "version: 2\nsources: []\n", run.created_by, "application/yaml")
        await self.common.store_text_artifact(run.id, "GENERATED_DBT", "models/schema.yml", schema_yml or "version: 2\nmodels: []\n", run.created_by, "application/yaml")
        payload = {
            "run_id": run.id,
            "status": "COMPLETED_WITH_WARNINGS" if report.get("review_items") else "COMPLETED",
            "dbt_project_name": project_name,
            "generated_artifact_count": len(generated) + 3,
            "project_tree": _dbt_project_tree(project_name, candidates[:40], False),
            "generated_models": generated,
            "ai_generation": ai_generation,
            "warnings": report.get("review_items", []),
            "executed": False,
            "message": "dbt artifacts were generated for review only. UMA did not run dbt build or execute generated SQL.",
        }
        run.status = payload["status"]
        run.current_phase = "GENERATED"
        run.completed_at = utcnow()
        run.summary_json = {**report, "generation": payload, "generated_artifact_count": payload["generated_artifact_count"]}
        run.metrics_json = {
            **(run.metrics_json or {}),
            "generated_artifact_count": payload["generated_artifact_count"],
            "warnings_count": len(payload["warnings"]),
        }
        await self.common.finish_job(job, "COMPLETED", payload)
        await self.db.commit()
        return payload

    async def analyze_existing_project(self, artifact: ControlPlaneArtifact, user_id: str | None = None) -> dict:
        if artifact.file_type != "zip" and artifact.artifact_category != "DBT_PROJECT":
            raise HTTPException(415, "Upload a dbt project zip before running static project analysis.")
        entries = _zip_entries(artifact)
        models = [name for name in entries if name.startswith("models/") and name.endswith(".sql")]
        snapshots = [name for name in entries if name.startswith("snapshots/") and name.endswith(".sql")]
        macros = [name for name in entries if name.startswith("macros/") and name.endswith(".sql")]
        schema_files = [name for name in entries if name.endswith(("schema.yml", "schema.yaml", "sources.yml", "sources.yaml"))]
        refs = {}
        sources = {}
        risky_models = []
        missing_tests = []
        for model in models[:200]:
            text = _read_zip_text(artifact, model)
            model_name = Path(model).stem
            refs[model_name] = _dbt_refs(text)
            sources[model_name] = _dbt_sources(text)
            if re.search(r"\bmerge\b|\bis_incremental\(", text, re.I):
                risky_models.append(model_name)
            if model_name not in " ".join(schema_files):
                missing_tests.append(model_name)
        return {
            "project_id": artifact.id,
            "file_name": artifact.original_filename,
            "entry_count": len(entries),
            "model_count": len(models),
            "snapshot_count": len(snapshots),
            "macro_count": len(macros),
            "schema_file_count": len(schema_files),
            "models": [{"name": Path(name).stem, "path": name, "refs": refs.get(Path(name).stem, []), "sources": sources.get(Path(name).stem, [])} for name in models[:200]],
            "lineage": [{"model": model, "refs": refs.get(model, []), "sources": sources.get(model, [])} for model in sorted(refs.keys())],
            "missing_tests": missing_tests[:120],
            "risky_incremental_logic": risky_models[:120],
            "recommendations": [
                "Remove hardcoded database and schema references where possible.",
                "Backfill schema.yml coverage for models without tests.",
                "Review incremental merge predicates and uniqueness assumptions before deployment.",
            ],
        }
