"""운영규정·지침 (지원사업 소관부서). 조문 등록·확인, 근거 검색."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.services import governance, regulation

router = APIRouter(prefix="/navigator/regulations", tags=["운영규정·지침"])
Check = Literal["TAX_DELINQUENT", "INSOLVENT", "RND_RESTRICTED", "PROCUREMENT_SANCTIONED", "DUPLICATE"]


class ArticleIn(BaseModel):
    article_no: str = Field(min_length=1, max_length=40, examples=["제10조"])
    title: str | None = Field(default=None, max_length=100)
    body: str = Field(min_length=1, max_length=20000)
    checks: list[Check] | None = Field(default=None, description="공통 참여제한 항목. 비우면 본문에서 찾은 후보")
    within_years: int | None = Field(default=None, ge=1, le=10, description="중복지원 제한 기간(년)")


class RegulationIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["COMMON", "PROGRAM"]
    program_id: int | None = None
    version_label: str | None = Field(default=None, max_length=50)
    effective_on: date | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    text: str | None = Field(default=None, max_length=200000, description="규정 전문. '제N조(제목)' 단위로 나눈다")
    articles: list[ArticleIn] | None = Field(default=None, max_length=500, description="조문을 직접 줄 때")


class RegulationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    version_label: str | None = Field(default=None, max_length=50)
    effective_on: date | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    articles: list[ArticleIn] | None = Field(default=None, max_length=500,
                                             description="조문 전체를 바꾼다. 바꾸면 확인일이 지워진다")


class PreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=200000)


def _articles(items: list[ArticleIn] | None) -> list[dict] | None:
    return None if items is None else [a.model_dump() for a in items]


@router.get("")
async def list_regulations(user: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    async with transaction() as conn:
        return await regulation.list_all(conn)


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=500), program_id: int | None = None,
                 user: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    """조문 검색: 벡터 관련도와 낱말 겹침으로 고르고 다시 정렬. program_id 를 주면 그 사업 규정과 공통운영규정만."""
    async with transaction() as conn:
        rows = await regulation.search(conn, q, program_id=program_id, limit=10)
        return [{k: r[k] for k in ("id", "ref", "regulation_id", "kind", "body", "check_labels", "sim", "keyword",
                                   "score", "confirmed_at")} for r in rows]


@router.post("/preview")
async def preview(body: PreviewIn, user: CurrentUser = Depends(require_roles(*governance.CRITERIA))):
    """저장하지 않고 조문 나누기와 참여제한 후보만 본다."""
    out = []
    for a in regulation.split_articles(body.text):
        checks, years = regulation.guess_checks(a["body"])
        out.append({**a, "checks": checks, "within_years": years,
                    "check_labels": [regulation.CHECK_KO[c] for c in checks]})
    return out


@router.get("/{reg_id}")
async def get_regulation(reg_id: int, user: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    async with transaction() as conn:
        try:
            return await regulation.get(conn, reg_id)
        except LookupError:
            raise NotFound("운영규정", reg_id) from None


@router.post("", status_code=201)
async def create(body: RegulationIn, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                 rid: str = Depends(request_id)):
    if not body.text and not body.articles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "규정 전문(text)이나 조문(articles)이 필요합니다")
    async with transaction(user.id, rid) as conn:
        data = body.model_dump()
        data["articles"] = _articles(body.articles)
        try:
            return await regulation.create(conn, data, user.id, user.department_id)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.put("/{reg_id}")
async def update(reg_id: int, body: RegulationUpdate, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                 rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        data = body.model_dump(exclude_unset=True)
        if "articles" in data:
            if not body.articles:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "조문이 없습니다")
            data["articles"] = _articles(body.articles)
        try:
            return await regulation.update(conn, reg_id, data)
        except LookupError:
            raise NotFound("운영규정", reg_id) from None


@router.post("/{reg_id}/confirm")
async def confirm(reg_id: int, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                  rid: str = Depends(request_id)):
    """소관부서 확인. 확인일이 판단기준 확인일로 자격검토 결과에 나온다."""
    async with transaction(user.id, rid) as conn:
        try:
            return await regulation.confirm(conn, reg_id, user.id)
        except LookupError:
            raise NotFound("운영규정", reg_id) from None


@router.delete("/{reg_id}", status_code=204)
async def delete(reg_id: int, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                 rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        try:
            await regulation.delete(conn, reg_id)
        except LookupError:
            raise NotFound("운영규정", reg_id) from None
