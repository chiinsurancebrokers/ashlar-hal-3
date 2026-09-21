from datetime import date, timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.core.durable_store import configure_store
from backend.app.cases.models import AshlarCase, CaseDocument
from backend.app.cases.store import ServerCaseAnalysisStore, CaseAnalysisRecord, CASE_ANALYSIS_STORE
from backend.app.documents.store import ServerDocumentEvidenceStore, StoredDocumentEvidence, DOCUMENT_EVIDENCE_STORE
from backend.app.proposals.artifacts import ProposalArtifactStore, StoredProposal
from backend.app.api.journey import router
from backend.app.core.config import get_settings


def durable(monkeypatch, tmp_path):
    monkeypatch.setenv('ASHLAR_DB_PATH', str(tmp_path / 'ashlar.sqlite'))
    monkeypatch.setenv('ASHLAR_STORAGE_KEY', Fernet.generate_key().decode())
    def cases():
        return configure_store(ServerCaseAnalysisStore(), attribute='_records', namespace='cases', record_type=CaseAnalysisRecord, key_type=UUID)
    return cases


def test_encrypted_restart_and_stale_writer_protection(monkeypatch, tmp_path):
    factory = durable(monkeypatch, tmp_path)
    first = factory()
    record = first.put(case=AshlarCase(metadata={'sensitive': 'PRIVATE-CLIENT-CONTENT'}), results=[{'premium': None}])
    second = factory()
    restored = second.get(record.case.case_id, record.access_token)
    assert restored.case.metadata['sensitive'] == 'PRIVATE-CLIENT-CONTENT'
    assert second.get(record.case.case_id, 'wrong-token') is None
    restored.case.metadata['changed'] = True
    assert second.save_case(case=restored.case, access_token=record.access_token)
    assert first.save_case(case=record.case, access_token=record.access_token) is None
    assert factory().get(record.case.case_id, record.access_token).case.metadata['changed']
    raw = b''.join(p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    assert b'PRIVATE-CLIENT-CONTENT' not in raw and record.access_token.encode() not in raw
    monkeypatch.setenv('ASHLAR_STORAGE_KEY', Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        factory().get(record.case.case_id, record.access_token)


def test_original_documents_and_rendered_proposals_survive_new_store(monkeypatch, tmp_path):
    durable(monkeypatch, tmp_path)
    def docs():
        return configure_store(ServerDocumentEvidenceStore(), attribute='_records', namespace='documents', record_type=StoredDocumentEvidence)
    def proposals():
        return configure_store(ProposalArtifactStore(), attribute='_items', namespace='proposals', record_type=StoredProposal)
    case = AshlarCase()
    record = docs().put(case_id=case.case_id, case_token='secret-case-token', document=CaseDocument(filename='policy.txt', document_type='policy_schedule'), provider_label='Carrier', target_plan='Plan', role='issued_policy', extracted_text='PRIVATE TERMS', original_bytes=b'\x00\xffPRIVATE ORIGINAL')
    assert docs().get(record.document_ref, case_id=case.case_id, case_token='secret-case-token').original_bytes == b'\x00\xffPRIVATE ORIGINAL'
    assert docs().get(record.document_ref, case_id=case.case_id, case_token='wrong') is None
    token, _ = proposals().put(case=case, report={'review':'required'}, pdf_bytes=b'%PDF-test', pptx_bytes=b'PK-test')
    assert proposals().get(token).pdf_bytes == b'%PDF-test'


def seed_document(record, role, text='CT scan covered subject to pre-authorisation'):
    document = CaseDocument(filename='synthetic.txt', document_type='policy_schedule' if role == 'issued_policy' else role, plan_key='cigna:inspire_elite_care', metadata={'role':role,'pages':1})
    stored = DOCUMENT_EVIDENCE_STORE.put(case_id=record.case.case_id, case_token=record.access_token, document=document, provider_label='Cigna', target_plan='Elite Care', plan_key=document.plan_key, role=role, extracted_text=text, original_bytes=text.encode())
    latest = CASE_ANALYSIS_STORE.get(record.case.case_id, record.access_token)
    latest.case.documents.append(document)
    latest.case.metadata.setdefault('document_refs', {})[stored.document_ref] = str(document.document_id)
    CASE_ANALYSIS_STORE.save_case(case=latest.case, access_token=record.access_token)
    return stored


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings(), 'admin_password', 'test-broker-password')
    app = FastAPI(); app.include_router(router)
    return TestClient(app)


def test_realistic_lifecycle_boundaries_and_carrier_evidence(client):
    plan = 'cigna:inspire_elite_care'
    record = CASE_ANALYSIS_STORE.put(case=AshlarCase(selected_plan_keys=[plan,'img:gpmi_gold']), results=[])
    base = '/journey/' + str(record.case.case_id)
    auth = {'X-Admin-Password':'test-broker-password'}
    def post(path, data=None, broker=False):
        return client.post(base+path, json={'case_token':record.access_token, **(data or {})}, headers=auth if broker else {})
    assert post('/select-plan', {'plan_key':plan,'selected_by':'broker'}).status_code == 403
    assert post('/select-plan', {'plan_key':plan}).status_code == 200
    prepared = post('/application/prepare').json()['payload']
    signed = seed_document(record, 'application')
    for requirement in prepared['blueprint']['requirements']:
        if not requirement['required']: continue
        data={'section':requirement['key'],'note':'Client supplied signed form and broker reviewed requirements','document_refs':[signed.document_ref]}
        if requirement['owner']=='broker':
            assert post('/application/sections/complete',data).status_code==403
        assert post('/application/sections/complete',data,True).status_code==200
    assert post('/application/submit',{'external_reference':'REAL-REF-1'}).status_code==403
    assert post('/application/submit',{'external_reference':'REAL-REF-1'},True).status_code==200
    schedule = seed_document(record,'issued_policy')
    today=date.today()
    issued=post('/policy/issue',{'policy_number':'SYNTHETIC-1','provider':'Cigna','start_date':str(today),'renewal_date':str(today+timedelta(days=365)),'document_refs':[schedule.document_ref]},True)
    assert issued.status_code==200,issued.text
    wallet=client.get(base+'/policy/wallet',params={'case_token':record.access_token}).json()['payload']['wallet']
    assert wallet['verified_benefits']=={} and wallet['terms_status']=='issued_terms_unverified'
    terms={'document_ref':schedule.document_ref,'key':'benefit.ct_scan','value':'Covered subject to pre-authorisation','page':1,'source_quote':'CT scan covered subject to pre-authorisation'}
    assert post('/policy/terms',terms).status_code==403
    assert post('/policy/terms',{**terms,'source_quote':'This was invented'},True).status_code==422
    assert post('/policy/terms',terms,True).status_code==200
    pre=post('/preauthorisations',{'service_key':'ct_scan'}).json()
    assert pre['policy_evidence']['verdict']=='covered'
    pre_id=pre['payload']['preauthorisation']['request_id']
    claim=post('/claims',{'service_date':str(today),'amount':120,'currency':'EUR'}).json()['payload']['claim']
    other=CASE_ANALYSIS_STORE.put(case=AshlarCase(),results=[])
    alien=seed_document(other,'claim')
    transition={'status':'submitted','external_reference':'CL-1','note':'Submitted through carrier portal','document_refs':[signed.document_ref]}
    path='/claims/'+claim['claim_id']+'/transition'
    assert post(path,transition).status_code==403
    assert post(path,{**transition,'document_refs':[alien.document_ref]},True).status_code==422
    assert post(path,transition,True).status_code==200
    assert post(path,{**transition,'status':'paid','paid_amount':100,'currency':'EUR'},True).status_code==409
    assert post(path,{**transition,'status':'approved'},True).status_code==422
    response=seed_document(record,'carrier_response','Approved claim CL-1. Payment EUR 100.')
    decision={**transition,'status':'approved','document_refs':[response.document_ref]}
    assert post(path,decision,True).status_code==200
    assert post(path,{**decision,'status':'paid','paid_amount':100,'currency':'EUR'},True).status_code==200
    assert post('/renewal/start').status_code==200
    assert post('/renewal/start').status_code==422
    workspace=post('/workspace').json()
    assert all(d['metadata']['role']!='carrier_response' for d in workspace['documents'])
    pack=post('/handoff-pack',{'document_refs':[schedule.document_ref]},True)
    assert pack.status_code==200 and pack.content.startswith(b'PK')
    assert post('/documents/'+response.document_ref+'/download').status_code==403
    assert post('/preauthorisations/'+pre_id+'/transition',transition,True).status_code==200


def test_durable_case_is_readable_in_an_independent_process(monkeypatch, tmp_path):
    import subprocess
    import sys
    factory = durable(monkeypatch, tmp_path)
    record = factory().put(case=AshlarCase(metadata={'restart_probe':True}), results=[])
    script = """import sys
from uuid import UUID
from backend.app.cases.store import CASE_ANALYSIS_STORE
record = CASE_ANALYSIS_STORE.get(UUID(sys.argv[1]), sys.argv[2])
assert record and record.case.metadata['restart_probe'] is True
print('restored')
"""
    completed = subprocess.run([sys.executable, '-c', script, str(record.case.case_id), record.access_token], capture_output=True, text=True, check=True)
    assert completed.stdout.strip() == 'restored'


def test_conflict_resolution_rebuilds_proposal_view_and_keeps_provenance(client):
    from backend.app.cases.models import Fact, FactStatus, FactSource, FactSourceType
    source=FactSource(source_type=FactSourceType.CARRIER_QUOTE,source_ref='Synthetic carrier confirmation')
    first=Fact(subject='plan:test:a',plan_key='test:a',key='annual_limit',value='EUR 100',status=FactStatus.VERIFIED,source=source)
    second=Fact(subject='plan:test:a',plan_key='test:a',key='annual_limit',value='EUR 200',status=FactStatus.VERIFIED,source=source)
    record=CASE_ANALYSIS_STORE.put(case=AshlarCase(selected_plan_keys=['test:a'],facts=[first,second]),results=[{'plan_key':'test:a','analysis':{'annual_limit':'stale value'},'focused_rows':[]}])
    base='/journey/'+str(record.case.case_id)
    auth={'X-Admin-Password':'test-broker-password'}
    body={'case_token':record.access_token,'winning_fact_id':str(second.fact_id),'note':'Confirmed against the updated carrier quotation'}
    assert client.post(base+'/conflicts/resolve',json=body).status_code==403
    assert client.post(base+'/conflicts/resolve',json=body,headers=auth).status_code==200
    assert CASE_ANALYSIS_STORE.get(record.case.case_id,record.access_token).case.metadata['proposal_requires_reanalysis']
    rebuilt=client.post(base+'/comparison/reconcile',json={'case_token':record.access_token},headers=auth)
    assert rebuilt.status_code==200
    result=rebuilt.json()['results'][0]['analysis']
    assert result['annual_limit']=='EUR 200'
    assert result['premium']['amount'] is None
    assert result['source_evidence'][0]['fact_id']==str(second.fact_id)
