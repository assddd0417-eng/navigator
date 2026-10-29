from fastapi import APIRouter, Depends, Query

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.db import transaction
from app.repositories.sql import insert
from app.schemas.documents import ChunkSearch, DocumentCreate, DocumentCreated
from app.services.embedding import embed_query, sha256, sync_chunk_embeddings

router = APIRouter(prefix="/documents", tags=["원문 문서·RAG"])


@router.post("", response_model=DocumentCreated, status_code=201)
async def create_document(body: DocumentCreate, user: CurrentUser = Depends(require_roles("CURATOR", "PLANNER")),
                          rid: str = Depends(request_id)):
    async with transaction(user.id, rid) as conn:
        doc_id = await insert(conn, "source_document", {
            **body.model_dump(exclude={"sections", "chunks"}), "parse_status": "CHUNKED"})
        section_ids: dict[str, int] = {}
        for i, s in enumerate(body.sections):
            section_ids[s.key] = await insert(conn, "document_section", {
                "document_id": doc_id, "parent_id": section_ids.get(s.parent_key) if s.parent_key else None,
                "section_no": s.section_no, "heading": s.heading, "level": s.level,
                "page_start": s.page_start, "page_end": s.page_end, "ordinal": i})
        chunk_ids = []
        for i, c in enumerate(body.chunks):
            chunk_ids.append(await insert(conn, "document_chunk", {
                "document_id": doc_id, "section_id": section_ids.get(c.section_key) if c.section_key else None,
                "chunk_index": i, "content": c.content, "content_sha256": sha256(c.content),
                "page_start": c.page_start, "page_end": c.page_end, "location": c.location,
                "chunk_type": c.chunk_type}))
        embedded = await sync_chunk_embeddings(conn, doc_id)
    return DocumentCreated(id=doc_id, chunk_ids=chunk_ids, embedded=embedded)


@router.get("")
async def list_documents(project_id: int | None = None, parse_status: str | None = None,
                         limit: int = Query(50, le=200), offset: int = 0,
                         user: CurrentUser = Depends(get_current_user)):
    """문서 처리 현황 (요청자가 열람 가능한 문서만). 청크·임베딩 수 포함."""
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            """SELECT d.id, d.doc_type_code, t.name_ko AS doc_type_name, d.title, d.project_id,
                       d.owner_dept_id, d.parse_status, d.security_code, d.created_at,
                       (SELECT count(*) FROM ax.document_chunk c WHERE c.document_id = d.id) AS chunk_count
                  FROM ax.source_document d JOIN ax.code_document_type t ON t.code = d.doc_type_code
                 WHERE (%(project_id)s::bigint IS NULL OR d.project_id = %(project_id)s)
                   AND (%(parse_status)s::text IS NULL OR d.parse_status = %(parse_status)s)
                   AND ax.can_read_document(%(uid)s, d.id)
                 ORDER BY d.created_at DESC LIMIT %(limit)s OFFSET %(offset)s""",
            {"project_id": project_id, "parse_status": parse_status, "uid": user.id,
             "limit": limit, "offset": offset})).fetchall()


@router.post("/search")
async def search(body: ChunkSearch, user: CurrentUser = Depends(get_current_user)):
    """권한 필터가 적용된 RAG 청크 검색 (출처 문서·조항·페이지 포함)."""
    vec = await embed_query(body.query)
    async with transaction(user.id) as conn:
        return await (await conn.execute(
            "SELECT * FROM ax.search_chunks(%s, %s, %s, %s, %s)",
            (vec, user.id, body.k, body.doc_types, body.project_id))).fetchall()
