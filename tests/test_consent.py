from backend.app.cases.consent import ConsentGate
from backend.app.cases.models import ConsentRecord, ConsentStatus


def test_health_to_insurance_is_denied_without_explicit_consent():
    gate = ConsentGate()
    assert gate.can_share_health_to_insurance([]) is False


def test_health_to_insurance_requires_active_matching_consent():
    gate = ConsentGate()
    records = [
        ConsentRecord(
            purpose="share_health_to_insurance",
            status=ConsentStatus.GRANTED,
            data_categories=["medical_summary"],
        )
    ]

    assert gate.can_share_health_to_insurance(records, required_category="medical_summary") is True
    assert gate.can_share_health_to_insurance(records, required_category="raw_health_history") is False


def test_revoked_consent_cannot_authorize_transfer():
    gate = ConsentGate()
    records = [
        ConsentRecord(
            purpose="share_health_to_insurance",
            status=ConsentStatus.REVOKED,
            data_categories=["medical_summary"],
        )
    ]

    assert gate.can_share_health_to_insurance(records, required_category="medical_summary") is False
