"""
UMA Platform — AI Service Layer
Implements:
  A. Text-to-SQL (OpenAI + Cortex Analyst mode)
  B. RAG / metadata search over migration assets
  C. Agentic orchestration (multi-step reasoning)
  D. AI Functions (summarize, classify, extract, document)
  E. Cortex benchmark mode (compare OpenAI vs Cortex Analyst)
"""

import logging
import json
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger("uma.services.ai")


# ══════════════════════════════════════════════════════════════
# Text-to-SQL Service (OpenAI + optional Cortex Analyst)
# ══════════════════════════════════════════════════════════════

class TextToSQLService:
    """
    Natural language → Snowflake SQL.
    Supports: OpenAI (default), Cortex Analyst (Snowflake-native), side-by-side benchmark.
    """

    def __init__(self, anthropic_api_key: str, snowflake_config: Optional[Dict] = None):
        self.api_key = anthropic_api_key
        self.sf_config = snowflake_config

    async def generate_sql(
        self,
        question: str,
        database: str,
        schema: str,
        table_metadata: Optional[List[Dict]] = None,
        semantic_model: Optional[str] = None,
        mode: str = "openai",  # "openai" | "cortex" | "benchmark"
    ) -> Dict[str, Any]:
        """Generate SQL from natural language question."""

        results = {}

        if mode in ("openai", "benchmark"):
            results["openai"] = await self._openai_sql(question, database, schema, table_metadata)

        if mode in ("cortex", "benchmark") and self.sf_config:
            results["cortex"] = await self._cortex_sql(question, semantic_model)

        if mode == "benchmark":
            results["recommendation"] = self._compare_results(
                results.get("openai", {}), results.get("cortex", {}))

        return results if mode == "benchmark" else results.get(mode, {})

    async def _openai_sql(self, question: str, database: str, schema: str,
                           table_metadata: Optional[List[Dict]]) -> Dict:
        import httpx

        schema_context = ""
        if table_metadata:
            schema_context = "\n".join([
                f"Table: {t['name']}\nColumns: {', '.join(c['name'] + ' ' + c.get('type','') for c in t.get('columns',[]))}"
                for t in table_metadata
            ])

        system = f"""You are a Snowflake SQL expert generating precise, production-ready SQL.
Target: database={database}, schema={schema}

{f'Available tables and schema:{chr(10)}{schema_context}' if schema_context else ''}

Rules:
- Use double quotes for identifiers: "DATABASE"."SCHEMA"."TABLE"
- Generate only the SQL query, no explanation
- Use Snowflake-specific functions where appropriate
- Include LIMIT 1000 on SELECT * queries
- Never use deprecated Snowflake syntax"""

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "openai-sonnet-4-20250514", "max_tokens": 1024,
                      "system": system,
                      "messages": [{"role": "user", "content": question}]}
            )
            resp.raise_for_status()
            sql = resp.json()["content"][0]["text"].strip()

        # Strip markdown code blocks if present
        if sql.startswith("```"):
            sql = "\n".join(sql.split("\n")[1:-1])

        return {"sql": sql, "model": "openai-sonnet-4-20250514", "mode": "openai"}

    async def _cortex_sql(self, question: str, semantic_model: Optional[str]) -> Dict:
        """Call Snowflake Cortex Analyst REST API."""
        if not self.sf_config:
            return {"error": "Snowflake config required for Cortex mode"}

        import httpx

        account   = self.sf_config.get("account", "")
        token     = await self._get_snowflake_token()
        stage_ref = semantic_model or self.sf_config.get("semantic_model_stage", "")

        if not stage_ref:
            return {"error": "semantic_model stage path required for Cortex Analyst"}

        cortex_url = f"https://{account}.snowflakecomputing.com/api/v2/cortex/analyst/message"

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                cortex_url,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={
                    "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
                    "semantic_model_file": stage_ref,
                }
            )
            if not resp.ok:
                return {"error": f"Cortex Analyst error: {resp.status_code} {resp.text}"}

            data = resp.json()
            sql = ""
            explanation = ""
            for item in data.get("message", {}).get("content", []):
                if item.get("type") == "sql":
                    sql = item.get("statement", "")
                elif item.get("type") == "text":
                    explanation = item.get("text", "")

        return {"sql": sql, "explanation": explanation,
                "model": "cortex_analyst", "mode": "cortex"}

    async def _get_snowflake_token(self) -> str:
        """Get Snowflake OAuth token for Cortex API calls."""
        import snowflake.connector
        conn = snowflake.connector.connect(**{
            k: v for k, v in self.sf_config.items()
            if k in ("account","user","password","warehouse","role")
        })
        token = conn.rest.token
        conn.close()
        return token

    def _compare_results(self, openai_result: Dict, cortex_result: Dict) -> Dict:
        """Compare OpenAI vs Cortex Analyst results."""
        has_openai = bool(openai_result.get("sql"))
        has_cortex = bool(cortex_result.get("sql"))
        return {
            "openai_generated": has_openai,
            "cortex_generated": has_cortex,
            "recommendation": "cortex" if has_cortex and not has_openai
                              else "openai" if has_openai and not has_cortex
                              else "both_available",
            "note": "Review both queries and validate against your data before using in production."
        }

    async def execute_and_explain(
        self,
        sql: str,
        snowflake_connector,
        question: str,
    ) -> Dict:
        """Execute SQL against Snowflake and generate a natural language explanation."""
        import httpx

        try:
            rows = snowflake_connector.run_query(sql + " LIMIT 100")
            row_count = len(rows)
            sample = rows[:5]
        except Exception as e:
            return {"error": str(e), "sql": sql}

        # Generate explanation
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "openai-sonnet-4-20250514", "max_tokens": 512,
                      "messages": [{"role": "user", "content":
                          f"Question: {question}\n\nSQL: {sql}\n\n"
                          f"Results ({row_count} rows): {json.dumps(sample[:3])}\n\n"
                          "Explain these results in 2-3 clear business sentences."}]}
            )
            explanation = resp.json()["content"][0]["text"]

        return {
            "sql": sql,
            "row_count": row_count,
            "sample_rows": sample,
            "explanation": explanation,
        }


# ══════════════════════════════════════════════════════════════
# RAG / Metadata Search
# ══════════════════════════════════════════════════════════════

class MetadataRAGService:
    """
    Semantic search over migration metadata, job logs, schema definitions,
    validation results, and documentation.
    Uses embedding-based similarity (simple cosine for now, Cortex Search when available).
    """

    def __init__(self, anthropic_api_key: str, db_session_factory=None):
        self.api_key = anthropic_api_key
        self._db_factory = db_session_factory
        self._doc_store: List[Dict] = []  # In-memory for simple deployments

    def index_document(self, doc_type: str, title: str, content: str, metadata: Dict = None):
        """Add a document to the search index."""
        self._doc_store.append({
            "id": hashlib.md5(f"{doc_type}:{title}".encode()).hexdigest()[:12],
            "type": doc_type,
            "title": title,
            "content": content,
            "metadata": metadata or {},
            "indexed_at": datetime.utcnow().isoformat(),
        })

    def index_job_context(self, job: Dict, tasks: List[Dict], logs: List[Dict]):
        """Index a completed job's context for future search."""
        content = f"""
Job: {job.get('name')}
Status: {job.get('status')}
Source: {job.get('source_connection_id')}
Destination: {job.get('sf_database')}.{job.get('sf_schema')}
Tables: {', '.join(t.get('source_table','') for t in tasks)}
Errors: {'; '.join(l.get('message','') for l in logs if l.get('level')=='ERROR')}
Duration: Export {job.get('export_duration_s')}s / Load {job.get('load_duration_s')}s
""".strip()
        self.index_document("job", job.get("name", ""), content,
                            {"job_id": job.get("id"), "status": job.get("status")})

    async def search(self, query: str, top_k: int = 5,
                     doc_types: Optional[List[str]] = None) -> List[Dict]:
        """
        Semantic search using OpenAI embeddings (or keyword fallback).
        In production: use Snowflake Cortex Search or pgvector.
        """
        if not self._doc_store:
            return []

        # Filter by doc type
        candidates = [d for d in self._doc_store
                      if not doc_types or d["type"] in doc_types]

        # Simple keyword relevance scoring (production: use embeddings)
        query_terms = set(query.lower().split())
        scored = []
        for doc in candidates:
            text = f"{doc['title']} {doc['content']}".lower()
            score = sum(1 for term in query_terms if term in text) / max(len(query_terms), 1)
            scored.append({**doc, "_score": score})

        scored.sort(key=lambda x: x["_score"], reverse=True)
        return scored[:top_k]

    async def rag_answer(self, query: str, context_docs: Optional[List[Dict]] = None) -> Dict:
        """Answer a question using retrieved context documents."""
        import httpx

        if context_docs is None:
            context_docs = await self.search(query)

        context = "\n\n".join([
            f"[{d['type'].upper()}] {d['title']}:\n{d['content'][:500]}"
            for d in context_docs
        ])

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "openai-sonnet-4-20250514", "max_tokens": 1024,
                      "system": "You are UMA AI. Answer questions about data migrations using the provided context. Be specific and technical.",
                      "messages": [{"role": "user", "content":
                          f"Context from migration platform:\n{context}\n\n"
                          f"Question: {query}"}]}
            )
            answer = resp.json()["content"][0]["text"]

        return {
            "answer": answer,
            "sources": [{"title": d["title"], "type": d["type"]} for d in context_docs],
        }


# ══════════════════════════════════════════════════════════════
# Agentic Orchestrator
# ══════════════════════════════════════════════════════════════

class AgentOrchestrator:
    """
    Multi-step agentic execution using tool use.
    Tools: sql_generate, search, validate, explain_failure, schema_map, run_query
    """

    TOOLS = [
        {
            "name": "sql_generate",
            "description": "Generate Snowflake SQL from a natural language description",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "database": {"type": "string"},
                    "schema": {"type": "string"},
                },
                "required": ["question"],
            }
        },
        {
            "name": "search_metadata",
            "description": "Search migration metadata, job logs, and documentation",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "doc_type": {"type": "string",
                                 "enum": ["job", "schema", "validation", "error", "all"]},
                },
                "required": ["query"],
            }
        },
        {
            "name": "explain_failure",
            "description": "Explain why a migration job or task failed and suggest fixes",
            "input_schema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "error_message": {"type": "string"},
                },
            }
        },
        {
            "name": "schema_mapping",
            "description": "Generate Snowflake DDL from source schema definition",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string"},
                    "source_schema": {"type": "array"},
                    "target_table": {"type": "string"},
                },
                "required": ["source_schema", "target_table"],
            }
        },
        {
            "name": "validate_rows",
            "description": "Run a row count parity check between source and target",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_count": {"type": "integer"},
                    "target_table": {"type": "string"},
                },
            }
        },
    ]

    def __init__(self, anthropic_api_key: str,
                 sql_service: Optional[TextToSQLService] = None,
                 rag_service: Optional[MetadataRAGService] = None):
        self.api_key = anthropic_api_key
        self.sql_svc = sql_service
        self.rag_svc = rag_service

    async def run(self, user_message: str, context: Dict = None,
                  max_turns: int = 5) -> Dict:
        """Execute agentic loop: reason → tool call → observe → respond."""
        import httpx

        messages = [{"role": "user", "content": user_message}]
        system = """You are UMA AI Agent — an autonomous data engineering assistant.
Break down complex requests, use tools to gather information, and synthesize complete answers.
Always verify facts before responding. For SQL, generate and explain. For failures, diagnose and fix."""

        if context:
            system += f"\n\nPlatform context:\n{json.dumps(context, indent=2)}"

        tool_results = []
        final_response = ""

        for turn in range(max_turns):
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={
                        "model": "openai-sonnet-4-20250514",
                        "max_tokens": 2048,
                        "system": system,
                        "tools": self.TOOLS,
                        "messages": messages,
                    }
                )
                resp.raise_for_status()
                data = resp.json()

            # Check stop reason
            if data.get("stop_reason") == "end_turn":
                text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                final_response = "\n".join(text_blocks)
                break

            # Handle tool calls
            tool_calls = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
            if not tool_calls:
                text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                final_response = "\n".join(text_blocks)
                break

            # Execute tool calls
            tool_results_content = []
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_input = tc.get("input", {})
                result = await self._execute_tool(tool_name, tool_input)
                tool_results.append({"tool": tool_name, "input": tool_input, "result": result})
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": json.dumps(result),
                })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": data.get("content", [])})
            messages.append({"role": "user", "content": tool_results_content})

        return {
            "response": final_response,
            "tool_calls": tool_results,
            "turns": turn + 1,
        }

    async def _execute_tool(self, tool_name: str, tool_input: Dict) -> Any:
        if tool_name == "sql_generate" and self.sql_svc:
            result = await self.sql_svc.generate_sql(
                question=tool_input.get("question", ""),
                database=tool_input.get("database", "ANALYTICS_DB"),
                schema=tool_input.get("schema", "PUBLIC"),
            )
            return result

        elif tool_name == "search_metadata" and self.rag_svc:
            doc_type = tool_input.get("doc_type")
            results = await self.rag_svc.search(
                tool_input.get("query", ""),
                doc_types=None if doc_type == "all" else ([doc_type] if doc_type else None)
            )
            return [{"title": r["title"], "type": r["type"], "content": r["content"][:300]}
                    for r in results]

        elif tool_name == "explain_failure":
            error = tool_input.get("error_message", "")
            common_fixes = {
                "sas token": "Regenerate Azure SAS token — it has expired. Go to Connections > Edit > update SAS token.",
                "access denied": "Check IAM role permissions. Snowflake role needs CREATE TABLE, INSERT, COPY INTO privileges.",
                "authentication failed": "Verify credentials in the connection configuration.",
                "connection refused": "Check firewall rules and network access. Ensure the source database allows connections from UMA's IP.",
                "timeout": "Increase job timeout in settings or reduce batch size.",
                "file format": "Verify the file format setting matches the actual data format.",
            }
            suggestion = next((v for k, v in common_fixes.items() if k in error.lower()), "Check job logs for more detail.")
            return {"error": error, "suggested_fix": suggestion,
                    "job_id": tool_input.get("job_id", "")}

        elif tool_name == "schema_mapping":
            from connectors.snowflake_connector import SnowflakeConnector
            schema = tool_input.get("source_schema", [])
            table = tool_input.get("target_table", "target_table")
            cols = ", ".join(
                f'"{c["name"]}" {SnowflakeConnector.map_source_type_to_snowflake(c.get("type","STRING"))}'
                for c in schema
            )
            return {"ddl": f'CREATE TABLE IF NOT EXISTS "{table}" ({cols})'}

        elif tool_name == "validate_rows":
            return {
                "source_count": tool_input.get("source_count", 0),
                "target_table": tool_input.get("target_table", ""),
                "status": "Run validation rule to compare counts",
            }

        return {"error": f"Tool {tool_name} not available"}


# ══════════════════════════════════════════════════════════════
# AI Functions (AISQL-style)
# ══════════════════════════════════════════════════════════════

class AIFunctions:
    """
    Cortex-style AI functions for unstructured data processing.
    summarize · classify · extract · document · suggest · explain
    """

    def __init__(self, anthropic_api_key: str):
        self.api_key = anthropic_api_key

    async def _call(self, system: str, prompt: str, max_tokens: int = 512) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "openai-sonnet-4-20250514", "max_tokens": max_tokens,
                      "system": system,
                      "messages": [{"role": "user", "content": prompt}]}
            )
            return resp.json()["content"][0]["text"]

    async def summarize_job(self, job: Dict, tasks: List[Dict], logs: List[Dict]) -> str:
        errors = [l for l in logs if l.get("level") == "ERROR"]
        prompt = f"""Migration job summary:
Name: {job.get('name')}
Status: {job.get('status')}
Data: {job.get('total_bytes_gb', 0)} GB, {job.get('total_rows_exported', 0):,} rows
Duration: {job.get('load_duration_s', 0):.0f}s load
Tasks: {job.get('tasks_succeeded', 0)}/{job.get('task_count', 0)} succeeded
Errors: {'; '.join(e.get('message','') for e in errors[:3])}"""
        return await self._call(
            "Summarize this migration job result in 2-3 business-friendly sentences. Note any issues.",
            prompt)

    async def generate_documentation(self, table_name: str, schema: List[Dict],
                                      sample_rows: Optional[List[Dict]] = None) -> str:
        cols = "\n".join(f"  - {c['name']} ({c.get('type','')}): {c.get('description','')}"
                         for c in schema)
        prompt = f"Table: {table_name}\nColumns:\n{cols}"
        if sample_rows:
            prompt += f"\nSample data: {json.dumps(sample_rows[:2])}"
        return await self._call(
            "Generate a concise markdown data dictionary for this Snowflake table. Include column descriptions, data types, and usage notes.",
            prompt, max_tokens=1024)

    async def suggest_validation_rules(self, table_name: str,
                                        schema: List[Dict]) -> List[Dict]:
        cols_json = json.dumps([{"name": c["name"], "type": c.get("type","")} for c in schema])
        result = await self._call(
            "Generate validation rules as JSON array. Each rule: {name, type, query, description}. Types: row_count, null_check, duplicate, freshness.",
            f"Table: {table_name}\nSchema: {cols_json}\n\nGenerate 3-5 validation rules as a JSON array only.",
            max_tokens=1024)
        try:
            clean = result.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(clean)
        except Exception:
            return []

    async def explain_sql(self, sql: str) -> str:
        return await self._call(
            "Explain this Snowflake SQL in plain English. Be concise and technical.",
            f"SQL:\n{sql}")

    async def suggest_dbt_model(self, source_table: str, schema: List[Dict]) -> str:
        cols = ", ".join(f'"{c["name"]}"' for c in schema)
        return await self._call(
            "Generate a dbt model skeleton (SQL file) for this Snowflake source table. Include ref(), config(), and basic column selection.",
            f"Source table: {source_table}\nColumns: {cols}")

    async def classify_failure(self, error_message: str) -> Dict:
        result = await self._call(
            "Classify this migration error. Respond with JSON: {category, severity, is_retryable, fix}",
            f"Error: {error_message}")
        try:
            clean = result.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(clean)
        except Exception:
            return {"category": "unknown", "severity": "medium",
                    "is_retryable": True, "fix": result}

    async def map_source_to_snowflake(self, source_type: str,
                                       source_schema: List[Dict]) -> List[Dict]:
        """Suggest Snowflake column mappings with AI assistance."""
        schema_json = json.dumps([{"name": c["name"], "source_type": c.get("type","")}
                                   for c in source_schema])
        result = await self._call(
            "Map source columns to Snowflake types. Respond with JSON array: [{name, source_type, snowflake_type, notes}]",
            f"Source: {source_type}\nSchema: {schema_json}",
            max_tokens=2048)
        try:
            clean = result.strip().lstrip("```json").rstrip("```").strip()
            return json.loads(clean)
        except Exception:
            return []
