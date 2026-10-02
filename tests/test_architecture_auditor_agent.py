from backend.app.core.config import Settings
from backend.app.services.architecture_auditor_agent import audit_architecture


def test_architecture_auditor_passes_or_warns_with_loaded_deterministic_controls():
    result = audit_architecture(Settings())
    assert result.verdict in {"PASS", "WARN"}
    controls = {f.control for f in result.findings}
    assert "rate_registry" in controls
    assert "eligibility_rules" in controls
    assert "deductible_model" in controls


def test_architecture_auditor_warns_when_unconfirmed_deductible_model_enabled():
    result = audit_architecture(Settings(deductible_model_enabled=True))
    assert result.verdict == "WARN"
    assert any(f.control == "deductible_model" and f.severity == "warn" for f in result.findings)
