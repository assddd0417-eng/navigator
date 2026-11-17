from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from psycopg import AsyncConnection
from starlette.concurrency import run_in_threadpool

from app.auth import CurrentUser, get_current_user, request_id, require_roles
from app.config import get_settings
from app.db import transaction
from app.repositories.sql import insert
from app.schemas.documents import (ChunkIn, ChunkSearch, DocumentCreate, DocumentCreated, DocumentUploaded,
                                   ParsePreview)
from app.services.document_parser import ParsedDocument, ParseError, parse_upload
from app.services.embedding import active_model_id, embed_query, sha256, sync_chunk_embeddings
from app.services.synonyms import expand, load_groups
from app.services.project_linker import link_document

router = APIRouter(prefix="/documents", tags=["원문 문서·RAG"])


@router.post("", response_model=DocumentCreated, status_code=201)
async def create_document(body: DocumentCreate, user: CurrentUser = Depends(require_roles("CURATOR", "PLANNER")),
                          rid: str = Depends(request_id)):
    return await _store_document(body, user, rid)


async def _store_document(body: DocumentCreate, user: CurrentUser, rid: str) -> DocumentCreated:
    """이어달리기 문서 등록: 저장 후 본문의 과제번호·과제명으로 과제에 연결한다 (0032)."""
    async with transaction(user.id, rid) as conn:
        created = await store_document(conn, body)
        created.linked_projects = await link_document(conn, created.id)
        # 대상 과제를 못 찾은 문서(공모서 등)는 올린 사람 부서 소관
        await conn.execute("UPDATE ax.source_document SET owner_dept_id = %s WHERE id = %s AND owner_dept_id IS NULL",
                           (user.department_id, created.id))
        return created


async def store_document(conn: AsyncConnection, body: DocumentCreate) -> DocumentCreated:
    """열린 트랜잭션 안에서 문서·조항·청크를 넣고 임베딩한다 (공고 PDF 등록도 같이 쓴다)."""
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


async def parse_file(file: UploadFile) -> ParsedDocument:
    settings = get_settings()
    limit = settings.upload_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ParseError("file_too_large", f"파일이 {settings.upload_max_mb}MB 를 넘습니다", 413)
    return await run_in_threadpool(parse_upload, data, file.filename or "", max_pages=settings.pdf_max_pages,
                                   chunk_max_chars=settings.chunk_max_chars)


@router.post("/parse", response_model=ParsePreview)
async def parse_document(file: UploadFile = File(..., description="PDF · TXT · MD"),
                         user: CurrentUser = Depends(require_roles("CURATOR", "PLANNER"))):
    """업로드 파일에서 텍스트를 추출·청킹해 미리보기로 돌려준다 (DB 저장 없음)."""
    p = await parse_file(file)
    return ParsePreview(filename=p.filename, file_type=p.file_type, parser=p.parser, page_count=p.page_count,
                        pages_without_text=p.pages_without_text, char_count=p.char_count, warnings=p.warnings,
                        chunks=[c.__dict__ for c in p.chunks])


@router.post("/upload", response_model=DocumentUploaded, status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="PDF · TXT · MD (스캔본 OCR 미지원)"),
    doc_type_code: str = Form(...),
    title: str | None = Form(None, description="비우면 파일 이름"),
    project_id: int | None = Form(None),
    program_id: int | None = Form(None),
    owner_dept_id: int | None = Form(None),
    security_code: str = Form("INTERNAL"),
    source_system_code: str = Form("PMS"),
    external_ref: str | None = Form(None),
    version_label: str | None = Form(None),
    authored_at: str | None = Form(None),
    user: CurrentUser = Depends(require_roles("CURATOR", "PLANNER")),
    rid: str = Depends(request_id),
):
    """파일을 올려 텍스트 추출 → 쪽 단위 청킹 → 등록·임베딩까지 한 번에 한다.

    원본 파일 자체는 저장하지 않는다 (storage_uri 없음, 파일 SHA-256 은 metadata 에 기록).
    """
    p = await parse_file(file)
    body = DocumentCreate(
        doc_type_code=doc_type_code, title=(title or "").strip() or PurePath(p.filename).stem or "제목 없음",
        project_id=project_id, program_id=program_id, owner_dept_id=owner_dept_id, security_code=security_code,
        external_ref=external_ref, version_label=version_label, authored_at=authored_at,
        source_system_code=source_system_code, page_count=p.page_count,
        metadata={"source_filename": p.filename, "file_type": p.file_type, "parser": p.parser,
                  "file_sha256": p.file_sha256, "pages_without_text": p.pages_without_text},
        chunks=[ChunkIn(content=c.content, page_start=c.page_start, page_end=c.page_end, location=c.location)
                for c in p.chunks])
    created = await _store_document(body, user, rid)
    return DocumentUploaded(**created.model_dump(), filename=p.filename, file_type=p.file_type,
                            page_count=p.page_count, pages_without_text=p.pages_without_text, warnings=p.warnings)


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
    async with transaction(user.id) as conn:
        query = expand(body.query, await load_groups(conn))  # 동의어 사전으로 검색어 넓히기
    vec = await embed_query(query)
    async with transaction(user.id) as conn:
        await active_model_id(conn)  # 검색 함수가 보는 활성 모델을 이 서버의 EMBEDDER 와 맞춘다
        return await (await conn.execute(
            "SELECT * FROM ax.search_chunks(%s, %s, %s, %s, %s)",
            (vec, user.id, body.k, body.doc_types, body.project_id))).fetchall()
