from fastapi import APIRouter, Depends

from app.auth import CurrentUser, get_current_user
from app.db import transaction

router = APIRouter(prefix="/kpi", tags=["PoC KPI"])


@router.get("/recommendations")
async def recommendation_kpi(match_run_id: int | None = None, user: CurrentUser = Depends(get_current_user)):
    """추천결과 원문 근거 연결률(목표 100%)·최종 검토율(목표 100%)."""
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            "SELECT * FROM ax.v_kpi_recommendation WHERE %(id)s::bigint IS NULL OR match_run_id = %(id)s "
            "ORDER BY match_run_id", {"id": match_run_id})).fetchall()


@router.get("/eval")
async def eval_kpi(user: CurrentUser = Depends(get_current_user)):
    """전문가 주요 후보 상위 K 포함률(목표 80%)·연계유형 정확도."""
    async with transaction(user.id) as conn:
        return await (await conn.execute("SELECT * FROM ax.v_kpi_eval ORDER BY eval_run_id")).fetchall()


@router.get("/work-time")
async def work_time_kpi(user: CurrentUser = Depends(get_current_user)):
    """업무시간 단축률 (조사 70%, 검토자료 60% 목표)."""
    async with transaction(user.id) as conn:
        return await (await conn.execute("SELECT * FROM ax.v_kpi_work_time")).fetchall()
