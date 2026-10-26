"""임베딩 생성과 패싯 임베딩 동기화.

- Embedder 는 교체 가능하다: 개발·테스트는 결정적 HashEmbedder, 실제 PoC 는 BGE-M3.
- 카드·수요를 관점(facet)별 텍스트로 나눠 임베딩한다 (스키마 0010 참조).
- 원문 텍스트의 sha256 이 같으면 다시 임베딩하지 않는다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np
from psycopg import AsyncConnection

from app.config import get_settings


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


class BgeM3Embedder:
    """sentence-transformers 로 BGE-M3 dense 벡터(1024)를 만든다. `pip install .[bge]` 필요."""

    def __init__(self, model_path: str, dim: int):
        from sentence_transformers import SentenceTransformer  # 선택 의존성

        self.model = SentenceTransformer(model_path)
        self.dim = dim

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        out = self.model.encode(texts, normalize_embeddings=True, batch_size=16)
        return [np.asarray(v, dtype=np.float32) for v in out]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedder == "bge_m3":
        return BgeM3Embedder(s.embedding_model_path, s.embedding_dim)
    return HashEmbedder(s.embedding_dim)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class FacetText:
    facet: str
    text: str
    source_table: str | None = None
    source_id: int | None = None


async def active_model_id(conn: AsyncConnection) -> int:
    row = await (await conn.execute("SELECT id FROM ax.embedding_model WHERE is_active")).fetchone()
    if row is None:
        raise RuntimeError("활성 임베딩 모델(ax.embedding_model.is_active)이 없습니다")
    return row["id"]


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
    vectors = get_embedder().embed([f.text for f in todo])
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
    for r, vec in zip(rows, get_embedder().embed([r["content"] for r in rows])):
        await conn.execute("INSERT INTO ax.chunk_embedding (chunk_id, model_id, embedding) VALUES (%s, %s, %s)",
                           (r["id"], model_id, vec))
    await conn.execute("UPDATE ax.source_document SET parse_status = 'EMBEDDED' WHERE id = %s", (document_id,))
    return len(rows)


async def embed_query(text: str) -> np.ndarray:
    return get_embedder().embed([text])[0]
