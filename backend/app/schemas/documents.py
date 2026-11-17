from pydantic import BaseModel


class SectionIn(BaseModel):
    key: str                         # 요청 안에서만 쓰는 임시 키 (청크·하위 조항이 참조)
    parent_key: str | None = None
    section_no: str | None = None
    heading: str | None = None
    level: int = 1
    page_start: int | None = None
    page_end: int | None = None


class ChunkIn(BaseModel):
    content: str
    section_key: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    location: dict = {}
    chunk_type: str = "TEXT"


class DocumentCreate(BaseModel):
    """파싱·청킹이 끝난 공고문."""
    doc_type_code: str
    title: str
    program_id: int | None = None
    source_system_code: str = "MANUAL"
    external_ref: str | None = None
    version_label: str | None = None
    authored_at: str | None = None
    storage_uri: str | None = None
    page_count: int | None = None
    security_code: str = "PUBLIC"
    metadata: dict = {}
    sections: list[SectionIn] = []
    chunks: list[ChunkIn]


class DocumentCreated(BaseModel):
    id: int
    chunk_ids: list[int]
    embedded: int
