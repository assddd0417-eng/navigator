from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.cards import Comparator

SourceKind = Literal["ROADMAP", "CALL", "EXPORT_REQ", "DOMESTIC"]
DemandKind = Literal["ROADMAP", "CALL", "EXPORT_REQ"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class OverseasSourceIn(BaseModel):
    source_no: str
    issuer: str
    title: str
    published_on: str | None = None
    url: str = Field(pattern=r"^https?://")
    source_kind: SourceKind
    license_note: str = Field(min_length=1, description="이용 조건 (예: CC BY 4.0, 표시 없음)")
    allow_full_text: bool = False
    checked_on: date
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    security_code: str = "PUBLIC"
    document_id: int | None = None
    note: str | None = None


class OverseasPerformanceIn(BaseModel):
    metric_name: str
    comparator: Comparator = "GTE"
    required_value: float | None = None
    required_max: float | None = None
    required_text: str | None = None
    unit: str | None = None
    quote: str | None = None


class OverseasDemandIn(BaseModel):
    demand_no: str
    title: str
    demand_kind: DemandKind
    region: str
    requirement: str
    source_nos: list[str] = Field(min_length=1, description="첫 번째가 주 출처")
    tech_area: str | None = None
    tech_taxonomy_id: int | None = None
    target_system: str | None = None
    weapon_system_id: int | None = None
    target_period: str | None = None
    quote: str | None = None
    confidence: Confidence = "MEDIUM"
    note: str | None = None
    security_code: str = "PUBLIC"
    performances: list[OverseasPerformanceIn] = []


class ImportSummary(BaseModel):
    dry_run: bool
    sources_created: int
    sources_updated: int
    demands_created: int
    demands_updated: int
    embedded: int
    gap_run_id: int | None = Field(None, description="올린 뒤 자동으로 돈 갭 분석 실행 번호")


class SimilarCard(BaseModel):
    card_id: int
    title: str
    project_title: str | None
    similarity: float
    matched_facet: str = Field(description="가장 가까웠던 관점 (해외 수요 패싯 → 카드 패싯)")
