"""기업 상담 (담당자). D-STATE 진단, 진단 변수 보완.

기업 보완 답변은 /navigator/manage/dstate (관리 링크).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.routers.navigator import manage_link
from app.services import consultation, dstate, eligibility_review, governance, route
from app.services.bizno import format_bizno
from app.services.ratelimit import public_rate_limit

router = APIRouter(prefix="/navigator", tags=["기업 상담"])
STAFF = ("STAFF",)


class DstateValues(BaseModel):
    values: dict[str, Any] = Field(description="변수 코드: 값. null 이면 그 값을 지움",
                                   examples=[{"PROTOTYPE": "HAVE", "RND_STAFF": 4}])


class EligibilityRequest(BaseModel):
    concern: str | None = Field(default=None, max_length=2000,
                                description="상담 애로사항·관심분야. 사업 목적 부합 평가에 씀")
    announcement_ids: list[int] | None = Field(default=None, description="비우면 접수중·접수전 공개 공고 전체")
    include_closed: bool = False


class RouteRequest(BaseModel):
    concern: str | None = Field(default=None, max_length=2000, description="상담 애로사항·관심분야")


AreaCode = Literal["TECH", "QUALITY", "PRODUCTION", "BUSINESS", "DEFENSE", "EXPORT"]


class ProgramRouteIn(BaseModel):
    stage_code: Literal["ENTRY", "TECH_DEV", "SCALE"]
    next_program_ids: list[int] = Field(default_factory=list, max_length=20)
    entry_condition: str | None = Field(default=None, max_length=500)
    entry_min_scores: dict[AreaCode, int] = Field(default_factory=dict, examples=[{"TECH": 60, "DEFENSE": 30}])
    prep_tasks: list[str] = Field(default_factory=list, max_length=10)
    expected_output: str | None = Field(default=None, max_length=500)
    repeatable: bool = False
    sort_order: int = Field(default=0, ge=0, le=999)

    @field_validator("entry_min_scores")
    @classmethod
    def _range(cls, v: dict[str, int]) -> dict[str, int]:
        if any(not 0 <= x <= 100 for x in v.values()):
            raise ValueError("진입조건 점수는 0~100")
        return v

    @field_validator("prep_tasks")
    @classmethod
    def _tasks(cls, v: list[str]) -> list[str]:
        return [t.strip()[:200] for t in v if t.strip()]


class ConsultRequestIn(BaseModel):
    concern: str = Field(min_length=1, max_length=2000, description="애로사항")
    interest: str | None = Field(default=None, max_length=500, description="관심 지원사업")
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=40)


class RequestStatusIn(BaseModel):
    status: Literal["REQUESTED", "IN_PROGRESS", "DONE", "CANCELED"]


class ConsultRunIn(BaseModel):
    task: Literal["A", "B", "C"] = "C"
    concern: str | None = Field(default=None, max_length=2000)
    request_id: int | None = None


class VerdictOverride(BaseModel):
    announcement_id: int
    verdict: Literal["ELIGIBLE", "NEEDS_INFO", "INELIGIBLE"]
    reason: str = Field(min_length=1, max_length=500, description="판정을 바꾼 사유")


class ConsultUpdateIn(BaseModel):
    report: dict[str, str] | None = Field(default=None, description="결과서 항목 key: 고친 문장. 없는 key 는 유지")
    overrides: list[VerdictOverride] | None = Field(default=None, description="공고별 판정 수정. 주면 통째로 바꿈")
    feedback: str | None = Field(default=None, max_length=2000, description="결과에 대한 담당자 의견(이력 점검용)")


class ConfirmIn(BaseModel):
    notify: bool = Field(default=False, description="기업 등록 이메일로 확정 안내")


async def _require_company(conn, org_id: int, user: CurrentUser | None = None) -> None:
    if not await (await conn.execute(
            "SELECT 1 FROM ax.company_profile WHERE organization_id = %s", (org_id,))).fetchone():
        raise NotFound("기업 프로필", org_id)
    if user is not None and not await governance.can_view(conn, user, org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "이 기업정보를 볼 권한이 없습니다")


async def _require_consultation(conn, cid: int, user: CurrentUser) -> None:
    row = await (await conn.execute("SELECT organization_id FROM ax.consultation WHERE id = %s", (cid,))).fetchone()
    if row is None:
        raise NotFound("상담", cid)
    await _require_company(conn, row["organization_id"], user)


@router.get("/consult/companies")
async def search_companies(q: str = "", limit: int = 20,
                           user: CurrentUser = Depends(require_roles("STAFF", "AX_ADMIN"))):
    """상담 기업 선택: 상호 또는 사업자번호 일부. 빈 값이면 최근 수정 순."""
    digits = "".join(ch for ch in q if ch.isdigit())
    cond, extra = governance.access_filter(user)
    async with transaction() as conn:
        rows = await (await conn.execute(
            f"""SELECT o.id AS organization_id, o.name, o.business_reg_no, cp.company_size, cp.main_business,
                      cp.region, cp.business_status,
                      (SELECT max(d.created_at) FROM ax.company_diagnosis d WHERE d.organization_id = o.id)
                          AS last_diagnosed_at
                 FROM ax.organization o JOIN ax.company_profile cp ON cp.organization_id = o.id
                WHERE o.is_active AND {cond}
                  AND (%(q)s = '' OR o.name ILIKE '%%' || %(q)s || '%%'
                       OR (%(d)s <> '' AND o.business_reg_no LIKE '%%' || %(d)s || '%%'))
                ORDER BY cp.updated_at DESC, o.id DESC LIMIT %(n)s""",
            {"q": q.strip(), "d": digits, "n": max(1, min(limit, 100)), **extra})).fetchall()
    return [{**r, "business_reg_no": format_bizno(r["business_reg_no"]) if r["business_reg_no"] else None,
             "last_diagnosed_at": r["last_diagnosed_at"].isoformat() if r["last_diagnosed_at"] else None}
            for r in rows]


@router.get("/consult/dstate/rules")
async def dstate_rules(_: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
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
async def preview_dstate(org_id: int, user: CurrentUser = Depends(require_roles(*STAFF))):
    """저장하지 않고 지금 값으로 진단."""
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await dstate.run(conn, org_id, save=False)


@router.post("/consult/companies/{org_id}/dstate", status_code=201)
async def run_dstate(org_id: int, user: CurrentUser = Depends(require_roles(*STAFF)),
                     rid: str = Depends(request_id)):
    """진단 실행 후 이력에 저장."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        return await dstate.run(conn, org_id, save=True, user_id=user.id)


@router.put("/consult/companies/{org_id}/dstate/values")
async def staff_values(org_id: int, body: DstateValues, user: CurrentUser = Depends(require_roles(*STAFF)),
                       rid: str = Depends(request_id)):
    """담당자가 확인한 변수값. 기업 답변·회사 정보보다 먼저 쓴다."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        try:
            await dstate.save_values(conn, org_id, body.values, "STAFF", user.id)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
        return await dstate.run(conn, org_id, save=False)


@router.get("/consult/companies/{org_id}/diagnoses")
async def diagnosis_history(org_id: int, user: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await dstate.history(conn, org_id)


@router.post("/consult/companies/{org_id}/eligibility")
async def eligibility(org_id: int, body: EligibilityRequest, user: CurrentUser = Depends(require_roles(*STAFF))):
    """자격요건 검토 (D-STATE + 자격): 공고별 신청 가능 여부, 적합도 상·중·하, 근거, 보완 포인트, 신청 안내.
    저장하지 않는다."""
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await eligibility_review.review(conn, org_id, concern=body.concern,
                                               announcement_ids=body.announcement_ids,
                                               include_closed=body.include_closed)


@router.post("/consult/companies/{org_id}/route")
async def growth_route(org_id: int, body: RouteRequest, user: CurrentUser = Depends(require_roles(*STAFF))):
    """맞춤형 성장경로: 단기·중기·장기 단계별 목표, 추천 사업(준비상태), 준비과제, 근거, 미추천 사유. 저장하지 않는다."""
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await route.build(conn, org_id, concern=body.concern)


@router.get("/consult/route/rules")
async def route_rules(_: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    """성장단계와 지원사업 연계 기준표. 연계 기준이 없는 사업도 함께 보여 준다."""
    async with transaction() as conn:
        return await route.rules(conn)


@router.put("/consult/route/programs/{program_id}")
async def save_route(program_id: int, body: ProgramRouteIn,
                     user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                     rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        try:
            await route.save_program_route(conn, program_id, body.model_dump(), user.id)
        except LookupError:
            raise NotFound("지원사업", program_id) from None
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
        return await route.rules(conn)


@router.delete("/consult/route/programs/{program_id}", status_code=204)
async def delete_route(program_id: int, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                       rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await conn.execute("DELETE FROM ax.program_route WHERE program_id = %s", (program_id,))


@router.get("/consult/requests")
async def consult_requests(status_: str | None = Query(default=None, alias="status"),
                           user: CurrentUser = Depends(require_roles(*STAFF))):
    """상담 요청 목록. 요청 상태가 먼저."""
    async with transaction() as conn:
        rows = await consultation.list_requests(conn, status=status_)
        return [r for r in rows if await governance.can_view(conn, user, r["organization_id"])]


@router.post("/consult/companies/{org_id}/requests", status_code=201)
async def staff_request(org_id: int, body: ConsultRequestIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                        rid: str = Depends(request_id)):
    """전화·방문 상담 요청을 담당자가 대신 등록."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        return await consultation.create_request(conn, org_id, body.model_dump(), "STAFF", user.id)


@router.patch("/consult/requests/{req_id}")
async def request_status(req_id: int, body: RequestStatusIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                         rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        row = await (await conn.execute(
            "SELECT organization_id FROM ax.consult_request WHERE id = %s", (req_id,))).fetchone()
        if row is None:
            raise NotFound("상담 요청", req_id)
        if not await governance.can_view(conn, user, row["organization_id"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "이 기업정보를 볼 권한이 없습니다")
        try:
            return await consultation.set_request_status(conn, req_id, body.status, user.id)
        except LookupError:
            raise NotFound("상담 요청", req_id) from None


@router.post("/consult/companies/{org_id}/consultations", status_code=201)
async def run_consultation(org_id: int, body: ConsultRunIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                           rid: str = Depends(request_id)):
    """상담 실행 후 이력 저장: 진단(+자격요건 검토+성장경로)과 상담결과서 초안."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        try:
            return await consultation.run(conn, org_id, task=body.task, concern=body.concern,
                                          request_id=body.request_id, user_id=user.id)
        except consultation.ConsultError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.get("/consult/companies/{org_id}/consultations")
async def consultation_history(org_id: int, user: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await consultation.history(conn, org_id)


@router.get("/consult/consultations/{cid}")
async def get_consultation(cid: int, user: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        await _require_consultation(conn, cid, user)
        c = await consultation.get(conn, cid)
    if c is None:
        raise NotFound("상담", cid)
    return c


@router.put("/consult/consultations/{cid}")
async def update_consultation(cid: int, body: ConsultUpdateIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                              rid: str = Depends(request_id)):
    """결과서 문장, 판정 수정(사유 필수), 담당자 의견. 확정 전에만."""
    async with transaction(user.id, rid) as conn:
        await _require_consultation(conn, cid, user)
        try:
            return await consultation.update(
                conn, cid, report=body.report, feedback=body.feedback,
                overrides=[o.model_dump() for o in body.overrides] if body.overrides is not None else None)
        except LookupError:
            raise NotFound("상담", cid) from None
        except consultation.ConsultError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


@router.post("/consult/consultations/{cid}/confirm")
async def confirm_consultation(cid: int, body: ConfirmIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                               rid: str = Depends(request_id)):
    """확정하면 기업 화면에 보인다. notify 면 기업 등록 이메일로 안내."""
    async with transaction(user.id, rid) as conn:
        await _require_consultation(conn, cid, user)
        try:
            return await consultation.confirm(conn, cid, user.id, body.notify)
        except LookupError:
            raise NotFound("상담", cid) from None
        except consultation.ConsultError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


@router.get("/consult/review-log")
async def review_log(limit: int = 100, _: CurrentUser = Depends(require_roles(*governance.AUDIT))):
    """이력 점검: 담당자가 판정을 바꾸거나 결과서를 고친 상담."""
    async with transaction() as conn:
        return await consultation.review_log(conn, max(1, min(limit, 500)))


@router.get("/manage/consultations", dependencies=[Depends(public_rate_limit)])
async def my_consultations(link: dict = Depends(manage_link)):
    """기업 화면: 확정된 상담결과와 내 상담 요청."""
    async with transaction() as conn:
        return await consultation.company_view(conn, link["organization_id"])


@router.post("/manage/consult-requests", status_code=201, dependencies=[Depends(public_rate_limit)])
async def my_consult_request(body: ConsultRequestIn, link: dict = Depends(manage_link),
                             rid: str = Depends(request_id)):
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        return await consultation.create_request(conn, link["organization_id"], body.model_dump(), "SELF")


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


# ---------- 서비스 안내·열람 권한 ----------

class AccessIn(BaseModel):
    department_ids: list[int] = Field(default_factory=list, max_length=50,
                                      description="볼 수 있는 부서. 비우면 모든 담당 부서가 본다")


@router.get("/service/info")
async def service_info(_: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    """서비스 정의, 주체별 역할(RACI), AI 자율성 등급과 확정 관문."""
    return governance.info()


@router.get("/consult/companies/{org_id}/access")
async def company_access(org_id: int, user: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await governance.get_access(conn, org_id)


@router.put("/consult/companies/{org_id}/access")
async def set_company_access(org_id: int, body: AccessIn, user: CurrentUser = Depends(require_roles("AX_ADMIN")),
                             rid: str = Depends(request_id)):
    """기업정보 열람 부서 지정 (AX 주관부서)."""
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        try:
            return await governance.set_access(conn, org_id, body.department_ids, user.id)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
