from fastapi import APIRouter, Depends, Query

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import CLEARANCE_OK, insert, update
from app.schemas.common import Created, EmbedResult
from app.schemas.demands import DemandCreate, DemandUpdate, MatchRequest
from app.services.embedding import sync_demand_embeddings
from app.services.matching import run_demand_matching

router = APIRouter(prefix="/demands", tags=["신규 기획수요"])


@router.post("", response_model=Created, status_code=201)
async def create_demand(body: DemandCreate, user: CurrentUser = Depends(require_roles("PLANNER")),
                        rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        demand_id = await insert(conn, "planning_demand", {
            **body.model_dump(exclude={"performance_reqs", "technologies", "weapon_system_ids", "item_ids"}),
            "owner_user_id": user.id,
            "requesting_dept_id": body.requesting_dept_id or user.department_id})
        for i, r in enumerate(body.performance_reqs):
            await insert(conn, "demand_performance_req", {**r.model_dump(), "demand_id": demand_id, "sort_order": i})
        for t in body.technologies:
            await insert(conn, "demand_technology", {**t.model_dump(), "demand_id": demand_id})
        for ws in body.weapon_system_ids:
            await insert(conn, "demand_weapon_system", {"demand_id": demand_id, "weapon_system_id": ws}, "demand_id")
        for it in body.item_ids:
            await insert(conn, "demand_item", {"demand_id": demand_id, "item_id": it}, "demand_id")
        await sync_demand_embeddings(conn, demand_id)
    return Created(id=demand_id)


@router.get("")
async def list_demands(status: str | None = None, limit: int = Query(50, le=200), offset: int = 0,
                       user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT d.id, d.demand_no, d.title, d.status, d.required_trl_min, d.required_trl_max,
                       d.target_program_id, d.requesting_dept_id, d.updated_at
                  FROM ax.planning_demand d
                 WHERE (%(status)s::text IS NULL OR d.status = %(status)s)
                   AND {CLEARANCE_OK.format(col='d.security_code')}
                 ORDER BY d.updated_at DESC LIMIT %(limit)s OFFSET %(offset)s""",
            {"status": status, "uid": user.id, "limit": limit, "offset": offset})).fetchall()


@router.get("/{demand_id}")
async def get_demand(demand_id: int, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        d = await (await conn.execute(
            f"SELECT d.* FROM ax.planning_demand d WHERE d.id = %(id)s AND {CLEARANCE_OK.format(col='d.security_code')}",
            {"id": demand_id, "uid": user.id})).fetchone()
        if d is None:
            raise NotFound("기획수요", demand_id)
        d["performance_reqs"] = await (await conn.execute(
            "SELECT * FROM ax.demand_performance_req WHERE demand_id = %s ORDER BY sort_order", (demand_id,))).fetchall()
        d["technologies"] = await (await conn.execute(
            "SELECT * FROM ax.demand_technology WHERE demand_id = %s ORDER BY id", (demand_id,))).fetchall()
        d["weapon_system_ids"] = [r["weapon_system_id"] for r in await (await conn.execute(
            "SELECT weapon_system_id FROM ax.demand_weapon_system WHERE demand_id = %s", (demand_id,))).fetchall()]
        d["match_runs"] = await (await conn.execute(
            "SELECT id, status, created_at, finished_at FROM ax.match_run WHERE demand_id = %s ORDER BY id DESC",
            (demand_id,))).fetchall()
    return d


@router.patch("/{demand_id}", status_code=204)
async def update_demand(demand_id: int, body: DemandUpdate, user: CurrentUser = Depends(require_roles("PLANNER")),
                        rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await update(conn, "planning_demand", demand_id, body.model_dump(exclude_unset=True))
        await sync_demand_embeddings(conn, demand_id)


@router.post("/{demand_id}/embeddings", response_model=EmbedResult)
async def embed_demand(demand_id: int, user: CurrentUser = Depends(require_roles("PLANNER"))):
    async with transaction(user.id) as conn:
        return EmbedResult(updated=await sync_demand_embeddings(conn, demand_id))


@router.post("/{demand_id}/match", response_model=Created, status_code=201)
async def match_demand(demand_id: int, body: MatchRequest | None = None,
                       user: CurrentUser = Depends(require_roles("PLANNER")), rid: str = Depends(request_id)):
    """연계 가능한 기존 성과를 찾아 추천을 생성한다. 반환값은 match_run id."""
    async with transaction(user.id, rid) as conn:
        run_id = await run_demand_matching(conn, demand_id, user.id, body.top_k if body else None)
    return Created(id=run_id)
