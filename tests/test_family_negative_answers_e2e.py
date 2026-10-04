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
    assert result["quotes"] == []  # never an individual premium shown as family price
    top = result["household_quote"]["options"][0]
    assert len(top["allocations"]) == 4

    breakdown = {b["member_id"]: b for b in result["household_breakdown"]}
    assert breakdown["member-1"]["maternity"] is True
    # Declined benefits must never be claimed as requested requirements.
    for word in ("Mental health", "Optical", "Medical evacuation"):
        assert word not in result["reply"]
    # Every member appears with their own price, and the total is their sum.
    assert abs(sum(a["premium"] for a in top["allocations"]) - top["total_premium"]) < 0.01
    for label in ("Chris (51)", "Spouse (35)", "Child 1 (5)", "Child 2 (5)", "Household total"):
        assert label in result["reply"]
