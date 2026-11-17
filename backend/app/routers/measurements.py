"""PoC 효과 측정: 업무시간(기존 수작업 vs AX)과 만족도 입력·집계.

제안서 정량목표: 관련 과제 조사시간 70% 이상 단축, 통합기획 검토자료 작성시간 60% 이상 단축,
추가 연계후보 수 확대, 담당자·기획부서·전문가 만족도 (정의서 91~96).
- 측정값은 본인 것으로만 입력·삭제한다. 집계·내려받기는 기획자·검수자.
"""
from datetime import date
from io import BytesIO
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import insert
from app.schemas.common import Created

router = APIRouter(prefix="/measurements", tags=["PoC 효과 측정"])
WRITERS = ("PLANNER", "DEPT_REVIEWER", "EXPERT", "CURATOR")
READERS = ("PLANNER", "DEPT_REVIEWER")

TaskType = Literal["RESEARCH", "DOCUMENT_READING", "CANDIDATE_LIST", "REVIEW_MATERIAL"]
TASKS = {  # 업무 → (이름, 제안서 목표 단축률 %)
    "RESEARCH": ("관련 성과·과제 조사", 70),
    "DOCUMENT_READING": ("자료 열람", None),
    "CANDIDATE_LIST": ("후보목록 작성", None),
    "REVIEW_MATERIAL": ("통합기획 검토자료 작성", 60),
}
ASPECTS = {"usefulness": "추천이 쓸모 있음", "evidence": "근거가 믿을 만함", "ease": "쓰기 쉬움",
           "time_saving": "시간이 줄었음"}


class WorkTimeIn(BaseModel):
    task_type: TaskType
    method: Literal["MANUAL", "AX"]
    minutes: float = Field(gt=0, le=60 * 24 * 10)
    demand_id: int | None = None
    candidates_found: int | None = Field(None, ge=0)
    measured_on: date | None = None
    note: str | None = None


class SurveyIn(BaseModel):
    score: int = Field(ge=1, le=5, description="전체 만족도 1~5")
    aspects: dict[Literal["usefulness", "evidence", "ease", "time_saving"], int] = {}
    comment: str | None = None


def _role(user: CurrentUser) -> str:
    for r in ("PLANNER", "DEPT_REVIEWER", "EXPERT"):
        if r in user.roles:
            return r
    return "OTHER"


@router.post("/work-time", response_model=Created, status_code=201)
async def add_work_time(body: WorkTimeIn, user: CurrentUser = Depends(require_roles(*WRITERS)),
                        rid: str = Depends(request_id)):
    data = body.model_dump(exclude_none=True)
    async with transaction(user.id, rid) as conn:
        return Created(id=await insert(conn, "work_time_measurement", {**data, "user_id": user.id}))


@router.get("/work-time")
async def list_work_time(mine: bool = True, user: CurrentUser = Depends(require_roles(*WRITERS))):
    """측정 기록. 기획자·검수자는 mine=false 로 전체를 본다."""
    show_all = not mine and user.has_any(*READERS)
    async with transaction(user.id) as conn:
        rows = await (await conn.execute(
            """SELECT w.id, w.task_type, w.method, w.minutes::float AS minutes, w.candidates_found, w.measured_on,
                      w.note, w.demand_id, pd.demand_no, u.name AS user_name, w.user_id
                 FROM ax.work_time_measurement w
                 LEFT JOIN ax.app_user u ON u.id = w.user_id
                 LEFT JOIN ax.planning_demand pd ON pd.id = w.demand_id
                WHERE %(all)s OR w.user_id = %(uid)s
                ORDER BY w.measured_on DESC, w.id DESC""", {"all": show_all, "uid": user.id})).fetchall()
    for r in rows:
        r["task_name"] = TASKS[r["task_type"]][0]
    return rows


@router.delete("/work-time/{mid}", status_code=204)
async def delete_work_time(mid: int, user: CurrentUser = Depends(require_roles(*WRITERS)),
                           rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        cur = await conn.execute("DELETE FROM ax.work_time_measurement WHERE id = %s AND user_id = %s", (mid, user.id))
        if cur.rowcount == 0:
            raise NotFound("내 측정 기록", mid)


@router.post("/surveys", response_model=Created, status_code=201)
async def add_survey(body: SurveyIn, user: CurrentUser = Depends(require_roles(*WRITERS)),
                     rid: str = Depends(request_id)):
    for k, v in body.aspects.items():
        if not 1 <= v <= 5:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{ASPECTS[k]} 점수는 1~5")
    async with transaction(user.id, rid) as conn:
        return Created(id=await insert(conn, "satisfaction_survey", {
            "user_id": user.id, "respondent_role": _role(user), "score": body.score,
            "aspects": dict(body.aspects), "comment": body.comment}))


async def _summary(conn) -> dict:
    rows = await (await conn.execute(
        """SELECT task_type,
                  count(*) FILTER (WHERE method = 'MANUAL') AS manual_n,
                  count(*) FILTER (WHERE method = 'AX') AS ax_n,
                  round(avg(minutes) FILTER (WHERE method = 'MANUAL'), 1)::float AS manual_avg,
                  round(avg(minutes) FILTER (WHERE method = 'AX'), 1)::float AS ax_avg,
                  round(avg(candidates_found) FILTER (WHERE method = 'MANUAL'), 1)::float AS manual_candidates,
                  round(avg(candidates_found) FILTER (WHERE method = 'AX'), 1)::float AS ax_candidates
             FROM ax.work_time_measurement GROUP BY task_type""")).fetchall()
    by = {r["task_type"]: r for r in rows}
    tasks = []
    for code, (name, target) in TASKS.items():
        r = by.get(code, {"manual_n": 0, "ax_n": 0, "manual_avg": None, "ax_avg": None,
                          "manual_candidates": None, "ax_candidates": None})
        red = (round(100 * (1 - r["ax_avg"] / r["manual_avg"]), 1)
               if r["manual_avg"] and r["ax_avg"] is not None else None)
        tasks.append({"task_type": code, "task_name": name, "target_pct": target, **{k: r[k] for k in (
            "manual_n", "ax_n", "manual_avg", "ax_avg", "manual_candidates", "ax_candidates")},
            "reduction_pct": red, "met": None if red is None or target is None else red >= target})
    s = await (await conn.execute(
        """SELECT count(*) AS n, round(avg(score), 2)::float AS avg_score,
                  COALESCE(jsonb_object_agg(respondent_role, role_avg) FILTER (WHERE respondent_role IS NOT NULL), '{}')
                    AS by_role
             FROM (SELECT respondent_role, score,
                          round(avg(score) OVER (PARTITION BY respondent_role), 2) AS role_avg
                     FROM ax.satisfaction_survey) x""")).fetchone()
    aspects = await (await conn.execute(
        """SELECT key, round(avg(value::int), 2)::float AS avg, count(*) AS n
             FROM ax.satisfaction_survey, jsonb_each_text(aspects) GROUP BY key""")).fetchall()
    total_manual = sum(t["manual_avg"] or 0 for t in tasks if t["manual_avg"] and t["ax_avg"] is not None)
    total_ax = sum(t["ax_avg"] or 0 for t in tasks if t["manual_avg"] and t["ax_avg"] is not None)
    return {
        "tasks": tasks,
        "overall_reduction_pct": round(100 * (1 - total_ax / total_manual), 1) if total_manual else None,
        "survey": {"n": s["n"], "avg_score": s["avg_score"], "by_role": s["by_role"],
                   "aspects": [{"key": a["key"], "name": ASPECTS.get(a["key"], a["key"]), "avg": a["avg"], "n": a["n"]}
                               for a in aspects]},
    }


@router.get("/summary")
async def summary(user: CurrentUser = Depends(require_roles(*READERS))):
    """업무별 평균 시간(수작업 vs AX)·단축률·목표 달성, 추가 후보 수, 만족도."""
    async with transaction(user.id) as conn:
        return await _summary(conn)


@router.get("/export.xlsx")
async def export(user: CurrentUser = Depends(require_roles(*READERS)),
                 since: date | None = Query(None, description="이 날짜 이후 측정만")):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    async with transaction(user.id) as conn:
        sm = await _summary(conn)
        rows = await (await conn.execute(
            """SELECT w.measured_on, w.task_type, w.method, w.minutes::float AS minutes, w.candidates_found,
                      u.name AS user_name, pd.demand_no, w.note
                 FROM ax.work_time_measurement w LEFT JOIN ax.app_user u ON u.id = w.user_id
                 LEFT JOIN ax.planning_demand pd ON pd.id = w.demand_id
                WHERE %(since)s::date IS NULL OR w.measured_on >= %(since)s
                ORDER BY w.measured_on, w.id""", {"since": since})).fetchall()
        surveys = await (await conn.execute(
            "SELECT submitted_at::date AS d, respondent_role, score, aspects, comment FROM ax.satisfaction_survey "
            "ORDER BY id")).fetchall()
    role_ko = {"PLANNER": "기획자", "DEPT_REVIEWER": "담당부서 검수자", "EXPERT": "전문가", "OTHER": "기타"}
    wb = Workbook()
    head = (Font(bold=True), PatternFill("solid", fgColor="E7F1FB"))
    sheets = [
        ("업무시간 요약", ["업무", "목표 단축률(%)", "수작업 건수", "수작업 평균(분)", "AX 건수", "AX 평균(분)",
                     "단축률(%)", "목표 달성", "수작업 후보 수(평균)", "AX 후보 수(평균)"],
         [[t["task_name"], t["target_pct"] or "", t["manual_n"], t["manual_avg"], t["ax_n"], t["ax_avg"],
           t["reduction_pct"], "" if t["met"] is None else ("달성" if t["met"] else "미달"),
           t["manual_candidates"], t["ax_candidates"]] for t in sm["tasks"]]),
        ("업무시간 기록", ["측정일", "업무", "방식", "시간(분)", "찾은 후보 수", "측정자", "기획수요", "메모"],
         [[r["measured_on"], TASKS[r["task_type"]][0], "수작업" if r["method"] == "MANUAL" else "AX", r["minutes"],
           r["candidates_found"], r["user_name"], r["demand_no"], r["note"]] for r in rows]),
        ("만족도", ["응답일", "응답자", "전체(1~5)", *ASPECTS.values(), "의견"],
         [[s["d"], role_ko.get(s["respondent_role"], ""), s["score"], *(s["aspects"].get(k) for k in ASPECTS),
           s["comment"]] for s in surveys]),
    ]
    for i, (title, header, body) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head
        for r in body:
            ws.append(r)
        for j, h in enumerate(header, start=1):
            ws.column_dimensions[ws.cell(1, j).column_letter].width = max(10, len(h) * 1.8)
    buf = BytesIO()
    wb.save(buf)
    name = f"효과측정_{date.today():%Y%m%d}.xlsx"
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
