"""Deterministic selected-plan detection adapted from Proposal Studio.

HAL never guesses a plan merely because a brochure mentions it. This first-stage
selector accepts explicit quote fields, broker override, or one plan next to a
selection cue. LLM recovery can be layered on later without weakening this gate.
"""
from __future__ import annotations

import re


_COMMON_TIERS = (
    "Bronze Plus", "Bronze", "Silver", "Gold", "Platinum",
    "Standard Plus", "Standard", "Comprehensive", "Premium",
    "Classic", "Executive Plus", "Executive", "Foundation",
    "SimpleCare 250", "SimpleCare 100", "SimpleCare CORE", "Select",
)


def _explicit_selected_plan(text: str, provider_label: str = "") -> dict | None:
    patterns = [
        r"Selected\s+plan\s*:\s*(?P<plan>Select|SimpleCare\s+(?:CORE|100|250)|Bronze\s+Plus|Bronze|Silver|Gold|Platinum|Executive\s+Plus|Executive|Classic|Standard\s+Plus|Standard)",
        r"Plan\s+Selected\s*:\s*(?P<plan>SimpleCare\s+(?:CORE|100|250)|Select|Silver|Gold|Platinum)",
        r"Quote\s*\d+\s*[|:-]?\s*(?P<plan>Silver|Gold|Platinum)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text or "", flags=re.IGNORECASE)
        if not m:
            continue
        plan = re.sub(r"\s+", " ", m.group("plan")).strip()
        if plan.casefold().startswith("simplecare"):
            suffix = plan.split(" ", 1)[1]
            plan = f"SimpleCare {suffix.upper() if suffix.casefold() == 'core' else suffix}"
        elif plan.casefold() == "select":
            plan = "Select"
        else:
            plan = plan.title()
        return {
            "provider": provider_label or None,
            "plan_name": plan,
            "confidence": "high",
            "evidence": "Explicit selected-plan field in applicant quotation.",
            "other_plans_mentioned": [],
            "method": "rule-based-explicit",
        }
    return None


def _fallback(text: str, provider_label: str = "") -> dict:
    compact = " ".join((text or "").split())
    cue_re = re.compile(
        r"(?:selected\s+plan|plan\s+option|cover\s+level|plan\s+name|quotation\s+for|product\s*[:\-]|tier\s*[:\-]).{0,80}",
        re.IGNORECASE,
    )
    spans = [m.group(0) for m in cue_re.finditer(compact)]
    matches = []
    for tier in _COMMON_TIERS:
        if any(re.search(rf"\b{re.escape(tier)}\b", span, re.IGNORECASE) for span in spans):
            matches.append(tier)
    matches = sorted(set(matches), key=len, reverse=True)
    if len(matches) == 1:
        return {
            "provider": provider_label or None,
            "plan_name": matches[0],
            "confidence": "medium",
            "evidence": "Detected next to a selected-plan/cover-level cue.",
            "other_plans_mentioned": [],
            "method": "rule-based",
        }
    return {
        "provider": provider_label or None,
        "plan_name": None,
        "confidence": "low",
        "evidence": "No single selected plan could be identified safely.",
        "other_plans_mentioned": [
            tier for tier in _COMMON_TIERS if re.search(rf"\b{re.escape(tier)}\b", compact, re.IGNORECASE)
        ],
        "method": "rule-based",
    }


def identify_selected_plan(quotation_text: str, provider_label: str = "", manual_override: str = "") -> dict:
    if manual_override.strip():
        return {
            "provider": provider_label or None,
            "plan_name": manual_override.strip(),
            "confidence": "high",
            "evidence": "Broker supplied target-plan override.",
            "other_plans_mentioned": [],
            "method": "broker_override",
        }
    text = (quotation_text or "").strip()
    if not text:
        return _fallback("", provider_label)
    explicit = _explicit_selected_plan(text, provider_label)
    return explicit if explicit else _fallback(text, provider_label)
