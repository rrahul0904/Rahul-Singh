from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
import hashlib
import json
import re
import unicodedata
import zlib
import zipfile

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ArtifactChunk, ArtifactExtraction, UploadedArtifact, User


ARTIFACT_ROOT = Path(__file__).resolve().parent.parent / "uploads" / "migration_intelligence"
SUPPORTED_EXTENSIONS = {".sql", ".txt", ".md", ".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_CHARS = 500
SECRET_PATTERNS = [
    re.compile(r"(?i)(password|token|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)"),
]
SQL_KEYWORDS = {"select", "insert", "update", "delete", "merge", "create", "alter", "drop", "replace", "call"}
DDL_WORDS = ("create table", "alter table", "create view", "replace view", "drop table", "create schema")
DML_WORDS = ("insert into", "update ", "delete from", "merge into", "copy into")
BTEQ_PATTERNS = (".logon", ".if errorcode", ".quit", ".export", ".run file")
PROC_PATTERNS = ("create or replace procedure", "create procedure", "create function", "create package")
NARRATIVE_STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "into", "is", "of", "on", "or", "the", "to",
    "with", "without", "need", "needs", "must", "should", "mapping", "source", "target", "table", "tables",
    "snowflake", "acceptance", "criteria", "requirement", "requirements", "column", "columns",
}
OBJECT_LIKE_TOKEN = re.compile(r'(?i)\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b|\b[A-Za-z_]*_[A-Za-z0-9_]+\b')


def is_object_like_identifier(raw: str) -> bool:
    value = normalize_identifier(raw).lower()
    if not value or value in NARRATIVE_STOPWORDS:
        return False
    if value.startswith('"') or value.endswith('"'):
        value = value.strip('"')
    if value.count(".") >= 1:
        return all(part and part not in NARRATIVE_STOPWORDS for part in value.split("."))
    return "_" in value and not value.startswith("_") and not value.endswith("_")


def extract_object_like_tokens(text: str) -> list[str]:
    seen: list[str] = []
    for match in OBJECT_LIKE_TOKEN.finditer(text):
        candidate = normalize_identifier(match.group(0))
        if is_object_like_identifier(candidate) and candidate not in seen:
            seen.append(candidate)
    return seen


def _extract_narrative_references(text: str) -> dict:
    dependencies = set()
    procedures = set()
    ignored_candidates = set()
    evidence_notes = []

    for match in re.finditer(r'(?i)\b(?:procedure|function|package)\s+([A-Za-z_][A-Za-z0-9_.]*)', text):
        candidate = normalize_identifier(match.group(1))
        if is_object_like_identifier(candidate):
            procedures.add(candidate)
            dependencies.add(candidate)
            evidence_notes.append(f"keyword:{candidate}")
        else:
            ignored_candidates.add(candidate)

    narrative_patterns = (
        re.compile(r'(?i)\bdepends\s+on\s+(.+?)(?:;|\n|$)'),
        re.compile(r'(?i)\bconvert\s+(.+?)\s+to\s+snowflake\b'),
    )
    for pattern in narrative_patterns:
        for match in pattern.finditer(text):
            raw_segment = match.group(1)
            candidates = extract_object_like_tokens(raw_segment)
            if candidates:
                dependencies.update(candidates)
                evidence_notes.extend(f"phrase:{candidate}" for candidate in candidates)
            else:
                for token in re.findall(r'(?i)\b[A-Za-z_][A-Za-z0-9_.]*\b', raw_segment):
                    token_normalized = normalize_identifier(token)
                    if token_normalized and token_normalized.lower() in NARRATIVE_STOPWORDS:
                        ignored_candidates.add(token_normalized)

    if not dependencies:
        for token in re.findall(r'(?i)\b[A-Za-z_][A-Za-z0-9_.]*\b', text):
            token_normalized = normalize_identifier(token)
            if token_normalized and token_normalized.lower() in NARRATIVE_STOPWORDS:
                ignored_candidates.add(token_normalized)

    return {
        "tables": [],
        "views": [],
        "procedures": sorted(procedures),
        "packages": [],
        "dependencies": sorted(dependencies),
        "bteq_commands": [],
        "ignored_dependency_candidates": sorted(ignored_candidates),
        "dependency_evidence_strength": "strong" if dependencies else "weak",
        "dependency_evidence_notes": evidence_notes or ["No strong dependency evidence was detected from the uploaded requirement text."],
    }


@dataclass
class ParsedArtifact:
    extraction_status: str
    extracted_text: str
    preview: str
    classification: str
    language_guess: str
    source_system_guess: str
    chunks: list[dict]
    metadata: dict
    error_message: str | None = None


def redact_sensitive_text(text: str) -> str:
    safe = text
    for pattern in SECRET_PATTERNS:
        safe = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", safe)
    return safe


def sanitize_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    cleaned = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in normalized)
    return cleaned[:180] or "artifact"


def validate_upload_payload(name: str, content: bytes) -> tuple[str, int]:
    ext = Path(name or "artifact").suffix.lower()
    size_bytes = len(content)
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(415, f"Unsupported file type `{ext or 'unknown'}`. Supported types: {allowed}.")
    if size_bytes == 0:
        raise HTTPException(400, "Uploaded artifact is empty. Upload a non-empty .sql, .txt, .md, or text-based .pdf file.")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Uploaded artifact exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB MVP limit.")
    return ext, size_bytes


def build_preview(text: str) -> str:
    return redact_sensitive_text(text.strip())[:MAX_PREVIEW_CHARS]


def normalize_identifier(raw: str) -> str:
    return raw.strip().strip('"').strip()


def guess_source_system(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in (".logon", "qualify ", "multiset", "volatile table")):
        return "Teradata"
    if any(token in lowered for token in ("package body", "varchar2", "number(", "exception when", "sysdate")):
        return "Oracle"
    if any(token in lowered for token in ("::", "serial", "language plpgsql", "returning ")):
        return "Postgres"
    if any(token in lowered for token in ("`", "unnest(", "create temp function", "bigquery")):
        return "BigQuery"
    if any(token in lowered for token in ("snowflake", "variant", "qualify row_number()", "copy into")):
        return "Snowflake"
    if any(word in lowered for word in SQL_KEYWORDS):
        return "Generic SQL"
    return "Unknown"


def classify_text(text: str, file_ext: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(token in lowered for token in BTEQ_PATTERNS):
        return "BTEQ", "sql"
    if any(token in lowered for token in PROC_PATTERNS):
        return "PL_SQL", "sql"
    if any(word in lowered for word in SQL_KEYWORDS):
        return "SQL", "sql"
    if any(token in lowered for token in ("requirement", "must ", "should ", "acceptance criteria", "user story")):
        return "REQUIREMENTS", "markdown" if file_ext == ".md" else "text"
    if any(token in lowered for token in ("source column", "target column", "mapping", "source table", "target table")):
        return "MAPPING_DOC", "markdown" if file_ext == ".md" else "text"
    if file_ext == ".md":
        return "REQUIREMENTS", "markdown"
    return "UNKNOWN", "text"


def extract_references(text: str, classification: str | None = None) -> dict:
    if classification in {"REQUIREMENTS", "MAPPING_DOC"}:
        refs = _extract_narrative_references(text)
        refs.update(
            {
                "has_primary_key": bool(re.search(r"(?i)\bprimary\s+key\b", text)),
                "has_watermark": bool(re.search(r"(?i)\b(updated_at|modified_at|last_updated|watermark|cdc_ts)\b", text)),
                "has_transaction_control": bool(re.search(r"(?i)\b(begin|commit|rollback|transaction)\b", text)),
            }
        )
        return refs

    tables = []
    views = []
    procedures = []
    packages = []
    bteq_commands = []
    dependencies = set()

    for regex in (
        re.compile(r"(?i)\b(?:from|join|into|update|table|view)\s+([A-Za-z0-9_.$\"]+)"),
        re.compile(r"(?i)\binsert\s+into\s+([A-Za-z0-9_.$\"]+)"),
    ):
        for match in regex.finditer(text):
            candidate = normalize_identifier(match.group(1))
            if candidate and candidate.lower() not in NARRATIVE_STOPWORDS:
                dependencies.add(candidate)

    for match in re.finditer(r'(?i)\bcreate\s+(?:or\s+replace\s+)?table\s+([A-Za-z0-9_.$\"]+)', text):
        tables.append(normalize_identifier(match.group(1)))
    for match in re.finditer(r'(?i)\bcreate\s+(?:or\s+replace\s+)?view\s+([A-Za-z0-9_.$\"]+)', text):
        views.append(normalize_identifier(match.group(1)))
    for match in re.finditer(r'(?i)\bcreate\s+(?:or\s+replace\s+)?(?:procedure|function)\s+([A-Za-z0-9_.$\"]+)', text):
        procedures.append(normalize_identifier(match.group(1)))
    for match in re.finditer(r'(?i)\bcreate\s+(?:or\s+replace\s+)?package(?:\s+body)?\s+([A-Za-z0-9_.$\"]+)', text):
        packages.append(normalize_identifier(match.group(1)))
    for token in BTEQ_PATTERNS:
        if token in text.lower():
            bteq_commands.append(token.upper())

    return {
        "tables": sorted(set(tables)),
        "views": sorted(set(views)),
        "procedures": sorted(set(procedures)),
        "packages": sorted(set(packages)),
        "dependencies": sorted(dep for dep in dependencies if dep),
        "bteq_commands": sorted(set(bteq_commands)),
        "ignored_dependency_candidates": [],
        "dependency_evidence_strength": "strong" if dependencies else "none",
        "dependency_evidence_notes": [],
        "has_primary_key": bool(re.search(r"(?i)\bprimary\s+key\b", text)),
        "has_watermark": bool(re.search(r"(?i)\b(updated_at|modified_at|last_updated|watermark|cdc_ts)\b", text)),
        "has_transaction_control": bool(re.search(r"(?i)\b(begin|commit|rollback|transaction)\b", text)),
    }


def detect_statement_type(text: str) -> str:
    lowered = text.lower().strip()
    if any(lowered.startswith(token) for token in (".logon", ".if", ".quit", ".export", ".run")):
        return "BTEQ_CONTROL"
    if any(token in lowered for token in DDL_WORDS):
        return "DDL"
    if any(token in lowered for token in DML_WORDS):
        return "DML"
    if any(token in lowered for token in PROC_PATTERNS):
        return "PROCEDURE"
    if lowered.startswith("#") or lowered.startswith("##"):
        return "SECTION"
    return "TEXT"


def split_chunks(text: str, classification: str) -> list[dict]:
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[dict] = []
    if classification in {"SQL", "BTEQ", "PL_SQL"}:
        pieces = [piece.strip() for piece in re.split(r";\s*|\n/\s*\n", stripped, flags=re.MULTILINE) if piece.strip()]
    else:
        pieces = [piece.strip() for piece in re.split(r"\n\s*\n", stripped) if piece.strip()]

    for idx, piece in enumerate(pieces):
        stmt_type = detect_statement_type(piece)
        refs = extract_references(piece, classification)
        object_name = next((name for bucket in ("tables", "views", "procedures", "packages") for name in refs[bucket]), None)
        chunks.append(
            {
                "chunk_index": idx,
                "chunk_type": stmt_type,
                "heading": piece.splitlines()[0][:255] if piece.splitlines() else None,
                "text": redact_sensitive_text(piece),
                "statement_type": stmt_type,
                "object_name": object_name,
                "metadata_json": refs,
            }
        )
    return chunks


def _extract_pdf_literal_strings(stream_text: str) -> str:
    strings = []
    for match in re.finditer(r"\((.*?)(?<!\\)\)\s*Tj", stream_text, flags=re.DOTALL):
        strings.append(match.group(1))
    for match in re.finditer(r"\[(.*?)\]\s*TJ", stream_text, flags=re.DOTALL):
        strings.extend(re.findall(r"\((.*?)(?<!\\)\)", match.group(1), flags=re.DOTALL))
    return " ".join(s.replace("\\(", "(").replace("\\)", ")").replace("\\n", "\n") for s in strings)


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    content = pdf_bytes.decode("latin-1", errors="ignore")
    page_count = max(content.count("/Type /Page"), 1 if "/Type /Page" in content else 0)
    texts: list[str] = []
    for match in re.finditer(r"stream\r?\n(.*?)\r?\nendstream", content, flags=re.DOTALL):
        raw_stream = match.group(1)
        candidates = [raw_stream]
        raw_bytes = raw_stream.encode("latin-1", errors="ignore")
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                candidates.append(zlib.decompress(raw_bytes, wbits).decode("latin-1", errors="ignore"))
                break
            except Exception:
                continue
        for candidate in candidates:
            extracted = _extract_pdf_literal_strings(candidate)
            if extracted.strip():
                texts.append(extracted.strip())
    return "\n".join(texts).strip(), page_count


def parse_artifact_bytes(file_name: str, file_ext: str, content: bytes) -> ParsedArtifact:
    if file_ext not in SUPPORTED_EXTENSIONS:
        return ParsedArtifact(
            extraction_status="UNSUPPORTED_TYPE",
            extracted_text="",
            preview="",
            classification="UNKNOWN",
            language_guess="unknown",
            source_system_guess="Unknown",
            chunks=[],
            metadata={},
            error_message=f"Unsupported file type: {file_ext}",
        )

    try:
        if file_ext == ".pdf":
            extracted_text, page_count = extract_pdf_text(content)
            if not extracted_text.strip():
                return ParsedArtifact(
                    extraction_status="NEEDS_OCR_NOT_SUPPORTED",
                    extracted_text="",
                    preview="",
                    classification="UNKNOWN",
                    language_guess="pdf",
                    source_system_guess="Unknown",
                    chunks=[],
                    metadata={"page_count": page_count, "ocr_supported": False},
                    error_message="Embedded text extraction returned no usable text; OCR is not supported in MVP.",
                )
            metadata = {"page_count": page_count, "ocr_supported": False}
        else:
            extracted_text = content.decode("utf-8", errors="ignore")
            metadata = {"page_count": None, "ocr_supported": False}
    except Exception as exc:
        status = "FAILED_EXTRACTION" if file_ext != ".pdf" else "NEEDS_OCR_NOT_SUPPORTED"
        return ParsedArtifact(
            extraction_status=status,
            extracted_text="",
            preview="",
            classification="UNKNOWN",
            language_guess="unknown",
            source_system_guess="Unknown",
            chunks=[],
            metadata={},
            error_message=str(exc),
        )

    safe_text = redact_sensitive_text(extracted_text)
    classification, language_guess = classify_text(safe_text, file_ext)
    source_system_guess = guess_source_system(safe_text)
    chunks = split_chunks(safe_text, classification)
    refs = extract_references(safe_text, classification)
    metadata.update(
        {
            "statement_count": len(chunks),
            "classification": classification,
            "language_guess": language_guess,
            "source_system_guess": source_system_guess,
            **refs,
        }
    )
    status = "CLASSIFIED" if chunks else "EXTRACTED"
    return ParsedArtifact(
        extraction_status=status,
        extracted_text=safe_text,
        preview=build_preview(safe_text),
        classification=classification,
        language_guess=language_guess,
        source_system_guess=source_system_guess,
        chunks=chunks,
        metadata=metadata,
        error_message=None,
    )


def render_report_markdown(report_json: dict) -> str:
    lines = [f"# {report_json['title']}", ""]
    for section in report_json.get("sections", []):
        lines.append(f"## {section['title']}")
        content = section.get("content")
        if isinstance(content, list):
            for item in content:
                lines.append(f"- {item}")
        else:
            lines.append(content or "")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_pdf_bytes(title: str, report_markdown: str, metadata: dict) -> bytes:
    lines = [title, ""]
    lines.extend(f"{key}: {value}" for key, value in metadata.items())
    lines.extend(["", *report_markdown.splitlines()])
    content = "\n".join(line[:100] for line in lines)
    safe = content.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 10 Tf 36 792 Td 12 TL " + " T* ".join(f"({line}) Tj" for line in safe.splitlines()) + " ET"
    objects = []
    objects.append("1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append("2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append("3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n")
    objects.append("4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append(f"5 0 obj << /Length {len(stream.encode('latin-1'))} >> stream\n{stream}\nendstream endobj\n")
    pdf = "%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(pdf.encode("latin-1")))
        pdf += obj
    xref_offset = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return pdf.encode("latin-1")


def render_docx_bytes(title: str, report_markdown: str, metadata: dict) -> bytes:
    def paragraph(text: str) -> str:
        return f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"

    body = [paragraph(title)]
    for key, value in metadata.items():
        body.append(paragraph(f"{key}: {value}"))
    for line in report_markdown.splitlines():
        body.append(paragraph(line))
    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        f"<w:body>{''.join(body)}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )
    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
        "</Relationships>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


class MigrationIntelligenceArtifactService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _persist_parsed_artifact(
        self,
        artifact: UploadedArtifact,
        parsed: ParsedArtifact,
    ) -> UploadedArtifact:
        artifact.extraction_status = parsed.extraction_status
        artifact.extracted_text_preview = parsed.preview
        artifact.classification = parsed.classification
        artifact.language_guess = parsed.language_guess
        artifact.source_system_guess = parsed.source_system_guess
        artifact.error_message = parsed.error_message

        existing = (
            await self.db.execute(select(ArtifactExtraction).where(ArtifactExtraction.artifact_id == artifact.id))
        ).scalar_one_or_none()
        if existing:
            extraction = existing
        else:
            extraction = ArtifactExtraction(artifact_id=artifact.id)
            self.db.add(extraction)
        extraction.extraction_status = parsed.extraction_status
        extraction.extracted_text = parsed.extracted_text
        extraction.extracted_text_preview = parsed.preview
        extraction.page_count = parsed.metadata.get("page_count")
        extraction.metadata_json = parsed.metadata
        extraction.error_message = parsed.error_message
        await self.db.flush()

        await self.db.execute(delete(ArtifactChunk).where(ArtifactChunk.artifact_id == artifact.id))
        for chunk in parsed.chunks:
            self.db.add(
                ArtifactChunk(
                    artifact_id=artifact.id,
                    extraction_id=extraction.id,
                    chunk_index=chunk["chunk_index"],
                    chunk_type=chunk["chunk_type"],
                    heading=chunk["heading"],
                    text=chunk["text"],
                    statement_type=chunk["statement_type"],
                    object_name=chunk["object_name"],
                    metadata_json=chunk["metadata_json"],
                )
            )
        await self.db.flush()
        return artifact

    async def upload_artifact(self, upload: UploadFile, user: User) -> UploadedArtifact:
        name = upload.filename or "artifact"
        content = await upload.read()
        ext, size_bytes = validate_upload_payload(name, content)
        sha256_hash = hashlib.sha256(content).hexdigest()
        artifact = UploadedArtifact(
            file_name=name,
            file_type=ext.lstrip(".") or "unknown",
            mime_type=upload.content_type or "application/octet-stream",
            size_bytes=size_bytes,
            sha256_hash=sha256_hash,
            storage_path="",
            uploaded_by=user.id,
            extraction_status="UPLOADED",
        )
        self.db.add(artifact)
        await self.db.flush()

        target_dir = ARTIFACT_ROOT / artifact.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / sanitize_filename(name)
        target_path.write_bytes(content)
        artifact.storage_path = str(target_path)

        parsed = parse_artifact_bytes(name, ext, content)
        await self._persist_parsed_artifact(artifact, parsed)
        await self.db.commit()
        await self.db.refresh(artifact)
        return artifact

    async def list_artifacts(self) -> list[UploadedArtifact]:
        rows = (await self.db.execute(select(UploadedArtifact).order_by(UploadedArtifact.created_at.desc()))).scalars().all()
        return list(rows)

    async def get_artifact(self, artifact_id: str) -> UploadedArtifact:
        artifact = await self.db.get(UploadedArtifact, artifact_id)
        if not artifact:
            raise HTTPException(404, "Artifact not found")
        return artifact

    async def get_extraction(self, artifact_id: str) -> ArtifactExtraction | None:
        return (
            await self.db.execute(select(ArtifactExtraction).where(ArtifactExtraction.artifact_id == artifact_id))
        ).scalar_one_or_none()

    async def get_chunks(self, artifact_id: str) -> list[ArtifactChunk]:
        rows = (
            await self.db.execute(
                select(ArtifactChunk).where(ArtifactChunk.artifact_id == artifact_id).order_by(ArtifactChunk.chunk_index.asc())
            )
        ).scalars().all()
        return list(rows)
