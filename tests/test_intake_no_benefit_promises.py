from backend.app.services.adviser import build_intake_instructions


def test_intake_prompt_forbids_promising_requested_benefits_are_included():
    instructions = build_intake_instructions({"evacuation_required": True}, False).lower()
    assert "do not invent benefits" in instructions
    assert "deterministic" in instructions
