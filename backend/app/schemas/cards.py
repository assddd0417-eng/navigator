from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceIn

Comparator = Literal["GTE", "LTE", "EQ", "RANGE"]
RelationStatus = Literal["CONFIRMED", "NEEDS_CONFIRMATION", "REJECTED"]


class TechnologyIn(BaseModel):
    tech_name: str
    principle: str | None = None
    tech_taxonomy_id: int | None = None
    is_primary: bool = False
    evidence: list[EvidenceIn] = []


class PerformanceIn(BaseModel):
    metric_name: str
    comparator: Comparator = "GTE"
    target_value: float | None = None
    achieved_value: float | None = None
    achieved_text: str | None = None
    unit: str | None = None
    is_achieved: bool | None = None
    test_condition: str | None = None
    evidence: list[EvidenceIn] = []


class OpenIssueIn(BaseModel):
    issue_type: Literal["UNRESOLVED_TECH", "UNMET_TARGET", "FOLLOW_UP_NEED"]
    description: str
    priority: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    source: Literal["AI", "EXPERT", "REPORT"] = "AI"
    evidence: list[EvidenceIn] = []


class OutcomeIn(BaseModel):
    outcome_type_code: str
    title: str
    identifier: str | None = None
    outcome_date: str | None = None
    holder: str | None = None


class RelationIn(BaseModel):
    id: int = Field(description="무기체계/품목/기관/사업트랙 ID")
    relation_type: str | None = None
    relation_status: RelationStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class CardCreate(BaseModel):
    card_no: str
    project_id: int
    title: str
    core_achievement: str
    summary: str | None = None
    trl: int | None = Field(default=None, ge=1, le=9)
    trl_basis: str | None = None
    dev_stage_code: str | None = None
    test_conditions: str | None = None
    application_env: str | None = None
    extracted_by: Literal["AI", "HUMAN", "IMPORT"] = "HUMAN"
    extraction_model: str | None = None
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    security_code: str = "INTERNAL"
    technologies: list[TechnologyIn] = []
    performances: list[PerformanceIn] = []
    open_issues: list[OpenIssueIn] = []
    outcomes: list[OutcomeIn] = []
    weapon_systems: list[RelationIn] = []
    items: list[RelationIn] = []
    companies: list[RelationIn] = []
    programs: list[RelationIn] = []
    evidence: list[EvidenceIn] = Field(default=[], description="카드 자체(핵심성과 등)의 근거")


class CardUpdate(BaseModel):
    title: str | None = None
    core_achievement: str | None = None
    summary: str | None = None
    trl: int | None = Field(default=None, ge=1, le=9)
    trl_basis: str | None = None
    dev_stage_code: str | None = None
    test_conditions: str | None = None
    application_env: str | None = None
    has_follow_up_research: bool | None = None
    latest_utilization_at: str | None = None
    utilization_assessment: dict | None = None
