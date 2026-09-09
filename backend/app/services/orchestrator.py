from __future__ import annotations
import re
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist, quote_exclusions
from backend.app.discovery.flow import apply_discovery_answer, next_discovery_question, discovery_progress
from backend.app.services.journey import classify_journey
from backend.app.services.adviser import intake_analysis, build_local_review_instructions
from backend.app.services.openai_client import adviser_response
from backend.app.knowledge.service import detect_hnwi

APPLICANT_STATE_KEYS = {
    "age", "residence_country", "nationality", "coverage_area", "currency", "deductible",
    "deductible_preference", "budget_annual", "client_segment", "chronic_conditions_note",
    "outpatient_required", "maternity_required", "dental_required", "mental_health_required",
    "wellness_required", "optical_required", "evacuation_required", "chronic_required",
    "chronic_conditions_disclosed", "private_hospital_choice_required", "cross_border_treatment_required",
    "home_country_treatment_required", "continuity_portability_required", "high_annual_limit_required",
    "private_room_required", "direct_billing_required", "second_medical_opinion_required",
}


def _is_greek(text: str) -> bool:
    return bool(re.search(r"[\u0370-\u03ff]", text or ""))


def _applicant_from_state(state: dict) -> Applicant | None:
    if not state.get("age") or not state.get("coverage_area"):
        return None
    fields = {k: v for k, v in state.items() if k in APPLICANT_STATE_KEYS}
    try:
        return Applicant(**fields)
    except Exception:
        return None


def _merge(state: dict, updates: dict) -> dict:
    merged = dict(state)
    merged.update({k: v for k, v in (updates or {}).items() if v is not None})
    return merged


def _quote_payload(state: dict, settings: Settings) -> list[dict]:
    applicant = _applicant_from_state(state)
    if not applicant:
        return []
    return [q.model_dump(mode="json") for q in quote_shortlist(applicant, settings)]


def _exclusions_payload(state: dict, settings: Settings) -> list[dict]:
    applicant = _applicant_from_state(state)
    if not applicant:
        return []
    return quote_exclusions(applicant, settings)


async def chat_turn(message: str, state: dict, history: list[dict] | None = None) -> dict[str, Any]:
    settings = get_settings()
    greek = _is_greek(message)

    previous_journey = str((state or {}).get("journey") or "undetermined")
    provisional = classify_journey(message, state)
    valid = {"travel", "ipmi", "local_review"}
    if previous_journey in valid and provisional in valid and provisional != previous_journey:
        # Product switch: fully isolate state — no cross-journey leakage.
        state = {"journey": provisional, "currency": (state or {}).get("currency", "EUR")}
        history = []

    if provisional == "travel":
        return {
            "reply": ("Αυτό ακούγεται σαν ταξιδιωτική ασφάλιση. Αυτό το κομμάτι είναι υπό κατασκευή αυτή τη στιγμή — "
                      "μπορώ να καταγράψω το αίτημά σας για έναν broker να επικοινωνήσει μαζί σας."
                      if greek else
                      "That sounds like travel insurance. This part of HAL is still being built — "
                      "I can log your request for a broker to follow up directly."),
            "state": {**state, "journey": "travel"}, "quotes": [], "excluded_plans": [],
            "ai_status": "travel_not_yet_implemented", "journey": "travel",
            "lead_cta": {"show": True, "journey": "travel", "label": "Request a travel insurance callback"},
            "open_application_form": False, "quick_replies": [],
        }

    state = _merge(state, apply_discovery_answer(message, state))

    if detect_hnwi(message) and not state.get("client_segment"):
        state["client_segment"] = "hnwi"

    openai_ack = ""
    provisional = classify_journey(message, state)
    if settings.openai_api_key and provisional not in {"travel", "local_review"} and not state.get("discovery_complete"):
        intake = await intake_analysis(message, state, history, greek)
        state = _merge(state, intake.get("applicant_updates", {}))
        openai_ack = intake.get("acknowledgement", "")

    journey = classify_journey(message, state)
    state["journey"] = journey

    if journey == "local_review":
        try:
            reply = await adviser_response(instructions=build_local_review_instructions(greek), message=message, history=history, max_output_tokens=300)
        except Exception:
            reply = ("Ένα local πρόγραμμα μπορεί να ταιριάζει αν θέλετε κάλυψη κυρίως στην Ελλάδα με χαμηλότερο κόστος. "
                      "Αν όμως θέλετε ευρύτερη επιλογή νοσοκομείων, υψηλότερα όρια ή θεραπεία στο εξωτερικό, ένα διεθνές πρόγραμμα ταιριάζει καλύτερα. "
                      "Τι είναι πιο σημαντικό για εσάς: το κόστος ή η ευρύτερη κάλυψη;"
                      if greek else
                      "A local plan can be a good fit if you mainly want Greece-only cover at a lower cost. "
                      "But if broader hospital choice, higher limits or treatment abroad matter to you, an international plan usually fits better. "
                      "What matters most to you: cost or broader coverage?")
        return {
            "reply": reply, "state": state, "quotes": [], "excluded_plans": [],
            "ai_status": "local_review_playbook", "journey": journey,
            "lead_cta": {"show": True, "journey": "local_review", "label": "Request a local-vs-international review"},
            "open_application_form": False, "quick_replies": [],
        }

    next_q = next_discovery_question(state, greek)
    if next_q is not None:
        state["pending_question"] = next_q["key"]
        state["discovery_complete"] = False
        reply = ((openai_ack.rstrip() + " " + next_q["reply"]) if openai_ack else next_q["reply"]).strip()
        return {
            "reply": reply, "state": state, "quotes": [], "excluded_plans": [],
            "ai_status": "guided_discovery", "journey": journey if journey != "undetermined" else "ipmi",
            "lead_cta": {"show": False, "journey": "ipmi", "label": "Request a proposal"},
            "open_application_form": False, "quick_replies": next_q["quick_replies"],
            "discovery": discovery_progress(state),
        }

    state["pending_question"] = None
    state["discovery_complete"] = True
    quotes = _quote_payload(state, settings)
    excluded = _exclusions_payload(state, settings)
    label = "Request a private consultation" if state.get("client_segment") == "hnwi" else "Request a proposal"
    reply = ("Τέλεια — τώρα έχω αρκετά στοιχεία. Παρακάτω είναι το shortlist του HAL."
              if greek else "Great — I now have enough information. Here is HAL's shortlist.")
    return {
        "reply": reply, "state": state, "quotes": quotes, "excluded_plans": excluded,
        "ai_status": "deterministic_shortlist", "journey": journey if journey != "undetermined" else "ipmi",
        "lead_cta": {"show": True, "journey": "ipmi", "label": label},
        "open_application_form": False, "quick_replies": [],
        "discovery": discovery_progress(state),
    }
