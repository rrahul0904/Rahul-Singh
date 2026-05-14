from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.database import get_db
from mcp.server import InternalToolRegistryServer
from mcp.tools import registry_summary
from models import User

router = APIRouter()


class ToolCallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


@router.get("/status")
async def status(_user: User = Depends(get_current_user)):
    return registry_summary()


@router.get("/tools")
async def tools(_user: User = Depends(get_current_user)):
    return InternalToolRegistryServer(user=_user).list_tools()


@router.post("/call")
async def call_tool(body: ToolCallRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await InternalToolRegistryServer(db=db, user=user).call_tool_async(body.name, body.arguments, approved=body.approved)
