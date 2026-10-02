from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

from backend.app.core.config import Settings
from backend.app.evidence.eligibility_rules import load_eligibility_rules
from backend.app.rates.registry import load_rates


class ArchitectureFinding(BaseModel):
    severity: Literal["info", "warn", "block"]
    control: str
    message: str


class ArchitectureAudit(BaseModel):
    verdict: Literal["PASS", "WARN", "BLOCK"]
    findings: list[ArchitectureFinding] = Field(default_factory=list)


def audit_architecture(settings: Settings) -> ArchitectureAudit:
    """Runtime guardrail audit. It observes configuration; it never mutates it."""
    findings: list[ArchitectureFinding] = []
    rates = load_rates()
    if not rates:
        findings.append(ArchitectureFinding(severity="block", control="rate_registry", message="No rate records are loaded."))
    elif any(float(r.annual_premium) <= 0 for r in rates):
        findings.append(ArchitectureFinding(severity="block", control="rate_registry", message="A non-positive premium exists in the deterministic rate registry."))
    else:
        findings.append(ArchitectureFinding(severity="info", control="rate_registry", message=f"{len(rates)} deterministic rate records loaded."))

    rules = load_eligibility_rules()
    if not isinstance(rules.get("plan_profiles", {}), dict):
        findings.append(ArchitectureFinding(severity="block", control="eligibility_rules", message="Eligibility plan_profiles is invalid."))
    else:
        findings.append(ArchitectureFinding(severity="info", control="eligibility_rules", message="Eligibility mappings are deterministic JSON rules."))

    if settings.deductible_model_enabled:
        findings.append(ArchitectureFinding(severity="warn", control="deductible_model", message="Illustrative deductible pricing model is enabled; confirm carrier approval before relying on it."))
    else:
        findings.append(ArchitectureFinding(severity="info", control="deductible_model", message="Unconfirmed deductible pricing adjustments remain disabled."))

    if not settings.openai_verifier_enabled:
        findings.append(ArchitectureFinding(severity="warn", control="verifier", message="Second-pass OpenAI verifier is disabled; deterministic checks still apply."))

    if any(f.severity == "block" for f in findings):
        verdict = "BLOCK"
    elif any(f.severity == "warn" for f in findings):
        verdict = "WARN"
    else:
        verdict = "PASS"
    return ArchitectureAudit(verdict=verdict, findings=findings)
