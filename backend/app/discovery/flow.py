from __future__ import annotations
import re

YES = {"yes", "y", "sure", "include it", "include", "important", "needed", "want it",
       "ναι", "βεβαιως", "βεβαίως", "θελω", "θέλω"}
NO = {"no", "n", "not needed", "no thanks", "none",
      "όχι", "οχι", "δεν με ενδιαφερει", "δεν με ενδιαφέρει"}
SKIP = {"skip", "not sure", "no preference", "i don't know", "i dont know", "pass",
        "δεν ξέρω", "δεν ξερω", "παράλειψη", "παραλειψη", "δεν έχω άποψη", "δεν εχω αποψη"}

# Every question in the sequence, in order. `key` matches the state flag
# `<key>_answered`. `field` is the applicant boolean/value field it sets.
# Chronic is asked early (right after outpatient) per the audit finding that
# it is the single most underwriting-relevant question and must not be
# tucked away in an optional edit panel.
QUESTION_ORDER = [
    "age", "residence", "coverage_area", "deductible", "outpatient",
    "chronic", "maternity", "dental", "mental_health", "wellness",
    "optical", "evacuation", "budget",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _has_any(text: str, terms: set[str]) -> bool:
    return any(t in text for t in terms)


def _is_skip(text: str) -> bool:
    return _norm(text) in SKIP


def _q(key: str, reply: str, choices: list[tuple[str, str]] | None = None, skippable: bool = True) -> dict:
    replies = [{"label": a, "value": b} for a, b in (choices or [])]
    if skippable:
        replies.append({"label": "Not sure / Skip", "value": "skip"})
    return {"key": key, "reply": reply, "quick_replies": replies}


def apply_discovery_answer(message: str, state: dict) -> dict:
    """Interpret the applicant's answer to whatever question is pending.
    A skip is ALWAYS honoured — the applicant can never get stuck repeating
    the same question forever."""
    pending = state.get("pending_question")
    if not pending:
        return {}
    text = _norm(message)
    out: dict = {}

    if _is_skip(text):
        return _skip_result(pending)

    if pending == "age":
        m = re.search(r"\b(\d{1,3})\b", text)
        if m:
            age = int(m.group(1))
            if 0 <= age <= 120:
                out["age"] = age

    elif pending == "residence":
        raw = text.strip(" .,!?:;")
        aliases = {
            "greece": "Greece", "hellas": "Greece", "ελλάδα": "Greece", "ελλαδα": "Greece",
            "uk": "United Kingdom", "united kingdom": "United Kingdom", "england": "United Kingdom",
            "usa": "United States", "united states": "United States",
        }
        cleaned = re.sub(
            r"^(?:i\s+(?:live|reside)\s+in|i'?m\s+(?:living|resident)\s+in|living\s+in|resident\s+in|residing\s+in|in|"
            r"μένω\s+(?:στη|στην|στο|σε)|μενω\s+(?:στη|στην|στο|σε)|κατοικώ\s+(?:στη|στην|στο|σε)|κατοικω\s+(?:στη|στην|στο|σε))\s+",
            "", raw, flags=re.I,
        ).strip(" .,!?:;")
        canonical = aliases.get(cleaned.lower())
        if canonical:
            out["residence_country"] = canonical
        elif cleaned and len(cleaned) <= 80 and re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿΑ-Ωα-ωΆ-ώ .'-]+", cleaned):
            out["residence_country"] = " ".join(p.capitalize() for p in cleaned.split())

    elif pending == "coverage_area":
        if any(x in text for x in ["worldwide including usa", "including usa", "με ηπα", "με usa"]):
            out["coverage_area"] = "area4"
        elif any(x in text for x in ["excluding usa, singapore", "excl usa singapore", "area 2"]):
            out["coverage_area"] = "area2"
        elif any(x in text for x in ["worldwide excluding usa", "excluding usa", "without usa", "χωρίς ηπα", "χωρις ηπα"]):
            out["coverage_area"] = "area3"
        elif any(x in text for x in ["europe", "europe only", "ευρώπη", "ευρωπη"]):
            out["coverage_area"] = "area1"

    elif pending == "deductible":
        if any(x in text for x in ["flexible", "no preference", "whatever", "χωρις προτιμηση", "ευελικ"]):
            out.update(deductible_answered=True, deductible_preference="flexible")
        else:
            m = re.search(r"(?:€|eur)?\s*([0-9][0-9,.]*)", text)
            if m:
                try:
                    out["deductible"] = float(m.group(1).replace(",", ""))
                    out["deductible_answered"] = True
                    out["deductible_preference"] = "fixed"
                except Exception:
                    pass

    elif pending == "outpatient":
        if any(x in text for x in ["hospital only", "inpatient only", "νοσοκομειακη μονο"]):
            out.update(outpatient_required=False, outpatient_answered=True)
        elif _has_any(text, {"outpatient", "comprehensive", "doctor visits", "diagnostic", "εξωνοσοκομ"}) or _has_any(text, YES):
            out.update(outpatient_required=True, outpatient_answered=True)
        elif _has_any(text, NO):
            out.update(outpatient_required=False, outpatient_answered=True)

    elif pending == "chronic":
        # Two distinct facts can come out of one answer: does the applicant
        # want the plan to cover chronic conditions going forward
        # (chronic_required), and separately, do they have one to disclose
        # now (chronic_conditions_disclosed) — never conflate the two.
        if _has_any(text, {"i have", "i have a condition", "diagnosed", "already have",
                            "έχω", "εχω", "διαγνωσμ"}):
            out.update(chronic_conditions_disclosed=True, chronic_required=True, chronic_answered=True)
        elif _has_any(text, YES):
            out.update(chronic_required=True, chronic_answered=True)
        elif _has_any(text, NO):
            out.update(chronic_required=False, chronic_answered=True)

    elif pending in {"maternity", "dental", "mental_health", "wellness", "optical", "evacuation"}:
        field = {
            "maternity": "maternity_required", "dental": "dental_required",
            "mental_health": "mental_health_required", "wellness": "wellness_required",
            "optical": "optical_required", "evacuation": "evacuation_required",
        }[pending]
        answered = f"{pending}_answered"
        if _has_any(text, YES):
            out.update({field: True, answered: True})
        elif _has_any(text, NO):
            out.update({field: False, answered: True})
        else:
            keywords = {
                "maternity": {"maternity", "pregnancy", "childbirth", "τοκετ", "εγκυμοσ"},
                "dental": {"dental", "dentist", "οδοντ"},
                "mental_health": {"mental health", "psycholog", "psychiatr", "ψυχολ", "ψυχιατρ"},
                "wellness": {"wellness", "screening", "check-up", "checkup", "προληπτ"},
                "optical": {"optical", "eye test", "glasses", "οφθαλμ", "γυαλι"},
                "evacuation": {"evacuation", "repatriation", "διακομιδ", "επαναπατρ"},
            }[pending]
            if _has_any(text, keywords):
                out.update({field: True, answered: True})

    elif pending == "budget":
        if any(x in text for x in ["no fixed budget", "no budget", "flexible budget", "χωρις budget"]):
            out.update(budget_answered=True, budget_preference="flexible")
        else:
            m = re.search(r"(?:€|eur)?\s*([0-9][0-9,.]*)", text)
            if m:
                try:
                    out.update(budget_annual=float(m.group(1).replace(",", "")), budget_answered=True, budget_preference="fixed")
                except Exception:
                    pass

    if out:
        out["pending_question"] = None
    return out


def _skip_result(pending: str) -> dict:
    """Sensible, explicit defaults for a skipped question — never a stuck flow."""
    defaults: dict[str, dict] = {
        "age": {},  # age has no safe default; skip re-asks (handled by next_discovery_question)
        "residence": {},
        "coverage_area": {"coverage_area": "area1"},  # Europe is the safest narrow default
        "deductible": {"deductible_answered": True, "deductible_preference": "flexible"},
        "outpatient": {"outpatient_required": False, "outpatient_answered": True},
        "chronic": {"chronic_required": False, "chronic_answered": True},
        "maternity": {"maternity_required": False, "maternity_answered": True},
        "dental": {"dental_required": False, "dental_answered": True},
        "mental_health": {"mental_health_required": False, "mental_health_answered": True},
        "wellness": {"wellness_required": False, "wellness_answered": True},
        "optical": {"optical_required": False, "optical_answered": True},
        "evacuation": {"evacuation_required": False, "evacuation_answered": True},
        "budget": {"budget_answered": True, "budget_preference": "flexible"},
    }
    out = dict(defaults.get(pending, {}))
    if pending not in {"age", "residence"}:
        out["pending_question"] = None
    return out


def next_discovery_question(state: dict, greek: bool = False) -> dict | None:
    """Return the next question. None means shortlist-ready."""
    if not state.get("age"):
        return _q("age", "How old are you?" if not greek else "Πόσων χρονών είστε;", skippable=False)
    if not state.get("residence_country"):
        return _q("residence", "Which country do you live in?" if not greek else "Σε ποια χώρα μένετε;", skippable=False)
    if not state.get("coverage_area"):
        return _q("coverage_area",
            "Where do you want your cover to apply?" if not greek else "Πού θέλετε να ισχύει η κάλυψή σας;",
            [("Europe", "Europe only"), ("Worldwide excl. USA", "Worldwide excluding USA"), ("Worldwide incl. USA", "Worldwide including USA")])
    if not state.get("deductible_answered"):
        text = ("What deductible would you prefer? A higher one usually means a lower price."
                if not greek else
                "Τι απαλλαγή θα θέλατε; Μεγαλύτερη απαλλαγή σημαίνει συνήθως χαμηλότερη τιμή.")
        return _q("deductible", text, [("€0", "€0 deductible"), ("€500", "€500 deductible"), ("€1,000", "€1000 deductible")])
    if not state.get("outpatient_answered"):
        text = ("Do you want cover for hospital stays only, or also everyday doctor visits?"
                if not greek else
                "Θέλετε κάλυψη μόνο για νοσηλεία, ή και για καθημερινές επισκέψεις στον γιατρό;")
        return _q("outpatient", text, [("Hospital only", "Hospital only"), ("Include outpatient", "Include outpatient cover")])
    if not state.get("chronic_answered"):
        text = ("Do you have an ongoing health condition, or want cover for one in the future? Just yes or no for now."
                if not greek else
                "Έχετε κάποια χρόνια πάθηση, ή θέλετε κάλυψη γι' αυτό στο μέλλον; Για τώρα, απλώς ναι ή όχι.")
        return _q("chronic", text, [("Yes", "Yes"), ("No", "No")])
    age = int(state.get("age") or 0)
    if 18 <= age <= 45 and not state.get("maternity_answered"):
        text = ("Do you want maternity cover included?" if not greek else "Θέλετε να περιλαμβάνεται κάλυψη εγκυμοσύνης/τοκετού;")
        return _q("maternity", text, [("Yes, maternity", "Yes, maternity is required"), ("No", "No maternity needed")])
    if not state.get("maternity_answered"):
        state["maternity_answered"] = True
    if not state.get("dental_answered"):
        return _q("dental", "Do you want dental cover too?" if not greek else "Θέλετε να περιλαμβάνεται και οδοντιατρική κάλυψη;",
                   [("Yes", "Yes, dental is important"), ("No", "No dental needed")])
    if not state.get("mental_health_answered"):
        text = "Do you want mental health cover, like therapy or psychiatry?" if not greek else "Θέλετε κάλυψη για ψυχική υγεία, όπως ψυχοθεραπεία;"
        return _q("mental_health", text, [("Yes", "Yes, mental health is important"), ("No", "No mental health cover needed")])
    if not state.get("wellness_answered"):
        text = "Do you want yearly check-ups included?" if not greek else "Θέλετε να περιλαμβάνονται ετήσιες προληπτικές εξετάσεις;"
        return _q("wellness", text, [("Yes", "Yes, wellness is important"), ("No", "No wellness cover needed")])
    if not state.get("optical_answered"):
        text = "Do you want eye care included, like eye tests or glasses?" if not greek else "Θέλετε να περιλαμβάνεται οφθαλμολογική φροντίδα, όπως εξετάσεις ή γυαλιά;"
        return _q("optical", text, [("Yes", "Yes, optical is important"), ("No", "No optical cover needed")])
    if not state.get("evacuation_answered"):
        text = "Do you want cover for emergency transport home if you get seriously ill abroad?" if not greek else "Θέλετε κάλυψη επείγουσας μεταφοράς σπίτι αν αρρωστήσετε σοβαρά στο εξωτερικό;"
        return _q("evacuation", text, [("Yes", "Yes, evacuation is important"), ("No", "No evacuation priority")])
    if not state.get("budget_answered"):
        return _q("budget", "Do you have a yearly budget in mind?" if not greek else "Έχετε κάποιο ετήσιο ποσό κατά νου;",
                   [("No fixed budget", "No fixed budget"), ("Up to €3,000", "Budget €3000"), ("Up to €5,000", "Budget €5000")])
    return None


def discovery_progress(state: dict) -> dict:
    keys = ["age", "residence_country", "coverage_area", "deductible_answered", "outpatient_answered",
            "chronic_answered", "dental_answered", "mental_health_answered", "wellness_answered",
            "optical_answered", "evacuation_answered", "budget_answered"]
    age = int(state.get("age") or 0)
    if 18 <= age <= 45:
        keys.insert(6, "maternity_answered")
    done = sum(bool(state.get(k)) for k in keys)
    return {"completed": done, "total": len(keys), "percent": round(done / max(len(keys), 1) * 100)}
