# Local Ollama and RAG

UMA can run AI Copilot and AI patch proposal flows against a private Ollama server. Deterministic conversion remains the source of truth: local LLM output can propose a patch, but it cannot mark a job Snowflake-ready and cannot auto-apply changes.

## Local setup

Start UMA as usual. Ollama is optional and normal app startup does not require it.

```bash
docker compose --profile ollama up -d ollama
docker exec -it uma-ollama ollama pull llama3.1
docker exec -it uma-ollama ollama pull nomic-embed-text
```

Set the backend environment:

```bash
COPILOT_PROVIDER=ollama
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_CHAT_MODEL=llama3.1
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
RAG_ENABLED=true
RAG_VECTOR_STORE=faiss
RAG_INDEX_PATH=data/rag_index
```

For host-local development without Docker, use `OLLAMA_BASE_URL=http://localhost:11434`.

## Health and RAG APIs

- `GET /api/ai/providers/ollama/health`
- `POST /api/rag/index/run/{run_id}`
- `POST /api/rag/index/artifact/{artifact_id}`
- `GET /api/rag/search?query=...&run_id=...&top_k=6`

RAG indexing redacts secret-like fields before embeddings are created. When `provider=ollama`, UMA calls only the configured local Ollama base URL.

## Guardrails

- AI patch proposals return `manual_review_required=true`.
- Patch application still requires the apply endpoint with `confirmed=true`.
- The judge reruns after patch application and controls readiness state.
- If Ollama is unreachable or a configured model is missing, UMA reports Offline Deterministic mode and disables AI patch proposal in the UI.
