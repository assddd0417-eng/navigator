"""임베더별 벡터 분리: 활성 모델을 바꾸면 이전 모델 벡터는 조회되지 않고, 재임베딩으로 다시 채워진다."""
import pytest

from app.db import transaction
from app.reembed import reembed_all
from app.services import embedding as emb

CURATOR = 4


class _Rollback(Exception):
    pass


async def _search_count(conn) -> int:
    vec = await emb.embed_query("주파수 도약 동기 유지")
    rows = await (await conn.execute("SELECT * FROM ax.search_chunks(%s, %s, 10)", (vec, CURATOR))).fetchall()
    return len(rows)


async def test_switching_model_does_not_mix_vectors(client):
    # test_api_flow 가 hash 모델로 문서·카드·수요를 만들어 두었다
    with pytest.raises(_Rollback):
        async with transaction() as conn:
            hash_id = await emb.activate_model(conn)
            assert (await emb.embedding_status(conn))["reindex_needed"] is False
            assert await _search_count(conn) > 0

            other_id = await emb.activate_model(conn, "test/other-model")
            assert other_id != hash_id
            st = await emb.embedding_status(conn)
            assert st["model"] == "test/other-model" and st["reindex_needed"] is True
            assert st["other_model_vectors"] > 0
            assert await _search_count(conn) == 0  # hash 벡터가 새 모델 검색에 섞이지 않는다

            done = await reembed_all(conn=conn, model="test/other-model")
            assert done["chunks"] > 0 and done["cards"] > 0 and done["demands"] > 0 and done["purged"] > 0
            st = await emb.embedding_status(conn)
            assert st["reindex_needed"] is False and st["other_model_vectors"] == 0
            assert await _search_count(conn) > 0
            # 이미 만든 벡터는 다시 만들지 않는다
            again = await reembed_all(conn=conn, model="test/other-model")
            assert again["chunks"] == again["cards"] == again["demands"] == 0
            raise _Rollback  # 다른 테스트를 위해 hash 상태로 되돌린다
    emb._activated = None
    async with transaction() as conn:
        assert await emb.active_model_id(conn) == hash_id


def test_model_name_follows_embedder():
    from app.config import Settings

    assert emb.model_name(Settings(embedder="hash")) == emb.HASH_MODEL_NAME
    assert emb.model_name(Settings(embedder="bge_m3", embedding_model_name="BAAI/bge-m3")) == "BAAI/bge-m3"


def test_pick_device(monkeypatch):
    import sys
    import types

    def fake_torch(cuda: bool, mps: bool):
        t = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: cuda),
                                  backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps)))
        monkeypatch.setitem(sys.modules, "torch", t)

    assert emb.pick_device("cpu") == "cpu"
    fake_torch(cuda=False, mps=True)
    assert emb.pick_device("auto") == "mps"  # Apple Silicon
    fake_torch(cuda=False, mps=False)
    assert emb.pick_device("auto") == "cpu"
    fake_torch(cuda=True, mps=False)
    assert emb.pick_device("auto") == "cuda"
