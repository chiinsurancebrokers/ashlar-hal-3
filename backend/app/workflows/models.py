from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrictWorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    SUBMITTED = "submitted"


class PolicyStatus(str, Enum):
    ACTIVE = "active"
    LAPSED = "lapsed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PreauthorisationStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING = "pending"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    DECLINED = "declined"


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    INFO_REQUIRED = "info_required"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    DECLINED = "declined"
    PAID = "paid"


class RenewalStatus(str, Enum):
    MARKET_REVIEW = "market_review"
    QUOTED = "quoted"
    PROPOSAL = "proposal"
    SELECTED = "selected"
    COMPLETED = "completed"


class PlanSelectionRecord(StrictWorkflowModel):
    plan_key: str = Field(min_length=1, max_length=200)
    selected_by: Literal["client", "broker"] = "client"
    selected_at: datetime = Field(default_factory=utcnow)
    note: str | None = Field(default=None, max_length=1000)


class ApplicationRecord(StrictWorkflowModel):
    application_id: UUID = Field(default_factory=uuid4)
    plan_key: str = Field(min_length=1, max_length=200)
    status: ApplicationStatus = ApplicationStatus.DRAFT
    required_sections: list[str] = Field(default_factory=list)
    completed_sections: list[str] = Field(default_factory=list)
    section_data: dict[str, Any] = Field(default_factory=dict)
    submission_reference: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def missing_sections(self) -> list[str]:
        completed = set(self.completed_sections)
        return [item for item in self.required_sections if item not in completed]


class PolicyRecord(StrictWorkflowModel):
    policy_id: UUID = Field(default_factory=uuid4)
    policy_number: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=120)
    plan_key: str = Field(min_length=1, max_length=200)
    start_date: date
    renewal_date: date
    status: PolicyStatus = PolicyStatus.ACTIVE
    document_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.renewal_date <= self.start_date:
            raise ValueError("renewal_date must be later than start_date")
        return self


class PolicyWallet(StrictWorkflowModel):
    policy_number: str
    provider: str
    plan_key: str
    start_date: date
    renewal_date: date
    core_facts: dict[str, Any] = Field(default_factory=dict)
    verified_benefits: dict[str, Any] = Field(default_factory=dict)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    terms_status: str = "issued_terms_unverified"


class PreauthorisationRecord(StrictWorkflowModel):
    request_id: UUID = Field(default_factory=uuid4)
    plan_key: str = Field(min_length=1, max_length=200)
    service_key: str = Field(min_length=1, max_length=160)
    provider_name: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    planned_date: date | None = None
    status: PreauthorisationStatus = PreauthorisationStatus.DRAFT
    document_refs: list[str] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ClaimRecord(StrictWorkflowModel):
    claim_id: UUID = Field(default_factory=uuid4)
    plan_key: str = Field(min_length=1, max_length=200)
    service_date: date | None = None
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: ClaimStatus = ClaimStatus.DRAFT
    document_refs: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=1200)
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RenewalRecord(StrictWorkflowModel):
    renewal_id: UUID = Field(default_factory=uuid4)
    current_plan_key: str = Field(min_length=1, max_length=200)
    renewal_date: date
    status: RenewalStatus = RenewalStatus.MARKET_REVIEW
    selected_plan_key: str | None = Field(default=None, max_length=200)
    started_at: datetime = Field(default_factory=utcnow)


class WorkflowResult(StrictWorkflowModel):
    action: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1200)
    payload: dict[str, Any] = Field(default_factory=dict)
