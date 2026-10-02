from backend.app.services.healthcare_context_agent import assess_healthcare_context


def test_healthcare_agent_uses_curated_greece_profile():
    result = assess_healthcare_context("Greece", "en")
    assert result.available is True
    assert result.context.get("metrics")
    assert result.context.get("sources")
    assert result.evidence_quality == "curated_with_sources"


def test_healthcare_agent_fails_closed_for_unknown_country():
    result = assess_healthcare_context("Atlantis", "en")
    assert result.available is False
    assert result.evidence_quality == "unavailable"
    assert result.context.get("metrics") == []
    assert result.cautions
