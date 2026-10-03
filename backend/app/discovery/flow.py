from __future__ import annotations

"""Family-aware discovery facade.

The mature single-applicant parser remains in ``legacy_flow``. Household
collection is opt-in at the state level. New web sessions are upgraded when
the applicant answers the client-initialised name question; older in-flight
and server-started legacy sessions continue on the established path.
"""

from backend.app.discovery import legacy_flow as _legacy
from backend.app.discovery.family_flow import apply_family_answer, next_family_question

YES = _legacy.YES
NO = _legacy.NO
SKIP = _legacy.SKIP
QUESTION_ORDER = _legacy.QUESTION_ORDER
OPPORTUNISTIC_SIGNALS = _legacy.OPPORTUNISTIC_SIGNALS
QUICK_REPLY_LABELS_EL = _legacy.QUICK_REPLY_LABELS_EL


def _family_enabled(state: dict) -> bool:
    return bool(state.get("household_discovery_enabled"))


def _sex_question(greek: bool) -> dict:
    if greek:
        return {"key":"primary_sex","reply":"Ποιο είναι το φύλο σας;","quick_replies":[{"label":"Γυναίκα","value":"female"},{"label":"Άνδρας","value":"male"},{"label":"Δεν επιθυμώ να απαντήσω","value":"unspecified"}]}
    return {"key":"primary_sex","reply":"What is your sex?","quick_replies":[{"label":"Female","value":"female"},{"label":"Male","value":"male"},{"label":"Prefer not to say","value":"unspecified"}]}


def _maternity_question(greek: bool) -> dict:
    return {"key":"maternity","reply":"Θέλετε να περιλαμβάνεται κάλυψη εγκυμοσύνης/τοκετού;" if greek else "Do you want maternity cover included?","quick_replies":[{"label":"Ναι, με κάλυψη μητρότητας" if greek else "Yes, maternity","value":"Yes, maternity is required"},{"label":"Όχι" if greek else "No","value":"No maternity needed"}]}


def apply_discovery_answer(message: str, state: dict) -> dict:
    pending = state.get("pending_question")
    if not _family_enabled(state):
        updates = _legacy.apply_discovery_answer(message, state)
        # The browser initializes directly at the name question before a
        # journey has been classified. A server-started legacy journey has
        # already set journey='ipmi', so it remains backward compatible.
        if pending == "name" and not state.get("journey") and updates.get("name_asked"):
            updates["household_discovery_enabled"] = True
        return updates
    if pending == "primary_sex":
        low = (message or "").strip().lower()
        if low in {"female","woman","f","γυναίκα","γυναικα"}:
            return {"sex":"female","primary_sex_answered":True,"pending_question":None}
        if low in {"male","man","m","άνδρας","ανδρας"}:
            return {"sex":"male","primary_sex_answered":True,"pending_question":None}
        if low in {"unspecified","prefer not to say","skip","δεν επιθυμώ να απαντήσω","δεν επιθυμω να απαντησω"}:
            return {"sex":"unspecified","primary_sex_answered":True,"pending_question":None}
        return {}
    if pending and pending.startswith("family_"):
        return apply_family_answer(message, state)
    return _legacy.apply_discovery_answer(message, state)


def next_discovery_question(state: dict, greek: bool = False) -> dict | None:
    if not _family_enabled(state):
        return _legacy.next_discovery_question(state, greek)
    if not state.get("name_asked") or not state.get("age"):
        return _legacy.next_discovery_question(state, greek)
    if not state.get("primary_sex_answered"):
        return _sex_question(greek)
    prerequisites = (state.get("residence_country") and state.get("primary_healthcare_country_answered") and (state.get("nationality_answered") or state.get("coverage_area")) and state.get("coverage_area"))
    if prerequisites and not state.get("family_answered"):
        return next_family_question(state, greek)
    if state.get("family_requested") and not state.get("household_complete"):
        family_q = next_family_question(state, greek)
        if family_q:
            return family_q
    age = int(state.get("age") or 0)
    sex = state.get("sex")
    relevant = sex == "female" and 18 <= age <= 47
    if not relevant and not state.get("maternity_answered"):
        state["maternity_required"] = False
        state["maternity_answered"] = True
    if relevant and age in {46,47} and state.get("chronic_answered") and not state.get("maternity_answered"):
        return _maternity_question(greek)
    return _legacy.next_discovery_question(state, greek)


def discovery_progress(state: dict) -> dict:
    base = _legacy.discovery_progress(state)
    if not _family_enabled(state):
        return base
    extras = 1
    done_extras = int(bool(state.get("primary_sex_answered")))
    if state.get("coverage_area"):
        extras += 1
        done_extras += int(bool(state.get("family_answered")))
        if state.get("family_requested"):
            extras += 1
            done_extras += int(bool(state.get("household_complete")))
    completed = int(base.get("completed",0)) + done_extras
    total = int(base.get("total",0)) + extras
    return {"completed":completed,"total":total,"percent":round(completed/max(total,1)*100)}
