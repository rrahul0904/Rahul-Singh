from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.security import get_cipher
from models import Connection


class SnowparkUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnowparkTableRef:
    database: str
    schema: str
    table: str


class SnowparkValidationService:
    """Snowpark-backed validation helpers that run aggregate checks in Snowflake."""

    def __init__(self, session):
        self.session = session

    @classmethod
    def from_connection(cls, conn: Connection, database: str | None = None, schema: str | None = None):
        try:
            from snowflake.snowpark import Session
        except Exception as exc:
            raise SnowparkUnavailableError("snowflake-snowpark-python is not installed") from exc

        cipher = get_cipher()
        credentials = cipher.decrypt_dict(conn.credentials) if conn.credentials else {}
        cfg = {**(conn.config or {}), **credentials}
        connection_parameters = {
            "account": cfg.get("account"),
            "user": cfg.get("user") or cfg.get("username"),
            "password": cfg.get("password"),
            "role": cfg.get("role"),
            "warehouse": cfg.get("warehouse"),
            "database": database or cfg.get("database"),
            "schema": schema or cfg.get("schema"),
        }
        safe_parameters = {k: v for k, v in connection_parameters.items() if v}
        return cls(Session.builder.configs(safe_parameters).create())

    @staticmethod
    def q(name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    @classmethod
    def fqn(cls, ref: SnowparkTableRef) -> str:
        return f"{cls.q(ref.database)}.{cls.q(ref.schema)}.{cls.q(ref.table)}"

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def _first_row(self, sql: str) -> dict[str, Any]:
        rows = self.session.sql(sql).collect()
        if not rows:
            return {}
        row = rows[0]
        if hasattr(row, "as_dict"):
            return row.as_dict()
        if isinstance(row, dict):
            return row
        return dict(row)

    @staticmethod
    def _value(row: dict[str, Any], key: str, default: Any = None) -> Any:
        return row.get(key, row.get(key.upper(), default))

    def profile_table(
        self,
        ref: SnowparkTableRef,
        *,
        primary_key_columns: list[str] | None = None,
        watermark_column: str | None = None,
        soft_delete_column: str | None = None,
    ) -> dict[str, Any]:
        table = self.fqn(ref)
        row = self._first_row(f"SELECT COUNT(*) AS ROW_COUNT FROM {table}")
        profile = {"row_count": int(self._value(row, "ROW_COUNT", 0) or 0)}

        desc_rows = self.session.sql(f"DESCRIBE TABLE {table}").collect()
        profile["column_count"] = len(desc_rows)

        if watermark_column:
            wm = self._first_row(
                f"SELECT MIN({self.q(watermark_column)}) AS MIN_WATERMARK, "
                f"MAX({self.q(watermark_column)}) AS MAX_WATERMARK FROM {table}"
            )
            profile["min_watermark"] = self._value(wm, "MIN_WATERMARK")
            profile["max_watermark"] = self._value(wm, "MAX_WATERMARK")

        if primary_key_columns:
            profile["duplicate_primary_key_count"] = self.duplicate_primary_key_count(
                ref, primary_key_columns
            )

        if soft_delete_column:
            deleted = self._first_row(
                f"SELECT COUNT(*) AS SOFT_DELETE_COUNT FROM {table} "
                f"WHERE COALESCE({self.q(soft_delete_column)}, FALSE) = TRUE"
            )
            profile["soft_delete_count"] = int(self._value(deleted, "SOFT_DELETE_COUNT", 0) or 0)

        return profile

    def duplicate_primary_key_count(self, ref: SnowparkTableRef, primary_key_columns: list[str]) -> int:
        if not primary_key_columns:
            return 0
        table = self.fqn(ref)
        cols = ", ".join(self.q(c) for c in primary_key_columns)
        row = self._first_row(
            f"SELECT COUNT(*) AS DUPLICATE_COUNT FROM ("
            f"SELECT {cols}, COUNT(*) AS C FROM {table} GROUP BY {cols} HAVING COUNT(*) > 1"
            f")"
        )
        return int(self._value(row, "DUPLICATE_COUNT", 0) or 0)

    def row_hash(self, ref: SnowparkTableRef, columns: list[str]) -> str:
        if not columns:
            raise ValueError("columns are required for row hash validation")
        table = self.fqn(ref)
        col_expr = ", ".join(self.q(c) for c in columns)
        row = self._first_row(f"SELECT HASH_AGG(HASH({col_expr})) AS ROW_HASH FROM {table}")
        return str(self._value(row, "ROW_HASH", ""))

    def validate_row_count(self, source_count: int, target_ref: SnowparkTableRef) -> dict[str, Any]:
        target_count = self.profile_table(target_ref)["row_count"]
        return {
            "status": "SUCCEEDED" if int(source_count) == int(target_count) else "FAILED",
            "source_value": str(source_count),
            "target_value": str(target_count),
            "delta": int(target_count) - int(source_count),
        }

    def validate_sample_hash(
        self,
        source_hash: str,
        target_ref: SnowparkTableRef,
        columns: list[str],
    ) -> dict[str, Any]:
        target_hash = self.row_hash(target_ref, columns)
        return {
            "status": "SUCCEEDED" if source_hash == target_hash else "FAILED",
            "source_value": source_hash,
            "target_value": target_hash,
            "delta": "matched" if source_hash == target_hash else "mismatch",
        }
