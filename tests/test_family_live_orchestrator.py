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
        return {"state": family_state, "quotes": [{"premium": 999}], "excluded_plans": []}

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
