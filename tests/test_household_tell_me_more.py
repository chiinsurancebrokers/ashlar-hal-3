"""Regression (staging 2026-10-04): "Tell me more" on a household card quoted
only the primary applicant's premium (EUR 2,694.72) instead of the card's
household total (EUR 3,647.71 for Chris 51 + Child 5)."""
import asyncio

from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.services import family_live_orchestrator as live

MESSAGES = [
    "chris", "51", "male", "greece", "Same as residence", "greek", "Europe only", "yes",
    "spouse", "45", "female", "yes", "yes", "child", "24", "female", "yes",
    "yes", "child", "5", "male", "no",
    "€0 deductible", "Include outpatient cover", "No", "No dental needed",
    "No mental health cover needed", "Yes, wellness is important", "No optical cover needed",
    "Yes, evacuation is important", "No fixed budget",
]


def _family(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    async def go():
        state, result = {"pending_question": "name"}, None
        for m in MESSAGES:
            result = await live.chat_turn(m, state, [])
            state = result["state"]
        return result
    return asyncio.run(go())


def test_tell_me_more_uses_household_card_premium(monkeypatch):
    result = _family(monkeypatch)
    cards = result["quotes"]
    assert len(cards) == 2
    client = TestClient(app)
    for card in cards:
        ids = [m["member_id"] for m in card["household_members"]]
        response = client.post("/api/v1/quotes/explain", json={
            "applicant_state": result["state"], "plan_key": card["plan_key"],
            "household_member_ids": ids, "language": "en",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert abs(body["premium"] - card["premium"]) < 0.01
        assert f"{card['premium']:,.2f}" in body["answer"]
        assert len(body["household_lines"]) == len(ids)
        for member in card["household_members"]:
            assert any(member["label"] in line and f"{member['premium']:,.2f}" in line
                       for line in body["household_lines"])
        assert any("ipid" in url for url in body["source_documents"])
    get_settings.cache_clear()


def test_tell_me_more_rejects_unknown_member(monkeypatch):
    result = _family(monkeypatch)
    card = result["quotes"][0]
    response = TestClient(app).post("/api/v1/quotes/explain", json={
        "applicant_state": result["state"], "plan_key": card["plan_key"],
        "household_member_ids": ["member-99"],
    })
    assert response.status_code == 404
    get_settings.cache_clear()


def test_individual_tell_me_more_unchanged(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    state = {"age": 51, "sex": "male", "residence_country": "Greece", "nationality": "Greece",
             "coverage_area": "area1", "deductible": 0, "outpatient_required": True}
    response = TestClient(app).post("/api/v1/quotes/explain", json={
        "applicant_state": state, "plan_key": "morgan_price:standard_plus"})
    assert response.status_code == 200, response.text
    assert response.json()["household_lines"] == []
    get_settings.cache_clear()


def test_ai_explanation_with_wrong_premium_falls_back(monkeypatch):
    from backend.app.services import adviser

    async def fake_ai(**kwargs):
        assert "Household members on this plan" in kwargs["instructions"]
        return "This plan costs EUR 2,694.72 per year and covers outpatient care."

    monkeypatch.setattr(adviser, "adviser_response", fake_ai)
    result = _family(monkeypatch)
    card = next(c for c in result["quotes"] if c["family_size"] > 1)
    response = TestClient(app).post("/api/v1/quotes/explain", json={
        "applicant_state": result["state"], "plan_key": card["plan_key"],
        "household_member_ids": [m["member_id"] for m in card["household_members"]],
    })
    answer = response.json()["answer"]
    assert f"{card['premium']:,.2f}" in answer
    assert answer != "This plan costs EUR 2,694.72 per year and covers outpatient care."
    get_settings.cache_clear()
