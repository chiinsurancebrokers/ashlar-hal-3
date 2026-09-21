"""Carrier-aware deterministic extraction helpers.

The carrier layer locks applicant-specific headline facts before the LLM is asked
for interpretation. This prevents a carrier-specific quote layout from silently
blanking premium, plan, limit, deductible or area fields.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable


MISSING = {"", "—", "-", "not specified", "not mentioned", "unclear", "null", "none"}


def missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in MISSING
    return False


def _clean_amount_token(raw: str) -> str:
    # Quote prose often ends a monetary amount with sentence punctuation.
    # The extraction regex deliberately accepts "." and "," inside numbers,
    # so trim punctuation that is only trailing prose before numeric parsing.
    return str(raw or "").strip().rstrip(".,")


def _number(raw: str) -> float:
    try:
        return float(_clean_amount_token(raw).replace(",", ""))
    except Exception:
        return -1.0


def _currency_code(token: str) -> str:
    token = token.upper()
    return {"€": "EUR", "$": "USD", "£": "GBP"}.get(token, token)


def _currency_symbol(token: str) -> str:
    token = token.upper()
    return {"EUR": "€", "USD": "$", "GBP": "£", "€": "€", "$": "$", "£": "£"}.get(token, token)


def _pretty_money(cur: str, amt: str) -> str:
    raw = amt.strip()
    if re.fullmatch(r"\d+", raw) and len(raw) > 3:
        raw = f"{int(raw):,}"
    return f"{_currency_symbol(cur)}{raw}"



def _clean_for_matching(text: str) -> str:
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text or "")


def _currency_amount_from_fragment(fragment: str, currency: str = "EUR") -> str | None:
    token = {"EUR": r"(?:EUR|€)", "USD": r"(?:USD|\$)", "GBP": r"(?:GBP|£)"}.get((currency or "EUR").upper(), r"(?:EUR|€)")
    m = re.search(rf"{token}\s*(\d[\d,.]*)", fragment or "", flags=re.IGNORECASE)
    return m.group(1) if m else None

def _premium_from_anchored_patterns(text: str) -> dict | None:
    patterns = [
        r"(?:final\s+total\s+premium|total\s+annual\s+premium|annual\s+premium|yearly\s+premium|premium\s+per\s+annum|total\s+premium)"
        r"[^\d€$£A-Z]{0,60}(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
        r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s*"
        r"(?:annual(?:ly)?|per\s+annum|per\s+year|indicative\s+per\s+year)",
        r"\bpremium\b[^\n\r]{0,45}(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
    ]
    candidates: list[tuple[float, str, str]] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            candidates.append((_number(m.group("amt")), m.group("cur"), m.group("amt")))
        if candidates:
            break
    if not candidates:
        return None
    _, cur, amt = max(candidates, key=lambda x: x[0])
    clean_amount = _clean_amount_token(amt)
    return {"amount": clean_amount.replace(",", ""), "currency": _currency_code(cur), "frequency": "Annual"}


def _generic_area(text: str) -> str | None:
    area_patterns = [
        (r"(?:area\s+of\s+cover|area\s+covered|geographical\s+area|coverage\s+area|area\s+of\s+coverage\s+selected)[^\n\r]{0,100}worldwide\s+(?:excluding|excl\.?|without)\s+(?:the\s+)?(?:usa|u\.s\.?a?\.?)", "Worldwide excluding USA"),
        (r"(?:area\s+of\s+cover|area\s+covered|geographical\s+area|coverage\s+area|area\s+of\s+coverage\s+selected)[^\n\r]{0,100}worldwide\s+(?:including|incl\.?)\s+(?:the\s+)?(?:usa|u\.s\.?a?\.?)", "Worldwide including USA"),
        (r"worldwide\s+(?:excluding|excl\.?|without)\s+(?:the\s+)?(?:usa|u\.s\.?a?\.?)", "Worldwide excluding USA"),
        (r"worldwide\s+(?:including|incl\.?)\s+(?:the\s+)?(?:usa|u\.s\.?a?\.?)", "Worldwide including USA"),
    ]
    for pattern, value in area_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            return value
    return None


def _generic_deductible(text: str) -> str | None:
    m = re.search(
        r"(?:deductible|excess)\s*(?:amount)?\s*[:\-]?\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s*(?:deductible|excess)",
            text,
            flags=re.IGNORECASE,
        )
    if not m:
        return None
    phrase = f"{_pretty_money(m.group('cur'), m.group('amt'))} deductible/excess"
    share = re.search(r"(?P<share>\d{1,3})%\s*(?:cost\s*share|co[- ]?insurance)", text, flags=re.IGNORECASE)
    if share:
        phrase += f"; {share.group('share')}% cost share/co-insurance"
    return phrase


def _generic_annual_limit(text: str) -> str | None:
    patterns = [
        r"(?:annual\s+allowance|annual\s+maximum\s+plan\s+limit|overall\s+annual\s+(?:policy\s+)?maximum|annual\s+overall\s+benefit\s+maximum)"
        r"[^\d€$£A-Z]{0,80}(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return _pretty_money(m.group("cur"), m.group("amt"))
    return None


def generic_quote_facts(text: str) -> dict:
    facts: dict = {}
    if not text:
        return facts
    text = _clean_for_matching(text)
    premium = _premium_from_anchored_patterns(text)
    if premium:
        facts["premium"] = premium
        facts["quote_currency"] = premium["currency"]
    deductible = _generic_deductible(text)
    if deductible:
        facts["deductible_or_excess"] = deductible
    area = _generic_area(text)
    if area:
        facts["area_of_cover"] = area
    annual = _generic_annual_limit(text)
    if annual:
        facts["annual_limit"] = annual
    facts["selected_modules"] = set()
    facts["benefit_hints"] = {}
    facts["fact_warnings"] = []
    return facts


def cigna_quote_facts(text: str) -> dict:
    facts = generic_quote_facts(text)
    if not text:
        return facts
    text = _clean_for_matching(text)
    m = re.search(
        r"Quote\s*\d+\s+(?P<plan>Silver|Gold|Platinum)\s+"
        r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s+indicative\s+per\s+year",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        facts["premium"] = {"amount": m.group("amt").replace(",", ""), "currency": _currency_code(m.group("cur")), "frequency": "Annual"}
        facts["quote_currency"] = facts["premium"]["currency"]
        facts["quoted_plan"] = m.group("plan").title()
    d = re.search(
        r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<ded>\d[\d,.]*)\s*deductible.{0,100}?(?P<share>\d{1,3})%\s*cost\s*share",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if d:
        phrase = f"{_pretty_money(d.group('cur'), d.group('ded'))} deductible; {d.group('share')}% cost share"
        oop = re.search(r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<oop>\d[\d,.]*)\s*out\s+of\s+pocket\s+maximum", text, flags=re.IGNORECASE)
        if oop:
            phrase += f"; {_pretty_money(oop.group('cur'), oop.group('oop'))} out-of-pocket maximum"
        facts["deductible_or_excess"] = phrase
    if re.search(r"USA\s*Cover\s*:?\s*Not\s+selected", text, flags=re.IGNORECASE | re.DOTALL):
        facts["area_of_cover"] = "Worldwide excluding USA"
    selected_modules = set()
    module_patterns = {
        "outpatient": r"International\s+Outpatient\s*:?\s*(?:\n|\r|.){0,180}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
        "evacuation": r"International\s+Medical\s+Evacuation\s*:?\s*(?:\n|\r|.){0,100}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
        "wellbeing": r"International\s+Health\s+(?:&|and)\s+Wellbeing\s*:?\s*(?:\n|\r|.){0,100}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
        "vision_dental": r"International\s+Vision\s+(?:&|and)\s+Dental\s*:?\s*(?:\n|\r|.){0,100}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
    }
    for name, pattern in module_patterns.items():
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            selected_modules.add(name)
    facts["selected_modules"] = selected_modules
    return facts


def img_quote_facts(text: str) -> dict:
    return generic_quote_facts(text)


def bupa_quote_facts(text: str) -> dict:
    facts = generic_quote_facts(text)
    if not text:
        return facts
    text = _clean_for_matching(text)

    plan = re.search(r"Selected\s+plan\s*:\s*(?P<plan>[A-Za-z][A-Za-z0-9 +\-]{1,40})", text, flags=re.IGNORECASE)
    if plan:
        facts["quoted_plan"] = plan.group("plan").strip().splitlines()[0].strip()

    premium = re.search(
        r"Selected\s+plan\s*:\s*[A-Za-z][A-Za-z0-9 +\-]{1,40}?\s+"
        r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s+Annually",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if premium:
        facts["premium"] = {"amount": premium.group("amt").replace(",", ""), "currency": _currency_code(premium.group("cur")), "frequency": "Annual"}
        facts["quote_currency"] = facts["premium"]["currency"]

    allowance = re.search(
        r"Annual\s+allowance\s*:\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if allowance:
        facts["annual_limit"] = _pretty_money(allowance.group("cur"), allowance.group("amt"))

    op = re.search(r"Out[- ]patient\s+deductible\s*:\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, flags=re.IGNORECASE | re.DOTALL)
    other = re.search(r"All\s+other\s+benefits\s+deductible\s*:\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, flags=re.IGNORECASE | re.DOTALL)
    if op or other:
        parts = []
        if op:
            parts.append(f"{_pretty_money(op.group('cur'), op.group('amt'))} outpatient deductible")
        if other:
            parts.append(f"{_pretty_money(other.group('cur'), other.group('amt'))} all-other-benefits deductible")
        facts["deductible_or_excess"] = "; ".join(parts)

    hints = facts.setdefault("benefit_hints", {})
    covered_block = re.search(r"What's\s+covered\s*:\s*(?P<body>.*?)What's\s+not\s+covered\s*:", text, flags=re.IGNORECASE | re.DOTALL)
    excluded_block = re.search(r"What's\s+not\s+covered\s*:\s*(?P<body>.*?)Important\s+documents", text, flags=re.IGNORECASE | re.DOTALL)
    covered = (covered_block.group("body") if covered_block else "").casefold()
    excluded = (excluded_block.group("body") if excluded_block else "").casefold()
    if "admitted" in covered or "hospital" in covered:
        hints["inpatient"] = "Covered according to the applicant quote summary; detailed limits are in the Select Membership Guide."
    if "specialists consultations" in covered or "specialists consultations and gps" in covered:
        hints["outpatient"] = "Specialist consultations and GP care are shown as covered in the applicant quote summary, subject to the Select plan limits."
    if "cancer" in covered:
        hints["cancer"] = "Cancer treatment is shown as covered in the applicant quote summary."
    if "mental health" in covered:
        hints["mental_health"] = "Mental health treatment is shown as covered in the applicant quote summary, subject to plan limits and terms."
    if "medical evacuation" in covered:
        hints["evacuation_repatriation"] = "Medical evacuation in emergencies is shown as covered in the applicant quote summary."
    if "maternity" in excluded:
        hints["maternity"] = "Not covered on this quotation."
    if "dental" in excluded:
        hints["dental"] = "Not covered on this quotation."
    if "optical" in excluded:
        hints["optical"] = "Not covered on this quotation."
    return facts


def now_health_quote_facts(text: str) -> dict:
    facts = generic_quote_facts(text)
    if not text:
        return facts
    text = _clean_for_matching(text)

    plan = re.search(r"Plan\s+Selected\s*:\s*(?P<plan>SimpleCare\s+(?:CORE|100|250))", text, flags=re.IGNORECASE)
    if plan:
        facts["quoted_plan"] = re.sub(r"\s+", " ", plan.group("plan")).strip()

    premium = re.search(r"Final\s+Total\s+Premium\s*:\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, flags=re.IGNORECASE)
    if premium:
        facts["premium"] = {"amount": premium.group("amt").replace(",", ""), "currency": _currency_code(premium.group("cur")), "frequency": "Annual"}
        facts["quote_currency"] = facts["premium"]["currency"]

    uw = re.search(r"Underwriting\s+Basis\s*:\s*(?P<uw>[^\n\r]+)", text, flags=re.IGNORECASE)
    if uw:
        facts["underwriting_basis"] = uw.group("uw").strip()

    deductible = re.search(
        r"In/Day-Patient\s+Annual\s+(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s*Deductible",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not deductible:
        deductible = re.search(
            r"In/Day-Patient\s+Annual.{0,60}?(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s*Deductible",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    if deductible:
        phrase = f"{_pretty_money(deductible.group('cur'), deductible.group('amt'))} in/day-patient annual deductible"
        if re.search(r"Out-Patient\s+Options\s+Selected\s*:\s*No\s+Out-Patient\s+Options", text, flags=re.IGNORECASE | re.DOTALL):
            phrase += "; no optional outpatient excess/co-insurance selected"
        facts["deductible_or_excess"] = phrase

    annual = re.search(
        r"Annual\s+Maximum\s+Plan\s+Limit.{0,120}?(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if annual:
        facts["annual_limit"] = _pretty_money(annual.group("cur"), annual.group("amt"))

    hints = facts.setdefault("benefit_hints", {})
    if re.search(r"Cancer\s+Treatment\s*:\s*Full\s+refund", text, flags=re.IGNORECASE):
        hints["cancer"] = "Full refund, subject to the overall plan maximum and policy terms."
    op = re.search(r"Annual\s+Out-Patient\s+Limit.{0,120}?(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, flags=re.IGNORECASE | re.DOTALL)
    if op:
        hints["outpatient"] = f"Annual outpatient limit {_pretty_money(op.group('cur'), op.group('amt'))}, subject to the quoted benefit schedule."
    evac = re.search(r"Evacuation\s+and\s+Repatriation.{0,1200}?Combined\s+limit\s+of.{0,420}?EUR\s*(?P<amt>\d[\d,.]*)", text, flags=re.IGNORECASE | re.DOTALL)
    if evac:
        hints["evacuation_repatriation"] = f"Evacuation and repatriation combined limit €{evac.group('amt')}."
    psych = re.search(r"Out-Patient\s+Psychiatric\s+Illness(?P<body>.{0,220})", text, flags=re.IGNORECASE | re.DOTALL)
    if psych:
        amt = _currency_amount_from_fragment(psych.group("body"), facts.get("quote_currency", "EUR"))
        if amt:
            hints["mental_health"] = f"Outpatient psychiatric illness up to {_pretty_money(facts.get('quote_currency', 'EUR'), amt)}."
    dental = re.search(r"Dental\s+Care.{0,500}?EUR\s*(?P<amt>\d[\d,.]*).{0,140}?20%\s+co[- ]?insurance", text, flags=re.IGNORECASE | re.DOTALL)
    if dental:
        hints["dental"] = f"Dental care up to €{dental.group('amt')}, subject to 20% co-insurance and the stated waiting period/exclusions."
    if facts.get("annual_limit"):
        hints["inpatient"] = f"In/day-patient cover is included under SimpleCare 250 within the {facts['annual_limit']} overall plan maximum; see the quoted benefit schedule for sub-limits."

    if re.search(r"Routine\s+examinations\s*,?\s*health\s+screening", text, flags=re.IGNORECASE):
        hints["preventive"] = (
            "Not covered — routine examinations and health screening are excluded except where "
            "a benefit is specifically stated in the benefit schedule; no separate wellness benefit is included."
        )

    network = re.search(r"Network\s*:\s*(?P<network>SimpleCare\s+(?:Europe|Comprehensive))", text, flags=re.IGNORECASE)
    if network:
        facts["network"] = network.group("network").strip()
        if facts.get("area_of_cover") == "Worldwide excluding USA" and "europe" in facts["network"].casefold():
            facts.setdefault("fact_warnings", []).append(
                "Applicant quote shows Worldwide excluding USA while the network field reads SimpleCare Europe; verify the intended network with Now Health before presentation."
            )
    return facts


@dataclass(frozen=True)
class CarrierAdapter:
    carrier_id: str
    display_name: str
    aliases: tuple[str, ...]
    extractor: Callable[[str], dict]
    tested_level: str = "framework"
    benefit_strategy: str = "generic"

    def matches(self, value: str) -> bool:
        key = (value or "").casefold()
        return any(alias.casefold() in key for alias in self.aliases)

    def extract_quote_facts(self, text: str) -> dict:
        return self.extractor(text)


ADAPTERS: tuple[CarrierAdapter, ...] = (
    CarrierAdapter("cigna", "Cigna", ("cigna", "cigna global", "cgho"), cigna_quote_facts, "validated", "multi_plan_table"),
    CarrierAdapter("img", "IMG", ("international medical group", "img", "global prima"), img_quote_facts, "validated", "multi_plan_table"),
    CarrierAdapter("bupa", "Bupa", ("bupa", "bupa global", "lifeline", "select global health"), bupa_quote_facts, "validated", "single_plan_guide"),
    CarrierAdapter("now_health", "Now Health", ("now health", "nowhealth", "worldcare", "simplecare", "simple care"), now_health_quote_facts, "validated", "quote_schedule"),
)
GENERIC = CarrierAdapter("generic", "Generic", tuple(), generic_quote_facts, "fallback", "generic")


def get_carrier_adapter(provider_label: str = "", document_text: str = "") -> CarrierAdapter:
    combined = f"{provider_label}\n{document_text[:8000]}"
    for adapter in ADAPTERS:
        if adapter.matches(combined):
            return adapter
    return GENERIC


def carrier_metadata(provider_label: str = "", document_text: str = "") -> dict:
    adapter = get_carrier_adapter(provider_label, document_text)
    return {
        "carrier_id": adapter.carrier_id,
        "carrier_name": adapter.display_name,
        "adapter_level": adapter.tested_level,
        "benefit_strategy": adapter.benefit_strategy,
    }
