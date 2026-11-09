"""임베딩 생성과 패싯 임베딩 동기화.

- Embedder 는 교체 가능하다: 개발·테스트는 결정적 HashEmbedder, 실제 PoC 는 BGE-M3.
- 임베더마다 ax.embedding_model 행이 따로 있고(0016), 백엔드가 EMBEDDER 설정에 맞는 행을 활성으로 만든다.
  모든 벡터 조회는 활성 모델의 벡터만 보므로 hash 벡터와 BGE-M3 벡터가 섞이지 않는다.
  임베더를 바꾼 뒤에는 `python -m app.reembed` 로 기존 문서·카드·수요를 다시 임베딩한다.
- 카드·수요를 관점(facet)별 텍스트로 나눠 임베딩한다 (스키마 0010 참조).
- 원문 텍스트의 sha256 이 같으면 (같은 모델 안에서) 다시 임베딩하지 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np
from psycopg import AsyncConnection

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

HASH_MODEL_NAME = "relay-ax/hash-ngram"  # 0016 에서 등록


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class HashEmbedder:
    """문자 2·3-gram 해시 임베더. 의미 이해는 없지만 표현이 겹치면 유사도가 높아진다.

    모델 없이 전체 파이프라인을 돌리고 테스트를 결정적으로 만들기 위한 용도다.
    """

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        s = re.sub(r"\s+", " ", text.lower()).strip()
        for n in (2, 3):
            for i in range(len(s) - n + 1):
                gram = s[i : i + n]
                if gram.strip() == "":
                    continue
                h = hashlib.blake2b(gram.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                v[idx] += 1.0 if h[4] & 1 else -1.0
        norm = np.linalg.norm(v)
        return v / norm if norm > 0 else v

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._vec(t) for t in texts]


def pick_device(requested: str) -> str:
    """auto 면 CUDA → Apple Silicon MPS → CPU 순으로 고른다."""
    if requested != "auto":
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class BgeM3Embedder:
    """sentence-transformers 로 BGE-M3 dense 벡터(1024)를 만든다. `pip install .[bge]` 필요.

    - 모델: EMBEDDING_MODEL_PATH (Hugging Face 이름이면 첫 실행 때 내려받아 캐시, 로컬 폴더면 그대로 읽음)
    - 폐쇄망: EMBEDDING_OFFLINE=true (또는 HF_HUB_OFFLINE=1) 이면 네트워크 없이 캐시·로컬 폴더에서만 읽는다
    - 장치: EMBEDDING_DEVICE=auto|cpu|mps|cuda
    """

    def __init__(self, s: Settings):
        if s.embedding_offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # MPS 미지원 연산은 CPU 로
        try:
            from sentence_transformers import SentenceTransformer  # 선택 의존성
        except ImportError as e:
            raise RuntimeError('EMBEDDER=bge_m3 에는 sentence-transformers 가 필요합니다: pip install -e ".[bge]"') from e

        self.device = pick_device(s.embedding_device)
        self.batch_size = s.embedding_batch_size
        self.model = SentenceTransformer(
            s.embedding_model_path, device=self.device, cache_folder=s.embedding_cache_dir,
            local_files_only=s.embedding_offline)
        self.model.max_seq_length = s.embedding_max_seq_length
        get_dim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dim = get_dim() or s.embedding_dim
        if self.dim != s.embedding_dim:
            raise RuntimeError(f"모델 차원 {self.dim} 이 스키마 차원 {s.embedding_dim} 과 다릅니다 (vector(1024))")
        self._lock = threading.Lock()  # 한 모델을 여러 스레드가 동시에 쓰지 않게 (MPS 안정성)
        log.info("BGE-M3 로드: %s (device=%s, max_seq_length=%s)", s.embedding_model_path, self.device,
                 s.embedding_max_seq_length)

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        with self._lock:
            out = self.model.encode(texts, normalize_embeddings=True, batch_size=self.batch_size,
                                    convert_to_numpy=True, show_progress_bar=False)
        return [np.asarray(v, dtype=np.float32) for v in out]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedder == "bge_m3":
        return BgeM3Embedder(s)
    if s.embedder != "hash":
        raise RuntimeError(f"알 수 없는 EMBEDDER={s.embedder!r} (hash | bge_m3)")
    return HashEmbedder(s.embedding_dim)


async def embed_texts(texts: list[str]) -> list[np.ndarray]:
    """모델 추론은 이벤트 루프 밖(스레드)에서 돌린다. BGE-M3 는 문서 하나에 수 초가 걸릴 수 있다."""
    if not texts:
        return []
    return await asyncio.to_thread(lambda: get_embedder().embed(texts))


def model_name(s: Settings | None = None) -> str:
    """EMBEDDER 설정에 해당하는 ax.embedding_model.name"""
    s = s or get_settings()
    return HASH_MODEL_NAME if s.embedder == "hash" else s.embedding_model_name


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class FacetText:
    facet: str
    text: str
    source_table: str | None = None
    source_id: int | None = None


_activated: int | None = None  # 이 프로세스에서 활성화를 확인한 모델 ID


async def activate_model(conn: AsyncConnection, name: str | None = None) -> int:
    """EMBEDDER 에 맞는 모델 행을 (없으면 만들고) 유일한 활성 모델로 만든다. 바뀌면 경고를 남긴다."""
    global _activated
    s = get_settings()
    name = name or model_name(s)
    row = await (await conn.execute(
        """INSERT INTO ax.embedding_model (name, version, dimension, distance, note)
           VALUES (%s, '1', %s, 'cosine', 'EMBEDDER 설정으로 자동 등록')
           ON CONFLICT (name, version) DO UPDATE SET name = EXCLUDED.name
           RETURNING id, is_active""", (name, s.embedding_dim))).fetchone()
    if not row["is_active"]:
        await conn.execute("UPDATE ax.embedding_model SET is_active = false WHERE is_active")
        await conn.execute("UPDATE ax.embedding_model SET is_active = true WHERE id = %s", (row["id"],))
        log.warning("활성 임베딩 모델을 %s 로 바꿨습니다. 기존 문서·카드·수요는 `python -m app.reembed` 로 "
                    "다시 임베딩해야 매칭·검색에 나옵니다.", name)
    _activated = row["id"]
    return row["id"]


async def active_model_id(conn: AsyncConnection) -> int:
    """활성 모델 ID. 프로세스에서 처음 부를 때 EMBEDDER 설정과 맞춘다."""
    if _activated is None:
        return await activate_model(conn)
    row = await (await conn.execute("SELECT id FROM ax.embedding_model WHERE is_active")).fetchone()
    if row is None:
        raise RuntimeError("활성 임베딩 모델(ax.embedding_model.is_active)이 없습니다")
    if row["id"] != _activated:
        # 같은 DB 를 다른 EMBEDDER 로 띄운 서버가 활성 모델을 바꿨다. 섞이지 않게 이 서버 설정으로 되돌린다.
        return await activate_model(conn)
    return row["id"]


async def embedding_status(conn: AsyncConnection) -> dict[str, object]:
    """활성 모델과 재임베딩 필요 건수 (/health 용)."""
    model_id = await active_model_id(conn)
    row = await (await conn.execute(
        """SELECT m.name AS model,
                  (SELECT count(*) FROM ax.document_chunk c WHERE NOT EXISTS
                      (SELECT 1 FROM ax.chunk_embedding e WHERE e.chunk_id = c.id AND e.model_id = m.id)) AS chunks_missing,
                  (SELECT count(*) FROM ax.achievement_card a WHERE NOT EXISTS
                      (SELECT 1 FROM ax.card_embedding e WHERE e.card_id = a.id AND e.model_id = m.id)) AS cards_missing,
                  (SELECT count(*) FROM ax.planning_demand d WHERE NOT EXISTS
                      (SELECT 1 FROM ax.demand_embedding e WHERE e.demand_id = d.id AND e.model_id = m.id)) AS demands_missing,
                  (SELECT count(*) FROM ax.chunk_embedding WHERE model_id <> m.id)
                + (SELECT count(*) FROM ax.card_embedding WHERE model_id <> m.id)
                + (SELECT count(*) FROM ax.demand_embedding WHERE model_id <> m.id) AS other_model_vectors
             FROM ax.embedding_model m WHERE m.id = %s""", (model_id,))).fetchone()
    s = get_settings()
    return {"embedder": s.embedder, **row,
            "reindex_needed": bool(row["chunks_missing"] or row["cards_missing"] or row["demands_missing"])}


def _join(*parts: str | None) -> str:
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 패싯 텍스트 구성
# ---------------------------------------------------------------------------
async def card_facets(conn: AsyncConnection, card_id: int) -> tuple[int, list[FacetText]]:
    card = await (await conn.execute(
        "SELECT title, core_achievement, summary, test_conditions, application_env, revision "
        "FROM ax.achievement_card WHERE id = %s", (card_id,))).fetchone()
    techs = await (await conn.execute(
        "SELECT id, tech_name, principle FROM ax.card_technology WHERE card_id = %s ORDER BY sort_order, id",
        (card_id,))).fetchall()
    perfs = await (await conn.execute(
        "SELECT metric_name, achieved_value, achieved_text, unit, test_condition "
        "FROM ax.card_performance WHERE card_id = %s ORDER BY sort_order, id", (card_id,))).fetchall()
    issues = await (await conn.execute(
        "SELECT id, description FROM ax.card_open_issue WHERE card_id = %s AND NOT is_resolved "
        "ORDER BY sort_order, id", (card_id,))).fetchall()

    facets = [FacetText("SUMMARY", _join(card["title"], card["core_achievement"], card["summary"]))]
    for t in techs:
        facets.append(FacetText("CORE_TECH", t["tech_name"], "card_technology", t["id"]))
        if t["principle"]:
            facets.append(FacetText("PRINCIPLE", _join(t["tech_name"], t["principle"]), "card_technology", t["id"]))
    for i in issues:
        facets.append(FacetText("OPEN_ISSUE", i["description"], "card_open_issue", i["id"]))
    if perfs:
        facets.append(FacetText("PERFORMANCE", "\n".join(
            f"{p['metric_name']} {p['achieved_value'] if p['achieved_value'] is not None else (p['achieved_text'] or '')}"
            f"{p['unit'] or ''} {p['test_condition'] or ''}".strip() for p in perfs)))
    env = _join(card["application_env"], card["test_conditions"])
    if env:
        facets.append(FacetText("APPLICATION_ENV", env))
    return card["revision"], facets


async def demand_facets(conn: AsyncConnection, demand_id: int) -> list[FacetText]:
    d = await (await conn.execute(
        "SELECT title, tech_need, business_purpose, application_env FROM ax.planning_demand WHERE id = %s",
        (demand_id,))).fetchone()
    techs = await (await conn.execute(
        "SELECT id, tech_name, description FROM ax.demand_technology WHERE demand_id = %s ORDER BY id",
        (demand_id,))).fetchall()
    reqs = await (await conn.execute(
        "SELECT metric_name, required_value, required_text, unit FROM ax.demand_performance_req "
        "WHERE demand_id = %s ORDER BY sort_order, id", (demand_id,))).fetchall()

    facets = [FacetText("SUMMARY", _join(d["title"], d["tech_need"])),
              FacetText("TECH_NEED", d["tech_need"])]
    for t in techs:
        facets.append(FacetText("TECH_NEED", _join(t["tech_name"], t["description"]), "demand_technology", t["id"]))
    if reqs:
        facets.append(FacetText("PERFORMANCE", "\n".join(
            f"{r['metric_name']} {r['required_value'] if r['required_value'] is not None else (r['required_text'] or '')}"
            f"{r['unit'] or ''}".strip() for r in reqs)))
    if d["application_env"]:
        facets.append(FacetText("APPLICATION_ENV", d["application_env"]))
    if d["business_purpose"]:
        facets.append(FacetText("PURPOSE", d["business_purpose"]))
    return facets


# ---------------------------------------------------------------------------
# 동기화
# ---------------------------------------------------------------------------
async def _sync(conn: AsyncConnection, table: str, owner_col: str, owner_id: int,
                facets: list[FacetText], extra: dict[str, object]) -> int:
    model_id = await active_model_id(conn)
    existing = {
        (r["facet"], r["source_table"], r["source_id"]): r["source_sha256"]
        for r in await (await conn.execute(
            f"SELECT facet, source_table, source_id, source_sha256 FROM ax.{table} "
            f"WHERE {owner_col} = %s AND model_id = %s", (owner_id, model_id))).fetchall()
    }
    wanted = {(f.facet, f.source_table, f.source_id): f for f in facets if f.text.strip()}

    stale = [k for k in existing if k not in wanted]
    for facet, st, sid in stale:
        await conn.execute(
            f"DELETE FROM ax.{table} WHERE {owner_col} = %s AND model_id = %s AND facet = %s "
            f"AND source_table IS NOT DISTINCT FROM %s AND source_id IS NOT DISTINCT FROM %s",
            (owner_id, model_id, facet, st, sid))

    todo = [f for k, f in wanted.items() if existing.get(k) != sha256(f.text)]
    if not todo:
        return 0
    vectors = await embed_texts([f.text for f in todo])
    extra_cols = "".join(f", {c}" for c in extra)
    extra_vals = "".join(", %s" for _ in extra)
    extra_upd = "".join(f", {c} = EXCLUDED.{c}" for c in extra)
    for f, vec in zip(todo, vectors):
        await conn.execute(
            f"""INSERT INTO ax.{table} ({owner_col}, facet, source_table, source_id, model_id,
                                        source_text, source_sha256, embedding{extra_cols})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s{extra_vals})
                ON CONFLICT ({owner_col}, facet, source_table, source_id, model_id) DO UPDATE
                SET source_text = EXCLUDED.source_text, source_sha256 = EXCLUDED.source_sha256,
                    embedding = EXCLUDED.embedding, created_at = now(){extra_upd}""",
            (owner_id, f.facet, f.source_table, f.source_id, model_id, f.text, sha256(f.text), vec,
             *extra.values()))
    return len(todo)


async def sync_card_embeddings(conn: AsyncConnection, card_id: int) -> int:
    revision, facets = await card_facets(conn, card_id)
    return await _sync(conn, "card_embedding", "card_id", card_id, facets, {"card_revision": revision})


async def sync_demand_embeddings(conn: AsyncConnection, demand_id: int) -> int:
    return await _sync(conn, "demand_embedding", "demand_id", demand_id, await demand_facets(conn, demand_id), {})


async def sync_chunk_embeddings(conn: AsyncConnection, document_id: int) -> int:
    model_id = await active_model_id(conn)
    rows = await (await conn.execute(
        """SELECT c.id, c.content FROM ax.document_chunk c
            WHERE c.document_id = %s
              AND NOT EXISTS (SELECT 1 FROM ax.chunk_embedding e WHERE e.chunk_id = c.id AND e.model_id = %s)
            ORDER BY c.chunk_index""", (document_id, model_id))).fetchall()
    if not rows:
        return 0
    for r, vec in zip(rows, await embed_texts([r["content"] for r in rows])):
        await conn.execute("INSERT INTO ax.chunk_embedding (chunk_id, model_id, embedding) VALUES (%s, %s, %s)",
                           (r["id"], model_id, vec))
    await conn.execute("UPDATE ax.source_document SET parse_status = 'EMBEDDED' WHERE id = %s", (document_id,))
    return len(rows)


async def embed_query(text: str) -> np.ndarray:
    return (await embed_texts([text]))[0]


async def purge_other_models(conn: AsyncConnection) -> int:
    """활성 모델이 아닌 벡터를 지운다. HNSW 인덱스는 모델 구분 없이 하나라서, 남겨 두면 근접 후보 자리를 차지한다.
    (match_run.model_id 이력은 그대로 둔다)"""
    model_id = await active_model_id(conn)
    n = 0
    for t in ("chunk_embedding", "card_embedding", "demand_embedding", "company_tech_embedding", "program_embedding",
              "company_embedding", "announcement_embedding"):
        n += (await conn.execute(f"DELETE FROM ax.{t} WHERE model_id <> %s", (model_id,))).rowcount
    return n
