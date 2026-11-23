"""AI 관리 (AX 주관부서). 프롬프트 버전 관리와 AI 호출 기록."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.services import ai_gateway

router = APIRouter(prefix="/navigator/ai", tags=["AI 관리"])
AX = ("AX_ADMIN",)
Code = Literal["ELIGIBILITY_JUDGE", "REPORT_DRAFT"]


class PromptIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    system_text: str | None = Field(default=None, min_length=1, max_length=20000,
                                    description="역할·출력 형식. 비우면 지금 버전 그대로")
    guide_text: str | None = Field(default=None, max_length=20000, description="판단 지침·문장 규칙")
    note: str | None = Field(default=None, max_length=500, description="바꾼 이유")


@router.get("/prompts")
async def list_prompts(user: CurrentUser = Depends(require_roles(*AX, "STAFF", "PROGRAM_OWNER"))):
    """프롬프트 전체 버전. 사용 중인 버전이 is_active."""
    async with transaction() as conn:
        return {"mode": ai_gateway.mode(), "items": await ai_gateway.prompts(conn)}


@router.post("/prompts/{code}", status_code=201)
async def save_prompt(code: Code, body: PromptIn, user: CurrentUser = Depends(require_roles(*AX)),
                      rid: str = Depends(request_id)):
    """새 버전을 만들고 바로 사용한다. 이전 버전은 남는다."""
    async with transaction(user.id, rid) as conn:
        return await ai_gateway.save_prompt(conn, code, body.model_dump(), user.id)


@router.post("/prompts/{code}/versions/{prompt_id}/activate")
async def activate(code: Code, prompt_id: int, user: CurrentUser = Depends(require_roles(*AX)),
                   rid: str = Depends(request_id)):
    """예전 버전으로 되돌리기."""
    async with transaction(user.id, rid) as conn:
        try:
            return await ai_gateway.activate_prompt(conn, prompt_id, code)
        except LookupError:
            raise NotFound("프롬프트", prompt_id) from None


@router.get("/calls")
async def calls(purpose: Code | None = None, limit: int = Query(default=100, ge=1, le=500),
                user: CurrentUser = Depends(require_roles(*AX))):
    """AI 호출 기록: 목적·프롬프트 버전·모델·입력 근거·출력·차단 사유."""
    async with transaction() as conn:
        return await ai_gateway.call_logs(conn, limit=limit, purpose=purpose)
