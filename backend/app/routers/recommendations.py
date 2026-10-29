from fastapi import APIRouter, Depends

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.config import get_settings
from app.db import set_status_reason, transaction
from app.errors import Conflict, NotFound
from app.repositories.sql import insert
from app.schemas.common import Created
from app.schemas.reviews import (
    AssignmentCreate, CommentCreate, ConfirmationCreate, ConfirmationResolve, DecisionCreate, WithdrawRequest,
)
from app.services.matching import regenerate_llm_rationale
from app.services.rationale import get_llm_writer

router = APIRouter(tags=["추천·HITL 검토"])

# 연계이유는 사용자별로 고른다: LLM 문장은 그 입력 근거 문서를 모두 열람할 수 있을 때만 (0017)
OVERVIEW_SQL = """SELECT o.*, rf.rationale AS visible_rationale, rf.rationale_source,
                         r.rationale_meta->>'status' AS rationale_llm_status,
                         r.rationale_meta->>'generator' AS rationale_generator,
                         r.rationale_meta->>'error' AS rationale_llm_error
                    FROM ax.v_recommendation_overview o
                    JOIN ax.recommendation r ON r.id = o.recommendation_id,
                         LATERAL ax.rationale_for_user(%s, o.recommendation_id) rf"""


def _visible_rationale(rec: dict) -> dict:
    rec["rationale"] = rec.pop("visible_rationale")
    # LLM 생성 기록: status OK | FALLBACK | null(LLM 미사용)
    rec["rationale_generation"] = {"status": rec.pop("rationale_llm_status"),
                                   "generator": rec.pop("rationale_generator"),
                                   "error": rec.pop("rationale_llm_error")}
    return rec


@router.get("/match-runs/{run_id}")
async def get_match_run(run_id: int, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        run = await (await conn.execute("SELECT * FROM ax.match_run WHERE id = %s", (run_id,))).fetchone()
        if run is None:
            raise NotFound("매칭 실행", run_id)
        rows = await (await conn.execute(
            OVERVIEW_SQL + " WHERE o.match_run_id = %s ORDER BY o.rank", (user.id, run_id))).fetchall()
        run["recommendations"] = [_visible_rationale(r) for r in rows]
    return run


@router.get("/recommendations/{rec_id}")
async def get_recommendation(rec_id: int, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        rec = await (await conn.execute(
            OVERVIEW_SQL + " WHERE o.recommendation_id = %s", (user.id, rec_id))).fetchone()
        if rec is None:
            raise NotFound("추천", rec_id)
        _visible_rationale(rec)
        q = lambda s: conn.execute(s, (rec_id,))  # noqa: E731
        rec["score_details"] = await (await q(
            "SELECT criterion, score, weight, method, detail FROM ax.recommendation_score WHERE recommendation_id = %s")).fetchall()
        rec["linkage_scores"] = await (await q(
            "SELECT linkage_type_code, probability, reason FROM ax.recommendation_linkage_score "
            "WHERE recommendation_id = %s ORDER BY probability DESC")).fetchall()
        # 원문 근거는 요청자가 열람 가능한 문서만 노출
        rec["evidence"] = await (await conn.execute(
            "SELECT * FROM ax.v_recommendation_evidence WHERE recommendation_id = %s "
            "AND ax.can_read_document(%s, document_id)", (rec_id, user.id))).fetchall()
        rec["departments"] = await (await q(
            "SELECT rd.*, d.name FROM ax.recommendation_department rd JOIN ax.department d ON d.id = rd.department_id "
            "WHERE rd.recommendation_id = %s")).fetchall()
        rec["companies"] = await (await q(
            "SELECT rc.*, o.name FROM ax.recommendation_company rc JOIN ax.organization o ON o.id = rc.organization_id "
            "WHERE rc.recommendation_id = %s")).fetchall()
        rec["items"] = await (await q(
            "SELECT ri.*, i.name, i.item_no FROM ax.recommendation_item ri JOIN ax.item i ON i.id = ri.item_id "
            "WHERE ri.recommendation_id = %s")).fetchall()
        rec["confirmations"] = await (await q(
            "SELECT * FROM ax.confirmation_item WHERE recommendation_id = %s ORDER BY id")).fetchall()
        rec["assignments"] = await (await q(
            "SELECT * FROM ax.review_assignment WHERE recommendation_id = %s ORDER BY id")).fetchall()
        rec["decisions"] = await (await q(
            "SELECT rd.*, u.name AS reviewer_name FROM ax.review_decision rd JOIN ax.app_user u ON u.id = rd.reviewer_id "
            "WHERE rd.recommendation_id = %s ORDER BY rd.id")).fetchall()
        rec["comments"] = await (await q(
            "SELECT * FROM ax.review_comment WHERE recommendation_id = %s ORDER BY id")).fetchall()
    return rec


@router.post("/recommendations/{rec_id}/rationale")
async def regenerate_rationale(rec_id: int, user: CurrentUser = Depends(require_roles("PLANNER"))):
    """LLM 연계이유를 다시 생성한다 (재매칭 없이). 실패하면 템플릿 문장이 유지되고 사유를 돌려준다."""
    writer = get_llm_writer(get_settings())
    if writer is None:
        raise Conflict("LLM 연계이유 생성이 꺼져 있습니다 (RATIONALE_GENERATOR·ANTHROPIC_API_KEY 확인)")
    async with transaction(user.id) as conn:
        result = await regenerate_llm_rationale(conn, rec_id, writer)
        shown = await (await conn.execute(
            "SELECT * FROM ax.rationale_for_user(%s, %s)", (user.id, rec_id))).fetchone()
    return {**result, "rationale": shown["rationale"], "rationale_source": shown["rationale_source"]}


@router.post("/recommendations/{rec_id}/assignments", response_model=Created, status_code=201)
async def assign(rec_id: int, body: AssignmentCreate, user: CurrentUser = Depends(require_roles("PLANNER")),
                 rid: str = Depends(request_id)):
    """검토 배정. 근거 없는 추천·카드 1개 융합형은 DB 가드가 거부한다 (422)."""
    async with transaction(user.id, rid) as conn:
        return Created(id=await insert(conn, "review_assignment", {
            **body.model_dump(), "recommendation_id": rec_id, "assigned_by": user.id}))


@router.post("/recommendations/{rec_id}/decisions", response_model=Created, status_code=201)
async def decide(rec_id: int, body: DecisionCreate,
                 user: CurrentUser = Depends(require_roles("DEPT_REVIEWER", "EXPERT")),
                 rid: str = Depends(request_id)):
    """검토 의견·판정. 최종판정(is_final)은 DEPT_REVIEWER 만 가능하며 DB 가 다시 검증한다."""
    async with transaction(user.id, rid) as conn:
        await set_status_reason(conn, body.opinion)
        return Created(id=await insert(conn, "review_decision", {
            **body.model_dump(), "recommendation_id": rec_id, "reviewer_id": user.id}))


@router.post("/recommendations/{rec_id}/withdraw", status_code=204)
async def withdraw(rec_id: int, body: WithdrawRequest, user: CurrentUser = Depends(require_roles("PLANNER")),
                   rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await set_status_reason(conn, body.reason)
        cur = await conn.execute(
            "UPDATE ax.recommendation SET status = 'WITHDRAWN' WHERE id = %s AND status <> 'DECIDED'", (rec_id,))
        if cur.rowcount == 0:
            raise NotFound("철회 가능한 추천", rec_id)


@router.get("/recommendations/{rec_id}/history")
async def history(rec_id: int, user: CurrentUser = Depends(get_current_user)):
    """검토 이력: 상태 변경 + 판정 + 감사 로그."""
    async with transaction(user.id) as conn:
        status_rows = await (await conn.execute(
            "SELECT h.*, u.name AS changed_by_name FROM ax.recommendation_status_history h "
            "LEFT JOIN ax.app_user u ON u.id = h.changed_by WHERE h.recommendation_id = %s ORDER BY h.id",
            (rec_id,))).fetchall()
        audit = await (await conn.execute(
            """SELECT a.occurred_at, a.table_name, a.action, a.actor_user_id, a.changed_fields, a.old_data, a.new_data
                 FROM ax.audit_log a
                WHERE (a.table_name = 'recommendation' AND a.row_pk = jsonb_build_object('id', %(id)s::bigint))
                   OR (a.table_name IN ('review_decision','review_assignment','recommendation_source_card',
                                        'recommendation_department','recommendation_company','confirmation_item')
                       AND COALESCE(a.new_data, a.old_data) ->> 'recommendation_id' = %(id)s::text)
                ORDER BY a.id""", {"id": rec_id})).fetchall()
    return {"status_history": status_rows, "audit": audit}


@router.post("/recommendations/{rec_id}/comments", response_model=Created, status_code=201)
async def comment(rec_id: int, body: CommentCreate, user: CurrentUser = Depends(get_current_user),
                  rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        return Created(id=await insert(conn, "review_comment", {
            **body.model_dump(), "recommendation_id": rec_id, "author_id": user.id}))


@router.post("/recommendations/{rec_id}/confirmations", response_model=Created, status_code=201)
async def add_confirmation(rec_id: int, body: ConfirmationCreate, user: CurrentUser = Depends(get_current_user),
                           rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        return Created(id=await insert(conn, "confirmation_item", {**body.model_dump(), "recommendation_id": rec_id}))


@router.patch("/confirmations/{item_id}", status_code=204)
async def resolve_confirmation(item_id: int, body: ConfirmationResolve, user: CurrentUser = Depends(get_current_user),
                               rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        cur = await conn.execute(
            "UPDATE ax.confirmation_item SET status = %s, resolution_note = %s, resolved_by = %s, resolved_at = now() "
            "WHERE id = %s AND status = 'OPEN'", (body.status, body.resolution_note, user.id, item_id))
        if cur.rowcount == 0:
            raise NotFound("미해결 확인사항", item_id)


@router.get("/reviews/queue")
async def review_queue(mine: bool = True, user: CurrentUser = Depends(get_current_user)):
    """검토 대기열. mine=true 면 본인 또는 본인 부서에 배정된 건만."""
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            """SELECT * FROM ax.v_review_queue
                WHERE NOT %(mine)s OR assignee_user_id = %(uid)s OR assignee_dept_id = %(dept)s
                ORDER BY is_overdue DESC, due_at NULLS LAST, assigned_at""",
            {"mine": mine, "uid": user.id, "dept": user.department_id})).fetchall()
