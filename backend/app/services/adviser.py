from __future__ import annotations
import json
import re
from typing import Any

from backend.app.services.anthropic_client import claude_response as adviser_response
from backend.app.schemas.quote import QuoteResult
from backend.app.knowledge.service import fairness_rules, international_vs_local, fairness_check

BOOL_FIELDS = {
    "outpatient_required", "maternity_required", "dental_required", "mental_health_required",
    "wellness_required", "optical_required", "evacuation_required", "chronic_required",
    "chronic_conditions_disclosed", "private_hospital_choice_required", "cross_border_treatment_required",
    "home_country_treatment_required", "continuity_portability_required", "high_annual_limit_required",
    "private_room_required", "direct_billing_required", "second_medical_opinion_required",
}
STRING_FIELDS = {"first_name", "residence_country", "nationality", "client_segment", "journey", "chronic_conditions_note"}
ALLOWED_FIELDS = {"age", "coverage_area", "currency", "deductible", "budget_annual", *BOOL_FIELDS, *STRING_FIELDS}


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
    return {}


def clean_applicant_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Whitelist + type-coerce whatever the LLM extracted. This is the hard
    boundary: nothing outside ALLOWED_FIELDS, and nothing outside its
    expected type, ever reaches the deterministic engine's applicant state."""
    clean: dict[str, Any] = {}
    for key, value in (updates or {}).items():
        if key not in ALLOWED_FIELDS or value is None:
            continue
        if key in BOOL_FIELDS:
            clean[key] = bool(value)
        elif key == "age":
            try:
                v = int(value)
                if 0 <= v <= 120:
                    clean[key] = v
            except Exception:
                pass
        elif key in {"deductible", "budget_annual"}:
            try:
                v = float(value)
                if v >= 0:
                    clean[key] = v
            except Exception:
                pass
        elif key == "coverage_area":
            if value in {"area1", "area2", "area3", "area4"}:
                clean[key] = value
        elif key in STRING_FIELDS:
            clean[key] = str(value)[:200]
    return clean


def _fairness_clause() -> str:
    rules = fairness_rules()
    prohibited = "\n".join(f"  - Never say or imply: {c}" for c in rules["prohibited_claims"])
    required = "\n".join(f"  - Always acknowledge when relevant: {a}" for a in rules["required_acknowledgements"])
    return f"Fairness rules (hard constraints):\n{prohibited}\n{required}"


def build_intake_instructions(state: dict, greek: bool) -> str:
    return f"""You are HAL's applicant-understanding layer for Ashlar Assurance.

Return one JSON object only:
{{"acknowledgement": "one short natural acknowledgement, never a question", "applicant_updates": {{}}}}

Rules:
- Converse in {"Greek" if greek else "English"}.
- acknowledgement must be at most two short sentences.
- Vary your phrasing turn to turn — never fall into a repeating template like
  "Got it, X noted." every time. A real adviser doesn't parrot the same
  three words back on every answer; sound like a person, not a form.
- Do not ask the next insurance question; HAL's deterministic discovery engine does that.
- Do not calculate premiums, decide eligibility, or state which plans are recommended — that is the deterministic engine's job, not yours.
- Do not invent benefits, exclusions, underwriting outcomes or eligibility.
- Extract only facts the applicant actually stated or clearly confirmed.
- Never infer nationality from residence.
- Use only these applicant_updates keys: {", ".join(sorted(ALLOWED_FIELDS))}.

Current state:
{json.dumps(state, ensure_ascii=False)}
"""


async def intake_analysis(message: str, state: dict, history: list[dict] | None, greek: bool) -> dict:
    try:
        text = await adviser_response(
            instructions=build_intake_instructions(state, greek),
            message=message, history=history, json_mode=True, max_tokens=500,
        )
        parsed = _extract_json(text)
        return {
            "acknowledgement": str(parsed.get("acknowledgement", "") or "").strip(),
            "applicant_updates": clean_applicant_updates(parsed.get("applicant_updates", {})),
        }
    except Exception:
        return {"acknowledgement": "", "applicant_updates": {}}


def build_explain_plan_instructions(quote: QuoteResult, greek: bool) -> str:
    """The ONLY facts this prompt is allowed to state about the plan are the
    ones explicitly listed below, all sourced from the evidence layer. It
    cannot see the internet, training data, or "general knowledge" about
    this insurer — only this list."""
    facts = "\n".join(f"- {f}" for f in quote.verified_facts) or "- (no additional verified facts loaded for this plan)"
    return f"""You are HAL, explaining ONE specific insurance plan to an applicant, in {"Greek" if greek else "English"}.

Plan: {quote.insurer} — {quote.product_name}
Annual premium: {quote.currency} {quote.premium:,.2f}
Matched requirements (verified): {", ".join(quote.matched_requirements) or "none selected"}
Unmatched requirements (verified): {", ".join(quote.unmatched_requirements) or "none"}

The ONLY verified facts about this plan you may state:
{facts}

Hard rules:
- Never state a benefit, limit, waiting period or exclusion that is not in the verified facts list above.
- If asked about something not in that list, say it is not confirmed in the loaded policy evidence rather than guessing.
- Do not restate the premium as anything other than the figure given above.
- Keep the explanation warm, concise, advisory — 3-5 sentences.

{_fairness_clause()}
"""


async def explain_plan(quote: QuoteResult, question: str, greek: bool) -> str:
    try:
        text = await adviser_response(instructions=build_explain_plan_instructions(quote, greek), message=question, max_tokens=400)
        flags = fairness_check(text)
        if flags:
            # Fail closed to a safe deterministic fallback rather than ever
            # surface a flagged claim to a client.
            return _deterministic_plan_summary(quote, greek)
        return text
    except Exception:
        return _deterministic_plan_summary(quote, greek)


def _deterministic_plan_summary(quote: QuoteResult, greek: bool) -> str:
    facts = "; ".join(quote.verified_facts[:3])
    if greek:
        return f"{quote.product_name} ({quote.insurer}): {quote.currency} {quote.premium:,.2f}/έτος. {facts}"
    return f"{quote.product_name} ({quote.insurer}): {quote.currency} {quote.premium:,.2f}/year. {facts}"


def build_comparison_conclusion_instructions(matrix_rows: list[dict], plan_labels: dict[str, str], greek: bool) -> str:
    """Mirrors the 'Σύντομο Συμπέρασμα' pattern from the Ashlar comparison
    PDF: 1-3 short bullet points summarising genuine trade-offs. The ONLY
    facts available are the matrix rows passed in — never general knowledge
    about these insurers."""
    labels = "\n".join(f"- {k}: {v}" for k, v in plan_labels.items())
    rows_text = "\n".join(
        f"- {r['label']}: " + "; ".join(f"{plan_labels.get(k, k)}={v}" for k, v in r["values"].items())
        for r in matrix_rows
    ) or "(no comparable verified benefit rows)"

    return f"""You are HAL, writing a short comparison conclusion.

Write ENTIRELY in {"Greek" if greek else "English"} — every single word, including
if any of the data below happens to contain the other language. Never mix
languages and never switch language mid-response, in the style of:
"Plan A is cheaper and includes X from day one, but has a lower outpatient limit and no Y."
"Plan B has a materially higher overall limit and includes Z, but does not cover W at this tier."

Plans being compared:
{labels}

The ONLY verified data you may reference:
{rows_text}

Hard rules:
- 2-3 short sentences maximum, one genuine trade-off framing per plan.
- Never state a number, benefit or limit not present in the data above.
- If a row says "Not confirmed" for a plan, either omit it or say explicitly that it is not confirmed for that plan — never guess a value.
- No sales pressure, no superlatives beyond what the data supports.

{_fairness_clause()}
"""


def _language_mismatch(text: str, greek: bool) -> bool:
    """Defensive guard: the model is instructed to answer in one language,
    but occasionally slips into the other (e.g. pulled by non-English data
    embedded in the prompt). Never ship a mismatched response silently."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 20:
        return False  # too short to judge reliably
    greek_letters = sum(1 for c in letters if "\u0370" <= c <= "\u03ff" or "\u1f00" <= c <= "\u1fff")
    greek_ratio = greek_letters / len(letters)
    if greek and greek_ratio < 0.3:
        return True   # asked for Greek, got mostly non-Greek
    if not greek and greek_ratio > 0.15:
        return True   # asked for English, got meaningfully Greek text
    return False


async def comparison_conclusion(matrix_rows: list[dict], plan_labels: dict[str, str], greek: bool) -> str:
    try:
        text = await adviser_response(
            instructions=build_comparison_conclusion_instructions(matrix_rows, plan_labels, greek),
            message="Write the comparison conclusion.", max_tokens=300,
        )
        if fairness_check(text) or _language_mismatch(text, greek):
            return _deterministic_comparison_conclusion(matrix_rows, plan_labels, greek)
        return text
    except Exception:
        return _deterministic_comparison_conclusion(matrix_rows, plan_labels, greek)


def _deterministic_comparison_conclusion(matrix_rows: list[dict], plan_labels: dict[str, str], greek: bool) -> str:
    """Network-free fallback: purely mechanical, but still never invents
    anything — it only ever restates rows that are already in the matrix."""
    if not matrix_rows or len(plan_labels) < 2:
        return ("Δεν υπάρχουν αρκετά επαληθευμένα στοιχεία για σύγκριση αυτή τη στιγμή."
                if greek else "There isn't enough verified data to compare these plans yet.")
    keys = list(plan_labels.keys())
    parts = []
    for key in keys:
        confirmed = [r["label"] for r in matrix_rows if r["values"].get(key, "Not confirmed") != "Not confirmed"]
        if confirmed:
            sample = ", ".join(confirmed[:3])
            parts.append((f"{plan_labels[key]}: επιβεβαιωμένη κάλυψη σε {sample}." if greek
                           else f"{plan_labels[key]}: verified cover confirmed for {sample}."))
    return " ".join(parts) or ("Επαληθεύστε τα στοιχεία στον πίνακα παρακάτω." if greek else "Please review the table below for verified details.")


def build_local_review_instructions(greek: bool) -> str:
    playbook = international_vs_local()["local_review_playbook"]
    steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(playbook["steps"]))
    return f"""You are HAL. The applicant has asked about LOCAL (domestic-only) health insurance.

Guiding principle: {playbook['principle']}

Follow this playbook:
{steps}

{_fairness_clause()}

Converse in {"Greek" if greek else "English"}. Keep it to 3-5 sentences and end with a genuine question about what matters most to them (price, Greece-only cover, private hospital access, family cover, etc.) — do not lecture.
"""
