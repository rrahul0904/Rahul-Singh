from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ArtifactChunk,
    ArtifactExtraction,
    MigrationIntelligenceFinding,
    MigrationIntelligenceReport,
    MigrationIntelligenceRun,
    MigrationIntelligenceRunStep,
    UploadedArtifact,
)
from services.migration_intelligence_backend import render_report_markdown


class MigrationIntelligenceOrchestrator:
    STEP_NAMES = [
        "intake",
        "extraction_verification",
        "classification",
        "source_understanding",
        "dependency_extraction",
        "sql_procedure_inventory",
        "snowflake_compatibility_assessment",
        "replication_impact_assessment",
        "conversion_recommendations",
        "risk_readiness_assessment",
        "report_generation",
    ]

    def __init__(self, db: AsyncSession):
        self.db = db
        self._sequence = 0

    async def _create_step(self, run_id: str, name: str) -> MigrationIntelligenceRunStep:
        self._sequence += 1
        step = MigrationIntelligenceRunStep(
            run_id=run_id,
            step_name=name,
            sequence=self._sequence,
            status="RUNNING",
            started_at=datetime.utcnow(),
        )
        self.db.add(step)
        await self.db.flush()
        return step

    async def _finish_step(self, step: MigrationIntelligenceRunStep, status: str, details: dict | None = None, error: str | None = None) -> None:
        step.status = status
        step.completed_at = datetime.utcnow()
        step.details_json = details or {}
        step.error_message = error
        await self.db.flush()

    async def _create_finding(
        self,
        run_id: str,
        severity: str,
        finding_type: str,
        title: str,
        description: str,
        evidence: list[str],
        source_artifact_id: str | None,
        recommended_action: str,
        status: str = "OPEN",
    ) -> None:
        self.db.add(
            MigrationIntelligenceFinding(
                run_id=run_id,
                severity=severity,
                finding_type=finding_type,
                title=title,
                description=description,
                evidence=evidence,
                source_artifact_id=source_artifact_id,
                recommended_action=recommended_action,
                status=status,
            )
        )
        await self.db.flush()

    async def run(self, run: MigrationIntelligenceRun) -> MigrationIntelligenceReport:
        run.status = "RUNNING"
        run.token_credit_note = "Deterministic local orchestrator only; no OpenAI or Snowflake Cortex credits consumed."
        await self.db.flush()

        artifacts = (
            await self.db.execute(select(UploadedArtifact).where(UploadedArtifact.id.in_(run.selected_artifact_ids)))
        ).scalars().all()
        extractions = {
            row.artifact_id: row
            for row in (
                await self.db.execute(select(ArtifactExtraction).where(ArtifactExtraction.artifact_id.in_(run.selected_artifact_ids)))
            ).scalars().all()
        }
        chunks = (
            await self.db.execute(
                select(ArtifactChunk).where(ArtifactChunk.artifact_id.in_(run.selected_artifact_ids)).order_by(ArtifactChunk.chunk_index.asc())
            )
        ).scalars().all()

        artifact_map = {artifact.id: artifact for artifact in artifacts}
        chunk_groups: dict[str, list[ArtifactChunk]] = {}
        for chunk in chunks:
            chunk_groups.setdefault(chunk.artifact_id, []).append(chunk)

        inventory = {
            "tables": set(),
            "views": set(),
            "procedures": set(),
            "packages": set(),
            "dependencies": set(),
            "bteq_commands": set(),
            "ddl_count": 0,
            "dml_count": 0,
            "procedure_count": 0,
            "requirements_count": 0,
            "mapping_docs_count": 0,
            "missing_primary_key_artifacts": [],
            "missing_watermark_artifacts": [],
        }
        source_counts: dict[str, int] = {}

        intake = await self._create_step(run.id, "intake")
        await self._finish_step(
            intake,
            "COMPLETED",
            {
                "artifact_count": len(artifacts),
                "selected_artifact_ids": run.selected_artifact_ids,
                "uploaded_sql_executed": False,
                "generated_code_executed": False,
            },
        )

        verify = await self._create_step(run.id, "extraction_verification")
        usable_artifacts = []
        blocked_artifacts = []
        for artifact in artifacts:
            if artifact.extraction_status in {"FAILED_EXTRACTION", "UNSUPPORTED_TYPE", "NEEDS_OCR_NOT_SUPPORTED"}:
                blocked_artifacts.append(artifact.id)
                finding_type = "BLOCKER" if artifact.extraction_status != "UNSUPPORTED_TYPE" else "RECOMMENDATION"
                severity = "HIGH" if artifact.extraction_status != "UNSUPPORTED_TYPE" else "MEDIUM"
                await self._create_finding(
                    run.id,
                    severity,
                    finding_type,
                    f"{artifact.file_name} could not be fully analyzed",
                    artifact.error_message or f"Artifact status is {artifact.extraction_status}.",
                    [artifact.extracted_text_preview or "", artifact.storage_path],
                    artifact.id,
                    "Upload a text-based source artifact or provide a PDF with embedded text.",
                )
            else:
                usable_artifacts.append(artifact.id)
        await self._finish_step(
            verify,
            "COMPLETED",
            {"usable_artifact_ids": usable_artifacts, "blocked_artifact_ids": blocked_artifacts},
        )

        classify = await self._create_step(run.id, "classification")
        for artifact in artifacts:
            source_counts[artifact.source_system_guess or "Unknown"] = source_counts.get(artifact.source_system_guess or "Unknown", 0) + 1
            if artifact.classification == "REQUIREMENTS":
                inventory["requirements_count"] += 1
                await self._create_finding(
                    run.id,
                    "LOW",
                    "REQUIREMENT_DETECTED",
                    f"Requirements content detected in {artifact.file_name}",
                    "Narrative requirements were detected and should be incorporated into migration design and judge review.",
                    [artifact.extracted_text_preview or ""],
                    artifact.id,
                    "Review requirement text during design and sign-off.",
                    status="NOTED",
                )
            elif artifact.classification == "MAPPING_DOC":
                inventory["mapping_docs_count"] += 1
        await self._finish_step(
            classify,
            "COMPLETED",
            {"classifications": {artifact.id: artifact.classification for artifact in artifacts}},
        )

        source_step = await self._create_step(run.id, "source_understanding")
        dominant_source = max(source_counts, key=source_counts.get) if source_counts else "Unknown"
        await self._finish_step(source_step, "COMPLETED", {"source_system_counts": source_counts, "dominant_source": dominant_source})

        dependency = await self._create_step(run.id, "dependency_extraction")
        for artifact in artifacts:
            extraction = extractions.get(artifact.id)
            metadata = extraction.metadata_json if extraction else {}
            for bucket in ("tables", "views", "procedures", "packages", "dependencies", "bteq_commands"):
                inventory[bucket].update(metadata.get(bucket, []))
            if not metadata.get("has_primary_key") and metadata.get("tables"):
                inventory["missing_primary_key_artifacts"].append(artifact.id)
                await self._create_finding(
                    run.id,
                    "MEDIUM",
                    "MISSING_PRIMARY_KEY",
                    f"Primary key metadata missing in {artifact.file_name}",
                    "Detected table definitions or table references without explicit primary key evidence.",
                    metadata.get("tables", []),
                    artifact.id,
                    "Confirm business keys or replication merge keys before conversion.",
                )
            if not metadata.get("has_watermark") and metadata.get("dependencies"):
                inventory["missing_watermark_artifacts"].append(artifact.id)
                await self._create_finding(
                    run.id,
                    "MEDIUM",
                    "MISSING_WATERMARK",
                    f"Incremental watermark not evident in {artifact.file_name}",
                    "Dependency-bearing SQL lacks an obvious watermark or CDC timestamp column.",
                    metadata.get("dependencies", []),
                    artifact.id,
                    "Identify a trusted incremental watermark or plan full refresh behavior.",
                )
        for dep_name in sorted(inventory["dependencies"]):
            await self._create_finding(
                run.id,
                "LOW",
                "TABLE_DEPENDENCY",
                f"Dependency detected: {dep_name}",
                "A table or view reference was detected and added to lineage evidence.",
                [dep_name],
                None,
                "Confirm upstream availability and cutover order.",
                status="NOTED",
            )
        await self._finish_step(
            dependency,
            "COMPLETED",
            {k: sorted(v) if isinstance(v, set) else v for k, v in inventory.items() if k in {"tables", "views", "procedures", "packages", "dependencies", "bteq_commands"}},
        )

        inventory_step = await self._create_step(run.id, "sql_procedure_inventory")
        for chunk in chunks:
            if chunk.statement_type == "DDL":
                inventory["ddl_count"] += 1
            elif chunk.statement_type == "DML":
                inventory["dml_count"] += 1
            elif chunk.statement_type in {"PROCEDURE", "BTEQ_CONTROL"}:
                inventory["procedure_count"] += 1
        await self._finish_step(
            inventory_step,
            "COMPLETED",
            {
                "ddl_count": inventory["ddl_count"],
                "dml_count": inventory["dml_count"],
                "procedure_count": inventory["procedure_count"],
            },
        )

        compatibility = await self._create_step(run.id, "snowflake_compatibility_assessment")
        for artifact in artifacts:
            extraction = extractions.get(artifact.id)
            metadata = extraction.metadata_json if extraction else {}
            if metadata.get("bteq_commands"):
                await self._create_finding(
                    run.id,
                    "HIGH",
                    "BTEQ_CONTROL_FLOW",
                    f"BTEQ control flow detected in {artifact.file_name}",
                    "BTEQ session and control commands are not directly portable to Snowflake SQL.",
                    metadata.get("bteq_commands", []),
                    artifact.id,
                    "Convert BTEQ orchestration into application, stored procedure, or task-based control flow.",
                )
            if metadata.get("packages"):
                await self._create_finding(
                    run.id,
                    "HIGH",
                    "PROCEDURE_CONVERSION_REQUIRED",
                    f"Oracle package conversion required for {artifact.file_name}",
                    "PL/SQL package constructs will require redesign for Snowflake stored procedures or external orchestration.",
                    metadata.get("packages", []),
                    artifact.id,
                    "Decompose package bodies into Snowflake procedures, tasks, or external services.",
                )
            if artifact.classification in {"SQL", "PL_SQL", "BTEQ"} and metadata.get("tables"):
                await self._create_finding(
                    run.id,
                    "MEDIUM",
                    "DDL_CONVERSION_REQUIRED",
                    f"DDL conversion required for {artifact.file_name}",
                    "Source-side SQL objects will need Snowflake-compatible DDL and identifier review.",
                    metadata.get("tables", []) + metadata.get("views", []),
                    artifact.id,
                    "Generate Snowflake DDL with manual review before execution.",
                )
            if metadata.get("has_transaction_control"):
                await self._create_finding(
                    run.id,
                    "MEDIUM",
                    "TRANSACTION_BEHAVIOR_RISK",
                    f"Transaction semantics require review in {artifact.file_name}",
                    "BEGIN/COMMIT/ROLLBACK semantics may differ and can affect batching or exception behavior.",
                    [artifact.extracted_text_preview or ""],
                    artifact.id,
                    "Validate transactional intent against Snowflake procedure and task semantics.",
                )
        await self._create_finding(
            run.id,
            "MEDIUM",
            "SNOWFLAKE_COMPATIBILITY_RISK",
            "Manual Snowflake compatibility review required",
            "This local orchestrator performs deterministic heuristics only and does not validate SQL against a live Snowflake engine.",
            ["snowflake_sql_executed=False", "snowflake_cortex_called=False"],
            None,
            "Perform human review before any generated conversion is executed.",
        )
        await self._finish_step(compatibility, "COMPLETED", {"snowflake_sql_executed": False, "snowflake_cortex_called": False})

        replication = await self._create_step(run.id, "replication_impact_assessment")
        if inventory["dependencies"]:
            await self._create_finding(
                run.id,
                "LOW",
                "REPLICATION_CANDIDATE",
                "Dependency graph suggests replication candidates",
                "Referenced tables and views may need staged replication or CDC planning ahead of conversion.",
                sorted(inventory["dependencies"])[:20],
                None,
                "Prioritize high-churn dependencies for replication design.",
                status="NOTED",
            )
        await self._finish_step(
            replication,
            "COMPLETED",
            {
                "dependency_count": len(inventory["dependencies"]),
                "missing_primary_key_artifacts": inventory["missing_primary_key_artifacts"],
                "missing_watermark_artifacts": inventory["missing_watermark_artifacts"],
            },
        )

        conversion = await self._create_step(run.id, "conversion_recommendations")
        await self._create_finding(
            run.id,
            "LOW",
            "RECOMMENDATION",
            "Generate reviewed Snowflake conversion assets only after analysis",
            "The orchestrator prepared inventory and risks but intentionally did not execute uploaded SQL, generated code, or DDL.",
            ["uploaded_sql_executed=False", "generated_code_executed=False", "ddl_executed=False"],
            None,
            "Use findings and report sections to draft reviewed Snowflake DDL, procedures, and replication plans.",
            status="NOTED",
        )
        await self._finish_step(conversion, "COMPLETED", {"generated_code_executed": False, "ddl_executed": False})

        risk = await self._create_step(run.id, "risk_readiness_assessment")
        findings = (
            await self.db.execute(select(MigrationIntelligenceFinding).where(MigrationIntelligenceFinding.run_id == run.id))
        ).scalars().all()
        blocker_count = sum(1 for finding in findings if finding.finding_type == "BLOCKER")
        high_count = sum(1 for finding in findings if finding.severity == "HIGH")
        run.status = "BLOCKED" if not usable_artifacts else "NEEDS_REVIEW" if blocker_count or high_count else "COMPLETED"
        await self._finish_step(
            risk,
            "COMPLETED",
            {"blocker_count": blocker_count, "high_severity_count": high_count, "final_status": run.status},
        )

        report_step = await self._create_step(run.id, "report_generation")
        report_json = await self._build_report_json(run, artifacts, extractions, findings, inventory, dominant_source)
        report_markdown = render_report_markdown(report_json)
        report = MigrationIntelligenceReport(
            run_id=run.id,
            title=report_json["title"],
            report_json=report_json,
            report_markdown=report_markdown,
        )
        self.db.add(report)
        for artifact in artifacts:
            artifact.extraction_status = "INCLUDED_IN_REPORT" if artifact.id in usable_artifacts else artifact.extraction_status
        run.completed_at = datetime.utcnow()
        await self._finish_step(report_step, "COMPLETED", {"report_title": report.title, "report_sections": len(report_json.get("sections", []))})
        await self.db.commit()
        await self.db.refresh(report)
        return report

    async def _build_report_json(
        self,
        run: MigrationIntelligenceRun,
        artifacts: list[UploadedArtifact],
        extractions: dict[str, ArtifactExtraction],
        findings: list[MigrationIntelligenceFinding],
        inventory: dict,
        dominant_source: str,
    ) -> dict:
        by_type: dict[str, int] = {}
        for finding in findings:
            by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1

        evidence_lines = []
        weak_requirement_evidence = False
        for artifact in artifacts:
            extraction = extractions.get(artifact.id)
            meta = extraction.metadata_json if extraction else {}
            evidence_strength = meta.get("dependency_evidence_strength", "none")
            weak_requirement_evidence = weak_requirement_evidence or (
                artifact.classification in {"REQUIREMENTS", "MAPPING_DOC"} and evidence_strength != "strong"
            )
            ignored_tokens = meta.get("ignored_dependency_candidates", [])
            evidence_lines.append(
                f"{artifact.file_name}: classification={artifact.classification}, source={artifact.source_system_guess}, "
                f"tables={len(meta.get('tables', []))}, dependencies={len(meta.get('dependencies', []))}"
            )
            if artifact.classification in {"REQUIREMENTS", "MAPPING_DOC"}:
                evidence_lines.append(
                    f"{artifact.file_name}: dependency_evidence={evidence_strength}, "
                    f"ignored_candidates={', '.join(ignored_tokens) or 'none'}"
                )

        dependency_lines = []
        if inventory["dependencies"]:
            dependency_lines.append(f"Dependencies: {', '.join(sorted(inventory['dependencies']))}")
        if weak_requirement_evidence and not inventory["dependencies"]:
            dependency_lines.append("No strong dependency evidence was detected from the uploaded requirement text.")
        elif weak_requirement_evidence:
            dependency_lines.append("Narrative requirement text did not add strong dependency evidence beyond SQL-derived objects.")

        sections = [
            {"title": "Executive Summary", "content": [
                f"Run status: {run.status}",
                f"Artifacts analyzed: {len(artifacts)}",
                f"Dominant source system guess: {dominant_source}",
                "OpenAI called: No",
                "Snowflake Cortex called: No",
                "Snowflake SQL executed: No",
                "Uploaded SQL executed: No",
                "Generated code executed: No",
                "DDL/DML executed: No",
                "Data moved: No",
            ]},
            {"title": "Inputs Analyzed", "content": [f"{a.file_name} ({a.file_type}, {a.classification}, {a.extraction_status})" for a in artifacts]},
            {"title": "Source System Understanding", "content": [f"Dominant source system guess: {dominant_source}"]},
            {"title": "SQL / Procedure / DDL Inventory", "content": [
                f"DDL chunks: {inventory['ddl_count']}",
                f"DML chunks: {inventory['dml_count']}",
                f"Procedure/BTEQ chunks: {inventory['procedure_count']}",
                f"Tables: {', '.join(sorted(inventory['tables'])) or 'None detected'}",
                f"Views: {', '.join(sorted(inventory['views'])) or 'None detected'}",
                f"Procedures: {', '.join(sorted(inventory['procedures'])) or 'None detected'}",
                f"Packages: {', '.join(sorted(inventory['packages'])) or 'None detected'}",
            ]},
            {"title": "Dependency and Lineage Findings", "content": dependency_lines or ["None detected"]},
            {"title": "Snowflake Compatibility Assessment", "content": [
                f"High-severity compatibility findings: {sum(1 for finding in findings if finding.severity == 'HIGH')}",
                f"BTEQ commands: {', '.join(sorted(inventory['bteq_commands'])) or 'None detected'}",
            ]},
            {"title": "Data Replication Assessment", "content": [
                f"Missing primary key artifacts: {len(inventory['missing_primary_key_artifacts'])}",
                f"Missing watermark artifacts: {len(inventory['missing_watermark_artifacts'])}",
            ]},
            {"title": "Conversion Plan", "content": [
                "Convert source DDL to Snowflake DDL with manual review.",
                "Separate orchestration logic from source-specific procedural wrappers.",
                "Treat requirements and mapping documents as design constraints, not executable inputs.",
            ]},
            {"title": "Generated DDL / Code Recommendations", "content": [
                "Generate reviewed Snowflake CREATE/ALTER statements only after human approval.",
                "Do not execute uploaded SQL or generated code automatically.",
            ]},
            {"title": "Technical Design Document", "content": [
                "Artifact upload persists raw files, extracted text, and deterministic chunks.",
                "The orchestrator records run steps, findings, and a canonical report JSON/Markdown pair.",
                "PDF and DOCX exports are produced from saved report content, not regenerated prompts.",
            ]},
            {"title": "Risk Assessment", "content": [f"{key}: {value}" for key, value in sorted(by_type.items())]},
            {"title": "Snowflake Readiness", "content": [
                "Readiness is heuristic-only in local mode.",
                "No Snowflake connection or SQL execution was invoked by this run.",
            ]},
            {"title": "Blockers", "content": [finding.title for finding in findings if finding.finding_type == "BLOCKER"] or ["No hard blockers beyond flagged review items."]},
            {"title": "Recommended Next Actions", "content": [
                "Review high-severity compatibility findings first.",
                "Confirm primary keys and watermark strategy for replicated objects.",
                "Draft reviewed Snowflake DDL and procedure conversions from the inventory.",
            ]},
            {"title": "Judge Pass Review Scaffold", "content": [
                "Reviewer questions:",
                "1. Are all source dependencies and control-flow constructs accounted for?",
                "2. Are conversion recommendations safe without automatic execution?",
                "3. Are replication keys, watermarks, and cutover risks documented?",
            ]},
            {"title": "Appendix: Evidence", "content": evidence_lines},
        ]
        return {
            "title": f"Migration Intelligence Report {run.id}",
            "run_id": run.id,
            "generated_at": datetime.utcnow().isoformat(),
            "flags": {
                "openai_called": False,
                "snowflake_cortex_called": False,
                "snowflake_sql_executed": False,
                "uploaded_sql_executed": False,
                "generated_code_executed": False,
                "ddl_executed": False,
                "data_moved": False,
            },
            "sections": sections,
        }
