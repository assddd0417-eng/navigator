"""통합기획 검토: 이어달리기 후보 검토표 · 통합기획 자료 초안 · 통합기획 회의 결정.

- 만들기(검토표·초안·회의·회의 결정)는 기획자, 보기는 기획자·담당부서 검수자.
- 검토표 항목은 생성 시점 사본이다. 볼 때는 검토표 등급과 항목별 추천 열람 권한을 다시 확인한다.
- 회의 결정은 후속조치 기록이다. 추천의 최종판정(채택·보류·제외)은 기존처럼 담당부서 검수자가 한다.
"""
import json
from datetime import date, datetime
from io import BytesIO
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import Conflict, NotFound
from app.repositories.sql import CLEARANCE_OK, insert
from app.schemas.common import Created
from app.services.review_sheet import DECISION_KO, SCOPE_KO, STATUS_KO, render_draft, select_candidates, snapshot

router = APIRouter(tags=["통합기획 검토"])
READERS = ("PLANNER", "DEPT_REVIEWER")
_OK = CLEARANCE_OK.format
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Scope = Literal["COMPLETED_PROJECT_UTILIZATION", "CROSS_PROGRAM", "DEMAND", "CUSTOM"]


class SheetIn(BaseModel):
    sheet_scope: Scope = "CUSTOM"
    department_id: int | None = Field(None, description="대상 부서 (비우면 전체)")
    demand_id: int | None = Field(None, description="DEMAND 범위일 때 신규 기획수요")
    meeting_id: int | None = None
    title: str | None = None
    per_target: int = Field(5, ge=1, le=20, description="수요(매칭 실행)마다 상위 몇 건")
    limit: int = Field(30, ge=1, le=100)


class SheetPatch(BaseModel):
    meeting_id: int | None = None
    title: str | None = Field(None, min_length=2)


class MeetingIn(BaseModel):
    title: str = Field(min_length=2)
    held_at: datetime | None = None
    host_dept_id: int | None = None
    department_ids: list[int] = []


class MeetingPatch(BaseModel):
    status: Literal["SCHEDULED", "HELD", "CANCELLED"] | None = None
    held_at: datetime | None = None


class DecisionIn(BaseModel):
    decision: str = Field(min_length=2, description="결정 내용")
    recommendation_id: int | None = None
    follow_up_action: str | None = None
    owner_dept_id: int | None = None
    due_date: date | None = None


class DecisionPatch(BaseModel):
    status: Literal["OPEN", "DONE", "DROPPED"]


class DraftPatch(BaseModel):
    status: Literal["DRAFT", "REVIEWED", "FINAL"]


# ---------------------------------------------------------------------------
# 공통 조회
# ---------------------------------------------------------------------------
async def _sheet(conn, sheet_id: int, uid: int) -> dict:
    s = await (await conn.execute(
        f"""SELECT s.*, d.name AS department_name, m.title AS meeting_title, u.name AS created_by_name,
                   fu.name AS finalized_by_name, pd.demand_no, pd.title AS demand_title
              FROM ax.relay_review_sheet s
              LEFT JOIN ax.department d ON d.id = s.department_id
              LEFT JOIN ax.planning_meeting m ON m.id = s.meeting_id
              LEFT JOIN ax.app_user u ON u.id = s.created_by
              LEFT JOIN ax.app_user fu ON fu.id = s.finalized_by
              LEFT JOIN ax.planning_demand pd ON pd.id = s.demand_id
             WHERE s.id = %(id)s AND s.status <> 'ARCHIVED' AND {_OK(col='s.security_code')}""",
        {"id": sheet_id, "uid": uid})).fetchone()
    if s is None:
        raise NotFound("검토표", sheet_id)
    s["scope_name"] = SCOPE_KO.get(s["sheet_scope"], s["sheet_scope"])
    return s


async def _items(conn, sheet_id: int, uid: int) -> list[dict]:
    """항목 사본 + 지금 검토 상태. 지금 볼 수 없는 추천(등급 변경 등)은 뺀다."""
    rows = await (await conn.execute(
        """SELECT i.recommendation_id, i.sort_order, i.snapshot, r.status, r.final_decision_code,
                  r.final_linkage_type_code, lt.name_ko AS final_linkage_type_name,
                  (SELECT jsonb_build_object('decision_code', rd.decision_code, 'opinion', rd.opinion,
                                             'reviewer', u.name)
                     FROM ax.review_decision rd JOIN ax.app_user u ON u.id = rd.reviewer_id
                    WHERE rd.recommendation_id = r.id AND rd.is_final ORDER BY rd.id DESC LIMIT 1) AS final_decision
             FROM ax.relay_review_sheet_item i
             JOIN ax.recommendation r ON r.id = i.recommendation_id
             LEFT JOIN ax.code_linkage_type lt ON lt.code = r.final_linkage_type_code
            WHERE i.sheet_id = %s AND ax.can_view_recommendation(%s, i.recommendation_id)
            ORDER BY i.sort_order""", (sheet_id, uid))).fetchall()
    out = []
    for r in rows:
        live = {k: r[k] for k in ("status", "final_decision_code", "final_linkage_type_code",
                                  "final_linkage_type_name", "final_decision")}
        live["status_name"] = STATUS_KO.get(r["status"], r["status"])
        live["final_decision_name"] = DECISION_KO.get(r["final_decision_code"]) if r["final_decision_code"] else None
        out.append({"recommendation_id": r["recommendation_id"], "sort_order": r["sort_order"],
                    "snapshot": r["snapshot"], "live": live})
    return out


def _summary(items: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    for i in items:
        name = i["snapshot"]["linkage_type_name"]
        by_type[name] = by_type.get(name, 0) + 1
    decided = sum(1 for i in items if i["live"]["final_decision_code"])
    adopted = sum(1 for i in items if i["live"]["final_decision_code"] == "ADOPT")
    return {"candidates": len(items), "decided": decided, "adopted": adopted,
            "final_review_rate_pct": round(decided * 100 / len(items), 1) if items else 0.0,
            "evidence_linked": sum(1 for i in items if i["snapshot"]["evidence_count"]),
            "by_linkage_type": by_type}


async def _visible_meeting(conn, meeting_id: int) -> dict:
    m = await (await conn.execute(
        """SELECT m.*, d.name AS host_dept_name FROM ax.planning_meeting m
             LEFT JOIN ax.department d ON d.id = m.host_dept_id WHERE m.id = %s""", (meeting_id,))).fetchone()
    if m is None:
        raise NotFound("통합기획 회의", meeting_id)
    return m


async def _meeting_decisions(conn, meeting_id: int, uid: int) -> list[dict]:
    return await (await conn.execute(
        """SELECT md.*, d.name AS owner_dept_name, u.name AS decided_by_name
             FROM ax.meeting_decision md
             LEFT JOIN ax.department d ON d.id = md.owner_dept_id
             LEFT JOIN ax.app_user u ON u.id = md.decided_by
            WHERE md.meeting_id = %s
              AND (md.recommendation_id IS NULL OR ax.can_view_recommendation(%s, md.recommendation_id))
            ORDER BY md.id""", (meeting_id, uid))).fetchall()


# ---------------------------------------------------------------------------
# 검토표
# ---------------------------------------------------------------------------
@router.post("/review-sheets", response_model=Created, status_code=201)
async def create_sheet(body: SheetIn, user: CurrentUser = Depends(require_roles("PLANNER")),
                       rid: str = Depends(request_id)):
    """조건에 맞는 추천으로 검토표를 만든다. 수요·순위 순, 각 추천의 근거·담당부서·판정 상태를 사본으로 남긴다."""
    if body.sheet_scope == "DEMAND" and body.demand_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "신규 기획수요 대상 검토표는 기획수요를 골라 주세요")
    async with transaction(user.id, rid) as conn:
        if body.meeting_id is not None:
            await _visible_meeting(conn, body.meeting_id)
        ids = await select_candidates(conn, user.id, body.sheet_scope, body.department_id, body.demand_id,
                                      body.per_target, body.limit)
        if not ids:
            raise Conflict("조건에 맞는 추천이 없습니다. 먼저 '연계 후보 찾기'에서 AI 추천을 실행해 주세요")
        snaps = [await snapshot(conn, user.id, i) for i in ids]
        top_rank = max(1, max(r for _, r, _ in snaps))  # 최소 '내부'
        sec = (await (await conn.execute(
            "SELECT code FROM ax.code_security_level WHERE level_rank = %s", (top_rank,))).fetchone())["code"]
        title = body.title
        if not title:
            dept = None
            if body.department_id:
                row = await (await conn.execute("SELECT name FROM ax.department WHERE id = %s",
                                                (body.department_id,))).fetchone()
                dept = row["name"] if row else None
            title = f"{dept + ' ' if dept else ''}{SCOPE_KO[body.sheet_scope]} 검토표 ({date.today():%Y-%m-%d})"
        sheet_id = await insert(conn, "relay_review_sheet", {
            "title": title, "department_id": body.department_id, "meeting_id": body.meeting_id,
            "sheet_scope": body.sheet_scope, "demand_id": body.demand_id, "status": "DRAFT", "generated_by": "AI",
            "security_code": sec, "created_by": user.id,
            "criteria": body.model_dump(exclude={"title", "meeting_id"})})
        for n, (snap, _, _) in enumerate(snaps, start=1):
            await conn.execute(
                "INSERT INTO ax.relay_review_sheet_item (sheet_id, recommendation_id, sort_order, snapshot) "
                "VALUES (%s, %s, %s, %s)",
                (sheet_id, snap["recommendation_id"], n, json.dumps(snap, ensure_ascii=False, default=str)))
    return Created(id=sheet_id)


@router.get("/review-sheets")
async def list_sheets(meeting_id: int | None = None, user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT s.id, s.title, s.sheet_scope, s.status, s.security_code, s.created_at, s.finalized_at,
                       d.name AS department_name, m.title AS meeting_title, s.meeting_id,
                       (SELECT count(*) FROM ax.relay_review_sheet_item i WHERE i.sheet_id = s.id) AS item_count,
                       (SELECT count(*) FROM ax.relay_review_sheet_item i JOIN ax.recommendation r
                          ON r.id = i.recommendation_id
                         WHERE i.sheet_id = s.id AND r.final_decision_code IS NOT NULL) AS decided_count,
                       (SELECT count(*) FROM ax.planning_draft pdr WHERE pdr.sheet_id = s.id) AS draft_count
                  FROM ax.relay_review_sheet s
                  LEFT JOIN ax.department d ON d.id = s.department_id
                  LEFT JOIN ax.planning_meeting m ON m.id = s.meeting_id
                 WHERE s.status <> 'ARCHIVED' AND {_OK(col='s.security_code')}
                   AND (%(meeting)s::bigint IS NULL OR s.meeting_id = %(meeting)s)
                 ORDER BY s.id DESC""", {"uid": user.id, "meeting": meeting_id})).fetchall()


@router.get("/review-sheets/{sheet_id}")
async def get_sheet(sheet_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    """검토표: 항목 사본 + 지금 검토 상태 + 요약(담당부서 최종 검토율 등) + 초안 목록."""
    async with transaction(user.id) as conn:
        s = await _sheet(conn, sheet_id, user.id)
        s["items"] = await _items(conn, sheet_id, user.id)
        s["summary"] = _summary(s["items"])
        s["drafts"] = await (await conn.execute(
            "SELECT id, title, version, status, created_at FROM ax.planning_draft WHERE sheet_id = %s ORDER BY version DESC",
            (sheet_id,))).fetchall()
    return s


@router.patch("/review-sheets/{sheet_id}", status_code=204)
async def patch_sheet(sheet_id: int, body: SheetPatch, user: CurrentUser = Depends(require_roles("PLANNER")),
                      rid: str = Depends(request_id)):
    """회의에 올리기(meeting_id) · 제목 바꾸기."""
    async with transaction(user.id, rid) as conn:
        await _sheet(conn, sheet_id, user.id)
        data = body.model_dump(exclude_unset=True)
        if data.get("meeting_id") is not None:
            await _visible_meeting(conn, data["meeting_id"])
        if data:
            sets = ", ".join(f"{k} = %({k})s" for k in data)
            await conn.execute(f"UPDATE ax.relay_review_sheet SET {sets} WHERE id = %(id)s", {**data, "id": sheet_id})


@router.post("/review-sheets/{sheet_id}/finalize", status_code=204)
async def finalize_sheet(sheet_id: int, user: CurrentUser = Depends(require_roles("PLANNER")),
                         rid: str = Depends(request_id)):
    """검토표 확정: 이후 항목을 바꿀 수 없다 (회의자료로 고정)."""
    async with transaction(user.id, rid) as conn:
        await _sheet(conn, sheet_id, user.id)
        cur = await conn.execute(
            "UPDATE ax.relay_review_sheet SET status = 'FINALIZED', finalized_by = %s, finalized_at = now() "
            "WHERE id = %s AND status = 'DRAFT'", (user.id, sheet_id))
        if cur.rowcount == 0:
            raise Conflict("이미 확정된 검토표입니다")


@router.delete("/review-sheets/{sheet_id}/items/{rec_id}", status_code=204)
async def remove_item(sheet_id: int, rec_id: int, user: CurrentUser = Depends(require_roles("PLANNER")),
                      rid: str = Depends(request_id)):
    """확정 전 검토표에서 후보 하나를 뺀다."""
    async with transaction(user.id, rid) as conn:
        await _sheet(conn, sheet_id, user.id)
        cur = await conn.execute(
            "DELETE FROM ax.relay_review_sheet_item WHERE sheet_id = %s AND recommendation_id = %s "
            "AND ax.can_view_recommendation(%s, recommendation_id)", (sheet_id, rec_id, user.id))
        if cur.rowcount == 0:
            raise NotFound("검토표 항목", rec_id)


@router.get("/review-sheets/{sheet_id}/export.xlsx")
async def export_sheet(sheet_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    """회의자료용 엑셀: 검토표 · 회의 결정(회의에 올린 경우) · 작성기준."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    async with transaction(user.id) as conn:
        s = await _sheet(conn, sheet_id, user.id)
        items = await _items(conn, sheet_id, user.id)
        decisions = await _meeting_decisions(conn, s["meeting_id"], user.id) if s["meeting_id"] else []
    rows = []
    for n, i in enumerate(items, start=1):
        sn, lv = i["snapshot"], i["live"]
        fd = lv["final_decision"] or {}
        rows.append([
            n, sn["demand_title"] or sn["target_program_name"] or "",
            ", ".join(f"{c['title']} ({c['project_no']})" for c in sn["source_cards"]),
            ", ".join(sorted({c["department"] for c in sn["source_cards"] if c["department"]})),
            sn["linkage_type_name"], lv["final_linkage_type_name"] or "", round(sn["total_score"], 3),
            sn["rationale"], sn["development_needs"] or "",
            "\n".join(f"{e['document_title']}" + (f" p.{e['page_start']}" if e["page_start"] else "")
                      + f": {e['quote']}" for e in sn["evidence"]),
            ", ".join(sn["owner_departments"]), ", ".join(sn["collab_departments"]), ", ".join(sn["companies"]),
            sn["open_confirmations"] or "", lv["status_name"], lv["final_decision_name"] or "", fd.get("opinion") or "",
        ])
    header = ["번호", "연계 대상", "기존 성과 (과제번호)", "기존 과제 부서", "추천 연계유형", "최종 연계유형", "종합점수",
              "연계이유", "개발 필요사항", "원문 근거", "담당부서", "협업부서", "관련 기업 후보", "확인 필요",
              "검토 상태", "최종 판정", "판정 의견"]
    sheets = [("검토표", header, rows)]
    if decisions:
        sheets.append(("회의 결정", ["결정", "후속조치", "담당 부서", "기한", "상태"],
                       [[d["decision"], d["follow_up_action"] or "", d["owner_dept_name"] or "",
                         d["due_date"].isoformat() if d["due_date"] else "",
                         {"OPEN": "진행", "DONE": "완료", "DROPPED": "취소"}[d["status"]]] for d in decisions]))
    wb = Workbook()
    head_font, head_fill = Font(bold=True), PatternFill("solid", fgColor="E7F1FB")
    for k, (title, hdr, body_rows) in enumerate(sheets):
        ws = wb.active if k == 0 else wb.create_sheet()
        ws.title = title
        ws.append(hdr)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in body_rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        for i, h in enumerate(hdr, start=1):
            longest = max([len(str(h))] + [max((len(x) for x in str(r[i - 1]).split("\n")), default=0)
                                            for r in body_rows[:200]])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(8, longest * 1.6), 60)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
    note = wb.create_sheet("작성기준")
    for line in [["검토표", s["title"]], ["범위", s["scope_name"] + (f" / {s['department_name']}" if s["department_name"] else "")],
                 ["상태", "확정" if s["status"] == "FINALIZED" else "작성 중"],
                 ["기준일", date.today().isoformat()],
                 ["항목 기준", "검토표를 만든 시점의 추천 내용. 검토 상태·최종 판정은 내려받은 시점 기준"],
                 ["판정", "연계검토 후보이며 사업 추진 여부는 담당부서와 위원회가 판단"]]:
        note.append(line)
    note.column_dimensions["A"].width, note.column_dimensions["B"].width = 12, 90
    buf = BytesIO()
    wb.save(buf)
    name = f"이어달리기_후보검토표_{sheet_id}_{date.today():%Y%m%d}.xlsx"
    return Response(buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------------------------------------------------------------------------
# 통합기획 자료 초안
# ---------------------------------------------------------------------------
@router.post("/review-sheets/{sheet_id}/drafts", response_model=Created, status_code=201)
async def create_draft(sheet_id: int, user: CurrentUser = Depends(require_roles("PLANNER")),
                       rid: str = Depends(request_id)):
    """검토표로 통합기획 자료 초안을 만든다. 다시 만들면 판 번호가 올라간다."""
    async with transaction(user.id, rid) as conn:
        s = await _sheet(conn, sheet_id, user.id)
        items = await _items(conn, sheet_id, user.id)
        if not items:
            raise Conflict("검토표에 볼 수 있는 후보가 없습니다")
        decisions = await _meeting_decisions(conn, s["meeting_id"], user.id) if s["meeting_id"] else []
        md, struct, evidence_ids = render_draft(s, items, decisions)
        version = (await (await conn.execute(
            "SELECT COALESCE(max(version), 0) + 1 AS v FROM ax.planning_draft WHERE sheet_id = %s",
            (sheet_id,))).fetchone())["v"]
        draft_id = await insert(conn, "planning_draft", {
            "sheet_id": sheet_id, "demand_id": s["demand_id"], "title": f"통합기획 검토자료: {s['title']}",
            "version": version, "content_md": md, "content_struct": struct, "generated_by": "AI",
            "security_code": s["security_code"], "created_by": user.id})
        for n, eid in enumerate(evidence_ids, start=1):
            await conn.execute("INSERT INTO ax.planning_draft_evidence (draft_id, evidence_id, footnote_no) "
                               "VALUES (%s, %s, %s)", (draft_id, eid, n))
    return Created(id=draft_id)


async def _draft(conn, draft_id: int, uid: int) -> dict:
    d = await (await conn.execute(
        f"""SELECT pdr.id, pdr.sheet_id, pdr.title, pdr.version, pdr.status, pdr.content_md, pdr.content_struct,
                   pdr.created_at, u.name AS created_by_name
              FROM ax.planning_draft pdr LEFT JOIN ax.app_user u ON u.id = pdr.created_by
             WHERE pdr.id = %(id)s AND pdr.sheet_id IS NOT NULL AND {_OK(col='pdr.security_code')}""",
        {"id": draft_id, "uid": uid})).fetchone()
    if d is None:
        raise NotFound("통합기획 자료 초안", draft_id)
    await _sheet(conn, d["sheet_id"], uid)
    return d


@router.get("/planning-drafts/{draft_id}")
async def get_draft(draft_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        d = await _draft(conn, draft_id, user.id)
        d["evidence_count"] = (await (await conn.execute(
            "SELECT count(*) AS n FROM ax.planning_draft_evidence WHERE draft_id = %s", (draft_id,))).fetchone())["n"]
    return d


@router.get("/planning-drafts/{draft_id}/export.md")
async def export_draft(draft_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        d = await _draft(conn, draft_id, user.id)
    name = f"통합기획_검토자료_{d['sheet_id']}_v{d['version']}.md"
    return Response(d["content_md"].encode("utf-8"), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.patch("/planning-drafts/{draft_id}", status_code=204)
async def review_draft(draft_id: int, body: DraftPatch, user: CurrentUser = Depends(require_roles("PLANNER")),
                       rid: str = Depends(request_id)):
    """초안 상태: DRAFT → REVIEWED → FINAL."""
    async with transaction(user.id, rid) as conn:
        await _draft(conn, draft_id, user.id)
        await conn.execute("UPDATE ax.planning_draft SET status = %s WHERE id = %s", (body.status, draft_id))


# ---------------------------------------------------------------------------
# 통합기획 회의
# ---------------------------------------------------------------------------
@router.post("/meetings", response_model=Created, status_code=201)
async def create_meeting(body: MeetingIn, user: CurrentUser = Depends(require_roles("PLANNER")),
                         rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        mid = await insert(conn, "planning_meeting", {
            "title": body.title, "held_at": body.held_at, "host_dept_id": body.host_dept_id or user.department_id,
            "created_by": user.id})
        for d in sorted(set(body.department_ids)):
            await conn.execute("INSERT INTO ax.planning_meeting_department (meeting_id, department_id) VALUES (%s, %s)",
                               (mid, d))
    return Created(id=mid)


@router.get("/meetings")
async def list_meetings(user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT m.id, m.title, m.held_at, m.status, d.name AS host_dept_name, m.created_at,
                       (SELECT count(*) FROM ax.relay_review_sheet s
                         WHERE s.meeting_id = m.id AND s.status <> 'ARCHIVED' AND {_OK(col='s.security_code')}) AS sheet_count,
                       (SELECT count(*) FROM ax.meeting_decision md WHERE md.meeting_id = m.id) AS decision_count,
                       (SELECT count(*) FROM ax.meeting_decision md
                         WHERE md.meeting_id = m.id AND md.status = 'OPEN') AS open_count
                  FROM ax.planning_meeting m LEFT JOIN ax.department d ON d.id = m.host_dept_id
                 ORDER BY m.held_at DESC NULLS FIRST, m.id DESC""", {"uid": user.id})).fetchall()


@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        m = await _visible_meeting(conn, meeting_id)
        m["departments"] = await (await conn.execute(
            "SELECT d.id, d.name FROM ax.planning_meeting_department md JOIN ax.department d ON d.id = md.department_id "
            "WHERE md.meeting_id = %s ORDER BY d.name", (meeting_id,))).fetchall()
        m["sheets"] = await (await conn.execute(
            f"""SELECT s.id, s.title, s.status FROM ax.relay_review_sheet s
                 WHERE s.meeting_id = %(id)s AND s.status <> 'ARCHIVED' AND {_OK(col='s.security_code')}
                 ORDER BY s.id""", {"id": meeting_id, "uid": user.id})).fetchall()
        m["decisions"] = await _meeting_decisions(conn, meeting_id, user.id)
    return m


@router.patch("/meetings/{meeting_id}", status_code=204)
async def patch_meeting(meeting_id: int, body: MeetingPatch, user: CurrentUser = Depends(require_roles("PLANNER")),
                        rid: str = Depends(request_id)):
    data = body.model_dump(exclude_unset=True)
    async with transaction(user.id, rid) as conn:
        await _visible_meeting(conn, meeting_id)
        if data:
            sets = ", ".join(f"{k} = %({k})s" for k in data)
            await conn.execute(f"UPDATE ax.planning_meeting SET {sets} WHERE id = %(id)s", {**data, "id": meeting_id})


@router.post("/meetings/{meeting_id}/decisions", response_model=Created, status_code=201)
async def add_meeting_decision(meeting_id: int, body: DecisionIn, user: CurrentUser = Depends(require_roles("PLANNER")),
                               rid: str = Depends(request_id)):
    """회의 결정·후속조치. 추천에 대한 결정이면 그 추천이 이 회의에 올린 검토표에 있어야 한다."""
    async with transaction(user.id, rid) as conn:
        m = await _visible_meeting(conn, meeting_id)
        if m["status"] == "CANCELLED":
            raise Conflict("취소된 회의에는 결정을 남길 수 없습니다")
        if body.recommendation_id is not None:
            ok = await (await conn.execute(
                """SELECT 1 FROM ax.relay_review_sheet_item i JOIN ax.relay_review_sheet s ON s.id = i.sheet_id
                    WHERE s.meeting_id = %s AND i.recommendation_id = %s
                      AND ax.can_view_recommendation(%s, i.recommendation_id) LIMIT 1""",
                (meeting_id, body.recommendation_id, user.id))).fetchone()
            if ok is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                    "이 회의에 올린 검토표에 있는 추천만 결정에 연결할 수 있습니다")
        return Created(id=await insert(conn, "meeting_decision", {
            **body.model_dump(), "meeting_id": meeting_id, "decided_by": user.id}))


@router.patch("/meeting-decisions/{decision_id}", status_code=204)
async def patch_meeting_decision(decision_id: int, body: DecisionPatch,
                                 user: CurrentUser = Depends(require_roles(*READERS)), rid: str = Depends(request_id)):
    """후속조치 진행 상태. 기획자 또는 담당 부서 검수자."""
    async with transaction(user.id, rid) as conn:
        cur = await conn.execute(
            """UPDATE ax.meeting_decision SET status = %(st)s
                WHERE id = %(id)s AND (%(planner)s OR owner_dept_id = %(dept)s)
                  AND (recommendation_id IS NULL OR ax.can_view_recommendation(%(uid)s, recommendation_id))""",
            {"st": body.status, "id": decision_id, "planner": user.has_any("PLANNER"), "dept": user.department_id,
             "uid": user.id})
        if cur.rowcount == 0:
            raise NotFound("내가 바꿀 수 있는 회의 결정", decision_id)
