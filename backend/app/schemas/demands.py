from pydantic import BaseModel, Field

from app.schemas.cards import Comparator


class PerformanceReqIn(BaseModel):
    metric_name: str
    comparator: Comparator = "GTE"
    required_value: float | None = None
    required_max: float | None = None
    required_text: str | None = None
    unit: str | None = None
    is_mandatory: bool = True


class DemandTechIn(BaseModel):
    tech_name: str
    description: str | None = None
    tech_taxonomy_id: int | None = None


class DemandCreate(BaseModel):
    demand_no: str
    title: str
    tech_need: str
    business_purpose: str | None = None
    application_env: str | None = None
    required_trl_min: int | None = Field(default=None, ge=1, le=9)
    required_trl_max: int | None = Field(default=None, ge=1, le=9)
    dev_stage_code: str | None = None
    target_program_id: int | None = None
    requesting_dept_id: int | None = None
    status: str = "OPEN"
    security_code: str = "INTERNAL"
    performance_reqs: list[PerformanceReqIn] = []
    technologies: list[DemandTechIn] = Field(default=[], description="기술요소 (2개 이상이면 융합형 탐색)")
    weapon_system_ids: list[int] = []
    item_ids: list[int] = []


class DemandUpdate(BaseModel):
    title: str | None = None
    tech_need: str | None = None
    business_purpose: str | None = None
    application_env: str | None = None
    required_trl_min: int | None = Field(default=None, ge=1, le=9)
    required_trl_max: int | None = Field(default=None, ge=1, le=9)
    target_program_id: int | None = None
    status: str | None = None


class MatchRequest(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=100)
