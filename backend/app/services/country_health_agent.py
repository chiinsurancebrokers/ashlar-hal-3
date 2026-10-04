"""Country healthcare note written by AI, locked to official OECD evidence.

For the country where the applicant will live, HAL explains — from OECD
Health at a Glance 2025 only — why international cover can add value there.

* Evidence: data/knowledge/oecd_hag2025/<country>.json (38 OECD countries,
  built by tools/build_oecd_evidence.py, every fact with its PDF page).
* Framing: always the GAP — what is NOT covered, NOT satisfied or unmet —
  never the covered share. The evidence files contain only gap figures.
* Safety: the AI may phrase freely, but every number in its text must exist
  in the country's evidence; otherwise (or on any failure) HAL uses the
  deterministic gap note built from the same evidence.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.knowledge.service import fairness_check
from backend.app.services.anthropic_client import claude_response

EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge" / "oecd_hag2025"

_NEED_LABELS = {
    "outpatient_required": "outpatient care", "dental_required": "dental care",
    "maternity_required": "maternity", "mental_health_required": "mental health",
    "wellness_required": "check-ups / screening", "optical_required": "optical",
    "evacuation_required": "medical evacuation", "chronic_required": "chronic conditions",
}

# Common English variants and Greek names -> evidence file slug.
_ALIASES = {
    "turkey": "turkiye", "τουρκια": "turkiye", "greece": "greece", "hellas": "greece", "ελλαδα": "greece",
    "portugal": "portugal", "πορτογαλια": "portugal", "spain": "spain", "ισπανια": "spain",
    "italy": "italy", "ιταλια": "italy", "france": "france", "γαλλια": "france",
    "germany": "germany", "γερμανια": "germany", "uk": "united-kingdom", "great britain": "united-kingdom",
    "britain": "united-kingdom", "england": "united-kingdom", "ηνωμενο βασιλειο": "united-kingdom",
    "αγγλια": "united-kingdom", "usa": "united-states", "us": "united-states", "america": "united-states",
    "ηπα": "united-states", "ηνωμενες πολιτειες": "united-states", "netherlands": "netherlands",
    "holland": "netherlands", "ολλανδια": "netherlands", "belgium": "belgium", "βελγιο": "belgium",
    "austria": "austria", "αυστρια": "austria", "switzerland": "switzerland", "ελβετια": "switzerland",
    "sweden": "sweden", "σουηδια": "sweden", "norway": "norway", "νορβηγια": "norway",
    "denmark": "denmark", "δανια": "denmark", "finland": "finland", "φινλανδια": "finland",
    "ireland": "ireland", "ιρλανδια": "ireland", "poland": "poland", "πολωνια": "poland",
    "czech republic": "czechia", "τσεχια": "czechia", "slovakia": "slovak-republic",
    "σλοβακια": "slovak-republic", "slovenia": "slovenia", "σλοβενια": "slovenia",
    "hungary": "hungary", "ουγγαρια": "hungary", "estonia": "estonia", "εσθονια": "estonia",
    "latvia": "latvia", "λετονια": "latvia", "lithuania": "lithuania", "λιθουανια": "lithuania",
    "luxembourg": "luxembourg", "λουξεμβουργο": "luxembourg", "iceland": "iceland", "ισλανδια": "iceland",
    "israel": "israel", "ισραηλ": "israel", "japan": "japan", "ιαπωνια": "japan",
    "south korea": "korea", "republic of korea": "korea", "κορεα": "korea", "νοτια κορεα": "korea",
    "canada": "canada", "καναδας": "canada", "mexico": "mexico", "μεξικο": "mexico",
    "chile": "chile", "χιλη": "chile", "colombia": "colombia", "κολομβια": "colombia",
    "costa rica": "costa-rica", "κοστα ρικα": "costa-rica", "australia": "australia",
    "αυστραλια": "australia", "new zealand": "new-zealand", "νεα ζηλανδια": "new-zealand",
}


def _plain(name: str) -> str:
    value = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().strip()
    if not value:  # Greek script: strip accents but keep letters
        value = "".join(c for c in unicodedata.normalize("NFD", (name or "").lower().strip())
                        if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", value)


def resolve_country(name: str | None) -> str | None:
    """Return the evidence slug for a country name in English or Greek, or None."""
    if not name:
        return None
    plain = _plain(name)
    slug = _ALIASES.get(plain) or re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return slug if slug and (EVIDENCE_DIR / f"{slug}.json").exists() else None


@lru_cache
def load_oecd_evidence(country: str | None) -> dict | None:
    slug = resolve_country(country)
    if not slug:
        return None
    return json.loads((EVIDENCE_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def _numbers(text: str) -> set[str]:
    """Normalised numbers: '12,1' -> '12.1', '37.0' -> '37'. Thousands
    separators are not treated as decimals ('1 000' -> '1', '000')."""
    out = set()
    for n in re.findall(r"\d+(?:[.,]\d+)?", text or ""):
        n = n.replace(",", ".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def allowed_numbers(evidence: dict) -> set[str]:
    allowed: set[str] = set()
    for fact in evidence.get("facts", []):
        allowed |= _numbers(fact["text"])
    allowed |= _numbers(evidence.get("source_short_en", ""))
    return allowed


def validate_note(text: str, evidence: dict) -> list[str]:
    """Return the problems with an AI note; empty list means it is safe."""
    problems = [f"unsupported figure: {n}" for n in sorted(_numbers(text) - allowed_numbers(evidence))]
    problems += [f"fairness: {flag}" for flag in fairness_check(text)]
    if "Health at a Glance 2025" not in text:
        problems.append("missing source")
    if len(text) > 1400:
        problems.append("too long")
    return problems


# ---------------------------------------------------------------------------
# Deterministic gap note (fallback, any OECD country)
# ---------------------------------------------------------------------------

_COUNTRY_EL = {
    "greece": ("Ελλάδα", "στην Ελλάδα"), "turkiye": ("Τουρκία", "στην Τουρκία"),
    "portugal": ("Πορτογαλία", "στην Πορτογαλία"), "spain": ("Ισπανία", "στην Ισπανία"),
    "italy": ("Ιταλία", "στην Ιταλία"), "france": ("Γαλλία", "στη Γαλλία"),
    "germany": ("Γερμανία", "στη Γερμανία"), "united-kingdom": ("Ηνωμένο Βασίλειο", "στο Ηνωμένο Βασίλειο"),
    "united-states": ("ΗΠΑ", "στις ΗΠΑ"), "netherlands": ("Ολλανδία", "στην Ολλανδία"),
    "belgium": ("Βέλγιο", "στο Βέλγιο"), "switzerland": ("Ελβετία", "στην Ελβετία"),
}


def _pct(value: float, greek: bool) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return (text.replace(".", ",") if greek else text) + "%"


def _join(items: list[str], greek: bool) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" και " if greek else " and ") + items[-1]


def deterministic_note(country: str | None, greek: bool = False) -> str:
    """Gap-framed note from the country's OECD metrics. Only gaps where the
    country is worse than the OECD average are shown; if there are none,
    no note is produced."""
    evidence = load_oecd_evidence(country)
    if not evidence:
        return ""
    m = {k: v for k, v in evidence.get("metrics", {}).items() if v[0] > v[1]}
    slug = resolve_country(country) or ""
    name = evidence["country"]
    _name_el, in_el = _COUNTRY_EL.get(slug, (name, f"στη χώρα {name}"))
    p = lambda key, i: _pct(m[key][i], greek)  # noqa: E731
    by_type_keys = (("not_public_hospital", "της νοσηλείας", "hospital costs"),
                    ("not_public_outpatient", "της εξωνοσοκομειακής περίθαλψης", "outpatient care"),
                    ("not_public_dental", "της οδοντιατρικής φροντίδας", "dental care"))
    sentences: list[str] = []
    if greek:
        people = []
        if "not_satisfied" in m:
            people.append(f"το {p('not_satisfied', 0)} των κατοίκων δεν είναι ικανοποιημένο από τη διαθεσιμότητα "
                          f"ποιοτικής περίθαλψης (μέσος όρος ΟΟΣΑ {p('not_satisfied', 1)})")
        if "unmet_needs" in m:
            people.append(f"το {p('unmet_needs', 0)} αναφέρει ανικανοποίητες ανάγκες περίθαλψης λόγω κόστους, "
                          f"απόστασης ή αναμονής (ΟΟΣΑ {p('unmet_needs', 1)})")
        if people:
            sentences.append(f"Λίγα λόγια για το σύστημα υγείας {in_el}: " + ", ενώ ".join(people) + ".")
        if "not_public" in m:
            sentences.append(f"{'Επίσης, το' if people else f'Στο σύστημα υγείας {in_el}, το'} {p('not_public', 0)} των δαπανών υγείας "
                             f"δεν καλύπτεται από δημόσια ή υποχρεωτικά σχήματα (ΟΟΣΑ {p('not_public', 1)}).")
        by_type = [f"το {p(k, 0)} {el} (ΟΟΣΑ {p(k, 1)})" for k, el, _en in by_type_keys if k in m]
        if by_type:
            sentences.append("Ανά είδος περίθαλψης, τα δημόσια σχήματα αφήνουν ακάλυπτο " + _join(by_type, True) + ".")
        if not sentences:
            return ""
        sentences.append("Ένα διεθνές πρόγραμμα μπορεί να καλύψει μεγάλο μέρος όσων αφήνει το δημόσιο σύστημα στον ασθενή — "
                         "ιδιωτική νοσηλεία, εξετάσεις και, ανάλογα με το πρόγραμμα, εξωνοσοκομειακή και οδοντιατρική περίθαλψη. "
                         f"Πηγή: {evidence['source_short_el']}.")
        return " ".join(sentences)

    people = []
    if "not_satisfied" in m:
        people.append(f"{p('not_satisfied', 0)} of residents are not satisfied with the availability of quality "
                      f"healthcare (OECD average {p('not_satisfied', 1)})")
    if "unmet_needs" in m:
        people.append(f"{p('unmet_needs', 0)} report unmet medical needs due to cost, distance or waiting times "
                      f"(OECD {p('unmet_needs', 1)})")
    if people:
        sentences.append(f"A word on healthcare in {name}: " + ", and ".join(people) + ".")
    if "not_public" in m:
        lead = "In addition," if people else f"In {name},"
        sentences.append(f"{lead} {p('not_public', 0)} of health spending is not covered by public or compulsory "
                         f"schemes (OECD {p('not_public', 1)}).")
    by_type = [f"{p(k, 0)} of {en} (OECD {p(k, 1)})" for k, _el, en in by_type_keys if k in m]
    if by_type:
        sentences.append("By type of care, public schemes leave uncovered " + _join(by_type, False) + ".")
    if not sentences:
        return ""
    sentences.append("International cover can pay for much of what the public system leaves to the patient — private "
                     "hospital treatment, diagnostics and, depending on the plan, outpatient and dental care. "
                     f"Source: {evidence['source_short_en']}.")
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# AI note
# ---------------------------------------------------------------------------

def build_instructions(evidence: dict, greek: bool, wanted: list[str], household: bool) -> str:
    facts = "\n".join(f"- [p.{f['page']}] {f['text']}" for f in evidence["facts"])
    source = evidence["source_short_el" if greek else "source_short_en"]
    country = evidence["country"]
    return f"""You are HAL, an insurance adviser at Ashlar Assurance. Write a short note, in {"Greek" if greek else "English"}, about the healthcare system in {country}, where the applicant will live, explaining why international private medical insurance can add value there.

Applicant context: {"a family / household quote" if household else "an individual quote"}; benefits the applicant asked for: {", ".join(wanted) or "in-patient cover"}.

The ONLY facts you may use (official OECD data for {country}):
{facts}

Hard rules:
- Use only figures and claims from the list above, and only what they say about {country}. Never add any other number, year, ranking or claim. Never compute new figures.
- ALWAYS frame figures as the gap: what is NOT covered, NOT satisfied, or unmet (e.g. "37% of hospital costs are not covered by public schemes"). Never state the covered or satisfied share.
- Write every percentage exactly as given (in Greek use a decimal comma, e.g. 12,1%).
- Pick the 3-4 gaps most relevant to this applicant: prefer the benefits they asked for (e.g. outpatient, dental, hospital), then health spending not publicly covered, dissatisfaction and unmet needs.
- Only use gaps where {country} is worse than the OECD average. Do not mention figures where {country} does better than the OECD average.
- Explain plainly that international cover can pay for care that the public system leaves to the patient, depending on the plan's benefits. Do not promise that any specific cost is covered.
- Do not insult or disparage the public system or its staff.
- 4-5 sentences, warm and professional, no headings, no bullet points, no markdown.
- End with exactly: "{"Πηγή" if greek else "Source"}: {source}."
"""


async def country_health_note(state: dict, greek: bool, household: bool = False) -> str:
    """AI-written, evidence-locked gap note; deterministic fallback otherwise."""
    country = state.get("primary_healthcare_country") or state.get("residence_country")
    evidence = load_oecd_evidence(country)
    if not evidence:
        return ""
    fallback = deterministic_note(country, greek)
    if not get_settings().anthropic_api_key:
        return fallback
    wanted = [label for key, label in _NEED_LABELS.items() if state.get(key)]
    if any(m.get("maternity_required") for m in state.get("household_members") or [] if isinstance(m, dict)):
        wanted.append("maternity")
    try:
        text = await claude_response(
            instructions=build_instructions(evidence, greek, sorted(set(wanted)), household),
            message="Write the note now.",
            max_tokens=600,
        )
    except Exception:
        return fallback
    text = (text or "").strip()
    if not text or validate_note(text, evidence):
        return fallback
    return text
