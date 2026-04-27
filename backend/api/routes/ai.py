"""UMA Platform — OpenAI-powered AI Routes."""
from typing import Any, Dict, List, Optional
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from models import Connection, Job, JobLog, JobTask

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
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)):
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


@router.post("/sql")
async def generate_sql(body: SQLRequest):
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
async def agent_run(body: AgentRequest, db: AsyncSession = Depends(get_db)):
    platform_ctx = await _ctx(db)
    system = (
        "You are UMA AI orchestration assistant. Plan and execute migration troubleshooting steps with concise action items."
    )
    prompt = f"User request:\n{body.message}\n\nPlatform context:\n{platform_ctx}\n\nAdditional context:\n{body.context or {}}"
    out = await _openai_complete(system, prompt, max_tokens=1000, temperature=0.2)
    return {"reply": out["text"], "model": out["model"]}


@router.post("/summarize")
async def summarize_job(body: SummarizeRequest, db: AsyncSession = Depends(get_db)):
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


@router.post("/document")
async def document_table(body: DocumentRequest):
    out = await _openai_complete(
        "Write concise data catalog documentation for a technical audience.",
        f"Table name: {body.table_name}\nSchema: {body.schema}\nSample rows: {body.sample_rows or []}",
        max_tokens=900,
        temperature=0.2,
    )
    return {"documentation": out["text"], "table": body.table_name}


@router.post("/validate-suggest")
async def suggest_validation(body: ValidateSuggestRequest):
    out = await _openai_complete(
        "Generate robust validation rules for migration verification. Return JSON array of rules with name, type, and sql.",
        f"Table: {body.table_name}\nSchema: {body.schema}",
        max_tokens=1000,
        temperature=0.1,
    )
    return {"rules": out["text"], "table": body.table_name}


@router.post("/explain-sql")
async def explain_sql_route(body: ExplainSQLRequest):
    out = await _openai_complete(
        "Explain SQL clearly for data engineers. Keep it structured and concise.",
        body.sql,
        max_tokens=900,
        temperature=0.2,
    )
    return {"explanation": out["text"]}


@router.post("/dbt-model")
async def dbt_model(body: DBTModelRequest):
    out = await _openai_complete(
        "Generate a dbt model SQL and a matching YAML tests snippet.",
        f"Source table: {body.source_table}\nColumns: {body.schema}",
        max_tokens=1100,
        temperature=0.2,
    )
    return {"dbt_model": out["text"], "table": body.source_table}


@router.post("/search")
async def search_metadata(body: SearchRequest):
    # Placeholder for future vector search; keep API shape stable.
    return {"results": [], "query": body.query, "doc_types": body.doc_types or [], "top_k": body.top_k}


@router.get("/lineage/{table_name:path}")
async def get_lineage(table_name: str, db: AsyncSession = Depends(get_db)):
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
