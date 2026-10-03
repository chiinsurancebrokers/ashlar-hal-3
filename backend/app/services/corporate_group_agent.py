from __future__ import annotations

import re
from typing import Any

MHD_MIN_EMPLOYEES = 5
YES = {"yes", "y", "ναι", "nai"}
NO = {"no", "n", "όχι", "οχι"}
BENEFITS = {
    "inpatient": "Inpatient",
    "outpatient": "Outpatient",
    "dental": "Dental",
    "optical": "Optical",
    "maternity": "Maternity",
    "mental_health": "Mental Health",
    "wellness": "Wellness",
    "evacuation": "Evacuation",
}


def is_corporate_intent(message: str, state: dict | None = None) -> bool:
    state = state or {}
    if state.get("journey") == "corporate_group":
        return True
    text = (message or "").lower()
    terms = (
        "group health", "group insurance", "corporate health", "corporate insurance",
        "employee health", "employee insurance", "company health", "company insurance",
        "staff health", "staff insurance", "ομαδική ασφάλιση", "ομαδικη ασφαλιση",
        "ασφάλιση εργαζομένων", "ασφαλιση εργαζομενων", "εταιρική ασφάλιση", "εταιρικη ασφαλιση",
    )
    return any(term in text for term in terms)


def mhd_option_unlocked(employee_count: int | None) -> bool:
    return bool(employee_count is not None and employee_count >= MHD_MIN_EMPLOYEES)


def _q(key: str, reply: str, choices: list[tuple[str, str]] | None = None, *, multi: bool = False) -> dict[str, Any]:
    return {
        "key": key,
        "reply": reply,
        "quick_replies": [{"label": label, "value": value} for label, value in (choices or [])],
        "multi_select": multi,
    }


def _parse_count(text: str) -> int | None:
    match = re.search(r"\b(\d{1,5})\b", text or "")
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 100000 else None


def apply_corporate_answer(message: str, state: dict) -> dict[str, Any]:
    pending = state.get("corporate_pending_question")
    text = (message or "").strip()
    low = text.lower()
    out: dict[str, Any] = {"journey": "corporate_group"}

    if pending == "organisation_type":
        out["organisation_type"] = text[:100]
    elif pending == "employee_count":
        count = _parse_count(text)
        if count is None:
            return {}
        out["employee_count"] = count
        out["mhd_option_unlocked"] = mhd_option_unlocked(count)
        if count < MHD_MIN_EMPLOYEES:
            out["mhd_requested"] = False
    elif pending == "company_country":
        out["company_country"] = text[:100]
    elif pending == "employee_countries":
        out["employee_countries"] = text[:500]
    elif pending == "coverage_area":
        mapping = {
            "europe": "Europe", "europe only": "Europe",
            "worldwide excluding usa": "Worldwide excl. USA", "worldwide excl usa": "Worldwide excl. USA",
            "worldwide including usa": "Worldwide incl. USA", "worldwide incl usa": "Worldwide incl. USA",
        }
        out["coverage_area_label"] = mapping.get(low, text[:120])
    elif pending == "benefits":
        selected = []
        for key, label in BENEFITS.items():
            if key.replace("_", " ") in low or label.lower() in low:
                selected.append(key)
        if low in {"all", "all benefits", "όλα", "ολα"}:
            selected = list(BENEFITS)
        if not selected:
            return {}
        out["group_benefits"] = sorted(set(selected))
    elif pending == "pre_existing":
        if low in YES:
            out["pre_existing_requested"] = True
        elif low in NO:
            out["pre_existing_requested"] = False
        else:
            return {}
    elif pending == "mhd":
        if not mhd_option_unlocked(int(state.get("employee_count") or 0)):
            out["mhd_requested"] = False
        elif low in YES or "mhd" in low or "medical history disregarded" in low:
            out["mhd_requested"] = True
        elif low in NO:
            out["mhd_requested"] = False
        else:
            return {}
    elif pending == "existing_scheme":
        if low in YES:
            out["existing_scheme"] = True
        elif low in NO:
            out["existing_scheme"] = False
        else:
            return {}
    elif pending == "current_provider":
        out["current_provider"] = text[:120]
    elif pending == "renewal_date":
        out["renewal_date"] = text[:80]
    elif pending == "start_date":
        out["desired_start_date"] = text[:80]
    elif pending == "census":
        if low in YES:
            out["census_upload_requested"] = True
        elif low in NO:
            out["census_upload_requested"] = False
        else:
            return {}
    else:
        return out

    out["corporate_pending_question"] = None
    return out


def next_corporate_question(state: dict, greek: bool = False) -> dict | None:
    if not state.get("organisation_type"):
        return _q("organisation_type", "What type of organisation is this?", [("Company / SME", "Company / SME"), ("Maritime", "Maritime"), ("Other", "Other")])
    if not state.get("employee_count"):
        return _q("employee_count", "How many employees would you like to insure?", [("1–4", "4"), ("5–19", "5"), ("20–49", "20"), ("50+", "50")])
    if not state.get("company_country"):
        return _q("company_country", "In which country is the company based?")
    if not state.get("employee_countries"):
        return _q("employee_countries", "In which country or countries are the employees based?")
    if not state.get("coverage_area_label"):
        return _q("coverage_area", "What geographical coverage do you want?", [("Europe", "Europe"), ("Worldwide excl. USA", "Worldwide excluding USA"), ("Worldwide incl. USA", "Worldwide including USA")])
    if not state.get("group_benefits"):
        return _q("benefits", "Which benefits are important for the group? You can select several.", [(v, k.replace("_", " ")) for k, v in BENEFITS.items()], multi=True)
    if "pre_existing_requested" not in state:
        return _q("pre_existing", "Do you want us to explore options for pre-existing conditions?", [("Yes", "yes"), ("No", "no")])
    if state.get("pre_existing_requested") and mhd_option_unlocked(int(state.get("employee_count") or 0)) and "mhd_requested" not in state:
        return _q("mhd", "With 5+ employees, HAL can ask Ashlar to explore Medical History Disregarded (MHD). This is subject to insurer rules and approval; it is not guaranteed. Would you like us to include MHD in the enquiry?", [("Explore MHD", "yes"), ("No", "no")])
    if "existing_scheme" not in state:
        return _q("existing_scheme", "Does the company already have a group health scheme?", [("Yes", "yes"), ("No", "no")])
    if state.get("existing_scheme") and not state.get("current_provider"):
        return _q("current_provider", "Who is the current insurer/provider?")
    if state.get("existing_scheme") and not state.get("renewal_date"):
        return _q("renewal_date", "When is the current scheme due for renewal?")
    if not state.get("desired_start_date"):
        return _q("start_date", "When would you like the new group cover to start?")
    if "census_upload_requested" not in state:
        return _q("census", "Would you like to attach a census list? Please include only administrative census data needed for quoting — no diagnoses, medical histories or other clinical information.", [("Upload census", "yes"), ("Continue without file", "no")])
    return None


def group_fact_find_summary(state: dict) -> str:
    benefits = ", ".join(BENEFITS.get(x, x) for x in state.get("group_benefits", [])) or "Not specified"
    lines = [
        f"Organisation: {state.get('organisation_type', 'Not specified')}",
        f"Employees: {state.get('employee_count', 'Not specified')}",
        f"Company country: {state.get('company_country', 'Not specified')}",
        f"Employee countries: {state.get('employee_countries', 'Not specified')}",
        f"Coverage area: {state.get('coverage_area_label', 'Not specified')}",
        f"Benefits: {benefits}",
        f"Pre-existing conditions requested: {'Yes' if state.get('pre_existing_requested') else 'No'}",
        f"MHD exploration: {'Requested — subject to insurer approval' if state.get('mhd_requested') else 'No'}",
        f"Existing scheme: {'Yes' if state.get('existing_scheme') else 'No'}",
        f"Current provider: {state.get('current_provider') or 'N/A'}",
        f"Renewal date: {state.get('renewal_date') or 'N/A'}",
        f"Desired start: {state.get('desired_start_date') or 'Not specified'}",
    ]
    return "\n".join(lines)


def corporate_chat_turn(message: str, state: dict) -> dict[str, Any]:
    state = dict(state or {})
    state["journey"] = "corporate_group"
    updates = apply_corporate_answer(message, state)
    state.update(updates)
    question = next_corporate_question(state)
    if question:
        state["corporate_pending_question"] = question["key"]
        return {
            "reply": question["reply"], "state": state, "quotes": [], "excluded_plans": [],
            "ai_status": "corporate_group_guided_discovery", "journey": "corporate_group",
            "lead_cta": {"show": False, "journey": "corporate_group", "label": "Request a Group Proposal"},
            "open_application_form": False, "quick_replies": question["quick_replies"],
            "multi_select": question.get("multi_select", False),
        }
    state["group_fact_find_summary"] = group_fact_find_summary(state)
    return {
        "reply": "Thanks — I have enough information to prepare your group enquiry. HAL will not calculate a group premium automatically; an Ashlar specialist will review the census, underwriting options and insurer terms.",
        "state": state, "quotes": [], "excluded_plans": [], "ai_status": "corporate_group_fact_find_complete",
        "journey": "corporate_group", "lead_cta": {"show": True, "journey": "corporate_group", "label": "Request a Group Proposal"},
        "open_application_form": True, "quick_replies": [], "group_fact_find_summary": state["group_fact_find_summary"],
        "census_upload_requested": bool(state.get("census_upload_requested")),
    }
