from backend.app.cases.consent import ConsentGate


def test_health_to_insurance_bridge_is_deny_by_default():
    gate = ConsentGate()
    assert gate.allows("medical_report_summary", purpose="insurance_application") is False


def test_consent_allows_only_explicit_fields_and_purpose():
    gate = ConsentGate()
    record = gate.grant(
        purpose="insurance_application",
        allowed_fields=["medical_report_summary", "current_medications"],
    )

    assert gate.allows("medical_report_summary", purpose="insurance_application") is True
    assert gate.allows("symptom_chat_history", purpose="insurance_application") is False
    assert gate.allows("medical_report_summary", purpose="claims") is False

    gate.revoke(record.consent_id)
    assert gate.allows("medical_report_summary", purpose="insurance_application") is False
