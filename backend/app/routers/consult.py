"""기업 상담 (담당자). D-STATE 진단, 진단 변수 보완.

기업 보완 답변은 /navigator/manage/dstate (관리 링크).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.routers.navigator import manage_link
from app.services import dstate
from app.services.bizno import format_bizno
from app.services.ratelimit import public_rate_limit

router = APIRouter(prefix="/navigator", tags=["기업 상담"])
STAFF = ("STAFF",)


class DstateValues(BaseModel):
    values: dict[str, Any] = Field(description="변수 코드: 값. null 이면 그 값을 지움",
                                   examples=[{"PROTOTYPE": "HAVE", "RND_STAFF": 4}])


async def _require_company(conn, org_id: int) -> None:
    if not await (await conn.execute(
            "SELECT 1 FROM ax.company_profile WHERE organization_id = %s", (org_id,))).fetchone():
        raise NotFound("기업 프로필", org_id)


@router.get("/consult/companies")
async def search_companies(q: str = "", limit: int = 20, _: CurrentUser = Depends(require_roles(*STAFF))):
    """상담 기업 선택: 상호 또는 사업자번호 일부. 빈 값이면 최근 수정 순."""
    digits = "".join(ch for ch in q if ch.isdigit())
    async with transaction() as conn:
        rows = await (await conn.execute(
            """SELECT o.id AS organization_id, o.name, o.business_reg_no, cp.company_size, cp.main_business,
                      cp.region, cp.business_status,
                      (SELECT max(d.created_at) FROM ax.company_diagnosis d WHERE d.organization_id = o.id)
                          AS last_diagnosed_at
                 FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
                WHERE o.is_active
                  AND (%(q)s = '' OR o.name ILIKE '%%' || %(q)s || '%%'
                       OR (%(d)s <> '' AND o.business_reg_no LIKE '%%' || %(d)s || '%%'))
                ORDER BY cp.updated_at DESC, o.id DESC LIMIT %(n)s""",
            {"q": q.strip(), "d": digits, "n": max(1, min(limit, 100))})).fetchall()
    return [{**r, "business_reg_no": format_bizno(r["business_reg_no"]) if r["business_reg_no"] else None,
             "last_diagnosed_at": r["last_diagnosed_at"].isoformat() if r["last_diagnosed_at"] else None}
            for r in rows]


@router.get("/consult/dstate/rules")
async def dstate_rules(_: CurrentUser = Depends(require_roles(*STAFF))):
    """진단 기준: 영역별 산정식, 상태유형 분류 조건, 변수사전."""
    async with transaction() as conn:
        defs = await dstate.variables(conn)
    return {
        "rule_version": dstate.RULE_VERSION,
        "areas": [{"code": c, "label": l, "formula": dstate.AREA_FORMULA[c]} for c, l in dstate.AREAS],
        "state_types": [{"code": c, "label": l, "condition": cond} for c, l, cond, _ in dstate.STATE_RULES],
        "variables": defs,
    }


@router.get("/consult/companies/{org_id}/dstate")
async def preview_dstate(org_id: int, _: CurrentUser = Depends(require_roles(*STAFF))):
    """저장하지 않고 지금 값으로 진단."""
    async with transaction() as conn:
        await _require_company(conn, org_id)
        return await dstate.run(conn, org_id, save=False)


@router.post("/consult/companies/{org_id}/dstate", status_code=201)
async def run_dstate(org_id: int, user: CurrentUser = Depends(require_roles(*STAFF)),
                     rid: str = Depends(request_id)):
    """진단 실행 후 이력에 저장."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id)
        return await dstate.run(conn, org_id, save=True, user_id=user.id)


@router.put("/consult/companies/{org_id}/dstate/values")
async def staff_values(org_id: int, body: DstateValues, user: CurrentUser = Depends(require_roles(*STAFF)),
                       rid: str = Depends(request_id)):
    """담당자가 확인한 변수값. 기업 답변·회사 정보보다 먼저 쓴다."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id)
        try:
            await dstate.save_values(conn, org_id, body.values, "STAFF", user.id)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
        return await dstate.run(conn, org_id, save=False)


@router.get("/consult/companies/{org_id}/diagnoses")
async def diagnosis_history(org_id: int, _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        await _require_company(conn, org_id)
        return await dstate.history(conn, org_id)


@router.get("/manage/dstate", dependencies=[Depends(public_rate_limit)])
async def my_dstate_questions(link: dict = Depends(manage_link)):
    """기업 보완질의: 진단 변수와 지금 값. 점수는 보여 주지 않는다."""
    async with transaction() as conn:
        inp = await dstate.load_input(conn, link["organization_id"])
        rows = dstate.variable_rows(await dstate.variables(conn), inp)
    return {"variables": rows, "missing": [r["code"] for r in rows if r["missing"]]}


@router.put("/manage/dstate", dependencies=[Depends(public_rate_limit)])
async def my_dstate_answers(body: DstateValues, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        try:
            await dstate.save_values(conn, link["organization_id"], body.values, "SELF")
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
        inp = await dstate.load_input(conn, link["organization_id"])
        rows = dstate.variable_rows(await dstate.variables(conn), inp)
    return {"variables": rows, "missing": [r["code"] for r in rows if r["missing"]]}
