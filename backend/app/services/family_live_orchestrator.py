from __future__ import annotations

from typing import Any

from backend.app.core.config import get_settings
from backend.app.rates.quote_engine import quote_shortlist
from backend.app.services.eligibility_agent import assess_eligibility
from backend.app.services.household_quote_service import household_member_states, compose_verified_household
from backend.app.services.orchestrator import chat_turn as base_chat_turn
from backend.app.services.healthcare_context import healthcare_note


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
        labels = _member_labels(current, greek)
        maternity_ids = _maternity_member_ids(current)
        lines = []
        for alloc in top["allocations"]:
            mid = alloc["member_id"]
            note = ""
            if mid in maternity_ids:
                note = " (με κάλυψη μητρότητας)" if greek else " (includes maternity)"
            lines.append(
                f"• {labels.get(mid, mid)}: {alloc['product_name']}{note} — "
                f"{alloc['currency']} {alloc['premium']:,.2f}/{'έτος' if greek else 'year'}"
            )
        split = top.get("plan_count", 1) > 1
        if greek:
            head = ("Έχω πλέον επαληθευμένη σύνθεση για όλα τα μέλη. "
                    + ("Για χαμηλότερο συνολικό κόστος, τα μέλη κατανέμονται σε διαφορετικά προγράμματα ανάλογα με τις ανάγκες του καθενός:"
                       if split else "Όλα τα μέλη καλύπτονται στο ίδιο πρόγραμμα:"))
            tail = f"Σύνολο νοικοκυριού: {currency} {total:,.2f}/έτος."
        else:
            head = ("I now have a verified composition for every household member. "
                    + ("To keep the total cost down, members are placed on different plans according to their individual needs:"
                       if split else "All members are covered on the same plan:"))
            tail = f"Household total: {currency} {total:,.2f}/year."
        result["reply"] = "\n".join([head, *lines, tail])
        note = healthcare_note(current.get("primary_healthcare_country") or current.get("residence_country"), greek)
        if note:
            result["reply"] += "\n\n" + note
        result["healthcare_note"] = note
        result["household_breakdown"] = [
            {**alloc, "label": labels.get(alloc["member_id"], alloc["member_id"]),
             "maternity": alloc["member_id"] in maternity_ids}
            for alloc in top["allocations"]
        ]
        result["quotes"] = _household_plan_cards(
            top, quotes_by_member, labels, maternity_ids, greek
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


_REL_LABELS = {
    "spouse": ("Spouse", "Σύζυγος"),
    "partner": ("Partner", "Σύντροφος"),
    "child": ("Child", "Παιδί"),
    "other": ("Family member", "Μέλος"),
}


def _member_labels(state: dict[str, Any], greek: bool) -> dict[str, str]:
    """Client-facing, non-identifying labels such as 'Spouse (35)'."""
    name = state.get("applicant_name")
    age = state.get("age")
    if greek:
        primary = f"{name or 'Εσείς'} ({age})" if age else (name or "Εσείς")
    else:
        primary = f"{name or 'You'} ({age})" if age else (name or "You")
    labels = {"primary": primary}
    counts: dict[str, int] = {}
    members = [m for m in state.get("household_members") or [] if isinstance(m, dict)]
    totals: dict[str, int] = {}
    for m in members:
        totals[m.get("relationship", "other")] = totals.get(m.get("relationship", "other"), 0) + 1
    for m in members:
        rel = m.get("relationship", "other")
        en, el = _REL_LABELS.get(rel, _REL_LABELS["other"])
        base = el if greek else en
        counts[rel] = counts.get(rel, 0) + 1
        if totals[rel] > 1:
            base = f"{base} {counts[rel]}"
        if m.get("age") is not None:
            base = f"{base} ({m['age']})"
        labels[str(m.get("member_id"))] = base
    return labels


def _maternity_member_ids(state: dict[str, Any]) -> set[str]:
    ids = {str(m.get("member_id")) for m in state.get("household_members") or []
           if isinstance(m, dict) and m.get("maternity_required")}
    try:
        primary_eligible = str(state.get("sex") or "").lower() == "female" and 18 <= int(state.get("age") or 0) <= 47
    except (TypeError, ValueError):
        primary_eligible = False
    if state.get("maternity_required") and primary_eligible:
        ids.add("primary")
    return ids


def _household_plan_cards(
    top: dict[str, Any],
    quotes_by_member: dict[str, list[dict[str, Any]]],
    labels: dict[str, str],
    maternity_ids: set[str],
    greek: bool,
) -> list[dict[str, Any]]:
    """One card per plan used in the chosen household composition.

    The card's premium is the sum of the verified premiums of the members
    allocated to that plan — never one person's price presented as a family
    price. Each card lists exactly which members it covers and at what price.
    Card details (benefits, limits) come from the member's own verified quote.
    """
    by_plan: dict[str, list[dict[str, Any]]] = {}
    for alloc in top["allocations"]:
        by_plan.setdefault(alloc["plan_key"], []).append(alloc)

    cards: list[dict[str, Any]] = []
    for plan_key, allocs in by_plan.items():
        source = None
        for alloc in allocs:
            source = next((q for q in quotes_by_member.get(alloc["member_id"], [])
                           if q.get("plan_key") == plan_key), None)
            if source:
                break
        if source is None:
            continue
        members = [{
            "member_id": a["member_id"],
            "label": labels.get(a["member_id"], a["member_id"]),
            "premium": a["premium"],
            "currency": a["currency"],
            "maternity": a["member_id"] in maternity_ids,
        } for a in allocs]
        card = dict(source)
        card["premium"] = round(sum(a["premium"] for a in allocs), 2)
        card["family_size"] = len(allocs)
        card["household_card"] = True
        card["household_members"] = members
        card["recommended"] = False
        names = ", ".join(m["label"] for m in members)
        card["card_why"] = (f"Καλύπτει: {names}" if greek else f"Covers: {names}")
        # Individual excluded-plan or "top pick" wording must not leak in.
        card.pop("rank_reason", None)
        cards.append(card)

    # Show the plan covering most members first.
    cards.sort(key=lambda c: (-c["family_size"], c["premium"]))
    return cards


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
