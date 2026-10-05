"""Residents outside HAL's verified rating area get an honest reply."""


def test_unsupported_residence_gets_honest_reply_not_empty_shortlist():
    import asyncio
    from backend.app.services import family_live_orchestrator as live
    msgs = ["anna", "38", "female", "Portugal", "Same as residence", "british",
            "Europe only", "no", "€500 deductible", "Hospital only", "No", "No maternity needed", "No dental needed",
            "No mental health cover needed", "No wellness cover needed", "No optical cover needed",
            "No evacuation priority", "No fixed budget"]

    async def go():
        st = {"pending_question": "name"}
        for m in msgs:
            r = await live.chat_turn(m, st, [])
            st = r["state"]
        return r
    r = asyncio.run(go())
    assert r["quotes"] == [] and "Here is HAL's shortlist" not in r["reply"]
    assert "residents of Portugal" in r["reply"]
    assert r["followup_message"] == "" and r["lead_cta"]["show"] is True
