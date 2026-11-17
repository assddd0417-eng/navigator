"""Navigator 매칭 API. /matching/* 는 담당자, /companies/{brn}/matches·/manage/* 는 기업."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.routers.navigator import _bizno, manage_link
from app.services import mailer
from app.services import navigator_outreach as outreach
from app.services.bizno import format_bizno
from app.services.company_profile import find_by_bizno, full_view
from app.services.navigator_matching import (
    add_past_context,
    fresh_company_run,
    match_announcement,
    match_company,
    run_results,
)
from app.services.ratelimit import public_rate_limit

router = APIRouter(prefix="/navigator", tags=["navigator-matching"])
STAFF = ("PLANNER",)
VERDICTS = ("ELIGIBLE", "NEEDS_INFO", "INELIGIBLE")


def _verdicts(raw: str | None) -> tuple[str, ...] | None:
    if not raw:
        return None
    vs = tuple(v.strip().upper() for v in raw.split(",") if v.strip())
    bad = [v for v in vs if v not in VERDICTS]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"verdict 는 {', '.join(VERDICTS)} 중에서 고르세요")
    return vs


@router.post("/matching/announcements/{ann_id}", status_code=201)
async def run_announcement_matching(ann_id: int, verdict: str | None = Query(None, description="ELIGIBLE,NEEDS_INFO"),
                                    user: CurrentUser = Depends(require_roles(*STAFF)),
                                    rid: str = Depends(request_id)):
    vs = _verdicts(verdict)
    async with transaction(user.id, rid) as conn:
        run_id = await match_announcement(conn, ann_id, requested_by=user.id)
        return await run_results(conn, run_id, verdicts=vs)


@router.post("/matching/companies/{org_id}", status_code=201)
async def run_company_matching(org_id: int, include_closed: bool = False, past: bool = False,
                               verdict: str | None = None,
                               user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    vs = _verdicts(verdict)
    async with transaction(user.id, rid) as conn:
        run_id = await match_company(conn, org_id, include_closed=include_closed, past=past,
                                     requested_by=user.id, via="STAFF")
        res = await run_results(conn, run_id, verdicts=vs)
        return await add_past_context(conn, org_id, res) if past else res


@router.get("/matching/announcements/{ann_id}")
async def latest_announcement_run(ann_id: int, verdict: str | None = None,
                                  _: CurrentUser = Depends(require_roles(*STAFF))):
    """마지막 실행 결과. 없으면 run=null."""
    vs = _verdicts(verdict)
    async with transaction() as conn:
        row = await (await conn.execute(
            """SELECT id FROM ax.company_match_run WHERE announcement_id = %s
                  AND direction = 'ANNOUNCEMENT_TO_COMPANY' AND requested_via <> 'SYSTEM'
                ORDER BY created_at DESC, id DESC LIMIT 1""",
            (ann_id,))).fetchone()
        if row is None:
            return {"run": None, "summary": {v: 0 for v in VERDICTS}, "recommendations": []}
        return await run_results(conn, row["id"], verdicts=vs)


@router.get("/matching/companies/{org_id}/profile")
async def staff_company_profile(org_id: int, _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        if not await (await conn.execute(
                "SELECT 1 FROM ax.company_profile WHERE organization_id = %s", (org_id,))).fetchone():
            raise NotFound("기업 프로필", org_id)
        view = await full_view(conn, org_id)
    view["visibility"] = "STAFF"
    if view.get("registered_email"):
        view["registered_email"] = mailer.mask_email(view["registered_email"])
    return view


@router.get("/matching/runs/{run_id}")
async def get_run(run_id: int, verdict: str | None = None, _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        return await run_results(conn, run_id, verdicts=_verdicts(verdict))


async def _company_run(conn, org_id: int, include_closed: bool, refresh: bool, via: str, past: bool = False) -> int:
    run_id = None if refresh else await fresh_company_run(conn, org_id, include_closed, past)
    return run_id or await match_company(conn, org_id, include_closed=include_closed, past=past, via=via)


@router.get("/companies/{business_reg_no}/matches", dependencies=[Depends(public_rate_limit)])
async def public_matches(business_reg_no: str, rid: str = Depends(request_id)):
    """공개 조회. 신용등급·매출 요건은 가리고 나머지로만 판정."""
    bizno = _bizno(business_reg_no)
    async with transaction(None, rid) as conn:
        found = await find_by_bizno(conn, bizno)
        if not found or not found["has_profile"] or found["org_type"] != "COMPANY":
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"사업자번호 {format_bizno(bizno)} 로 등록된 기업이 없습니다")
        run_id = await _company_run(conn, found["organization_id"], False, False, "PUBLIC")
        return await run_results(conn, run_id, public=True)


@router.post("/manage/matches", dependencies=[Depends(public_rate_limit)])
async def my_matches(include_closed: bool = False, refresh: bool = False, verdict: str | None = None,
                     link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    vs = _verdicts(verdict)
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        run_id = await _company_run(conn, link["organization_id"], include_closed, refresh, "COMPANY_LINK")
        return await run_results(conn, run_id, verdicts=vs)


@router.post("/manage/past-matches", dependencies=[Depends(public_rate_limit)])
async def my_past_matches(refresh: bool = False, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """참여할 수 있었던 사업: 최근 마감 공고 중 지금 회사 정보로 적합·확인 필요인 것."""
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        run_id = await _company_run(conn, link["organization_id"], False, refresh, "COMPANY_LINK", past=True)
        res = await run_results(conn, run_id, verdicts=("ELIGIBLE", "NEEDS_INFO"))
        return await add_past_context(conn, link["organization_id"], res)


@router.get("/manage/questions", dependencies=[Depends(public_rate_limit)])
async def my_questions(link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        run_id = await _company_run(conn, link["organization_id"], False, False, "COMPANY_LINK")
        res = await run_results(conn, run_id)
    out: dict[int, dict] = {}
    for r in res["recommendations"]:
        if r["verdict"] == "INELIGIBLE":
            continue
        for c in r["checks"]:
            if c["result"] == "UNKNOWN" and c["question"] and c["requirement_id"] not in out:
                out[c["requirement_id"]] = {
                    "requirement_id": c["requirement_id"], "announcement_id": r["announcement_id"],
                    "announcement_title": r["announcement_title"], "requirement": c["description"],
                    "mandatory_label": c["mandatory_label"], "question": c["question"],
                    "answer_type": "integer" if c["req_type_code"] == "TRL" else "boolean"}
    return {"run_id": run_id, "questions": list(out.values())}


class AnswerIn(BaseModel):
    requirement_id: int
    value: bool | int = Field(description="TRL 은 1~9 숫자, 나머지는 예(true)/아니오(false)")


class AnswersIn(BaseModel):
    answers: list[AnswerIn] = Field(min_length=1, max_length=50)


@router.post("/manage/answers", dependencies=[Depends(public_rate_limit)])
async def answer_questions(body: AnswersIn, link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """답 저장(요건당 최신 1건) 후 재판정 결과 반환."""
    org_id = link["organization_id"]
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        for a in body.answers:
            req = await (await conn.execute(
                """SELECT r.req_type_code FROM ax.announcement_requirement r
                     JOIN ax.announcement an ON an.id = r.announcement_id
                    WHERE r.id = %s AND an.status = 'PUBLISHED'""", (a.requirement_id,))).fetchone()
            if req is None:
                raise NotFound("자격요건", a.requirement_id)
            if req["req_type_code"] == "TRL":
                if isinstance(a.value, bool) or not 1 <= a.value <= 9:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "TRL 은 1~9 사이 숫자로 답해 주세요")
            elif not isinstance(a.value, bool):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                    f"자격요건 {a.requirement_id} 은 예(true)/아니오(false)로 답해 주세요")
            await conn.execute(
                """INSERT INTO ax.eligibility_answer (organization_id, requirement_id, answer, answered_via)
                   VALUES (%s, %s, jsonb_build_object('value', %s::jsonb), 'COMPANY_LINK')
                   ON CONFLICT (organization_id, requirement_id)
                   DO UPDATE SET answer = EXCLUDED.answer, answered_via = EXCLUDED.answered_via,
                                 answered_by = NULL, answered_at = now()""",
                (org_id, a.requirement_id, "true" if a.value is True else "false" if a.value is False else str(a.value)))
        run_id = await match_company(conn, org_id, via="COMPANY_LINK")
        return await run_results(conn, run_id)


class OutreachIn(BaseModel):
    organization_ids: list[int] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/matching/announcements/{ann_id}/outreach")
async def outreach_candidates(ann_id: int, _: CurrentUser = Depends(require_roles(*STAFF))):
    """마지막 매칭 결과의 적합·확인 필요 기업, 권유 메일 동의 여부, 보낸 기록."""
    async with transaction() as conn:
        return await outreach.candidates(conn, ann_id)


@router.post("/matching/announcements/{ann_id}/outreach")
async def send_outreach(ann_id: int, body: OutreachIn, user: CurrentUser = Depends(require_roles(*STAFF)),
                        rid: str = Depends(request_id)):
    """권유 메일 발송. 동의하지 않았거나 이미 보낸 기업은 건너뛰고 skipped 에 이유를 적는다."""
    res = await outreach.send(ann_id, body.organization_ids, (body.note or "").strip() or None, user.id, rid)
    async with transaction() as conn:
        res["candidates"] = await outreach.candidates(conn, ann_id)
    return res
