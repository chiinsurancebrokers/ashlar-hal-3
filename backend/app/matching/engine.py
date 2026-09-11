from __future__ import annotations
from dataclasses import dataclass

from backend.app.schemas.applicant import Applicant
from backend.app.evidence.morgan_price_2026 import covered

# Applicant boolean field -> (client-facing label, Table-of-Benefits check)
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


def benefit_checklist(carrier: str, product_code: str) -> list[dict]:
    """A fixed, always-the-same-order checklist for every quote card — the
    fast-scan pattern (green check / grey dash / '?'), but never a guess:
    if we hold no TOB evidence for this carrier, every item is explicitly
    'not confirmed' rather than a fabricated tick or cross."""
    has_evidence = carrier == "morgan_price"
    items = []
    for field in CHECKLIST_ORDER:
        label, check = REQUIREMENT_CHECKS[field]
        covered_status = bool(check(product_code)) if has_evidence else None
        items.append({"field": field, "label": label, "covered": covered_status})
    return items


@dataclass(frozen=True)
class RequirementResult:
    label: str
    required: bool
    met: bool
    evidence_confidence: float  # 1.0 = verified against loaded Table of Benefits; <1.0 = not yet verifiable


@dataclass(frozen=True)
class MatchOutcome:
    """The single source of truth for whether a plan may appear in the
    shortlist at all. `eligible` is a HARD boolean, never a score."""
    eligible: bool
    requirements_score: float | None   # fraction of MUST-HAVEs met, for ranking only among eligible plans
    evidence_confidence: float
    matched: list[str]
    unmatched: list[str]


def score_requirements(results: list[RequirementResult]) -> tuple[float, float]:
    """Pure function: given per-requirement results, return
    (requirements_score, overall_evidence_confidence).

    A single unmet MUST-HAVE zeroes the score outright — this is the
    behaviour the v8 audit called for explicitly (routine maternity example):
    a plan that fails one mandatory requirement must never look like a
    partial match, it must look like a rejection.
    """
    if not results:
        return 1.0, 1.0
    if any((not r.met) for r in results):
        confidence = min(r.evidence_confidence for r in results)
        return 0.0, confidence
    confidence = min(r.evidence_confidence for r in results)
    return 1.0, confidence


def evaluate_requirements(applicant: Applicant, carrier: str, product_code: str) -> MatchOutcome:
    selected: list[tuple[str, str]] = []
    for field, (label, _check) in REQUIREMENT_CHECKS.items():
        if getattr(applicant, field):
            selected.append((field, label))

    if not selected:
        # No must-haves selected at all: every plan is "eligible" on
        # requirements grounds (price/other criteria decide ranking).
        return MatchOutcome(eligible=True, requirements_score=None, evidence_confidence=1.0, matched=[], unmatched=[])

    if carrier != "morgan_price":
        # We do not yet hold verified benefit-level evidence for other
        # carriers, so we can never HARD-exclude them on a must-have — that
        # would be excluding a plan based on data we don't actually have.
        # Instead they are marked low-confidence and ranked below verified
        # matches, never silently promoted above them.
        return MatchOutcome(eligible=True, requirements_score=None, evidence_confidence=0.0, matched=[], unmatched=[])

    results: list[RequirementResult] = []
    for field, label in selected:
        _label, check = REQUIREMENT_CHECKS[field]
        results.append(RequirementResult(label=label, required=True, met=bool(check(product_code)), evidence_confidence=1.0))

    score, confidence = score_requirements(results)
    matched = [r.label for r in results if r.met]
    unmatched = [r.label for r in results if not r.met]

    # THE hard rule: a verified failed must-have removes the plan from
    # eligibility outright. Confidence==1.0 means we are certain about this
    # verdict (it comes from the loaded, verified Table of Benefits).
    eligible = not (confidence == 1.0 and score == 0.0)

    return MatchOutcome(
        eligible=eligible,
        requirements_score=score,
        evidence_confidence=confidence,
        matched=matched,
        unmatched=unmatched,
    )
