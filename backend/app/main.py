import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.db import close_pool, open_pool, transaction
from app.errors import install_error_handlers
from app.routers import ai_admin, announcements, consult, navigator, navigator_alerts, navigator_matching, navigator_sources
from app.services.embedding import activate_model, embedding_status, get_embedder
from app.services.requirement_extract import wants_llm

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    # 모델을 먼저 올려 첫 요청이 모델 로딩(BGE-M3 는 수십 초)을 기다리지 않게 한다
    await asyncio.to_thread(get_embedder)
    async with transaction() as conn:
        await activate_model(conn)
        st = await embedding_status(conn)
    if st["reindex_needed"]:
        log.warning("활성 모델 %s 의 벡터가 없는 항목: 청크 %s · 기업 %s · 공고 %s → `python -m app.reembed` 실행 필요",
                    st["model"], st["chunks_missing"], st["companies_missing"], st["announcements_missing"])
    auto = asyncio.create_task(_auto_collect()) if get_settings().collect_auto_minutes > 0 else None
    yield
    if auto:
        auto.cancel()
        with suppress(asyncio.CancelledError):
            await auto
    await close_pool()


async def _auto_collect(sleep=asyncio.sleep) -> None:
    """주기가 된 출처를 서버가 알아서 수집한다 (출처별 주기는 external_source.fetch_interval)."""
    from app.services.collector import run_due
    await sleep(30)                    # 서버가 뜬 직후 요청과 겹치지 않게
    while True:
        try:
            for r in await run_due("auto"):
                log.info("자동 수집 %s %s %s", r["source"], r["status"], r.get("error") or r["counts"])
        except Exception:  # noqa: BLE001  한 번 실패해도 다음 주기에 다시
            log.exception("자동 수집 실패")
        await sleep(get_settings().collect_auto_minutes * 60)


app = FastAPI(
    title="Navigator API",
    version="0.1.0",
    description="기업 정보 · 공고 · 기업↔공고 판정과 추천 · 알림 · 외부 수집",
    lifespan=lifespan,
)
install_error_handlers(app)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.get("/health", tags=["시스템"])
async def health():
    async with transaction() as conn:
        row = await (await conn.execute(
            "SELECT max(version) AS schema_version, (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector "
            "FROM ax.schema_migrations")).fetchone()
        embedding = await embedding_status(conn)
    s = get_settings()
    # 공고 조건 뽑기에 외부 LLM 을 쓰는지 (공개 공고문 글자만 보냄)
    extractor = {"mode": "llm" if wants_llm(s) else "rules", "provider": s.llm_provider if wants_llm(s) else None}
    return {"status": "ok", **row, "embedding": embedding, "requirement_extractor": extractor}


@app.get("/me", tags=["시스템"])
async def me(user: CurrentUser = Depends(get_current_user)):
    """X-User-Id 로 식별된 현재 사용자와 역할 (프론트엔드 역할별 화면 분기용)."""
    return {"id": user.id, "name": user.name, "department_id": user.department_id,
            "clearance_code": user.clearance_code, "roles": sorted(user.roles)}


for r in (navigator.router, announcements.router, navigator_matching.router, navigator_alerts.router,
          navigator_sources.router, consult.router, ai_admin.router):
    app.include_router(r)
