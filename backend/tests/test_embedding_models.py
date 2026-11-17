"""임베더별 벡터 분리: 활성 모델을 바꾸면 이전 모델 벡터는 조회되지 않고, 재임베딩으로 다시 채워진다."""
import pytest

from app.db import transaction
from app.reembed import reembed_all
from app.services import embedding as emb



class _Rollback(Exception):
    pass


async def _vector_count(conn) -> int:
    """활성 모델의 기업·공고 벡터 수"""
    row = await (await conn.execute(
        """SELECT (SELECT count(*) FROM ax.company_embedding e JOIN ax.embedding_model m ON m.id = e.model_id AND m.is_active)
                + (SELECT count(*) FROM ax.announcement_embedding e
                     JOIN ax.embedding_model m ON m.id = e.model_id AND m.is_active) AS n""")).fetchone()
    return row["n"]


async def test_switching_model_does_not_mix_vectors(client):
    with pytest.raises(_Rollback):
        async with transaction() as conn:
            await conn.execute("""INSERT INTO ax.organization (id, name, org_type, business_reg_no)
                                  VALUES (990, '(가상)임베딩기업', 'COMPANY', '9998499001')""")
            await conn.execute("""INSERT INTO ax.company_profile (organization_id, main_business, registration_channel)
                                  VALUES (990, '전술통신 모뎀', 'SELF')""")
            await conn.execute("""INSERT INTO ax.announcement (id, announcement_no, title, agency_name)
                                  VALUES (990, 'EMB-990', '전술통신 부품 공고', '(가상)기관')""")
            hash_id = await emb.activate_model(conn)
            await reembed_all(conn=conn, keep_other_models=True)
            assert (await emb.embedding_status(conn))["reindex_needed"] is False
            assert await _vector_count(conn) > 0

            other_id = await emb.activate_model(conn, "test/other-model")
            assert other_id != hash_id
            st = await emb.embedding_status(conn)
            assert st["model"] == "test/other-model" and st["reindex_needed"] is True
            assert st["other_model_vectors"] > 0
            assert await _vector_count(conn) == 0  # hash 벡터가 새 모델 조회에 섞이지 않는다

            done = await reembed_all(conn=conn, model="test/other-model")
            assert done["companies"] > 0 and done["announcements"] > 0 and done["purged"] > 0
            st = await emb.embedding_status(conn)
            assert st["reindex_needed"] is False and st["other_model_vectors"] == 0
            assert await _vector_count(conn) > 0
            # 이미 만든 벡터는 다시 만들지 않는다
            again = await reembed_all(conn=conn, model="test/other-model")
            assert again["chunks"] == again["companies"] == again["announcements"] == 0
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
