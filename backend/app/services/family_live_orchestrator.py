from __future__ import annotations

from typing import Any

from backend.app.core.config import get_settings
from backend.app.rates.quote_engine import quote_shortlist
from backend.app.services.eligibility_agent import assess_eligibility
from backend.app.services.household_quote_service import household_member_states, compose_verified_household
from backend.app.services.orchestrator import chat_turn as base_chat_turn


_SHORTLIST_STATUSES = {"verified_shortlist", "deterministic_shortlist"}


def _completed_family_shortlist(result: dict[str, Any], current: dict[str, Any]) -> bool:
    """Return True only when the base flow has just completed a family IPMI shortlist.

    The public orchestrator can expose ``journey='ipmi'`` at the response level
    while the persisted state still contains ``journey='undetermined'``.  The
    family price safeguard must therefore not depend on the state-level journey
    alone.  Requiring a completed household plus a shortlist response keeps the
    guard narrow and prevents an individual shortlist from being presented as a
    family price.
    """
    journey = current.get("journey") or result.get("journey")
    if journey == "undetermined":
        journey = result.get("journey")
    return bool(
        journey == "ipmi"
        and current.get("family_requested")
        and current.get("household_complete")
        and current.get("discovery_complete")
        and result.get("ai_status") in _SHORTLIST_STATUSES
    )


async def chat_turn(message: str, state: dict, history: list[dict] | None = None) -> dict[str, Any]:
    """Run the established HAL flow, then safely compose a completed family quote.

    The existing orchestrator remains authoritative for discovery and verifier
    behaviour. Once family discovery is complete, each household member is
    independently passed through deterministic eligibility/matching/rating.
    The public response never exposes the primary applicant shortlist as a
    family premium.

    Provider commercial rules are intentionally not injected here until an
    approved evidence-backed rule source is wired. No evidence means no
    discount, by design.
    """
    result = await base_chat_turn(message, state, history)
    current = result.get("state") or state

    if not _completed_family_shortlist(result, current):
        return result

    settings = get_settings()
    quotes_by_member: dict[str, list[dict[str, Any]]] = {}
    member_eligibility: dict[str, dict[str, Any]] = {}

    for member_id, member_state in household_member_states(current):
        applicant = _applicant_from_member_state(member_state)
        if applicant is None:
            quotes_by_member[member_id] = []
            member_eligibility[member_id] = {"verdict": "REVIEW", "reason": "Incomplete member data"}
            continue

        eligibility = await assess_eligibility(applicant, greek=current.get("language") == "el", settings=settings)
        member_eligibility[member_id] = eligibility.model_dump(mode="json")
        if eligibility.verdict == "BLOCK":
            quotes_by_member[member_id] = []
            continue

        quotes_by_member[member_id] = [
            quote.model_dump(mode="json") for quote in quote_shortlist(applicant, settings)
        ]

    household = compose_verified_household(quotes_by_member, commercial_rules=[])
    current["household_quote_status"] = household["status"]
    result["state"] = current
    result["household_quote"] = household
    result["member_eligibility"] = member_eligibility

    # Critical safeguard: a single-person shortlist must never be rendered as
    # the family price. Family pricing is exposed only through household_quote.
    # Excluded individual plans are also suppressed: they are not household
    # options and must never render as available comparison cards.
    result["quotes"] = []
    result["excluded_plans"] = []

    greek = current.get("language") == "el"
    if household["status"] == "verified_household_options":
        top = household["options"][0]
        total = top["total_premium"]
        currency = top["currency"]
        result["reply"] = (
            f"Έχω πλέον επαληθευμένη σύνθεση για όλα τα μέλη του νοικοκυριού. "
            f"Η χαμηλότερη πλήρης επιλογή είναι {currency} {total:,.2f}/έτος για όλο το νοικοκυριό."
            if greek else
            f"I now have a verified composition for every household member. "
            f"The lowest complete option is {currency} {total:,.2f}/year for the whole household."
        )
        result["ai_status"] = "verified_household_shortlist"
    else:
        result["reply"] = (
            "Δεν υπάρχει ακόμη επαληθευμένη τιμή για κάθε μέλος, επομένως δεν θα εμφανίσω ατομική τιμή ως οικογενειακή. "
            "Χρειάζεται προσωπική οικογενειακή προσφορά."
            if greek else
            "A verified price is not yet available for every household member, so I will not present an individual premium as a family premium. "
            "A personal family quotation is required."
        )
        result["ai_status"] = "personal_family_quotation_required"

    return result


def _applicant_from_member_state(member_state: dict[str, Any]):
    # Importing the canonical schema here keeps this adapter independent from
    # private orchestrator helpers while using the same deterministic fields.
    from backend.app.schemas.applicant import Applicant

    allowed = set(Applicant.model_fields)
    fields = {key: value for key, value in member_state.items() if key in allowed}
    if not fields.get("age") or not fields.get("coverage_area"):
        return None
    try:
        return Applicant(**fields)
    except Exception:
        return None
