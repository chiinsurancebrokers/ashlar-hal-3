"""Visa / residence-permit awareness.

Many people look for health insurance because a consulate or immigration
authority asks for it (e.g. Portugal's AIMA appointment, a D7/D8 visa, a
golden visa). They often buy the cheapest plan that gets them through the
appointment and look at international cover a year later — when any new
condition may be excluded at underwriting.

HAL does not state what any authority requires (that changes and differs by
visa type). It says so plainly, lays out the routes Ashlar can help with, and
explains the switching risk honestly.
"""
from __future__ import annotations

import re
from typing import Any

_TERMS = re.compile(
    r"\bvisa\b|\bvisas\b|residence\s+permit|residency\s+permit|residence\s+card|residency\s+(?:application|appointment)|"
    r"golden\s+visa|digital\s+nomad|\bd7\b|\bd8\b|\baima\b|\bsef\b|immigration\s+(?:office|appointment|authority)|"
    r"βίζα|βιζα|visa\b|άδεια\s+διαμονής|αδεια\s+διαμονης|χρυσή\s+βίζα|χρυση\s+βιζα|μετανάστευσ|μεταναστευσ",
    re.I,
)


def mentions_residency_purpose(text: str) -> bool:
    return bool(_TERMS.search(text or ""))


def is_foreign_resident(state: dict[str, Any]) -> bool:
    residence = str(state.get("residence_country") or "").strip().lower()
    nationality = str(state.get("nationality") or "").strip().lower()
    return bool(residence and nationality and residence != nationality)


def residency_question(greek: bool) -> tuple[str, list[tuple[str, str]]]:
    if greek:
        return ("Χρειάζεστε την ασφάλιση για αίτηση βίζας ή άδειας διαμονής;",
                [("Ναι, για βίζα/άδεια διαμονής", "Yes, for a visa or residence permit"), ("Όχι", "No, not for a visa")])
    return ("Do you need this insurance for a visa or residence-permit application?",
            [("Yes, for a visa / permit", "Yes, for a visa or residence permit"), ("No", "No, not for a visa")])


def residency_note(state: dict[str, Any], greek: bool) -> str:
    country = state.get("residence_country") or ""
    name = state.get("applicant_name")
    if greek:
        where = f" για {country}" if country else ""
        lead = f"{name}, επειδή" if name else "Επειδή"
        return (
            f"{lead} τη χρειάζεστε για βίζα ή άδεια διαμονής{where}: την ακριβή απαίτηση (ελάχιστη κάλυψη, απαλλαγή, "
            "τι πρέπει να γράφει η βεβαίωση) την ορίζει το προξενείο ή η υπηρεσία μετανάστευσης, γι' αυτό ελέγξτε την "
            "για τον δικό σας τύπο βίζας πριν αγοράσετε. Η Ashlar μπορεί να βοηθήσει με τρεις δρόμους: βραχυπρόθεσμη "
            "ταξιδιωτική κάλυψη για το στάδιο της βίζας, ένα τοπικό πρόγραμμα, ή διεθνή κάλυψη. "
            "Ένα σημείο που αξίζει να ζυγίσετε: αν ξεκινήσετε με φθηνότερο τοπικό ή βραχυπρόθεσμο πρόγραμμα και περάσετε "
            "σε διεθνές αργότερα, ο νέος ασφαλιστής θα σας αξιολογήσει τότε — παθήσεις που θα εμφανιστούν στο μεταξύ "
            "μπορεί να εξαιρεθούν. Η Ashlar μπορεί να κρατήσει τη σύγκρισή σας έτοιμη για εκείνη τη στιγμή."
        )
    where = f" in {country}" if country else ""
    lead = f"{name}, since" if name else "Since"
    return (
        f"{lead} you need this for a visa or residence permit{where}: the exact insurance requirement (minimum cover, "
        "deductible, what the certificate must say) is set by the consulate or immigration authority, so please check it "
        "for your visa type before you buy. Ashlar can help with three routes: short-term travel cover for the visa stage, "
        "a local plan, or international cover. One thing worth weighing: if you start with a cheaper local or "
        "short-term plan and move to international cover later, the new insurer underwrites you at that point — conditions "
        "that start in between may be excluded. Ashlar can keep your comparison ready for that moment."
    )


def residency_quick_reply(greek: bool) -> dict[str, str]:
    # The value deliberately contains "travel insurance" so the journey
    # classifier opens the travel (Europesure) flow.
    return ({"label": "Ταξιδιωτική κάλυψη για τη βίζα", "value": "I need travel insurance for my visa stage"}
            if greek else
            {"label": "Travel cover for the visa stage", "value": "I need travel insurance for my visa stage"})


def add_residency_note(result: dict[str, Any], state: dict[str, Any], greek: bool) -> None:
    """Insert the note once, before the closing country healthcare note."""
    if not state.get("residency_purpose") or state.get("residency_note_shown"):
        return
    text = residency_note(state, greek)
    reply = result.get("reply") or ""
    health = result.get("healthcare_note") or ""
    if health and health in reply:
        cut = reply.rfind(health)
        result["reply"] = reply[:cut].rstrip() + "\n\n" + text + "\n\n" + health
    else:
        result["reply"] = (reply.rstrip() + "\n\n" + text).strip()
    result["residency_note"] = text
    result["quick_replies"] = [*(result.get("quick_replies") or []), residency_quick_reply(greek)]
    state["residency_note_shown"] = True
