from __future__ import annotations
import re
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_shortlist, quote_exclusions
from backend.app.discovery.flow import apply_discovery_answer, next_discovery_question, discovery_progress
from backend.app.services.journey import classify_journey
from backend.app.services.adviser import intake_analysis, build_local_review_instructions, explain_plan
from backend.app.services.anthropic_client import claude_response as adviser_response
from backend.app.services.verifier_agent import verify_shortlist
from backend.app.knowledge.service import detect_hnwi, greece_profile
from backend.app.travel.discovery import deterministic_travel_updates, next_travel_question
from backend.app.travel.europesure import recommend_tier, public_catalog

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


def _has_latin_words(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", text or ""))


LANGUAGE_NEUTRAL_UI_VALUES = {
    "skip", "same as residence",
    "europe only", "worldwide excluding usa", "worldwide including usa",
    "€0 deductible", "€500 deductible", "€1000 deductible",
    "hospital only", "include outpatient cover",
    "yes", "no", "yes, maternity is required", "no maternity needed",
    "yes, dental is important", "no dental needed",
    "yes, mental health is important", "no mental health cover needed",
    "yes, wellness is important", "no wellness cover needed",
    "yes, optical is important", "no optical cover needed",
    "yes, evacuation is important", "no evacuation priority",
    "no fixed budget", "budget €3000", "budget €5000",
}


def _resolve_language(message: str, state: dict) -> bool:
    """Returns True if the conversation should continue in Greek.

    Machine values behind localized quick-reply buttons stay in English so
    deterministic parsers remain stable. Those values are language-neutral
    and must never be interpreted as the applicant switching languages.
    """
    raw = (message or "").strip()
    low = raw.lower()
    if _is_greek(raw):
        state["language"] = "el"
    elif low in LANGUAGE_NEUTRAL_UI_VALUES:
        pass
    elif _has_latin_words(raw):
        state["language"] = "en"
    return state.get("language") == "el"



def _quote_objects(state: dict, settings: Settings):
    applicant = _applicant_from_state(state)
    if not applicant:
        return []
    return quote_shortlist(applicant, settings)


def _post_shortlist_intent(message: str) -> str | None:
    low = (message or "").strip().lower()
    if any(x in low for x in [
        "public healthcare", "public health system", "greece healthcare", "greek healthcare",
        "δημόσιο σύστημα", "δημοσιο συστημα", "δημόσια υγεία", "δημοσια υγεια",
        "σύστημα υγείας", "συστημα υγειας",
    ]):
        return "greece_healthcare"
    if any(x in low for x in [
        "tell me more", "more detail", "more about", "explain the plan", "explain this plan",
        "details about", "walk me through", "πες μου περισσότερα", "πείτε μου περισσότερα",
        "πιο αναλυτικά", "πιο αναλυτικα", "εξήγησέ", "εξηγησε", "ανάλυσέ", "αναλυσε",
    ]) or low in {"yes", "yes please", "sure", "ναι", "ναι παρακαλώ", "ναι παρακαλω"}:
        return "explain_plan"
    return None


def _pick_quote_from_message(message: str, quotes):
    low = (message or "").lower()
    for q in quotes:
        names = [q.product_name or "", q.insurer or ""]
        if any(name and name.lower() in low for name in names):
            return q
    return quotes[0] if quotes else None


def _greece_healthcare_summary(greek: bool) -> str:
    profile = greece_profile()
    by_id = {x["id"]: x for x in profile.get("indicators", [])}
    satisfaction = by_id.get("satisfaction", {})
    unmet = by_id.get("unmet_needs_oecd", {})
    oop = by_id.get("out_of_pocket_share", {})
    if greek:
        return (
            "Με βάση τα στοιχεία που έχει φορτωμένα ο HAL από το OECD Health at a Glance 2025 για την Ελλάδα, "
            f"{satisfaction.get('value', 'η ικανοποίηση από τη διαθεσιμότητα ποιοτικής φροντίδας είναι χαμηλή σε σύγκριση με τον OECD')}. "
            f"Επίσης, {unmet.get('value', 'καταγράφονται σημαντικές ανεκπλήρωτες ανάγκες υγείας λόγω κόστους, απόστασης ή αναμονής')}, "
            f"ενώ {oop.get('value', 'σημαντικό μέρος της δαπάνης υγείας καλύπτεται απευθείας από τα νοικοκυριά')}. "
            "Αυτό δεν σημαίνει ότι το δημόσιο σύστημα είναι ανεπαρκές για όλους· βοηθά όμως να εξηγήσουμε γιατί κάποιος μπορεί να θέλει ιδιωτική ή διεθνή κάλυψη για μεγαλύτερη προβλεψιμότητα και επιλογές."
        )
    return (
        "Based on HAL's loaded OECD Health at a Glance 2025 evidence for Greece, "
        f"{satisfaction.get('value', 'reported satisfaction with the availability of quality care is low versus the OECD average')}. "
        f"Also, {unmet.get('value', 'there are material unmet healthcare needs due to cost, distance or waiting times')}, "
        f"while {oop.get('value', 'households fund a significant share of healthcare directly out of pocket')}. "
        "That does not mean Greece's public system is unsuitable for everyone; it helps explain why some people value private or international cover for added predictability and choice."
    )

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


def _shortlist_reasoning(quotes: list[dict], excluded: list[dict], greek: bool) -> str:
    """Pure, deterministic explanation of the shortlist — built entirely
    from data the matching engine already computed, never from the LLM.
    This is the 'why these plans' the applicant should always see, not just
    find buried inside a card."""
    if not quotes:
        return ""
    top = quotes[0]
    matched = top.get("matched_requirements") or []
    price = f'{top.get("currency", "EUR")} {top.get("premium", 0):,.2f}'

    if greek:
        if matched:
            why = f"γιατί είναι η φθηνότερη επιλογή που καλύπτει επαληθευμένα: {', '.join(matched)}"
        elif (top.get("evidence_confidence") if top.get("evidence_confidence") is not None else 1.0) < 1.0:
            why = "γιατί είναι η πιο οικονομική επιλογή· δεν έχουμε ακόμα λεπτομερή στοιχεία παροχών για αυτόν τον ασφαλιστή ώστε να επιβεβαιώσουμε ότι καλύπτει όσα ζητήσατε"
        else:
            why = "γιατί είναι η πιο οικονομική επιλογή από τις επιλέξιμες"
        line = f"Η κορυφαία επιλογή είναι {top.get('product_name')} ({top.get('insurer')}) στα {price}/έτος — {why}."
        if excluded:
            names = ", ".join(e.get("product_name", "") for e in excluded[:3])
            line += f" {len(excluded)} πρόγραμμα{'τα' if len(excluded) != 1 else ''} αποκλείστηκαν επειδή δεν καλύπτουν κάποια από τις απαιτήσεις σας ({names})."
    else:
        if matched:
            why = f"it's the lowest-priced option that verifiably covers: {', '.join(matched)}"
        elif (top.get("evidence_confidence") if top.get("evidence_confidence") is not None else 1.0) < 1.0:
            why = "it's the lowest-priced option, though we don't yet hold detailed benefit data for this carrier to confirm it covers everything you asked for"
        else:
            why = "it's the lowest-priced eligible option"
        line = f"HAL's top pick is {top.get('product_name')} ({top.get('insurer')}) at {price}/year — {why}."
        if excluded:
            names = ", ".join(e.get("product_name", "") for e in excluded[:3])
            line += f" {len(excluded)} plan{'s' if len(excluded) != 1 else ''} were excluded because they don't cover something you asked for ({names})."
    return line


async def chat_turn(message: str, state: dict, history: list[dict] | None = None) -> dict[str, Any]:
    settings = get_settings()
    greek = _resolve_language(message, state)

    previous_journey = str((state or {}).get("journey") or "undetermined")
    provisional = classify_journey(message, state)
    valid = {"travel", "ipmi", "local_review"}
    if previous_journey in valid and provisional in valid and provisional != previous_journey:
        # Product switch: fully isolate state — no cross-journey leakage.
        state = {"journey": provisional, "currency": (state or {}).get("currency", "EUR")}
        history = []

    if provisional == "travel":
        state = {**state, "journey": "travel"}
        state = _merge(state, deterministic_travel_updates(message, state))

        long_stay_prefix = ""
        if state.get("travel_long_stay_flag") and not state.get("travel_long_stay_warning_shown"):
            state["travel_long_stay_warning_shown"] = True
            long_stay_prefix = (
                "Αυτό ακούγεται περισσότερο σαν μετεγκατάσταση παρά ταξίδι — αν θα μείνετε μόνιμα ή για μεγάλο διάστημα, "
                "η διεθνής ασφάλιση υγείας (IPMI) συνήθως ταιριάζει καλύτερα από την ταξιδιωτική. Μπορούμε πάντα να συνεχίσουμε με το ταξιδιωτικό αν προτιμάτε. "
                if greek else
                "This sounds more like a relocation than a trip — if you'll be staying long-term, international health insurance (IPMI) is usually a better fit than travel cover. "
                "We can still continue with travel insurance if you'd prefer. "
            )

        next_q = next_travel_question(state, greek)
        if next_q is not None:
            state["travel_pending_question"] = next_q["key"]
            return {
                "reply": (long_stay_prefix + next_q["reply"]).strip(), "state": state, "quotes": [], "excluded_plans": [],
                "ai_status": "travel_guided_discovery", "journey": "travel",
                "lead_cta": {"show": False, "journey": "travel", "label": "Request a travel insurance callback"},
                "open_application_form": False, "quick_replies": next_q["quick_replies"],
            }

        state["travel_pending_question"] = None
        result = recommend_tier(state)
        reply = (f"Βάσει των legacy Europesure στοιχείων, το {result['plan_name']} ταιριάζει καλύτερα. "
                 "Τα τρέχοντα όρια/όροι/τιμή πρέπει να επιβεβαιωθούν στο Europesure portal πριν την αγορά."
                 if greek else
                 f"Based on the legacy Europesure data, {result['plan_name']} looks like the best fit. "
                 "Current limits, terms and price must be confirmed in the Europesure portal before purchase.")
        if not result["eligible_on_legacy_data"]:
            reply += " " + (result["eligibility_note"] or "")
        return {
            "reply": reply, "state": state, "quotes": [], "excluded_plans": [],
            "ai_status": "travel_recommendation", "journey": "travel", "travel_recommendation": result,
            "lead_cta": {"show": True, "journey": "travel", "label": "Request a travel insurance callback"},
            "open_application_form": False, "quick_replies": [],
        }

    prior_pending = state.get("pending_question")
    deterministic_updates = apply_discovery_answer(message, state)
    state = _merge(state, deterministic_updates)

    if detect_hnwi(message) and not state.get("client_segment"):
        state["client_segment"] = "hnwi"

    claude_ack = ""
    provisional = classify_journey(message, state)
    if (settings.anthropic_api_key and provisional not in {"travel", "local_review"}
            and not state.get("discovery_complete") and prior_pending != "name"):
        intake = await intake_analysis(message, state, history, greek)
        ai_updates = dict(intake.get("applicant_updates", {}) or {})
        # Deterministic answers to the actual pending question are authoritative.
        # The LLM may enrich other facts from the same sentence, but it must
        # never overwrite the field the applicant just explicitly confirmed.
        protected_by_question = {
            "age": {"age"},
            "residence": {"residence_country"},
            "nationality": {"nationality"},
            "coverage_area": {"coverage_area"},
            "deductible": {"deductible", "deductible_preference"},
            "outpatient": {"outpatient_required"},
            "chronic": {"chronic_required", "chronic_conditions_disclosed"},
            "maternity": {"maternity_required"},
            "dental": {"dental_required"},
            "mental_health": {"mental_health_required"},
            "wellness": {"wellness_required"},
            "optical": {"optical_required"},
            "evacuation": {"evacuation_required"},
            "budget": {"budget_annual"},
        }
        for key in protected_by_question.get(prior_pending, set()):
            if key in deterministic_updates:
                ai_updates.pop(key, None)
        state = _merge(state, ai_updates)
        claude_ack = intake.get("acknowledgement", "")

    journey = classify_journey(message, state)
    # Once discovery has established an IPMI journey, short follow-ups such as
    # "yes" / "ναι" must not erase that context by being classified as
    # undetermined. Keep the established journey sticky unless the applicant
    # clearly switches product.
    if journey == "undetermined" and previous_journey in valid:
        journey = previous_journey
    state["journey"] = journey

    if state.get("discovery_complete") and journey == "ipmi":
        intent = _post_shortlist_intent(message)
        if intent == "greece_healthcare":
            return {
                "reply": _greece_healthcare_summary(greek),
                "state": state, "quotes": [], "excluded_plans": [],
                "ai_status": "greece_healthcare_context", "journey": "ipmi",
                "lead_cta": {"show": True, "journey": "ipmi", "label": "Request a proposal"},
                "open_application_form": False, "quick_replies": [],
            }
        if intent == "explain_plan":
            quote_objects = _quote_objects(state, settings)
            quote = _pick_quote_from_message(message, quote_objects)
            if quote is not None:
                reply = await explain_plan(quote, message, greek)
                state["last_explained_plan_key"] = quote.plan_key
                return {
                    "reply": reply,
                    "state": state, "quotes": [], "excluded_plans": [],
                    "ai_status": "evidence_locked_plan_explanation", "journey": "ipmi",
                    "lead_cta": {"show": True, "journey": "ipmi", "label": "Request a proposal"},
                    "open_application_form": False, "quick_replies": [],
                }

    if journey == "local_review":
        try:
            reply = await adviser_response(instructions=build_local_review_instructions(greek), message=message, history=history, max_tokens=300)
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
        reply = ((claude_ack.rstrip() + " " + next_q["reply"]) if claude_ack else next_q["reply"]).strip()
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
    state["last_shortlist_plan_keys"] = [q.get("plan_key") for q in quotes if q.get("plan_key")]
    excluded = _exclusions_payload(state, settings)
    label = "Request a private consultation" if state.get("client_segment") == "hnwi" else "Request a proposal"
    name = state.get("applicant_name")
    intro = (f"Τέλεια{', ' + name if name else ''} — τώρα έχω αρκετά στοιχεία. Παρακάτω είναι το shortlist του HAL."
              if greek else f"Great{', ' + name if name else ''} — I now have enough information. Here is HAL's shortlist.")
    reasoning = _shortlist_reasoning(quotes, excluded, greek)
    followup = ("Θέλετε να σας εξηγήσω κάποιο από τα προγράμματα πιο αναλυτικά, ή να συγκρίνουμε αυτά τα δύο συστήματα υγείας (δημόσιο vs ιδιωτικό) στην Ελλάδα;"
                if greek else
                "Want me to walk you through any of these plans in more detail, or explain how they'd compare to relying on Greece's public healthcare system?")
    reply = f"{intro} {reasoning}".strip()

    verification = await verify_shortlist(
        state, quotes, excluded,
        rendered_reply=reply,
        expected_greek=greek,
        settings=settings,
    )
    verification_payload = verification.model_dump(mode="json")

    if verification.verdict == "BLOCK":
        blocked_reply = (
            "Ο HAL εντόπισε ασυνέπεια μεταξύ των απαιτήσεών σας και του αποτελέσματος της σύγκρισης, "
            "οπότε δεν θα εμφανίσει το shortlist μέχρι να επανελεγχθούν τα δεδομένα. Έχει σημανθεί για έλεγχο."
            if greek else
            "HAL detected a consistency issue between your requirements and the comparison output, "
            "so it has withheld the shortlist until the data is rechecked. It has been flagged for review."
        )
        return {
            "reply": blocked_reply, "followup_message": "", "state": state, "quotes": [], "excluded_plans": excluded,
            "ai_status": "verifier_blocked_shortlist", "journey": journey if journey != "undetermined" else "ipmi",
            "lead_cta": {"show": True, "journey": "ipmi", "label": label},
            "open_application_form": False, "quick_replies": [],
            "discovery": discovery_progress(state),
            "verification": verification_payload,
        }

    return {
        "reply": reply, "followup_message": followup, "state": state, "quotes": quotes, "excluded_plans": excluded,
        "ai_status": "verified_shortlist" if verification.model_used else "deterministic_shortlist",
        "journey": journey if journey != "undetermined" else "ipmi",
        "lead_cta": {"show": True, "journey": "ipmi", "label": label},
        "open_application_form": False, "quick_replies": [],
        "discovery": discovery_progress(state),
        "verification": verification_payload,
    }
