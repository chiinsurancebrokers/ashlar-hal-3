from datetime import date

from backend.app.services.adviser import (
    clean_applicant_updates, build_intake_instructions, build_explain_plan_instructions,
    build_local_review_instructions, _deterministic_plan_summary, _language_mismatch,
)
from backend.app.services.anthropic_client import build_request_body as build_claude_request_body, build_messages
from backend.app.services.openai_client import build_request_body as build_openai_request_body
from backend.app.schemas.quote import QuoteResult


def test_clean_applicant_updates_rejects_unknown_fields():
    out = clean_applicant_updates({"age": 40, "hack_field": "drop me", "premium": 1})
    assert out == {"age": 40}


def test_clean_applicant_updates_rejects_invalid_coverage_area():
    out = clean_applicant_updates({"coverage_area": "area9"})
    assert "coverage_area" not in out


def test_clean_applicant_updates_type_coerces_and_bounds_age():
    assert clean_applicant_updates({"age": "200"}) == {}
    assert clean_applicant_updates({"age": "45"}) == {"age": 45}


def test_intake_instructions_never_let_llm_calculate_premium_or_eligibility():
    instr = build_intake_instructions({}, greek=False)
    assert "Do not calculate premiums" in instr
    assert "Do not invent benefits" in instr


def test_intake_instructions_discourage_repetitive_acknowledgement_template():
    # Regression: Claude was falling into a repeating "Got it, X noted."
    # template on almost every turn — explicitly told not to.
    instr = build_intake_instructions({}, greek=False)
    assert "repeating template" in instr or "vary your phrasing" in instr.lower()


def test_language_mismatch_guard_catches_greek_when_english_was_requested():
    # Regression: a real reported bug — the comparison conclusion came back
    # in Greek even though the whole conversation was in English, and
    # nothing caught it before it reached the user.
    greek_text = "Το Σχέδιο Α είναι φθηνότερο και περιλαμβάνει εξωνοσοκομειακή περίθαλψη, αλλά δεν καλύπτει οδοντιατρική φροντίδα."
    assert _language_mismatch(greek_text, greek=False) is True


def test_language_mismatch_guard_accepts_correct_english():
    english_text = "Plan A is cheaper and includes outpatient cover from day one, but does not cover dental treatment."
    assert _language_mismatch(english_text, greek=False) is False


def test_language_mismatch_guard_accepts_correct_greek():
    greek_text = "Το Σχέδιο Α είναι φθηνότερο και περιλαμβάνει εξωνοσοκομειακή περίθαλψη, αλλά δεν καλύπτει οδοντιατρική φροντίδα."
    assert _language_mismatch(greek_text, greek=True) is False


def test_language_mismatch_guard_does_not_false_positive_on_short_text():
    assert _language_mismatch("OK.", greek=False) is False


def _sample_quote() -> QuoteResult:
    return QuoteResult(
        insurer="Morgan Price (Europe) ApS", product_code="premium", product_name="Morgan Price Premium",
        eligible=True, base_premium=6868.77, premium=6868.77, currency="EUR",
        rate_version="v", coverage_area_label="Europe", official_rate=True,
        evidence_status="verified", evidence_confidence=1.0, requirements_score=1.0,
        matched_requirements=["Routine maternity"], unmatched_requirements=[],
        verified_facts=["Routine maternity: €7,500 (Table of Benefits p.4)."],
        quoted_on=date(2026, 1, 1), valid_until=date(2026, 1, 31),
    )


def test_explain_plan_instructions_restrict_to_verified_facts_only():
    q = _sample_quote()
    instr = build_explain_plan_instructions(q, greek=False)
    assert "Routine maternity: €7,500" in instr
    assert "Never state a benefit" in instr
    assert "6,868.77" in instr


def test_deterministic_fallback_never_needs_network():
    q = _sample_quote()
    text = _deterministic_plan_summary(q, greek=False)
    assert "6,868.77" in text
    assert "Morgan Price Premium" in text


def test_local_review_instructions_include_never_lose_the_prospect_principle():
    instr = build_local_review_instructions(greek=False)
    assert "opportunity" in instr.lower()


def test_claude_request_body_shape():
    body = build_claude_request_body(instructions="You are HAL.", message="hi", history=None, json_mode=False)
    assert body["system"] == "You are HAL."
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "model" in body and "max_tokens" in body


def test_claude_json_mode_appends_strict_instruction_no_response_format_param():
    # Unlike OpenAI's Responses API, Claude has no structured 'text.format'
    # param — JSON mode is enforced via a strict system-prompt instruction.
    body = build_claude_request_body(instructions="Base.", message="hi", history=None, json_mode=True)
    assert "JSON object only" in body["system"]
    assert "text" not in body


def test_claude_messages_always_start_with_user_even_with_odd_history():
    # A malformed/trimmed history should never produce an invalid
    # assistant-first turn sequence sent to the API.
    history = [{"role": "assistant", "content": "stray leading reply"}, {"role": "user", "content": "ok"}]
    messages = build_messages(history, "next question")
    assert messages[0]["role"] == "user"


def test_openai_client_still_usable_standalone_for_future_deep_analysis():
    # OpenAI is no longer the chat provider, but stays available/tested for
    # the planned deep policy-wording comparison feature.
    body = build_openai_request_body(instructions="x", message="hi", history=None, json_mode=False)
    assert body["store"] is False
