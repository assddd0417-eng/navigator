from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import CLEARANCE_OK, evidence_from_chunk, insert, update
from app.schemas.cards import CardCreate, CardUpdate
from app.schemas.common import Created, EmbedResult, EvidenceIn
from app.services.embedding import sync_card_embeddings

router = APIRouter(prefix="/cards", tags=["성과 활용카드"])
CURATORS = ("CURATOR", "PLANNER")


async def _link_evidence(conn: AsyncConnection, card_id: int, target_table: str, target_id: int | None,
                         field_name: str, evidence: list[EvidenceIn], target_key: dict | None = None) -> None:
    for e in evidence:
        ev_id = await evidence_from_chunk(conn, e.chunk_id, e.quote, e.page_start, e.page_end)
        await insert(conn, "card_field_evidence", {
            "card_id": card_id, "target_table": target_table, "target_id": target_id,
            "target_key": target_key, "field_name": field_name, "evidence_id": ev_id})
        await conn.execute(
            "INSERT INTO ax.card_source_document SELECT %s, document_id FROM ax.evidence WHERE id = %s "
            "ON CONFLICT DO NOTHING", (card_id, ev_id))


@router.post("", response_model=Created, status_code=201)
async def create_card(body: CardCreate, user: CurrentUser = Depends(require_roles(*CURATORS)),
                      rid: str = Depends(request_id)):
    nested = {"technologies", "performances", "open_issues", "outcomes", "weapon_systems", "items",
              "companies", "programs", "evidence"}
    async with transaction(user.id, rid) as conn:
        card_id = await insert(conn, "achievement_card", body.model_dump(exclude=nested))
        await _link_evidence(conn, card_id, "achievement_card", card_id, "core_achievement", body.evidence)

        for i, t in enumerate(body.technologies):
            tid = await insert(conn, "card_technology", {**t.model_dump(exclude={"evidence"}), "card_id": card_id, "sort_order": i})
            await _link_evidence(conn, card_id, "card_technology", tid, "tech_name", t.evidence)
        perf_ids = []
        for i, p in enumerate(body.performances):
            pid = await insert(conn, "card_performance", {**p.model_dump(exclude={"evidence"}), "card_id": card_id, "sort_order": i})
            perf_ids.append(pid)
            await _link_evidence(conn, card_id, "card_performance", pid, "achieved_value", p.evidence)
        for i, o in enumerate(body.open_issues):
            oid = await insert(conn, "card_open_issue", {**o.model_dump(exclude={"evidence"}), "card_id": card_id, "sort_order": i})
            await _link_evidence(conn, card_id, "card_open_issue", oid, "description", o.evidence)
        for o in body.outcomes:
            await insert(conn, "card_outcome", {**o.model_dump(), "card_id": card_id})

        rel = [("card_weapon_system", "weapon_system_id", body.weapon_systems),
               ("card_item", "item_id", body.items),
               ("card_company", "organization_id", body.companies),
               ("card_program", "program_id", body.programs)]
        for table, col, rows in rel:
            for r in rows:
                data = {"card_id": card_id, col: r.id, "confidence": r.confidence}
                if r.relation_type:
                    data["relation_type"] = r.relation_type
                if r.relation_status:
                    data["relation_status"] = r.relation_status
                if table == "card_company" and "relation_type" not in data:
                    data["relation_type"] = "TECH_HOLDER"
                await insert(conn, table, data, returning="card_id")

        await sync_card_embeddings(conn, card_id)
    return Created(id=card_id)


@router.get("")
async def list_cards(project_id: int | None = None, status: str | None = None,
                     q: str | None = Query(default=None, description="제목 부분일치"),
                     limit: int = Query(50, le=200), offset: int = 0,
                     user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        rows = await (await conn.execute(
            f"""SELECT ac.id, ac.card_no, ac.title, ac.trl, ac.status, ac.revision, ac.project_id,
                       p.project_no, p.title AS project_title, ac.updated_at
                  FROM ax.achievement_card ac JOIN ax.project p ON p.id = ac.project_id
                 WHERE (%(project_id)s::bigint IS NULL OR ac.project_id = %(project_id)s)
                   AND (%(status)s::text IS NULL OR ac.status = %(status)s)
                   AND (%(q)s::text IS NULL OR ac.title ILIKE '%%' || %(q)s || '%%')
                   AND {CLEARANCE_OK.format(col='ac.security_code')}
                 ORDER BY ac.updated_at DESC LIMIT %(limit)s OFFSET %(offset)s""",
            {"project_id": project_id, "status": status, "q": q, "uid": user.id,
             "limit": limit, "offset": offset})).fetchall()
    return rows


@router.get("/{card_id}")
async def get_card(card_id: int, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        card = await (await conn.execute(
            f"SELECT ac.* FROM ax.achievement_card ac WHERE ac.id = %(id)s "
            f"AND {CLEARANCE_OK.format(col='ac.security_code')}", {"id": card_id, "uid": user.id})).fetchone()
        if card is None:
            raise NotFound("성과카드", card_id)
        sub = {}
        for key, table in [("technologies", "card_technology"), ("performances", "card_performance"),
                           ("open_issues", "card_open_issue"), ("outcomes", "card_outcome"),
                           ("weapon_systems", "card_weapon_system"), ("items", "card_item"),
                           ("companies", "card_company"), ("programs", "card_program")]:
            sub[key] = await (await conn.execute(f"SELECT * FROM ax.{table} WHERE card_id = %s", (card_id,))).fetchall()
        sub["evidence"] = await (await conn.execute(
            """SELECT f.target_table, f.target_id, f.target_key, f.field_name, e.id AS evidence_id, e.quote,
                      e.page_start, e.page_end, d.id AS document_id, d.title AS document_title,
                      s.section_no, e.chunk_id
                 FROM ax.card_field_evidence f
                 JOIN ax.evidence e ON e.id = f.evidence_id
                 JOIN ax.source_document d ON d.id = e.document_id
                 LEFT JOIN ax.document_section s ON s.id = e.section_id
                WHERE f.card_id = %s AND ax.can_read_document(%s, d.id)
                ORDER BY f.id""", (card_id, user.id))).fetchall()
    return {**card, **sub}


@router.patch("/{card_id}", status_code=204)
async def update_card(card_id: int, body: CardUpdate, user: CurrentUser = Depends(require_roles(*CURATORS)),
                      rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        await update(conn, "achievement_card", card_id, body.model_dump(exclude_unset=True),
                     extra_sql="revision = revision + 1")
        await sync_card_embeddings(conn, card_id)


@router.post("/{card_id}/publish", status_code=204)
async def publish_card(card_id: int, user: CurrentUser = Depends(require_roles("CURATOR")),
                       rid: str = Depends(request_id)):
    """검수 확정: 매칭 대상(PUBLISHED)이 된다."""
    async with transaction(user.id, rid) as conn:
        await update(conn, "achievement_card", card_id,
                     {"status": "PUBLISHED", "curated_by": user.id}, extra_sql="curated_at = now()")
        await sync_card_embeddings(conn, card_id)


@router.post("/{card_id}/embeddings", response_model=EmbedResult)
async def embed_card(card_id: int, user: CurrentUser = Depends(require_roles(*CURATORS))):
    async with transaction(user.id) as conn:
        return EmbedResult(updated=await sync_card_embeddings(conn, card_id))
