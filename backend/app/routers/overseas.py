"""해외 수요 (해외 기술 로드맵·공모·수출 요구) 등록·조회와 국내 성과 검색."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from psycopg import AsyncConnection, Rollback

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.config import get_settings
from app.db import transaction
from app.errors import NotFound
from app.repositories.sql import CLEARANCE_OK, insert, update
from app.schemas.common import Created, EmbedResult
from app.schemas.overseas import ImportSummary, OverseasDemandIn, OverseasSourceIn, SimilarCard
from app.services.embedding import active_model_id, sync_overseas_demand_embeddings
from app.services.overseas_import import OverseasImportError, parse_workbook

router = APIRouter(prefix="/overseas", tags=["해외 수요"])
EDITORS = ("PLANNER", "CURATOR")

# 해외 수요 패싯 → 국내 성과 카드 패싯 (가까운 성과 찾기)
SIMILAR_PAIRS = [("TECH_NEED", "CORE_TECH"), ("TECH_NEED", "OPEN_ISSUE"), ("SUMMARY", "SUMMARY"),
                 ("PERFORMANCE", "PERFORMANCE"), ("APPLICATION_ENV", "APPLICATION_ENV")]


async def _upsert_source(conn: AsyncConnection, data: dict, user_id: int) -> tuple[int, bool]:
    row = await (await conn.execute("SELECT id FROM ax.overseas_source WHERE source_no = %s",
                                    (data["source_no"],))).fetchone()
    if row:
        await update(conn, "overseas_source", row["id"], {k: v for k, v in data.items() if k != "source_no"})
        return row["id"], False
    return await insert(conn, "overseas_source", {**data, "created_by": user_id}), True


async def _upsert_demand(conn: AsyncConnection, body: OverseasDemandIn, user_id: int) -> tuple[int, bool]:
    src = await (await conn.execute("SELECT id, source_no FROM ax.overseas_source WHERE source_no = ANY(%s)",
                                    (body.source_nos,))).fetchall()
    ids = {r["source_no"]: r["id"] for r in src}
    missing = [s for s in body.source_nos if s not in ids]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"등록되지 않은 출처 번호: {', '.join(missing)}")

    data = body.model_dump(exclude={"source_nos", "performances"})
    row = await (await conn.execute("SELECT id FROM ax.overseas_demand WHERE demand_no = %s",
                                    (body.demand_no,))).fetchone()
    if row:
        demand_id, created = row["id"], False
        await update(conn, "overseas_demand", demand_id, {k: v for k, v in data.items() if k != "demand_no"})
        await conn.execute("DELETE FROM ax.overseas_demand_source WHERE overseas_demand_id = %s", (demand_id,))
        await conn.execute("DELETE FROM ax.overseas_demand_performance WHERE overseas_demand_id = %s", (demand_id,))
    else:
        demand_id, created = await insert(conn, "overseas_demand", {**data, "created_by": user_id}), True
    for i, no in enumerate(dict.fromkeys(body.source_nos)):
        await insert(conn, "overseas_demand_source",
                     {"overseas_demand_id": demand_id, "source_id": ids[no], "is_primary": i == 0},
                     "overseas_demand_id")
    for i, p in enumerate(body.performances):
        await insert(conn, "overseas_demand_performance", {**p.model_dump(), "overseas_demand_id": demand_id,
                                                           "sort_order": i})
    return demand_id, created


@router.post("/sources", response_model=Created, status_code=201)
async def create_source(body: OverseasSourceIn, user: CurrentUser = Depends(require_roles(*EDITORS)),
                        rid: str = Depends(request_id)):
    """출처 등록 (같은 출처 번호면 갱신). URL·발행 기관·확인일·이용 조건은 필수."""
    async with transaction(user.id, rid) as conn:
        source_id, _ = await _upsert_source(conn, body.model_dump(), user.id)
    return Created(id=source_id)


@router.get("/sources")
async def list_sources(user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT s.id, s.source_no, s.issuer, s.title, s.published_on, s.url, s.source_kind,
                       s.license_note, s.allow_full_text, s.checked_on, s.security_code,
                       (SELECT count(*) FROM ax.overseas_demand_source ds WHERE ds.source_id = s.id) AS demand_count
                  FROM ax.overseas_source s
                 WHERE {CLEARANCE_OK.format(col='s.security_code')}
                 ORDER BY s.source_no""", {"uid": user.id})).fetchall()


@router.post("/demands", response_model=Created, status_code=201)
async def create_demand(body: OverseasDemandIn, user: CurrentUser = Depends(require_roles(*EDITORS)),
                        rid: str = Depends(request_id)):
    """해외 수요 등록 (같은 수요 번호면 갱신) + 임베딩."""
    async with transaction(user.id, rid) as conn:
        demand_id, _ = await _upsert_demand(conn, body, user.id)
        await sync_overseas_demand_embeddings(conn, demand_id)
    return Created(id=demand_id)


@router.post("/import", response_model=ImportSummary)
async def import_workbook(file: UploadFile = File(..., description="해외 수요 정리 엑셀 (출처·해외수요 시트)"),
                          dry_run: bool = Query(False, description="true 면 검사만 하고 저장하지 않는다"),
                          user: CurrentUser = Depends(require_roles(*EDITORS)), rid: str = Depends(request_id)):
    """정리 엑셀을 한 번에 올린다. 한 행이라도 잘못되면 아무것도 저장하지 않고 행별 오류를 돌려준다."""
    limit = get_settings().upload_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "파일이 너무 큽니다")
    try:
        parsed = parse_workbook(data)
    except OverseasImportError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": e.errors}) from e

    counts = {"sources_created": 0, "sources_updated": 0, "demands_created": 0, "demands_updated": 0, "embedded": 0}
    async with transaction(user.id, rid) as conn:
        for s in parsed.sources:
            _, created = await _upsert_source(conn, dict(s.__dict__), user.id)
            counts["sources_created" if created else "sources_updated"] += 1
        demand_ids = []
        for d in parsed.demands:
            body = OverseasDemandIn(**{k: v for k, v in d.__dict__.items()})
            demand_id, created = await _upsert_demand(conn, body, user.id)
            demand_ids.append(demand_id)
            counts["demands_created" if created else "demands_updated"] += 1
        if dry_run:
            raise Rollback()  # 검사만: DB 규칙까지 확인하고 아무것도 남기지 않는다
        for demand_id in demand_ids:
            counts["embedded"] += await sync_overseas_demand_embeddings(conn, demand_id)
    return ImportSummary(dry_run=dry_run, **counts)


@router.get("/demands")
async def list_demands(kind: str | None = None, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            f"""SELECT d.id, d.demand_no, d.title, d.demand_kind, d.region, d.tech_area, d.target_system,
                       d.target_period, d.confidence, d.status,
                       (SELECT array_agg(s.source_no ORDER BY ds.is_primary DESC, s.source_no)
                          FROM ax.overseas_demand_source ds JOIN ax.overseas_source s ON s.id = ds.source_id
                         WHERE ds.overseas_demand_id = d.id) AS source_nos
                  FROM ax.overseas_demand d
                 WHERE (%(kind)s::text IS NULL OR d.demand_kind = %(kind)s)
                   AND {CLEARANCE_OK.format(col='d.security_code')}
                 ORDER BY d.demand_no""", {"kind": kind, "uid": user.id})).fetchall()


@router.get("/demands/{demand_id}")
async def get_demand(demand_id: int, user: CurrentUser = Depends(get_current_user)):
    async with transaction(user.id) as conn:
        d = await (await conn.execute(
            f"SELECT d.* FROM ax.overseas_demand d WHERE d.id = %(id)s AND {CLEARANCE_OK.format(col='d.security_code')}",
            {"id": demand_id, "uid": user.id})).fetchone()
        if d is None:
            raise NotFound("해외 수요", demand_id)
        d["sources"] = await (await conn.execute(
            """SELECT s.source_no, s.issuer, s.title, s.published_on, s.url, s.license_note, s.allow_full_text,
                      s.checked_on, ds.is_primary
                 FROM ax.overseas_demand_source ds JOIN ax.overseas_source s ON s.id = ds.source_id
                WHERE ds.overseas_demand_id = %s ORDER BY ds.is_primary DESC, s.source_no""",
            (demand_id,))).fetchall()
        d["performances"] = await (await conn.execute(
            "SELECT * FROM ax.overseas_demand_performance WHERE overseas_demand_id = %s ORDER BY sort_order",
            (demand_id,))).fetchall()
    return d


@router.post("/demands/{demand_id}/embeddings", response_model=EmbedResult)
async def embed_demand(demand_id: int, user: CurrentUser = Depends(require_roles(*EDITORS))):
    async with transaction(user.id) as conn:
        return EmbedResult(updated=await sync_overseas_demand_embeddings(conn, demand_id))


@router.get("/demands/{demand_id}/similar-cards", response_model=list[SimilarCard])
async def similar_cards(demand_id: int, k: int = Query(10, ge=1, le=50),
                        user: CurrentUser = Depends(get_current_user)):
    """해외 수요와 가장 가까운 국내 성과 카드 (검수 확정된 카드 중 열람 가능한 것만).

    갭 분석의 첫 단계: 가까운 성과가 없으면 공백, 있으면 성능·성숙도를 비교한다.
    """
    async with transaction(user.id) as conn:
        visible = await (await conn.execute(
            f"SELECT 1 FROM ax.overseas_demand d WHERE d.id = %(id)s AND {CLEARANCE_OK.format(col='d.security_code')}",
            {"id": demand_id, "uid": user.id})).fetchone()
        if visible is None:
            raise NotFound("해외 수요", demand_id)
        model_id = await active_model_id(conn)
        pairs = ", ".join(f"('{a}', '{b}')" for a, b in SIMILAR_PAIRS)
        return await (await conn.execute(
            f"""WITH pairs(dfacet, cfacet) AS (VALUES {pairs}),
                scored AS (
                    SELECT ce.card_id, p.dfacet || '→' || p.cfacet AS matched_facet,
                           1 - (ce.embedding <=> oe.embedding) AS similarity
                      FROM pairs p
                      JOIN ax.overseas_demand_embedding oe
                        ON oe.facet = p.dfacet AND oe.overseas_demand_id = %(id)s AND oe.model_id = %(m)s
                      JOIN ax.card_embedding ce ON ce.facet = p.cfacet AND ce.model_id = %(m)s
                ), best AS (
                    SELECT DISTINCT ON (card_id) card_id, matched_facet, similarity
                      FROM scored ORDER BY card_id, similarity DESC
                )
                SELECT b.card_id, ac.title, pr.title AS project_title, round(b.similarity::numeric, 4)::float AS similarity,
                       b.matched_facet
                  FROM best b
                  JOIN ax.achievement_card ac ON ac.id = b.card_id AND ac.status = 'PUBLISHED'
                  LEFT JOIN ax.project pr ON pr.id = ac.project_id
                 WHERE {CLEARANCE_OK.format(col='ac.security_code')}
                 ORDER BY b.similarity DESC LIMIT %(k)s""",
            {"id": demand_id, "m": model_id, "uid": user.id, "k": k})).fetchall()
