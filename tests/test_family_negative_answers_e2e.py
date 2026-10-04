"""Regression for the live 4-member family failure (2026-10-04).

Quick-reply values such as "No mental health cover needed" and
"No evacuation priority" were parsed as YES because the yes/no matcher used
substring checks ("needed" in YES; "y" inside "priority"). The household was
then priced against benefits the applicant explicitly declined.
"""
import asyncio

import pytest

from backend.app.discovery.legacy_flow import _polarity, apply_discovery_answer
from backend.app.services import family_live_orchestrator


@pytest.mark.parametrize("answer", [
    "No mental health cover needed", "No optical cover needed", "No evacuation priority",
    "No dental needed", "No maternity needed", "No wellness cover needed", "no", "No",
    "όχι", "δεν χρειάζομαι", "not needed", "don't need it",
])
def test_negative_quick_replies_are_no(answer):
    assert _polarity(answer) is False


@pytest.mark.parametrize("answer", [
    "Yes, dental is important", "Yes, mental health is important", "Yes, evacuation is important",
    "yes", "ναι", "Yes, maternity is required",
])
def test_positive_quick_replies_are_yes(answer):
    assert _polarity(answer) is True


@pytest.mark.parametrize("pending,answer,field", [
    ("mental_health", "No mental health cover needed", "mental_health_required"),
    ("optical", "No optical cover needed", "optical_required"),
    ("evacuation", "No evacuation priority", "evacuation_required"),
    ("dental", "No dental needed", "dental_required"),
    ("wellness", "No wellness cover needed", "wellness_required"),
])
def test_benefit_question_negative_answer_sets_false(pending, answer, field):
    out = apply_discovery_answer(answer, {"pending_question": pending})
    assert out[field] is False
    assert out[f"{pending}_answered"] is True


def test_chronic_greek_negation_is_not_a_disclosure():
    out = apply_discovery_answer("δεν έχω", {"pending_question": "chronic"})
    assert out["chronic_required"] is False
    assert not out.get("chronic_conditions_disclosed")


MESSAGES = [
    "chris", "51", "male", "greece", "Same as residence", "greek", "Europe only",
    "yes", "spouse", "35", "female", "yes",
    "yes", "child", "5", "male",
    "yes", "child", "5", "male", "no",
    "€0 deductible", "Include outpatient cover", "No", "Yes, dental is important",
    "No mental health cover needed", "Yes, wellness is important",
    "No optical cover needed", "No evacuation priority", "No fixed budget",
]


def _run(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from backend.app.core.config import get_settings
    get_settings.cache_clear()

    async def go():
        state = {"pending_question": "name"}
        result = None
        for message in MESSAGES:
            result = await family_live_orchestrator.chat_turn(message, state, [])
            state = result["state"]
        return result

    try:
        return asyncio.run(go())
    finally:
        get_settings.cache_clear()


def test_live_family_scenario_respects_declined_benefits_and_splits_plans(monkeypatch):
    result = _run(monkeypatch)
    state = result["state"]

    assert state["mental_health_required"] is False
    assert state["optical_required"] is False
    assert state["evacuation_required"] is False
    assert state["dental_required"] is True
    assert state["wellness_required"] is True

    assert result["ai_status"] == "verified_household_shortlist"
    top = result["household_quote"]["options"][0]
    assert len(top["allocations"]) == 4

    # Cards are household cards only: one per plan used, priced as the sum of
    # the members on that plan — never one person's price as a family price.
    cards = result["quotes"]
    assert cards and all(c["household_card"] for c in cards)
    assert sum(c["family_size"] for c in cards) == 4
    for card in cards:
        assert abs(card["premium"] - sum(m["premium"] for m in card["household_members"])) < 0.01
    assert abs(sum(c["premium"] for c in cards) - top["total_premium"]) < 0.01
    maternity_card = next(c for c in cards if any(m["maternity"] for m in c["household_members"]))
    assert [m["member_id"] for m in maternity_card["household_members"]] == ["member-1"]

    breakdown = {b["member_id"]: b for b in result["household_breakdown"]}
    assert breakdown["member-1"]["maternity"] is True
    # Declined benefits must never be claimed as requested requirements.
    for word in ("Mental health", "Optical", "Medical evacuation"):
        assert word not in result["reply"]
    # Every member appears with their own price, and the total is their sum.
    assert abs(sum(a["premium"] for a in top["allocations"]) - top["total_premium"]) < 0.01
    for label in ("Chris (51)", "Spouse (35)", "Child 1 (5)", "Child 2 (5)", "Household total"):
        assert label in result["reply"]


def test_lead_email_includes_hal_context():
    from backend.app.services.leads import _build_lead_message

    payload = {
        "insurance_interest": "International Health Insurance", "first_name": "Chris",
        "last_name": "Test", "email": "c@example.com", "consent": True, "message": "",
        "hal_context": {
            "age": 51, "residence_country": "Greece", "coverage_area": "Europe only",
            "needs": {"outpatient_required": True, "dental_required": False, "evacuation_required": True},
            "household_members": [{"relationship": "spouse", "age": 35, "sex": "female", "maternity_required": True}],
            "household_breakdown": [
                {"member_id": "primary", "label": "Chris (51)", "product_name": "Morgan Price Standard Plus",
                 "premium": 2694.72, "currency": "EUR"},
                {"member_id": "member-1", "label": "Spouse (35)", "product_name": "Morgan Price Premium",
                 "premium": 3671.07, "currency": "EUR", "maternity": True},
            ],
        },
    }
    msg = _build_lead_message(payload, "HAL-TEST", "quotes@example.com", "info@example.com")
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    for text in (plain, html):
        assert "Spouse (35)" in text and "Morgan Price Premium" in text
        assert "EUR 6,365.79" in text  # household total
        assert "Medical evacuation" in text
        assert "Declined: Dental" in text


def test_plan_documents_are_plan_specific():
    from backend.app.evidence.morgan_price_2026 import plan_documents

    docs = plan_documents("premium")
    types = [d["type"] for d in docs]
    assert types == ["ipid", "table_of_benefits", "policy_wording"]
    assert "ipid_premium" in docs[0]["url"]
    assert all(d["url"].startswith("https://morgan-price.eu/") for d in docs)
    assert "ipid_standard-plus" in plan_documents("standard_plus")[0]["url"]


def test_household_cards_carry_their_plan_documents(monkeypatch):
    result = _run(monkeypatch)
    for card in result["quotes"]:
        ipid = next(d for d in card["plan_documents"] if d["type"] == "ipid")
        code = card["product_code"].replace("_", "-")
        assert f"ipid_{code}" in ipid["url"]


def test_lead_email_lists_plan_document_links():
    from backend.app.services.leads import _build_lead_message

    url = "https://morgan-price.eu/media/xl0bmfdo/evolutionhealth_eu_ipid_premium_si_04-26.pdf"
    payload = {
        "insurance_interest": "International Health Insurance", "first_name": "A", "last_name": "B",
        "email": "a@example.com", "consent": True,
        "hal_context": {"plan_documents": [
            {"product_name": "Morgan Price Premium", "documents": [{"label": "Plan summary (IPID)", "url": url}]},
            {"product_name": "Bad", "documents": [{"label": "x", "url": "javascript:alert(1)"}]},
        ]},
    }
    msg = _build_lead_message(payload, "HAL-T", "q@example.com", "i@example.com")
    html = msg.get_body(preferencelist=("html",)).get_content()
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert f"href='{url}'" in html and url in plain
    assert "javascript:" not in html and "javascript:" not in plain
