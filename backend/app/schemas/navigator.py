"""Navigator 기업 프로필 스키마."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Origin = Literal["SELF", "EXTERNAL", "INTERNAL", "STAFF"]
Region = Literal["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
                 "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
CompanySize = Literal["LARGE", "MIDSIZE", "SME", "STARTUP", "VENTURE"]
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class PatentIn(BaseModel):
    application_no: str = Field(min_length=1, max_length=50)
    registration_no: str | None = None
    title: str = Field(min_length=1, max_length=500)
    abstract: str | None = None
    ipc_codes: list[str] = []
    status: Literal["APPLIED", "REGISTERED", "LAPSED"] = "APPLIED"
    applied_on: date | None = None
    registered_on: date | None = None

    @model_validator(mode="after")
    def _registered_needs_no(self):
        if self.status == "REGISTERED" and not self.registration_no:
            raise ValueError("등록 특허는 등록번호가 필요합니다")
        return self


class CertificationIn(BaseModel):
    cert_type_code: str
    cert_no: str | None = None
    issuer: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None


class CreditRatingIn(BaseModel):
    agency: Literal["NICE", "KED", "SELF", "OTHER"] = "SELF"
    grade: str = Field(min_length=1, max_length=10)
    rated_on: date | None = None
    valid_until: date | None = None


class RndHistoryIn(BaseModel):
    project_no: str | None = None
    title: str = Field(min_length=1, max_length=500)
    funding_agency: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    amount_krw: int | None = Field(default=None, ge=0)
    role: Literal["LEAD", "PARTICIPANT"] = "LEAD"
    summary: str | None = None


class ProfileFields(BaseModel):
    main_business: str | None = Field(default=None, max_length=2000)
    homepage: str | None = None
    company_size: CompanySize | None = None
    established_on: date | None = None
    employee_count: int | None = Field(default=None, ge=0)
    annual_revenue_krw: int | None = Field(default=None, ge=0)
    revenue_year: int | None = Field(default=None, ge=1900, le=2100)
    region: Region | None = None
    address: str | None = None


class CompanyLists(BaseModel):
    patents: list[PatentIn] = []
    certifications: list[CertificationIn] = []
    credit_ratings: list[CreditRatingIn] = []
    rnd_history: list[RndHistoryIn] = []


class CompanyRegister(ProfileFields, CompanyLists):
    business_reg_no: str = Field(description="사업자등록번호 (하이픈 있어도 됨)", examples=["123-45-67890"])
    company_name: str = Field(min_length=1, max_length=200)
    representative_name: str = Field(min_length=1, max_length=100, description="국세청 진위확인용 대표자명")
    opened_on: date = Field(description="국세청 진위확인용 개업일")
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320,
                       description="관리 링크를 받을 이메일 (필수). 수정은 이 주소로 받은 링크로만 가능")


class CompanyUpdate(ProfileFields):
    # 목록 칸을 보내면 SELF 행 전체 교체
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    patents: list[PatentIn] | None = None
    certifications: list[CertificationIn] | None = None
    credit_ratings: list[CreditRatingIn] | None = None
    rnd_history: list[RndHistoryIn] | None = None


class LinkSent(BaseModel):
    sent_to: str = Field(description="가린 이메일 (예: a***@example.com)")
    expires_at: str
    dev_management_link: str | None = Field(
        default=None, description="NAVIGATOR_DEV_EXPOSE_LINK=true 일 때만 (로컬 확인용)")


class RegisterResult(LinkSent):
    organization_id: int
    business_reg_no: str
    biz_verify_status: Literal["VERIFIED", "UNVERIFIED", "FAILED"]
    biz_verify_label: str
    business_status: str
    message: str
