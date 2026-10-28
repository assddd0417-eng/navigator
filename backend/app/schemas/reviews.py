from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AssignmentCreate(BaseModel):
    review_role: Literal["DEPT_OWNER", "COLLAB_DEPT", "EXPERT"]
    assignee_user_id: int | None = None
    assignee_dept_id: int | None = None
    due_at: datetime | None = None
    note: str | None = None


class DecisionCreate(BaseModel):
    """검토자는 요청 사용자 본인으로 고정된다 (본문으로 지정 불가)."""
    decision_code: Literal["ADOPT", "HOLD", "EXCLUDE", "NEEDS_INFO"]
    is_final: bool = False
    assignment_id: int | None = None
    linkage_type_override: str | None = None
    opinion: str | None = None
    relevance_rating: int | None = Field(default=None, ge=1, le=5)
    is_low_relevance: bool | None = None
    evidence_adequacy: int | None = Field(default=None, ge=1, le=5)
    dev_needs_accuracy: Literal["CORRECT", "PARTIAL", "INCORRECT"] | None = None
    supersedes_id: int | None = None


class WithdrawRequest(BaseModel):
    reason: str


class ConfirmationCreate(BaseModel):
    subject_type: Literal["COMPANY", "ITEM", "TECH", "WEAPON_SYSTEM", "PROGRAM", "PERFORMANCE", "OTHER"]
    description: str
    assignee_user_id: int | None = None


class ConfirmationResolve(BaseModel):
    status: Literal["RESOLVED", "DISMISSED"]
    resolution_note: str | None = None


class CommentCreate(BaseModel):
    body: str
    parent_id: int | None = None
