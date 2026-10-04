from __future__ import annotations

import re
from typing import Any

from backend.app.services.family_household_agent import HouseholdMember, maternity_relevant

YES = {"yes", "y", "sure", "include", "yes please", "ναι", "βεβαίως", "βεβαιως"}
NO = {"no", "n", "none", "no thanks", "όχι", "οχι"}

# Children are insurable as dependants only while under this age.
MAX_CHILD_DEPENDANT_AGE = 25


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _q(key: str, reply: str, choices: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "reply": reply,
        "quick_replies": [{"label": label, "value": value} for label, value in (choices or [])],
    }


def _members(state: dict) -> list[dict]:
    members = state.get("household_members")
    return list(members) if isinstance(members, list) else []


def _current_member(state: dict) -> dict | None:
    members = _members(state)
    idx = int(state.get("household_member_index") or 0)
    return members[idx] if 0 <= idx < len(members) else None


def _parse_relationship(text: str) -> str | None:
    low = _norm(text)
    if any(x in low for x in ["spouse", "wife", "husband", "σύζυγ", "συζυγ"]):
        return "spouse"
    if any(x in low for x in ["partner", "σύντροφ", "συντροφ"]):
        return "partner"
    if any(x in low for x in ["child", "son", "daughter", "kid", "παιδ", "γιο", "κόρη", "κορη"]):
        return "child"
    if any(x in low for x in ["other", "άλλο", "αλλο"]):
        return "other"
    return None


def _parse_sex(text: str) -> str | None:
    low = _norm(text)
    if low in {"female", "woman", "girl", "f", "γυναίκα", "γυναικα", "κορίτσι", "κοριτσι"}:
        return "female"
    if low in {"male", "man", "boy", "m", "άνδρας", "ανδρας", "αγόρι", "αγορι"}:
        return "male"
    if low in {"prefer not to say", "unspecified", "skip", "δεν επιθυμώ", "δεν επιθυμω"}:
        return "unspecified"
    return None


def apply_family_answer(message: str, state: dict) -> dict:
    """Parse only the deterministic household questions.

    The function never infers sex from names and never calculates premiums.
    """
    pending = state.get("pending_question")
    text = _norm(message)
    out: dict[str, Any] = {}

    if pending == "family_include":
        if text in YES:
            out.update(family_answered=True, family_requested=True, household_members=[], household_member_index=0)
        elif text in NO:
            out.update(family_answered=True, family_requested=False, household_complete=True)

    elif pending == "family_relationship":
        relationship = _parse_relationship(text)
        if relationship:
            members = _members(state)
            members.append({"member_id": f"member-{len(members)+1}", "relationship": relationship})
            out.update(household_members=members, household_member_index=len(members)-1)

    elif pending == "family_age":
        match = re.search(r"\b(\d{1,3})\b", text)
        if match:
            age = int(match.group(1))
            if 0 <= age <= 120:
                members = _members(state)
                idx = int(state.get("household_member_index") or 0)
                if 0 <= idx < len(members):
                    if members[idx].get("relationship") == "child" and age >= MAX_CHILD_DEPENDANT_AGE:
                        # A child aged 25+ cannot be insured as a dependant.
                        members.pop(idx)
                        out.update(
                            household_members=members,
                            household_member_index=len(members),
                            family_notice="child_over_age",
                        )
                    else:
                        members[idx] = {**members[idx], "age": age}
                        out["household_members"] = members

    elif pending == "family_sex":
        sex = _parse_sex(text)
        if sex:
            members = _members(state)
            idx = int(state.get("household_member_index") or 0)
            if 0 <= idx < len(members):
                members[idx] = {**members[idx], "sex": sex}
                out["household_members"] = members

    elif pending == "family_maternity":
        members = _members(state)
        idx = int(state.get("household_member_index") or 0)
        if 0 <= idx < len(members) and (text in YES or text in NO):
            members[idx] = {**members[idx], "maternity_required": text in YES, "maternity_answered": True}
            out["household_members"] = members

    elif pending == "family_add_another":
        if text in YES:
            out["household_member_index"] = len(_members(state))
            out["family_add_another_answered"] = False
        elif text in NO:
            out.update(household_complete=True, family_add_another_answered=True)

    if out:
        out["pending_question"] = None
    return out


def next_family_question(state: dict, greek: bool = False) -> dict | None:
    """Return the next family question, or None when household discovery is complete."""
    if not state.get("family_answered"):
        return _q(
            "family_include",
            "Would you like this quotation to include any family members?" if not greek else "Θέλετε η προσφορά να περιλαμβάνει και μέλη της οικογένειάς σας;",
            [("Yes", "yes"), ("No", "no")] if not greek else [("Ναι", "yes"), ("Όχι", "no")],
        )
    if not state.get("family_requested"):
        return None
    if state.get("household_complete"):
        return None

    if state.get("family_notice") == "child_over_age":
        state.pop("family_notice", None)
        q = _q(
            "family_add_another",
            ("Children aged 25 or over can't be added as dependants on a family policy — they would need "
             "their own individual policy, which we can quote separately. Would you like to add another family member?")
            if not greek else
            ("Τα παιδιά 25 ετών και άνω δεν μπορούν να ασφαλιστούν ως εξαρτώμενα μέλη — χρειάζονται δικό τους "
             "ατομικό πρόγραμμα, που μπορούμε να τιμολογήσουμε ξεχωριστά. Θέλετε να προσθέσετε άλλο μέλος της οικογένειας;"),
            [("Yes", "yes"), ("No", "no")] if not greek else [("Ναι", "yes"), ("Όχι", "no")],
        )
        q["suppress_ack"] = True
        return q

    members = _members(state)
    idx = int(state.get("household_member_index") or 0)
    if idx >= len(members):
        return _q(
            "family_relationship",
            "Who would you like to add?" if not greek else "Ποιο μέλος θέλετε να προσθέσετε;",
            [("Spouse", "spouse"), ("Partner", "partner"), ("Child", "child"), ("Other", "other")]
            if not greek else [("Σύζυγος", "spouse"), ("Σύντροφος", "partner"), ("Παιδί", "child"), ("Άλλο", "other")],
        )

    member = members[idx]
    if "age" not in member:
        return _q("family_age", "How old is this family member?" if not greek else "Πόσων ετών είναι αυτό το μέλος της οικογένειας;")
    if "sex" not in member:
        return _q(
            "family_sex",
            "What is this family member's sex?" if not greek else "Ποιο είναι το φύλο αυτού του μέλους της οικογένειας;",
            [("Female", "female"), ("Male", "male"), ("Prefer not to say", "unspecified")]
            if not greek else [("Γυναίκα", "female"), ("Άνδρας", "male"), ("Δεν επιθυμώ να απαντήσω", "unspecified")],
        )

    typed = HouseholdMember(
        member_id=str(member.get("member_id")),
        relationship=member.get("relationship", "other"),
        age=int(member.get("age") or 0),
        sex=member.get("sex", "unspecified"),
    )
    if maternity_relevant(typed) and not member.get("maternity_answered"):
        return _q(
            "family_maternity",
            "Should maternity cover be included for this family member?" if not greek else "Θέλετε να περιλαμβάνεται κάλυψη μητρότητας για αυτό το μέλος;",
            [("Yes", "yes"), ("No", "no")] if not greek else [("Ναι", "yes"), ("Όχι", "no")],
        )

    return _q(
        "family_add_another",
        "Would you like to add another family member?" if not greek else "Θέλετε να προσθέσετε άλλο μέλος της οικογένειας;",
        [("Yes", "yes"), ("No", "no")] if not greek else [("Ναι", "yes"), ("Όχι", "no")],
    )
