from __future__ import annotations

from typing import Any

MATERNITY_MIN_AGE = 18
MATERNITY_MAX_AGE = 47


def normalise_sex(value: Any) -> str | None:
    """Normalise only an explicitly supplied applicant sex value; never infer from proxies."""
    text = str(value or "").strip().lower()
    if text in {"female", "f", "woman", "γυναίκα", "γυναικα", "θηλυκό", "θηλυκο"}:
        return "female"
    if text in {"male", "m", "man", "άνδρας", "ανδρας", "αρσενικό", "αρσενικο"}:
        return "male"
    if text in {"prefer_not_to_say", "prefer not to say", "skip", "other", "άλλο", "αλλο"}:
        return "unspecified"
    return None


def maternity_question_relevant(state: dict[str, Any]) -> bool:
    """Ask maternity preference only for explicitly female applicants aged 18–47."""
    try:
        age = int(state.get("age"))
    except (TypeError, ValueError):
        return False
    return normalise_sex(state.get("sex")) == "female" and MATERNITY_MIN_AGE <= age <= MATERNITY_MAX_AGE
