import pytest

from backend.app.services import family_live_orchestrator as live


@pytest.mark.asyncio
async def test_non_family_response_passes_through(monkeypatch):
    async def fake_base(message, state, history):
        return {"state": {"journey": "ipmi", "family_requested": False}, "quotes": [{"premium": 100}]}

    monkeypatch.setattr(live, "base_chat_turn", fake_base)
    result = await live.chat_turn("hello", {}, [])
    assert result["quotes"] == [{"premium": 100}]
    assert "household_quote" not in result


@pytest.mark.asyncio
async def test_incomplete_member_quote_never_exposes_primary_price(monkeypatch):
    family_state = {
        "journey": "ipmi",
        "family_requested": True,
        "household_complete": True,
        "discovery_complete": True,
        "age": 40,
        "coverage_area": "Europe only",
        "household_members": [
            {"member_id": "member-1", "relationship": "spouse", "age": 35, "sex": "female", "maternity_required": True},
            {"member_id": "member-2", "relationship": "child", "age": 8, "sex": "male"},
            {"member_id": "member-3", "relationship": "child", "age": 5, "sex": "female"},
        ],
    }

    async def fake_base(message, state, history):
        return {
            "state": family_state,
            "journey": "ipmi",
            "ai_status": "deterministic_shortlist",
            "quotes": [{"premium": 999}],
            "excluded_plans": [],
        }

    class Eligibility:
        verdict = "ALLOW"
        def model_dump(self, mode="json"):
            return {"verdict": self.verdict}

    async def fake_eligibility(*args, **kwargs):
        return Eligibility()

    monkeypatch.setattr(live, "base_chat_turn", fake_base)
    monkeypatch.setattr(live, "assess_eligibility", fake_eligibility)
    monkeypatch.setattr(live, "quote_shortlist", lambda applicant, settings: [])

    result = await live.chat_turn("done", family_state, [])
    assert result["quotes"] == []
    assert result["household_quote"]["status"] == "personal_family_quotation_required"
    assert result["household_quote"]["member_count"] == 4
    assert result["ai_status"] == "personal_family_quotation_required"


@pytest.mark.asyncio
async def test_live_four_member_family_with_response_level_ipmi_never_leaks_individual_cards(monkeypatch):
    """Regression for the staging journey reproduced on 2026-10-03.

    The base orchestrator can retain journey=undetermined in state while the
    response correctly identifies the completed journey as IPMI. The family
    safeguard must still activate for Chris 51/M + spouse 35/F maternity + two
    children and suppress both the primary price and individual excluded cards.
    """
    family_state = {
        "journey": "undetermined",
        "family_requested": True,
        "household_complete": True,
        "discovery_complete": True,
        "age": 51,
        "sex": "male",
        "residence_country": "Greece",
        "nationality": "Greece",
        "coverage_area": "Europe only",
        "deductible": 0,
        "outpatient_required": True,
        "dental_required": False,
        "mental_health_required": False,
        "wellness_required": True,
        "optical_required": False,
        "evacuation_required": True,
        "household_members": [
            {"member_id": "member-1", "relationship": "spouse", "age": 35, "sex": "female", "maternity_required": True},
            {"member_id": "member-2", "relationship": "child", "age": 5, "sex": "male"},
            {"member_id": "member-3", "relationship": "child", "age": 5, "sex": "female"},
        ],
    }

    async def fake_base(message, state, history):
        return {
            "state": family_state,
            "journey": "ipmi",
            "ai_status": "verified_shortlist",
            "reply": "HAL's top pick is Morgan Price Premium at EUR 5,879.35/year.",
            "quotes": [{"plan_key": "mp-premium", "premium": 5879.35}],
            "excluded_plans": [{"plan_key": "img-bronze", "product_name": "IMG Bronze"}],
        }

    class Eligibility:
        verdict = "ALLOW"
        def model_dump(self, mode="json"):
            return {"verdict": self.verdict}

    async def fake_eligibility(*args, **kwargs):
        return Eligibility()

    monkeypatch.setattr(live, "base_chat_turn", fake_base)
    monkeypatch.setattr(live, "assess_eligibility", fake_eligibility)
    # No verified member-level prices: safe outcome is personal family quote.
    monkeypatch.setattr(live, "quote_shortlist", lambda applicant, settings: [])

    result = await live.chat_turn("No fixed budget", family_state, [])

    assert result["quotes"] == []
    assert result["excluded_plans"] == []
    assert result["ai_status"] == "personal_family_quotation_required"
    assert result["household_quote"]["member_count"] == 4
    assert "5,879.35" not in result["reply"]
    assert "IMG Bronze" not in result["reply"]
    assert "personal family quotation" in result["reply"].lower()
