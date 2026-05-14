from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_operator
from core.database import get_db
from models import User
from services.copilot import UmaCopilotService

router = APIRouter()


class CopilotAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    provider: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class CopilotActionRequest(BaseModel):
    action_type: str = Field(min_length=1, max_length=120)
    provider: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class SnowflakeServiceRequest(BaseModel):
    service: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("/providers")
async def providers(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await UmaCopilotService(db).providers()


@router.get("/snowflake-services")
async def snowflake_services(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await UmaCopilotService(db).execute_action(
        action_type="get_snowflake_services_health",
        payload={},
        confirmed=False,
        user=_user,
    )


@router.post("/ask")
async def ask(
    body: CopilotAskRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await UmaCopilotService(db).ask(
        message=body.message,
        provider_name=body.provider,
        context=body.context,
    )


@router.post("/actions/preview")
async def preview_action(
    body: CopilotActionRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await UmaCopilotService(db).preview_action(
        body.action_type,
        body.payload,
        provider_name=body.provider,
    )


@router.post("/snowflake-services/query")
async def query_snowflake_service(
    body: SnowflakeServiceRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service_map = {
        "health": "get_snowflake_services_health",
        "cortex_analyst": "ask_cortex_analyst",
        "cortex_documents": "search_cortex_documents",
        "cortex_search": "search_cortex_logs",
        "cortex_llm": "summarize_with_cortex",
        "snowpark_profile": "profile_with_snowpark",
        "query_history": "get_snowflake_query_history",
        "cost_intelligence": "get_snowflake_cost_intelligence",
    }
    action_type = service_map.get(body.service.strip().lower(), body.service.strip().lower())
    return await UmaCopilotService(db).execute_action(
        action_type=action_type,
        payload=body.payload,
        confirmed=False,
        user=_user,
    )


@router.post("/actions/execute")
async def execute_action(
    body: CopilotActionRequest,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    return await UmaCopilotService(db).execute_action(
        action_type=body.action_type,
        payload=body.payload,
        confirmed=body.confirmed,
        user=user,
    )
