from fastapi.testclient import TestClient
from uuid import UUID
import pytest

from backend.app.main import app
from backend.app.cases.models import AshlarCase
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.core.config import get_settings
from backend.app.evidence.compare_matrix import build_comparison_matrix
from backend.app.evidence.catalogue import catalogue_checklist
from backend.app.agents.document_analyst import _merge_document_analysis

client = TestClient(app, client=("catalogue-tests", 50000))


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_real_catalogue_comparison_no_price_and_persisted_provenance():
    response = client.post('/api/v1/quotes/compare', json={
        'applicant_state': {'age': 45, 'residence_country': 'Greece'},
        'plan_keys': ['img:gpmi_silver', 'cigna:inspire_executive_care'],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(p['premium'] is None for p in body['plans'])
    assert all(p['eligible'] is None for p in body['plans'])
    assert not body['proposal_quality']['can_generate']
    row = next(r for r in body['matrix']['rows'] if r['benefit_code'] == 'routine_dental')
    assert 'Waiting period: 6 months' in row['values']['img:gpmi_silver']
    assert '10% co-insurance' in row['values']['img:gpmi_silver']
    assert row['values']['cigna:inspire_executive_care'] == 'Not confirmed'
    record = CASE_ANALYSIS_STORE.get(UUID(body['case_id']), body['case_token'])
    assert record is not None
    assert not any(f.key == 'premium_amount' for f in record.case.facts)
    dental = next(f for f in record.case.facts if f.key == 'benefit.routine_dental')
    assert dental.source.page == 10
    assert dental.source.source_ref == 'gpmi-brochure (3).pdf'
    assert any(r['analysis']['waiting_periods'] for r in record.results)
    from backend.app.policy.engine import get_policy_engine, PolicyVerdict
    check = get_policy_engine().check_benefit(case=record.case, benefit_key='routine_dental', plan_key='img:gpmi_silver')
    assert check.verdict == PolicyVerdict.UNKNOWN
    assert 'optional' in check.reason.lower()


def test_catalogue_rejects_unknown_and_duplicate_plan_keys():
    for keys in [['img:gpmi_silver', 'madeup:gold'], ['img:gpmi_silver'] * 2]:
        response = client.post('/api/v1/quotes/compare', json={
            'applicant_state': {'age': 45, 'residence_country': 'Greece'}, 'plan_keys': keys})
        assert response.status_code in {400, 422}


def test_unverified_cell_not_promoted_by_other_carrier(monkeypatch):
    import backend.app.evidence.compare_matrix as module
    import backend.app.evidence.catalogue as catalogue
    tables = {
        'a': {'benefits': [{'benefit_code': 'x', 'status': 'verified', 'values': {'silver': '100'}}]},
        'b': {'benefits': [{'benefit_code': 'x', 'status': 'draft', 'values': {'silver': '999'}}]},
    }
    monkeypatch.setattr(module, 'load_carrier_table', lambda carrier: tables.get(carrier))
    monkeypatch.setattr(catalogue, 'load_carrier_table', lambda carrier: tables.get(carrier))
    plans = [dict(plan_key=f'{c}:silver', carrier=c, product_code='silver', insurer=c, product_name='Silver') for c in tables]
    matrix = build_comparison_matrix(plans)
    assert matrix.rows[0].values['b:silver'] == 'Not confirmed'


def upload(role, headers=None):
    case = AshlarCase(selected_plan_keys=['img:gpmi_silver'])
    record = CASE_ANALYSIS_STORE.put(case=case, results=[])
    return client.post('/api/v1/documents/upload', headers=headers or {}, data={
        'case_id': str(case.case_id), 'case_token': record.access_token,
        'provider_label': 'IMG', 'target_plan': 'GPMI Silver', 'role': role,
    }, files={'file': ('policy.txt', b'GPMI Silver policy. Annual limit EUR 3,000,000. Annual premium EUR 2,000.', 'text/plain')})


def test_current_policy_public_but_carrier_uploads_fail_closed(monkeypatch):
    assert upload('existing_policy').status_code == 200
    for role in ['quotation', 'brochure', 'wording']:
        assert upload(role).status_code == 503
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-broker-secret')
    get_settings.cache_clear()
    for role in ['quotation', 'brochure', 'wording']:
        assert upload(role).status_code == 403
        assert upload(role, {'X-Admin-Password': 'wrong'}).status_code == 403
        assert upload(role, {'X-Admin-Password': 'test-broker-secret'}).status_code == 200


def test_optional_benefits_are_not_automatic_matches():
    by_field = {r['field']: r for r in catalogue_checklist('img', 'silver')}
    assert by_field['dental_required']['covered'] is None
    assert by_field['dental_required']['status'] == 'conditional'
    assert by_field['mental_health_required']['covered'] is False


def test_uploaded_quote_can_fill_missing_catalogue_premium():
    base = [{'plan_key': 'cigna:inspire_executive_care', 'analysis': {'premium': {'amount': None, 'currency': 'EUR'}}}]
    result = _merge_document_analysis(base, plan_key=base[0]['plan_key'], role='quotation',
        envelope={'analysis': {'premium': {'amount': 1234, 'currency': 'EUR'}}})
    assert result[0]['analysis']['premium']['amount'] == 1234


def test_catalogue_email_cannot_silently_drop_unpriced_plans():
    from backend.app.services.leads import _verified_plans_for
    with pytest.raises(ValueError, match="broker-reviewed"):
        _verified_plans_for({'age': 45, 'residence_country': 'Greece'},
            ['morgan_price:standard', 'cigna:inspire_executive_care'], get_settings())
