from __future__ import annotations
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.app.schemas.applicant import Applicant

RULES_FILE = Path(__file__).resolve().parents[3] / "data" / "evidence" / "eligibility_rules.json"


@dataclass(frozen=True)
class EligibilityDecision:
    status: str  # eligible | ineligible | unknown
    profile: str | None
    reason: str


@lru_cache
def load_eligibility_rules() -> dict:
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


def _condition_value(applicant: Applicant, condition: dict) -> bool | None:
    field = condition.get("field")
    value = getattr(applicant, field, None)
    if "different_from_field" in condition:
        other = getattr(applicant, condition["different_from_field"], None)
        if not value or not other:
            return None
        return str(value).strip().casefold() != str(other).strip().casefold()
    if "equals" in condition:
        if not value:
            return None
        return str(value).strip().casefold() == str(condition["equals"]).strip().casefold()
    return None


def evaluate_profile(applicant: Applicant, profile_name: str) -> EligibilityDecision:
    profile = load_eligibility_rules().get("profiles", {}).get(profile_name)
    if not profile:
        return EligibilityDecision("unknown", profile_name, "Eligibility profile not configured.")

    results = [_condition_value(applicant, c) for c in profile.get("conditions", [])]
    if not results:
        return EligibilityDecision("unknown", profile_name, "Eligibility profile has no conditions.")

    operator = profile.get("operator", "all")
    if operator == "any":
        if any(v is True for v in results):
            return EligibilityDecision("eligible", profile_name, profile.get("description", "Eligible."))
        if all(v is False for v in results):
            return EligibilityDecision("ineligible", profile_name, profile.get("description", "Not eligible."))
        return EligibilityDecision("unknown", profile_name, "More eligibility information is required.")

    if any(v is False for v in results):
        return EligibilityDecision("ineligible", profile_name, profile.get("description", "Not eligible."))
    if all(v is True for v in results):
        return EligibilityDecision("eligible", profile_name, profile.get("description", "Eligible."))
    return EligibilityDecision("unknown", profile_name, "More eligibility information is required.")


def evaluate_plan_eligibility(applicant: Applicant, carrier: str, product_code: str) -> EligibilityDecision:
    """Apply only explicitly activated product mappings.

    future_examples are documentation, not active business rules. This
    prevents an example rule from silently excluding current catalogue plans.
    """
    key = f"{carrier}:{product_code}"
    profile_name = load_eligibility_rules().get("plan_profiles", {}).get(key)
    if not profile_name:
        return EligibilityDecision("eligible", None, "No additional product-specific eligibility rule is active.")
    return evaluate_profile(applicant, profile_name)
