"""Navigator 매칭과 판정 API (3단계).

담당자(로그인, PLANNER):
  POST /navigator/matching/announcements/{ann_id}   공고 → 기업 순위 (새로 실행)
  POST /navigator/matching/companies/{org_id}       기업 → 공고 순위 (새로 실행)
  GET  /navigator/matching/runs/{run_id}            저장된 실행 결과 (근거·판정 전부)
기업(로그인 없음):
  GET  /navigator/companies/{brn}/matches           사업자번호만으로: 공개 정보 기준 결과 (신용등급·매출 요건은 가림)
  POST /navigator/manage/matches                    관리 링크로: 내 결과 전부
  GET  /navigator/manage/questions                  관리 링크로: 정보부족 공고의 보완질문
  POST /navigator/manage/answers                    관리 링크로: 보완질문에 답 → 다시 판정
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.routers.navigator import _bizno, manage_link
from app.services.bizno import format_bizno
from app.services.company_profile import find_by_bizno
from app.services.navigator_matching import (
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


# ---------------------------------------------------------------------------
# 담당자
# ---------------------------------------------------------------------------
@router.post("/matching/announcements/{ann_id}", status_code=201)
async def run_announcement_matching(ann_id: int, verdict: str | None = Query(None, description="ELIGIBLE,NEEDS_INFO"),
                                    user: CurrentUser = Depends(require_roles(*STAFF)),
                                    rid: str = Depends(request_id)):
    """이 공고에 맞는 기업을 찾는다. 판정(적합→정보부족→부적격)·총점 순."""
    vs = _verdicts(verdict)
    async with transaction(user.id, rid) as conn:
        run_id = await match_announcement(conn, ann_id, requested_by=user.id)
        return await run_results(conn, run_id, verdicts=vs)


@router.post("/matching/companies/{org_id}", status_code=201)
async def run_company_matching(org_id: int, include_closed: bool = False, verdict: str | None = None,
                               user: CurrentUser = Depends(require_roles(*STAFF)), rid: str = Depends(request_id)):
    """이 기업이 지원할 만한 공고를 찾는다 (담당자가 대신 실행)."""
    vs = _verdicts(verdict)
    async with transaction(user.id, rid) as conn:
        run_id = await match_company(conn, org_id, include_closed=include_closed, requested_by=user.id, via="STAFF")
        return await run_results(conn, run_id, verdicts=vs)


@router.get("/matching/runs/{run_id}")
async def get_run(run_id: int, verdict: str | None = None, _: CurrentUser = Depends(require_roles(*STAFF))):
    async with transaction() as conn:
        return await run_results(conn, run_id, verdicts=_verdicts(verdict))


# ---------------------------------------------------------------------------
# 기업 (로그인 없음)
# ---------------------------------------------------------------------------
async def _company_run(conn, org_id: int, include_closed: bool, refresh: bool, via: str) -> int:
    run_id = None if refresh else await fresh_company_run(conn, org_id, include_closed)
    return run_id or await match_company(conn, org_id, include_closed=include_closed, via=via)


@router.get("/companies/{business_reg_no}/matches", dependencies=[Depends(public_rate_limit)])
async def public_matches(business_reg_no: str, rid: str = Depends(request_id)):
    """사업자번호만으로 보는 추천 공고. 신용등급·매출 요건은 결과를 가리고, 판정도 공개 정보만으로 낸다.
    전체 결과와 보완질문은 관리 링크로 본다."""
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
    """관리 링크로 보는 내 추천 공고 (오늘 결과가 있고 그 뒤 바뀐 게 없으면 그 결과를 다시 쓴다)."""
    vs = _verdicts(verdict)
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        run_id = await _company_run(conn, link["organization_id"], include_closed, refresh, "COMPANY_LINK")
        return await run_results(conn, run_id, verdicts=vs)


@router.get("/manage/questions", dependencies=[Depends(public_rate_limit)])
async def my_questions(link: dict = Depends(manage_link), rid: str = Depends(request_id)):
    """정보부족(또는 우대 요건 모름)으로 남은 보완질문. 같은 요건은 한 번만."""
    async with transaction(None, f"{rid}|company-link:{link['link_id']}") as conn:
        run_id = await _company_run(conn, link["organization_id"], False, False, "COMPANY_LINK")
        res = await run_results(conn, run_id)
    out: dict[int, dict] = {}
    for r in res["recommendations"]:
        if r["verdict"] == "INELIGIBLE":
            continue   # 이미 부적격이면 답해도 바뀌지 않는다
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
    """보완질문에 답한다 (같은 요건은 최신 답 하나). 답한 뒤 다시 판정한 결과를 돌려준다.
    답은 '자가 신고'로 표시된다."""
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
