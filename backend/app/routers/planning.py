"""신규 과제 기획: 동향 입력 → 관련 과거 과제 요약 → 새 기획에 넣을 것 → 기획수요로 넘기기.

- 동향은 해외 수요 표(overseas_demand)에 함께 둔다. 국제동향 조사팀이 직접 입력하는 국내 계획·성능개량·
  국산화/단종 대응도 같은 표에 넣어 갭 분석·국내 성과 검색을 그대로 쓴다. 직접 입력은 출처 메모로 근거를 남긴다.
- 과거 과제의 결과 구분(전력화·전환 실패 등)과 평가 의견은 과제 표·과제 평가 의견 표(0029)에 둔다.
- 열람 등급 밖의 카드·평가 의견은 참고서에 넣지 않는다.
"""
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth import CurrentUser, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import CLEARANCE_OK, insert, update
from app.schemas.cards import Comparator
from app.schemas.common import Created
from app.services.embedding import active_model_id, sync_demand_embeddings, sync_overseas_demand_embeddings
from app.services.gap_analysis import auto_run, near_cards
from app.services.gap_rules import DEFAULT_RULES
from app.services.planning_brief import DEMAND_KIND_KO, build_brief, render_markdown
from app.services.project_linker import add_identifier, link_document

router = APIRouter(prefix="/planning", tags=["신규 과제 기획"])
READERS = ("PLANNER", "DEPT_REVIEWER", "CURATOR")
EDITORS = ("PLANNER", "CURATOR")   # 동향 입력: 기획자 + 자료 담당(동향 조사)
_OK = CLEARANCE_OK.format

TrendKind = Literal["ROADMAP", "CALL", "EXPORT_REQ", "DOMESTIC_PLAN", "UPGRADE", "SUPPLY"]


class TrendPerformanceIn(BaseModel):
    metric_name: str = Field(min_length=1)
    comparator: Comparator = "GTE"
    required_value: float | None = None
    required_max: float | None = None
    required_text: str | None = None
    unit: str | None = None


class TrendIn(BaseModel):
    title: str = Field(min_length=2)
    demand_kind: TrendKind
    region: str = Field(min_length=1, description="나라·기관 (예: 폴란드, 방위사업청, 육군)")
    requirement: str = Field(min_length=2, description="요구 내용")
    source_note: str = Field(min_length=2, description="출처 메모: 기관·자료명·날짜 (예: 국방중기계획 2026~2030)")
    tech_area: str | None = None
    target_system: str | None = None
    weapon_system_id: int | None = None
    target_period: str | None = None
    confidence: str = Field("MEDIUM", pattern="^(HIGH|MEDIUM|LOW)$")
    security_code: str = "INTERNAL"
    performances: list[TrendPerformanceIn] = []


class EvaluationIn(BaseModel):
    eval_kind: str = Field(pattern="^(RESULT|INTERIM|EXPERT|USER)$")
    opinion: str = Field(min_length=2)
    eval_date: date | None = None
    grade: str | None = None
    suggestion: str | None = None
    evaluator: str | None = None
    document_id: int | None = None
    security_code: str = "INTERNAL"


class OutcomeIn(BaseModel):
    outcome_code: str | None = Field(None, pattern="^(FIELDED|FOLLOW_ON|TECH_ONLY|NOT_TRANSITIONED|STOPPED)$")
    outcome_note: str | None = None


def _f(x):
    return float(x) if x is not None else None


# ---------------------------------------------------------------------------
# 동향 입력
# ---------------------------------------------------------------------------
@router.post("/trends", response_model=Created, status_code=201)
async def create_trend(body: TrendIn, user: CurrentUser = Depends(require_roles(*EDITORS)),
                       rid: str = Depends(request_id)):
    """동향을 직접 입력한다. 저장 즉시 국내 성과와 대조(갭 분석)한다."""
    for p in body.performances:
        if p.required_value is None and not (p.required_text or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"요구 성능 '{p.metric_name}'에 값이나 설명을 적어 주세요")
    async with transaction(user.id, rid) as conn:
        year = date.today().year
        n = (await (await conn.execute(
            "SELECT count(*) AS n FROM ax.overseas_demand WHERE demand_no LIKE %s", (f"TR-{year}-%",))).fetchone())["n"]
        demand_no = f"TR-{year}-{n + 1:04d}"
        trend_id = await insert(conn, "overseas_demand", {
            **body.model_dump(exclude={"performances"}), "demand_no": demand_no, "status": "CONFIRMED",
            "created_by": user.id})
        for i, p in enumerate(body.performances):
            await insert(conn, "overseas_demand_performance",
                         {**p.model_dump(), "overseas_demand_id": trend_id, "sort_order": i})
        await sync_overseas_demand_embeddings(conn, trend_id)
    await auto_run(user.id, "NEW_DEMAND", [trend_id], rid)
    return Created(id=trend_id)


@router.get("/trends")
async def list_trends(kind: str | None = None, user: CurrentUser = Depends(require_roles(*READERS))):
    """동향 목록 (해외 수요 + 직접 입력한 국내 동향). 기획수요로 넘긴 것은 그 번호도 함께."""
    async with transaction(user.id) as conn:
        rows = await (await conn.execute(
            f"""SELECT d.id, d.demand_no, d.title, d.demand_kind, d.region, d.tech_area, d.target_system,
                       d.target_period, d.confidence, d.source_note, d.created_at,
                       (SELECT pd.demand_no FROM ax.planning_demand pd
                         WHERE pd.origin_overseas_demand_id = d.id AND pd.origin_gap_finding_id IS NULL
                           AND {_OK(col='pd.security_code')} ORDER BY pd.id DESC LIMIT 1) AS planning_demand_no
                  FROM ax.overseas_demand d
                 WHERE d.status <> 'ARCHIVED' AND (%(kind)s::text IS NULL OR d.demand_kind = %(kind)s)
                   AND {_OK(col='d.security_code')}
                 ORDER BY d.created_at DESC, d.demand_no""", {"kind": kind, "uid": user.id})).fetchall()
    for r in rows:
        r["demand_kind_name"] = DEMAND_KIND_KO.get(r["demand_kind"], r["demand_kind"])
    return rows


# ---------------------------------------------------------------------------
# 자료 사슬: 사업 기획서 → 공모서 → 연구개발계획서 → 결과보고서 → 평가서 (과제번호로 연결, 0032)
# ---------------------------------------------------------------------------
CHAIN_STEPS = [("PROGRAM_PLAN", "사업 기획서"), ("PROGRAM_NOTICE", "공모서"), ("RND_PLAN", "연구개발계획서"),
               ("FINAL_REPORT", "결과보고서"), ("EVALUATION", "평가서")]


async def _chains(conn, project_ids: list[int], uid: int) -> dict[int, list[dict]]:
    """과제마다 자료 사슬. 문서는 내가 열람할 수 있는 것만.

    연결 경로: 문서의 대상 과제 · 본문에서 찾은 과제번호/과제명(document_project_link) ·
    같은 사업에 붙은 사업 기획서·공모서(과제가 따로 적혀 있지 않은 사업 단위 문서).
    """
    if not project_ids:
        return {}
    rows = await (await conn.execute(
        """WITH p AS (SELECT id, program_id FROM ax.project WHERE id = ANY(%(ids)s))
           SELECT p.id AS project_id, d.id AS document_id, d.doc_type_code, d.title, d.authored_at::text AS authored_at,
                  CASE WHEN d.project_id = p.id THEN 'SUBJECT' WHEN l.document_id IS NOT NULL THEN l.link_role
                       ELSE 'PROGRAM' END AS via,
                  l.match_method
             FROM p
             JOIN ax.source_document d
               ON d.is_latest AND (d.project_id = p.id
                  OR EXISTS (SELECT 1 FROM ax.document_project_link x WHERE x.document_id = d.id AND x.project_id = p.id)
                  OR (d.program_id = p.program_id AND d.doc_type_code IN ('PROGRAM_PLAN','PROGRAM_NOTICE')
                      AND NOT EXISTS (SELECT 1 FROM ax.document_project_link y WHERE y.document_id = d.id)))
             LEFT JOIN ax.document_project_link l ON l.document_id = d.id AND l.project_id = p.id
            WHERE ax.can_read_document(%(uid)s, d.id)
            ORDER BY d.authored_at NULLS LAST, d.id""", {"ids": project_ids, "uid": uid})).fetchall()
    out: dict[int, list[dict]] = {pid: [{"code": c, "name": n, "documents": []} for c, n in CHAIN_STEPS]
                                  for pid in project_ids}
    for r in rows:
        step = next((x for x in out[r["project_id"]] if x["code"] == r["doc_type_code"]), None)
        if step is not None:
            step["documents"].append({k: r[k] for k in ("document_id", "title", "authored_at", "via", "match_method")})
    return out


class IdentifierIn(BaseModel):
    identifier: str = Field(min_length=2, description="다른 시스템의 과제번호 (예: DTiMS 번호)")
    source_system_code: str = Field("DTIMS", description="PMS · DTIMS 등")
    note: str | None = None


@router.get("/projects/{project_id}/chain")
async def project_chain(project_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    """과제 하나의 자료 사슬과 다른 번호."""
    async with transaction(user.id) as conn:
        await _visible_project(conn, project_id, user.id)
        chain = (await _chains(conn, [project_id], user.id))[project_id]
        idents = await (await conn.execute(
            "SELECT identifier, source_system_code, note FROM ax.project_identifier WHERE project_id = %s ORDER BY id",
            (project_id,))).fetchall()
    return {"project_id": project_id, "chain": chain, "identifiers": idents}


@router.post("/projects/{project_id}/identifiers", response_model=Created, status_code=201)
async def add_project_identifier(project_id: int, body: IdentifierIn,
                                 user: CurrentUser = Depends(require_roles(*EDITORS)), rid: str = Depends(request_id)):
    """과제의 다른 번호를 등록한다 (시스템마다 번호가 다를 때). 이미 올린 문서는 /documents/{id}/relink 로 다시 연결."""
    async with transaction(user.id, rid) as conn:
        await _visible_project(conn, project_id, user.id)
        return Created(id=await add_identifier(conn, project_id, body.identifier, body.source_system_code, body.note))


@router.post("/documents/{document_id}/relink")
async def relink_document(document_id: int, user: CurrentUser = Depends(require_roles(*EDITORS)),
                          rid: str = Depends(request_id)):
    """문서를 과제번호·과제명으로 다시 연결한다 (다른 번호를 새로 등록한 뒤 등)."""
    async with transaction(user.id, rid) as conn:
        ok = await (await conn.execute("SELECT ax.can_read_document(%s, %s) AS ok", (user.id, document_id))).fetchone()
        if not ok or not ok["ok"]:
            raise NotFound("문서", document_id)
        return {"document_id": document_id, "linked_projects": await link_document(conn, document_id)}


# ---------------------------------------------------------------------------
# 기획 참고서
# ---------------------------------------------------------------------------
async def _brief(conn, trend_id: int, uid: int, k: int, min_sim: float) -> dict:
    trend = await (await conn.execute(
        f"""SELECT d.id, d.demand_no, d.title, d.demand_kind, d.region, d.tech_area, d.target_system, d.requirement,
                   d.target_period, d.confidence, d.source_note, d.security_code, d.weapon_system_id
              FROM ax.overseas_demand d WHERE d.id = %(id)s AND {_OK(col='d.security_code')}""",
        {"id": trend_id, "uid": uid})).fetchone()
    if trend is None:
        raise NotFound("동향", trend_id)
    reqs = [{**r, "required_value": _f(r["required_value"]), "required_max": _f(r["required_max"])}
            for r in await (await conn.execute(
                "SELECT metric_name, comparator, required_value, required_max, required_text, unit "
                "FROM ax.overseas_demand_performance WHERE overseas_demand_id = %s ORDER BY sort_order, id",
                (trend_id,))).fetchall()]
    trend["sources"] = await (await conn.execute(
        """SELECT s.source_no, s.issuer, s.title, s.url FROM ax.overseas_demand_source ds
             JOIN ax.overseas_source s ON s.id = ds.source_id
            WHERE ds.overseas_demand_id = %s ORDER BY ds.is_primary DESC, s.source_no""", (trend_id,))).fetchall()

    model_id = await active_model_id(conn)
    near = await near_cards(conn, trend_id, model_id, k * 3)
    # 열람 가능한 카드만 + 과제 정보
    rows = await (await conn.execute(
        f"""SELECT ac.id AS card_id, ac.security_code, p.id AS project_id, p.project_no, p.title, p.start_date,
                   p.end_date, ps.name_ko AS status_name, pg.name AS program_name, pt.name_ko AS program_type_name,
                   dp.name AS department, p.outcome_code, po.name_ko AS outcome_name,
                   coalesce(po.is_failure, false) AS outcome_is_failure, p.outcome_note
              FROM ax.achievement_card ac
              JOIN ax.project p ON p.id = ac.project_id
              JOIN ax.code_project_status ps ON ps.code = p.status_code
              LEFT JOIN ax.program pg ON pg.id = p.program_id
              LEFT JOIN ax.code_program_type pt ON pt.code = pg.program_type_code
              LEFT JOIN ax.department dp ON dp.id = p.department_id
              LEFT JOIN ax.code_project_outcome po ON po.code = p.outcome_code
             WHERE ac.id = ANY(%(ids)s) AND {_OK(col='ac.security_code')}""",
        {"ids": [c.card_id for c in near], "uid": uid})).fetchall()
    info = {r["card_id"]: r for r in rows}
    cards = [c for c in near if c.card_id in info and c.similarity >= min_sim][:k]
    card_project = {c.card_id: info[c.card_id]["project_id"] for c in cards}
    projects: dict[int, dict] = {}
    for c in cards:
        r = info[c.card_id]
        period = "~".join(str(x.year) for x in (r["start_date"], r["end_date"]) if x) or None
        projects[r["project_id"]] = {
            "project_id": r["project_id"], "project_no": r["project_no"], "title": r["title"],
            "status_name": r["status_name"], "program_name": r["program_name"],
            "program_type_name": r["program_type_name"], "department": r["department"], "period": period,
            "outcome_code": r["outcome_code"], "outcome_name": r["outcome_name"],
            "outcome_is_failure": r["outcome_is_failure"], "outcome_note": r["outcome_note"]}
    evals: dict[int, list[dict]] = {}
    for e in await (await conn.execute(
            f"""SELECT e.id, e.project_id, e.eval_kind, e.eval_date::text AS eval_date, e.grade, e.opinion,
                       e.suggestion, e.evaluator
                  FROM ax.project_evaluation e
                 WHERE e.project_id = ANY(%(ids)s) AND {_OK(col='e.security_code')}
                 ORDER BY e.eval_date DESC NULLS LAST, e.id""",
            {"ids": list(projects), "uid": uid})).fetchall():
        evals.setdefault(e["project_id"], []).append(e)

    brief = build_brief(trend, reqs, cards, projects, card_project, evals,
                        float(DEFAULT_RULES["issue_threshold"]))
    chains = await _chains(conn, [p["project_id"] for p in brief["projects"]], uid)
    for p in brief["projects"]:
        p["chain"] = chains.get(p["project_id"], [])
    brief["card_security"] = sorted({info[c.card_id]["security_code"] for c in cards})
    # 이 동향의 갭 분석 결과 (검수 전·확정만)
    brief["gaps"] = await (await conn.execute(
        f"""SELECT f.id, f.status, f.gap_type_code, t.name_ko AS gap_type_name, f.summary, f.score
              FROM ax.gap_finding f JOIN ax.code_gap_type t ON t.code = f.gap_type_code
             WHERE f.overseas_demand_id = %(id)s AND f.status IN ('DRAFT','CONFIRMED')
               AND {_OK(col='f.security_code')}
             ORDER BY f.status = 'CONFIRMED' DESC, f.score DESC""", {"id": trend_id, "uid": uid})).fetchall()
    for g in brief["gaps"]:
        g["score"] = _f(g["score"])
    brief["planning_demand"] = await (await conn.execute(
        f"""SELECT pd.id, pd.demand_no, pd.status FROM ax.planning_demand pd
             WHERE pd.origin_overseas_demand_id = %(id)s AND pd.origin_gap_finding_id IS NULL
               AND {_OK(col='pd.security_code')} ORDER BY pd.id DESC LIMIT 1""",
        {"id": trend_id, "uid": uid})).fetchone()
    return brief


@router.get("/brief/{trend_id}")
async def get_brief(trend_id: int, k: int = Query(6, ge=1, le=20, description="볼 성과 카드 수"),
                    min_sim: float = Query(0.45, description="이보다 덜 비슷한 성과는 빼기"),
                    user: CurrentUser = Depends(require_roles(*READERS))):
    """동향 하나의 기획 참고서: 관련 과거 과제 요약 · 요구 성능 비교 · 새 기획에 넣을 것."""
    async with transaction(user.id) as conn:
        brief = await _brief(conn, trend_id, user.id, k, min_sim)
    brief.pop("card_security")
    return brief


@router.post("/brief/{trend_id}/to-demand")
async def brief_to_demand(trend_id: int, response: Response,
                          k: int = Query(6, ge=1, le=20), min_sim: float = Query(0.45),
                          user: CurrentUser = Depends(require_roles("PLANNER")), rid: str = Depends(request_id)):
    """기획 참고서로 신규 기획수요를 만들고 참고서 사본을 붙여 둔다. 이미 만든 동향이면 그 기획수요를 돌려준다."""
    async with transaction(user.id, rid) as conn:
        brief = await _brief(conn, trend_id, user.id, k, min_sim)
        existing = await (await conn.execute(
            "SELECT id, demand_no FROM ax.planning_demand WHERE origin_overseas_demand_id = %s "
            "AND origin_gap_finding_id IS NULL AND status <> 'CLOSED' ORDER BY id DESC LIMIT 1",
            (trend_id,))).fetchone()
        if existing:
            response.status_code = status.HTTP_200_OK
            return {"demand_id": existing["id"], "demand_no": existing["demand_no"], "draft_id": None,
                    "created": False}
        t = brief["trend"]
        # 보안등급: 내부·동향·참고서에 들어간 카드 중 가장 높은 등급
        sec = (await (await conn.execute(
            """SELECT code FROM ax.code_security_level
                WHERE level_rank = (SELECT max(level_rank) FROM ax.code_security_level
                                     WHERE code = ANY(%s::text[]))""",
            (["INTERNAL", t["security_code"], *brief["card_security"]],))).fetchone())["code"]
        n = (await (await conn.execute(
            "SELECT count(*) AS n FROM ax.planning_demand WHERE origin_overseas_demand_id = %s "
            "AND origin_gap_finding_id IS NULL", (trend_id,))).fetchone())["n"]
        demand_no = f"PD-TR-{trend_id:04d}" + (f"-{n + 1}" if n else "")
        top = [f"- [{s['kind_name']}] {s['title']}" for s in brief["suggestions"][:6]]
        demand_id = await insert(conn, "planning_demand", {
            "demand_no": demand_no,
            "title": t["title"],
            "tech_need": t["requirement"] + ("\n\n기획 참고:\n" + "\n".join(top) if top else ""),
            "business_purpose": f"{t['region']} {t['demand_kind_name']} 대응"
                                + (f", 목표 시기 {t['target_period']}" if t.get("target_period") else ""),
            "application_env": t.get("target_system"),
            "status": "OPEN",
            "security_code": sec,
            "owner_user_id": user.id,
            "requesting_dept_id": user.department_id,
            "origin_overseas_demand_id": trend_id})
        for i, r in enumerate(t["requirements"]):
            await insert(conn, "demand_performance_req", {
                "demand_id": demand_id, "sort_order": i, "metric_name": r["metric_name"],
                "comparator": r["comparator"], "required_value": r["required_value"],
                "required_max": r["required_max"], "required_text": r["required_text"], "unit": r["unit"]})
        if t.get("weapon_system_id"):
            await insert(conn, "demand_weapon_system",
                         {"demand_id": demand_id, "weapon_system_id": t["weapon_system_id"]}, "demand_id")
        brief.pop("card_security")
        draft_id = await insert(conn, "planning_draft", {
            "demand_id": demand_id, "title": f"기획 참고서: {t['title']}",
            "content_md": render_markdown(brief),
            "content_struct": json.loads(json.dumps(brief, ensure_ascii=False, default=str)),
            "generated_by": "AI", "created_by": user.id})
        await sync_demand_embeddings(conn, demand_id)
    response.status_code = status.HTTP_201_CREATED
    return {"demand_id": demand_id, "demand_no": demand_no, "draft_id": draft_id, "created": True}


@router.get("/demands/{demand_id}/brief")
async def demand_brief(demand_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    """기획수요에 붙여 둔 기획 참고서 사본 (가장 최근 것). 기획수요를 볼 수 있어야 한다."""
    async with transaction(user.id) as conn:
        row = await (await conn.execute(
            f"""SELECT pdr.id, pdr.title, pdr.content_md, pdr.created_at
                  FROM ax.planning_draft pdr JOIN ax.planning_demand pd ON pd.id = pdr.demand_id
                 WHERE pdr.demand_id = %(id)s AND {_OK(col='pd.security_code')}
                 ORDER BY pdr.id DESC LIMIT 1""", {"id": demand_id, "uid": user.id})).fetchone()
    if row is None:
        raise NotFound("기획 참고서", demand_id)
    return row


# ---------------------------------------------------------------------------
# 과거 과제: 결과 구분 · 평가 의견 (원천 시스템 연계 전까지 직접 입력)
# ---------------------------------------------------------------------------
async def _visible_project(conn, project_id: int, uid: int) -> dict:
    p = await (await conn.execute(
        f"SELECT id, security_code FROM ax.project p WHERE p.id = %(id)s AND {_OK(col='p.security_code')}",
        {"id": project_id, "uid": uid})).fetchone()
    if p is None:
        raise NotFound("과제", project_id)
    return p


@router.get("/projects/{project_id}/evaluations")
async def list_evaluations(project_id: int, user: CurrentUser = Depends(require_roles(*READERS))):
    async with transaction(user.id) as conn:
        await _visible_project(conn, project_id, user.id)
        return await (await conn.execute(
            f"""SELECT e.* FROM ax.project_evaluation e
                 WHERE e.project_id = %(id)s AND {_OK(col='e.security_code')}
                 ORDER BY e.eval_date DESC NULLS LAST, e.id""", {"id": project_id, "uid": user.id})).fetchall()


@router.post("/projects/{project_id}/evaluations", response_model=Created, status_code=201)
async def add_evaluation(project_id: int, body: EvaluationIn, user: CurrentUser = Depends(require_roles(*EDITORS)),
                         rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await _visible_project(conn, project_id, user.id)
        eval_id = await insert(conn, "project_evaluation",
                               {**body.model_dump(), "project_id": project_id, "created_by": user.id})
    return Created(id=eval_id)


@router.put("/projects/{project_id}/outcome", status_code=204)
async def set_outcome(project_id: int, body: OutcomeIn, user: CurrentUser = Depends(require_roles(*EDITORS)),
                      rid: str = Depends(request_id)):
    """과제 결과 구분. 전환 실패·중단은 원인을 꼭 적어야 한다 (DB 가 막는다)."""
    if body.outcome_code in ("NOT_TRANSITIONED", "STOPPED") and not (body.outcome_note or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "전환 실패·중단 과제는 원인을 적어 주세요")
    async with transaction(user.id, rid) as conn:
        await _visible_project(conn, project_id, user.id)
        await update(conn, "project", project_id, body.model_dump())
