import os
import re
import sys
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://uma:uma@localhost:5432/uma_test")

from models import ConnectionType, MigrationState  # noqa: E402
from services.real_migration_engine import (  # noqa: E402
    ColumnSpec,
    SqlSourceAdapter,
    TablePlan,
    TableSchema,
    _set_state_last_primary_key,
)


def _adapter():
    adapter = SqlSourceAdapter.__new__(SqlSourceAdapter)
    adapter.conn = object()
    adapter.conn_model = SimpleNamespace(type=ConnectionType.postgres)
    return adapter


class _RecordingCursor:
    def __init__(self, result):
        self.result = result
        self.sql = None
        self.params = None
        self.closed = False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = list(params or [])

    def fetchone(self):
        return [self.result]

    def close(self):
        self.closed = True


class _RecordingConnection:
    def __init__(self, result):
        self.cursor_obj = _RecordingCursor(result)

    def cursor(self):
        return self.cursor_obj


def _read_chunks(chunks):
    frames = [pd.read_parquet(c.file_path) for c in chunks]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def test_incremental_extract_uses_composite_cursor_across_duplicate_watermarks(monkeypatch, tmp_path):
    same_wm = datetime(2026, 1, 1, 12, 0, 0)
    rows = pd.DataFrame(
        [
            {"id": 1, "updated_at": same_wm, "value": "a"},
            {"id": 2, "updated_at": same_wm, "value": "b"},
            {"id": 3, "updated_at": same_wm, "value": "c"},
            {"id": 4, "updated_at": same_wm, "value": "d"},
            {"id": 5, "updated_at": same_wm, "value": "e"},
        ]
    )
    seen_sql = []

    def fake_read_sql_query(sql, _conn, params=None):
        seen_sql.append(sql)
        params = list(params or [])
        filtered = rows.copy()
        if len(params) == 4:
            cursor_wm, _, cursor_pk, end_wm = params
            filtered = filtered[
                (
                    (filtered["updated_at"] > cursor_wm)
                    | ((filtered["updated_at"] == cursor_wm) & (filtered["id"] > cursor_pk))
                )
                & (filtered["updated_at"] <= end_wm)
            ]
        elif len(params) == 1:
            end_wm = params[0]
            filtered = filtered[filtered["updated_at"] <= end_wm]
        limit = int(re.search(r"LIMIT (\d+)", sql).group(1))
        return filtered.sort_values(["updated_at", "id"]).head(limit).reset_index(drop=True)

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    chunks = list(
        _adapter().extract_chunks(
            "",
            "source_table",
            ["id", "updated_at", "value"],
            TablePlan(
                pk_columns=["id"],
                watermark_column="updated_at",
                delete_flag_column=None,
                batch_size=2,
                full_refresh=False,
            ),
            TableSchema(
                [
                    ColumnSpec("id", "integer"),
                    ColumnSpec("updated_at", "timestamp"),
                    ColumnSpec("value", "text"),
                ]
            ),
            None,
            None,
            same_wm,
            tmp_path,
        )
    )

    extracted = _read_chunks(chunks)
    assert extracted["id"].tolist() == [1, 2, 3, 4, 5]
    assert extracted["id"].is_unique
    assert chunks[-1].last_watermark == same_wm
    assert chunks[-1].last_primary_key == 5
    assert any('"updated_at" > %s OR ("updated_at" = %s AND "id" > %s)' in sql for sql in seen_sql)
    assert any('ORDER BY "updated_at" ASC, "id" ASC' in sql for sql in seen_sql)


def test_incremental_extract_rerun_from_composite_cursor_is_idempotent(monkeypatch, tmp_path):
    same_wm = datetime(2026, 1, 1, 12, 0, 0)
    rows = pd.DataFrame(
        [
            {"id": 1, "updated_at": same_wm, "value": "a"},
            {"id": 2, "updated_at": same_wm, "value": "b"},
        ]
    )

    def fake_read_sql_query(_sql, _conn, params=None):
        cursor_wm, _, cursor_pk, end_wm = list(params or [])
        filtered = rows[
            (
                (rows["updated_at"] > cursor_wm)
                | ((rows["updated_at"] == cursor_wm) & (rows["id"] > cursor_pk))
            )
            & (rows["updated_at"] <= end_wm)
        ]
        return filtered.reset_index(drop=True)

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    chunks = list(
        _adapter().extract_chunks(
            "",
            "source_table",
            ["id", "updated_at", "value"],
            TablePlan(
                pk_columns=["id"],
                watermark_column="updated_at",
                delete_flag_column=None,
                batch_size=2,
                full_refresh=False,
            ),
            TableSchema(
                [
                    ColumnSpec("id", "integer"),
                    ColumnSpec("updated_at", "timestamp"),
                    ColumnSpec("value", "text"),
                ]
            ),
            same_wm,
            2,
            same_wm,
            tmp_path,
        )
    )

    assert chunks == []


def test_max_watermark_uses_composite_cursor_for_same_watermark_boundary():
    same_wm = datetime(2026, 1, 1, 12, 0, 0)
    conn = _RecordingConnection(same_wm)
    adapter = _adapter()
    adapter.conn = conn
    adapter.schema = lambda _dataset, _table: TableSchema(
        [
            ColumnSpec("id", "integer"),
            ColumnSpec("updated_at", "timestamp"),
            ColumnSpec("value", "text"),
        ]
    )

    result = adapter.max_watermark(
        "",
        "source_table",
        "updated_at",
        same_wm,
        primary_key_column="id",
        start_primary_key=2,
    )

    assert result == same_wm
    assert (
        '"updated_at" > %s OR ("updated_at" = %s AND "id" > %s)'
        in conn.cursor_obj.sql
    )
    assert conn.cursor_obj.params == [same_wm, same_wm, 2]
    assert conn.cursor_obj.closed is True


def test_primary_key_cursor_is_persisted_in_state_json():
    state = MigrationState(state_json={})

    _set_state_last_primary_key(state, 42)

    assert state.state_json["last_primary_key_value"] == "42"
