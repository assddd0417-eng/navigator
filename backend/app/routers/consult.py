"""기업 상담 (담당자). D-STATE 진단, 진단 변수 보완.

기업 보완 답변은 /navigator/manage/dstate (관리 링크).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.routers.navigator import manage_link
from app.config import get_settings
from app.services import (consult_evidence, consultation, criteria, dstate, eligibility_review, governance,
                          route)
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
    evidence_ids: list[int] | None = Field(default=None, description="이번 상담에 쓴 보완자료 (담당자 첨부·기업 제출)")


class VariableIn(BaseModel):
    name_ko: str | None = Field(default=None, min_length=1, max_length=50)
    definition: str | None = Field(default=None, min_length=1, max_length=500)
    source_desc: str | None = Field(default=None, min_length=1, max_length=200)
    question: str | None = Field(default=None, max_length=300, description="보완 질문. 빈 문자열이면 지움")
    option_labels: dict[str, str] | None = Field(default=None, description="선택지 코드: 새 이름")


class CheckItemIn(BaseModel):
    item: str = Field(min_length=1, max_length=50)
    content: str = Field(default="", max_length=300)
    kind: Literal["MANDATORY", "FIT", "GUIDE"]


class CriteriaIn(BaseModel):
    capability_full: int = Field(ge=1, le=100, description="역량 '충분' 경계 (D-STATE 영역 평균)")
    capability_partial: int = Field(ge=1, le=100, description="역량 '부분' 경계")
    grade_high: int = Field(ge=1, le=100, description="적합도 '상' 경계")
    grade_mid: int = Field(ge=1, le=100, description="적합도 '중' 경계")
    partial_ratio: int = Field(ge=1, le=99, description="'부분' 충족 비율(%)")
    check_items: list[CheckItemIn] = Field(min_length=1, max_length=30)
    note: str | None = Field(default=None, max_length=500, description="바꾼 이유 (소관부서 협의 내용)")


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
                                               include_closed=body.include_closed, user_id=user.id)


@router.post("/consult/companies/{org_id}/route")
async def growth_route(org_id: int, body: RouteRequest, user: CurrentUser = Depends(require_roles(*STAFF))):
    """맞춤형 성장경로: 단기·중기·장기 단계별 목표, 추천 사업(준비상태), 준비과제, 근거, 미추천 사유. 저장하지 않는다."""
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await route.build(conn, org_id, concern=body.concern, user_id=user.id)


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
                                          request_id=body.request_id, user_id=user.id,
                                          evidence_ids=body.evidence_ids)
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
async def review_log(limit: int = 100, user: CurrentUser = Depends(require_roles(*governance.AUDIT))):
    """이력 점검: 담당자가 판정을 바꾸거나 결과서를 고친 상담. 열람 권한이 없는 기업은 빠진다 (AX 주관부서는 전체)."""
    async with transaction() as conn:
        return await consultation.review_log(conn, max(1, min(limit, 500)),
                                             access=governance.access_filter(user, "c.organization_id"))


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


# ---------- 진단 변수사전·판정기준 ----------

@router.get("/consult/dstate/variables")
async def variable_list(user: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    """진단 변수사전 (고친 사람·시각 포함)."""
    async with transaction() as conn:
        return await dstate.variable_admin(conn)


@router.put("/consult/dstate/variables/{code}")
async def variable_update(code: str, body: VariableIn, user: CurrentUser = Depends(require_roles("AX_ADMIN")),
                          rid: str = Depends(request_id)):
    """변수명·정의·증빙 원천·보완 질문·선택지 이름 수정. 산정식과 값 유형은 그대로."""
    async with transaction(user.id, rid) as conn:
        try:
            return await dstate.update_variable(conn, code, body.model_dump(exclude_unset=True), user.id)
        except LookupError:
            raise NotFound("진단 변수", code) from None
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.get("/consult/criteria")
async def criteria_view(user: CurrentUser = Depends(require_roles(*governance.CRITERIA_READ))):
    """공고문 점검 항목·판정 기준과 버전 이력."""
    async with transaction() as conn:
        return await criteria.view(conn)


@router.put("/consult/criteria")
async def criteria_save(body: CriteriaIn, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                        rid: str = Depends(request_id)):
    """새 버전으로 저장하고 바로 적용한다."""
    async with transaction(user.id, rid) as conn:
        data = body.model_dump()
        note = data.pop("note")
        try:
            return await criteria.save(conn, data, note, user.id)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


@router.post("/consult/criteria/versions/{version}/activate")
async def criteria_activate(version: int, user: CurrentUser = Depends(require_roles(*governance.CRITERIA)),
                            rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        try:
            return await criteria.activate(conn, version)
        except LookupError:
            raise NotFound("판정기준 버전", version) from None


# ---------- 상담 보완자료 ----------

@router.get("/consult/companies/{org_id}/evidence")
async def evidence_list(org_id: int, user: CurrentUser = Depends(require_roles(*STAFF))):
    """기업이 낸 증빙과 담당자가 첨부한 보완자료."""
    async with transaction() as conn:
        await _require_company(conn, org_id, user)
        return await consult_evidence.list_for(conn, org_id)


@router.post("/consult/companies/{org_id}/evidence", status_code=201)
async def evidence_add(org_id: int, file: UploadFile = File(..., description="인증서·수출실적·보유기술 자료 (PDF·HWP)"),
                       note: str | None = Form(default=None, max_length=500),
                       user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    """상담 중 보완자료 첨부. 글자와 뽑은 값만 남긴다."""
    limit = get_settings().upload_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"파일이 {get_settings().upload_max_mb}MB 를 넘습니다")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "빈 파일입니다")
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        return await consult_evidence.add(conn, org_id, (file.filename or "보완자료").strip()[:300], data,
                                          (note or "").strip() or None, user.id)


@router.delete("/consult/companies/{org_id}/evidence/{evidence_id}", status_code=204)
async def evidence_delete(org_id: int, evidence_id: int, user: CurrentUser = Depends(require_roles(*STAFF)),
                          rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await _require_company(conn, org_id, user)
        try:
            await consult_evidence.delete(conn, org_id, evidence_id)
        except LookupError:
            raise NotFound("보완자료", evidence_id) from None
        except PermissionError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from None
    return Response(status_code=204)
