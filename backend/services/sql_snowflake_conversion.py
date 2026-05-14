from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path
import asyncio
import os
import shutil
import csv
import difflib
import json
import re
import subprocess
import tempfile
import zipfile
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.state import ConversionJobState
from connectors.snowflake_connector import SnowflakeConnector
from core.security import get_cipher
from models import Connection, ConnectionType, ControlPlaneArtifact, ControlPlaneRun
from services.control_plane import (
    ControlPlaneService,
    normalize_status,
    parse_sql_semantic,
    read_artifact_text,
    redact_secrets,
    safe_translate_sql,
    split_sql_statements,
    statement_type,
    utcnow,
)
from services.snowflake_connection import normalize_snowflake_config


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
JINJA_TOKEN_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})", re.S)


def _strip_ansi(value):
    if isinstance(value, str):
        return ANSI_ESCAPE_RE.sub("", value)
    if isinstance(value, list):
        return [_strip_ansi(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_ansi(item) for key, item in value.items()}
    return value


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_./-]+", "_", str(value or "").strip()).strip("_")
    return cleaned or "conversion"


def _strip_quotes(value: str) -> str:
    return str(value or "").strip().strip('"').strip("`").strip("[]")


def _guess_input_type(artifacts: list[ControlPlaneArtifact]) -> str:
    if any(a.artifact_category == "DBT_PROJECT" for a in artifacts):
        return "dbt_project"
    kinds = {a.file_type.lower() for a in artifacts}
    if kinds == {"ddl"}:
        return "ddl_export"
    if any("proc" in a.original_filename.lower() for a in artifacts):
        return "stored_procedure"
    if len(kinds) > 1 or "zip" in kinds:
        return "mixed_zip"
    return "sql_file"


def _build_markdown_warnings(file_reports: list[dict]) -> str:
    lines = ["# Conversion Warnings", ""]
    for report in _dedupe_file_reports(file_reports):
        report = _strip_ansi(report)
        warnings = report.get("warnings") or []
        unsupported = report.get("unsupported_features") or []
        lines.append(f"## {report['source_path']}")
        lines.append("")
        if not warnings and not unsupported:
            lines.append("- No conversion warnings were generated for this file.")
        for item in warnings:
            lines.append(f"- WARN: {item}")
        for item in unsupported:
            lines.append(f"- REVIEW: {item}")
        lines.append("")
    if len(lines) == 2:
        lines.extend(["No conversion warnings were generated.", ""])
    return "\n".join(lines).strip() + "\n"


def _build_csv_rows(file_reports: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "source_path",
            "target_path",
            "detected_dialect",
            "conversion_status",
            "manual_review_required",
            "confidence_score",
            "rules_applied",
            "warnings",
            "unsupported_features",
        ],
    )
    writer.writeheader()
    for report in _dedupe_file_reports(file_reports):
        report = _strip_ansi(report)
        writer.writerow(
            {
                "source_path": report["source_path"],
                "target_path": report["target_path"],
                "detected_dialect": report["detected_dialect"],
                "conversion_status": report["conversion_status"],
                "manual_review_required": str(report["manual_review_required"]).lower(),
                "confidence_score": report["confidence_score"],
                "rules_applied": "; ".join(report.get("rules_applied") or []),
                "warnings": "; ".join(report.get("warnings") or []),
                "unsupported_features": "; ".join(report.get("unsupported_features") or []),
            }
        )
    return buffer.getvalue()


def _score_detection(top_score: int, total_score: int) -> int:
    if top_score <= 0 or total_score <= 0:
        return 0
    return max(1, min(100, int((top_score / total_score) * 100)))


def _dedupe_file_reports(file_reports: list[dict]) -> list[dict]:
    reports_by_source: dict[str, dict] = {}
    for report in file_reports:
        reports_by_source[report["source_path"]] = report
    return list(reports_by_source.values())


def _conversion_status(converted: dict) -> str:
    if converted.get("judge_status") == "failed" and (
        converted.get("copied_source_sql")
        or converted.get("rules_applied_count", len(converted.get("rules_applied") or [])) == 0
        or converted.get("parser_failed")
        or converted.get("dbt_jinja_corrupted")
    ):
        return "FAILED"
    if converted.get("manual_review_required") or converted.get("unsupported_features") or converted.get("source_residue"):
        return "REQUIRES_REVIEW"
    if converted.get("warnings"):
        return "CONVERTED_WITH_WARNINGS"
    return "COMPLETED"


def _job_status_from_reports(file_reports: list[dict]) -> str:
    if not file_reports:
        return "failed"
    statuses = {str(row.get("conversion_status") or "").upper() for row in file_reports}
    if statuses <= {"COMPLETED"}:
        return "converted"
    if "FAILED" in statuses and len(statuses) == 1:
        return "failed"
    if "REQUIRES_REVIEW" in statuses or "FAILED" in statuses:
        return "requires_review"
    if "CONVERTED_WITH_WARNINGS" in statuses:
        return "converted_with_warnings"
    return "requires_review"


def _normalize_sql_for_compare(sql: str) -> str:
    text = re.sub(r"--.*?$", "", sql or "", flags=re.M)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"[;\"`]", "", text)
    return text


def _nearly_identical(left: str, right: str) -> bool:
    norm_left = _normalize_sql_for_compare(left)
    norm_right = _normalize_sql_for_compare(right)
    if not norm_left or not norm_right:
        return False
    if norm_left == norm_right:
        return True
    return difflib.SequenceMatcher(None, norm_left, norm_right).ratio() >= 0.98


def _has_meaningful_conversion_rules(rules_applied: list[str]) -> bool:
    ignored = {"parser_translation_skipped_for_bigquery_dbt"}
    return any(rule not in ignored for rule in rules_applied or [])


def _diff_summary(source_sql: str, converted_sql: str) -> dict:
    source_lines = (source_sql or "").splitlines()
    converted_lines = (converted_sql or "").splitlines()
    diff_lines = list(difflib.unified_diff(source_lines, converted_lines, fromfile="source", tofile="converted", lineterm=""))
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return {
        "source_lines": len(source_lines),
        "converted_lines": len(converted_lines),
        "changed_lines": added + removed,
        "added_lines": added,
        "removed_lines": removed,
        "diff": "\n".join(diff_lines[:400]),
    }


def _jinja_corrupted(source_sql: str, converted_sql: str) -> tuple[bool, list[str]]:
    source_body = source_sql or ""
    while True:
        match = JinjaProtector.CONFIG_RE.match(source_body)
        if not match:
            break
        source_body = source_body[match.end() :]
    source_tokens = sorted(set(JINJA_TOKEN_RE.findall(source_body)))
    missing = [token for token in source_tokens if token not in (converted_sql or "")]
    corrupted = bool(missing) or "UMA_JINJA_" in (converted_sql or "")
    return corrupted, missing


def _scan_source_residue(sql: str, detected: str) -> list[str]:
    if (detected or "").lower() == "bigquery":
        return BigQueryAdapter().residue(sql)
    return []


def _parser_errors(unsupported: list[str]) -> list[str]:
    return [item for item in unsupported if "parser-backed translation failed" in item.lower() or "parse" in item.lower()]


def _state_from_report(run: ControlPlaneRun, report: dict, artifacts: dict | None = None) -> dict:
    file_reports = _dedupe_file_reports(report.get("file_reports") or [])
    source_residue = sorted({item for row in file_reports for item in row.get("source_residue", [])})
    warnings = sorted({item for row in file_reports for item in row.get("warnings", [])})
    unsupported = sorted({item for row in file_reports for item in row.get("unsupported_features", [])})
    errors = sorted({item for row in file_reports for item in row.get("errors", [])})
    rules = sorted({item for row in file_reports for item in row.get("rules_applied", [])})
    readiness_reasons = [
        reason
        for row in file_reports
        for reason in row.get("readiness_reasons", [])
    ]
    judge_statuses = {row.get("judge_status") for row in file_reports if row.get("judge_status")}
    snowflake_ready = bool(file_reports) and all(row.get("snowflake_ready") is True for row in file_reports)
    manual_review_required = any(row.get("manual_review_required") for row in file_reports) or not snowflake_ready
    state = ConversionJobState(
        job_id=run.id,
        status=report.get("status") or _job_status_from_reports(file_reports),
        source_dialect=report.get("source_dialect") or run.source_dialect or "auto_detect",
        target_dialect=report.get("target_dialect") or run.target_dialect or "snowflake",
        input_type=report.get("input_type") or (run.config_json or {}).get("input_type") or "sql_file",
        total_files=len(file_reports),
        converted_files_count=sum(1 for row in file_reports if row.get("conversion_status") in {"COMPLETED", "CONVERTED_WITH_WARNINGS"}),
        failed_files_count=sum(1 for row in file_reports if row.get("conversion_status") == "FAILED"),
        requires_review_count=sum(1 for row in file_reports if row.get("conversion_status") == "REQUIRES_REVIEW"),
        rules_applied_count=len(rules),
        judge_status="failed" if "failed" in judge_statuses else "passed_with_warnings" if "passed_with_warnings" in judge_statuses else "passed" if judge_statuses else "not_run",
        snowflake_ready=snowflake_ready,
        manual_review_required=manual_review_required,
        source_residue=source_residue,
        warnings=warnings,
        errors=errors,
        unsupported_features=unsupported,
        readiness_reasons=readiness_reasons,
        ai_provider_configured=bool(report.get("ai_provider_configured", False)),
        ai_provider_name=report.get("ai_provider_name") or report.get("llm_provider") or "offline",
        ai_model_name=report.get("ai_model_name") or "offline",
        ai_review_available=bool(report.get("ai_review_available", report.get("llm_available", False))),
        ai_patch_available=bool(report.get("ai_patch_available", report.get("llm_available", False))),
        validation_status=(report.get("validation") or {}).get("validation_status") or report.get("validation_status") or "not_run",
        validation_required=not bool((report.get("validation") or {}).get("validation_passed")),
        artifacts=artifacts or {},
        diff_summary={
            "changed_lines": sum((row.get("diff_summary") or {}).get("changed_lines", 0) for row in file_reports),
            "files": [
                {
                    "source_path": row.get("source_path"),
                    "target_path": row.get("target_path"),
                    "changed_lines": (row.get("diff_summary") or {}).get("changed_lines", 0),
                }
                for row in file_reports
            ],
        },
    )
    return state.model_dump()


def _validation_gate_passed(summary: dict) -> bool:
    validation = summary.get("validation") or {}
    status = validation.get("validation_status") or summary.get("validation_status")
    return bool(
        validation.get("validation_passed")
        and status in {"validation_passed", "waived_by_brain_review"}
        and validation.get("dbt_compile_passed") is not False
    )


def _split_args(arg_text: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    for idx, ch in enumerate(arg_text):
        if ch == "'" and not in_double and not _is_backslash_escaped(arg_text, idx):
            in_single = not in_single
        elif ch == '"' and not in_single and not _is_backslash_escaped(arg_text, idx):
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth:
                depth -= 1
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
                continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _is_backslash_escaped(text: str, idx: int) -> bool:
    slash_count = 0
    pos = idx - 1
    while pos >= 0 and text[pos] == "\\":
        slash_count += 1
        pos -= 1
    return slash_count % 2 == 1


def _replace_backtick_identifiers_outside_strings(text: str) -> tuple[str, int]:
    pieces: list[str] = []
    idx = 0
    changed = 0
    in_single = False
    in_double = False
    while idx < len(text):
        ch = text[idx]
        if ch == "'" and not in_double and not _is_backslash_escaped(text, idx):
            in_single = not in_single
            pieces.append(ch)
            idx += 1
            continue
        if ch == '"' and not in_single and not _is_backslash_escaped(text, idx):
            in_double = not in_double
            pieces.append(ch)
            idx += 1
            continue
        if ch == "`" and not in_single and not in_double:
            end = text.find("`", idx + 1)
            if end != -1:
                inner = text[idx + 1 : end]
                if re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){1,2}", inner):
                    pieces.append(".".join(f'"{part}"' for part in inner.split(".")))
                    changed += 1
                    idx = end + 1
                    continue
        pieces.append(ch)
        idx += 1
    return "".join(pieces), changed


def _replace_raw_string_prefixes(text: str) -> tuple[str, int]:
    pieces: list[str] = []
    idx = 0
    changed = 0
    in_single = False
    in_double = False
    while idx < len(text):
        ch = text[idx]
        if ch == "'" and not in_double and not _is_backslash_escaped(text, idx):
            in_single = not in_single
            pieces.append(ch)
            idx += 1
            continue
        if ch == '"' and not in_single and not _is_backslash_escaped(text, idx):
            in_double = not in_double
            pieces.append(ch)
            idx += 1
            continue
        if not in_single and not in_double and ch.lower() == "r" and idx + 1 < len(text) and text[idx + 1] in {"'", '"'}:
            prev = text[idx - 1] if idx else " "
            if not (prev.isalnum() or prev == "_"):
                quote = text[idx + 1]
                end = idx + 2
                while end < len(text):
                    if text[end] == quote and not _is_backslash_escaped(text, end):
                        break
                    end += 1
                if end < len(text):
                    content = text[idx + 2 : end]
                    content = content.replace(f"\\{quote}", quote).replace("'", "''")
                    pieces.append(f"'{content}'")
                    changed += 1
                    idx = end + 1
                    continue
                changed += 1
                idx += 1
                continue
        pieces.append(ch)
        idx += 1
    return "".join(pieces), changed


def _rewrite_split_ordinal(text: str) -> tuple[str, int]:
    pattern = re.compile(r"\bsplit\s*\(", re.I)
    pieces: list[str] = []
    pos = 0
    changed = 0
    while True:
        match = pattern.search(text, pos)
        if not match:
            pieces.append(text[pos:])
            break
        start_args = match.end()
        depth = 1
        idx = start_args
        in_single = False
        in_double = False
        while idx < len(text):
            ch = text[idx]
            if ch == "'" and not in_double and not _is_backslash_escaped(text, idx):
                in_single = not in_single
            elif ch == '"' and not in_single and not _is_backslash_escaped(text, idx):
                in_double = not in_double
            elif not in_single and not in_double:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
            idx += 1
        if depth:
            pieces.append(text[pos:])
            break
        ordinal_match = re.match(r"\s*\[\s*ordinal\s*\(\s*(\d+)\s*\)\s*\]", text[idx + 1 :], re.I)
        if not ordinal_match:
            pieces.append(text[pos : idx + 1])
            pos = idx + 1
            continue
        args = _split_args(text[start_args:idx])
        if len(args) < 2:
            pieces.append(text[pos : idx + 1])
            pos = idx + 1
            continue
        pieces.append(text[pos : match.start()])
        pieces.append(f"SPLIT_PART({args[0]}, {args[1]}, {ordinal_match.group(1)})")
        pos = idx + 1 + ordinal_match.end()
        changed += 1
    return "".join(pieces), changed


def _rewrite_known_flatten_aliases(text: str) -> tuple[str, int]:
    updated = text
    changed = 0
    struct_aliases = ("address", "em")
    for alias in struct_aliases:
        if not re.search(rf"\bFLATTEN\s*\([^)]*\)\s+AS\s+{re.escape(alias)}\b", updated, re.I):
            continue
        updated, count = re.subn(
            rf"\b{re.escape(alias)}\.([A-Za-z_][\w$]*)\b",
            rf"{alias}.value:\1",
            updated,
        )
        changed += count
    if re.search(r"\bFLATTEN\s*\([^)]*ratePlans[^)]*\)\s+AS\s+rp\b", updated, re.I):
        updated, count = re.subn(r"\brp\.rateCode\b", "rp.value:rateCode", updated)
        changed += count
    scalar_replacements = (
        (r"\bpp\s+raw_id\b", "pp.value raw_id"),
        (r"\bcoalesce\s*\(\s*mpp\s*,", "coalesce(mpp.value,"),
        (r"\border\s+by\s+mpp\b", "order by mpp.value"),
        (r"\bon\s+pid\s*=", "on pid.value="),
        (r"\breservationId\s+as\s+resId\b", "reservationId.value as resId"),
        (r"\bcount\s*\(\s*distinct\s+profiles\s*\)", "count(distinct profiles.value)"),
    )
    for pattern, repl in scalar_replacements:
        updated, count = re.subn(pattern, repl, updated, flags=re.I)
        changed += count
    return updated, changed


def _rewrite_function_calls(text: str, function_name: str, transform, label: str, rules_applied: list[str]) -> str:
    updated = text
    changed_any = False
    for _ in range(10):
        next_text, changed = _rewrite_function_calls_once(updated, function_name, transform)
        updated = next_text
        changed_any = changed_any or changed
        if not changed:
            break
    if changed_any:
        rules_applied.append(label)
    return updated


def _rewrite_function_calls_once(text: str, function_name: str, transform) -> tuple[str, bool]:
    pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(", re.I)
    pieces: list[str] = []
    pos = 0
    changed = False
    while True:
        match = pattern.search(text, pos)
        if not match:
            pieces.append(text[pos:])
            break
        start_args = match.end()
        depth = 1
        idx = start_args
        in_single = False
        in_double = False
        while idx < len(text):
            ch = text[idx]
            if ch == "'" and not in_double and not _is_backslash_escaped(text, idx):
                in_single = not in_single
            elif ch == '"' and not in_single and not _is_backslash_escaped(text, idx):
                in_double = not in_double
            elif not in_single and not in_double:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
            idx += 1
        if depth:
            pieces.append(text[pos:])
            break
        original = text[match.start() : idx + 1]
        replacement = transform(_split_args(text[start_args:idx]))
        pieces.append(text[pos : match.start()])
        pieces.append(replacement or original)
        changed = changed or bool(replacement and replacement != original)
        pos = idx + 1
    return "".join(pieces), changed


def _readiness_reason(category: str, severity: str, message: str, recommended_action: str) -> dict:
    return {
        "category": category,
        "severity": severity,
        "message": message,
        "recommended_action": recommended_action,
    }


def _dbt_semantic_readiness(text: str) -> list[dict]:
    config_match = re.search(r"\{\{\s*config\s*\((.*?)\)\s*\}\}", text, re.I | re.S)
    if not config_match:
        return []
    config_body = config_match.group(1)
    if not re.search(r"materialized\s*=\s*['\"]incremental['\"]", config_body, re.I):
        return []
    has_unique_key = re.search(r"\bunique_key\s*=", config_body, re.I) is not None
    has_incremental_filter = re.search(r"\bis_incremental\s*\(", text, re.I) is not None
    has_incremental_predicates = re.search(r"\bincremental_predicates\s*=", config_body, re.I) is not None
    has_strategy = re.search(r"\bincremental_strategy\s*=", config_body, re.I) is not None
    reasons: list[dict] = []
    if not has_unique_key:
        reasons.append(
            _readiness_reason(
                "dbt_incremental",
                "warning",
                "Incremental model requires review because unique_key was not confirmed.",
                "Add or confirm unique_key and incremental_strategy before Snowflake-ready approval.",
            )
        )
    if not has_incremental_filter and not has_incremental_predicates:
        reasons.append(
            _readiness_reason(
                "dbt_incremental",
                "warning",
                "Incremental model requires review because no is_incremental() filter or incremental_predicates were found.",
                "Add or confirm the incremental filter predicate so Snowflake incremental runs do not reload or duplicate data.",
            )
        )
    if not has_strategy:
        reasons.append(
            _readiness_reason(
                "dbt_incremental",
                "info",
                "Incremental strategy was not confirmed for Snowflake.",
                "Confirm merge/delete+insert strategy and warehouse-specific behavior before approval.",
            )
        )
    if re.search(r"\{\{\s*(source|ref)\s*\(", text, re.I):
        reasons.append(
            _readiness_reason(
                "dbt_mapping",
                "warning",
                "dbt refs/sources were preserved, but source mapping validation has not run.",
                "Validate source and ref mappings against the target Snowflake/dbt project before approval.",
            )
        )
    custom_macros = sorted(set(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)))
    custom_macros = [macro for macro in custom_macros if macro.lower() not in {"config", "ref", "source", "is_incremental"}]
    if custom_macros:
        reasons.append(
            _readiness_reason(
                "dbt_macro",
                "warning",
                "Custom dbt/Jinja macros are present and require semantic review.",
                "Review macro behavior and adapter-specific SQL before Snowflake-ready approval.",
            )
        )
    if re.search(r"\b(partition_by|cluster_by)\s*=", config_body, re.I):
        reasons.append(
            _readiness_reason(
                "dbt_bigquery_config",
                "warning",
                "BigQuery-specific dbt partitioning or clustering config requires Snowflake review.",
                "Map partition_by/cluster_by behavior to Snowflake clustering or remove unsupported config.",
            )
        )
    reasons.append(
        _readiness_reason(
            "snowflake_validation",
            "warning",
            "Snowflake compile validation has not run.",
            "Run dbt compile or static project validation against the Snowflake target before marking this model Snowflake-ready.",
        )
    )
    return reasons


def _dbt_incremental_warnings(text: str) -> list[str]:
    return [reason["message"] for reason in _dbt_semantic_readiness(text)]


def _quote_dbt_hook_strings(block: str) -> str:
    return re.sub(
        r"\b(pre_hook|post_hook)\s*=\s*'([^']*)'",
        lambda m: f'{m.group(1)}="{m.group(2)}"',
        block,
        flags=re.I | re.S,
    )


@dataclass
class ProtectedSql:
    sql: str
    tokens: dict[str, str]
    config_blocks: list[str]


class JinjaProtector:
    TOKEN_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})", re.S)
    CONFIG_RE = re.compile(r"\A(?P<prefix>\s*)(?P<config>\{\{\s*config\s*\(.*?\)\s*\}\})\s*", re.I | re.S)

    @classmethod
    def protect(cls, text: str) -> ProtectedSql:
        tokens: dict[str, str] = {}
        config_blocks: list[str] = []
        working = text

        while True:
            match = cls.CONFIG_RE.match(working)
            if not match:
                break
            config_blocks.append(match.group("config"))
            working = working[match.end() :]

        def replace(match: re.Match[str]) -> str:
            token = f"UMA_JINJA_{len(tokens)}"
            tokens[token] = match.group(0)
            original = match.group(0)
            if original.startswith("{%") or original.startswith("{#"):
                return f"/* {token} */"
            return token

        return ProtectedSql(cls.TOKEN_RE.sub(replace, working), tokens, config_blocks)

    @staticmethod
    def restore(text: str, tokens: dict[str, str]) -> str:
        restored = text
        # Restore longer placeholders first so UMA_JINJA_1 does not partially
        # replace UMA_JINJA_10 and leave broken suffixes such as source(...)}}0.
        for token, original in sorted(tokens.items(), key=lambda item: len(item[0]), reverse=True):
            restored = restored.replace(token, original)
            restored = restored.replace(f'"{token}"', original)
            restored = restored.replace(f"/* {token} */", original)
        return restored

    @staticmethod
    def restore_config(text: str, config_blocks: list[str]) -> str:
        body = text.strip()
        if not config_blocks:
            return body + ("\n" if body else "")
        return "\n".join(config_blocks).strip() + "\n" + (body + "\n" if body else "")


@dataclass
class DetectionResult:
    dialect: str
    confidence: int
    reasons: list[str]
    scores: dict[str, int]


@dataclass
class RewriteResult:
    sql: str
    rules_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_features: list[str] = field(default_factory=list)


class SourceDialectAdapter:
    name = "generic_ansi"
    aliases = ("generic_ansi", "ansi")
    sqlglot_name = None
    detection_patterns: tuple[tuple[str, str, int], ...] = ()
    warning_patterns: tuple[tuple[str, str], ...] = ()

    def detect(self, text: str) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        for reason, pattern, weight in self.detection_patterns:
            if re.search(pattern, text, re.I | re.M):
                score += weight
                reasons.append(reason)
        return score, reasons

    def _replace(self, text: str, pattern: str, repl: str, label: str, rules_applied: list[str]) -> str:
        updated, count = re.subn(pattern, repl, text, flags=re.I | re.M)
        if count:
            rules_applied.append(label)
        return updated

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        rules_applied: list[str] = []
        warnings: list[str] = []
        unsupported: list[str] = []
        updated = sql
        for pattern, warning in self.warning_patterns:
            if re.search(pattern, updated, re.I | re.M):
                warnings.append(warning)
        return RewriteResult(updated, rules_applied, warnings, unsupported)

    def classify_procedure(self, sql: str) -> dict:
        lowered = sql.lower()
        complexity = "simple"
        if re.search(r"\b(loop|cursor|while|for|exception|try|catch|dynamic sql|execute immediate|sp_executesql)\b", lowered):
            complexity = "complex"
        elif re.search(r"\b(if|begin|declare|return|set)\b", lowered):
            complexity = "moderate"
        recommendation = "Snowflake Scripting"
        if complexity == "complex":
            recommendation = "Manual rewrite to Snowflake Scripting or Snowpark Python"
        return {
            "complexity": complexity,
            "recommendation": recommendation,
        }


class BigQueryAdapter(SourceDialectAdapter):
    name = "bigquery"
    aliases = ("bigquery", "bq")
    sqlglot_name = "bigquery"
    detection_patterns = (
        ("Backticked project.dataset.table identifiers detected", r"`[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`", 40),
        ("TIMESTAMP_TRUNC detected", r"\btimestamp_trunc\s*\(", 30),
        ("DATETIME_ADD detected", r"\bdatetime_add\s*\(", 30),
        ("DATETIME_SUB detected", r"\bdatetime_sub\s*\(", 30),
        ("DATE_SUB detected", r"\bdate_sub\s*\(", 30),
        ("DATE_ADD detected", r"\bdate_add\s*\(", 30),
        ("BigQuery INTERVAL expression detected", r"\binterval\s+-?\d+\s+(day|month|quarter|year|hour|minute|second)\b", 20),
        ("TIME(hour, minute, second) constructor detected", r"\btime\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)", 20),
        ("dbt source/ref macro detected", r"\{\{\s*(source|ref)\s*\(", 15),
        ("SAFE_CAST detected", r"\bsafe_cast\s*\(", 25),
        ("UNNEST detected", r"\bunnest\s*\(", 25),
        ("STRUCT or ARRAY constructor detected", r"\b(struct|array)\s*[<(]", 20),
    )
    warning_patterns = (
        (r"\bunnest\s*\(", "BigQuery UNNEST logic needs human review for Snowflake FLATTEN semantics."),
        (r"\b(struct|array)\s*[<(]", "BigQuery STRUCT/ARRAY usage may need Snowflake VARIANT or FLATTEN rewrites."),
    )

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        result = super().rewrite(sql, input_type)
        result.sql = _rewrite_function_calls(
            result.sql,
            "TIMESTAMP_TRUNC",
            self._rewrite_timestamp_trunc,
            "TIMESTAMP_TRUNC->DATE_TRUNC",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATE_TRUNC",
            lambda args: f"DATE_TRUNC('{args[1].upper()}', {args[0]})" if len(args) >= 2 and args[1].upper() in {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"} else None,
            "DATE_TRUNC_argument_order",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATETIME_ADD",
            self._rewrite_datetime_add,
            "DATETIME_ADD_DATETIME_INTERVAL_MONTH->DATEADD",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATE_SUB",
            self._rewrite_date_sub,
            "DATE_SUB_INTERVAL_DAY->DATEADD",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATE_ADD",
            self._rewrite_date_add,
            "DATE_ADD_INTERVAL_DAY->DATEADD",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATETIME_SUB",
            self._rewrite_datetime_sub,
            "DATETIME_SUB_INTERVAL->DATEADD",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATETIME",
            lambda args: args[0] if len(args) == 1 else None,
            "DATETIME_single_arg_removed",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "TIMESTAMP_SECONDS",
            lambda args: f"TO_TIMESTAMP({args[0]})" if args else None,
            "TIMESTAMP_SECONDS->TO_TIMESTAMP",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "TIMESTAMP_MILLIS",
            lambda args: f"TO_TIMESTAMP({args[0]} / 1000)" if args else None,
            "TIMESTAMP_MILLIS->TO_TIMESTAMP",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "TIMESTAMP_MICROS",
            lambda args: f"TO_TIMESTAMP({args[0]} / 1000000)" if args else None,
            "TIMESTAMP_MICROS->TO_TIMESTAMP",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "PARSE_TIMESTAMP",
            self._rewrite_parse_timestamp,
            "PARSE_TIMESTAMP->TO_TIMESTAMP_NTZ",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "TIMESTAMP",
            lambda args: f"TO_TIMESTAMP({args[0]})" if len(args) == 1 else None,
            "TIMESTAMP->TO_TIMESTAMP",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "DATE_DIFF",
            self._rewrite_date_diff,
            "DATE_DIFF->DATEDIFF",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "LAST_DAY",
            lambda args: f"LAST_DAY({args[0]}, 'MONTH')" if len(args) >= 2 and args[1].lower() == "month" else None,
            "LAST_DAY_month->LAST_DAY_MONTH",
            result.rules_applied,
        )
        result.sql = self._replace(
            result.sql,
            r"\btime\s*\(\s*(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)",
            lambda m: f"TIME_FROM_PARTS({int(m.group(1))}, {int(m.group(2))}, {int(m.group(3))})",
            "TIME_parts->TIME_FROM_PARTS",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r"\bdate\s*\(\s*([^)]+?)\s*\)",
            lambda m: f"TO_DATE({m.group(1).strip()})",
            "DATE->TO_DATE",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(result.sql, r"\bsafe_cast\s*\(", "TRY_CAST(", "SAFE_CAST->TRY_CAST", result.rules_applied)
        result.sql = _rewrite_function_calls(
            result.sql,
            "SAFE_DIVIDE",
            lambda args: f"IFF({args[1]} = 0, NULL, {args[0]} / {args[1]})" if len(args) >= 2 else None,
            "SAFE_DIVIDE->IFF_DIVISION",
            result.rules_applied,
        )
        result.sql = self._replace(result.sql, r"\bregexp_contains\s*\(", "REGEXP_LIKE(", "REGEXP_CONTAINS->REGEXP_LIKE", result.rules_applied)
        result.sql = _rewrite_function_calls(
            result.sql,
            "REGEXP_EXTRACT",
            lambda args: f"REGEXP_SUBSTR({args[0]}, {args[1]})" if len(args) >= 2 else None,
            "REGEXP_EXTRACT->REGEXP_SUBSTR",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "SHA256",
            lambda args: f"SHA2({args[0]}, 256)" if args else None,
            "SHA256->SHA2_256",
            result.rules_applied,
        )
        result.sql = _rewrite_function_calls(
            result.sql,
            "STRING_AGG",
            lambda args: f"LISTAGG({args[0]}, ',')" if len(args) == 1 else None,
            "STRING_AGG->LISTAGG",
            result.rules_applied,
        )
        result.sql = self._replace(
            result.sql,
            r"\bcast\s*\(\s*([^)]+?)\s+as\s+string\s*\)",
            lambda m: f"CAST({m.group(1).strip()} AS VARCHAR)",
            "CAST_STRING->CAST_VARCHAR",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r"\bcast\s*\(\s*([^)]+?)\s+as\s+int64\s*\)",
            lambda m: f"CAST({m.group(1).strip()} AS NUMBER)",
            "CAST_INT64->CAST_NUMBER",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r"\bcast\s*\(\s*([^)]+?)\s+as\s+float64\s*\)",
            lambda m: f"CAST({m.group(1).strip()} AS FLOAT)",
            "CAST_FLOAT64->CAST_FLOAT",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(result.sql, r"\bas\s+int64\b", "AS NUMBER", "INT64->NUMBER", result.rules_applied)
        result.sql = self._replace(result.sql, r"\bas\s+float64\b", "AS FLOAT", "FLOAT64->FLOAT", result.rules_applied)
        result.sql, split_ordinal_count = _rewrite_split_ordinal(result.sql)
        if split_ordinal_count:
            result.rules_applied.append("SPLIT_ORDINAL->SPLIT_PART")
        result.sql = self._replace(
            result.sql,
            r"(\b(?:[A-Za-z_][\w$]*\.)?\*)\s+except\s*\(([^)]*)\)",
            lambda m: f"{m.group(1)} EXCLUDE ({m.group(2)})",
            "SELECT_STAR_EXCEPT->EXCLUDE",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r"\bunnest\s*\(\s*generate_array\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)\s*\)\s+as\s+([A-Za-z_][\w$]*)",
            lambda m: f"LATERAL (SELECT {m.group(1)} + SEQ4() AS {m.group(3)} FROM TABLE(GENERATOR(ROWCOUNT => {int(m.group(2)) - int(m.group(1)) + 1})))",
            "UNNEST_GENERATE_ARRAY->LATERAL_GENERATOR",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r"\b(left\s+join|cross\s+join|join)\s+unnest\s*\(([^)]+)\)\s+(?:as\s+)?([A-Za-z_][\w$]*)",
            lambda m: f"{m.group(1).upper()} LATERAL FLATTEN(INPUT => {m.group(2).strip()}) AS {m.group(3)} ON TRUE",
            "JOIN_UNNEST->JOIN_LATERAL_FLATTEN",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r",\s*unnest\s*\(([^)]+)\)\s+(?:as\s+)?([A-Za-z_][\w$]*)",
            lambda m: f", LATERAL FLATTEN(INPUT => {m.group(1).strip()}) AS {m.group(2)}",
            "COMMA_UNNEST->LATERAL_FLATTEN",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql = self._replace(
            result.sql,
            r"\b(on|and|where)\s+(.+?)\s+in\s+unnest\s*\(([^)]+)\)",
            lambda m: f"{m.group(1)} ARRAY_CONTAINS(({m.group(2).strip()})::VARIANT, {m.group(3).strip()})",
            "IN_UNNEST->ARRAY_CONTAINS",
            result.rules_applied,
        )  # type: ignore[arg-type]
        result.sql, flatten_alias_count = _rewrite_known_flatten_aliases(result.sql)
        if flatten_alias_count:
            result.rules_applied.append("FLATTEN_aliases->VALUE_access")
        result.sql, backtick_count = _replace_backtick_identifiers_outside_strings(result.sql)
        if backtick_count:
            result.rules_applied.append("backticks->quoted_identifiers")
        result.sql, raw_string_count = _replace_raw_string_prefixes(result.sql)
        if raw_string_count:
            result.rules_applied.append("raw_string_literals->snowflake_strings")
        return result

    @staticmethod
    def _rewrite_timestamp_trunc(args: list[str]) -> str | None:
        if len(args) < 2:
            return None
        part = args[1].strip().upper()
        if part in {"DAY", "MONTH", "QUARTER", "YEAR"}:
            return f"DATE_TRUNC('{part}', {args[0]})"
        if part.startswith("WEEK("):
            return f"DATE_TRUNC('WEEK', {args[0]})"
        return None

    @staticmethod
    def _rewrite_datetime_add(args: list[str]) -> str | None:
        if len(args) < 2:
            return None
        first = args[0].strip()
        interval = re.match(r"interval\s+(-?\d+)\s+(day|month|quarter|year|hour|minute|second)\Z", args[1], re.I)
        datetime_arg = re.match(r"datetime\s*\((.*)\)\Z", first, re.I | re.S)
        if not interval:
            return None
        return f"DATEADD({interval.group(2).upper()}, {interval.group(1)}, {(datetime_arg.group(1).strip() if datetime_arg else first)})"

    @staticmethod
    def _rewrite_date_diff(args: list[str]) -> str | None:
        if len(args) < 3:
            return None
        part = args[2].strip().strip("'\"").upper()
        if part not in {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR", "HOUR", "MINUTE", "SECOND"}:
            return None
        return f"DATEDIFF('{part}', {args[1]}, {args[0]})"

    @classmethod
    def _rewrite_parse_timestamp(cls, args: list[str]) -> str | None:
        if len(args) < 2:
            return None
        return f"TO_TIMESTAMP_NTZ({args[1]}, {cls._bigquery_format_to_snowflake(args[0])})"

    @staticmethod
    def _bigquery_format_to_snowflake(fmt: str) -> str:
        stripped = fmt.strip()
        quote = stripped[0] if stripped[:1] in {"'", '"'} else "'"
        body = stripped[1:-1] if len(stripped) >= 2 and stripped[-1] == quote else stripped.strip("'\"")
        replacements = {
            "%Y": "YYYY",
            "%y": "YY",
            "%m": "MM",
            "%d": "DD",
            "%H": "HH24",
            "%I": "HH12",
            "%M": "MI",
            "%S": "SS",
            "%F": "YYYY-MM-DD",
            "%T": "HH24:MI:SS",
            "%z": "TZHTZM",
            "%Z": "TZD",
        }
        for source, target in replacements.items():
            body = body.replace(source, target)
        return "'" + body.replace("'", "''") + "'"

    @staticmethod
    def _rewrite_date_sub(args: list[str]) -> str | None:
        if len(args) < 2:
            return None
        interval = re.match(r"interval\s+(.+?)\s+(day|month|quarter|year|hour|minute|second)\Z", args[1], re.I)
        if not interval:
            return None
        amount = interval.group(1).strip()
        negated = f"-{amount}" if re.fullmatch(r"\d+", amount) else f"-({amount})"
        return f"DATEADD({interval.group(2).upper()}, {negated}, {args[0]})"

    @staticmethod
    def _rewrite_date_add(args: list[str]) -> str | None:
        if len(args) < 2:
            return None
        interval = re.match(r"interval\s+(.+?)\s+(day|month|quarter|year|hour|minute|second)\Z", args[1], re.I)
        if not interval:
            return None
        return f"DATEADD({interval.group(2).upper()}, {interval.group(1).strip()}, {args[0]})"

    @staticmethod
    def _rewrite_datetime_sub(args: list[str]) -> str | None:
        if len(args) < 2:
            return None
        interval = re.match(r"interval\s+(\d+)\s+(day|month|quarter|year|hour|minute|second)\Z", args[1], re.I)
        if not interval:
            return None
        return f"DATEADD({interval.group(2).upper()}, -{interval.group(1)}, {args[0]})"

    def residue(self, sql: str) -> list[str]:
        checks = (
            ("TIMESTAMP_TRUNC", r"\btimestamp_trunc\s*\("),
            ("TIMESTAMP_SECONDS", r"\btimestamp_seconds\s*\("),
            ("TIMESTAMP_MILLIS", r"\btimestamp_millis\s*\("),
            ("TIMESTAMP_MICROS", r"\btimestamp_micros\s*\("),
            ("PARSE_TIMESTAMP", r"\bparse_timestamp\s*\("),
            ("DATE_DIFF", r"\bdate_diff\s*\("),
            ("DATETIME_ADD", r"\bdatetime_add\s*\("),
            ("DATETIME_SUB", r"\bdatetime_sub\s*\("),
            ("DATE_SUB", r"\bdate_sub\s*\("),
            ("DATE_ADD", r"\bdate_add\s*\("),
            ("SAFE_CAST", r"\bsafe_cast\s*\("),
            ("SAFE_DIVIDE", r"\bsafe_divide\s*\("),
            ("REGEXP_CONTAINS", r"\bregexp_contains\s*\("),
            ("REGEXP_EXTRACT", r"\bregexp_extract\s*\("),
            ("CAST AS STRING", r"\bcast\s*\([^)]*\s+as\s+string\s*\)"),
            ("CAST AS INT64", r"\bcast\s*\([^)]*\s+as\s+int64\s*\)"),
            ("BigQuery backtick identifier", r"`[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){1,2}`"),
            ("BigQuery SELECT * EXCEPT", r"\*\s+except\s*\("),
            ("DATETIME timezone constructor", r"\bdatetime\s*\("),
            ("BigQuery wildcard table suffix", r"\b_table_suffix\b"),
            ("BigQuery FORMAT_TIMESTAMP", r"\bformat_timestamp\s*\("),
            ("BigQuery formatted CAST", r"\bformat\s+'YYYYMMDD'"),
            ("Unsupported DATE_TRUNC WEEK(MONDAY) residue", r"\bdate_trunc\s*\(\s*'MONDAY'\s*,"),
            ("BigQuery DATE_TRUNC argument order", r"\bdate_trunc\s*\(\s*[^,'()]+(?:\([^()]*\)[^,]*)?\s*,\s*(day|week|month|quarter|year)\s*\)"),
            ("BigQuery raw string prefix", r"\br(['\"])"),
            ("BigQuery ORDINAL array offset", r"\[\s*ordinal\s*\("),
            ("TIME(hour, minute, second)", r"\btime\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)"),
            ("STRUCT", r"\bstruct\s*[<(]"),
            ("UNNEST", r"\bunnest\s*\("),
            ("ARRAY syntax", r"\barray\s*[<(]|\[[^\]]+,\s*[^\]]+\]"),
        )
        return [label for label, pattern in checks if re.search(pattern, sql, re.I | re.M)]


class TeradataAdapter(SourceDialectAdapter):
    name = "teradata"
    aliases = ("teradata",)
    sqlglot_name = "teradata"
    detection_patterns = (
        ("QUALIFY detected", r"\bqualify\b", 25),
        ("VOLATILE TABLE detected", r"\bvolatile\s+table\b", 35),
        ("SEL shorthand detected", r"^\s*sel\b", 20),
        ("Teradata FORMAT clause detected", r"\bformat\s+'[^']+'", 20),
    )
    warning_patterns = (
        (r"\bvolatile\s+table\b", "Teradata volatile tables need Snowflake temporary or transient table review."),
        (r"\bprimary\s+index\b|\bfallback\b|\bmultiset\b", "Teradata table options are not portable to Snowflake and require review."),
    )

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        result = super().rewrite(sql, input_type)
        result.sql = self._replace(result.sql, r"^\s*sel\b", "SELECT", "SEL->SELECT", result.rules_applied)
        result.sql = self._replace(result.sql, r"\bvolatile\s+table\b", "TEMPORARY TABLE", "VOLATILE->TEMPORARY", result.rules_applied)
        return result


class DatabricksAdapter(SourceDialectAdapter):
    name = "databricks"
    aliases = ("databricks",)
    sqlglot_name = "databricks"
    detection_patterns = (
        ("USING DELTA detected", r"\busing\s+delta\b", 35),
        ("explode detected", r"\bexplode\s*\(", 20),
        ("Databricks backtick path detected", r"`[^`]+`", 10),
    )
    warning_patterns = (
        (r"\busing\s+delta\b", "Delta Lake storage clauses need Snowflake table/storage redesign."),
        (r"\boptimize\b|\bzorder\b", "Databricks optimization commands are not portable to Snowflake."),
    )

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        result = super().rewrite(sql, input_type)
        result.sql = self._replace(result.sql, r"\busing\s+delta\b", "", "remove_using_delta", result.rules_applied)
        return result


class SparkSqlAdapter(SourceDialectAdapter):
    name = "spark"
    aliases = ("spark", "sparksql", "spark sql")
    sqlglot_name = "spark"
    detection_patterns = (
        ("LATERAL VIEW detected", r"\blateral\s+view\b", 30),
        ("collect_list detected", r"\bcollect_list\s*\(", 20),
        ("array_contains detected", r"\barray_contains\s*\(", 20),
    )
    warning_patterns = (
        (r"\blateral\s+view\b|\bexplode\s*\(", "Spark explode/lateral view patterns need Snowflake FLATTEN review."),
        (r"\bmap<|array<|struct<", "Spark complex nested types require VARIANT/object modeling review."),
    )


class OracleAdapter(SourceDialectAdapter):
    name = "oracle"
    aliases = ("oracle",)
    sqlglot_name = "oracle"
    detection_patterns = (
        ("NVL detected", r"\bnvl\s*\(", 20),
        ("DECODE detected", r"\bdecode\s*\(", 20),
        ("SYSDATE detected", r"\bsysdate\b", 20),
        ("dual table detected", r"\bfrom\s+dual\b", 15),
        ("CONNECT BY detected", r"\bconnect\s+by\b", 30),
    )
    warning_patterns = (
        (r"\bpackage\b|\bexception\b|\bdeclare\b", "Oracle PL/SQL package or block syntax requires manual procedural review."),
        (r"\bconnect\s+by\b", "Oracle hierarchical CONNECT BY logic needs recursive CTE review."),
    )

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        result = super().rewrite(sql, input_type)
        result.sql = self._replace(result.sql, r"\bnvl\s*\(", "COALESCE(", "NVL->COALESCE", result.rules_applied)
        result.sql = self._replace(result.sql, r"\bsysdate\b", "CURRENT_TIMESTAMP", "SYSDATE->CURRENT_TIMESTAMP", result.rules_applied)
        return result


class MySqlAdapter(SourceDialectAdapter):
    name = "mysql"
    aliases = ("mysql",)
    sqlglot_name = "mysql"
    detection_patterns = (
        ("AUTO_INCREMENT detected", r"\bauto_increment\b", 25),
        ("IFNULL detected", r"\bifnull\s*\(", 20),
        ("NOW() detected", r"\bnow\s*\(", 15),
        ("MySQL backticks detected", r"`[^`]+`", 10),
    )
    warning_patterns = (
        (r"\bengine\s*=", "MySQL engine clauses are not portable to Snowflake."),
        (r"\bauto_increment\b", "AUTO_INCREMENT should be reviewed as Snowflake IDENTITY or sequence usage."),
    )

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        result = super().rewrite(sql, input_type)
        result.sql = self._replace(result.sql, r"\bifnull\s*\(", "COALESCE(", "IFNULL->COALESCE", result.rules_applied)
        result.sql = self._replace(result.sql, r"\bnow\s*\(\s*\)", "CURRENT_TIMESTAMP()", "NOW->CURRENT_TIMESTAMP", result.rules_applied)
        result.sql = self._replace(result.sql, r"`([^`]+)`", lambda m: ".".join(f'"{part}"' for part in m.group(1).split(".")), "backticks->quoted_identifiers", result.rules_applied)  # type: ignore[arg-type]
        return result


class SqlServerAdapter(SourceDialectAdapter):
    name = "sqlserver"
    aliases = ("sqlserver", "tsql", "mssql", "sql server")
    sqlglot_name = "tsql"
    detection_patterns = (
        ("TOP clause detected", r"\btop\s+\d+\b", 25),
        ("GETDATE detected", r"\bgetdate\s*\(", 20),
        ("ISNULL detected", r"\bisnull\s*\(", 20),
        ("Square-bracket identifiers detected", r"\[[^\]]+\]", 20),
        ("Temp table detected", r"#[A-Za-z0-9_]+", 20),
    )
    warning_patterns = (
        (r"#[A-Za-z0-9_]+", "SQL Server temp tables require Snowflake temporary table review."),
        (r"\bsp_executesql\b|\bexec\s*\(", "SQL Server dynamic SQL requires manual review."),
    )

    def rewrite(self, sql: str, input_type: str) -> RewriteResult:
        result = super().rewrite(sql, input_type)
        result.sql = self._replace(result.sql, r"\bisnull\s*\(", "COALESCE(", "ISNULL->COALESCE", result.rules_applied)
        result.sql = self._replace(result.sql, r"\bgetdate\s*\(\s*\)", "CURRENT_TIMESTAMP()", "GETDATE->CURRENT_TIMESTAMP", result.rules_applied)
        result.sql = self._replace(result.sql, r"\[([^\]]+)\]", lambda m: f'"{_strip_quotes(m.group(1))}"', "brackets->quoted_identifiers", result.rules_applied)  # type: ignore[arg-type]
        return result


class PostgresAdapter(SourceDialectAdapter):
    name = "postgres"
    aliases = ("postgres", "postgresql")
    sqlglot_name = "postgres"
    detection_patterns = (
        ("Postgres :: cast detected", r"::[A-Za-z_][A-Za-z0-9_]*", 25),
        ("ILIKE detected", r"\bilike\b", 15),
        ("JSONB detected", r"\bjsonb\b|->>|->", 20),
        ("SERIAL detected", r"\bserial\b", 20),
    )
    warning_patterns = (
        (r"\bjsonb\b|->>|->", "Postgres JSONB operator-heavy logic may require Snowflake VARIANT rewrites."),
        (r"\bserial\b", "Postgres SERIAL should be reviewed as Snowflake IDENTITY or sequence usage."),
    )


class HiveAdapter(SourceDialectAdapter):
    name = "hive"
    aliases = ("hive",)
    sqlglot_name = "hive"
    detection_patterns = (
        ("Hive STORED AS detected", r"\bstored\s+as\s+(parquet|orc|textfile)\b", 30),
        ("Hive external table detected", r"\bexternal\s+table\b", 25),
        ("Hive lateral view detected", r"\blateral\s+view\b", 20),
    )
    warning_patterns = (
        (r"\bstored\s+as\s+(parquet|orc|textfile)\b", "Hive storage-format clauses are not portable to Snowflake DDL."),
        (r"\blocation\s+'", "Hive external table locations need Snowflake external stage design review."),
    )


class GenericAnsiAdapter(SourceDialectAdapter):
    name = "generic_ansi"
    aliases = ("generic_ansi", "ansi", "auto_detect")
    sqlglot_name = None


class SnowflakeAdapter:
    def normalize(self, sql: str) -> RewriteResult:
        rules: list[str] = []
        normalized = sql
        replacements = (
            (r"\bvarchar2\b", "VARCHAR", "VARCHAR2->VARCHAR"),
            (r"\bnumber\s*\(", "NUMBER(", "NUMBER-normalized"),
            (r"\bdatetime2\b", "TIMESTAMP_NTZ", "DATETIME2->TIMESTAMP_NTZ"),
        )
        for pattern, repl, label in replacements:
            updated, count = re.subn(pattern, repl, normalized, flags=re.I)
            if count:
                normalized = updated
                rules.append(label)
        normalized, count = re.subn(
            r"\bDATE_TRUNC\s*\(\s*'DATETIME\(([^,]+),\s*\\?'([^'\\]+)\\?'\)'\s*,\s*'(DAY|WEEK|MONTH|QUARTER|YEAR)'\s*\)",
            lambda m: f"DATE_TRUNC('{m.group(3).upper()}', CONVERT_TIMEZONE('UTC', '{m.group(2)}', {m.group(1).lower()}))",
            normalized,
            flags=re.I,
        )
        if count:
            rules.append("DATE_TRUNC_malformed_datetime_post_parser_fix")
        normalized, count = re.subn(
            r"\bDATE_TRUNC\s*\(\s*'([A-Za-z_][A-Za-z0-9_]*)'\s*,\s*'(DAY|WEEK|MONTH|QUARTER|YEAR)'\s*\)",
            lambda m: f"DATE_TRUNC('{m.group(2).upper()}', {m.group(1).lower()})",
            normalized,
            flags=re.I,
        )
        if count:
            rules.append("DATE_TRUNC_post_parser_order_fix")
        normalized, count = re.subn(
            r"\bLAST_DAY\s*\(\s*([^,]+?)\s*,\s*(MONTH|QUARTER|YEAR)\s*\)",
            lambda m: f"LAST_DAY({m.group(1).strip()}, '{m.group(2).upper()}')",
            normalized,
            flags=re.I,
        )
        if count:
            rules.append("LAST_DAY_post_parser_datepart_quote")
        normalized, count = re.subn(
            r"\bDATETIME\s*\(\s*([^,()]+(?:\([^()]*\))?)\s*,\s*'([^']+)'\s*\)",
            lambda m: f"CONVERT_TIMEZONE('UTC', '{m.group(2)}', {m.group(1).strip()})",
            normalized,
            flags=re.I,
        )
        if count:
            rules.append("DATETIME_timezone->CONVERT_TIMEZONE")
        normalized, count = re.subn(r"TO_CHAR\(([^,]+),\s*'%F'\)", r"TO_CHAR(\1, 'YYYY-MM-DD')", normalized, flags=re.I)
        if count:
            rules.append("FORMAT_TIMESTAMP_%F->TO_CHAR_YYYY_MM_DD")
        return RewriteResult(normalized, rules_applied=rules)


ADAPTERS = [
    BigQueryAdapter(),
    TeradataAdapter(),
    DatabricksAdapter(),
    SparkSqlAdapter(),
    OracleAdapter(),
    MySqlAdapter(),
    SqlServerAdapter(),
    PostgresAdapter(),
    HiveAdapter(),
    GenericAnsiAdapter(),
]
ADAPTER_BY_NAME = {alias.lower(): adapter for adapter in ADAPTERS for alias in adapter.aliases}


def _zip_entries(artifact: ControlPlaneArtifact) -> list[str]:
    path = Path(artifact.storage_path)
    if not path.exists():
        return []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return sorted(zf.namelist())
    except Exception:
        return []


def _read_zip_bytes(artifact: ControlPlaneArtifact, name: str) -> bytes:
    with zipfile.ZipFile(Path(artifact.storage_path), "r") as zf:
        return zf.read(name)


DBT_SOURCE_CALL_RE = re.compile(r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.I)


def _dbt_project_slug(value: str | None) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    if not slug:
        return "uma_conversion"
    if re.match(r"^\d", slug):
        slug = f"project_{slug}"
    return slug


def _dbt_model_slug(value: str | None) -> str:
    stem = Path(str(value or "model.sql")).stem
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", stem).strip("_").lower()
    if not slug:
        slug = "model"
    if re.match(r"^\d", slug):
        slug = f"model_{slug}"
    return slug


def _dbt_model_path(run: ControlPlaneRun, source_path: str | None) -> str:
    project_name = _dbt_project_slug((run.config_json or {}).get("dbt_project_name") or run.name)
    return f"models/{project_name}/{_dbt_model_slug(source_path)}.sql"


def _build_dbt_project_yml(run: ControlPlaneRun) -> str:
    config = run.config_json or {}
    project_name = _dbt_project_slug(config.get("dbt_project_name") or run.name)
    profile_name = _dbt_project_slug(config.get("dbt_profile_name") or project_name)
    database = config.get("default_database") or "ANALYTICS"
    schema = config.get("default_schema") or "MARTS"
    materialization = config.get("default_materialization") or "view"
    return "\n".join([
        f"name: {project_name}",
        "version: '1.0.0'",
        "config-version: 2",
        f"profile: {profile_name}",
        "model-paths: ['models']",
        "macro-paths: ['macros']",
        "test-paths: ['tests']",
        "seed-paths: ['seeds']",
        "snapshot-paths: ['snapshots']",
        "",
        "models:",
        f"  {project_name}:",
        f"    +database: {database}",
        f"    +schema: {schema}",
        f"    +materialized: {materialization}",
        "",
    ])


def _build_dbt_packages_yml() -> str:
    return "\n".join([
        "packages: []",
        "",
    ])


def _build_dbt_requirements_txt() -> str:
    return "\n".join([
        "dbt-core>=1.8,<1.9",
        "dbt-snowflake>=1.8,<1.9",
        "",
    ])


def _build_profiles_yml_example(run: ControlPlaneRun) -> str:
    project_name = _dbt_project_slug((run.config_json or {}).get("dbt_profile_name") or (run.config_json or {}).get("dbt_project_name") or run.name)
    return "\n".join([
        f"{project_name}:",
        "  target: dev",
        "  outputs:",
        "    dev:",
        "      type: snowflake",
        "      account: ${SNOWFLAKE_ACCOUNT}",
        "      user: ${SNOWFLAKE_USER}",
        "      password: ${SNOWFLAKE_PASSWORD}",
        "      role: ${SNOWFLAKE_ROLE}",
        "      warehouse: ${SNOWFLAKE_WAREHOUSE}",
        "      database: ${SNOWFLAKE_DATABASE}",
        "      schema: ${SNOWFLAKE_SCHEMA}",
        "      threads: 4",
        "      client_session_keep_alive: false",
        "",
    ])


def _build_sources_yml(file_reports: list[dict]) -> str:
    sources: dict[str, set[str]] = {}
    for row in file_reports:
        for sql_key in ("converted_sql", "original_sql"):
            for source_name, table_name in DBT_SOURCE_CALL_RE.findall(row.get(sql_key) or ""):
                sources.setdefault(source_name, set()).add(table_name)
    lines = ["version: 2", "sources:"]
    if not sources:
        return "version: 2\nsources: []\n"
    for source_name in sorted(sources):
        lines.append(f"  - name: {source_name}")
        lines.append("    tables:")
        for table_name in sorted(sources[source_name]):
            lines.append(f"      - name: {table_name}")
    lines.append("")
    return "\n".join(lines)


def _build_schema_yml(file_reports: list[dict]) -> str:
    lines = ["version: 2", "models:"]
    for row in sorted(file_reports, key=lambda item: item.get("target_path") or item.get("source_path") or ""):
        model_name = _dbt_model_slug(row.get("target_path") or row.get("source_path"))
        status = row.get("conversion_status") or row.get("judge_status") or "requires_review"
        lines.extend([
            f"  - name: {model_name}",
            f"    description: \"Converted by UMA from {Path(row.get('source_path') or model_name).name}. Status: {status}. Review before production use.\"",
        ])
    if len(lines) == 2:
        return "version: 2\nmodels: []\n"
    lines.append("")
    return "\n".join(lines)


def _build_dbt_project_readme(run: ControlPlaneRun, file_reports: list[dict]) -> str:
    project_name = _dbt_project_slug((run.config_json or {}).get("dbt_project_name") or run.name)
    model_count = len([row for row in file_reports if (row.get("converted_sql") or "").strip()])
    return "\n".join([
        f"# {project_name}",
        "",
        "Generated by UMA dbt Conversion.",
        "",
        "This is a review-stage dbt Core project. UMA did not run `dbt run` and did not execute generated models.",
        "",
        "## Local setup",
        "",
        "```bash",
        "python -m venv .venv",
        "source .venv/bin/activate",
        "pip install -r requirements-dbt.txt",
        "dbt deps",
        "dbt compile --profiles-dir .",
        "```",
        "",
        "Populate `profiles.yml` from `profiles.yml.example` or point `DBT_PROFILES_DIR` at your existing profile.",
        "",
        f"Models generated: {model_count}",
        "",
        "Snowflake-ready package promotion still requires Brain Review clearance, dbt compile, and real Snowflake validation.",
        "",
    ])


@dataclass
class SqlToSnowflakeConversionEngine:
    db: AsyncSession

    def __post_init__(self) -> None:
        self.common = ControlPlaneService(self.db)
        self.target = SnowflakeAdapter()

    def adapter_for(self, source_dialect: str | None) -> SourceDialectAdapter:
        return ADAPTER_BY_NAME.get((source_dialect or "").lower(), GenericAnsiAdapter())

    def detect_dialect(self, text: str, requested: str | None = None) -> DetectionResult:
        if requested and requested.lower() not in {"", "auto", "auto_detect"}:
            adapter = self.adapter_for(requested)
            score, reasons = adapter.detect(text)
            confidence = max(65, score or 65)
            return DetectionResult(adapter.name, min(100, confidence), reasons or [f"User selected {adapter.name}"], {adapter.name: score or confidence})

        scores: dict[str, int] = {}
        reasons_by: dict[str, list[str]] = {}
        for adapter in ADAPTERS:
            if isinstance(adapter, GenericAnsiAdapter):
                continue
            score, reasons = adapter.detect(text)
            scores[adapter.name] = score
            reasons_by[adapter.name] = reasons
        best = max(scores.items(), key=lambda item: item[1], default=("generic_ansi", 0))
        if best[1] <= 0:
            return DetectionResult("generic_ansi", 35, ["No dialect-specific signatures matched strongly; using ANSI fallback."], scores)
        return DetectionResult(best[0], _score_detection(best[1], sum(v for v in scores.values() if v > 0) or best[1]), reasons_by.get(best[0], []), scores)

    async def analyze(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> dict:
        job = await self.common.create_job(run.id, "CONVERSION", "ANALYZE")
        inventory = []
        file_reports = []
        for artifact in artifacts:
            if artifact.file_type == "zip" or artifact.artifact_category == "DBT_PROJECT":
                entries = _zip_entries(artifact)
                sample = "\n".join(entries[:80])
                detection = self.detect_dialect(sample, run.source_dialect)
                inventory.append(
                    {
                        "artifact_id": artifact.id,
                        "file_name": artifact.original_filename,
                        "artifact_category": artifact.artifact_category,
                        "entry_count": len(entries),
                        "status": "READY_FOR_OFFLINE_CONVERSION",
                    }
                )
                file_reports.append(
                    {
                        "source_path": artifact.original_filename,
                        "target_path": f"converted/{artifact.original_filename}",
                        "detected_dialect": detection.dialect,
                        "confidence_score": detection.confidence,
                        "detection_reasons": detection.reasons,
                        "conversion_status": "READY",
                        "manual_review_required": artifact.artifact_category != "DBT_PROJECT",
                        "rules_applied": [],
                        "warnings": ["Archive inspection is static; unsupported inner files will be flagged during conversion."] if artifact.artifact_category != "DBT_PROJECT" else [],
                        "unsupported_features": [],
                    }
                )
                continue

            text = redact_secrets(read_artifact_text(artifact))
            detection = self.detect_dialect(text, run.source_dialect)
            adapter = self.adapter_for(detection.dialect)
            rewrite = adapter.rewrite(text, _guess_input_type([artifact]))
            inventory.append(
                {
                    "artifact_id": artifact.id,
                    "file_name": artifact.original_filename,
                    "artifact_category": artifact.artifact_category,
                    "line_count": len(text.splitlines()),
                    "statement_count": len(split_sql_statements(rewrite.sql)) if text.strip() else 0,
                    "status": "READY_FOR_OFFLINE_CONVERSION",
                }
            )
            file_reports.append(
                {
                    "source_path": artifact.original_filename,
                    "target_path": f"converted/{Path(artifact.original_filename).name}",
                    "detected_dialect": detection.dialect,
                    "confidence_score": detection.confidence,
                    "detection_reasons": detection.reasons,
                    "conversion_status": "READY",
                    "manual_review_required": bool(rewrite.warnings or rewrite.unsupported_features),
                    "rules_applied": rewrite.rules_applied,
                    "warnings": rewrite.warnings,
                    "unsupported_features": rewrite.unsupported_features,
                }
            )

        report = {
            "run_id": run.id,
            "status": "uploaded",
            "input_type": (run.config_json or {}).get("input_type") or _guess_input_type(artifacts),
            "source_dialect": run.source_dialect or "auto_detect",
            "target_dialect": "snowflake",
            "inventory": inventory,
            "file_reports": file_reports,
            "next_actions": [
                "Review detected dialects and confidence scores.",
                "Run offline conversion to generate Snowflake SQL and dbt artifacts.",
                "Use optional validation separately after Snowflake credentials are configured.",
            ],
        }
        report["job_state"] = _state_from_report(run, report)
        run.status = "uploaded"
        run.current_phase = "ANALYZED"
        run.summary_json = report
        run.metrics_json = {
            "file_count": len(file_reports),
            "manual_review_items": sum(1 for row in file_reports if row["manual_review_required"]),
        }
        await self.common.store_json_artifact(run.id, "REPORT", "dialect_detection_report.json", {"run_id": run.id, "files": file_reports}, run.created_by)
        await self.common.finish_job(job, "COMPLETED", report)
        await self.db.commit()
        return report

    def _convert_statement(self, stmt: str, adapter: SourceDialectAdapter, target_dialect: str, input_type: str) -> tuple[str, list[str], list[str], bool, list[str]]:
        rewrite = adapter.rewrite(stmt, input_type)
        safe_stmt = rewrite.sql.strip()
        if not safe_stmt:
            return "", rewrite.warnings, rewrite.unsupported_features, False, rewrite.rules_applied
        stype = statement_type(safe_stmt)
        manual_review = bool(rewrite.warnings or rewrite.unsupported_features)
        if stype in {"PROCEDURE", "UDF"} or input_type == "stored_procedure":
            complexity = adapter.classify_procedure(safe_stmt)
            rewrite.unsupported_features.append(
                f"Stored procedure assessment classified as {complexity['complexity']}; recommended target is {complexity['recommendation']}."
            )
            return safe_stmt, rewrite.warnings, rewrite.unsupported_features, True, rewrite.rules_applied

        rules_applied = list(rewrite.rules_applied)
        if isinstance(adapter, BigQueryAdapter):
            output = safe_stmt
            error = None
            rules_applied.append("parser_translation_skipped_for_bigquery_deterministic_rewrite")
        else:
            translated, error = safe_translate_sql(safe_stmt, adapter.sqlglot_name or adapter.name, target_dialect)
            output = translated or safe_stmt
            if translated and translated.strip() != safe_stmt.strip():
                rules_applied.append("parser_translation->snowflake")
            if error:
                manual_review = True
                rewrite.unsupported_features.append(f"Parser-backed translation failed: {error}")
        normalized = self.target.normalize(output)
        rules_applied.extend(normalized.rules_applied)
        return normalized.sql, rewrite.warnings + normalized.warnings, rewrite.unsupported_features, manual_review or bool(normalized.warnings), rules_applied

    def judge_conversion(
        self,
        *,
        source_sql: str,
        converted_sql: str,
        detected_dialect: str,
        rules_applied: list[str],
        warnings: list[str],
        unsupported_features: list[str],
    ) -> dict:
        residue = sorted(set(_scan_source_residue(converted_sql, detected_dialect)))
        parser_errors = _parser_errors(unsupported_features)
        copied_source_sql = _nearly_identical(source_sql, converted_sql) and not _has_meaningful_conversion_rules(rules_applied)
        jinja_corrupted, missing_jinja = _jinja_corrupted(source_sql, converted_sql)
        failures: list[str] = []
        review_items: list[str] = []
        if not (converted_sql or "").strip():
            failures.append("Converted SQL is empty.")
        if not rules_applied:
            failures.append("No deterministic or parser conversion rules were applied.")
        if copied_source_sql:
            failures.append("Converted SQL is identical or nearly identical to the source SQL.")
        if parser_errors:
            failures.extend(parser_errors)
        if jinja_corrupted:
            failures.append("dbt/Jinja macros were corrupted or not preserved.")
        if residue:
            failures.append("Source-dialect residue remains after conversion.")
            review_items.append("Source-dialect residue remains: " + ", ".join(residue) + ".")
        unsupported_without_parser = [item for item in unsupported_features if item not in parser_errors]
        review_items.extend(unsupported_without_parser)
        judge_status = "failed" if failures else "passed_with_warnings" if warnings or review_items else "passed"
        snowflake_ready = judge_status == "passed" and not residue and not review_items
        manual_review_required = bool(failures or review_items or warnings)
        return {
            "judge_status": judge_status,
            "snowflake_ready": snowflake_ready,
            "manual_review_required": manual_review_required,
            "source_residue": residue,
            "errors": sorted(set(failures)),
            "unsupported_features": sorted(set(review_items)),
            "warnings": sorted(set(warnings)),
            "rules_applied_count": len(set(rules_applied)),
            "copied_source_sql": copied_source_sql,
            "parser_failed": bool(parser_errors),
            "dbt_jinja_corrupted": jinja_corrupted,
            "missing_jinja_tokens": missing_jinja,
            "diff_summary": _diff_summary(source_sql, converted_sql),
        }

    def repair_sql_once(self, *, source_sql: str, converted_sql: str, detected_dialect: str, input_type: str) -> dict:
        protected = JinjaProtector.protect(converted_sql or source_sql)
        adapter = self.adapter_for(detected_dialect)
        rewrite = adapter.rewrite(protected.sql, input_type)
        normalized = self.target.normalize(rewrite.sql)
        repaired = JinjaProtector.restore(normalized.sql, protected.tokens)
        repaired = JinjaProtector.restore_config(repaired, protected.config_blocks)
        return {
            "sql": repaired,
            "rules_applied": sorted(set(rewrite.rules_applied + normalized.rules_applied)),
            "warnings": sorted(set(rewrite.warnings + normalized.warnings)),
            "unsupported_features": sorted(set(rewrite.unsupported_features)),
            "changed": _normalize_sql_for_compare(repaired) != _normalize_sql_for_compare(converted_sql),
        }

    def assess_converted_sql(
        self,
        *,
        source_sql: str,
        converted_sql: str,
        detected_dialect: str,
        input_type: str,
        rules_applied: list[str],
        warnings: list[str] | None = None,
        unsupported_features: list[str] | None = None,
    ) -> dict:
        readiness_reasons = _dbt_semantic_readiness(converted_sql or source_sql)
        merged_warnings = sorted(set((warnings or []) + [reason["message"] for reason in readiness_reasons]))
        judge = self.judge_conversion(
            source_sql=source_sql,
            converted_sql=converted_sql,
            detected_dialect=detected_dialect,
            rules_applied=rules_applied,
            warnings=merged_warnings,
            unsupported_features=unsupported_features or [],
        )
        return {
            "readiness_reasons": readiness_reasons,
            "warnings": sorted(set(merged_warnings + judge["warnings"])),
            "unsupported_features": sorted(set((unsupported_features or []) + judge["unsupported_features"])),
            "errors": judge["errors"],
            "judge_status": judge["judge_status"],
            "snowflake_ready": judge["snowflake_ready"] and not readiness_reasons,
            "manual_review_required": judge["manual_review_required"] or bool(readiness_reasons),
            "source_residue": judge["source_residue"],
            "diff_summary": judge["diff_summary"],
            "rules_applied_count": judge["rules_applied_count"],
            "copied_source_sql": judge["copied_source_sql"],
            "parser_failed": judge["parser_failed"],
            "dbt_jinja_corrupted": judge["dbt_jinja_corrupted"],
        }

    def _convert_sql_text(self, text: str, detected: str, input_type: str) -> dict:
        protected = JinjaProtector.protect(text)
        adapter = self.adapter_for(detected)
        statements = split_sql_statements(protected.sql) or [(0, protected.sql, 1, max(1, len(protected.sql.splitlines())))]
        converted_chunks: list[str] = []
        rules_applied: list[str] = []
        warnings: list[str] = []
        unsupported: list[str] = []
        manual_review = False
        for idx, stmt, line_start, line_end in statements:
            converted, stmt_warnings, stmt_unsupported, needs_review, stmt_rules = self._convert_statement(stmt, adapter, "snowflake", input_type)
            if not converted.strip():
                continue
            converted = JinjaProtector.restore(converted, protected.tokens)
            converted_chunks.append(f"-- statement {idx + 1}; source lines {line_start}-{line_end}\n{converted.rstrip(';')};")
            rules_applied.extend(stmt_rules)
            warnings.extend(stmt_warnings)
            unsupported.extend(stmt_unsupported)
            manual_review = manual_review or needs_review
        readiness_reasons = _dbt_semantic_readiness(text)
        warnings.extend(reason["message"] for reason in readiness_reasons)
        config_blocks = protected.config_blocks
        if config_blocks:
            config_blocks = []
            for block in protected.config_blocks:
                rewritten_config = adapter.rewrite(_quote_dbt_hook_strings(block), input_type)
                config_blocks.append(rewritten_config.sql)
                rules_applied.extend([f"config:{rule}" for rule in rewritten_config.rules_applied])
                warnings.extend(rewritten_config.warnings)
                unsupported.extend(rewritten_config.unsupported_features)
        sql = JinjaProtector.restore_config("\n\n".join(converted_chunks), config_blocks)
        if input_type == "dbt_project" and protected.tokens:
            rules_applied.append("dbt_jinja_preserved_for_snowflake")
        if isinstance(adapter, BigQueryAdapter):
            residue = adapter.residue(sql)
            if residue:
                manual_review = True
                unsupported.append("BigQuery source-dialect residue remains after conversion: " + ", ".join(sorted(set(residue))) + ".")
        repair_attempts: list[dict] = []
        judge = self.judge_conversion(
            source_sql=text,
            converted_sql=sql,
            detected_dialect=detected,
            rules_applied=rules_applied,
            warnings=warnings,
            unsupported_features=unsupported,
        )
        while judge["judge_status"] == "failed" and len(repair_attempts) < 2:
            repair = self.repair_sql_once(source_sql=text, converted_sql=sql, detected_dialect=detected, input_type=input_type)
            repair_attempts.append(
                {
                    "attempt": len(repair_attempts) + 1,
                    "changed": repair["changed"],
                    "rules_applied": repair["rules_applied"],
                    "warnings": repair["warnings"],
                    "unsupported_features": repair["unsupported_features"],
                }
            )
            if not repair["changed"]:
                break
            sql = repair["sql"]
            rules_applied.extend(repair["rules_applied"])
            warnings.extend(repair["warnings"])
            unsupported.extend(repair["unsupported_features"])
            judge = self.judge_conversion(
                source_sql=text,
                converted_sql=sql,
                detected_dialect=detected,
                rules_applied=rules_applied,
                warnings=warnings,
                unsupported_features=unsupported,
            )
        if not rules_applied and text.strip():
            unsupported.append("No deterministic conversion rules were applied; output was not marked as successfully converted.")
            judge = self.judge_conversion(
                source_sql=text,
                converted_sql=sql,
                detected_dialect=detected,
                rules_applied=rules_applied,
                warnings=warnings,
                unsupported_features=unsupported,
            )
        manual_review = manual_review or bool(judge["manual_review_required"])
        return {
            "sql": sql,
            "rules_applied": sorted(set(rules_applied)),
            "warnings": sorted(set(warnings + judge["warnings"])),
            "unsupported_features": sorted(set(unsupported + judge["unsupported_features"])),
            "readiness_reasons": readiness_reasons,
            "manual_review_required": manual_review,
            "judge_status": judge["judge_status"],
            "snowflake_ready": judge["snowflake_ready"],
            "source_residue": judge["source_residue"],
            "errors": judge["errors"],
            "diff_summary": judge["diff_summary"],
            "repair_attempts": repair_attempts,
            "copied_source_sql": judge["copied_source_sql"],
            "parser_failed": judge["parser_failed"],
            "dbt_jinja_corrupted": judge["dbt_jinja_corrupted"],
            "missing_jinja_tokens": judge["missing_jinja_tokens"],
            "rules_applied_count": judge["rules_applied_count"],
        }

    def _copy_or_convert_zip(self, artifact: ControlPlaneArtifact, requested_dialect: str | None) -> tuple[dict[str, bytes], list[dict]]:
        files: dict[str, bytes] = {}
        reports: list[dict] = []
        with zipfile.ZipFile(Path(artifact.storage_path), "r") as zf:
            names = sorted(zf.namelist())
            is_dbt = any(name.lower() in {"dbt_project.yml", "dbt_project.yaml"} for name in names)
            input_type = "dbt_project" if is_dbt else "mixed_zip"
            for name in names:
                raw = zf.read(name)
                if name.endswith("/"):
                    continue
                lower = name.lower()
                if is_dbt and not (lower.endswith(".sql") and (lower.startswith("models/") or lower.startswith("snapshots/"))):
                    files[name] = raw
                    continue
                if lower.endswith((".yml", ".yaml", ".md", ".csv", ".json")):
                    files[name] = raw
                    continue
                if not lower.endswith((".sql", ".ddl")):
                    files[name] = raw
                    continue
                text = raw.decode("utf-8", errors="ignore")
                detection = self.detect_dialect(text, requested_dialect)
                converted = self._convert_sql_text(text, detection.dialect, input_type)
                files[name] = converted["sql"].encode("utf-8")
                reports.append(
                    {
                        "source_path": f"{artifact.original_filename}:{name}",
                        "target_path": name,
                        "detected_dialect": detection.dialect,
                        "confidence_score": detection.confidence,
                        "detection_reasons": detection.reasons,
                        "conversion_status": _conversion_status(converted),
                        "converted_file_ready": bool(converted["snowflake_ready"]),
                        "manual_review_required": converted["manual_review_required"],
                        "rules_applied": converted["rules_applied"],
                        "warnings": converted["warnings"],
                        "unsupported_features": converted["unsupported_features"],
                        "readiness_reasons": converted["readiness_reasons"],
                        "errors": converted["errors"],
                        "judge_status": converted["judge_status"],
                        "snowflake_ready": converted["snowflake_ready"],
                        "source_residue": converted["source_residue"],
                        "diff_summary": converted["diff_summary"],
                        "repair_attempts": converted["repair_attempts"],
                        "original_sql": text,
                        "converted_sql": converted["sql"],
                    }
                )
        return files, reports

    async def convert(self, run: ControlPlaneRun, artifacts: list[ControlPlaneArtifact]) -> dict:
        job = await self.common.create_job(run.id, "CONVERSION", "CONVERT")
        output_files: dict[str, bytes] = {}
        file_reports: list[dict] = []
        package_name = f"{_sanitize_name(run.name)}-snowflake-conversion.zip"

        for artifact in artifacts:
            if artifact.file_type == "zip" or artifact.artifact_category == "DBT_PROJECT":
                zip_files, reports = self._copy_or_convert_zip(artifact, run.source_dialect)
                output_files.update(zip_files)
                file_reports.extend(reports)
                continue

            text = redact_secrets(read_artifact_text(artifact))
            detection = self.detect_dialect(text, run.source_dialect)
            converted = self._convert_sql_text(text, detection.dialect, (run.config_json or {}).get("input_type") or _guess_input_type([artifact]))
            target_path = _dbt_model_path(run, artifact.original_filename)
            output_files[target_path] = converted["sql"].encode("utf-8")
            output_files[f"converted/{Path(artifact.original_filename).name}"] = converted["sql"].encode("utf-8")
            conversion_status = _conversion_status(converted)
            file_reports.append(
                {
                    "source_path": artifact.original_filename,
                    "target_path": target_path,
                    "detected_dialect": detection.dialect,
                    "confidence_score": detection.confidence,
                    "detection_reasons": detection.reasons,
                    "conversion_status": conversion_status,
                    "converted_file_ready": bool(converted["snowflake_ready"]),
                    "manual_review_required": converted["manual_review_required"],
                    "rules_applied": converted["rules_applied"],
                    "warnings": converted["warnings"],
                    "unsupported_features": converted["unsupported_features"],
                    "readiness_reasons": converted["readiness_reasons"],
                    "errors": converted["errors"],
                    "judge_status": converted["judge_status"],
                    "snowflake_ready": converted["snowflake_ready"],
                    "source_residue": converted["source_residue"],
                    "diff_summary": converted["diff_summary"],
                    "repair_attempts": converted["repair_attempts"],
                    "original_sql": text,
                    "converted_sql": converted["sql"],
                }
            )
            if conversion_status == "FAILED":
                category = "REVIEW_DBT" if "{{" in text or "{%" in text else "REVIEW_SQL"
                review_path = f"review/{Path(artifact.original_filename).name}"
                await self.common.store_text_artifact(run.id, category, review_path, converted["sql"], run.created_by, "text/sql")
                continue
            category = "GENERATED_DBT" if "{{" in text or "{%" in text else "GENERATED_SQL"
            await self.common.store_text_artifact(run.id, category, target_path, converted["sql"], run.created_by, "text/sql")

        file_reports = _dedupe_file_reports(file_reports)
        severity_counts = {
            "INFO": len(file_reports),
            "WARN": sum(len(row["warnings"]) for row in file_reports),
            "ERROR": sum(len(row["unsupported_features"]) for row in file_reports),
            "FATAL": 0,
        }
        status = _job_status_from_reports(file_reports)
        conversion_report = {
            "run_id": run.id,
            "status": status,
            "input_type": (run.config_json or {}).get("input_type") or _guess_input_type(artifacts),
            "source_dialect": run.source_dialect or "auto_detect",
            "target_platform": "snowflake",
            "target_dialect": "snowflake",
            "manual_review_required": any(row["manual_review_required"] for row in file_reports),
            "file_count": len(file_reports),
            "file_reports": file_reports,
            "executed": False,
            "message": "Offline conversion completed from uploaded artifacts only. UMA did not connect to Snowflake or execute generated SQL.",
        }
        detection_report = {"run_id": run.id, "files": [{k: row[k] for k in ("source_path", "detected_dialect", "confidence_score", "detection_reasons")} for row in file_reports]}
        unsupported_report = {
            "run_id": run.id,
            "items": [
                {
                    "source_path": row["source_path"],
                    "target_path": row["target_path"],
                    "unsupported_features": row["unsupported_features"],
                    "manual_review_required": row["manual_review_required"],
                }
                for row in file_reports
            ],
        }

        conversion_report["file_reports"] = file_reports
        conversion_report["file_count"] = len(file_reports)
        conversion_report["manual_review_required"] = any(row["manual_review_required"] for row in file_reports)
        detection_report = {"run_id": run.id, "files": [{k: row[k] for k in ("source_path", "detected_dialect", "confidence_score", "detection_reasons")} for row in file_reports]}

        job_state = _state_from_report(run, conversion_report)
        conversion_report["job_state"] = job_state
        output_files["conversion_report.json"] = json.dumps(redact_secrets(_strip_ansi(conversion_report)), indent=2, sort_keys=True).encode("utf-8")
        output_files["dialect_detection_report.json"] = json.dumps(redact_secrets(_strip_ansi(detection_report)), indent=2, sort_keys=True).encode("utf-8")
        output_files["unsupported_features.json"] = json.dumps(redact_secrets(_strip_ansi(unsupported_report)), indent=2, sort_keys=True).encode("utf-8")
        output_files["model_conversion_report.csv"] = _build_csv_rows(file_reports).encode("utf-8")
        output_files["conversion_warnings.md"] = _build_markdown_warnings(file_reports).encode("utf-8")
        output_files.setdefault("dbt_project.yml", _build_dbt_project_yml(run).encode("utf-8"))
        output_files.setdefault("packages.yml", _build_dbt_packages_yml().encode("utf-8"))
        output_files.setdefault("requirements-dbt.txt", _build_dbt_requirements_txt().encode("utf-8"))
        output_files.setdefault("profiles.yml.example", _build_profiles_yml_example(run).encode("utf-8"))
        output_files.setdefault("models/sources.yml", _build_sources_yml(file_reports).encode("utf-8"))
        output_files.setdefault("models/schema.yml", _build_schema_yml(file_reports).encode("utf-8"))
        output_files.setdefault("macros/.gitkeep", b"")
        output_files.setdefault("tests/.gitkeep", b"")
        output_files.setdefault("README.md", _build_dbt_project_readme(run, file_reports).encode("utf-8"))

        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, payload in output_files.items():
                zf.writestr(name, payload)
        package_artifact = await self.common.store_binary_artifact(
            run.id,
            "CONVERSION_PACKAGE",
            package_name,
            archive.getvalue(),
            run.created_by,
            "application/zip",
        )
        await self.common.store_json_artifact(run.id, "REPORT", "conversion_report.json", conversion_report, run.created_by)
        await self.common.store_json_artifact(run.id, "REPORT", "dialect_detection_report.json", detection_report, run.created_by)
        await self.common.store_json_artifact(run.id, "REPORT", "unsupported_features.json", unsupported_report, run.created_by)
        await self.common.store_text_artifact(run.id, "REPORT", "model_conversion_report.csv", _build_csv_rows(file_reports), run.created_by, "text/csv")
        await self.common.store_text_artifact(run.id, "REPORT", "conversion_warnings.md", _build_markdown_warnings(file_reports), run.created_by, "text/markdown")

        package_ready = bool(job_state["snowflake_ready"] and _validation_gate_passed(conversion_report))
        artifacts_state = {
            "download_artifact_id": package_artifact.id if package_ready else None,
            "review_package_artifact_id": package_artifact.id if not package_ready else None,
            "package_filename": package_name,
        }
        job_state = _state_from_report(run, conversion_report, artifacts_state)
        if not _validation_gate_passed(conversion_report):
            job_state["snowflake_ready"] = False
            job_state["manual_review_required"] = True
            job_state["status"] = "requires_review"
            job_state["validation_required"] = True
            job_state["readiness_reasons"] = list(job_state.get("readiness_reasons") or []) + [{
                "category": "snowflake_validation",
                "severity": "warning",
                "message": "dbt compile and Snowflake validation have not passed for this package.",
                "recommended_action": "Run Validate/Compile with a Snowflake target profile before downloading the Snowflake-ready package.",
            }]
        conversion_report["job_state"] = job_state
        run.status = job_state["status"]
        run.current_phase = "CONVERTED" if job_state["snowflake_ready"] else "REQUIRES_REVIEW"
        run.completed_at = utcnow()
        run.summary_json = {
            **(run.summary_json or {}),
            **conversion_report,
            "download_artifact_id": package_artifact.id if job_state["snowflake_ready"] and _validation_gate_passed(conversion_report) else None,
            "review_package_artifact_id": package_artifact.id if not (job_state["snowflake_ready"] and _validation_gate_passed(conversion_report)) else None,
        }
        run.metrics_json = {
            "file_count": len(file_reports),
            "warning_count": severity_counts["WARN"],
            "unsupported_count": severity_counts["ERROR"],
        }
        await self.common.finish_job(job, "COMPLETED", conversion_report)
        await self.db.commit()
        return {
            **conversion_report,
            "download_artifact_id": package_artifact.id if job_state["snowflake_ready"] and _validation_gate_passed(conversion_report) else None,
            "review_package_artifact_id": package_artifact.id if not (job_state["snowflake_ready"] and _validation_gate_passed(conversion_report)) else None,
        }

    async def validate(self, run: ControlPlaneRun, target_connection_id: str | None, *, credentials: dict | None = None) -> dict:
        job = await self.common.create_job(run.id, "CONVERSION", "VALIDATE")
        requested_credentials = credentials or {}
        credentials = await self._resolve_snowflake_validation_config(run, target_connection_id, requested_credentials)
        target_connection_id = target_connection_id or run.target_connection_id
        required = ["account", "user", "role", "warehouse", "database", "schema"]
        missing = [key for key in required if not credentials.get(key)]
        if not (credentials.get("password") or credentials.get("authenticator") or credentials.get("auth_method")):
            missing.append("password_or_authenticator")
        summary = run.summary_json or {}
        validation_job = self._validation_job_state(
            run,
            target_connection_id,
            status="not_run",
            validation_mode="SNOWFLAKE_READINESS_AND_EXPLAIN",
        )
        validation_steps = {
            "generate_temporary_dbt_profile": False,
            "dbt_deps": False,
            "dbt_parse": False,
            "dbt_compile": False,
            "dbt_test": False,
            "dbt_run": False,
            "snowflake_connection_readiness": False,
            "snowflake_explain": False,
            "row_sample_validation": False,
        }
        if missing:
            validation_job.update(
                {
                    "status": "credentials_required",
                    "completed_at": utcnow().isoformat(),
                    "errors": [f"Missing Snowflake validation credential: {key}" for key in missing],
                    "readiness_effect": "blocks_package",
                }
            )
            payload = {
                "run_id": run.id,
                "validation_job_id": validation_job["validation_job_id"],
                "validation_status": "credentials_required",
                "status": "NOT_EXECUTED",
                "blocked_reason": "credentials_required",
                "validation_mode": validation_job["validation_mode"],
                "target_connection_id": target_connection_id,
                "missing_credentials": missing,
                "validation_steps": validation_steps,
                "validation_job": validation_job,
                "connection_readiness": [],
                "permission_checks": [],
                "syntax_results": [],
                "snowflake_gate": self._snowflake_gate_payload("credentials_required", "Missing Snowflake target credentials."),
                "compile_errors": [],
                "model_errors": [],
                "warnings": ["Snowflake validation requires explicit credentials and is separate from offline conversion."],
                "validation_passed": False,
                "message": "Snowflake validation was not run because target credentials are incomplete.",
            }
            run.summary_json = self._merge_validation(summary, payload)
            run.current_phase = "VALIDATION_BLOCKED"
            await self.common.store_json_artifact(run.id, "REPORT", "snowflake_validation_report.json", payload, run.created_by)
            await self.common.finish_job(job, "SKIPPED", payload)
            await self.db.commit()
            return payload
        connection_report = await self._run_snowflake_readiness_checks(credentials)
        validation_steps["snowflake_connection_readiness"] = connection_report["status"] == "passed"
        if connection_report["validation_status"] != "connection_ready":
            validation_job.update(
                {
                    "status": connection_report["validation_status"],
                    "completed_at": utcnow().isoformat(),
                    "errors": connection_report.get("errors") or [],
                    "warnings": connection_report.get("warnings") or [],
                    "artifacts": {"connection_readiness": connection_report.get("checks", [])},
                    "readiness_effect": "blocks_package",
                }
            )
            payload = {
                "run_id": run.id,
                "validation_job_id": validation_job["validation_job_id"],
                "validation_status": connection_report["validation_status"],
                "status": "FAILED",
                "blocked_reason": connection_report["validation_status"],
                "validation_mode": validation_job["validation_mode"],
                "target_connection_id": target_connection_id,
                "validation_steps": validation_steps,
                "validation_job": validation_job,
                "connection_readiness": connection_report.get("checks", []),
                "permission_checks": connection_report.get("permission_checks", []),
                "syntax_results": [],
                "snowflake_gate": self._snowflake_gate_payload(connection_report["validation_status"], connection_report["message"]),
                "compile_errors": [],
                "model_errors": [],
                "warnings": connection_report.get("warnings", []),
                "validation_passed": False,
                "dbt_compile_passed": False,
                "snowflake_validation_status": connection_report["validation_status"],
                "message": connection_report["message"],
            }
            run.summary_json = self._merge_validation(summary, payload)
            run.current_phase = "VALIDATION_FAILED"
            await self.common.store_json_artifact(run.id, "VALIDATION_RESULT", "snowflake_connection_readiness.json", payload, run.created_by)
            await self.common.finish_job(job, "FAILED", payload, payload["message"])
            await self.db.commit()
            return payload
        dbt_bin = shutil.which("dbt")
        if not dbt_bin:
            validation_job.update(
                {
                    "status": "validation_failed",
                    "completed_at": utcnow().isoformat(),
                    "errors": ["dbt CLI is not installed in the backend runtime."],
                    "artifacts": {"connection_readiness": connection_report.get("checks", [])},
                    "readiness_effect": "blocks_package",
                }
            )
            payload = {
                "run_id": run.id,
                "validation_job_id": validation_job["validation_job_id"],
                "validation_status": "validation_failed",
                "status": "NOT_EXECUTED",
                "blocked_reason": "tooling_unavailable",
                "validation_mode": validation_job["validation_mode"],
                "target_connection_id": target_connection_id,
                "validation_steps": validation_steps,
                "validation_job": validation_job,
                "connection_readiness": connection_report.get("checks", []),
                "permission_checks": connection_report.get("permission_checks", []),
                "syntax_results": [],
                "snowflake_gate": self._snowflake_gate_payload("validation_failed", "dbt CLI is not installed in the backend runtime."),
                "compile_errors": ["dbt CLI is not installed in the backend runtime."],
                "model_errors": [],
                "warnings": ["Install dbt-snowflake in the validation runtime before running compile validation."],
                "validation_passed": False,
                "message": "Snowflake validation was not run because dbt CLI tooling is unavailable.",
            }
            run.summary_json = self._merge_validation(summary, payload)
            run.current_phase = "VALIDATION_BLOCKED"
            await self.common.store_json_artifact(run.id, "REPORT", "snowflake_validation_report.json", payload, run.created_by)
            await self.common.finish_job(job, "SKIPPED", payload)
            await self.db.commit()
            return payload
        try:
            artifacts = (
                await self.db.execute(select(ControlPlaneArtifact).where(ControlPlaneArtifact.run_id == run.id))
            ).scalars().all()
            with tempfile.TemporaryDirectory(prefix=f"uma-dbt-{run.id[:8]}-") as tmp:
                workspace = Path(tmp) / "project"
                profiles_dir = Path(tmp) / "profiles"
                workspace.mkdir(parents=True, exist_ok=True)
                profiles_dir.mkdir(parents=True, exist_ok=True)
                workspace_summary = self._write_dbt_compile_workspace(workspace, list(artifacts), summary, credentials)
                validation_steps["generate_temporary_dbt_profile"] = True
                if workspace_summary["model_count"] == 0:
                    validation_job.update(
                        {
                            "status": "validation_failed",
                            "completed_at": utcnow().isoformat(),
                            "errors": ["No converted SQL/dbt model artifacts were available to compile."],
                            "artifacts": {"connection_readiness": connection_report.get("checks", [])},
                            "readiness_effect": "blocks_package",
                        }
                    )
                    payload = {
                        "run_id": run.id,
                        "validation_job_id": validation_job["validation_job_id"],
                        "validation_status": "validation_failed",
                        "status": "NOT_EXECUTED",
                        "blocked_reason": "no_dbt_or_sql_models",
                        "validation_mode": validation_job["validation_mode"],
                        "target_connection_id": target_connection_id,
                        "validation_steps": validation_steps,
                        "validation_job": validation_job,
                        "connection_readiness": connection_report.get("checks", []),
                        "permission_checks": connection_report.get("permission_checks", []),
                        "syntax_results": [],
                        "snowflake_gate": self._snowflake_gate_payload("validation_failed", "No converted SQL/dbt model artifacts were available to compile."),
                        "compile_errors": ["No converted SQL/dbt model artifacts were available to compile."],
                        "model_errors": [],
                        "warnings": ["Run conversion before dbt compile validation."],
                        "validation_passed": False,
                        "message": "dbt compile validation was not run because UMA found no converted models.",
                    }
                    run.summary_json = self._merge_validation(summary, payload)
                    run.current_phase = "VALIDATION_BLOCKED"
                    await self.common.store_json_artifact(run.id, "REPORT", "snowflake_validation_report.json", payload, run.created_by)
                    await self.common.finish_job(job, "SKIPPED", payload)
                    await self.db.commit()
                    return payload
                self._write_profiles_yml(profiles_dir / "profiles.yml", credentials)
                env = {**os.environ, "DBT_PROFILES_DIR": str(profiles_dir)}
                commands: list[dict] = []
                if credentials.get("run_dbt_deps") or (workspace / "packages.yml").exists():
                    commands.append(self._run_dbt_command(dbt_bin, ["deps"], workspace, env))
                    validation_steps["dbt_deps"] = commands[-1]["returncode"] == 0
                if credentials.get("run_dbt_parse", True):
                    commands.append(self._run_dbt_command(dbt_bin, ["parse", "--profiles-dir", str(profiles_dir)], workspace, env))
                    validation_steps["dbt_parse"] = commands[-1]["returncode"] == 0
                if credentials.get("run_dbt_compile", True):
                    commands.append(self._run_dbt_command(dbt_bin, ["compile", "--profiles-dir", str(profiles_dir)], workspace, env))
                    validation_steps["dbt_compile"] = commands[-1]["returncode"] == 0
                combined_log = "\n\n".join(
                    f"$ dbt {' '.join(item['args'])}\nreturncode={item['returncode']}\n\nSTDOUT\n{item['stdout']}\n\nSTDERR\n{item['stderr']}"
                    for item in commands
                )
                await self.common.store_text_artifact(run.id, "VALIDATION_RESULT", "dbt_compile.log", combined_log, run.created_by, "text/plain")
                compiled_artifact_id = None
                compiled_bytes = self._zip_compiled_artifacts(workspace / "target" / "compiled")
                if compiled_bytes:
                    compiled_artifact = await self.common.store_binary_artifact(
                        run.id,
                        "VALIDATION_RESULT",
                        "compiled_dbt_artifacts.zip",
                        compiled_bytes,
                        run.created_by,
                        "application/zip",
                    )
                    compiled_artifact_id = compiled_artifact.id
                failed = [item for item in commands if item["returncode"] != 0]
                dbt_compile_passed = not failed
                compiled_entries = self._compiled_sql_entries(workspace / "target" / "compiled")
                if not compiled_entries:
                    compiled_entries = self._workspace_model_sql_entries(workspace / "models")
                syntax_report = {"status": "not_run", "results": [], "errors": [], "warnings": ["EXPLAIN validation did not run because dbt compile failed."]}
                if dbt_compile_passed:
                    syntax_report = await self._run_snowflake_explain_validation(credentials, compiled_entries)
                    validation_steps["snowflake_explain"] = syntax_report["status"] == "passed"
                validation_status = "compile_passed" if dbt_compile_passed and syntax_report["status"] == "not_run" else "validation_passed" if dbt_compile_passed and syntax_report["status"] == "passed" else "validation_failed"
                all_validation_passed = validation_status == "validation_passed"
                optional_validation_warnings = []
                if requested_credentials.get("run_sample_validation") and not requested_credentials.get("approved_sample_validation"):
                    optional_validation_warnings.append("Row/sample validation was requested but not run because explicit approval was not provided.")
                elif requested_credentials.get("run_sample_validation") and requested_credentials.get("approved_sample_validation"):
                    optional_validation_warnings.append("Row/sample validation approval was recorded; use Validation Center with source/target mappings for row count, schema, null, aggregate, and sample-data checks.")
                else:
                    optional_validation_warnings.append("Optional row/sample validation was not run; explicit approval is required for row count, aggregate, null, and sample-data checks.")
                validation_job.update(
                    {
                        "status": validation_status,
                        "completed_at": utcnow().isoformat(),
                        "errors": [item["stderr"] or item["stdout"] for item in failed] + syntax_report.get("errors", []),
                        "warnings": connection_report.get("warnings", []) + syntax_report.get("warnings", []) + optional_validation_warnings,
                        "artifacts": {
                            "compiled_artifact_id": compiled_artifact_id,
                            "connection_readiness": connection_report.get("checks", []),
                            "syntax_result_count": len(syntax_report.get("results", [])),
                        },
                        "readiness_effect": "unlocks_package" if all_validation_passed else "blocks_package",
                    }
                )
                payload = {
                    "run_id": run.id,
                    "validation_job_id": validation_job["validation_job_id"],
                    "validation_status": validation_status,
                    "status": "PASSED" if all_validation_passed else "FAILED",
                    "validation_mode": validation_job["validation_mode"],
                    "target_connection_id": target_connection_id,
                    "workspace": workspace_summary,
                    "validation_steps": validation_steps,
                    "validation_job": validation_job,
                    "connection_readiness": connection_report.get("checks", []),
                    "permission_checks": connection_report.get("permission_checks", []),
                    "syntax_results": syntax_report.get("results", []),
                    "snowflake_gate": {
                        "dbt_compile": "compile_passed" if dbt_compile_passed else "validation_failed",
                        "connection_test": "passed",
                        "permission_check": "passed",
                        "database_schema_warehouse_check": "passed",
                        "explain_validation": "explain_passed" if syntax_report["status"] == "passed" else syntax_report["status"],
                        "selected_model_execution": "not_run",
                        "row_count_sample_validation": "not_run",
                        "message": "dbt compile and Snowflake EXPLAIN validation passed." if all_validation_passed else "dbt compile or Snowflake EXPLAIN validation failed.",
                    },
                    "compile_errors": [item["stderr"] or item["stdout"] for item in failed],
                    "model_errors": syntax_report.get("errors", []),
                    "warnings": connection_report.get("warnings", []) + syntax_report.get("warnings", []) + optional_validation_warnings,
                    "dbt_compile_passed": dbt_compile_passed,
                    "snowflake_validation_status": "explain_passed" if syntax_report["status"] == "passed" else syntax_report["status"],
                    "validation_waived": False,
                    "validation_passed": all_validation_passed,
                    "compiled_artifact_id": compiled_artifact_id,
                    "commands": commands,
                    "message": "Snowflake validation passed: connection, target readiness, permissions, dbt compile, and safe EXPLAIN checks completed." if all_validation_passed else ("dbt compile validation failed." if failed else "Snowflake EXPLAIN validation failed or had no model SQL to validate."),
                }
                run.summary_json = self._merge_validation(summary, payload)
                run.current_phase = "VALIDATED" if all_validation_passed else "VALIDATION_FAILED"
                await self.common.store_json_artifact(run.id, "REPORT", "snowflake_validation_report.json", payload, run.created_by)
                await self.common.store_json_artifact(run.id, "VALIDATION_RESULT", "snowflake_explain_results.json", syntax_report, run.created_by)
                await self.common.finish_job(job, "COMPLETED" if all_validation_passed else "FAILED", payload)
                await self.db.commit()
                return payload
        except Exception as exc:
            validation_job.update(
                {
                    "status": "validation_failed",
                    "completed_at": utcnow().isoformat(),
                    "errors": [str(exc)],
                    "readiness_effect": "blocks_package",
                }
            )
            payload = {
                "run_id": run.id,
                "validation_job_id": validation_job["validation_job_id"],
                "validation_status": "validation_failed",
                "status": "FAILED",
                "validation_mode": validation_job["validation_mode"],
                "target_connection_id": target_connection_id,
                "validation_steps": validation_steps,
                "validation_job": validation_job,
                "connection_readiness": connection_report.get("checks", []) if "connection_report" in locals() else [],
                "permission_checks": connection_report.get("permission_checks", []) if "connection_report" in locals() else [],
                "syntax_results": [],
                "snowflake_gate": self._snowflake_gate_payload("validation_failed", "Snowflake validation raised an exception."),
                "compile_errors": [str(exc)],
                "model_errors": [],
                "warnings": ["Snowflake validation did not complete cleanly."],
                "validation_passed": False,
                "message": "Snowflake validation failed before completion.",
            }
            run.summary_json = self._merge_validation(summary, payload)
            run.current_phase = "VALIDATION_FAILED"
            await self.common.store_json_artifact(run.id, "REPORT", "snowflake_validation_report.json", payload, run.created_by)
            await self.common.finish_job(job, "FAILED", payload, str(exc))
            await self.db.commit()
            return payload

    async def _resolve_snowflake_validation_config(self, run: ControlPlaneRun, target_connection_id: str | None, supplied: dict) -> dict:
        cfg = dict(supplied or {})
        connection_id = target_connection_id or run.target_connection_id
        if connection_id:
            conn = await self.db.get(Connection, connection_id)
            if conn and getattr(conn.type, "value", conn.type) == ConnectionType.snowflake.value:
                stored_credentials = get_cipher().decrypt_dict(conn.credentials) if conn.credentials else {}
                cfg = {**(conn.config or {}), **stored_credentials, **cfg}
        if cfg.get("schema_name") and not cfg.get("schema"):
            cfg["schema"] = cfg.get("schema_name")
        return normalize_snowflake_config(cfg)

    def _validation_job_state(
        self,
        run: ControlPlaneRun,
        connection_id: str | None,
        *,
        status: str,
        validation_mode: str,
    ) -> dict:
        return {
            "validation_job_id": str(uuid4()),
            "run_id": run.id,
            "conversion_job_id": run.id,
            "connection_id": connection_id,
            "status": status,
            "validation_mode": validation_mode,
            "started_at": utcnow().isoformat(),
            "completed_at": None,
            "errors": [],
            "warnings": [],
            "artifacts": {},
            "readiness_effect": "blocks_package",
        }

    async def _run_snowflake_readiness_checks(self, cfg: dict) -> dict:
        return await asyncio.to_thread(self._run_snowflake_readiness_checks_sync, cfg)

    def _run_snowflake_readiness_checks_sync(self, cfg: dict) -> dict:
        checks: list[dict] = []
        permission_checks: list[dict] = []
        errors: list[str] = []
        warnings: list[str] = []

        def record(name: str, status: str, evidence: dict | None = None, error: str | None = None) -> None:
            row = {
                "check": name,
                "status": status,
                "evidence": redact_secrets(evidence or {}),
                "error": redact_secrets(error or ""),
                "checked_at": utcnow().isoformat(),
            }
            checks.append(row)
            if name in {"role_usable", "warehouse_usable", "database_usable", "schema_usable", "create_permission", "read_permission"}:
                permission_checks.append(row)
            if status == "failed" and error:
                errors.append(f"{name}: {error}")

        try:
            with SnowflakeConnector(cfg) as connector:
                metadata = connector.test_connection()
                if not metadata.get("success"):
                    record("account_reachable", "failed", error=metadata.get("diagnostic") or metadata.get("error") or "Snowflake connection failed.")
                    return {
                        "status": "failed",
                        "validation_status": "connection_failed",
                        "checks": checks,
                        "permission_checks": permission_checks,
                        "errors": errors or [metadata.get("error") or "Snowflake connection failed."],
                        "warnings": warnings,
                        "message": metadata.get("diagnostic") or "Snowflake account could not be reached or authenticated.",
                    }
                record("account_reachable", "passed", metadata)
                record("authentication", "passed", {"user": cfg.get("user"), "account": metadata.get("account")})
                self._snowflake_execute(connector, f"USE ROLE {self._quote_snowflake_identifier(cfg['role'])}")
                record("role_usable", "passed", {"role": cfg.get("role")})
                self._snowflake_execute(connector, f"USE WAREHOUSE {self._quote_snowflake_identifier(cfg['warehouse'])}")
                record("warehouse_usable", "passed", {"warehouse": cfg.get("warehouse")})
                self._snowflake_execute(connector, f"USE DATABASE {self._quote_snowflake_identifier(cfg['database'])}")
                record("database_usable", "passed", {"database": cfg.get("database")})
                self._snowflake_execute(connector, f"USE SCHEMA {self._quote_snowflake_identifier(cfg['database'])}.{self._quote_snowflake_identifier(cfg['schema'])}")
                record("schema_usable", "passed", {"database": cfg.get("database"), "schema": cfg.get("schema")})
                tables = self._snowflake_execute(connector, f"SHOW TABLES IN SCHEMA {self._quote_snowflake_identifier(cfg['database'])}.{self._quote_snowflake_identifier(cfg['schema'])}")
                record("read_permission", "passed", {"metadata_rows_visible": len(tables)})
                grants = self._snowflake_execute(connector, f"SHOW GRANTS TO ROLE {self._quote_snowflake_identifier(cfg['role'])}")
                create_ok = self._grants_include_create_on_schema(grants, cfg)
                if create_ok:
                    record("create_permission", "passed", {"role": cfg.get("role"), "grant_rows_checked": len(grants)})
                else:
                    warnings.append("CREATE privilege on the target schema was not visible in SHOW GRANTS evidence.")
                    record(
                        "create_permission",
                        "failed",
                        {"role": cfg.get("role"), "grant_rows_checked": len(grants)},
                        "Target role does not show CREATE TABLE/OWNERSHIP on the target schema.",
                    )
                    return {
                        "status": "failed",
                        "validation_status": "permission_failed",
                        "checks": checks,
                        "permission_checks": permission_checks,
                        "errors": errors,
                        "warnings": warnings,
                        "message": "Snowflake role lacks visible create permission on the target schema.",
                    }
                return {
                    "status": "passed",
                    "validation_status": "connection_ready",
                    "checks": checks,
                    "permission_checks": permission_checks,
                    "errors": [],
                    "warnings": warnings,
                    "message": "Snowflake connection, target, and permission checks passed.",
                }
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if any(token in lowered for token in ("does not exist", "not exist", "cannot be found")):
                status = "target_not_ready"
            elif any(token in lowered for token in ("insufficient privileges", "not authorized", "permission", "privilege")):
                status = "permission_failed"
            else:
                status = "connection_failed" if not checks else "validation_failed"
            record(status, "failed", error=message)
            return {
                "status": "failed",
                "validation_status": status,
                "checks": checks,
                "permission_checks": permission_checks,
                "errors": errors or [message],
                "warnings": warnings,
                "message": message,
            }

    def _snowflake_execute(self, connector: SnowflakeConnector, sql: str) -> list[dict]:
        with connector._cursor() as cur:
            cur.execute(sql)
            try:
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            except Exception:
                return []

    @staticmethod
    def _quote_snowflake_identifier(value: str) -> str:
        cleaned = str(value or "").strip().strip('"')
        if not cleaned or len(cleaned) > 255:
            raise ValueError("Invalid Snowflake identifier.")
        return '"' + cleaned.replace('"', '""') + '"'

    @staticmethod
    def _grants_include_create_on_schema(grants: list[dict], cfg: dict) -> bool:
        target_schema = str(cfg.get("schema") or "").upper()
        target_db = str(cfg.get("database") or "").upper()
        for grant in grants:
            privilege = str(grant.get("privilege") or grant.get("PRIVILEGE") or "").upper()
            granted_on = str(grant.get("granted_on") or grant.get("GRANTED_ON") or "").upper()
            name = str(grant.get("name") or grant.get("NAME") or "").upper()
            if privilege in {"OWNERSHIP", "ALL PRIVILEGES", "CREATE TABLE", "CREATE VIEW"} and granted_on == "SCHEMA":
                if name.endswith(f"{target_db}.{target_schema}") or name == target_schema or name.endswith(f".{target_schema}"):
                    return True
        return False

    def _compiled_sql_entries(self, compiled_dir: Path) -> list[tuple[str, str]]:
        if not compiled_dir.exists():
            return []
        return [
            (path.relative_to(compiled_dir).as_posix(), path.read_text(encoding="utf-8", errors="ignore"))
            for path in sorted(compiled_dir.rglob("*.sql"))
            if path.is_file()
        ]

    def _workspace_model_sql_entries(self, models_dir: Path) -> list[tuple[str, str]]:
        if not models_dir.exists():
            return []
        return [
            (path.relative_to(models_dir).as_posix(), path.read_text(encoding="utf-8", errors="ignore"))
            for path in sorted(models_dir.rglob("*.sql"))
            if path.is_file()
        ]

    async def _run_snowflake_explain_validation(self, cfg: dict, entries: list[tuple[str, str]]) -> dict:
        return await asyncio.to_thread(self._run_snowflake_explain_validation_sync, cfg, entries)

    def _run_snowflake_explain_validation_sync(self, cfg: dict, entries: list[tuple[str, str]]) -> dict:
        results: list[dict] = []
        errors: list[str] = []
        warnings: list[str] = []
        if not entries:
            return {"status": "validation_failed", "results": [], "errors": ["No compiled SQL files were available for EXPLAIN validation."], "warnings": []}
        try:
            with SnowflakeConnector(cfg) as connector:
                self._snowflake_execute(connector, f"USE ROLE {self._quote_snowflake_identifier(cfg['role'])}")
                self._snowflake_execute(connector, f"USE WAREHOUSE {self._quote_snowflake_identifier(cfg['warehouse'])}")
                self._snowflake_execute(connector, f"USE DATABASE {self._quote_snowflake_identifier(cfg['database'])}")
                self._snowflake_execute(connector, f"USE SCHEMA {self._quote_snowflake_identifier(cfg['database'])}.{self._quote_snowflake_identifier(cfg['schema'])}")
                for path, sql in entries:
                    statements = split_sql_statements(sql)
                    if not statements:
                        error = "No SQL statements found in compiled model."
                        errors.append(f"{path}: {error}")
                        results.append({"model": path, "status": "failed", "statement_count": 0, "errors": [error], "warnings": []})
                        continue
                    model_errors: list[str] = []
                    model_warnings: list[str] = []
                    explained = 0
                    for index, statement, line_start, line_end in statements:
                        kind = statement_type(statement)
                        if kind != "SELECT":
                            warning = f"Unsupported for safe EXPLAIN: {kind} statement at lines {line_start}-{line_end}."
                            model_warnings.append(warning)
                            model_errors.append(warning)
                            continue
                        if self._contains_data_changing_sql(statement):
                            warning = f"Data-changing SQL was not explained at lines {line_start}-{line_end}."
                            model_warnings.append(warning)
                            model_errors.append(warning)
                            continue
                        try:
                            self._snowflake_execute(connector, f"EXPLAIN USING TEXT {statement.rstrip(';')}")
                            explained += 1
                        except Exception as exc:
                            model_errors.append(f"EXPLAIN failed at lines {line_start}-{line_end}: {exc}")
                    status = "passed" if explained and not model_errors else "failed"
                    errors.extend(f"{path}: {err}" for err in model_errors)
                    warnings.extend(f"{path}: {warn}" for warn in model_warnings)
                    results.append(
                        {
                            "model": path,
                            "status": status,
                            "statement_count": len(statements),
                            "explained_statements": explained,
                            "errors": model_errors,
                            "warnings": model_warnings,
                        }
                    )
            return {
                "status": "passed" if results and all(row["status"] == "passed" for row in results) else "validation_failed",
                "results": results,
                "errors": errors,
                "warnings": warnings,
            }
        except Exception as exc:
            return {"status": "validation_failed", "results": results, "errors": errors + [str(exc)], "warnings": warnings}

    @staticmethod
    def _contains_data_changing_sql(sql: str) -> bool:
        return bool(re.search(r"\b(insert|update|delete|merge|create|alter|drop|truncate|copy|grant|revoke|call|execute)\b", sql or "", re.I))

    def _write_dbt_compile_workspace(self, workspace: Path, artifacts: list[ControlPlaneArtifact], summary: dict, credentials: dict) -> dict:
        written: list[str] = []
        model_count = 0

        def write_relative(relative: str, text: str) -> None:
            nonlocal model_count
            target = self._safe_dbt_relative_path(relative, default_dir="models")
            path = workspace / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text or "", encoding="utf-8")
            written.append(target)
            if target.endswith(".sql") and target.startswith("models/"):
                model_count += 1

        for artifact in artifacts:
            category = artifact.artifact_category or ""
            name = artifact.original_filename or artifact.filename or ""
            if artifact.file_type == "zip" and category in {"DBT_PROJECT", "CONVERSION_PACKAGE"}:
                model_count += self._extract_dbt_zip_artifact(workspace, artifact, written)
                continue
            if category not in {"GENERATED_DBT", "GENERATED_SQL", "GENERATED_SQL_PATCH", "DBT_PROJECT", "SOURCE_SQL", "SOURCE_DDL"}:
                continue
            if category in {"SOURCE_SQL", "SOURCE_DDL"} and not any(token in name.lower() for token in ("dbt_project.yml", "schema.yml", "sources.yml", "source.yml", "macros/")):
                continue
            text = read_artifact_text(artifact)
            if not text.strip():
                continue
            if category in {"GENERATED_SQL", "GENERATED_SQL_PATCH"} and not name.lower().endswith(".sql"):
                name = f"{Path(name).stem or 'model'}.sql"
            write_relative(name, text)

        for row in (summary.get("conversion_context") or {}).get("files") or summary.get("file_reports") or []:
            converted_sql = row.get("converted_sql") or ""
            if not converted_sql.strip():
                continue
            target_path = row.get("target_path") or row.get("source_path") or f"models/model_{model_count + 1}.sql"
            if target_path not in written:
                write_relative(target_path, converted_sql)

        project_path = workspace / "dbt_project.yml"
        if not project_path.exists():
            project_name = _sanitize_name(credentials.get("project_name") or "uma_conversion").replace("/", "_").replace("-", "_").lower()
            project_path.write_text(
                "\n".join([
                    f"name: {project_name}",
                    "version: '1.0'",
                    "config-version: 2",
                    "profile: uma_validation",
                    "model-paths: ['models']",
                    "macro-paths: ['macros']",
                    "models:",
                    f"  {project_name}:",
                    "    +materialized: view",
                    "",
                ]),
                encoding="utf-8",
            )
            written.append("dbt_project.yml")
        (workspace / "models").mkdir(exist_ok=True)
        (workspace / "macros").mkdir(exist_ok=True)
        return {"path": "[temporary workspace]", "files_written": sorted(set(written)), "model_count": model_count}

    def _safe_dbt_relative_path(self, value: str, *, default_dir: str) -> str:
        raw = str(value or "").replace("\\", "/").strip("/")
        parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
        if not parts:
            parts = ["model.sql"]
        relative = "/".join(parts)
        allowed_roots = {"models", "macros", "seeds", "snapshots", "analyses", "tests"}
        if relative in {"dbt_project.yml", "packages.yml", "schema.yml", "sources.yml", "source.yml"}:
            return relative
        if parts[0] not in allowed_roots:
            relative = f"{default_dir}/{Path(relative).name}"
        return relative

    def _extract_dbt_zip_artifact(self, workspace: Path, artifact: ControlPlaneArtifact, written: list[str]) -> int:
        model_count = 0
        path = Path(artifact.storage_path)
        if not path.exists():
            return model_count
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    safe_name = self._safe_dbt_relative_path(name, default_dir="models")
                    if not safe_name.endswith((".sql", ".yml", ".yaml", ".csv")):
                        continue
                    target = workspace / safe_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(name))
                    written.append(safe_name)
                    if safe_name.startswith("models/") and safe_name.endswith(".sql"):
                        model_count += 1
        except zipfile.BadZipFile:
            return 0
        return model_count

    def _write_profiles_yml(self, path: Path, credentials: dict) -> None:
        lines = [
            "uma_validation:",
            "  target: validate",
            "  outputs:",
            "    validate:",
            "      type: snowflake",
            f"      account: {credentials.get('account')}",
            f"      user: {credentials.get('user')}",
            f"      role: {credentials.get('role')}",
            f"      warehouse: {credentials.get('warehouse')}",
            f"      database: {credentials.get('database')}",
            f"      schema: {credentials.get('schema')}",
            "      threads: 4",
            "      client_session_keep_alive: false",
        ]
        if credentials.get("password"):
            lines.append(f"      password: {credentials.get('password')}")
        if credentials.get("auth_method") and not credentials.get("password"):
            lines.append(f"      authenticator: {credentials.get('auth_method')}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _run_dbt_command(self, dbt_bin: str, args: list[str], cwd: Path, env: dict[str, str]) -> dict:
        completed = subprocess.run(
            [dbt_bin, *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        return {
            "args": args,
            "returncode": completed.returncode,
            "stdout": redact_secrets(_strip_ansi(completed.stdout or "")),
            "stderr": redact_secrets(_strip_ansi(completed.stderr or "")),
        }

    def _zip_compiled_artifacts(self, compiled_dir: Path) -> bytes | None:
        if not compiled_dir.exists():
            return None
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(compiled_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(compiled_dir).as_posix())
        content = buffer.getvalue()
        return content if content else None

    @staticmethod
    def _snowflake_gate_payload(status: str, message: str) -> dict:
        return {
            "dbt_compile": status,
            "connection_test": "not_run",
            "permission_check": "not_run",
            "database_schema_warehouse_check": "not_run",
            "explain_validation": "not_run",
            "selected_model_execution": "approval_required",
            "row_count_sample_validation": "not_run",
            "message": message,
        }

    def _merge_validation(self, summary: dict, validation: dict) -> dict:
        next_summary = {**summary, "validation": validation, "validation_status": validation.get("validation_status")}
        files = (next_summary.get("conversion_context") or {}).get("files") or next_summary.get("file_reports") or []
        validation_passed = bool(validation.get("validation_passed")) and validation.get("validation_status") in {"validation_passed", "waived_by_brain_review"}
        if validation_passed:
            files = [self._clear_validation_reason(row) for row in files]
            if next_summary.get("file_reports"):
                next_summary["file_reports"] = [self._clear_validation_reason(row) for row in next_summary.get("file_reports", [])]
            context = dict(next_summary.get("conversion_context") or {})
            if context.get("files"):
                context["files"] = [self._clear_validation_reason(row) for row in context.get("files", [])]
                next_summary["conversion_context"] = context
        state = dict(next_summary.get("job_state") or {})
        state["validation_status"] = validation.get("validation_status") or "not_run"
        state["validation_required"] = not validation_passed
        state["readiness_reasons"] = [
            reason
            for reason in state.get("readiness_reasons", [])
            if not (validation_passed and reason.get("category") == "snowflake_validation")
        ]
        if files:
            source_residue = sorted({item for row in files for item in row.get("source_residue", [])})
            rules = {item for row in files for item in row.get("rules_applied", [])}
            judge_failed = any(row.get("judge_status") == "failed" for row in files)
            file_ready = all(row.get("snowflake_ready") for row in files)
            semantic_blockers = [reason for row in files for reason in row.get("readiness_reasons", [])]
            state["snowflake_ready"] = bool(validation_passed and file_ready and not source_residue and rules and not judge_failed and not semantic_blockers)
            state["manual_review_required"] = not state["snowflake_ready"]
            state["status"] = "converted" if state["snowflake_ready"] else "requires_review"
            state["source_residue"] = source_residue
            state["rules_applied_count"] = len(rules)
        else:
            state["snowflake_ready"] = False
            state["manual_review_required"] = True
            state["status"] = "requires_review"
        next_summary["job_state"] = state
        if not state.get("snowflake_ready"):
            next_summary["download_artifact_id"] = None
        elif validation_passed and next_summary.get("review_package_artifact_id"):
            next_summary["download_artifact_id"] = next_summary.get("review_package_artifact_id")
            next_summary["review_package_artifact_id"] = None
        return next_summary

    @staticmethod
    def _clear_validation_reason(row: dict) -> dict:
        next_row = dict(row)
        next_row["readiness_reasons"] = [
            reason for reason in next_row.get("readiness_reasons", []) if reason.get("category") != "snowflake_validation"
        ]
        next_row["warnings"] = [
            warning for warning in next_row.get("warnings", []) if "snowflake compile validation has not run" not in str(warning).lower()
        ]
        next_row["manual_review_required"] = bool(next_row.get("readiness_reasons") or next_row.get("warnings") or next_row.get("unsupported_features") or next_row.get("errors"))
        next_row["snowflake_ready"] = not next_row["manual_review_required"] and next_row.get("judge_status") == "passed"
        next_row["conversion_status"] = "COMPLETED" if next_row["snowflake_ready"] else "REQUIRES_REVIEW"
        return next_row
