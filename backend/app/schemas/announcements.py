"""Navigator 공고·자격요건 스키마.

자격요건의 rule 칸은 종류(req_type_code)마다 형식이 정해져 있다. RULE_MODELS 가 형식을 검사하고
정규화한 dict 를 저장한다. 3단계 판정기는 이 형식을 그대로 읽는다.
"""
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.common import EvidenceIn
from app.schemas.navigator import CompanySize, Region

Domain = Literal["DEFENSE_RND", "GENERAL_SUPPORT", "PROCUREMENT"]
Status = Literal["DRAFT", "PUBLISHED", "CANCELLED"]


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Range(_Rule):
    @model_validator(mode="after")
    def _order(self):
        lo, hi = self.bounds()
        if lo is None and hi is None:
            raise ValueError("최솟값·최댓값 중 하나는 있어야 합니다")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("최솟값이 최댓값보다 큽니다")
        return self

    def bounds(self) -> tuple[Any, Any]:  # pragma: no cover - 하위 클래스가 구현
        raise NotImplementedError


class CompanySizeRule(_Rule):
    allowed: list[CompanySize] = Field(min_length=1)


class BusinessAgeRule(_Range):
    min_years: float | None = Field(default=None, ge=0)
    max_years: float | None = Field(default=None, ge=0)

    def bounds(self):
        return self.min_years, self.max_years


class RequiredCertRule(_Rule):
    any_of: list[str] = Field(min_length=1, description="code_certification_type 코드")


class MinCreditGradeRule(_Rule):
    min_grade: str = Field(description="code_credit_grade 등급 (예: BB-)")


class RegionRule(_Rule):
    allowed: list[Region] = Field(min_length=1)


class TrlRule(_Range):
    min: int | None = Field(default=None, ge=1, le=9)
    max: int | None = Field(default=None, ge=1, le=9)

    def bounds(self):
        return self.min, self.max


class EmployeeCountRule(_Range):
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)

    def bounds(self):
        return self.min, self.max


class RevenueRule(_Range):
    min_krw: int | None = Field(default=None, ge=0)
    max_krw: int | None = Field(default=None, ge=0)

    def bounds(self):
        return self.min_krw, self.max_krw


class BusinessStatusRule(_Rule):
    allowed: list[Literal["ACTIVE", "SUSPENDED", "CLOSED"]] = Field(default=["ACTIVE"], min_length=1)


class DefenseCompanyRule(_Rule):
    required: bool = True


class RndExperienceRule(_Rule):
    min_count: int = Field(default=1, ge=1)
    role: Literal["LEAD", "PARTICIPANT"] | None = None
    within_years: int | None = Field(default=None, ge=1, description="최근 N년 안에 끝난 과제만")


class PatentRule(_Rule):
    min_count: int = Field(default=1, ge=1)
    status: Literal["APPLIED", "REGISTERED"] | None = None
    ipc_prefixes: list[str] = []


class OtherRule(_Rule):
    model_config = ConfigDict(extra="allow")   # 규칙으로 못 쓰는 요건: 문장(description)이 본체


RULE_MODELS: dict[str, type[_Rule]] = {
    "COMPANY_SIZE": CompanySizeRule, "BUSINESS_AGE": BusinessAgeRule, "REQUIRED_CERT": RequiredCertRule,
    "MIN_CREDIT_GRADE": MinCreditGradeRule, "REGION": RegionRule, "TRL": TrlRule,
    "EMPLOYEE_COUNT": EmployeeCountRule, "REVENUE": RevenueRule, "BUSINESS_STATUS": BusinessStatusRule,
    "DEFENSE_COMPANY": DefenseCompanyRule, "RND_EXPERIENCE": RndExperienceRule, "PATENT": PatentRule,
    "OTHER": OtherRule,
}


def normalize_rule(req_type_code: str, rule: dict[str, Any]) -> dict[str, Any]:
    """종류별 형식 검사 후 정규화한 rule. 틀리면 ValueError (한국어 메시지)."""
    model = RULE_MODELS.get(req_type_code)
    if model is None:
        raise ValueError(f"알 수 없는 자격요건 종류: {req_type_code} (가능: {', '.join(RULE_MODELS)})")
    try:
        return model.model_validate(rule).model_dump(exclude_none=True)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'rule'}: {err['msg']}" for err in e.errors())
        raise ValueError(f"{req_type_code} 규칙 형식 오류 — {msgs}") from None


class RequirementIn(BaseModel):
    req_type_code: str
    rule: dict[str, Any] = {}
    is_mandatory: bool = Field(default=True, description="true 필수 / false 우대")
    description: str = Field(min_length=1, max_length=1000, description="사람이 읽는 요건 문장")
    evidence: EvidenceIn | None = Field(default=None, description="공고문 청크 근거 (PDF 로 올린 공고)")
    source_quote: str | None = Field(default=None, max_length=2000)
    source_page: int | None = Field(default=None, gt=0)


class RequirementUpdate(BaseModel):
    rule: dict[str, Any] | None = None
    is_mandatory: bool | None = None
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    source_quote: str | None = None
    source_page: int | None = Field(default=None, gt=0)


class TechNeedIn(BaseModel):
    tech_name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    tech_taxonomy_id: int | None = None
    ipc_codes: list[str] = []
    is_core: bool = True


class AnnouncementFields(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    agency_name: str | None = Field(default=None, min_length=1, max_length=200)
    agency_org_id: int | None = None
    domain: Domain | None = None
    program_id: int | None = None
    summary: str | None = None
    target_desc: str | None = None
    support_amount_krw: int | None = Field(default=None, ge=0)
    support_period_months: int | None = Field(default=None, gt=0)
    receipt_start: date | None = None
    receipt_end: date | None = None
    source_url: str | None = None
    status: Status | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.receipt_start and self.receipt_end and self.receipt_end < self.receipt_start:
            raise ValueError("접수 마감일이 접수 시작일보다 빠릅니다")
        return self


class AnnouncementCreate(AnnouncementFields):
    announcement_no: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    agency_name: str = Field(min_length=1, max_length=200)
    domain: Domain = "DEFENSE_RND"
    status: Status = "PUBLISHED"
    requirements: list[RequirementIn] = []
    tech_needs: list[TechNeedIn] = []


class AnnouncementUpdate(AnnouncementFields):
    pass


class AnnouncementCreated(BaseModel):
    id: int
    requirement_ids: list[int] = []
    tech_need_ids: list[int] = []
    document_id: int | None = None
    chunk_count: int | None = None
    warnings: list[str] = []
