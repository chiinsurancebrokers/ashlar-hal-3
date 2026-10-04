"""Benefit trade-off adviser.

After a shortlist, HAL checks deterministically whether one optional benefit
the client asked for is what forces an expensive plan (e.g. optical cover is
only on Morgan Price Premium). If dropping it would lower the price
materially, HAL SUGGESTS it — the client's selection is never changed unless
they ask for it (quick reply "Show the option without …").

No AI is involved: every figure comes from the same rating engine.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from backend.app.core.config import Settings
from backend.app.rates.quote_engine import quote_shortlist
from backend.app.schemas.applicant import Applicant
from backend.app.services.household_quote_service import compose_verified_household, household_member_states

# Optional benefits HAL may suggest dropping. Maternity and chronic-condition
# cover are deliberately excluded: those are personal medical decisions.
DROPPABLE = {
    "optical_required": ("optical cover", "την κάλυψη οπτικών"),
    "dental_required": ("dental cover", "την οδοντιατρική κάλυψη"),
    "mental_health_required": ("mental health cover", "την κάλυψη ψυχικής υγείας"),
    "wellness_required": ("check-up / wellness cover", "την κάλυψη check-up"),
    "evacuation_required": ("medical evacuation cover", "την κάλυψη αεροδιακομιδής"),
    "outpatient_required": ("outpatient cover", "την εξωνοσοκομειακή κάλυψη"),
}
_DROP_PATTERNS = {
    "optical_required": r"optical|eye|οπτικ|οφθαλμ",
    "dental_required": r"dental|οδοντ",
    "mental_health_required": r"mental|ψυχικ",
    "wellness_required": r"wellness|check-?up|προληπτ",
    "evacuation_required": r"evacuation|αεροδιακομιδ|διακομιδ",
    "outpatient_required": r"outpatient|εξωνοσοκομ",
}
MIN_SAVING_EUR = 200.0
MIN_SAVING_SHARE = 0.05


def _applicant(state: dict[str, Any]) -> Applicant | None:
    fields = {k: v for k, v in state.items() if k in Applicant.model_fields}
    if not fields.get("age") or not fields.get("coverage_area"):
        return None
    try:
        return Applicant(**fields)
    except Exception:
        return None


def _household_total(state: dict[str, Any], settings: Settings, blocked: set[str]) -> dict | None:
    quotes_by_member: dict[str, list[dict]] = {}
    for member_id, member_state in household_member_states(state):
        if member_id in blocked:
            return None
        applicant = _applicant(member_state)
        if applicant is None:
            return None
        quotes_by_member[member_id] = [q.model_dump(mode="json") for q in quote_shortlist(applicant, settings)]
    household = compose_verified_household(quotes_by_member, commercial_rules=[])
    if household["status"] != "verified_household_options":
        return None
    top = household["options"][0]
    return {"total": top["total_premium"], "currency": top["currency"],
            "plans": sorted({a["product_name"] for a in top["allocations"]}),
            "by_member": {a["member_id"]: a["product_name"] for a in top["allocations"]},
            "options": len(household["options"])}


def _individual_total(state: dict[str, Any], settings: Settings) -> dict | None:
    applicant = _applicant(state)
    if applicant is None:
        return None
    quotes = [q for q in quote_shortlist(applicant, settings) if q.premium is not None]
    verified = [q for q in quotes if q.official_rate and not q.unmatched_requirements]
    if not verified:
        return None
    best = min(verified, key=lambda q: q.premium)
    return {"total": round(best.premium, 2), "currency": best.currency, "plans": [best.product_name],
            "by_member": {"primary": best.product_name}, "options": len(verified)}


def find_tradeoff(state: dict[str, Any], settings: Settings, current: dict, *, household: bool,
                  blocked: set[str] | None = None) -> dict | None:
    """Return the single most valuable optional benefit to reconsider, or None.

    `current` is {"total", "currency", "plans"} for the shortlist just shown.
    """
    best = None
    for field in DROPPABLE:
        if not state.get(field):
            continue
        alt_state = deepcopy(state)
        alt_state[field] = False
        for member in alt_state.get("household_members") or []:
            if isinstance(member, dict):
                member.pop(field, None)
        alt = (_household_total(alt_state, settings, blocked or set()) if household
               else _individual_total(alt_state, settings))
        if not alt or alt["currency"] != current["currency"]:
            continue
        saving = round(current["total"] - alt["total"], 2)
        if saving < max(MIN_SAVING_EUR, MIN_SAVING_SHARE * current["total"]):
            continue
        if best is None or saving > best["saving"]:
            best = {
                "field": field, "saving": saving, "alt_total": alt["total"], "currency": alt["currency"],
                "current_total": current["total"],
                # Plans members had to be on only because of this benefit.
                "only_on": sorted({plan for mid, plan in (current.get("by_member") or {}).items()
                                   if alt["by_member"].get(mid) not in (None, plan)}),
                "more_options": alt.get("options", 0) > current.get("options", 0),
            }
    return best


def tradeoff_message(tradeoff: dict, name: str | None, greek: bool, household: bool) -> str:
    en_label, el_label = DROPPABLE[tradeoff["field"]]
    cur, alt, save = (f"{tradeoff['currency']} {tradeoff[k]:,.2f}" for k in ("current_total", "alt_total", "saving"))
    only = ", ".join(tradeoff["only_on"])
    if greek:
        who = f", {name}" if name else ""
        scope = "το νοικοκυριό σας" if household else "εσάς"
        reason = (f", που απαιτεί το {only} — το φθηνότερο πρόγραμμα που την περιλαμβάνει" if only else "")
        return (f"💡 Μια πρόταση{who}: αυτό που ανεβάζει κυρίως την τιμή είναι {el_label}{reason}. "
                f"Χωρίς αυτήν, η κάλυψη για {scope} θα ξεκινούσε από {alt}/έτος αντί για {cur} "
                f"({save} λιγότερα){', με περισσότερες επιλογές προγραμμάτων' if tradeoff['more_options'] else ''}. "
                "Κράτησα την επιλογή σας όπως είναι — αν θέλετε να δείτε αυτή την εναλλακτική, πατήστε το κουμπί παρακάτω.")
    who = f", {name}" if name else ""
    scope = "your household" if household else "you"
    reason = (f", which requires {only} — the lowest-priced plan that includes it" if only else "")
    return (f"💡 A suggestion{who}: what mainly drives the price is {en_label}{reason}. "
            f"Without it, cover for {scope} would start from {alt}/year instead of {cur} "
            f"({save} less){', with more plans to choose from' if tradeoff['more_options'] else ''}. "
            "I've kept your selection as it is — if you'd like to see that alternative, tap the button below.")


def tradeoff_quick_reply(tradeoff: dict, greek: bool) -> dict:
    en_label, el_label = DROPPABLE[tradeoff["field"]]
    if greek:
        return {"label": f"Δείξε μου την επιλογή χωρίς {el_label.replace('την ', '')}",
                "value": f"Show the option without {en_label}"}
    return {"label": f"Show the option without {en_label}", "value": f"Show the option without {en_label}"}


def requested_drop(message: str) -> str | None:
    """Field the client explicitly asked to drop via the quick reply, else None."""
    low = (message or "").strip().lower()
    if not re.match(r"^(show (me )?the option without|δείξε μου την επιλογή χωρίς|δειξε μου την επιλογη χωρις)", low):
        return None
    for field, pattern in _DROP_PATTERNS.items():
        if re.search(pattern, low):
            return field
    return None
