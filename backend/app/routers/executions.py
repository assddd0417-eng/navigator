"""연계 실행 결과와 순환 구조: 채택된 추천이 실제 과제·사업화·수출로 이어졌는지 기록하고, 그 결과를 다시 쌓는다.

순환 고리
  1) 기존 성과 → (추천·채택) → 연계 실행 기록 → 이어진 신규 과제
  2) 이어진 과제는 과제 관계(선행 → 후속, 실제 이어달리기)로 남아, 과제가 끝나면 그 성과카드가 다시 '기존 성과'가 된다.
  3) 끝난(COMPLETED) 실행은 '실제 연계 사례' 검증 케이스로 만들어 추천 적중률 측정에 쓴다 (정의서 73·97).
권한: 기록은 기획자 또는 그 추천의 담당부서 검수자. 보기는 기획자·검수자. 열람 등급 밖 실행은 목록·집계에서 뺀다.
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import CLEARANCE_OK, insert
from app.schemas.common import Created

router = APIRouter(prefix="/executions", tags=["연계 실행·순환"])
READERS = ("PLANNER", "DEPT_REVIEWER")
_OK = CLEARANCE_OK.format

ExecType = Literal["NEW_PROJECT", "PROGRAM_APPLICATION", "TECH_TRANSFER", "COMMERCIALIZATION", "EXPORT",
                   "LOCALIZATION", "PILOT_TEST", "OTHER"]
ExecStatus = Literal["PLANNED", "IN_PROGRESS", "COMPLETED", "DROPPED"]
EXEC_TYPE_KO = {"NEW_PROJECT": "신규 과제", "PROGRAM_APPLICATION": "타 사업 신청", "TECH_TRANSFER": "기술이전",
                "COMMERCIALIZATION": "사업화", "EXPORT": "수출", "LOCALIZATION": "부품 국산화",
                "PILOT_TEST": "시험·실증", "OTHER": "기타"}
STATUS_KO = {"PLANNED": "계획", "IN_PROGRESS": "진행 중", "COMPLETED": "완료", "DROPPED": "중단"}


class NewProject(BaseModel):
    project_no: str = Field(min_length=2, description="이어진 과제의 과제번호 (PMS 등록 전이면 임시 번호)")
    title: str = Field(min_length=2)
    program_id: int | None = None
    department_id: int | None = None
    start_date: date | None = None


class ExecutionIn(BaseModel):
    recommendation_id: int | None = Field(None, description="채택된 추천 (AI 추천 없이 발굴한 연계면 비움)")
    source_card_id: int | None = Field(None, description="출처 성과 (추천이면 비워도 첫 출처 성과)")
    linkage_type_code: str | None = None
    execution_type: ExecType
    status: ExecStatus = "PLANNED"
    resulting_project_id: int | None = None
    new_project: NewProject | None = None
    organization_id: int | None = None
    executed_on: date | None = None
    discovered_by_ax: bool | None = None
    meeting_decision_id: int | None = None
    note: str | None = None
    result_note: str | None = None


class ExecutionPatch(BaseModel):
    status: ExecStatus | None = None
    executed_on: date | None = None
    result_note: str | None = None
    note: str | None = None
    resulting_project_id: int | None = None
    new_project: NewProject | None = None


async def _rank(conn, code: str) -> int:
    return (await (await conn.execute("SELECT level_rank FROM ax.code_security_level WHERE code = %s",
                                      (code,))).fetchone())["level_rank"]


async def _can_record(conn, user: CurrentUser, rec_id: int | None) -> None:
    """기획자 또는 그 추천의 담당부서(OWNER) 검수자."""
    if user.has_any("PLANNER"):
        return
    if rec_id is not None and user.department_id is not None:
        row = await (await conn.execute(
            "SELECT 1 FROM ax.recommendation_department WHERE recommendation_id = %s AND role = 'OWNER' "
            "AND department_id = %s", (rec_id, user.department_id))).fetchone()
        if row:
            return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "기획자 또는 그 추천의 담당부서 검수자만 기록할 수 있습니다")


async def _resolve_project(conn, user: CurrentUser, project_id: int | None, new: NewProject | None,
                           security_code: str) -> int | None:
    if new is not None:
        row = await (await conn.execute("SELECT id FROM ax.project WHERE project_no = %s", (new.project_no,))).fetchone()
        if row:
            return row["id"]
        return await insert(conn, "project", {
            **new.model_dump(), "department_id": new.department_id or user.department_id, "status_code": "PLANNING",
            "security_code": security_code, "source_system_code": "MANUAL"})
    if project_id is not None:
        row = await (await conn.execute(
            f"SELECT id FROM ax.project p WHERE p.id = %(id)s AND {_OK(col='p.security_code')}",
            {"id": project_id, "uid": user.id})).fetchone()
        if row is None:
            raise NotFound("과제", project_id)
    return project_id


async def _relate(conn, user: CurrentUser, ex: dict) -> int | None:
    """출처 성과의 과제 → 이어진 과제를 '실제 이어달리기' 과제 관계로 남긴다 (이미 있으면 확인 표시만)."""
    if not ex["resulting_project_id"]:
        return None
    row = await (await conn.execute(
        """INSERT INTO ax.project_relation (from_project_id, to_project_id, relation_type, linkage_type_code,
                                            is_actual_relay, verified_by, note)
           SELECT ac.project_id, %(to)s, 'PRECEDES', %(lt)s, true, %(uid)s, %(note)s
             FROM ax.achievement_card ac WHERE ac.id = %(card)s
           ON CONFLICT (from_project_id, to_project_id, relation_type)
           DO UPDATE SET is_actual_relay = true, linkage_type_code = COALESCE(ax.project_relation.linkage_type_code,
                                                                              EXCLUDED.linkage_type_code)
           RETURNING id""",
        {"to": ex["resulting_project_id"], "lt": ex["linkage_type_code"], "uid": user.id, "card": ex["source_card_id"],
         "note": f"연계 실행 기록 {ex['id']}"})).fetchone()
    return row["id"] if row else None


async def _to_eval_case(conn, user: CurrentUser, ex: dict, relation_id: int | None) -> int | None:
    """완료된 실행 → 실제 연계 사례 검증 케이스 (기획수요가 있는 추천일 때만, 한 번만)."""
    if ex["status"] != "COMPLETED" or not ex["recommendation_id"]:
        return None
    rec = await (await conn.execute(
        """SELECT r.demand_id, pd.title AS demand_title, ac.title AS card_title
             FROM ax.recommendation r JOIN ax.planning_demand pd ON pd.id = r.demand_id
             JOIN ax.achievement_card ac ON ac.id = %s
            WHERE r.id = %s""", (ex["source_card_id"], ex["recommendation_id"]))).fetchone()
    if rec is None:
        return None
    existing = await (await conn.execute("SELECT id FROM ax.eval_case WHERE origin_execution_id = %s",
                                         (ex["id"],))).fetchone()
    if existing:
        return existing["id"]
    case_id = await insert(conn, "eval_case", {
        "name": f"실제 연계: {rec['card_title']} → {rec['demand_title']}", "case_type": "HISTORICAL_RELAY",
        "query_type": "DEMAND", "demand_id": rec["demand_id"], "project_relation_id": relation_id,
        "origin_execution_id": ex["id"], "note": "연계 실행 결과에서 자동 생성", "created_by": user.id})
    await insert(conn, "eval_ground_truth", {
        "case_id": case_id, "expected_card_id": ex["source_card_id"], "expected_project_id": ex["resulting_project_id"],
        "linkage_type_code": ex["linkage_type_code"], "importance": "MAJOR", "expert_id": user.id,
        "opinion": f"실제 {EXEC_TYPE_KO[ex['execution_type']]}(으)로 이어진 사례"})
    return case_id


async def _after_write(conn, user: CurrentUser, ex_id: int) -> dict:
    ex = await (await conn.execute("SELECT * FROM ax.linkage_execution WHERE id = %s", (ex_id,))).fetchone()
    relation_id = await _relate(conn, user, ex)
    case_id = await _to_eval_case(conn, user, ex, relation_id)
    return {"id": ex_id, "project_relation_id": relation_id, "eval_case_id": case_id}


# ---------------------------------------------------------------------------
@router.get("/candidates")
async def candidates(user: CurrentUser = Depends(require_roles(*READERS))):
    """담당부서가 채택한 추천 (실행 기록 대기 여부 포함)."""
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            """SELECT o.recommendation_id, o.demand_id, o.demand_title, o.target_program_name,
                      COALESCE(o.final_linkage_type_code, o.linkage_type_code) AS linkage_type_code,
                      lt.name_ko AS linkage_type_name, o.source_cards, o.owner_department,
                      r.final_decided_at,
                      (SELECT count(*) FROM ax.linkage_execution le WHERE le.recommendation_id = r.id) AS execution_count
                 FROM ax.v_recommendation_overview o
                 JOIN ax.recommendation r ON r.id = o.recommendation_id
                 JOIN ax.code_linkage_type lt ON lt.code = COALESCE(o.final_linkage_type_code, o.linkage_type_code)
                WHERE r.final_decision_code = 'ADOPT' AND ax.can_view_recommendation(%s, r.id)
                ORDER BY (SELECT count(*) FROM ax.linkage_execution le WHERE le.recommendation_id = r.id),
                         r.final_decided_at DESC NULLS LAST""", (user.id,))).fetchall()


@router.post("", status_code=201)
async def create_execution(body: ExecutionIn, user: CurrentUser = Depends(require_roles(*READERS)),
                           rid: str = Depends(request_id)):
    """연계 실행을 기록한다. 이어진 과제가 있으면 과제 관계(실제 이어달리기)를 남기고,
    완료로 기록하면 실제 연계 사례 검증 케이스를 만든다."""
    async with transaction(user.id, rid) as conn:
        await _can_record(conn, user, body.recommendation_id)
        card_id, linkage = body.source_card_id, body.linkage_type_code
        if body.recommendation_id is not None:
            rec = await (await conn.execute(
                """SELECT r.id, COALESCE(r.final_linkage_type_code, r.linkage_type_code) AS lt,
                          (SELECT rsc.card_id FROM ax.recommendation_source_card rsc
                            WHERE rsc.recommendation_id = r.id ORDER BY rsc.role, rsc.card_id LIMIT 1) AS card_id
                     FROM ax.recommendation r
                    WHERE r.id = %s AND ax.can_view_recommendation(%s, r.id)""",
                (body.recommendation_id, user.id))).fetchone()
            if rec is None:
                raise NotFound("추천", body.recommendation_id)
            card_id, linkage = card_id or rec["card_id"], linkage or rec["lt"]
        if card_id is None or linkage is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "추천이 없으면 출처 성과와 연계유형을 골라 주세요")
        card = await (await conn.execute(
            f"SELECT id, security_code FROM ax.achievement_card ac WHERE ac.id = %(id)s AND {_OK(col='ac.security_code')}",
            {"id": card_id, "uid": user.id})).fetchone()
        if card is None:
            raise NotFound("성과카드", card_id)
        sec = card["security_code"] if await _rank(conn, card["security_code"]) >= 1 else "INTERNAL"
        project_id = await _resolve_project(conn, user, body.resulting_project_id, body.new_project, sec)
        ex_id = await insert(conn, "linkage_execution", {
            "recommendation_id": body.recommendation_id, "source_card_id": card_id, "linkage_type_code": linkage,
            "execution_type": body.execution_type, "status": body.status, "resulting_project_id": project_id,
            "organization_id": body.organization_id, "executed_on": body.executed_on,
            "discovered_by_ax": body.discovered_by_ax if body.discovered_by_ax is not None
            else body.recommendation_id is not None,
            "meeting_decision_id": body.meeting_decision_id, "note": body.note, "result_note": body.result_note,
            "security_code": sec, "created_by": user.id})
        return await _after_write(conn, user, ex_id)


@router.patch("/{ex_id}")
async def patch_execution(ex_id: int, body: ExecutionPatch, user: CurrentUser = Depends(require_roles(*READERS)),
                          rid: str = Depends(request_id)):
    """진행 상태·결과 갱신. 완료로 바꾸면 검증 케이스가 생긴다."""
    async with transaction(user.id, rid) as conn:
        ex = await _visible(conn, ex_id, user.id)
        await _can_record(conn, user, ex["recommendation_id"])
        data = body.model_dump(exclude_unset=True, exclude={"new_project", "resulting_project_id"})
        if "resulting_project_id" in body.model_fields_set or body.new_project is not None:
            data["resulting_project_id"] = await _resolve_project(conn, user, body.resulting_project_id,
                                                                  body.new_project, ex["security_code"])
        if data:
            sets = ", ".join(f"{k} = %({k})s" for k in data)
            await conn.execute(f"UPDATE ax.linkage_execution SET {sets} WHERE id = %(id)s", {**data, "id": ex_id})
        return await _after_write(conn, user, ex_id)


async def _visible(conn, ex_id: int, uid: int) -> dict:
    ex = await (await conn.execute(
        f"""SELECT le.* FROM ax.linkage_execution le
             WHERE le.id = %(id)s AND {_OK(col='le.security_code')}
               AND (le.recommendation_id IS NULL OR ax.can_view_recommendation(%(uid)s, le.recommendation_id))""",
        {"id": ex_id, "uid": uid})).fetchone()
    if ex is None:
        raise NotFound("연계 실행", ex_id)
    return ex


_LIST_SQL = f"""
    SELECT le.id, le.recommendation_id, le.source_card_id, ac.card_no, ac.title AS card_title,
           sp.project_no AS source_project_no, sp.title AS source_project_title,
           le.linkage_type_code, lt.name_ko AS linkage_type_name, le.execution_type, le.status,
           le.resulting_project_id, rp.project_no AS resulting_project_no, rp.title AS resulting_project_title,
           rp.status_code AS resulting_project_status, o.name AS organization_name, le.executed_on,
           le.discovered_by_ax, le.note, le.result_note, le.meeting_decision_id, le.created_at, le.updated_at,
           u.name AS created_by_name, pd.title AS demand_title,
           (SELECT ec.id FROM ax.eval_case ec WHERE ec.origin_execution_id = le.id) AS eval_case_id,
           (SELECT count(*) FROM ax.achievement_card c2
             WHERE c2.project_id = le.resulting_project_id AND c2.status = 'PUBLISHED'
               AND {_OK(col='c2.security_code')}) AS resulting_cards
      FROM ax.linkage_execution le
      JOIN ax.achievement_card ac ON ac.id = le.source_card_id
      JOIN ax.project sp ON sp.id = ac.project_id
      JOIN ax.code_linkage_type lt ON lt.code = le.linkage_type_code
      LEFT JOIN ax.project rp ON rp.id = le.resulting_project_id
      LEFT JOIN ax.organization o ON o.id = le.organization_id
      LEFT JOIN ax.app_user u ON u.id = le.created_by
      LEFT JOIN ax.recommendation r ON r.id = le.recommendation_id
      LEFT JOIN ax.planning_demand pd ON pd.id = r.demand_id
     WHERE {_OK(col='le.security_code')}
       AND (le.recommendation_id IS NULL OR ax.can_view_recommendation(%(uid)s, le.recommendation_id))"""


@router.get("")
async def list_executions(status_: ExecStatus | None = Query(None, alias="status"), user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        rows = await (await conn.execute(
            _LIST_SQL + " AND (%(st)s::text IS NULL OR le.status = %(st)s) ORDER BY le.updated_at DESC, le.id DESC",
            {"uid": user.id, "st": status_})).fetchall()
    for r in rows:
        r["execution_type_name"] = EXEC_TYPE_KO[r["execution_type"]]
        r["status_name"] = STATUS_KO[r["status"]]
    return rows


@router.get("/kpi")
async def execution_kpi(user: CurrentUser = Depends(require_roles(*READERS))):
    """순환 지표: 채택 추천 → 실행 기록 → 신규 과제·사업화 → 그 과제의 새 성과 → 검증 케이스."""
    async with transaction(user.id) as conn:
        rows = await (await conn.execute(_LIST_SQL, {"uid": user.id})).fetchall()
        adopted = await (await conn.execute(
            """SELECT count(*) AS adopted,
                      count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ax.linkage_execution x
                                                      WHERE x.recommendation_id = r.id)) AS adopted_executed
                 FROM ax.recommendation r
                WHERE r.final_decision_code = 'ADOPT' AND ax.can_view_recommendation(%s, r.id)""",
            (user.id,))).fetchone()
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[EXEC_TYPE_KO[r["execution_type"]]] = by_type.get(EXEC_TYPE_KO[r["execution_type"]], 0) + 1
    return {
        **adopted,
        "conversion_pct": round(adopted["adopted_executed"] * 100 / adopted["adopted"], 1) if adopted["adopted"] else 0.0,
        "executions": len(rows),
        "completed": sum(r["status"] == "COMPLETED" for r in rows),
        "ongoing": sum(r["status"] in ("PLANNED", "IN_PROGRESS") for r in rows),
        "dropped": sum(r["status"] == "DROPPED" for r in rows),
        "discovered_by_ax": sum(bool(r["discovered_by_ax"]) for r in rows),
        "resulting_projects": len({r["resulting_project_id"] for r in rows if r["resulting_project_id"]}),
        "resulting_cards": sum(r["resulting_cards"] for r in {r["resulting_project_id"]: r for r in rows
                                                               if r["resulting_project_id"]}.values()),
        "eval_cases": sum(r["eval_case_id"] is not None for r in rows),
        "by_type": by_type,
    }


@router.get("/lineage/cards/{card_id}")
async def lineage(card_id: int, depth: int = 4, user: CurrentUser = Depends(require_roles(*READERS))):
    """성과의 이어달리기 계보: 앞 세대(실제 이어달리기로 이 과제를 낳은 과제의 성과)와
    뒤 세대(이 성과의 연계 실행 → 이어진 과제 → 그 과제의 성과 → …)."""
    depth = max(1, min(depth, 6))
    async with transaction(user.id) as conn:
        card = await (await conn.execute(
            f"""SELECT ac.id, ac.card_no, ac.title, ac.project_id, p.project_no, p.title AS project_title, p.status_code
                  FROM ax.achievement_card ac JOIN ax.project p ON p.id = ac.project_id
                 WHERE ac.id = %(id)s AND {_OK(col='ac.security_code')}""", {"id": card_id, "uid": user.id})).fetchone()
        if card is None:
            raise NotFound("성과카드", card_id)
        ancestors = await (await conn.execute(
            f"""WITH RECURSIVE up(project_id, lvl, linkage_type_code) AS (
                    SELECT pr.from_project_id, 1, pr.linkage_type_code FROM ax.project_relation pr
                     WHERE pr.to_project_id = %(pid)s AND pr.is_actual_relay
                    UNION
                    SELECT pr.from_project_id, up.lvl + 1, pr.linkage_type_code FROM ax.project_relation pr
                      JOIN up ON pr.to_project_id = up.project_id
                     WHERE pr.is_actual_relay AND up.lvl < %(depth)s)
                SELECT up.lvl, p.id AS project_id, p.project_no, p.title AS project_title, p.status_code,
                       lt.name_ko AS linkage_type_name,
                       (SELECT COALESCE(jsonb_agg(jsonb_build_object('card_id', c.id, 'title', c.title) ORDER BY c.id), '[]')
                          FROM ax.achievement_card c WHERE c.project_id = p.id AND c.status = 'PUBLISHED'
                           AND {_OK(col='c.security_code')}) AS cards
                  FROM up JOIN ax.project p ON p.id = up.project_id
                  LEFT JOIN ax.code_linkage_type lt ON lt.code = up.linkage_type_code
                 WHERE {_OK(col='p.security_code')}
                 ORDER BY up.lvl DESC, p.project_no""", {"pid": card["project_id"], "depth": depth, "uid": user.id})).fetchall()
        descendants = []
        frontier, seen = [card_id], {card_id}
        for lvl in range(1, depth + 1):
            if not frontier:
                break
            rows = await (await conn.execute(
                _LIST_SQL + " AND le.source_card_id = ANY(%(cards)s) ORDER BY le.id",
                {"uid": user.id, "cards": frontier})).fetchall()
            nxt = []
            for r in rows:
                r["execution_type_name"] = EXEC_TYPE_KO[r["execution_type"]]
                r["status_name"] = STATUS_KO[r["status"]]
                r["level"] = lvl
                r["next_cards"] = []
                if r["resulting_project_id"]:
                    r["next_cards"] = await (await conn.execute(
                        f"""SELECT c.id AS card_id, c.title FROM ax.achievement_card c
                             WHERE c.project_id = %(p)s AND c.status = 'PUBLISHED' AND {_OK(col='c.security_code')}
                             ORDER BY c.id""", {"p": r["resulting_project_id"], "uid": user.id})).fetchall()
                    nxt += [c["card_id"] for c in r["next_cards"] if c["card_id"] not in seen]
                descendants.append(r)
            seen.update(nxt)
            frontier = nxt
    return {"card": card, "ancestors": ancestors, "descendants": descendants}
