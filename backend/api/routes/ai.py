"""UMA Platform — OpenAI-powered AI Routes."""
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.cortex_agent import CortexMigrationAgent
from core.auth import get_current_user
from core.config import settings
from core.database import get_db
from models import CodeGenerationArtifact, CodeGenerationJudgeReview, Connection, Job, JobLog, JobTask, User
from services.migration_intelligence import deterministic_migration_answer
from services.ollama_provider import OllamaClient
from services.ai import active_provider_status

router = APIRouter()
logger = logging.getLogger("uma.routes.ai")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: Optional[str] = None


class SQLRequest(BaseModel):
    question: str
    database: str = "ANALYTICS_DB"
    schema_name: str = "RAW"
    mode: str = "openai"
    table_metadata: Optional[List[Dict[str, Any]]] = None
    semantic_model: Optional[str] = None


class AgentRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None


class SummarizeRequest(BaseModel):
    job_id: str


class MigrationIntelligenceRequest(BaseModel):
    job_id: str
    question: str
    run_id: Optional[str] = None
    prompt_type: str = "cutover_readiness"


class DocumentRequest(BaseModel):
    table_name: str
    schema: List[Dict[str, Any]]
    sample_rows: Optional[List[Dict[str, Any]]] = None


class ValidateSuggestRequest(BaseModel):
    table_name: str
    schema: List[Dict[str, Any]]


class ExplainSQLRequest(BaseModel):
    sql: str


class DBTModelRequest(BaseModel):
    source_table: str
    schema: List[Dict[str, Any]]


class SearchRequest(BaseModel):
    query: str
    doc_types: Optional[List[str]] = None
    top_k: int = 5


class CodeGenerationRequest(BaseModel):
    generation_type: str
    prompt: str = ""
    source_code: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JudgePassRequest(BaseModel):
    score: int
    status: str = "NEEDS_IMPROVEMENT"
    improvement_points: List[str] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)
    notes: str = ""


class CodeRevisionRequest(BaseModel):
    prompt: str = ""


def _require_openai_key() -> str:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, "OPENAI_API_KEY not configured")
    return settings.OPENAI_API_KEY


def _openai_model() -> str:
    return (settings.OPENAI_MODEL or "gpt-4o-mini").strip()


def _openai_verify_tls() -> bool | str:
    insecure = os.getenv("OPENAI_INSECURE_MODE", "false").strip().lower() == "true"
    if insecure:
        return False
    ca_bundle = os.getenv("OPENAI_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE")
    return ca_bundle if ca_bundle else True


async def _ctx(db: AsyncSession) -> str:
    lines: List[str] = []
    try:
        r = await db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))
        lines.append(f"Jobs: {{ {', '.join(f'{row[0].value}: {row[1]}' for row in r)} }}")
        r2 = await db.execute(select(Job).where(Job.status == "FAILED").order_by(Job.updated_at.desc()).limit(3))
        for j in r2.scalars():
            lines.append(f"Failed: {j.name} phase={j.phase}")
        r3 = await db.execute(select(JobLog).where(JobLog.level == "ERROR").order_by(JobLog.created_at.desc()).limit(5))
        for l in r3.scalars():
            lines.append(f"Error: [{l.event}] {l.message}")
        r4 = await db.execute(select(Connection.name, Connection.type, Connection.health))
        for row in r4:
            lines.append(f"Conn: {row[0]} ({row[1].value}) {row[2]}")
    except Exception as exc:
        lines.append(f"Context error: {exc}")
    return "\n".join(lines)


async def _openai_chat(messages: List[Dict[str, str]], system: str, max_tokens: int = 1024, temperature: float = 0.2) -> Dict[str, Any]:
    api_key = _require_openai_key()
    model = _openai_model()
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}] + messages,
    }
    try:
        async with httpx.AsyncClient(timeout=90, verify=_openai_verify_tls()) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code >= 400:
                logger.error("OpenAI request failed status=%s body=%s", response.status_code, response.text)
                raise HTTPException(502, f"OpenAI request failed ({response.status_code})")
            data = response.json()
    except httpx.RequestError as exc:
        msg = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in msg or "certificate verify failed" in msg.lower():
            raise HTTPException(
                502,
                "OpenAI TLS certificate validation failed. Set OPENAI_CA_BUNDLE or REQUESTS_CA_BUNDLE "
                "to your corporate CA bundle, or set OPENAI_INSECURE_MODE=true only for local dev."
            ) from exc
        raise HTTPException(502, f"OpenAI request error: {msg}") from exc
    message = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    return {"text": message.strip(), "model": data.get("model", model)}


async def _openai_complete(system: str, user_prompt: str, max_tokens: int = 1024, temperature: float = 0.2) -> Dict[str, Any]:
    return await _openai_chat([{"role": "user", "content": user_prompt}], system, max_tokens=max_tokens, temperature=temperature)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _ctx(db)
    system = (
        "You are UMA AI, an expert migration copilot for Snowflake workloads. "
        "Give practical, specific guidance with short, clear steps. "
        "Use Snowflake SQL syntax and double-quoted identifiers when returning SQL.\n\n"
        f"LIVE PLATFORM CONTEXT:\n{ctx}"
    )
    if body.context:
        system += f"\n\nEXTRA CONTEXT:\n{body.context}"
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    out = await _openai_chat(msgs, system, max_tokens=1400, temperature=0.2)
    return {"reply": out["text"], "model": out["model"]}


@router.get("/providers/ollama/health")
async def ollama_health(
    test_generation: bool = False,
    test_embedding: bool = False,
    _user: User = Depends(get_current_user),
):
    return await OllamaClient().health(test_generation=test_generation, test_embedding=test_embedding)


@router.get("/providers/status")
async def provider_status(
    provider: str | None = None,
    _user: User = Depends(get_current_user),
):
    return await active_provider_status(provider)


@router.post("/sql")
async def generate_sql(
    body: SQLRequest,
    _user: User = Depends(get_current_user),
):
    schema_context = ""
    if body.table_metadata:
        lines = []
        for t in body.table_metadata:
            cols = ", ".join(
                f"{c.get('name', '')} {c.get('type', '')}".strip()
                for c in t.get("columns", [])
            )
            lines.append(f'Table: {t.get("name", "")}\nColumns: {cols}')
        schema_context = "\n\n".join(lines)

    system = (
        "You are a Snowflake SQL expert. Return only SQL, no prose, no markdown fencing.\n"
        "Rules:\n"
        '- Use fully qualified identifiers when possible: "DATABASE"."SCHEMA"."TABLE"\n'
        "- Prefer deterministic, production-safe SQL.\n"
        "- Add LIMIT 1000 for broad exploratory SELECT statements.\n"
    )
    prompt = (
        f"Target database: {body.database}\n"
        f"Target schema: {body.schema_name}\n"
        f"Question: {body.question}\n"
    )
    if schema_context:
        prompt += f"\nAvailable tables:\n{schema_context}\n"

    out = await _openai_complete(system, prompt, max_tokens=1200, temperature=0.1)
    sql = out["text"]
    if sql.startswith("```"):
        sql = "\n".join(sql.splitlines()[1:-1]).strip()
    return {"sql": sql, "model": out["model"], "mode": "openai"}


@router.post("/agent")
async def agent_run(
    body: AgentRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    platform_ctx = await _ctx(db)
    system = (
        "You are UMA AI orchestration assistant. Plan and execute migration troubleshooting steps with concise action items."
    )
    prompt = f"User request:\n{body.message}\n\nPlatform context:\n{platform_ctx}\n\nAdditional context:\n{body.context or {}}"
    out = await _openai_complete(system, prompt, max_tokens=1000, temperature=0.2)
    return {"reply": out["text"], "model": out["model"]}


@router.post("/cortex-agent")
async def cortex_agent_run(
    body: AgentRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.migration_intelligence import MigrationIntelligenceService

    service = MigrationIntelligenceService(db)
    return await service.answer_local(body.message, body.context)


@router.get("/cortex-agent/architecture")
async def cortex_agent_architecture(
    _user: User = Depends(get_current_user),
):
    agent = CortexMigrationAgent()
    return {
        "agent_name": agent.name,
        "version": agent.version,
        "architecture": agent.architecture(),
        "permission_checks": agent.permission_checklist(),
        "readiness": agent.readiness(),
        "internal_tool_registry": {
            "remote_mcp_server": False,
            "recommended_name_if_promoted_to_mcp": "uma-migration-tools-mcp",
            "transport": "authenticated FastAPI internal tools now; MCP HTTP/SSE only after hosted tool access is implemented",
        },
    }


@router.get("/cortex-agent/readiness")
async def cortex_agent_readiness(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.migration_intelligence import MigrationIntelligenceService

    ctx = await MigrationIntelligenceService(db).build_replication_context()
    return {
        "agent": CortexMigrationAgent().readiness(),
        "snowflake_readiness": ctx.get("snowflake_readiness", {}),
        "blocked_items": deterministic_migration_answer("Is this ready for Snowflake execution?", ctx)["blocked_items"],
    }


@router.post("/code-generation")
async def code_generation(
    body: CodeGenerationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.code_generation import generate_code_artifact_with_ai

    result = await generate_code_artifact_with_ai(
        generation_type=body.generation_type,
        prompt=body.prompt,
        source_code=body.source_code,
        metadata=body.metadata,
    )
    artifact = CodeGenerationArtifact(
        user_id=user.id,
        generation_type=result["generation_type"],
        source_language=result["source_language"],
        target_language=result["target_language"],
        prompt=body.prompt,
        source_code=body.source_code,
        metadata_json=body.metadata,
        basis_for_generation=result.get("basis_for_generation", "user_prompt_only"),
        revision_number=1,
        generated_code=result["generated_code"],
        technical_design_document=result["technical_design_document"],
        initial_judge_review=result["judge_pass_review"],
        safety_notes=result["safety_notes"],
        execution_ready=False,
        status="GENERATED",
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    payload = _code_artifact_dict(artifact, [])
    payload["judge_pass_review"] = result["judge_pass_review"]
    return payload


@router.get("/code-generation/artifacts")
async def list_code_generation_artifacts(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifacts = list(
        (
            await db.execute(
                select(CodeGenerationArtifact)
                .order_by(CodeGenerationArtifact.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
    )
    if not artifacts:
        return []
    artifact_ids = [row.id for row in artifacts]
    reviews = list(
        (
            await db.execute(
                select(CodeGenerationJudgeReview)
                .where(CodeGenerationJudgeReview.artifact_id.in_(artifact_ids))
                .order_by(CodeGenerationJudgeReview.created_at.desc())
            )
        ).scalars().all()
    )
    by_artifact: dict[str, list[CodeGenerationJudgeReview]] = {}
    for review in reviews:
        by_artifact.setdefault(review.artifact_id, []).append(review)
    return [_code_artifact_dict(row, by_artifact.get(row.id, [])) for row in artifacts]


@router.get("/code-generation/artifacts/{artifact_id}")
async def get_code_generation_artifact(
    artifact_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifact = await db.get(CodeGenerationArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Code generation artifact not found")
    reviews = list(
        (
            await db.execute(
                select(CodeGenerationJudgeReview)
                .where(CodeGenerationJudgeReview.artifact_id == artifact.id)
                .order_by(CodeGenerationJudgeReview.created_at.desc())
            )
        ).scalars().all()
    )
    payload = _code_artifact_dict(artifact, reviews)
    children = list(
        (
            await db.execute(
                select(CodeGenerationArtifact)
                .where(CodeGenerationArtifact.parent_artifact_id == artifact.id)
                .order_by(CodeGenerationArtifact.revision_number.asc())
            )
        ).scalars().all()
    )
    payload["revision_history"] = [
        {
            "id": row.id,
            "parent_artifact_id": row.parent_artifact_id,
            "revision_number": row.revision_number or 1,
            "status": row.status,
            "created_at": _dt(row.created_at),
        }
        for row in children
    ]
    return payload


@router.post("/code-generation/artifacts/{artifact_id}/revise")
async def revise_code_generation_artifact(
    artifact_id: str,
    body: CodeRevisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.code_generation import generate_code_artifact_with_ai

    artifact = await db.get(CodeGenerationArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Code generation artifact not found")
    reviews = list(
        (
            await db.execute(
                select(CodeGenerationJudgeReview)
                .where(CodeGenerationJudgeReview.artifact_id == artifact.id)
                .order_by(CodeGenerationJudgeReview.created_at.desc())
            )
        ).scalars().all()
    )
    improvement_points = []
    for review in reviews:
        improvement_points.extend(review.improvement_points or [])
        improvement_points.extend(review.blocking_issues or [])
    revision_prompt = "\n".join(
        [
            body.prompt or artifact.prompt,
            "Revise the artifact using saved Judge Pass review feedback:",
            *[f"- {item}" for item in improvement_points[:20]],
        ]
    ).strip()
    metadata = {
        **(artifact.metadata_json or {}),
        "previous_artifact_id": artifact.id,
        "previous_revision_number": artifact.revision_number or 1,
    }
    result = await generate_code_artifact_with_ai(
        generation_type=artifact.generation_type,
        prompt=revision_prompt,
        source_code=artifact.source_code,
        metadata=metadata,
    )
    child = CodeGenerationArtifact(
        user_id=user.id,
        generation_type=result["generation_type"],
        source_language=result["source_language"],
        target_language=result["target_language"],
        prompt=revision_prompt,
        source_code=artifact.source_code,
        metadata_json=metadata,
        basis_for_generation="previous_artifact_revision",
        parent_artifact_id=artifact.id,
        revision_number=(artifact.revision_number or 1) + 1,
        generated_code=result["generated_code"],
        technical_design_document=result["technical_design_document"],
        initial_judge_review=result["judge_pass_review"],
        safety_notes=result["safety_notes"],
        execution_ready=False,
        status="REVISED",
    )
    db.add(child)
    await db.commit()
    await db.refresh(child)
    return _code_artifact_dict(child, [])


@router.post("/code-generation/artifacts/{artifact_id}/judge-pass")
async def submit_judge_pass_review(
    artifact_id: str,
    body: JudgePassRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifact = await db.get(CodeGenerationArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Code generation artifact not found")
    if body.score < 1 or body.score > 5:
        raise HTTPException(400, "Judge Pass score must be between 1 and 5")
    status = body.status.strip().upper() or ("APPROVED" if body.score >= 5 else "NEEDS_IMPROVEMENT")
    review = CodeGenerationJudgeReview(
        artifact_id=artifact.id,
        reviewer_id=user.id,
        score=body.score,
        status=status,
        improvement_points=[item.strip() for item in body.improvement_points if item.strip()],
        blocking_issues=[item.strip() for item in body.blocking_issues if item.strip()],
        notes=body.notes,
    )
    artifact.status = status
    artifact.updated_at = datetime.utcnow()
    db.add(review)
    await db.commit()
    await db.refresh(review)
    reviews = list(
        (
            await db.execute(
                select(CodeGenerationJudgeReview)
                .where(CodeGenerationJudgeReview.artifact_id == artifact.id)
                .order_by(CodeGenerationJudgeReview.created_at.desc())
            )
        ).scalars().all()
    )
    return _code_artifact_dict(artifact, reviews)


def _dt(value):
    return value.isoformat() if value else None


def _judge_review_dict(row: CodeGenerationJudgeReview) -> dict[str, Any]:
    return {
        "id": row.id,
        "artifact_id": row.artifact_id,
        "reviewer_id": row.reviewer_id,
        "score": row.score,
        "status": row.status,
        "improvement_points": row.improvement_points or [],
        "blocking_issues": row.blocking_issues or [],
        "notes": row.notes,
        "created_at": _dt(row.created_at),
    }


def _code_artifact_dict(row: CodeGenerationArtifact, reviews: list[CodeGenerationJudgeReview]) -> dict[str, Any]:
    latest_review = reviews[0] if reviews else None
    return {
        "id": row.id,
        "generation_type": row.generation_type,
        "source_language": row.source_language,
        "target_language": row.target_language,
        "prompt": row.prompt,
        "source_code": row.source_code,
        "metadata": row.metadata_json or {},
        "basis_for_generation": row.basis_for_generation or "user_prompt_only",
        "parent_artifact_id": row.parent_artifact_id,
        "revision_number": row.revision_number or 1,
        "approval_status": row.status,
        "revision_history": [],
        "generated_code": row.generated_code,
        "technical_design_document": row.technical_design_document or {},
        "judge_pass_review": row.initial_judge_review or {},
        "safety_notes": row.safety_notes or [],
        "execution_ready": bool(row.execution_ready),
        "status": row.status,
        "latest_review": _judge_review_dict(latest_review) if latest_review else None,
        "reviews": [_judge_review_dict(review) for review in reviews],
        "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


@router.post("/summarize")
async def summarize_job(
    body: SummarizeRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    from api.routes.jobs import _job_dict, _task_dict
    tr = await db.execute(select(JobTask).where(JobTask.job_id == body.job_id))
    lr = await db.execute(select(JobLog).where(JobLog.job_id == body.job_id, JobLog.level == "ERROR").limit(20))
    payload = {
        "job": _job_dict(job),
        "tasks": [_task_dict(t) for t in tr.scalars()],
        "errors": [{"event": l.event, "message": l.message} for l in lr.scalars()],
    }
    out = await _openai_complete(
        "Summarize migration runs for engineering operators. Keep to 6 bullets max.",
        f"Create a concise run summary:\n{payload}",
        max_tokens=900,
        temperature=0.1,
    )
    return {"summary": out["text"], "job_id": body.job_id}


@router.post("/migration-intelligence")
async def migration_intelligence(
    body: MigrationIntelligenceRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.migration_intelligence import MigrationIntelligenceService

    class OpenAIProvider:
        async def complete(self, system: str, prompt: str) -> str:
            out = await _openai_complete(system, prompt, max_tokens=1200, temperature=0.1)
            return out["text"]

    provider = OpenAIProvider() if settings.OPENAI_API_KEY else None
    service = MigrationIntelligenceService(db, provider)
    return await service.answer(body.job_id, body.question, body.run_id, body.prompt_type)


@router.post("/document")
async def document_table(
    body: DocumentRequest,
    _user: User = Depends(get_current_user),
):
    out = await _openai_complete(
        "Write concise data catalog documentation for a technical audience.",
        f"Table name: {body.table_name}\nSchema: {body.schema}\nSample rows: {body.sample_rows or []}",
        max_tokens=900,
        temperature=0.2,
    )
    return {"documentation": out["text"], "table": body.table_name}


@router.post("/validate-suggest")
async def suggest_validation(
    body: ValidateSuggestRequest,
    _user: User = Depends(get_current_user),
):
    out = await _openai_complete(
        "Generate robust validation rules for migration verification. Return JSON array of rules with name, type, and sql.",
        f"Table: {body.table_name}\nSchema: {body.schema}",
        max_tokens=1000,
        temperature=0.1,
    )
    return {"rules": out["text"], "table": body.table_name}


@router.post("/explain-sql")
async def explain_sql_route(
    body: ExplainSQLRequest,
    _user: User = Depends(get_current_user),
):
    out = await _openai_complete(
        "Explain SQL clearly for data engineers. Keep it structured and concise.",
        body.sql,
        max_tokens=900,
        temperature=0.2,
    )
    return {"explanation": out["text"]}


@router.post("/dbt-model")
async def dbt_model(
    body: DBTModelRequest,
    _user: User = Depends(get_current_user),
):
    out = await _openai_complete(
        "Generate a dbt model SQL and a matching YAML tests snippet.",
        f"Source table: {body.source_table}\nColumns: {body.schema}",
        max_tokens=1100,
        temperature=0.2,
    )
    return {"dbt_model": out["text"], "table": body.source_table}


@router.post("/search")
async def search_metadata(
    body: SearchRequest,
    _user: User = Depends(get_current_user),
):
    # Placeholder for future vector search; keep API shape stable.
    return {"results": [], "query": body.query, "doc_types": body.doc_types or [], "top_k": body.top_k}


@router.get("/lineage/{table_name:path}")
async def get_lineage(
    table_name: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(JobTask, Job).join(Job, JobTask.job_id == Job.id)
        .where(JobTask.target_table == table_name)
        .order_by(Job.ended_at.desc()).limit(50)
    )
    lineage = []
    for task, job in r:
        lineage.append({
            "job_id": job.id,
            "job_name": job.name,
            "source_dataset": task.source_dataset,
            "source_table": task.source_table,
            "target_schema": f"{job.sf_database}.{job.sf_schema}",
            "rows_transferred": task.rows_exported,
            "load_strategy": job.load_strategy.value,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        })
    return {"table": table_name, "lineage": lineage}
