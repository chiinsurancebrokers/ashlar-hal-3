"""Carrier-aware deterministic headline extraction adapted from Proposal Studio."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable


def _number(raw: str) -> float:
    try:
        return float(raw.replace(",", ""))
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


def _clean(text: str) -> str:
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text or "")


def _premium(text: str) -> dict | None:
    patterns = [
        r"(?:final\s+total\s+premium|total\s+annual\s+premium|annual\s+premium|yearly\s+premium|premium\s+per\s+annum|total\s+premium)[^\d€$£A-Z]{0,60}(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
        r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s*(?:annual(?:ly)?|per\s+annum|per\s+year|indicative\s+per\s+year)",
        r"\bpremium\b[^\n\r]{0,45}(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)",
    ]
    candidates = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I | re.S):
            candidates.append((_number(m.group("amt")), m.group("cur"), m.group("amt")))
        if candidates:
            break
    if not candidates:
        return None
    _, cur, amt = max(candidates, key=lambda x: x[0])
    return {"amount": amt.replace(",", ""), "currency": _currency_code(cur), "frequency": "Annual"}


def _area(text: str) -> str | None:
    if re.search(r"worldwide\s+(?:excluding|excl\.?|without)\s+(?:the\s+)?(?:usa|u\.s\.?a?\.?)", text, re.I | re.S):
        return "Worldwide excluding USA"
    if re.search(r"worldwide\s+(?:including|incl\.?)\s+(?:the\s+)?(?:usa|u\.s\.?a?\.?)", text, re.I | re.S):
        return "Worldwide including USA"
    return None


def _deductible(text: str) -> str | None:
    m = re.search(r"(?:deductible|excess)\s*(?:amount)?\s*[:\-]?\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, re.I)
    if not m:
        m = re.search(r"(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s*(?:deductible|excess)", text, re.I)
    if not m:
        return None
    phrase = f"{_pretty_money(m.group('cur'), m.group('amt'))} deductible/excess"
    share = re.search(r"(?P<share>\d{1,3})%\s*(?:cost\s*share|co[- ]?insurance)", text, re.I)
    if share:
        phrase += f"; {share.group('share')}% cost share/co-insurance"
    return phrase


def _annual_limit(text: str) -> str | None:
    pattern = r"(?:annual\s+allowance|annual\s+maximum\s+plan\s+limit|overall\s+annual\s+(?:policy\s+)?maximum|annual\s+overall\s+benefit\s+maximum)[^\d€$£A-Z]{0,80}(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)"
    m = re.search(pattern, text, re.I | re.S)
    return _pretty_money(m.group("cur"), m.group("amt")) if m else None


def generic_quote_facts(text: str) -> dict:
    facts = {"selected_modules": set(), "benefit_hints": {}, "fact_warnings": []}
    if not text:
        return facts
    text = _clean(text)
    premium = _premium(text)
    if premium:
        facts["premium"] = premium
        facts["quote_currency"] = premium["currency"]
    deductible = _deductible(text)
    if deductible:
        facts["deductible_or_excess"] = deductible
    area = _area(text)
    if area:
        facts["area_of_cover"] = area
    annual = _annual_limit(text)
    if annual:
        facts["annual_limit"] = annual
    return facts


def cigna_quote_facts(text: str) -> dict:
    facts = generic_quote_facts(text)
    text = _clean(text)
    m = re.search(r"Quote\s*\d+\s+(?P<plan>Silver|Gold|Platinum)\s+(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)\s+indicative\s+per\s+year", text, re.I | re.S)
    if m:
        facts["premium"] = {"amount": m.group("amt").replace(",", ""), "currency": _currency_code(m.group("cur")), "frequency": "Annual"}
        facts["quoted_plan"] = m.group("plan").title()
    if re.search(r"USA\s*Cover\s*:?\s*Not\s+selected", text, re.I | re.S):
        facts["area_of_cover"] = "Worldwide excluding USA"
    modules = {
        "outpatient": r"International\s+Outpatient\s*:?\s*(?:\n|\r|.){0,180}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
        "evacuation": r"International\s+Medical\s+Evacuation\s*:?\s*(?:\n|\r|.){0,100}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
        "wellbeing": r"International\s+Health\s+(?:&|and)\s+Wellbeing\s*:?\s*(?:\n|\r|.){0,100}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
        "vision_dental": r"International\s+Vision\s+(?:&|and)\s+Dental\s*:?\s*(?:\n|\r|.){0,100}?(?:EUR|USD|GBP|€|\$|£)\s*\d",
    }
    facts["selected_modules"] = {name for name, pattern in modules.items() if re.search(pattern, text, re.I | re.S)}
    return facts


def img_quote_facts(text: str) -> dict:
    return generic_quote_facts(text)


def bupa_quote_facts(text: str) -> dict:
    facts = generic_quote_facts(text)
    text = _clean(text)
    plan = re.search(r"Selected\s+plan\s*:\s*(?P<plan>[A-Za-z][A-Za-z0-9 +\-]{1,40})", text, re.I)
    if plan:
        facts["quoted_plan"] = plan.group("plan").strip().splitlines()[0].strip()
    allowance = re.search(r"Annual\s+allowance\s*:\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, re.I | re.S)
    if allowance:
        facts["annual_limit"] = _pretty_money(allowance.group("cur"), allowance.group("amt"))
    covered = re.search(r"What's\s+covered\s*:\s*(?P<body>.*?)What's\s+not\s+covered\s*:", text, re.I | re.S)
    excluded = re.search(r"What's\s+not\s+covered\s*:\s*(?P<body>.*?)Important\s+documents", text, re.I | re.S)
    cbody = (covered.group("body") if covered else "").casefold()
    ebody = (excluded.group("body") if excluded else "").casefold()
    hints = facts["benefit_hints"]
    if "cancer" in cbody:
        hints["cancer"] = "Cancer treatment is shown as covered in the applicant quote summary."
    if "mental health" in cbody:
        hints["mental_health"] = "Mental health treatment is shown as covered in the applicant quote summary, subject to plan limits and terms."
    for benefit in ("maternity", "dental", "optical"):
        if benefit in ebody:
            hints[benefit] = "Not covered on this quotation."
    return facts


def now_health_quote_facts(text: str) -> dict:
    facts = generic_quote_facts(text)
    text = _clean(text)
    plan = re.search(r"Plan\s+Selected\s*:\s*(?P<plan>SimpleCare\s+(?:CORE|100|250))", text, re.I)
    if plan:
        facts["quoted_plan"] = re.sub(r"\s+", " ", plan.group("plan")).strip()
    premium = re.search(r"Final\s+Total\s+Premium\s*:\s*(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, re.I)
    if premium:
        facts["premium"] = {"amount": premium.group("amt").replace(",", ""), "currency": _currency_code(premium.group("cur")), "frequency": "Annual"}
    uw = re.search(r"Underwriting\s+Basis\s*:\s*(?P<uw>[^\n\r]+)", text, re.I)
    if uw:
        facts["underwriting_basis"] = uw.group("uw").strip()
    annual = re.search(r"Annual\s+Maximum\s+Plan\s+Limit.{0,120}?(?P<cur>EUR|USD|GBP|€|\$|£)\s*(?P<amt>\d[\d,.]*)", text, re.I | re.S)
    if annual:
        facts["annual_limit"] = _pretty_money(annual.group("cur"), annual.group("amt"))
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


ADAPTERS = (
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
