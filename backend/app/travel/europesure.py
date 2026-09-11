from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parents[3] / "data" / "travel" / "europesure" / "plans.json"

USA_TERMS = ("usa", "u.s.", "united states", "america", "ηνωμένες πολιτείες", "ηνωμενες πολιτειες")
EUROPE_TERMS = (
    "europe", "eu ", "europa", "ευρώπη", "ευρωπη", "european union",
    "greece", "greek", "italy", "italian", "france", "french", "spain", "spanish",
    "germany", "german", "portugal", "netherlands", "belgium", "austria",
    "switzerland", "cyprus", "malta", "croatia",
)
WORLDWIDE_TERMS = ("worldwide", "world wide", "global", "παγκόσμια", "παγκοσμια")

# Cues that this "trip" may actually be a relocation, not travel — in which
# case travel insurance is very likely the wrong product. This never blocks
# the applicant; it only ever adds one honest note, once.
RELOCATION_TERMS = (
    "moving to", "relocating", "relocate", "permanently", "long-term stay",
    "μετακομίζω", "μετακομιζω", "μόνιμα", "μονιμα",
)


@lru_cache
def europesure_data() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def money(value: int | float) -> str:
    return f"€{value:,.0f}"


def destination_scope(destination: str | None) -> str | None:
    text = (destination or "").strip().lower()
    if not text:
        return None
    if any(x in text for x in USA_TERMS):
        return "usa"
    if any(x in text for x in EUROPE_TERMS):
        return "europe"
    if any(x in text for x in WORLDWIDE_TERMS):
        return "worldwide"
    return "worldwide"


def looks_like_long_stay(text: str) -> bool:
    """Detects relocation language OR an explicit duration over ~180 days.
    Deliberately conservative: only fires on clear signals, never guesses."""
    low = (text or "").lower()
    if any(term in low for term in RELOCATION_TERMS):
        return True
    import re
    m = re.search(r"(\d{1,3})\s*(day|days|μέρες|μερες)", low)
    if m and int(m.group(1)) > 180:
        return True
    m = re.search(r"(\d{1,2})\s*(month|months|μήνες|μηνες)", low)
    if m and int(m.group(1)) > 6:
        return True
    m = re.search(r"\b(1|one|a)\s*year\b", low)
    if m:
        return True
    return False


def recommend_tier(state: dict) -> dict[str, Any]:
    """Conservative deterministic tier recommendation from the legacy
    Europesure positioning. Mirrors the health engine's philosophy: the
    tier CHOICE is deterministic; nothing here is ever an LLM guess."""
    data = europesure_data()
    plans = data["plans"]
    age = state.get("travel_age") or state.get("age")
    scope = state.get("travel_destination_scope") or destination_scope(state.get("travel_destination"))
    preference = str(state.get("travel_cover_preference") or "").lower()
    explicit = str(state.get("travel_tier_preference") or "").lower()

    eligible = True
    eligibility_note = None
    if age is not None:
        try:
            if int(age) > int(data["dataset"]["max_age_legacy"]):
                eligible = False
                eligibility_note = (
                    f"The legacy Europesure data states a maximum age of {data['dataset']['max_age_legacy']}. "
                    "Current eligibility must be confirmed in the Europesure portal before proceeding."
                )
        except Exception:
            pass

    if explicit in plans:
        tier = explicit
        reason = "You explicitly asked to look at this Europesure tier."
    elif preference in {"highest", "maximum", "premium", "strongest"}:
        tier = "platinum"
        reason = "You prioritised the strongest legacy limits."
    elif preference in {"balanced", "balance", "value"}:
        tier = "gold"
        reason = "You prioritised a balanced level of cover, matching the legacy positioning of Gold."
    elif preference in {"budget", "basic", "price", "economy"} and scope == "europe":
        tier = "silver"
        reason = "The legacy source positions Silver as the entry-level option for short European trips and budget-conscious travellers."
    elif scope in {"worldwide", "usa"}:
        tier = "platinum"
        reason = "The legacy source positions Platinum as the premium option for worldwide travel."
    else:
        tier = "gold"
        reason = "The legacy source positions Gold as the balanced, most-popular option."

    plan = dict(plans[tier])
    return {
        "provider": "Europesure", "tier": tier, "plan_name": f"Europesure {plan['name']}",
        "recommended": eligible, "eligible_on_legacy_data": eligible, "eligibility_note": eligibility_note,
        "reason": reason,
        "trip_type": state.get("travel_trip_type"), "destination": state.get("travel_destination"),
        "destination_scope": scope,
        "emergency_medical_eur": plan["emergency_medical_eur"], "cancellation_eur": plan["cancellation_eur"],
        "baggage_eur": plan["baggage_eur"], "positioning": plan["positioning"], "legacy_fit": plan["legacy_fit"],
        "common_benefits_legacy": data["dataset"]["common_benefits_legacy"],
        "optional_addons_legacy": data["dataset"]["optional_addons_legacy"],
        "portal_url": data["dataset"]["portal_url"],
        "verification_status": data["dataset"]["verification_status"], "current_terms_confirmed": False,
        "client_note": data["dataset"]["client_use"],
        "alternatives": [
            {"tier": k, "name": v["name"], "emergency_medical_eur": v["emergency_medical_eur"],
             "cancellation_eur": v["cancellation_eur"], "baggage_eur": v["baggage_eur"]}
            for k, v in plans.items()
        ],
    }


def public_catalog() -> dict[str, Any]:
    data = europesure_data()
    return {
        "provider": data["dataset"]["provider"], "verification_status": data["dataset"]["verification_status"],
        "current_terms_confirmed": False, "max_age_legacy": data["dataset"]["max_age_legacy"],
        "annual_multi_trip_from_eur_legacy": data["dataset"]["annual_multi_trip_from_eur_legacy"],
        "trip_types": data["dataset"]["trip_types"],
        "common_benefits_legacy": data["dataset"]["common_benefits_legacy"],
        "optional_addons_legacy": data["dataset"]["optional_addons_legacy"],
        "plans": [
            {"tier": key, "name": value["name"], "emergency_medical": money(value["emergency_medical_eur"]),
             "cancellation": money(value["cancellation_eur"]), "baggage": money(value["baggage_eur"]),
             "positioning": value["positioning"], "legacy_fit": value["legacy_fit"]}
            for key, value in data["plans"].items()
        ],
        "portal_url": data["dataset"]["portal_url"],
        "client_note": data["dataset"]["client_use"],
    }
