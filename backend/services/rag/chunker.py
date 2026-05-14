from __future__ import annotations

from core.config import settings
from services.rag.redaction import redact_rag_payload


def chunk_text(text: str, *, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    safe = str(redact_rag_payload(text or "") or "")
    size = max(200, int(chunk_size or settings.RAG_CHUNK_SIZE or 1200))
    step_back = max(0, min(int(overlap or settings.RAG_CHUNK_OVERLAP or 180), size // 2))
    if not safe.strip():
        return []
    paragraphs = safe.replace("\r\n", "\n").split("\n\n")
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}".strip()
            continue
        if current:
            chunks.append(current)
        if len(para) <= size:
            current = para
            continue
        for start in range(0, len(para), size - step_back):
            part = para[start : start + size].strip()
            if part:
                chunks.append(part)
        current = ""
    if current:
        chunks.append(current)
    return chunks
