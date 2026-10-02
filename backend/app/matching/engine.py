from __future__ import annotations
from dataclasses import dataclass

from backend.app.schemas.applicant import Applicant
from backend.app.evidence.morgan_price_2026 import covered
from backend.app.evidence.plan_capabilities import plan_capability

# Applicant boolean field -> (client-facing label, Morgan Price Table-of-Benefits check)
REQUIREMENT_CHECKS = {
    "outpatient_required": ("Out-patient cover", lambda code: code in {"standard_plus", "comprehensive", "premium", "elite"}),
    "maternity_required": ("Routine maternity", lambda code: covered(code, "normal_maternity")),
    "dental_required": ("Routine dental", lambda code: covered(code, "routine_dental")),
    "mental_health_required": ("Mental health", lambda code: covered(code, "outpatient_psychiatric") and covered(code, "inpatient_psychiatric")),
    "wellness_required": ("Wellness screening", lambda code: covered(code, "wellness_screening")),
    "optical_required": ("Optical benefits", lambda code: covered(code, "optical_eye_test")),
    "evacuation_required": ("Medical evacuation", lambda code: covered(code, "medical_evacuation_transport")),
    "chronic_required": ("Chronic condition cover", lambda code: covered(code, "inpatient_chronic_conditions")),
}

CHECKLIST_ORDER = [
    "outpatient_required", "maternity_required", "dental_required", "mental_health_required",
    "wellness_required", "optical_required", "evacuation_required", "chronic_required",
]


def _verified_capability(carrier: str, product_code: str, field: str) -> bool | None:
    """Return a hard benefit verdict only when HAL has explicit evidence.

    Morgan Price uses its loaded Table of Benefits. Other carriers use the
    carrier-neutral capability registry. Unknown remains None — never guess.
    """
    if carrier == "morgan_price":
        _label, check = REQUIREMENT_CHECKS[field]
        return bool(check(product_code))
    return plan_capability(carrier, product_code, field)


def benefit_checklist(carrier: str, product_code: str) -> list[dict]:
    """Fixed-order checklist for every quote card.

    True/False means HAL has explicit evidence. None means not confirmed.
    This allows known carrier facts (for example an inpatient-only tier) to
    be shown honestly without pretending the rest of that carrier's benefits
    are fully verified.
    """
    items = []
    for field in CHECKLIST_ORDER:
        label, _check = REQUIREMENT_CHECKS[field]
        items.append({
            "field": field,
            "label": label,
            "covered": _verified_capability(carrier, product_code, field),
        })
    return items


@dataclass(frozen=True)
class RequirementResult:
    label: str
    required: bool
    met: bool
    evidence_confidence: float


@dataclass(frozen=True)
class MatchOutcome:
    """Single source of truth for whether a plan may appear in the shortlist."""
    eligible: bool
    requirements_score: float | None
    evidence_confidence: float
    matched: list[str]
    unmatched: list[str]


def score_requirements(results: list[RequirementResult]) -> tuple[float, float]:
    if not results:
        return 1.0, 1.0
    if any(not r.met for r in results):
        return 0.0, min(r.evidence_confidence for r in results)
    return 1.0, min(r.evidence_confidence for r in results)


def evaluate_requirements(applicant: Applicant, carrier: str, product_code: str) -> MatchOutcome:
    selected: list[tuple[str, str]] = []
    for field, (label, _check) in REQUIREMENT_CHECKS.items():
        if getattr(applicant, field):
            selected.append((field, label))

    if not selected:
        return MatchOutcome(
            eligible=True, requirements_score=None, evidence_confidence=1.0,
            matched=[], unmatched=[],
        )

    known: list[RequirementResult] = []
    unknown_labels: list[str] = []

    for field, label in selected:
        verdict = _verified_capability(carrier, product_code, field)
        if verdict is None:
            unknown_labels.append(label)
        else:
            known.append(RequirementResult(
                label=label, required=True, met=verdict, evidence_confidence=1.0
            ))

    matched = [r.label for r in known if r.met]
    unmatched = [r.label for r in known if not r.met]

    # HARD RULE: one explicitly verified failed must-have removes the plan.
    if unmatched:
        return MatchOutcome(
            eligible=False,
            requirements_score=0.0,
            evidence_confidence=1.0,
            matched=matched,
            unmatched=unmatched,
        )

    # All requested requirements are explicitly verified as present.
    if not unknown_labels:
        return MatchOutcome(
            eligible=True,
            requirements_score=1.0,
            evidence_confidence=1.0,
            matched=matched,
            unmatched=[],
        )

    # Some requirements are genuinely unknown. Keep the plan as an
    # unverified alternative, rank it below fully verified matches, and never
    # claim that the unknown requirement is covered.
    return MatchOutcome(
        eligible=True,
        requirements_score=None,
        evidence_confidence=0.0,
        matched=matched,
        unmatched=[],
    )
