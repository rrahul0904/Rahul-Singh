from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    AdvisorCheckResult,
    AdvisorScan,
    AnalyzerComponent,
    AnalyzerDependency,
    Connection,
    ControlPlaneArtifact,
    ControlPlaneJob,
    ControlPlaneRun,
    HumanReviewItem,
    SqlConversionMessage,
    User,
)
from core.security import get_cipher
from connectors.snowflake_connector import SnowflakeConnector

try:
    import sqlglot
    from sqlglot import exp
except Exception:  # pragma: no cover - optional dependency fallback
    sqlglot = None
    exp = None


ARTIFACT_ROOT = Path(__file__).resolve().parent.parent / "uploads" / "control_plane"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SUPPORTED_EXTENSIONS = {
    ".sql", ".ddl", ".txt", ".md", ".json", ".yaml", ".yml", ".xml", ".twb", ".twbx", ".pdf", ".csv", ".zip"
}

ARTIFACT_CATEGORY_BY_EXT = {
    ".sql": "SOURCE_SQL",
    ".ddl": "SOURCE_DDL",
    ".txt": "REQUIREMENTS",
    ".md": "REQUIREMENTS",
    ".json": "REQUIREMENTS",
    ".yaml": "REQUIREMENTS",
    ".yml": "REQUIREMENTS",
    ".xml": "ETL_XML",
    ".twb": "TABLEAU",
    ".twbx": "TABLEAU",
    ".pdf": "PDF",
    ".csv": "REQUIREMENTS",
    ".zip": "ARCHIVE",
}

SAFETY_MODES = {"READ_ONLY", "PLAN_ONLY", "VALIDATION_ONLY", "WRITE_APPROVED", "DEPLOY_APPROVED"}
RUN_STATUSES = {
    "DRAFT", "PENDING", "RUNNING", "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "SKIPPED",
    "REQUIRES_CONFIGURATION", "REQUIRES_REVIEW", "APPROVAL_REQUIRED",
}
WRITE_MODES = {"WRITE_APPROVED", "DEPLOY_APPROVED"}
SELECT_ONLY = re.compile(r"^\s*(with\b.*)?select\b", re.IGNORECASE | re.DOTALL)
NON_SELECT_SQL = re.compile(r"\b(insert|update|delete|merge|create|alter|drop|truncate|copy|grant|revoke|call|execute)\b", re.I)

SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|token|api[_-]?key|secret|client_secret|private[_-]?key|oauth[_-]?secret)\b\s*[:=]\s*(['\"]?)[^'\"\s,;]+\2"),
    re.compile(r"(?i)\b(private_key_file)\b\s*[:=]\s*(['\"]?)[^'\"\s,;]+\2"),
    re.compile(r"(?i)(jdbc:[^\s]+://[^/\s:]+):([^@\s]+)@"),
    re.compile(r"(?i)(snowflake|postgres|mysql|oracle|sqlserver)://([^:\s/@]+):([^@\s]+)@"),
]

ENV_SECRET_NAMES = [name for name in os.environ if any(token in name.upper() for token in ("SECRET", "TOKEN", "PASSWORD", "KEY"))]


def utcnow() -> datetime:
    return datetime.utcnow()


def sanitize_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name or "artifact")
    cleaned = "".join(ch if ch.isalnum() or ch in {".", "_", "-"} else "_" for ch in normalized)
    return cleaned[:180] or "artifact"


def redact_secrets(value):
    if value is None:
        return None
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if any(token in str(key).upper() for token in ("SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", "API_KEY", "CONNECTION_STRING")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    text = str(value)
    for env_name in ENV_SECRET_NAMES:
        env_value = os.environ.get(env_name)
        if env_value:
            text = text.replace(env_value, "[REDACTED]")
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.pattern.startswith("(?i)(jdbc"):
            text = pattern.sub(r"\1:[REDACTED]@", text)
        elif "://" in pattern.pattern:
            text = pattern.sub(r"\1://\2:[REDACTED]@", text)
        else:
            text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    return text


def validate_upload(name: str, content: bytes) -> tuple[str, int]:
    ext = Path(name or "artifact").suffix.lower()
    size = len(content)
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(415, f"Unsupported file type `{ext or 'unknown'}`. Supported uploads: {allowed}.")
    if size == 0:
        raise HTTPException(400, "Uploaded artifact is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Uploaded artifact exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    return ext, size


def classify_text_file(ext: str, text: str) -> str:
    lowered = text.lower()
    if ext in {".sql", ".ddl"}:
        return "SOURCE_DDL" if "create " in lowered or ext == ".ddl" else "SOURCE_SQL"
    if ext in {".xml", ".twb", ".twbx"}:
        return "TABLEAU" if "workbook" in lowered or ext in {".twb", ".twbx"} else "ETL_XML"
    return ARTIFACT_CATEGORY_BY_EXT.get(ext, "REQUIREMENTS")


def classify_zip_artifact(path: Path) -> str:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = {name.lower() for name in zf.namelist()}
            if "dbt_project.yml" in names or "dbt_project.yaml" in names:
                return "DBT_PROJECT"
    except Exception:
        return "ARCHIVE"
    return "ARCHIVE"


def read_artifact_text(artifact: ControlPlaneArtifact, max_bytes: int = 2_000_000) -> str:
    path = Path(artifact.storage_path)
    if not path.exists():
        return ""
    ext = f".{artifact.file_type.lower().lstrip('.')}"
    if ext == ".twbx":
        with zipfile.ZipFile(path, "r") as zf:
            twb_names = [name for name in zf.namelist() if name.lower().endswith(".twb")]
            if not twb_names:
                return ""
            return zf.read(twb_names[0])[:max_bytes].decode("utf-8", errors="ignore")
    if ext == ".pdf":
        return path.read_bytes()[:max_bytes].decode("latin-1", errors="ignore")
    if ext == ".zip":
        previews = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in sorted(zf.namelist())[:40]:
                    previews.append(name)
        except Exception:
            return ""
        return "\n".join(previews)
    return path.read_bytes()[:max_bytes].decode("utf-8", errors="ignore")


def split_sql_statements(sql: str) -> list[tuple[int, str, int, int]]:
    statements = []
    start_line = 1
    current = []
    line_no = 0
    in_single = False
    in_double = False
    for line_no, line in enumerate(sql.splitlines(), start=1):
        stripped = line.strip()
        for ch in line:
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
        current.append(line)
        if stripped.endswith(";") and not in_single and not in_double:
            text = "\n".join(current).strip().rstrip(";").strip()
            if text:
                statements.append((len(statements), text, start_line, line_no))
            current = []
            start_line = line_no + 1
    tail = "\n".join(current).strip()
    if tail:
        statements.append((len(statements), tail, start_line, line_no or 1))
    return statements


def statement_type(sql: str) -> str:
    lowered = sql.strip().lower()
    for token, label in (
        ("create or replace procedure", "PROCEDURE"),
        ("create procedure", "PROCEDURE"),
        ("create function", "UDF"),
        ("create table", "DDL"),
        ("alter table", "DDL"),
        ("create view", "DDL"),
        ("merge", "MERGE"),
        ("update", "UPDATE"),
        ("delete", "DELETE"),
        ("insert", "INSERT"),
        ("select", "SELECT"),
        ("with", "SELECT"),
    ):
        if lowered.startswith(token):
            return label
    return "UNKNOWN"


DBT_CONFIG_RE = re.compile(r"\A\s*\{\{\s*config\s*\(.*?\)\s*\}\}\s*", re.I | re.S)
DBT_SOURCE_RE = re.compile(r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.I)
DBT_REF_RE = re.compile(r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.I)
JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)


def sql_for_semantic_parse(sql: str) -> str:
    cleaned = DBT_CONFIG_RE.sub("", sql or "")
    cleaned = DBT_SOURCE_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}", cleaned)
    cleaned = DBT_REF_RE.sub(lambda m: m.group(1), cleaned)
    cleaned = JINJA_RE.sub(" ", cleaned)
    return cleaned.strip()


DIALECT_MAP = {
    "bigquery": "bigquery",
    "bq": "bigquery",
    "oracle": "oracle",
    "mssql": "tsql",
    "sqlserver": "tsql",
    "teradata": "teradata",
    "hive": "hive",
    "sparksql": "spark",
    "spark": "spark",
    "databricks": "databricks",
    "postgres": "postgres",
    "postgresql": "postgres",
    "snowflake": "snowflake",
}


def sqlglot_dialect(value: str | None) -> str | None:
    return DIALECT_MAP.get((value or "").lower())


def parse_sql_semantic(stmt: str, source_dialect: str | None) -> tuple[object | None, str | None]:
    if not sqlglot:
        return None, "sqlglot is not installed; regex fallback was used."
    try:
        parsed = sqlglot.parse_one(stmt, read=sqlglot_dialect(source_dialect))
        return parsed, None
    except Exception as exc:
        return None, str(exc)


def semantic_statement_type(parsed, fallback: str) -> str:
    if not parsed or not exp:
        return fallback
    if isinstance(parsed, exp.Select):
        return "SELECT"
    if isinstance(parsed, exp.Create):
        kind = str(parsed.args.get("kind") or "").upper()
        return f"CREATE_{kind}" if kind else "DDL"
    if isinstance(parsed, exp.Insert):
        return "INSERT"
    if isinstance(parsed, exp.Update):
        return "UPDATE"
    if isinstance(parsed, exp.Delete):
        return "DELETE"
    if isinstance(parsed, exp.Merge):
        return "MERGE"
    return parsed.key.upper() if getattr(parsed, "key", None) else fallback


def semantic_sql_features(parsed) -> dict:
    if not parsed or not exp:
        return {"parser": "regex_fallback", "tables": [], "columns": [], "functions": []}
    tables = sorted({table.sql(dialect="snowflake") for table in parsed.find_all(exp.Table)})
    columns = sorted({column.sql(dialect="snowflake") for column in parsed.find_all(exp.Column)})[:200]
    functions = sorted({node.key.upper() for node in parsed.walk() if isinstance(node, exp.Func)})
    return {
        "parser": "sqlglot",
        "tables": tables,
        "columns": columns,
        "functions": functions,
        "expression_type": parsed.key.upper() if getattr(parsed, "key", None) else type(parsed).__name__,
    }


def safe_translate_sql(stmt: str, source_dialect: str | None, target_dialect: str | None = "snowflake") -> tuple[str | None, str | None]:
    if not sqlglot:
        return None, "sqlglot is not installed."
    try:
        parsed = sqlglot.parse_one(stmt, read=sqlglot_dialect(source_dialect))
        fallback_type = statement_type(stmt)
        if fallback_type in {"PROCEDURE", "UDF", "UNKNOWN"}:
            return None, f"{fallback_type} is not safe for deterministic translation."
        translated = parsed.sql(dialect=sqlglot_dialect(target_dialect) or "snowflake", pretty=True)
        return translated, None
    except Exception as exc:
        return None, str(exc)


def quote_identifier(identifier: str) -> str:
    cleaned = str(identifier or "").strip().strip('"')
    if not cleaned or not re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", cleaned):
        raise HTTPException(400, f"Invalid identifier `{identifier}`.")
    return f'"{cleaned}"'


def quote_fqn(table_name: str) -> str:
    parts = [part.strip() for part in str(table_name or "").split(".") if part.strip()]
    if not 1 <= len(parts) <= 3:
        raise HTTPException(400, f"Invalid table name `{table_name}`.")
    return ".".join(quote_identifier(part) for part in parts)


def snowflake_table_parts(table_name: str) -> tuple[str | None, str | None, str]:
    parts = [part.strip().strip('"') for part in str(table_name or "").split(".") if part.strip()]
    if not 1 <= len(parts) <= 3:
        raise HTTPException(400, f"Invalid table name `{table_name}`.")
    if len(parts) == 1:
        return None, None, parts[0]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    return parts[0], parts[1], parts[2]


def schema_query_for_table(table_name: str) -> str:
    database, schema, table = snowflake_table_parts(table_name)
    if database and schema:
        info_schema = f"{quote_identifier(database)}.INFORMATION_SCHEMA.COLUMNS"
    else:
        info_schema = "INFORMATION_SCHEMA.COLUMNS"
    predicates = [f"TABLE_NAME = '{table.upper()}'"]
    if schema:
        predicates.append(f"TABLE_SCHEMA = '{schema.upper()}'")
    return (
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION "
        f"FROM {info_schema} WHERE {' AND '.join(predicates)} ORDER BY ORDINAL_POSITION"
    )


def hash_query_for_table(table_name: str) -> str:
    return f"SELECT HASH_AGG(*) AS ROW_HASH FROM {quote_fqn(table_name)}"


def null_count_query_for_table(table_name: str, columns: list[str]) -> str:
    safe_columns = [col for col in columns if re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", str(col or ""))]
    if not safe_columns:
        return ""
    projections = [f"COUNT_IF({quote_identifier(col)} IS NULL) AS {quote_identifier(col + '_NULLS')}" for col in safe_columns[:50]]
    return f"SELECT {', '.join(projections)} FROM {quote_fqn(table_name)}"


def row_value(row: dict, key: str, default=None):
    if not isinstance(row, dict):
        return default
    if key in row:
        return row[key]
    lowered = key.lower()
    for row_key, value in row.items():
        if str(row_key).lower() == lowered:
            return value
    return default


def normalized_schema(rows: list[dict]) -> list[dict]:
    return [
        {
            "column_name": str(row_value(row, "COLUMN_NAME", "")).upper(),
            "data_type": str(row_value(row, "DATA_TYPE", "")).upper(),
            "is_nullable": str(row_value(row, "IS_NULLABLE", "")).upper(),
            "ordinal_position": row_value(row, "ORDINAL_POSITION"),
        }
        for row in rows
    ]


def sample_fingerprints(rows: list[dict]) -> set[str]:
    return {json.dumps(redact_secrets(row), sort_keys=True, default=str) for row in rows}


def connection_type_value(connection: Connection) -> str:
    return str(getattr(connection.type, "value", connection.type) or "").lower()


def build_snowflake_config(connection: Connection) -> dict:
    credentials = get_cipher().decrypt_dict(connection.credentials) if connection.credentials else {}
    return redact_secrets({**(connection.config or {}), **credentials})


def execute_snowflake_select(connection: Connection, sql: str) -> list[dict]:
    if NON_SELECT_SQL.search(sql) or not SELECT_ONLY.search(sql):
        raise HTTPException(403, "Only allowlisted SELECT queries can be executed.")
    safe_cfg = {**(connection.config or {}), **(get_cipher().decrypt_dict(connection.credentials) if connection.credentials else {})}
    with SnowflakeConnector(safe_cfg) as sf:
        with sf._cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return redact_secrets(rows)


RISK_RULES = [
    ("stored procedures or procedural code", re.compile(r"\b(create\s+(or\s+replace\s+)?(procedure|function|package)|begin\s+|exception\s+when|declare\s+)\b", re.I), "ERROR", "Tag for human review; procedural conversion needs semantic analysis."),
    ("dynamic SQL", re.compile(r"\b(execute\s+immediate|sp_executesql|prepare\s+|exec\s*\()", re.I), "ERROR", "Review dynamic SQL paths and generated statement text before translation."),
    ("temporary tables", re.compile(r"\b(temp|temporary|volatile)\s+table\b", re.I), "WARN", "Confirm Snowflake temporary/transient table semantics and session lifetime."),
    ("identity or sequence behavior", re.compile(r"\b(identity|sequence|nextval|currval|auto_increment|serial)\b", re.I), "WARN", "Validate generated identity/sequence behavior in Snowflake."),
    ("recursive queries", re.compile(r"\bwith\s+recursive\b|\bconnect\s+by\b", re.I), "WARN", "Review recursive query behavior and termination conditions."),
    ("DML write operation", re.compile(r"^\s*(merge|update|delete)\b", re.I), "WARN", "Plan DML carefully; UMA does not execute uploaded SQL by default."),
    ("external stages/files", re.compile(r"\b(external\s+table|copy\s+into|stage|s3://|azure://|gcs://|location\s*=)\b", re.I), "WARN", "Map external stages, file formats, and storage integration requirements."),
    ("UDF/UDAF", re.compile(r"\b(udf|udaf|language\s+(java|python|javascript|scala)|returns\s+table)\b", re.I), "ERROR", "Requires human review and target runtime selection."),
    ("data type risks", re.compile(r"\b(varchar2|number\s*\(|datetime2|money|ntext|clob|blob|bytea|long\s+raw|timestamp\s+with\s+time\s+zone)\b", re.I), "WARN", "Confirm Snowflake data type mapping and precision/scale."),
    ("date/time functions", re.compile(r"\b(sysdate|getdate|dateadd|datediff|months_between|to_date|date_trunc|current_timestamp)\b", re.I), "INFO", "Check date/time function parity and timezone semantics."),
    ("regex functions", re.compile(r"\b(regexp_|regexp_like|rlike|regexp_replace)\b", re.I), "INFO", "Validate regex flavor differences."),
    ("QUALIFY/windowing differences", re.compile(r"\b(qualify|over\s*\(|row_number\s*\(|rank\s*\()\b", re.I), "INFO", "Confirm window ordering and QUALIFY support."),
    ("TOP/LIMIT/SAMPLE syntax", re.compile(r"\b(top\s+\d+|limit\s+\d+|sample\s*\(|tablesample)\b", re.I), "WARN", "Normalize row limiting and sampling syntax for Snowflake."),
    ("BigQuery UNNEST array expansion", re.compile(r"\b(?:left\s+join|cross\s+join|join|,)?\s*unnest\s*\(", re.I), "ERROR", "Rewrite this array expansion with Snowflake LATERAL FLATTEN and verify row-count/cardinality semantics."),
    ("BigQuery SELECT * EXCEPT projection", re.compile(r"\bselect\b[\s\S]{0,300}\*\s+except\s*\(", re.I), "WARN", "Replace SELECT * EXCEPT with an explicit Snowflake projection list before approval."),
    ("BigQuery timestamp conversion", re.compile(r"\b(timestamp_seconds|timestamp_millis|timestamp_micros)\s*\(", re.I), "WARN", "Map BigQuery epoch timestamp conversion to Snowflake TO_TIMESTAMP_* and confirm timezone behavior."),
    ("BigQuery SAFE_CAST", re.compile(r"\bsafe_cast\s*\(", re.I), "WARN", "Map SAFE_CAST to TRY_CAST and confirm null-on-failure behavior is intended."),
    ("BigQuery backtick-qualified object reference", re.compile(r"`[^`]+`"), "WARN", "Convert BigQuery backtick object references to dbt source/ref or Snowflake database.schema.object names."),
    ("unsupported DDL clauses", re.compile(r"\b(tablespace|clustered\s+index|compress\s+for|multiset|fallback|primary\s+index)\b|^\s*(create|alter)\b[\s\S]{0,250}\bpartition\s+by\b", re.I), "ERROR", "Remove or remap source-specific DDL clauses."),
]


def risk_match_evidence(stmt: str, pattern: re.Pattern, line_start: int) -> dict:
    match = pattern.search(stmt or "")
    if not match:
        return {}
    prefix = stmt[:match.start()]
    relative_line = prefix.count("\n")
    lines = stmt.splitlines() or [stmt]
    evidence_line = line_start + relative_line
    excerpt_start = max(0, relative_line - 1)
    excerpt_end = min(len(lines), relative_line + 2)
    return {
        "matched_text": match.group(0)[:240],
        "line": evidence_line,
        "excerpt": "\n".join(lines[excerpt_start:excerpt_end])[:1200],
    }


def normalize_status(severity_counts: dict[str, int]) -> str:
    if severity_counts.get("FATAL", 0) or severity_counts.get("ERROR", 0):
        return "REQUIRES_REVIEW"
    if severity_counts.get("WARN", 0):
        return "COMPLETED_WITH_WARNINGS"
    return "COMPLETED"


def score_from_counts(statement_count: int, severity_counts: dict[str, int]) -> int:
    if statement_count <= 0:
        return 0
    score = 100
    score -= severity_counts.get("FATAL", 0) * 35
    score -= severity_counts.get("ERROR", 0) * 22
    score -= severity_counts.get("WARN", 0) * 10
    score -= min(severity_counts.get("INFO", 0), 6) * 2
    return max(0, min(100, score))


@dataclass
class ControlPlaneService:
    db: AsyncSession

    async def create_artifact_from_upload(self, upload: UploadFile, user: User, run_id: str | None = None, category: str | None = None) -> ControlPlaneArtifact:
        name = upload.filename or "artifact"
        content = await upload.read()
        ext, size = validate_upload(name, content)
        checksum = hashlib.sha256(content).hexdigest()
        safe_name = sanitize_filename(name)
        artifact = ControlPlaneArtifact(
            run_id=run_id,
            filename=safe_name,
            original_filename=name,
            file_type=ext.lstrip("."),
            artifact_category=category or ARTIFACT_CATEGORY_BY_EXT.get(ext, "REQUIREMENTS"),
            storage_path="",
            mime_type=upload.content_type or "application/octet-stream",
            size_bytes=size,
            checksum_sha256=checksum,
            created_by=user.id,
            metadata_json={"status": "UPLOADED"},
        )
        self.db.add(artifact)
        await self.db.flush()
        target_dir = ARTIFACT_ROOT / artifact.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_name
        target_path.write_bytes(content)
        text = redact_secrets(read_artifact_text(ControlPlaneArtifact(storage_path=str(target_path), file_type=ext.lstrip("."), filename=safe_name, original_filename=name, artifact_category="TMP", checksum_sha256=checksum)))
        artifact.storage_path = str(target_path)
        artifact.artifact_category = category or (classify_zip_artifact(target_path) if ext == ".zip" else classify_text_file(ext, text))
        artifact.metadata_json = {
            "status": "CLASSIFIED",
            "line_count": len(text.splitlines()) if text else 0,
            "preview": text[:500],
        }
        await self.db.commit()
        await self.db.refresh(artifact)
        return artifact

    async def create_run(self, *, name: str, workflow_type: str, user: User, safety_mode: str = "READ_ONLY", **kwargs) -> ControlPlaneRun:
        if safety_mode not in SAFETY_MODES:
            raise HTTPException(400, f"Invalid safety_mode `{safety_mode}`.")
        run = ControlPlaneRun(
            name=name,
            workflow_type=workflow_type,
            created_by=user.id,
            safety_mode=safety_mode,
            status=kwargs.pop("status", "PENDING"),
            **kwargs,
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def create_job(self, run_id: str, module: str, phase: str, status: str = "RUNNING", logs: str = "") -> ControlPlaneJob:
        job = ControlPlaneJob(
            run_id=run_id,
            module=module,
            phase=phase,
            status=status,
            started_at=utcnow() if status == "RUNNING" else None,
            logs_redacted=redact_secrets(logs) or "",
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def finish_job(self, job: ControlPlaneJob, status: str, output: dict | None = None, error: str = "") -> ControlPlaneJob:
        job.status = status
        job.completed_at = utcnow()
        safe_output = redact_secrets(output or {})
        job.output_json = safe_output
        job.error_message = redact_secrets(error) or ""
        if not job.logs_redacted:
            summary = {
                "status": status,
                "run_id": job.run_id,
                "module": job.module,
                "phase": job.phase,
                "message": safe_output.get("message") if isinstance(safe_output, dict) else "",
                "output_status": safe_output.get("status") if isinstance(safe_output, dict) else "",
                "file_count": safe_output.get("file_count") if isinstance(safe_output, dict) else None,
                "manual_review_required": safe_output.get("manual_review_required") if isinstance(safe_output, dict) else None,
                "warning_count": len(safe_output.get("warnings", [])) if isinstance(safe_output, dict) and isinstance(safe_output.get("warnings"), list) else None,
            }
            job.logs_redacted = redact_secrets(json.dumps({k: v for k, v in summary.items() if v is not None}, indent=2))
        await self.db.flush()
        return job

    async def artifact_ids(self, ids: list[str]) -> list[ControlPlaneArtifact]:
        if not ids:
            return []
        rows = (
            await self.db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.id.in_(ids)))
        ).scalars().all()
        if len(rows) != len(set(ids)):
            raise HTTPException(404, "One or more artifacts were not found.")
        return list(rows)

    async def link_artifacts(self, artifacts: list[ControlPlaneArtifact], run_id: str) -> None:
        for artifact in artifacts:
            artifact.run_id = run_id
        await self.db.flush()

    async def store_json_artifact(self, run_id: str, category: str, filename: str, payload: dict, user_id: str | None = None) -> ControlPlaneArtifact:
        safe_payload = redact_secrets(payload)
        content = json.dumps(safe_payload, indent=2, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(content).hexdigest()
        artifact = ControlPlaneArtifact(
            run_id=run_id,
            filename=sanitize_filename(filename),
            original_filename=filename,
            file_type="json",
            artifact_category=category,
            storage_path="",
            mime_type="application/json",
            size_bytes=len(content),
            checksum_sha256=checksum,
            created_by=user_id,
            metadata_json={"generated": True},
        )
        self.db.add(artifact)
        await self.db.flush()
        target_dir = ARTIFACT_ROOT / artifact.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / artifact.filename
        target_path.write_bytes(content)
        artifact.storage_path = str(target_path)
        await self.db.flush()
        return artifact

    async def store_text_artifact(self, run_id: str, category: str, filename: str, text: str, user_id: str | None = None, mime_type: str = "text/plain") -> ControlPlaneArtifact:
        safe_text = redact_secrets(text) or ""
        content = safe_text.encode("utf-8")
        checksum = hashlib.sha256(content).hexdigest()
        suffix = Path(filename).suffix.lower().lstrip(".") or "txt"
        artifact = ControlPlaneArtifact(
            run_id=run_id,
            filename=sanitize_filename(filename),
            original_filename=filename,
            file_type=suffix,
            artifact_category=category,
            storage_path="",
            mime_type=mime_type,
            size_bytes=len(content),
            checksum_sha256=checksum,
            created_by=user_id,
            metadata_json={"generated": True},
        )
        self.db.add(artifact)
        await self.db.flush()
        target_dir = ARTIFACT_ROOT / artifact.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / artifact.filename
        target_path.write_bytes(content)
        artifact.storage_path = str(target_path)
        await self.db.flush()
        return artifact

    async def store_binary_artifact(self, run_id: str, category: str, filename: str, content: bytes, user_id: str | None = None, mime_type: str = "application/octet-stream") -> ControlPlaneArtifact:
        checksum = hashlib.sha256(content).hexdigest()
        suffix = Path(filename).suffix.lower().lstrip(".") or "bin"
        artifact = ControlPlaneArtifact(
            run_id=run_id,
            filename=sanitize_filename(filename),
            original_filename=filename,
            file_type=suffix,
            artifact_category=category,
            storage_path="",
            mime_type=mime_type,
            size_bytes=len(content),
            checksum_sha256=checksum,
            created_by=user_id,
            metadata_json={"generated": True},
        )
        self.db.add(artifact)
        await self.db.flush()
        target_dir = ARTIFACT_ROOT / artifact.id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / artifact.filename
        target_path.write_bytes(content)
        artifact.storage_path = str(target_path)
        await self.db.flush()
        return artifact

    def enforce_no_sql_execution(self, sql: str | None = None) -> None:
        if sql:
            raise HTTPException(403, "SQL execution is blocked in this control-plane workflow. Generate a plan or report instead.")

    def enforce_select_only(self, run: ControlPlaneRun, sql: str) -> None:
        if run.safety_mode not in {"VALIDATION_ONLY", "WRITE_APPROVED", "DEPLOY_APPROVED"}:
            raise HTTPException(403, f"Safety mode {run.safety_mode} does not allow validation query execution.")
        if NON_SELECT_SQL.search(sql) or not SELECT_ONLY.search(sql):
            raise HTTPException(403, "Only read-only SELECT validation queries are allowed.")

    def enforce_write_approval(self, run: ControlPlaneRun) -> None:
        if run.safety_mode not in WRITE_MODES or not run.approval_granted:
            run.status = "APPROVAL_REQUIRED"
            raise HTTPException(409, "Approval required before write/apply operations.")


class SqlConversionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)

    async def analyze(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> dict:
        job = await self.common.create_job(run.id, "SQL_CONVERSION", "ANALYZE")
        await self.db.execute(delete(SqlConversionMessage).where(SqlConversionMessage.run_id == run.id))
        file_reports = []
        totals = {"files": len(artifacts), "statements": 0, "INFO": 0, "WARN": 0, "ERROR": 0, "FATAL": 0}
        try:
            for artifact in artifacts:
                text = redact_secrets(read_artifact_text(artifact))
                statements = split_sql_statements(text) if artifact.file_type in {"sql", "ddl", "txt", "md"} else []
                severity_counts = {"INFO": 0, "WARN": 0, "ERROR": 0, "FATAL": 0}
                file_messages = []
                if not statements:
                    statements = [(0, text[:4000], 1, max(1, len(text.splitlines())))] if text.strip() else []
                for idx, stmt, line_start, line_end in statements:
                    parser_stmt = sql_for_semantic_parse(stmt)
                    parsed, parse_error = parse_sql_semantic(parser_stmt or stmt, run.source_dialect)
                    stype = semantic_statement_type(parsed, statement_type(stmt))
                    semantic_metadata = semantic_sql_features(parsed)
                    info = {
                        "file_name": artifact.original_filename,
                        "statement_index": idx,
                        "statement_type": stype,
                        "severity": "INFO",
                        "message": f"Detected {stype} statement using {semantic_metadata['parser']} analysis.",
                        "source_dialect": run.source_dialect,
                        "target_dialect": run.target_dialect,
                        "line_start": line_start,
                        "line_end": line_end,
                        "recommendation": "Review generated readiness findings before attempting conversion.",
                        "metadata_json": semantic_metadata,
                    }
                    if parse_error:
                        info["metadata_json"] = {"parser": "regex_fallback", "parse_error": parse_error}
                    file_messages.append(info)
                    severity_counts["INFO"] += 1
                    self.db.add(SqlConversionMessage(run_id=run.id, artifact_id=artifact.id, **info))
                    if parse_error:
                        msg = {
                            "file_name": artifact.original_filename,
                            "statement_index": idx,
                            "statement_type": stype,
                            "severity": "WARN",
                            "message": "Parser could not fully parse the statement.",
                            "source_dialect": run.source_dialect,
                            "target_dialect": run.target_dialect,
                            "line_start": line_start,
                            "line_end": line_end,
                            "recommendation": "Keep this statement in human review until parser-backed conversion succeeds.",
                            "metadata_json": {"parse_error": parse_error},
                        }
                        file_messages.append(msg)
                        severity_counts["WARN"] += 1
                        self.db.add(SqlConversionMessage(run_id=run.id, artifact_id=artifact.id, **msg))
                    for label, pattern, severity, recommendation in RISK_RULES:
                        evidence = risk_match_evidence(stmt, pattern, line_start)
                        if evidence:
                            detail = f"{label} at line {evidence['line']}: {evidence['matched_text']}"
                            msg = {
                                "file_name": artifact.original_filename,
                                "statement_index": idx,
                                "statement_type": stype,
                                "severity": severity,
                                "message": detail,
                                "source_dialect": run.source_dialect,
                                "target_dialect": run.target_dialect,
                                "line_start": evidence["line"],
                                "line_end": evidence["line"],
                                "recommendation": recommendation,
                                "metadata_json": {"detected_by": "risk_rule", "risk": label, **evidence},
                            }
                            file_messages.append(msg)
                            severity_counts[severity] += 1
                            self.db.add(SqlConversionMessage(run_id=run.id, artifact_id=artifact.id, **msg))
                statement_count = len(statements)
                totals["statements"] += statement_count
                for sev in ("INFO", "WARN", "ERROR", "FATAL"):
                    totals[sev] += severity_counts[sev]
                file_reports.append({
                    "artifact_id": artifact.id,
                    "file_name": artifact.original_filename,
                    "statement_count": statement_count,
                    "message_counts": severity_counts,
                    "readiness_score": score_from_counts(statement_count, severity_counts),
                    "status": normalize_status(severity_counts),
                })
            readiness_score = score_from_counts(max(totals["statements"], 1), totals)
            report = {
                "run_id": run.id,
                "workflow_type": run.workflow_type,
                "source_dialect": run.source_dialect,
                "target_dialect": run.target_dialect,
                "analysis_engine": "sqlglot" if sqlglot else "regex_fallback",
                "translation_status": "AVAILABLE_FOR_SAFE_STATEMENTS" if sqlglot else "REQUIRES_CONFIGURATION",
                "translation_note": "Parser-backed safe statement translation is available for supported non-procedural SQL." if sqlglot else "No configured SQL translator is available. UMA produced readiness analysis only.",
                "summary": totals,
                "readiness_score": readiness_score,
                "files": file_reports,
            }
            await self.common.store_json_artifact(run.id, "REPORT", "sql-conversion-report.json", report, run.created_by)
            run.status = normalize_status(totals)
            run.current_phase = "ANALYZED"
            run.completed_at = utcnow()
            run.summary_json = report
            run.metrics_json = {"readiness_score": readiness_score, **totals}
            await self.common.finish_job(job, "COMPLETED", report)
            await self.db.commit()
            return report
        except Exception as exc:
            run.status = "FAILED"
            run.error_message = redact_secrets(str(exc))
            await self.common.finish_job(job, "FAILED", {}, str(exc))
            await self.db.commit()
            raise

    async def translate(self, run: ControlPlaneRun) -> dict:
        job = await self.common.create_job(run.id, "SQL_CONVERSION", "TRANSLATE")
        artifacts = await self.common.artifact_ids((run.config_json or {}).get("artifact_ids", []))
        translated_files = []
        unsupported_items = []
        from services.sql_snowflake_conversion import SqlToSnowflakeConversionEngine, _conversion_status

        engine = SqlToSnowflakeConversionEngine(self.db)
        for artifact in artifacts:
            text = redact_secrets(read_artifact_text(artifact))
            detection = engine.detect_dialect(text, run.source_dialect)
            input_type = "dbt_project" if "{{" in text or "{%" in text else "sql_file"
            converted = engine._convert_sql_text(text, detection.dialect, input_type)
            conversion_status = _conversion_status(converted)
            file_issues = sorted(set(
                (converted.get("warnings") or [])
                + (converted.get("unsupported_features") or [])
                + (converted.get("errors") or [])
            ))
            for issue in file_issues:
                unsupported_items.append({
                    "file_name": artifact.original_filename,
                    "statement_index": None,
                    "line_start": None,
                    "line_end": None,
                    "reason": issue,
                    "review_required": True,
                    "conversion_status": conversion_status,
                })
            if converted.get("sql", "").strip():
                sql_text = _snowflake_sql_without_dbt_macros(converted["sql"]) if input_type == "dbt_project" else converted["sql"]
                generated = await self.common.store_text_artifact(
                    run.id,
                    "GENERATED_SQL",
                    f"{Path(artifact.original_filename).stem}_snowflake.sql",
                    sql_text,
                    run.created_by,
                    "text/sql",
                )
                generated.metadata_json = {
                    "generated": True,
                    "source_artifact_id": artifact.id,
                    "source_file": artifact.original_filename,
                    "detected_dialect": detection.dialect,
                    "target_dialect": run.target_dialect or "snowflake",
                    "conversion_status": conversion_status,
                    "manual_review_required": converted.get("manual_review_required", False),
                    "rules_applied": converted.get("rules_applied") or [],
                    "warnings": converted.get("warnings") or [],
                    "unsupported_features": converted.get("unsupported_features") or [],
                    "source_residue": converted.get("source_residue") or [],
                }
                translated_files.append({
                    "artifact_id": generated.id,
                    "file_name": generated.original_filename,
                    "artifact_category": generated.artifact_category,
                    "conversion_status": conversion_status,
                })
                if input_type == "dbt_project":
                    dbt_artifact = await self.common.store_text_artifact(
                        run.id,
                        "GENERATED_DBT",
                        Path(artifact.original_filename).name,
                        converted["sql"],
                        run.created_by,
                        "text/sql",
                    )
                    dbt_artifact.metadata_json = {
                        **generated.metadata_json,
                        "artifact_kind": "snowflake_dbt_model",
                        "paired_sql_artifact_id": generated.id,
                    }
                    translated_files.append({
                        "artifact_id": dbt_artifact.id,
                        "file_name": dbt_artifact.original_filename,
                        "artifact_category": dbt_artifact.artifact_category,
                        "conversion_status": conversion_status,
                    })
        run.status = "REQUIRES_REVIEW" if unsupported_items else "COMPLETED"
        run.current_phase = "TRANSLATED_WITH_REVIEW" if unsupported_items else "TRANSLATED"
        payload = {
            "status": run.status,
            "translation_engine": "sqlglot" if sqlglot else "unavailable",
            "message": "Generated parser-backed translations for safe statements; unsupported items are tagged for human review." if sqlglot else "A SQL translation engine is not configured.",
            "executed": False,
            "translated_files": translated_files,
            "unsupported_items": unsupported_items,
        }
        run.summary_json = {**(run.summary_json or {}), "translation": payload}
        await self.common.finish_job(job, "COMPLETED" if sqlglot else "SKIPPED", payload)
        await self.db.commit()
        return payload


def _snowflake_sql_without_dbt_macros(sql: str) -> str:
    without_config = re.sub(r"\{\{\s*config\s*\(.*?\)\s*\}\}\s*", "", sql or "", flags=re.I | re.S)
    without_sources = re.sub(
        r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
        lambda match: f'"{match.group(1)}"."{match.group(2)}"',
        without_config,
        flags=re.I,
    )
    without_refs = re.sub(
        r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
        lambda match: f'"{match.group(1)}"',
        without_sources,
        flags=re.I,
    )
    return re.sub(r"\n{3,}", "\n\n", without_refs).strip() + "\n"


class AnalyzerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)

    def extract_components(self, artifact: ControlPlaneArtifact, analyzer_type: str) -> tuple[list[dict], list[dict], dict]:
        text = redact_secrets(read_artifact_text(artifact))
        components: list[dict] = []
        dependencies: list[dict] = []
        metadata = {"analyzer_type": analyzer_type, "source_file": artifact.original_filename}
        if artifact.file_type in {"json"} or analyzer_type == "GENERIC_JSON":
            try:
                parsed = json.loads(text)
                keys = list(parsed.keys()) if isinstance(parsed, dict) else []
                for key in keys[:100]:
                    components.append({"component_type": "JSON_NODE", "name": str(key), "metadata": {}})
                metadata["json_keys"] = len(keys)
            except Exception as exc:
                metadata["parse_error"] = str(exc)
        else:
            try:
                root = ET.fromstring(text)
                seen = set()
                for elem in root.iter():
                    name = (
                        elem.attrib.get("name") or elem.attrib.get("Name") or elem.attrib.get("caption") or
                        elem.attrib.get("id") or elem.tag.split("}")[-1]
                    )
                    component_type = elem.tag.split("}")[-1].upper()
                    key = (component_type, name)
                    if key not in seen:
                        seen.add(key)
                        components.append({
                            "component_type": component_type,
                            "name": name[:255],
                            "metadata": {"attributes": redact_secrets(dict(elem.attrib))},
                        })
                    source = elem.attrib.get("source") or elem.attrib.get("Source") or elem.attrib.get("from")
                    target = elem.attrib.get("target") or elem.attrib.get("Target") or elem.attrib.get("to")
                    if source and target:
                        dependencies.append({
                            "source_component": source[:255],
                            "target_component": target[:255],
                            "dependency_type": "XML_ATTRIBUTE",
                            "metadata": {"tag": component_type},
                        })
                metadata["xml_root"] = root.tag.split("}")[-1]
            except Exception as exc:
                metadata["parse_error"] = str(exc)
        for match in re.finditer(r"(?i)\b(from|join|table|connection|datasource|schema)\s*[:=]?\s*['\"]?([A-Za-z0-9_.-]+)", text):
            name = match.group(2)
            components.append({"component_type": match.group(1).upper(), "name": name[:255], "metadata": {"detected_by": "text_scan"}})
        return components[:300], dependencies[:300], metadata

    async def scan(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact], analyzer_type: str) -> dict:
        job = await self.common.create_job(run.id, "ANALYZER", "SCAN")
        await self.db.execute(delete(AnalyzerComponent).where(AnalyzerComponent.run_id == run.id))
        await self.db.execute(delete(AnalyzerDependency).where(AnalyzerDependency.run_id == run.id))
        reports = []
        total_components = 0
        total_dependencies = 0
        for artifact in artifacts:
            components, dependencies, metadata = self.extract_components(artifact, analyzer_type)
            total_components += len(components)
            total_dependencies += len(dependencies)
            for comp in components:
                self.db.add(AnalyzerComponent(
                    run_id=run.id,
                    component_type=comp["component_type"],
                    name=comp["name"],
                    source_file=artifact.original_filename,
                    metadata_json=comp.get("metadata", {}),
                ))
            for dep in dependencies:
                self.db.add(AnalyzerDependency(run_id=run.id, **dep))
            reports.append({
                "artifact_id": artifact.id,
                "file_name": artifact.original_filename,
                "component_count": len(components),
                "dependency_count": len(dependencies),
                "metadata": metadata,
            })
        complexity_score = min(100, total_components * 2 + total_dependencies * 5)
        report = {
            "run_id": run.id,
            "analyzer_type": analyzer_type,
            "component_count": total_components,
            "dependency_count": total_dependencies,
            "complexity_score": complexity_score,
            "files": reports,
        }
        run.status = "COMPLETED_WITH_WARNINGS" if any("parse_error" in f["metadata"] for f in reports) else "COMPLETED"
        run.current_phase = "SCANNED"
        run.completed_at = utcnow()
        run.summary_json = report
        run.metrics_json = {"complexity_score": complexity_score, "component_count": total_components, "dependency_count": total_dependencies}
        await self.common.store_json_artifact(run.id, "REPORT", "etl-bi-analyzer-report.json", report, run.created_by)
        await self.common.finish_job(job, "COMPLETED", report)
        await self.db.commit()
        return report


class MigrationIntelligenceControlService:
    PHASES = [
        "Intent Analyzer", "Artifact Classifier", "Source Inventory Builder", "SQL Risk Analyzer",
        "Source-to-Target Mapping Draft", "Load Strategy Advisor", "Validation Plan Builder",
        "Human Review Item Generator", "Report Builder",
    ]

    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)
        self.sql = SqlConversionService(db)
        self.analyzer = AnalyzerService(db)

    async def execute(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> dict:
        job = await self.common.create_job(run.id, "AGENTIC_INTELLIGENCE", "EXECUTE")
        run.status = "RUNNING"
        run.started_at = utcnow()
        run.current_phase = "Intent Analyzer"
        await self.db.flush()
        await self.db.execute(delete(HumanReviewItem).where(HumanReviewItem.run_id == run.id))

        sql_artifacts = [a for a in artifacts if a.artifact_category in {"SOURCE_SQL", "SOURCE_DDL"} or a.file_type in {"sql", "ddl"}]
        etl_artifacts = [a for a in artifacts if a.artifact_category in {"ETL_XML", "TABLEAU"} or a.file_type in {"xml", "twb", "twbx", "json"}]
        inventory = []
        for artifact in artifacts:
            text = redact_secrets(read_artifact_text(artifact))
            refs = sorted(set(re.findall(r"(?i)\b(?:from|join|into|update|table|view)\s+([A-Za-z0-9_.$\"]+)", text)))
            inventory.append({
                "artifact_id": artifact.id,
                "file_name": artifact.original_filename,
                "category": artifact.artifact_category,
                "file_type": artifact.file_type,
                "detected_references": refs[:50],
                "line_count": len(text.splitlines()),
            })

        sql_report = await self.sql.analyze(run, sql_artifacts) if sql_artifacts else {
            "readiness_score": 100,
            "summary": {"files": 0, "statements": 0, "INFO": 0, "WARN": 0, "ERROR": 0, "FATAL": 0},
            "files": [],
        }
        analyzer_report = await self.analyzer.scan(run, etl_artifacts, "GENERIC_XML") if etl_artifacts else {
            "component_count": 0,
            "dependency_count": 0,
            "complexity_score": 0,
            "files": [],
        }

        risk_register = []
        message_rows = (
            await self.db.execute(select(SqlConversionMessage).where(SqlConversionMessage.run_id == run.id))
        ).scalars().all()
        for msg in message_rows:
            if msg.severity in {"WARN", "ERROR", "FATAL"}:
                metadata = msg.metadata_json or {}
                evidence_line = metadata.get("line") or msg.line_start
                matched_text = metadata.get("matched_text") or msg.message
                excerpt = metadata.get("excerpt") or ""
                title = f"{msg.file_name}: {msg.message}"
                evidence = f"{msg.file_name}"
                if evidence_line:
                    evidence += f" line {evidence_line}"
                evidence += f": {matched_text}"
                if excerpt:
                    evidence += f"\n\n{excerpt}"
                risk_register.append({
                    "severity": msg.severity,
                    "title": title,
                    "file_name": msg.file_name,
                    "statement_index": msg.statement_index,
                    "line": evidence_line,
                    "matched_text": matched_text,
                    "excerpt": excerpt,
                    "recommendation": msg.recommendation,
                })

        if analyzer_report["complexity_score"] >= 50:
            self.db.add(HumanReviewItem(
                run_id=run.id,
                item_type="ETL_BI_COMPLEXITY",
                severity="WARN",
                title="ETL/BI artifact complexity requires review",
                description="Extracted components and dependencies indicate non-trivial migration complexity.",
                recommendation="Review component inventory and validate dependency extraction before implementation.",
            ))

        readiness_score = max(0, min(100, round((sql_report.get("readiness_score", 100) * 0.7) + ((100 - analyzer_report["complexity_score"]) * 0.3))))
        complexity_score = max(analyzer_report["complexity_score"], min(100, len(risk_register) * 8 + len(artifacts) * 3))
        load_strategy = {
            "recommended": "incremental_merge" if any("merge" in r["title"].lower() for r in risk_register) else "full_refresh",
            "options": ["full_refresh", "incremental_append", "incremental_merge", "cdc_column", "watermark", "hash_diff", "soft_delete", "hard_delete", "ignore_deletes"],
            "note": "Strategy is a deterministic planning recommendation; no data movement was executed.",
        }
        validation_plan = {
            "checks": ["schema_compare", "row_count", "null_counts", "hash_aggregate", "sampled_row_diff"],
            "execution_status": "PLANNED",
            "requires_connections": True,
            "safety_mode_required": "VALIDATION_ONLY",
        }
        report = {
            "title": f"Migration Readiness Report - {run.name}",
            "run_id": run.id,
            "migration_summary": {
                "artifact_count": len(artifacts),
                "sql_file_count": len(sql_artifacts),
                "etl_bi_file_count": len(etl_artifacts),
                "llm_status": "SKIPPED_REQUIRES_CONFIGURATION",
                "snowflake_execution": "NOT_EXECUTED",
            },
            "source_inventory": inventory,
            "risk_register": risk_register,
            "complexity_score": complexity_score,
            "readiness_score": readiness_score,
            "source_to_target_mapping": [
                {"source": item["detected_references"][0], "target": f"SNOWFLAKE.{item['detected_references'][0].replace('.', '_').upper()}", "status": "DRAFT"}
                for item in inventory if item["detected_references"]
            ],
            "load_strategy": load_strategy,
            "validation_plan": validation_plan,
            "human_review_items": len(risk_register),
            "recommended_next_actions": [
                "Resolve ERROR/FATAL SQL readiness findings.",
                "Confirm source-to-target object mappings.",
                "Generate provisioning and validation plans before any execution.",
                "Configure Snowflake and LLM providers only when ready; UMA did not call them by default.",
            ],
            "sql_conversion_readiness": sql_report,
            "etl_bi_dependency_analysis": analyzer_report,
            "provisioning_plan_summary": "Not generated in this run; use Snowflake Provisioning for a plan-only landing zone.",
            "advisor_summary": "Snowflake readiness scan not executed unless a configured connection is selected.",
        }
        await self.common.store_json_artifact(run.id, "REPORT", "migration-readiness-report.json", report, run.created_by)
        run.status = "REQUIRES_REVIEW" if risk_register else "COMPLETED"
        run.current_phase = "Report Builder"
        run.completed_at = utcnow()
        run.summary_json = report
        run.metrics_json = {"readiness_score": readiness_score, "complexity_score": complexity_score, "risk_count": len(risk_register)}
        await self.common.finish_job(job, "COMPLETED", report)
        await self.db.commit()
        return report


class ProvisionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)

    def generate_plan(self, config: dict, connected: bool = False) -> dict:
        cfg = {k: str(v).strip() for k, v in config.items() if v is not None}
        db_name = cfg.get("target_database") or f"{cfg.get('project_name', 'UMA')}_DB".upper()
        raw = cfg.get("raw_schema", "RAW")
        staging = cfg.get("staging_schema", "STAGING")
        curated = cfg.get("curated_schema", "CURATED")
        reporting = cfg.get("reporting_schema", "REPORTING")
        wh = cfg.get("migration_warehouse", "UMA_MIGRATION_WH")
        val_wh = cfg.get("validation_warehouse", "UMA_VALIDATION_WH")
        owner = cfg.get("owner_role", "UMA_OWNER_ROLE")
        read = cfg.get("read_role", "UMA_READ_ROLE")
        write = cfg.get("write_role", "UMA_WRITE_ROLE")
        statements = [
            f"CREATE DATABASE IF NOT EXISTS {db_name};",
            f"CREATE SCHEMA IF NOT EXISTS {db_name}.{raw};",
            f"CREATE SCHEMA IF NOT EXISTS {db_name}.{staging};",
            f"CREATE SCHEMA IF NOT EXISTS {db_name}.{curated};",
            f"CREATE SCHEMA IF NOT EXISTS {db_name}.{reporting};",
            f"CREATE WAREHOUSE IF NOT EXISTS {wh} WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;",
            f"CREATE WAREHOUSE IF NOT EXISTS {val_wh} WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;",
            f"CREATE ROLE IF NOT EXISTS {owner};",
            f"CREATE ROLE IF NOT EXISTS {read};",
            f"CREATE ROLE IF NOT EXISTS {write};",
            f"GRANT USAGE ON DATABASE {db_name} TO ROLE {read};",
            f"GRANT USAGE ON DATABASE {db_name} TO ROLE {write};",
            f"GRANT USAGE ON WAREHOUSE {wh} TO ROLE {write};",
            f"GRANT USAGE ON WAREHOUSE {val_wh} TO ROLE {read};",
            f"CREATE FILE FORMAT IF NOT EXISTS {db_name}.{staging}.CSV_STANDARD TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = '\"' SKIP_HEADER = 1;",
        ]
        return {
            "mode": "connected_plan" if connected else "local_plan",
            "status": "PLANNED_NOT_EXECUTED",
            "destructive_operations_blocked": True,
            "statement_count": len(statements),
            "statements": [s for s in statements if not re.search(r"^\s*drop\b", s, re.I)],
            "resources": {
                "database": db_name,
                "schemas": [raw, staging, curated, reporting],
                "warehouses": [wh, val_wh],
                "roles": [owner, read, write],
                "templates": ["landing_zone", "least_privilege_roles", "validation_warehouse"],
                "stacks": [cfg.get("environment", "dev")],
            },
        }


class AdvisorService:
    CHECKS = {
        "SECURITY": ["failed login attempts", "users with powerful roles", "MFA/account parameter visibility"],
        "COMPUTE": ["warehouse credit usage", "queued queries", "spilling queries", "long running queries", "auto suspend settings"],
        "STORAGE": ["largest tables", "high retention tables", "transient/permanent table review"],
        "STATUS": ["failing tasks", "broken pipes", "stale streams", "invalid views"],
        "MIGRATION_READINESS": ["target database exists", "target schema exists", "target warehouse exists", "migration role can use warehouse", "ACCOUNT_USAGE access"],
        "NETWORK": ["network policy visibility"],
        "COST": ["credit usage posture"],
        "ACCOUNT": ["account parameter visibility"],
        "SCOPING": ["migration scope completeness"],
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    def allowlisted_sql(self, category: str, check_name: str) -> str:
        key = (category.upper(), check_name.lower())
        checks = {
            ("SECURITY", "failed login attempts"): "SELECT USER_NAME, ERROR_MESSAGE, COUNT(*) RESULT_COUNT FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY WHERE IS_SUCCESS = 'NO' AND EVENT_TIMESTAMP >= DATEADD('day', -7, CURRENT_TIMESTAMP()) GROUP BY USER_NAME, ERROR_MESSAGE ORDER BY RESULT_COUNT DESC LIMIT 20",
            ("SECURITY", "users with powerful roles"): "SELECT GRANTEE_NAME, ROLE FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS WHERE DELETED_ON IS NULL AND ROLE IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN') LIMIT 50",
            ("SECURITY", "mfa/account parameter visibility"): "SELECT KEY, VALUE FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) LIMIT 0",
            ("COMPUTE", "warehouse credit usage"): "SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) CREDITS_USED FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP()) GROUP BY WAREHOUSE_NAME ORDER BY CREDITS_USED DESC LIMIT 20",
            ("COMPUTE", "queued queries"): "SELECT WAREHOUSE_NAME, COUNT(*) RESULT_COUNT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP()) AND QUEUED_OVERLOAD_TIME > 0 GROUP BY WAREHOUSE_NAME ORDER BY RESULT_COUNT DESC LIMIT 20",
            ("COMPUTE", "spilling queries"): "SELECT QUERY_ID, USER_NAME, WAREHOUSE_NAME, BYTES_SPILLED_TO_REMOTE_STORAGE FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP()) AND BYTES_SPILLED_TO_REMOTE_STORAGE > 0 ORDER BY BYTES_SPILLED_TO_REMOTE_STORAGE DESC LIMIT 20",
            ("COMPUTE", "long running queries"): "SELECT QUERY_ID, USER_NAME, WAREHOUSE_NAME, TOTAL_ELAPSED_TIME FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP()) AND TOTAL_ELAPSED_TIME > 3600000 ORDER BY TOTAL_ELAPSED_TIME DESC LIMIT 20",
            ("COMPUTE", "auto suspend settings"): "SELECT NAME, AUTO_SUSPEND, AUTO_RESUME FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES WHERE DELETED IS NULL LIMIT 50",
            ("STORAGE", "largest tables"): "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, BYTES FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS ORDER BY BYTES DESC LIMIT 20",
            ("STORAGE", "high retention tables"): "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, RETENTION_TIME FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES WHERE DELETED IS NULL AND RETENTION_TIME > 1 ORDER BY RETENTION_TIME DESC LIMIT 50",
            ("STORAGE", "transient/permanent table review"): "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, IS_TRANSIENT FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES WHERE DELETED IS NULL LIMIT 50",
            ("STATUS", "failing tasks"): "SELECT NAME, DATABASE_NAME, SCHEMA_NAME, STATE, ERROR_MESSAGE FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE SCHEDULED_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP()) AND STATE = 'FAILED' LIMIT 50",
            ("STATUS", "broken pipes"): "SELECT PIPE_CATALOG, PIPE_SCHEMA, PIPE_NAME, ERROR FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY WHERE LAST_LOAD_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP()) AND ERROR IS NOT NULL LIMIT 50",
            ("STATUS", "stale streams"): "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, STALE FROM SNOWFLAKE.ACCOUNT_USAGE.STREAMS WHERE DELETED IS NULL AND STALE = TRUE LIMIT 50",
            ("STATUS", "invalid views"): "SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME FROM SNOWFLAKE.ACCOUNT_USAGE.VIEWS WHERE DELETED IS NULL LIMIT 50",
            ("MIGRATION_READINESS", "target database exists"): "SELECT CURRENT_DATABASE() CURRENT_DATABASE",
            ("MIGRATION_READINESS", "target schema exists"): "SELECT CURRENT_SCHEMA() CURRENT_SCHEMA",
            ("MIGRATION_READINESS", "target warehouse exists"): "SELECT CURRENT_WAREHOUSE() CURRENT_WAREHOUSE",
            ("MIGRATION_READINESS", "migration role can use warehouse"): "SELECT CURRENT_ROLE() CURRENT_ROLE, CURRENT_WAREHOUSE() CURRENT_WAREHOUSE",
            ("MIGRATION_READINESS", "account_usage access"): "SELECT COUNT(*) RESULT_COUNT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())",
            ("NETWORK", "network policy visibility"): "SELECT CURRENT_ACCOUNT() CURRENT_ACCOUNT",
            ("COST", "credit usage posture"): "SELECT SUM(CREDITS_USED) CREDITS_USED FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
            ("ACCOUNT", "account parameter visibility"): "SELECT CURRENT_ACCOUNT() CURRENT_ACCOUNT, CURRENT_REGION() CURRENT_REGION",
            ("SCOPING", "migration scope completeness"): "SELECT CURRENT_DATABASE() CURRENT_DATABASE, CURRENT_SCHEMA() CURRENT_SCHEMA",
        }
        sql = checks.get(key)
        if not sql:
            return f"SELECT '{category}' AS CATEGORY, '{check_name}' AS CHECK_NAME"
        return sql

    async def create_scan_results(self, scan: AdvisorScan, categories: list[str], dry_run: bool) -> dict:
        await self.db.execute(delete(AdvisorCheckResult).where(AdvisorCheckResult.scan_id == scan.id))
        categories = categories or list(self.CHECKS.keys())
        total = 0
        requires_config = not dry_run and not scan.connection_id
        connection = await self.db.get(Connection, scan.connection_id) if scan.connection_id and not dry_run else None
        for category in categories:
            for check_name in self.CHECKS.get(category, []):
                total += 1
                status = "PLANNED" if dry_run else ("REQUIRES_CONFIGURATION" if requires_config else "COMPLETED")
                severity = "INFO" if dry_run else ("WARN" if requires_config else "INFO")
                raw_sql = self.allowlisted_sql(category, check_name)
                rows = []
                error_message = ""
                if connection and not dry_run:
                    try:
                        rows = execute_snowflake_select(connection, raw_sql)
                    except Exception as exc:
                        status = "FAILED"
                        severity = "WARN"
                        error_message = redact_secrets(str(exc)) or "Check failed"
                self.db.add(AdvisorCheckResult(
                    scan_id=scan.id,
                    check_name=check_name,
                    category=category,
                    severity=severity,
                    status=status,
                    description=f"{check_name.title()} readiness check.",
                    result_count=len(rows),
                    result_sample_json=rows[:5],
                    recommendation=error_message or ("Configure a Snowflake connection to run this allowlisted check." if requires_config else "Review results before remediation."),
                    raw_sql_redacted=redact_secrets(raw_sql),
                ))
        base = 100 if dry_run else (45 if requires_config else 80)
        scan.health_score = base
        scan.security_score = base
        scan.compute_score = base
        scan.storage_score = base
        scan.cost_score = base
        scan.operational_score = base
        scan.migration_readiness_score = base
        scan.status = "COMPLETED" if dry_run else ("REQUIRES_CONFIGURATION" if requires_config else "COMPLETED_WITH_WARNINGS")
        scan.completed_at = utcnow()
        report = {
            "scan_id": scan.id,
            "status": scan.status,
            "dry_run": dry_run,
            "check_count": total,
            "scores": {
                "health": scan.health_score,
                "security": scan.security_score,
                "compute": scan.compute_score,
                "storage": scan.storage_score,
                "cost": scan.cost_score,
                "operational": scan.operational_score,
                "migration_readiness": scan.migration_readiness_score,
            },
        }
        await self.db.commit()
        return report


class ValidationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)

    def build_plan(self, run: ControlPlaneRun) -> dict:
        cfg = run.config_json or {}
        tables = cfg.get("tables") or []
        checks = ["schema_compare", "row_count", "null_counts", "hash_aggregate", "sampled_row_diff"]
        return {
            "run_id": run.id,
            "status": "PLANNED_NOT_EXECUTED",
            "checks": checks,
            "tables": [
                {
                    "table": table,
                    "queries": {
                        "row_count": f"SELECT COUNT(*) AS ROW_COUNT FROM {quote_fqn(table)}",
                        "sample": f"SELECT * FROM {quote_fqn(table)} LIMIT 100",
                    },
                    "ignored_columns": cfg.get("ignored_columns", []),
                    "max_differences": cfg.get("max_differences", 0),
                    "filters": cfg.get("filters", {}),
                    "status": "PLANNED",
                }
                for table in tables
            ],
            "execution_requirements": ["source_connection_id", "target_connection_id", "VALIDATION_ONLY or stronger safety mode"],
        }

    async def execute(self, run: ControlPlaneRun) -> dict:
        if run.safety_mode not in {"VALIDATION_ONLY", "WRITE_APPROVED", "DEPLOY_APPROVED"}:
            raise HTTPException(403, "Validation execution requires safety mode VALIDATION_ONLY or higher.")
        if not run.source_connection_id or not run.target_connection_id:
            run.status = "REQUIRES_CONFIGURATION"
            await self.db.commit()
            return {"status": "REQUIRES_CONFIGURATION", "executed": False, "message": "Source and target connections are required."}
        source = await self.db.get(Connection, run.source_connection_id)
        target = await self.db.get(Connection, run.target_connection_id)
        if not source or not target:
            raise HTTPException(404, "Source or target connection not found.")
        if str(source.type) != "ConnectionType.snowflake" and getattr(source.type, "value", source.type) != "snowflake":
            return {"status": "REQUIRES_CONFIGURATION", "executed": False, "message": "First connected validation implementation supports Snowflake connections only."}
        if str(target.type) != "ConnectionType.snowflake" and getattr(target.type, "value", target.type) != "snowflake":
            return {"status": "REQUIRES_CONFIGURATION", "executed": False, "message": "First connected validation implementation supports Snowflake connections only."}

        results = []
        for table_cfg in self.build_plan(run)["tables"]:
            table = table_cfg["table"]
            row_count_sql = table_cfg["queries"]["row_count"]
            sample_sql = table_cfg["queries"]["sample"]
            source_count_rows = execute_snowflake_select(source, row_count_sql)
            target_count_rows = execute_snowflake_select(target, row_count_sql)
            source_count = int((source_count_rows[0] or {}).get("ROW_COUNT", 0)) if source_count_rows else 0
            target_count = int((target_count_rows[0] or {}).get("ROW_COUNT", 0)) if target_count_rows else 0
            sample_rows = execute_snowflake_select(target, sample_sql)
            results.append({
                "table": table,
                "row_count_source": source_count,
                "row_count_target": target_count,
                "diff_count": abs(source_count - target_count),
                "status": "MATCH" if source_count == target_count else "DIFFERENT",
                "recommendation": "Review sampled row diff and hash checks." if source_count != target_count else "No row-count difference detected.",
                "executed_sql_redacted": {"source": redact_secrets(row_count_sql), "target": redact_secrets(row_count_sql)},
                "sample_target_rows": sample_rows[:10],
                "hash_aggregate": "PLANNED_NOT_EXECUTED",
                "schema_compare": "PLANNED_NOT_EXECUTED",
                "sampled_row_diff": "TARGET_SAMPLE_CAPTURED",
            })
        payload = {"status": "COMPLETED", "executed": True, "results": results}
        run.status = "COMPLETED_WITH_WARNINGS" if any(r["status"] != "MATCH" for r in results) else "COMPLETED"
        run.summary_json = payload
        run.metrics_json = {"table_count": len(results), "difference_count": len([r for r in results if r["status"] != "MATCH"])}
        await self.common.store_json_artifact(run.id, "VALIDATION_RESULT", "validation-results.json", payload, run.created_by)
        await self.db.commit()
        return payload


class DataContractService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.common = ControlPlaneService(db)

    def infer_contract(self, artifact: ControlPlaneArtifact, text: str) -> dict:
        tables = sorted(set(re.findall(r"(?i)\b(?:create\s+table|from|join|into)\s+([A-Za-z0-9_.$\"]+)", text)))
        columns = sorted(set(re.findall(r"(?i)\b([A-Za-z_][A-Za-z0-9_]*)\s+(?:NUMBER|INT|INTEGER|VARCHAR|STRING|DATE|TIMESTAMP|BOOLEAN|DECIMAL)", text)))[:200]
        return {
            "artifact_id": artifact.id,
            "source_file": artifact.original_filename,
            "objects": tables,
            "columns": [{"name": col, "type": "UNKNOWN", "nullable": True, "tests": []} for col in columns],
            "quality_rules": [
                {"rule": "row_count_reconciliation", "severity": "ERROR"},
                {"rule": "schema_compare", "severity": "ERROR"},
                {"rule": "not_null_primary_keys", "severity": "WARN"},
            ],
            "owner": "REQUIRES_REVIEW",
            "status": "DRAFT_REQUIRES_REVIEW",
        }

    async def generate(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> dict:
        contracts = [self.infer_contract(artifact, redact_secrets(read_artifact_text(artifact))) for artifact in artifacts]
        payload = {
            "run_id": run.id,
            "status": "COMPLETED_WITH_WARNINGS",
            "review_required": True,
            "contracts": contracts,
        }
        run.status = "REQUIRES_REVIEW"
        run.summary_json = payload
        run.metrics_json = {"contract_count": len(contracts)}
        await self.common.store_json_artifact(run.id, "DATA_CONTRACT", "data-contracts.json", payload, run.created_by)
        await self.db.commit()
        return payload


class MetadataSearchService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(self, query: str, limit: int = 20) -> dict:
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_.$]+", query or "") if len(term) > 1]
        rows = (await self.db.execute(select(ControlPlaneArtifact).order_by(ControlPlaneArtifact.created_at.desc()).limit(500))).scalars().all()
        scored = []
        for artifact in rows:
            haystack = " ".join([
                artifact.original_filename or "",
                artifact.artifact_category or "",
                json.dumps(artifact.metadata_json or {}),
                read_artifact_text(artifact, max_bytes=50_000),
            ]).lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append({"score": score, "artifact": artifact})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return {
            "query": query,
            "mode": "metadata_keyword_search",
            "llm_status": "NOT_USED",
            "results": [
                {
                    "artifact_id": item["artifact"].id,
                    "file_name": item["artifact"].original_filename,
                    "category": item["artifact"].artifact_category,
                    "score": item["score"],
                    "preview": (item["artifact"].metadata_json or {}).get("preview", "")[:300],
                }
                for item in scored[:limit]
            ],
        }

    async def guarded_nl2sql(self, question: str) -> dict:
        if re.search(r"(?i)\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|copy|call|execute)\b", question or ""):
            raise HTTPException(403, "NL2SQL is read-only. Write or DDL intent is blocked.")
        search = await self.search(question, limit=5)
        candidate_table = None
        for result in search["results"]:
            text = result.get("preview") or result["file_name"]
            match = re.search(r"(?i)\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2})\b", text)
            if match:
                candidate_table = match.group(1)
                break
        sql = f"SELECT * FROM {quote_fqn(candidate_table)} LIMIT 100" if candidate_table else "SELECT CURRENT_DATE() AS CURRENT_DATE"
        return {
            "question": question,
            "sql": sql,
            "status": "DRAFT_NOT_EXECUTED",
            "execution_allowed": False,
            "guardrails": ["READ_ONLY_ONLY", "NOT_EXECUTED_BY_DEFAULT", "HUMAN_REVIEW_REQUIRED"],
            "evidence": search["results"],
        }


class RichReportService:
    def render_html(self, title: str, report: dict) -> str:
        def esc(value):
            return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        sections = []
        for key, value in (report or {}).items():
            if key in {"run_id", "title"}:
                continue
            sections.append(f"<section><h2>{esc(key.replace('_', ' ').title())}</h2><pre>{esc(json.dumps(value, indent=2, sort_keys=True))}</pre></section>")
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>body{{font-family:Inter,Arial,sans-serif;margin:32px;color:#172033}}h1{{font-size:28px}}h2{{font-size:18px;margin-top:28px}}section{{border-top:1px solid #d7dee8;padding-top:12px}}pre{{white-space:pre-wrap;background:#f7fafc;border:1px solid #dde6ef;border-radius:8px;padding:14px;font-size:12px}}</style>
</head><body><h1>{esc(title)}</h1>{''.join(sections)}</body></html>"""
