"""공고문 원문 저장: 파일을 읽어 조항·청크로 나누고 임베딩한다."""
from fastapi import UploadFile
from psycopg import AsyncConnection
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.repositories.sql import insert
from app.schemas.documents import DocumentCreate, DocumentCreated
from app.services.document_parser import ParsedDocument, ParseError, parse_upload
from app.services.embedding import sha256, sync_chunk_embeddings


async def store_document(conn: AsyncConnection, body: DocumentCreate) -> DocumentCreated:
    """열린 트랜잭션 안에서 문서·조항·청크를 넣고 임베딩한다."""
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
