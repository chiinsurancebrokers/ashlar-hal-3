from enum import Enum
from pydantic import BaseModel


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class EvidenceClaim(BaseModel):
    claim: str
    status: EvidenceStatus
    allow_generation: bool = False


def generation_allowed(claim: EvidenceClaim) -> bool:
    return claim.status == EvidenceStatus.VERIFIED and claim.allow_generation


def safe_claim_text(claim: EvidenceClaim) -> str:
    if generation_allowed(claim):
        return claim.claim
    return "I cannot confirm this point from the available verified policy evidence."
