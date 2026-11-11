from typing import Literal

from pydantic import BaseModel, Field


class GapRulesIn(BaseModel):
    """판정 기준을 이번 실행에만 바꿔 본다 (비우면 기본값). 바꾼 값은 gap_run.rule_snapshot 에 남는다."""
    coverage_threshold: float | None = Field(None, ge=-1, le=1, description="이보다 낮으면 공백 (기본 0.55)")
    near_k: int | None = Field(None, ge=1, le=50)
    evidence_cards: int | None = Field(None, ge=1, le=10)
    issue_threshold: float | None = Field(None, ge=-1, le=1)
    min_trl: int | None = Field(None, ge=1, le=9)
    localization_keywords: list[str] | None = None


class GapRunIn(BaseModel):
    demand_ids: list[int] | None = Field(None, description="비우면 보관되지 않은 해외 수요 전체")
    rules: GapRulesIn | None = None
    note: str | None = None


class GapRunOut(BaseModel):
    id: int
    demand_count: int
    finding_count: int


class GapDecisionIn(BaseModel):
    decision: Literal["CONFIRM", "REJECT"]
    reason: str | None = Field(None, description="기각이면 필수 (예: 이미 국내에 있음)")
