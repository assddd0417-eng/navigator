"""전체 재임베딩 (재색인).

EMBEDDER 를 바꾼 뒤(예: hash → bge_m3) 기존 문서 청크·성과카드·기획수요를 활성 모델로 다시 임베딩한다.
같은 모델에서 이미 만든 벡터는 건너뛰므로 중간에 멈춰도 다시 실행하면 이어서 한다.
끝나면 다른 모델의 벡터를 지운다 (HNSW 인덱스를 활성 모델 벡터만으로 유지).

    cd backend
    EMBEDDER=bge_m3 python -m app.reembed            # .env 의 설정을 그대로 쓴다
    python -m app.reembed --keep-other-models        # 이전 모델 벡터를 남겨 두기 (되돌릴 때 재임베딩 생략)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

from psycopg import AsyncConnection

from app.db import close_pool, transaction
from app.services import embedding as emb
from app.services import navigator_embedding as nav

log = logging.getLogger("app.reembed")


async def _ids(sql: str) -> list[int]:
    async with transaction() as conn:
        return [r["id"] for r in await (await conn.execute(sql)).fetchall()]


async def reembed_all(keep_other_models: bool = False, conn: AsyncConnection | None = None,
                      model: str | None = None) -> dict[str, int]:
    """conn 을 주면 그 트랜잭션 안에서 전부 처리한다 (테스트용). 없으면 항목마다 짧은 트랜잭션.
    model 은 모델 행 이름 (기본: EMBEDDER 설정에 해당하는 이름)."""
    jobs = [
        ("chunks", "SELECT id FROM ax.source_document ORDER BY id", emb.sync_chunk_embeddings),
        ("cards", "SELECT id FROM ax.achievement_card ORDER BY id", emb.sync_card_embeddings),
        ("demands", "SELECT id FROM ax.planning_demand ORDER BY id", emb.sync_demand_embeddings),
        # Navigator (기업 대상 서비스) 매칭용
        ("companies", "SELECT organization_id AS id FROM ax.company_profile ORDER BY 1", nav.sync_company_embeddings),
        ("announcements", "SELECT id FROM ax.announcement ORDER BY id", nav.sync_announcement_embeddings),
    ]
    done: dict[str, int] = {}
    if conn is not None:
        await emb.activate_model(conn, model)
        for name, sql, sync in jobs:
            ids = [r["id"] for r in await (await conn.execute(sql)).fetchall()]
            done[name] = sum([await sync(conn, i) for i in ids])
        done["purged"] = 0 if keep_other_models else await emb.purge_other_models(conn)
        return done

    async with transaction() as c:
        model_id = await emb.activate_model(c, model)
    log.info("활성 모델: %s (id=%s)", model or emb.model_name(), model_id)
    for name, sql, sync in jobs:
        ids = await _ids(sql)
        started, n = time.monotonic(), 0
        for k, i in enumerate(ids, 1):
            async with transaction() as c:
                n += await sync(c, i)
            if k % 20 == 0 or k == len(ids):
                log.info("%s %d/%d (새 벡터 %d개, %.0f초)", name, k, len(ids), n, time.monotonic() - started)
        done[name] = n
    if not keep_other_models:
        async with transaction() as c:
            done["purged"] = await emb.purge_other_models(c)
    return done


def main() -> None:
    p = argparse.ArgumentParser(description="활성 임베딩 모델로 전체 재임베딩")
    p.add_argument("--keep-other-models", action="store_true", help="다른 모델의 벡터를 지우지 않는다")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def run() -> None:
        try:
            done = await reembed_all(args.keep_other_models)
        finally:
            await close_pool()
        log.info("완료: 청크 %s · 카드 패싯 %s · 수요 패싯 %s · 기업 %s · 공고 %s 벡터 생성, 다른 모델 벡터 %s개 삭제",
                 done["chunks"], done["cards"], done["demands"], done["companies"], done["announcements"],
                 done.get("purged", 0))

    asyncio.run(run())


if __name__ == "__main__":
    main()
