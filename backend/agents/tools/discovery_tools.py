from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Connection


async def inspect_source_schema(
    db: AsyncSession,
    *,
    connection_id: str | None,
    schemas: list[str],
    source_type: str,
) -> dict:
    """Read source metadata if a connection exists; otherwise stage a deterministic discovery plan."""
    conn = await db.get(Connection, connection_id) if connection_id else None
    scoped_schemas = schemas or ["PUBLIC"]
    if not conn:
        return {
            "mode": "planned",
            "source_type": source_type,
            "schemas": scoped_schemas,
            "objects": [],
            "message": "No source connection selected yet; discovery plan staged without reading data.",
        }
    return {
        "mode": "connection_registered",
        "connection_id": conn.id,
        "connection_name": conn.name,
        "source_type": conn.type.value,
        "schemas": scoped_schemas,
        "objects": [
            {"schema": schema, "name": "*", "type": "schema_scan", "row_count": None, "risk": "unknown"}
            for schema in scoped_schemas
        ],
        "message": "Connection is registered; live metadata scan is ready for source-specific implementation.",
    }


async def list_available_connections(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(Connection).order_by(Connection.created_at.desc()))).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "type": row.type.value,
            "role": row.connection_role.value if row.connection_role else "both",
            "health": row.health,
        }
        for row in rows
    ]
