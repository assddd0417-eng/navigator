"""DB 연결 풀과 요청 단위 트랜잭션.

요청마다 하나의 트랜잭션을 열고, 감사 로그·검토 이력의 행위자 식별을 위해
`app.current_user_id` / `app.request_id` 를 SET LOCAL 로 설정한다 (스키마 0001 참조).
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

_pool: AsyncConnectionPool | None = None


async def _configure(conn: AsyncConnection) -> None:
    await register_vector_async(conn)
    conn.row_factory = dict_row
    await conn.set_autocommit(True)  # 트랜잭션은 transaction() 블록으로 명시


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = AsyncConnectionPool(
            s.database_url,
            min_size=s.db_pool_min,
            max_size=s.db_pool_max,
            configure=_configure,
            # 대여 전에 연결을 확인: DB 재시작·DB 재생성 후 끊긴 연결로 500 이 나지 않게 한다
            check=AsyncConnectionPool.check_connection,
            open=False,
        )
        await _pool.open(wait=True)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def transaction(user_id: int | None = None, request_id: str | None = None) -> AsyncIterator[AsyncConnection]:
    pool = await open_pool()
    async with pool.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('search_path', 'ax, public', true),"
            "       set_config('app.current_user_id', %s, true),"
            "       set_config('app.request_id', %s, true),"
            "       set_config('hnsw.ef_search', %s, true)",
            (str(user_id) if user_id else "", request_id or "", str(get_settings().hnsw_ef_search)),
        )
        yield conn


async def set_status_reason(conn: AsyncConnection, reason: str | None) -> None:
    """다음 상태 변경의 사유를 recommendation_status_history 에 남긴다."""
    await conn.execute("SELECT set_config('app.status_reason', %s, true)", (reason or "",))
