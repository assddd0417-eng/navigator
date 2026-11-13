"""공고·자격요건 스키마. rule 형식은 종류별로 RULE_MODELS 에서 검사·정규화 (eligibility.py 가 읽음)."""
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


class NoDisqualificationRule(_Rule):
    checks: list[Literal["TAX_DELINQUENT", "INSOLVENT", "RND_RESTRICTED"]] = Field(
        default=["TAX_DELINQUENT", "INSOLVENT", "RND_RESTRICTED"], min_length=1)


class DefenseSupplyRule(_Rule):
    defense_goods: bool | None = Field(default=None, description="true 면 방산물자 생산 기업만")
    min_supply_krw: int | None = Field(default=None, ge=0, description="최근 3년 군 납품 실적 하한 (원)")


class ExportRule(_Rule):
    min_krw: int = Field(default=1, ge=0)


class OtherRule(_Rule):
    model_config = ConfigDict(extra="allow")   # 규칙으로 못 쓰는 요건: 문장(description)이 본체


RULE_MODELS: dict[str, type[_Rule]] = {
    "COMPANY_SIZE": CompanySizeRule, "BUSINESS_AGE": BusinessAgeRule, "REQUIRED_CERT": RequiredCertRule,
    "MIN_CREDIT_GRADE": MinCreditGradeRule, "REGION": RegionRule, "TRL": TrlRule,
    "EMPLOYEE_COUNT": EmployeeCountRule, "REVENUE": RevenueRule, "BUSINESS_STATUS": BusinessStatusRule,
    "DEFENSE_COMPANY": DefenseCompanyRule, "RND_EXPERIENCE": RndExperienceRule, "PATENT": PatentRule,
    "NO_DISQUALIFICATION": NoDisqualificationRule, "DEFENSE_SUPPLY": DefenseSupplyRule, "EXPORT": ExportRule,
    "OTHER": OtherRule,
}


def normalize_rule(req_type_code: str, rule: dict[str, Any]) -> dict[str, Any]:
    model = RULE_MODELS.get(req_type_code)
    if model is None:
        raise ValueError(f"알 수 없는 자격요건 종류: {req_type_code} (가능: {', '.join(RULE_MODELS)})")
    try:
        return model.model_validate(rule).model_dump(exclude_none=True)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'rule'}: {err['msg']}" for err in e.errors())
        raise ValueError(f"{req_type_code} 규칙 형식 오류: {msgs}") from None


class RequirementIn(BaseModel):
    req_type_code: str
    rule: dict[str, Any] = {}
    is_mandatory: bool = Field(default=True, description="true 필수 / false 우대")
    description: str = Field(min_length=1, max_length=1000, description="사람이 읽는 요건 문장")
    evidence: EvidenceIn | None = Field(default=None, description="공고문 청크 근거 (PDF 로 올린 공고)")
    source_quote: str | None = Field(default=None, max_length=2000)
    source_page: int | None = Field(default=None, gt=0)
    origin: Literal["MANUAL", "AI_EXTRACTED"] = Field(default="MANUAL", description="AI_EXTRACTED = 뽑은 후보를 담당자가 확인")


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


class AnnouncementFromText(BaseModel):
    """홈페이지에 없는 공고를 담당자가 공고문 글자로 등록. 작성중으로 만들고 조건은 확인 화면에서 넣는다."""
    title: str = Field(min_length=1, max_length=500)
    agency_name: str = Field(default="국방기술진흥연구소", min_length=1, max_length=200)
    announcement_no: str | None = Field(default=None, max_length=100, description="비우면 MAN-날짜시각")
    body_text: str = Field(min_length=20, max_length=200_000, description="공고문 본문 (붙여넣기)")
    source_url: str | None = None
    posted_on: date | None = None
    domain: Domain = "DEFENSE_RND"


class AnnouncementReview(BaseModel):
    """확인 화면 저장. 조건·요구기술은 통째로 바꾼다."""
    fields: AnnouncementUpdate = AnnouncementUpdate()
    requirements: list[RequirementIn] = []
    tech_needs: list[TechNeedIn] = []
    confirm: bool = Field(default=True, description="조건 확인 완료로 표시")
    publish: bool = Field(default=False, description="확인과 함께 공개 (구독 기업 알림)")
