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
    """파싱·청킹이 끝난 문서를 등록한다 (파서는 별도 파이프라인)."""
    doc_type_code: str
    title: str
    project_id: int | None = None
    program_id: int | None = None
    owner_dept_id: int | None = None
    source_system_code: str = "PMS"
    external_ref: str | None = None
    version_label: str | None = None
    authored_at: str | None = None
    storage_uri: str | None = None
    page_count: int | None = None
    security_code: str = "INTERNAL"
    is_deidentified: bool = False
    metadata: dict = {}
    sections: list[SectionIn] = []
    chunks: list[ChunkIn]


class DocumentCreated(BaseModel):
    id: int
    chunk_ids: list[int]
    embedded: int


class ChunkSearch(BaseModel):
    query: str
    k: int = 10
    doc_types: list[str] | None = None
    project_id: int | None = None


class ParsedChunkOut(BaseModel):
    content: str
    page_start: int | None = None
    page_end: int | None = None
    location: dict = {}


class ParsePreview(BaseModel):
    """POST /documents/parse: 저장하지 않고 추출 결과만 돌려준다 (업로드 전 미리보기)."""
    filename: str
    file_type: str
    parser: str
    page_count: int | None
    pages_without_text: list[int]
    char_count: int
    warnings: list[str]
    chunks: list[ParsedChunkOut]


class DocumentUploaded(DocumentCreated):
    filename: str
    file_type: str
    page_count: int | None
    pages_without_text: list[int]
    warnings: list[str]
