from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from backend.app.schemas.applicant import Applicant


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Case models fail closed on unknown fields.

    Insurance case state is evidence-bearing business data. Silently accepting
    a misspelled field is more dangerous than rejecting it, particularly once
    Proposal Studio and Asklepios begin exchanging structured payloads.
    """

    model_config = ConfigDict(extra="forbid")


class CaseStatus(str, Enum):
    DISCOVERY = "discovery"
    MARKET_REVIEW = "market_review"
    COMPARISON = "comparison"
    PROPOSAL = "proposal"
    APPLICATION = "application"
    ACTIVE_POLICY = "active_policy"
    CLAIM = "claim"
    RENEWAL = "renewal"
    CLOSED = "closed"


class FactStatus(str, Enum):
    DECLARED = "declared"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"


class FactSourceType(str, Enum):
    CLIENT_DECLARATION = "client_declaration"
    BROKER_DECLARATION = "broker_declaration"
    QUOTE_ENGINE = "quote_engine"
    CARRIER_QUOTE = "carrier_quote"
    CARRIER_TOB = "carrier_tob"
    POLICY_WORDING = "policy_wording"
    POLICY_SCHEDULE = "policy_schedule"
    APPLICATION = "application"
    CLAIM_DOCUMENT = "claim_document"
    PROPOSAL_STUDIO = "proposal_studio"
    SYSTEM = "system"


class ConsentStatus(str, Enum):
    GRANTED = "granted"
    REVOKED = "revoked"


class CaseClient(StrictModel):
    client_id: UUID = Field(default_factory=uuid4)
    display_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    preferred_language: str = Field(default="en", pattern="^(en|el)$")


class CaseDocument(StrictModel):
    document_id: UUID = Field(default_factory=uuid4)
    filename: str = Field(min_length=1, max_length=255)
    document_type: str = Field(default="other", max_length=80)
    provider: str | None = Field(default=None, max_length=120)
    plan_key: str | None = Field(default=None, max_length=200)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    uploaded_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FactSource(StrictModel):
    source_type: FactSourceType
    source_ref: str | None = Field(default=None, max_length=500)
    document_id: UUID | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, max_length=800)
    observed_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def require_document_for_page(self) -> "FactSource":
        if self.page is not None and self.document_id is None:
            raise ValueError("document_id is required when a source page is supplied")
        return self


class Fact(StrictModel):
    fact_id: UUID = Field(default_factory=uuid4)
    subject: str = Field(default="case", min_length=1, max_length=250)
    key: str = Field(min_length=1, max_length=200)
    value: Any
    unit: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    provider: str | None = Field(default=None, max_length=120)
    plan_key: str | None = Field(default=None, max_length=200)
    status: FactStatus = FactStatus.EXTRACTED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: FactSource
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("fact key cannot be blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def validate_effective_window(self) -> "Fact":
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be earlier than effective_from")
        return self


class ConsentRecord(StrictModel):
    consent_id: UUID = Field(default_factory=uuid4)
    purpose: str = Field(min_length=1, max_length=120)
    source_domain: str = Field(default="health", max_length=80)
    destination_domain: str = Field(default="insurance", max_length=80)
    allowed_fields: list[str] = Field(default_factory=list)
    status: ConsentStatus = ConsentStatus.GRANTED
    granted_at: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("allowed_fields")
    @classmethod
    def normalize_allowed_fields(cls, values: list[str]) -> list[str]:
        # Preserve order for audit readability while removing duplicates.
        seen: set[str] = set()
        result: list[str] = []
        for raw in values:
            value = raw.strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @model_validator(mode="after")
    def validate_revocation(self) -> "ConsentRecord":
        if self.status == ConsentStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked_at is required for revoked consent")
        return self


class AshlarCase(StrictModel):
    case_id: UUID = Field(default_factory=uuid4)
    status: CaseStatus = CaseStatus.DISCOVERY
    client: CaseClient = Field(default_factory=CaseClient)
    applicant: Applicant | None = None

    # Deterministic structured state shared by HAL + Proposal Studio.
    needs_profile: dict[str, Any] = Field(default_factory=dict)
    existing_policy: dict[str, Any] | None = None
    selected_plan_keys: list[str] = Field(default_factory=list)
    # Stage 13: the single plan explicitly chosen by the client/broker after
    # comparison. This is deliberately separate from the comparison shortlist.
    selected_plan_key: str | None = Field(default=None, max_length=200)

    documents: list[CaseDocument] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    consents: list[ConsentRecord] = Field(default_factory=list)

    # Deliberately flexible at Phase 1. Each becomes a strict domain model when
    # that workflow is integrated in later phases.
    recommendation: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    application: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    preauthorisations: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    renewal: dict[str, Any] | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def touch(self) -> None:
        self.updated_at = utcnow()
