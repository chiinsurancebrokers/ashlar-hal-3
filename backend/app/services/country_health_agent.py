"""Country healthcare note written by AI, locked to official OECD evidence.

The AI may phrase the note freely and tailor it to what the applicant asked
for, but it may only use facts from the curated OECD Health at a Glance 2025
evidence file. Every number in the output is checked against that file; if
any figure is not found there, or the text fails the fairness check, HAL
falls back to the deterministic note built from the same evidence.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.knowledge.service import fairness_check
from backend.app.services.anthropic_client import claude_response
from backend.app.services.healthcare_context import _slug, healthcare_note

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge"

_NEED_LABELS = {
    "outpatient_required": "outpatient care", "dental_required": "dental care",
    "maternity_required": "maternity", "mental_health_required": "mental health",
    "wellness_required": "check-ups / screening", "optical_required": "optical",
    "evacuation_required": "medical evacuation", "chronic_required": "chronic conditions",
}


@lru_cache
def load_oecd_evidence(country: str) -> dict | None:
    path = KNOWLEDGE_DIR / f"oecd_hag2025_{_slug(country)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _numbers(text: str) -> set[str]:
    """Normalised numbers in a text: '12,1' -> '12.1', '60.9%' -> '60.9'."""
    found = re.findall(r"\d+(?:[.,]\d+)?", text or "")
    return {n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n for n in found}


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


def build_instructions(evidence: dict, greek: bool, wanted: list[str], household: bool) -> str:
    facts = "\n".join(f"- [p.{f['page']}] {f['text']}" for f in evidence["facts"])
    source = evidence["source_short_el" if greek else "source_short_en"]
    return f"""You are HAL, an insurance adviser at Ashlar Assurance. Write a short note, in {"Greek" if greek else "English"}, about the healthcare system in {evidence["country"]}, where the applicant will live, explaining why international private medical insurance can add value there.

Applicant context: {"a family / household quote" if household else "an individual quote"}; benefits the applicant asked for: {", ".join(wanted) or "in-patient cover"}.

The ONLY facts you may use (official OECD data):
{facts}

Hard rules:
- Use only figures and claims from the list above. Never add any other number, year, ranking or claim.
- Write every percentage exactly as given (in Greek use a decimal comma, e.g. 12,1%).
- Pick the 3-4 facts most relevant to this applicant: prefer the ones about the benefits they asked for (e.g. outpatient, dental, hospital) and about out-of-pocket costs, satisfaction and unmet needs.
- Explain plainly that international cover helps pay for care that in {evidence["country"]} is often paid out of pocket, depending on the plan's benefits. Do not promise that any specific cost is covered.
- Be fair: acknowledge that the public system covers the whole population for core services. Do not disparage it.
- 4-5 sentences, warm and professional, no headings, no bullet points, no markdown.
- End with exactly: "{"Πηγή" if greek else "Source"}: {source}."
"""


async def country_health_note(state: dict, greek: bool, household: bool = False) -> str:
    """AI-written, evidence-locked note; deterministic fallback otherwise."""
    country = state.get("primary_healthcare_country") or state.get("residence_country")
    fallback = healthcare_note(country, greek)
    evidence = load_oecd_evidence(country) if country else None
    if not evidence or not get_settings().anthropic_api_key:
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
