"""Navigator 외부 수집 API (담당자)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.services import collector

router = APIRouter(prefix="/navigator/sources", tags=["Navigator 외부 수집"])
STAFF = ("STAFF", "PROGRAM_OWNER")  # 공고 등록·조건 확인: 기업지원 담당자, 지원사업 소관부서


class ExternalIdIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=50)


@router.get("")
async def list_sources(_: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        return await collector.source_overview(conn)


@router.get("/jobs")
async def list_jobs(source: str | None = None, limit: int = Query(30, le=200),
                    _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        return await collector.recent_jobs(conn, source, limit)


@router.post("/{code}/run")
async def run_source(code: str, organization_id: int | None = None,
                     user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    """지금 수집. organization_id 를 주면 그 기업만 (국세청·KIPRIS·DART)."""
    try:
        return await collector.run_source(code.upper(), organization_id=organization_id, request_id=rid)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.get("/companies/{org_id}/external-ids")
async def company_external_ids(org_id: int, _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        return await (await conn.execute(
            """SELECT s.code AS source, e.external_id, e.set_by, e.updated_at
                 FROM ax.company_external_id e JOIN ax.external_source s ON s.id = e.source_id
                WHERE e.organization_id = %s ORDER BY s.id""", (org_id,))).fetchall()


@router.put("/companies/{org_id}/external-ids/{code}", status_code=204)
async def set_company_external_id(org_id: int, code: str, body: ExternalIdIn,
                                  user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    """동명 회사가 섞일 때 담당자가 DART 고유번호·KIPRIS 특허고객번호를 직접 지정."""
    async with transaction(user.id, rid) as conn:
        src = await (await conn.execute("SELECT id FROM ax.external_source WHERE code = %s",
                                        (code.upper(),))).fetchone()
        if src is None:
            raise NotFound("외부 출처", code)
        if not await (await conn.execute("SELECT 1 FROM ax.company_profile WHERE organization_id = %s",
                                         (org_id,))).fetchone():
            raise NotFound("기업 프로필", org_id)
        await conn.execute(
            """INSERT INTO ax.company_external_id (organization_id, source_id, external_id, set_by)
               VALUES (%s, %s, %s, 'STAFF')
               ON CONFLICT (organization_id, source_id) DO UPDATE
                 SET external_id = EXCLUDED.external_id, set_by = 'STAFF', updated_at = now()""",
            (org_id, src["id"], body.external_id.strip()))
    return Response(status_code=204)
