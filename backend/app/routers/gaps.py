"""갭 분석: 해외 수요 ↔ 국내 성과 비교 실행·조회·검수 판정."""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import CLEARANCE_OK
from app.schemas.gaps import GapDecisionIn, GapRunIn, GapRunOut
from app.services.gap_analysis import run_gap_analysis

router = APIRouter(prefix="/gaps", tags=["갭 분석"])
RUNNERS = ("PLANNER", "CURATOR")
STATUS_FILTER = {"open": ("DRAFT", "CONFIRMED"), "all": ("DRAFT", "CONFIRMED", "REJECTED", "SUPERSEDED")}

FINDING_COLS = """f.id, f.gap_run_id, f.overseas_demand_id, d.demand_no, d.title AS demand_title, d.demand_kind,
                  d.region, f.gap_type_code, g.name_ko AS gap_type_name, round(f.severity, 4)::float AS severity,
                  round(f.score, 4)::float AS score, round(f.best_similarity, 4)::float AS best_similarity,
                  f.summary, f.security_code, f.status, f.decided_by, f.decided_at, f.decision_reason,
                  f.maybe_resolved_at, f.created_at"""
FINDING_FROM = """ax.gap_finding f
                  JOIN ax.overseas_demand d ON d.id = f.overseas_demand_id
                  JOIN ax.code_gap_type g ON g.code = f.gap_type_code"""


@router.post("/runs", response_model=GapRunOut, status_code=201)
async def create_run(body: GapRunIn, user: CurrentUser = Depends(require_roles(*RUNNERS)),
                     rid: str = Depends(request_id)):
    """갭 분석을 지금 돌린다. 결과는 모두 초안(DRAFT)이며 소관부서 검수자가 확정·기각한다."""
    rules = body.rules.model_dump(exclude_none=True) if body.rules else None
    async with transaction(user.id, rid) as conn:
        if body.demand_ids:
            found = {r["id"] for r in await (await conn.execute(
                "SELECT id FROM ax.overseas_demand WHERE id = ANY(%s)", (body.demand_ids,))).fetchall()}
            missing = [i for i in body.demand_ids if i not in found]
            if missing:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"없는 해외 수요: {missing}")
        run_id = await run_gap_analysis(conn, user.id, body.demand_ids or None, "MANUAL", rules, body.note)
        row = await (await conn.execute(
            "SELECT id, cardinality(demand_ids) AS demand_count, finding_count FROM ax.gap_run WHERE id = %s",
            (run_id,))).fetchone()
    return GapRunOut(**row)


@router.get("/runs")
async def list_runs(limit: int = Query(20, ge=1, le=100), user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            """SELECT id, trigger_kind, cardinality(demand_ids) AS demand_count, finding_count,
                      rule_snapshot ->> 'version' AS rules_version, note, started_by, started_at, finished_at
                 FROM ax.gap_run ORDER BY id DESC LIMIT %s""", (limit,))).fetchall()


@router.get("/runs/{run_id}")
async def get_run(run_id: int, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        run = await (await conn.execute("SELECT * FROM ax.gap_run WHERE id = %s", (run_id,))).fetchone()
        if run is None:
            raise NotFound("갭 분석 실행", run_id)
        run["findings"] = await (await conn.execute(
            f"""SELECT {FINDING_COLS} FROM {FINDING_FROM}
                 WHERE f.gap_run_id = %(id)s AND {CLEARANCE_OK.format(col='f.security_code')}
                 ORDER BY f.score DESC, f.id""", {"id": run_id, "uid": user.id})).fetchall()
    return run


@router.get("/findings")
async def list_findings(status_: str = Query("open", alias="status",
                                             description="open(초안+확정) | all | DRAFT | CONFIRMED | REJECTED | SUPERSEDED"),
                        demand_id: int | None = None, gap_type: str | None = None,
                        user: CurrentUser = Depends(get_current_user)):
    """갭 목록 (점수 높은 순). 열람 등급보다 높은 갭은 보이지 않는다."""
    statuses = STATUS_FILTER.get(status_, (status_,))
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT {FINDING_COLS},
                       (SELECT count(*) FROM ax.gap_finding_card fc WHERE fc.finding_id = f.id) AS card_count
                  FROM {FINDING_FROM}
                 WHERE f.status = ANY(%(st)s)
                   AND (%(d)s::bigint IS NULL OR f.overseas_demand_id = %(d)s)
                   AND (%(t)s::text IS NULL OR f.gap_type_code = %(t)s)
                   AND {CLEARANCE_OK.format(col='f.security_code')}
                 ORDER BY f.score DESC, f.id""",
            {"st": list(statuses), "d": demand_id, "t": gap_type, "uid": user.id})).fetchall()


async def _visible_finding(conn, finding_id: int, user_id: int) -> dict:
    f = await (await conn.execute(
        f"SELECT {FINDING_COLS}, f.detail FROM {FINDING_FROM} "
        f"WHERE f.id = %(id)s AND {CLEARANCE_OK.format(col='f.security_code')}",
        {"id": finding_id, "uid": user_id})).fetchone()
    if f is None:
        raise NotFound("갭", finding_id)
    return f


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: int, user: CurrentUser = Depends(get_current_user)):
    """갭 하나: 근거 카드, 제안 경로, 해외 수요 출처."""
    async with transaction(user.id) as conn:
        f = await _visible_finding(conn, finding_id, user.id)
        f["cards"] = await (await conn.execute(
            """SELECT fc.card_id, ac.card_no, ac.title, ac.trl, pr.title AS project_title,
                      round(fc.similarity, 4)::float AS similarity, fc.role, fc.note
                 FROM ax.gap_finding_card fc
                 JOIN ax.achievement_card ac ON ac.id = fc.card_id
                 LEFT JOIN ax.project pr ON pr.id = ac.project_id
                WHERE fc.finding_id = %s ORDER BY fc.role DESC, fc.similarity DESC NULLS LAST""",
            (finding_id,))).fetchall()
        f["pathways"] = await (await conn.execute(
            """SELECT p.id, p.linkage_type_code, COALESCE(lt.name_ko, '신규 기획수요') AS linkage_name,
                      p.description, p.card_ids
                 FROM ax.gap_pathway p LEFT JOIN ax.code_linkage_type lt ON lt.code = p.linkage_type_code
                WHERE p.finding_id = %s ORDER BY p.sort_order, p.id""", (finding_id,))).fetchall()
        f["sources"] = await (await conn.execute(
            """SELECT s.source_no, s.issuer, s.title, s.url, s.license_note, ds.is_primary
                 FROM ax.overseas_demand_source ds JOIN ax.overseas_source s ON s.id = ds.source_id
                WHERE ds.overseas_demand_id = %s ORDER BY ds.is_primary DESC, s.source_no""",
            (f["overseas_demand_id"],))).fetchall()
    return f


@router.post("/findings/{finding_id}/decision", status_code=204)
async def decide(finding_id: int, body: GapDecisionIn,
                 user: CurrentUser = Depends(require_roles("DEPT_REVIEWER")), rid: str = Depends(request_id)):
    """소관부서 검수자의 확정·기각 (DB 트리거가 권한·상태를 다시 확인한다)."""
    if body.decision == "REJECT" and not (body.reason or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "기각 사유를 적어 주세요")
    async with transaction(user.id, rid) as conn:
        await _visible_finding(conn, finding_id, user.id)
        await conn.execute(
            "UPDATE ax.gap_finding SET status = %s, decided_by = %s, decided_at = now(), decision_reason = %s "
            "WHERE id = %s",
            ("CONFIRMED" if body.decision == "CONFIRM" else "REJECTED", user.id, body.reason, finding_id))


@router.get("/summary")
async def summary(user: CurrentUser = Depends(get_current_user)):
    """해외 수요별 열린 갭(초안·확정) 종류 한눈에 보기 (기관용 화면 재료)."""
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT d.id AS overseas_demand_id, d.demand_no, d.title, d.region, d.tech_area,
                       COALESCE(jsonb_object_agg(f.gap_type_code, jsonb_build_object(
                           'finding_id', f.id, 'status', f.status, 'score', round(f.score, 4)))
                           FILTER (WHERE f.id IS NOT NULL), '{{}}'::jsonb) AS gaps
                  FROM ax.overseas_demand d
                  LEFT JOIN ax.gap_finding f ON f.overseas_demand_id = d.id AND f.status IN ('DRAFT','CONFIRMED')
                       AND {CLEARANCE_OK.format(col='f.security_code')}
                 WHERE d.status <> 'ARCHIVED' AND {CLEARANCE_OK.format(col='d.security_code')}
                 GROUP BY d.id ORDER BY d.demand_no""", {"uid": user.id})).fetchall()
