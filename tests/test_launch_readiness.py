import asyncio
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.services.market_shortlist import public_market_shortlist, public_market_exclusions
from backend.app.schemas.applicant import Applicant
from backend.app.services import leads

client = TestClient(app, client=('launch-tests', 50000))


def test_mental_health_excludes_known_gaps_but_not_unknowns():
    applicant = Applicant(age=51, mental_health_required=True)
    plans = {p.plan_key: p for p in public_market_shortlist(applicant, get_settings())}
    assert 'img:gpmi_silver' not in plans
    assert 'img:gpmi_bronze_plus' not in plans
    assert 'img:gpmi_gold' in plans
    assert plans['img:gpmi_gold'].eligible is None
    assert plans['img:gpmi_gold'].eligibility_status == 'requires_carrier_confirmation'
    assert any(e['plan_key'] == 'img:gpmi_silver' for e in public_market_exclusions(applicant, get_settings()))


def test_optional_dental_is_not_a_confirmed_match_or_a_hard_exclusion():
    plans = {p.plan_key: p for p in public_market_shortlist(Applicant(age=40, dental_required=True), get_settings())}
    assert 'Routine dental' in plans['img:gpmi_silver'].unconfirmed_requirements
    assert 'Routine dental' not in plans['img:gpmi_silver'].matched_requirements


def test_legacy_prices_cannot_reenter_public_comparison():
    plans = public_market_shortlist(Applicant(age=40), get_settings())
    assert all(p.premium is None or p.official_rate for p in plans)
    for legacy in ['img:bronze', 'april:international']:
        response = client.post('/api/v1/quotes/compare', json={'applicant_state': {'age':40}, 'plan_keys':[legacy,'morgan_price:standard']})
        assert response.status_code == 400


def test_stale_selection_with_new_needs_is_rejected():
    response = client.post('/api/v1/quotes/compare', json={'applicant_state': {'age':40, 'mental_health_required':True}, 'plan_keys':['img:gpmi_silver','img:gpmi_gold']})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_broker_lead_contains_server_plans_and_needs_not_forged_premium(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'gmail_sender_email', 'sender@example.com')
    monkeypatch.setattr(settings, 'gmail_lead_recipient', 'broker@example.com')
    messages = []
    async def fake_send(message):
        messages.append(message)
        return {'id':'test-only'}
    monkeypatch.setattr(leads, '_send_via_gmail', fake_send)
    result = await leads.send_lead({'first_name':'Test','last_name':'Applicant','email':'test@example.com','consent':True,'plan_keys':['img:gpmi_silver'], 'applicant_state':{'age':40,'outpatient_required':True,'premium':1}})
    assert result['status'] == 'sent'
    body = messages[0].get_body(preferencelist=('plain',)).get_content()
    assert 'GPMI Silver' in body and 'Personal quotation required' in body
    assert 'outpatient_required' in body
    assert messages[0]['To'] == 'broker@example.com'


def test_source_excerpts_require_case_token(monkeypatch):
    monkeypatch.setattr(get_settings(), 'anthropic_api_key', None)
    response = client.post('/api/v1/quotes/compare',json={'applicant_state':{'age':40},'plan_keys':['img:gpmi_gold','img:gpmi_platinum']})
    assert response.status_code == 200
    data=response.json()
    payload={'case_id':data['case_id'],'case_token':'wrong','plan_key':'img:gpmi_gold'}
    assert client.post('/api/v1/quotes/source-evidence',json=payload).status_code == 404
    payload['case_token']=data['case_token']
    evidence=client.post('/api/v1/quotes/source-evidence',json=payload).json()
    assert any(e['source']=='gpmi-brochure (3).pdf' and e['page'] for e in evidence['excerpts'])


def test_production_gate_rejects_process_local_storage(monkeypatch):
    from backend.app.core.durable_store import configure_store
    monkeypatch.delenv('ASHLAR_DB_PATH',raising=False)
    monkeypatch.setenv('ASHLAR_REQUIRE_DURABLE_STORAGE','true')
    with pytest.raises(RuntimeError, match='persistent volume'):
        configure_store(object(), attribute='_records', namespace='test', record_type=dict)


def test_follow_up_questions_are_visible_quick_replies(monkeypatch):
    from backend.app.cases.models import AshlarCase
    from backend.app.cases.store import CASE_ANALYSIS_STORE
    monkeypatch.setattr(get_settings(), 'anthropic_api_key', None)
    record = CASE_ANALYSIS_STORE.put(case=AshlarCase(selected_plan_keys=['img:gpmi_gold','img:gpmi_platinum']), results=[{'target_plan':'GPMI Gold','analysis':{'annual_limit':'EUR 4,000,000','premium':{'amount':None}}}])
    response = client.post('/api/v1/chat/turn', json={'message':'Explain the differences', 'state':{'_adviser_os_case_id':str(record.case.case_id),'_adviser_os_case_token':record.access_token},'history':[]})
    assert response.status_code == 200
    body = response.json()
    assert all(q['label'] and q['value'] for q in body['quick_replies'])
    assert len(body['quick_replies']) == 3
    assert 'Next:' in body['reply'] and 'Still unconfirmed:' in body['reply']
