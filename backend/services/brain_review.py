from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ControlPlaneArtifact, ControlPlaneRun, HumanReviewItem, SqlConversionMessage


OPEN_STATUSES = {"NEW", "OPEN", "IN_REVIEW", "NEEDS_REWORK", "BLOCKED", "REQUIRES_REVIEW"}


def _severity(value: str | None, default: str = "MEDIUM") -> str:
    normalized = (value or default).upper()
    return {
        "FATAL": "CRITICAL",
        "ERROR": "HIGH",
        "REVIEW": "HIGH",
        "WARN": "MEDIUM",
        "WARNING": "MEDIUM",
        "INFO": "INFO",
        "LOW": "LOW",
    }.get(normalized, normalized if normalized in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"} else default)


def _confidence(value: Any, fallback: float = 0.72) -> float:
    try:
        score = float(value)
        return round(score if score <= 1 else score / 100, 2)
    except Exception:
        return fallback


def _short(value: str, limit: int = 255) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] or "UMA review required"


def _dedupe_key(run_id: str, item_type: str, source: str, target: str, title: str) -> str:
    raw = json.dumps([run_id, item_type, source, target, title], sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class ReviewSpec:
    item_type: str
    severity: str
    title: str
    description: str
    recommendation: str
    metadata: dict[str, Any]


class BrainReviewMaterializer:
    """Turns run evidence into durable UMA Brain Review decisions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def materialize_recent(self, limit: int = 200) -> int:
        runs = (
            await self.db.execute(
                select(ControlPlaneRun)
                .where(
                    ControlPlaneRun.workflow_type.in_(
                        [
                            "SQL_CONVERSION",
                            "SQL_DBT_TO_SNOWFLAKE",
                            "DBT_CONVERSION",
                            "DBT_PROJECT_ANALYSIS",
                            "DATA_VALIDATION",
                            "MIGRATION_READINESS",
                            "FULL_MIGRATION_PLAN",
                            "PIPELINE_BUILD",
                            "DATA_CONTRACT_DISCOVERY",
                        ]
                    )
                )
                .order_by(ControlPlaneRun.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        created = 0
        for run in runs:
            created += await self.materialize_run(run, commit=False)
        if created:
            await self.db.commit()
        return created

    async def materialize_run(self, run: ControlPlaneRun, *, commit: bool = True) -> int:
        artifacts = (
            await self.db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == run.id))
        ).scalars().all()
        messages = (
            await self.db.execute(select(SqlConversionMessage).where(SqlConversionMessage.run_id == run.id))
        ).scalars().all()
        specs = self._specs_for_run(run, list(artifacts), list(messages))
        if not specs:
            return 0

        existing = (
            await self.db.execute(select(HumanReviewItem).where(HumanReviewItem.run_id == run.id))
        ).scalars().all()
        existing_keys = {
            (item.metadata_json or {}).get("dedupe_key")
            or _dedupe_key(item.run_id, item.item_type, "", "", item.title)
            for item in existing
        }

        created = 0
        for spec in specs:
            source = spec.metadata.get("source_object") or spec.metadata.get("source_file") or ""
            target = spec.metadata.get("target_object") or spec.metadata.get("target_file") or ""
            dedupe = spec.metadata.get("dedupe_key") or _dedupe_key(run.id, spec.item_type, source, target, spec.title)
            if dedupe in existing_keys:
                continue
            metadata = {
                **spec.metadata,
                "dedupe_key": dedupe,
                "run_name": run.name,
                "workflow_type": run.workflow_type,
                "current_phase": run.current_phase,
                "created_by_engine": "BrainReviewMaterializer",
            }
            self.db.add(
                HumanReviewItem(
                    run_id=run.id,
                    item_type=spec.item_type,
                    severity=spec.severity,
                    title=_short(spec.title),
                    description=spec.description,
                    recommendation=spec.recommendation,
                    status="BLOCKED" if spec.severity == "CRITICAL" else "NEW",
                    metadata_json=metadata,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            existing_keys.add(dedupe)
            created += 1
        if created and commit:
            await self.db.commit()
        return created

    def _specs_for_run(
        self,
        run: ControlPlaneRun,
        artifacts: list[ControlPlaneArtifact],
        messages: list[SqlConversionMessage],
    ) -> list[ReviewSpec]:
        summary = run.summary_json or {}
        specs: list[ReviewSpec] = []
        specs.extend(self._sql_message_specs(run, messages))
        specs.extend(self._conversion_specs(run, summary, artifacts))
        specs.extend(self._dbt_specs(run, summary, artifacts))
        specs.extend(self._validation_specs(run, summary))
        specs.extend(self._generated_artifact_specs(run, artifacts))
        return specs

    def _sql_message_specs(self, run: ControlPlaneRun, messages: list[SqlConversionMessage]) -> list[ReviewSpec]:
        specs = []
        for msg in messages:
            if msg.severity not in {"WARN", "WARNING", "ERROR", "FATAL", "CRITICAL", "HIGH"}:
                continue
            source = msg.file_name or "SQL artifact"
            metadata = msg.metadata_json or {}
            evidence_line = metadata.get("line") or msg.line_start
            matched_text = metadata.get("matched_text") or msg.message
            excerpt = metadata.get("excerpt") or ""
            location = f"{source}"
            if evidence_line:
                location += f" line {evidence_line}"
            evidence = f"{location}: {matched_text}"
            if excerpt:
                evidence += f"\n\n{excerpt}"
            specs.append(
                ReviewSpec(
                    item_type="SQL_CONVERSION_ISSUE",
                    severity=_severity(msg.severity),
                    title=f"{source}: {msg.message}",
                    description=f"UMA found a SQL conversion issue in {location}, statement {msg.statement_index}.",
                    recommendation=msg.recommendation or "Open the SQL workspace or conversion diff, remediate the statement, then rerun conversion validation.",
                    metadata={
                        "source_object": source,
                        "target_object": "Snowflake SQL",
                        "reason": msg.message,
                        "evidence": evidence,
                        "excerpt": excerpt,
                        "matched_text": matched_text,
                        "confidence_score": 0.82,
                        "line_start": evidence_line,
                        "line_end": evidence_line,
                        "statement_index": msg.statement_index,
                    },
                )
            )
        return specs

    def _conversion_specs(
        self,
        run: ControlPlaneRun,
        summary: dict[str, Any],
        artifacts: list[ControlPlaneArtifact],
    ) -> list[ReviewSpec]:
        context = summary.get("conversion_context") or {}
        files = context.get("files") or summary.get("file_reports") or []
        specs: list[ReviewSpec] = []
        for file_row in files:
            source = file_row.get("source_path") or file_row.get("file_name") or "SQL/dbt artifact"
            target = file_row.get("target_path") or f"converted/{source}"
            confidence = _confidence(file_row.get("confidence_score"), 0.72)
            status = str(file_row.get("conversion_status") or file_row.get("status") or "").upper()
            unsupported = [str(x) for x in file_row.get("unsupported_features") or [] if str(x).strip()]
            warnings = [str(x) for x in file_row.get("warnings") or [] if str(x).strip()]
            review = file_row.get("agent_review_results") or {}
            findings = [row for row in review.get("findings") or [] if isinstance(row, dict)]
            source_artifact_id = self._source_artifact_id(source, artifacts)
            base = {
                "source_object": source,
                "target_object": target,
                "source_artifact_id": source_artifact_id,
                "confidence_score": confidence,
                "diff_available": bool(file_row.get("diff")),
                "comparison_view": "dbt_source_target_diff" if "dbt" in run.workflow_type.lower() or "models/" in target else "sql_source_target_diff",
            }

            if status == "FAILED" or file_row.get("converted_file_ready") is False:
                specs.append(
                    ReviewSpec(
                        item_type="FAILED_CONVERSION",
                        severity="CRITICAL",
                        title=f"Conversion did not produce trusted output for {source}",
                        description="UMA could not mark the converted SQL/dbt artifact as ready. This blocks migration readiness because downstream validation would be testing an untrusted target artifact.",
                        recommendation="Open the side-by-side source/target comparison, fix unsupported syntax or parser failures, regenerate the target artifact, then rerun Brain Review.",
                        metadata={**base, "reason": f"conversion_status={status or 'UNKNOWN'}", "evidence": "; ".join(unsupported + warnings) or "Converted file was not marked ready."},
                    )
                )

            if confidence < 0.80:
                specs.append(
                    ReviewSpec(
                        item_type="LOW_CONFIDENCE_DIALECT",
                        severity="MEDIUM",
                        title=f"Low confidence dialect detection for {source}",
                        description="Dialect detection confidence is below the production review threshold. The selected rewrite rules may not match the source system semantics.",
                        recommendation="Confirm the source dialect, rerun conversion with an explicit dialect if needed, and review the generated diff before approval.",
                        metadata={**base, "reason": f"confidence={confidence}", "evidence": "; ".join(file_row.get("detection_reasons") or [])},
                    )
                )

            if unsupported:
                specs.append(
                    ReviewSpec(
                        item_type="UNSUPPORTED_SOURCE_SYNTAX",
                        severity="HIGH",
                        title=f"Unsupported source syntax remains in {source}",
                        description="UMA detected source-dialect residue or constructs that cannot be trusted without human review.",
                        recommendation="Replace or manually rewrite the unsupported constructs, then rerun conversion and Snowflake syntax validation.",
                        metadata={**base, "reason": "Unsupported source syntax remains.", "evidence": "\n".join(f"- {item}" for item in unsupported[:12])},
                    )
                )

            combined = "\n".join(unsupported + warnings + [file_row.get("diff") or ""])
            if any(token in combined.upper() for token in ("UNNEST", "FLATTEN", "GENERATE_DATE_ARRAY", "ARRAY_GENERATE_RANGE")):
                specs.append(
                    ReviewSpec(
                        item_type="UNNEST_FLATTEN_REWRITE",
                        severity="HIGH",
                        title=f"Array/date expansion semantics need review for {source}",
                        description="UMA rewrote or flagged array/date expansion logic. These patterns can change row counts, date ranges, and join cardinality when moving to Snowflake.",
                        recommendation="Compare source and target SQL side by side, validate generated ranges with sample data, and approve only after row-count and business-rule checks pass.",
                        metadata={**base, "reason": "UNNEST/FLATTEN or date-array logic requires semantic approval.", "evidence": combined[:4000]},
                    )
                )

            dbt_metadata = file_row.get("dbt_metadata") or {}
            if dbt_metadata.get("sources") or dbt_metadata.get("source_relations"):
                specs.append(
                    ReviewSpec(
                        item_type="DBT_SOURCE_MAPPING_REVIEW",
                        severity="MEDIUM",
                        title=f"dbt source mapping requires owner review for {source}",
                        description="UMA preserved or inferred dbt source mappings. A project owner must verify source names, table names, and environment-specific database/schema bindings.",
                        recommendation="Open the source/target dbt model comparison, verify source() and ref() mappings, then approve the generated sources.yml/schema.yml changes.",
                        metadata={**base, "reason": "dbt source/ref mappings are migration-sensitive.", "evidence": json.dumps(dbt_metadata.get("source_relations") or dbt_metadata.get("sources"), indent=2)[:4000]},
                    )
                )

            for finding in findings:
                finding_text = str(finding.get("finding") or "").strip()
                if not finding_text:
                    continue
                sev = _severity(finding.get("severity"), "MEDIUM")
                if sev == "INFO" and "No SQL was executed" not in finding_text:
                    continue
                specs.append(
                    ReviewSpec(
                        item_type="AGENT_REVIEW_FINDING",
                        severity="HIGH" if "No SQL was executed" in finding_text else sev,
                        title=f"{finding.get('agent') or 'UMA specialist'} finding for {source}",
                        description=finding_text,
                        recommendation="Review the evidence, run the missing validation step where applicable, and mark the item resolved only when the target artifact is trustworthy.",
                        metadata={**base, "reason": finding_text, "evidence": finding_text, "agent": finding.get("agent")},
                    )
                )

        if files:
            if summary.get("llm_available") is False:
                specs.append(
                    ReviewSpec(
                        item_type="MISSING_LLM_PROVIDER",
                        severity="MEDIUM",
                        title=f"LLM review was unavailable for {run.name}",
                        description="UMA completed deterministic/static review, but no configured LLM provider was available for an additional semantic rewrite/review pass.",
                        recommendation="Configure an LLM provider for complex SQL/dbt rewrites or document why deterministic review is sufficient for this run.",
                        metadata={"source_object": run.name, "target_object": "AI review layer", "reason": "LLM provider unavailable.", "evidence": "summary.llm_available=false", "confidence_score": 0.7},
                    )
                )
            if not summary.get("validation") and run.target_connection_id is None:
                specs.append(
                    ReviewSpec(
                        item_type="MISSING_SNOWFLAKE_EXECUTION",
                        severity="HIGH",
                        title=f"Snowflake execution validation did not run for {run.name}",
                        description="The conversion may look complete, but UMA has not executed syntax validation or data validation against Snowflake.",
                        recommendation="Configure the Snowflake target connection, run syntax validation and row/sample checks, then approve the conversion.",
                        metadata={"source_object": run.name, "target_object": "Snowflake validation", "reason": "No Snowflake target execution evidence.", "evidence": "target_connection_id is not configured or validation payload is absent.", "confidence_score": 0.88},
                    )
                )
        return specs

    def _dbt_specs(
        self,
        run: ControlPlaneRun,
        summary: dict[str, Any],
        artifacts: list[ControlPlaneArtifact],
    ) -> list[ReviewSpec]:
        if run.workflow_type not in {"DBT_CONVERSION", "DBT_PROJECT_ANALYSIS", "DBT_MODEL_CREATION"}:
            return []
        specs: list[ReviewSpec] = []
        for item in summary.get("review_items") or []:
            message = item.get("message") if isinstance(item, dict) else str(item)
            specs.append(
                ReviewSpec(
                    item_type="DBT_CONVERSION_ISSUE",
                    severity=_severity(item.get("severity") if isinstance(item, dict) else "WARN"),
                    title=f"dbt conversion review required: {message}",
                    description="UMA found a dbt modeling or materialization issue that needs human approval before generated artifacts are trusted.",
                    recommendation="Review the model boundary, materialization, source mappings, and generated dbt YAML before approving.",
                    metadata={"source_object": run.name, "target_object": "Generated dbt project", "reason": message, "evidence": message, "confidence_score": 0.76},
                )
            )
        for candidate in summary.get("model_candidates") or []:
            name = candidate.get("name") or "generated_model"
            sources = candidate.get("sources") or []
            if not sources:
                specs.append(
                    ReviewSpec(
                        item_type="DBT_SOURCE_MAPPING_REVIEW",
                        severity="HIGH",
                        title=f"Generated dbt model {name} has no confirmed source mapping",
                        description="UMA can generate a dbt model skeleton, but it cannot prove the source relation without confirmed mapping evidence.",
                        recommendation="Map the source relation explicitly, regenerate the model, and compare source SQL to generated dbt SQL side by side.",
                        metadata={"source_object": name, "target_object": f"models/{candidate.get('layer', 'staging')}/{name}.sql", "reason": "No source mapping was inferred.", "evidence": json.dumps(candidate, indent=2), "confidence_score": 0.55, "comparison_view": "dbt_source_target_diff"},
                    )
                )
            if candidate.get("materialization") == "incremental":
                specs.append(
                    ReviewSpec(
                        item_type="TABLE_MIGRATION_RISK",
                        severity="HIGH",
                        title=f"Incremental dbt model {name} needs key and cursor review",
                        description="Incremental models require merge keys, watermarks, and duplicate handling to be production-safe on Snowflake.",
                        recommendation="Confirm unique_key, incremental predicate, late-arriving data behavior, and rollback strategy before approval.",
                        metadata={"source_object": name, "target_object": f"models/{candidate.get('layer', 'intermediate')}/{name}.sql", "reason": "Incremental materialization inferred.", "evidence": json.dumps(candidate, indent=2), "confidence_score": 0.72, "comparison_view": "dbt_source_target_diff"},
                    )
                )
        for model_name in summary.get("missing_tests") or []:
            specs.append(
                ReviewSpec(
                    item_type="DBT_CONVERSION_ISSUE",
                    severity="MEDIUM",
                    title=f"dbt model {model_name} is missing test coverage",
                    description="Existing dbt project analysis found a model without schema.yml test coverage.",
                    recommendation="Add at least uniqueness/not-null/accepted-values tests where business keys are known before cutover readiness.",
                    metadata={"source_object": model_name, "target_object": "dbt schema.yml", "reason": "Missing model tests.", "evidence": str(model_name), "confidence_score": 0.86},
                )
            )
        return specs

    def _validation_specs(self, run: ControlPlaneRun, summary: dict[str, Any]) -> list[ReviewSpec]:
        results = summary.get("results") or []
        specs = []
        validation = summary.get("validation") or {}
        validation_status = str(validation.get("validation_status") or "").lower()
        if validation and not validation.get("validation_passed"):
            reason = validation.get("blocked_reason") or validation_status or "validation_not_passed"
            errors = validation.get("compile_errors") or validation.get("model_errors") or validation.get("warnings") or []
            title_by_status = {
                "credentials_required": "Snowflake credentials are required",
                "connection_failed": "Snowflake connection validation failed",
                "permission_failed": "Snowflake permission validation failed",
                "target_not_ready": "Snowflake target is not ready",
                "compile_passed": "dbt compile passed but Snowflake validation has not passed",
                "validation_failed": "Snowflake validation failed",
            }
            item_type_by_status = {
                "credentials_required": "SNOWFLAKE_CONNECTION_FAILURE",
                "connection_failed": "SNOWFLAKE_CONNECTION_FAILURE",
                "permission_failed": "SNOWFLAKE_PERMISSION_FAILURE",
                "target_not_ready": "SNOWFLAKE_TARGET_NOT_READY",
                "compile_passed": "SNOWFLAKE_VALIDATION_NOT_RUN",
                "validation_failed": "SNOWFLAKE_VALIDATION_FAILURE",
            }
            explain_failures = [
                row for row in validation.get("syntax_results") or []
                if str(row.get("status") or "").lower() != "passed"
            ]
            specs.append(
                ReviewSpec(
                    item_type=item_type_by_status.get(validation_status, "VALIDATION_FAILURE"),
                    severity="CRITICAL" if validation_status in {"connection_failed", "permission_failed", "target_not_ready", "validation_failed"} else "HIGH",
                    title=title_by_status.get(validation_status, f"Validation gate is not passed for {run.name}"),
                    description="UMA cannot mark the generated Snowflake/dbt package ready until target connectivity, permissions, dbt compile, and safe Snowflake EXPLAIN validation pass or an explicit Brain Review waiver is approved.",
                    recommendation="Open the validation report, fix connection/permission/EXPLAIN failures, rerun Snowflake validation, and approve any waiver through Brain Review only when the risk is accepted.",
                    metadata={
                        "source_object": run.name,
                        "target_object": "Snowflake validation gate",
                        "reason": reason,
                        "evidence": json.dumps(validation, indent=2)[:4000],
                        "confidence_score": 0.9,
                        "owner": "Migration owner",
                        "compile_errors": errors,
                        "validation_job_id": validation.get("validation_job_id"),
                    },
                )
            )
            for result in explain_failures:
                specs.append(
                    ReviewSpec(
                        item_type="SNOWFLAKE_EXPLAIN_FAILURE",
                        severity="CRITICAL",
                        title=f"Snowflake EXPLAIN failed for {result.get('model') or 'compiled model'}",
                        description="A compiled/generated model did not pass safe Snowflake EXPLAIN validation. UMA did not execute the model, but syntax/readiness is not proven.",
                        recommendation="Open the compiled SQL, fix the Snowflake syntax or unsupported statement, rerun dbt compile and Snowflake validation, then resolve this item.",
                        metadata={
                            "source_object": run.name,
                            "target_object": result.get("model") or "compiled model",
                            "reason": "; ".join(result.get("errors") or []) or "EXPLAIN failed.",
                            "evidence": json.dumps(result, indent=2)[:4000],
                            "confidence_score": 0.94,
                            "validation_job_id": validation.get("validation_job_id"),
                        },
                    )
                )
        for result in results:
            status = str(result.get("status") or "").upper()
            if status in {"MATCH", "PASSED", "PASS"}:
                continue
            table = result.get("table") or "validation target"
            specs.append(
                ReviewSpec(
                    item_type="VALIDATION_FAILURE",
                    severity="HIGH",
                    title=f"Validation failed or warned for {table}",
                    description="UMA validation evidence indicates the source and target are not yet proven equivalent.",
                    recommendation=result.get("recommendation") or "Open SQL Workspace from this finding, inspect failed rows/aggregates, remediate, and rerun validation.",
                    metadata={"source_object": table, "target_object": table, "reason": f"validation_status={status}", "evidence": json.dumps(result, indent=2)[:4000], "confidence_score": 0.9},
                )
            )
        return specs

    def _generated_artifact_specs(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> list[ReviewSpec]:
        specs = []
        summary = run.summary_json or {}
        migration_summary = summary.get("migration_summary") or {}
        risk_count = len(summary.get("risk_register") or [])
        source_count = migration_summary.get("artifact_count") or migration_summary.get("sql_file_count") or len([
            artifact for artifact in artifacts
            if artifact.artifact_category in {"SOURCE_SQL", "SOURCE_DDL", "DBT_PROJECT"}
        ])
        for artifact in artifacts:
            if artifact.artifact_category not in {"GENERATED_DBT", "GENERATED_SQL", "REPORT", "DATA_CONTRACT"}:
                continue
            if artifact.artifact_category == "REPORT" and run.status not in {"REQUIRES_REVIEW", "APPROVAL_REQUIRED"}:
                continue
            title = f"Review {artifact.original_filename} for {run.name}"
            recommendation = "Verify the generated artifact matches the selected source evidence, risk register, readiness score, and validation plan before approving it for customer-facing use."
            evidence_bits = [f"{artifact.artifact_category} created at {artifact.created_at.isoformat() if artifact.created_at else 'unknown time'}"]
            if source_count:
                evidence_bits.append(f"source_artifacts={source_count}")
            if risk_count:
                evidence_bits.append(f"open_report_risks={risk_count}")
            specs.append(
                ReviewSpec(
                    item_type="GENERATED_ARTIFACT_APPROVAL",
                    severity="MEDIUM",
                    title=title,
                    description=f"{artifact.original_filename} was generated from the selected migration run and needs approval before it is used as client-ready evidence.",
                    recommendation=recommendation,
                    metadata={
                        "source_object": run.name,
                        "target_object": artifact.original_filename,
                        "generated_artifact_id": artifact.id,
                        "reason": f"Generated {artifact.artifact_category.lower()} requires approval for {run.name}.",
                        "evidence": "; ".join(evidence_bits),
                        "confidence_score": 0.78,
                    },
                )
            )
        return specs

    def _source_artifact_id(self, source: str, artifacts: list[ControlPlaneArtifact]) -> str | None:
        for artifact in artifacts:
            names = [artifact.original_filename or "", artifact.filename or ""]
            if any(name and name in source for name in names):
                return artifact.id
        return None
