import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request

from app.auth import CurrentUser, get_current_user
from app.db import close_pool, open_pool, transaction
from app.errors import install_error_handlers
from app.routers import cards, demands, documents, kpi, recommendations


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    yield
    await close_pool()


app = FastAPI(
    title="국방 R&D 성과연계·이어달리기 AX API",
    version="0.1.0",
    description="성과 활용카드 · 신규 기획수요 · 6대 연계유형 추천 · RAG 근거 · Human-in-the-Loop 검토",
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
    return {"status": "ok", **row}


@app.get("/me", tags=["시스템"])
async def me(user: CurrentUser = Depends(get_current_user)):
    """X-User-Id 로 식별된 현재 사용자와 역할 (프론트엔드 역할별 화면 분기용)."""
    return {"id": user.id, "name": user.name, "department_id": user.department_id,
            "clearance_code": user.clearance_code, "roles": sorted(user.roles)}


for r in (documents.router, cards.router, demands.router, recommendations.router, kpi.router):
    app.include_router(r)
