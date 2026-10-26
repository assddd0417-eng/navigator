from pydantic import BaseModel, Field


class EvidenceIn(BaseModel):
    """원문 근거 지정. chunk_id 로 문서·조항·페이지를 자동 연결한다."""
    chunk_id: int
    quote: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class Created(BaseModel):
    id: int


class EmbedResult(BaseModel):
    updated: int = Field(description="새로 만들거나 갱신한 임베딩 수 (내용이 같으면 건너뜀)")
