from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DriftFinding:
    drift_type: str
    column_name: str
    source_type: str | None = None
    target_type: str | None = None
    source_nullable: bool | None = None
    target_nullable: bool | None = None
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_type": self.drift_type,
            "column_name": self.column_name,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "source_nullable": self.source_nullable,
            "target_nullable": self.target_nullable,
            "severity": self.severity,
        }


def _normalize_col(col: dict[str, Any]) -> dict[str, Any]:
    name = str(col.get("name") or col.get("COLUMN_NAME") or "").upper()
    type_ = str(col.get("type") or col.get("DATA_TYPE") or "").upper()
    nullable = col.get("nullable")
    if nullable is None:
        nullable = col.get("NULLABLE")
    if isinstance(nullable, str):
        nullable = nullable.upper() in {"YES", "Y", "TRUE", "1"}
    return {"name": name, "type": type_, "nullable": nullable}


def _base_type(type_name: str | None) -> str:
    return (type_name or "").upper().split("(", 1)[0].strip()


def compare_schemas(
    source_columns: list[dict[str, Any]],
    target_columns: list[dict[str, Any]],
) -> list[DriftFinding]:
    source = {
        c["name"]: c
        for c in (_normalize_col(col) for col in source_columns)
        if c["name"] and not c["name"].startswith("_UMA_")
    }
    target = {
        c["name"]: c
        for c in (_normalize_col(col) for col in target_columns)
        if c["name"] and not c["name"].startswith("_UMA_")
    }
    findings: list[DriftFinding] = []
    for name, col in source.items():
        if name not in target:
            findings.append(DriftFinding("added", name, source_type=col["type"], source_nullable=col["nullable"]))
    for name, col in target.items():
        if name not in source:
            findings.append(DriftFinding("removed", name, target_type=col["type"], target_nullable=col["nullable"], severity="error"))
    for name in sorted(set(source) & set(target)):
        src = source[name]
        tgt = target[name]
        if _base_type(src["type"]) != _base_type(tgt["type"]):
            findings.append(DriftFinding(
                "type_changed",
                name,
                source_type=src["type"],
                target_type=tgt["type"],
                source_nullable=src["nullable"],
                target_nullable=tgt["nullable"],
                severity="error",
            ))
        if src["nullable"] is not None and tgt["nullable"] is not None and src["nullable"] != tgt["nullable"]:
            findings.append(DriftFinding(
                "nullable_changed",
                name,
                source_type=src["type"],
                target_type=tgt["type"],
                source_nullable=src["nullable"],
                target_nullable=tgt["nullable"],
                severity="warning",
            ))
    return findings


def additive_alter_statements(
    database: str,
    schema: str,
    table: str,
    findings: list[DriftFinding],
) -> list[str]:
    def q(name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    statements = []
    for finding in findings:
        if finding.drift_type != "added":
            continue
        sf_type = finding.source_type or "VARCHAR"
        statements.append(
            f"ALTER TABLE {q(database)}.{q(schema)}.{q(table)} "
            f"ADD COLUMN IF NOT EXISTS {q(finding.column_name)} {sf_type}"
        )
    return statements
