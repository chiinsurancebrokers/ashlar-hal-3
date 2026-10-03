from __future__ import annotations

from typing import Any


MATERNITY_MIN_AGE = 18
MATERNITY_MAX_AGE = 47


def normalise_sex(value: Any) -> str | None:
    """Normalise only an explicitly supplied applicant sex value.

    Never infer sex from a name, nationality, language, or other proxy.
    """
    text = str(value or "").strip().lower()
    female = {"female", "f", "woman", "γυναίκα", "γυναικα", "θηλυκό", "θηλυκο"}
    male = {"male", "m", "man", "άνδρας", "ανδρας", "αρσενικό", "αρσενικο"}
    if text in female:
        return "female"
    if text in male:
        return "male"
    if text in {"prefer_not_to_say", "prefer not to say", "skip", "other", "άλλο", "αλλο"}:
        return "unspecified"
    return None


def maternity_question_relevant(state: dict[str, Any]) -> bool:
    """True only when maternity discovery is relevant by explicit sex + age.

    This controls whether HAL asks the maternity preference question; it does
    not decide insurer eligibility, underwriting, or whether a plan covers
    maternity. Those remain authoritative deterministic/evidence decisions.
    """
    try:
        age = int(state.get("age"))
    except (TypeError, ValueError):
        return False
    return (
        normalise_sex(state.get("sex")) == "female"
        and MATERNITY_MIN_AGE <= age <= MATERNITY_MAX_AGE
    )
