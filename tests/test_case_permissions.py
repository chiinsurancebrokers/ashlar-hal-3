from backend.app.cases.consent import ConsentGate
from backend.app.cases.models import AshlarCase
from backend.app.cases.store import ServerCaseAnalysisStore


def test_case_store_denies_missing_or_wrong_access_token():
    store = ServerCaseAnalysisStore(ttl_hours=1, max_items=8)
    case = AshlarCase()
    record = store.put(case=case, results=[])

    assert store.get(case.case_id, "") is None
    assert store.get(case.case_id, "wrong-token") is None
    assert store.get(case.case_id, record.access_token) is not None


def test_case_token_is_bound_to_its_own_case():
    store = ServerCaseAnalysisStore(ttl_hours=1, max_items=8)
    first = store.put(case=AshlarCase(), results=[])
    second = store.put(case=AshlarCase(), results=[])

    assert store.get(first.case.case_id, second.access_token) is None
    assert store.get(second.case.case_id, first.access_token) is None

    mutated_second = second.case.model_copy(deep=True)
    mutated_second.metadata["forged"] = True
    assert store.save_case(case=mutated_second, access_token=first.access_token) is None

    untouched = store.get(second.case.case_id, second.access_token)
    assert untouched is not None
    assert "forged" not in untouched.case.metadata


def test_health_context_is_deny_by_default_and_purpose_scoped():
    gate = ConsentGate()

    assert gate.allows("medical_summary", purpose="share_health_to_insurance") is False

    consent = gate.grant(
        purpose="share_health_to_insurance",
        allowed_fields=["medical_summary"],
    )

    assert gate.allows("medical_summary", purpose="share_health_to_insurance") is True
    assert gate.allows("raw_health_history", purpose="share_health_to_insurance") is False
    assert gate.allows("medical_summary", purpose="unrelated_purpose") is False

    gate.revoke(consent.consent_id)
    assert gate.allows("medical_summary", purpose="share_health_to_insurance") is False
