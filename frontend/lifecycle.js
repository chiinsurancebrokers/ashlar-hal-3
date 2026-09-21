/* Case-bound client and broker workspace. Credentials remain in this tab only. */
(() => {
  'use strict';
  const api = '/api/v1';
  const broker = new URLSearchParams(location.search).get('workspace') === 'broker';
  let access = null, snapshot = null, password = '';
  const el = (tag, text, parent) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  };
  const style = el('style', `
    #ashlarLifecycleOpen{position:fixed;left:16px;bottom:16px;z-index:900;padding:10px 16px;border-radius:22px;background:#164b47;color:white;border:0;box-shadow:0 2px 10px #0003}
    #ashlarLifecycle{width:min(920px,94vw);max-height:90vh;border:1px solid #c9d9d5;border-radius:16px;padding:22px;color:#203d3a;background:#fafcfb}
    #ashlarLifecycle::backdrop{background:#102b2866} #ashlarLifecycle button{cursor:pointer;padding:8px 12px;margin:5px;border:1px solid #aac4bd;border-radius:7px;background:white;color:#164b47}
    #ashlarLifecycle label{display:flex;flex-direction:column;gap:4px;margin:9px 0;font-size:13px} #ashlarLifecycle input,#ashlarLifecycle textarea,#ashlarLifecycle select{padding:9px;border:1px solid #b8cbc5;border-radius:6px;font:inherit;max-width:100%;box-sizing:border-box}
    #ashlarLifecycle details{border-top:1px solid #d7e2de;padding:14px 0} #ashlarLifecycle summary{font-weight:700;cursor:pointer} #ashlarLifecycle pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#edf3f0;padding:12px}
    #ashlarLifecycle .life-error{color:#a13228} #ashlarLifecycle .life-status{color:#47645c;font-size:13px} #ashlarLifecycle h3{margin-bottom:8px}
  `, document.head);
  const open = el('button', 'My Ashlar case', document.body);
  open.id = 'ashlarLifecycleOpen';
  const dialog = el('dialog', undefined, document.body); dialog.id = 'ashlarLifecycle';
  const title = el('h2', broker ? 'Broker case workspace' : 'My Ashlar case', dialog);
  const close = el('button', 'Close', dialog); close.onclick = () => dialog.close();
  const status = el('p', '', dialog); status.className = 'life-status'; status.setAttribute('role', 'status');
  const body = el('div', undefined, dialog);
  function field(parent, label, type = 'text', value = '') {
    const wrap = el('label', label, parent);
    const input = el(type === 'textarea' ? 'textarea' : 'input', undefined, wrap);
    if (type !== 'textarea') input.type = type;
    input.value = value ?? ''; input.required = true;
    return input;
  }
  function choices(parent, label, options) {
    const wrap = el('label', label, parent), select = el('select', undefined, wrap);
    for (const [value, text] of options) { const option = el('option', text, select); option.value = value; }
    return select;
  }
  function section(name) { const d = el('details', undefined, body); el('summary', name, d); return d; }
  function button(parent, label, run) {
    const b = el('button', label, parent); b.type = 'button';
    b.onclick = async () => { b.disabled = true; status.textContent = ''; status.className = 'life-status'; try { await run(); } catch (e) { status.textContent = e.message; status.className = 'life-error'; } finally { b.disabled = false; } };
    return b;
  }
  function form(parent, label, run) {
    const f = el('form', undefined, parent), b = el('button', label, f); b.type = 'submit';
    f.onsubmit = async e => { e.preventDefault(); b.disabled = true; status.textContent = ''; try { await run(); status.className = 'life-status'; } catch (err) { status.textContent = err.message; status.className = 'life-error'; } finally { b.disabled = false; } };
    return f;
  }
  async function request(path, payload = {}, binary = false) {
    if (!access) throw new Error('Open a comparison or restore your case access file first.');
    const response = await fetch(api + '/journey/' + encodeURIComponent(access.case_id) + path, {method:'POST', headers:{'Content-Type':'application/json', ...(broker && password ? {'X-Admin-Password':password} : {})}, body:JSON.stringify({case_token:access.case_token, ...payload})});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the fields and try again.'); }
    return binary ? response.blob() : response.json();
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob), a = el('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function updateAccess() {
    if (typeof state === 'object' && state._adviser_os_case_id && state._adviser_os_case_token) { if(access?.case_id!==state._adviser_os_case_id) snapshot=null; access = {case_id:state._adviser_os_case_id, case_token:state._adviser_os_case_token}; }
  }
  async function refresh() { snapshot = await request('/workspace'); render(); }
  function docOptions(parent) {
    return choices(parent, 'Evidence document', [['', 'Choose an uploaded document'], ...snapshot.documents.flatMap(d => (d.refs || []).map(ref => [ref, d.filename + ' — ' + d.document_type]))]);
  }
  function render() {
    body.replaceChildren();
    if (broker) {
      const auth = field(body, 'Broker password (kept in this tab)', 'password', password); auth.autocomplete = 'current-password';
      auth.onchange = () => { password = auth.value; document.dispatchEvent(new CustomEvent("ashlar:broker-password", {detail:password})); };
      button(body, 'Unlock / refresh broker workspace', refresh);
    }
    const restore = section('Save or restore case access');
    el('p', 'Your access file opens this case. Keep it private. It contains no broker password.', restore);
    button(restore, 'Save private access file', () => { if (!access) throw new Error('No case selected.'); download(new Blob([JSON.stringify(access)], {type:'application/json'}), 'ashlar-case-access.json'); });
    const upload = field(restore, 'Restore access file', 'file'); upload.accept = '.json';
    upload.onchange = async () => { try { const data = JSON.parse(await upload.files[0].text()); if (!/^[0-9a-f-]{36}$/i.test(data.case_id) || typeof data.case_token !== 'string' || data.case_token.length < 20 || data.case_token.length > 256) throw new Error('Invalid access file.'); access = {case_id:data.case_id, case_token:data.case_token}; if (typeof state === 'object') { state._adviser_os_case_id = access.case_id; state._adviser_os_case_token = access.case_token; } document.dispatchEvent(new CustomEvent('ashlar:restore-case', {detail:access})); await refresh(); } catch (e) { status.textContent = e.message; } };
    if (!snapshot) { el('p', 'Create a plan comparison in HAL or restore an existing case.', body); return; }
    el('p', 'Case ' + snapshot.case_id + ' · ' + snapshot.status, body);
    if(snapshot.storage !== 'encrypted_sqlite') el('p','Temporary staging storage: cases and documents can be lost on restart. Keep original documents.',body);
    const docs = section('Documents');
    for (const doc of snapshot.documents) for (const ref of doc.refs || []) { button(docs, doc.filename, async () => download(await request('/documents/' + encodeURIComponent(ref) + '/download', {}, true), doc.filename)); if(['application','claim','preauthorisation','carrier_response','issued_policy'].includes(doc.metadata?.role)) button(docs,'Review '+doc.filename,async()=>{const review=await request('/documents/'+encodeURIComponent(ref)+'/analyse');el('p','Extracted candidates — require human verification',docs);el('pre',review.excerpt,docs);el('p','Amounts found: '+review.candidate_amounts.join(', '),docs);el('p','Dates found: '+review.candidate_dates.join(', '),docs);}); }
    let role, file, label;
    const df = form(docs, 'Upload document', async () => {
      if (!file.files[0]) throw new Error('Choose a document.');
      const payload = new FormData(); payload.append('case_id', access.case_id); payload.append('case_token', access.case_token); payload.append('role', role.value); payload.append('provider_label', snapshot.policy?.provider || 'Selected carrier'); payload.append('target_plan', snapshot.selected_plan_key || 'Current policy');
      if (snapshot.selected_plan_key) payload.append('plan_key', snapshot.selected_plan_key);
      payload.append('file', file.files[0]);
      const response = await fetch(api + '/documents/upload', {method:'POST', headers:broker && password ? {'X-Admin-Password':password} : {}, body:payload});
      const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Upload failed.');
      await refresh(); status.textContent = 'Document saved. Its contents are not automatically verified.';
    });
    role = choices(df, 'Document purpose', [['existing_policy','Your existing policy'],['application','Application / signed form'],['claim','Claim evidence'],['preauthorisation','Pre-authorisation evidence'],...(broker ? [['issued_policy','Issued policy schedule'],['carrier_response','Carrier response / payment receipt'],['wording','Policy wording']] : [])]);
    file = field(df, 'PDF, TXT or HTML', 'file'); file.accept = '.pdf,.txt,.html,.htm';
    if (broker) button(docs, 'Download broker handoff pack', async () => download(await request('/handoff-pack', {document_refs:snapshot.documents.flatMap(d => d.refs || [])}, true), 'ashlar-handoff.zip'));
    const app = section('14 · Application');
    if (!snapshot.application) button(app, 'Prepare application for selected plan', async () => { await request('/application/prepare'); await refresh(); });
    else {
      el('p', snapshot.blueprint?.note || 'Carrier forms and requirements need broker verification.', app);
      el('p', 'Status: ' + snapshot.application.status, app);
      for (const key of snapshot.application.required_sections) {
        const spec = (snapshot.blueprint?.requirements || []).find(r => r.key === key) || {label:key};
        el('h3', spec.label + (snapshot.application.completed_sections.includes(key) ? ' ✓' : ''), app);
        if (snapshot.application.status === 'submitted' || (spec.owner === 'broker' && !broker)) { el('p', spec.owner === 'broker' ? 'Broker section' : 'Submitted', app); continue; }
        let note, document;
        const f = form(app, 'Record section evidence', async () => { await request('/application/sections/complete', {section:key,note:note.value,document_refs:document.value ? [document.value] : []}); await refresh(); });
        note = field(f, 'Information supplied / evidence reviewed', 'textarea', snapshot.application.section_data?.[key]?.note);
        document = docOptions(f);
        if (spec.requires_signature) el('p', 'Attach the signed application; typing a name here does not create a signature.', f);
      }
      if (broker && snapshot.application.status === 'ready') {
        let ref; const f = form(app, 'Record external submission', async () => { await request('/application/submit', {external_reference:ref.value}); await refresh(); }); ref = field(f, 'Actual carrier submission reference');
        el('p', 'Send through the carrier’s approved channel first. This action records that submission.', f);
      }
    }
    if (broker && snapshot.application?.status === 'submitted') {
      const issue = section('15 · Record issued policy'); let number, provider, start, end, document;
      const f = form(issue, 'Record carrier issuance', async () => { await request('/policy/issue', {policy_number:number.value,provider:provider.value,start_date:start.value,renewal_date:end.value,document_refs:document.value ? [document.value] : []}); await refresh(); });
      number = field(f, 'Policy number'); provider = field(f, 'Carrier'); start = field(f, 'Start date', 'date'); end = field(f, 'Renewal date', 'date'); document = docOptions(f);
    }
    if (snapshot.policy) {
      const wallet = section('16 · Policy Wallet');
      el('p', snapshot.policy.provider + ' · ' + snapshot.policy.policy_number + ' · renewal ' + snapshot.policy.renewal_date, wallet);
      button(wallet, 'Load verified issued terms', async () => { const data = await request('/policy/wallet'); const w = data.payload.wallet; el('p', w.terms_status === 'issued_terms_unverified' ? 'Issued terms still require broker reconciliation. Brochure benefits are not treated as your issued cover.' : 'Reconciled issued terms', wallet); el('pre', JSON.stringify({core:w.core_facts,benefits:w.verified_benefits,conflicts:w.unresolved_conflicts},null,2), wallet); });
      if (broker) {
        let document,key,value,page,quote; const f = form(wallet,'Verify an issued term',async()=>{await request('/policy/terms',{document_ref:document.value,key:key.value,value:value.value,page:Number(page.value),source_quote:quote.value});await refresh();});
        document=docOptions(f);key=field(f,'Fact key, e.g. annual_limit or benefit.ct_scan');value=field(f,'Exact value including restrictions','textarea');page=field(f,'Source page','number','1');page.min='1';quote=field(f,'Verbatim source passage','textarea');
      }
      const health=section('17 · Health navigation');
      if(snapshot.health_navigation.url){const a=el('a','Open Asklepios',health);a.href=snapshot.health_navigation.url;a.target='_blank';a.rel='noopener noreferrer';}
      else el('p','Asklepios connection has not been configured.',health);
      el('p','Health navigation takes place in Asklepios. Case details and clinical documents are not sent automatically.',health);
      for (const [kind,heading] of [['preauthorisations','18 · Pre-authorisation'],['claims','19 · Claims']]) {
        const area=section(heading);let service,amount,currency,day,note,doc;
        const f=form(area,'Open draft',async()=>{const payload=kind==='claims'?{service_date:day.value||null,amount:amount.value?Number(amount.value):null,currency:currency.value||null,note:note.value||null}:{service_key:service.value,planned_date:day.value||null};payload.document_refs=doc.value?[doc.value]:[];await request('/'+kind,payload);await refresh();});
        if(kind==='claims'){amount=field(f,'Claimed amount','number');amount.required=false;amount.min='0';amount.step='0.01';currency=field(f,'Currency','text','EUR');note=field(f,'Claim notes','textarea');note.required=false;}else service=field(f,'Benefit/service key, e.g. ct_scan');
        day=field(f,kind==='claims'?'Service date':'Planned date','date');day.required=false;doc=docOptions(f);
        for(const item of snapshot[kind]) {
          const id=item.claim_id||item.request_id;el('h3',(item.service_key||'Claim')+' · '+item.status,area);
          for(const event of item.events||[])el('p',event.at+' · '+event.to+' · '+event.reference,area);
          if(!broker)continue;
          const available=kind==='claims'?{draft:['submitted'],submitted:['info_required','approved','partially_approved','declined'],info_required:['submitted'],approved:['paid'],partially_approved:['paid']}:{draft:['submitted'],submitted:['pending','approved','partially_approved','declined'],pending:['approved','partially_approved','declined']};
          if(!available[item.status])continue;
          let next,ref,notes,evidence,paid,cur;const tf=form(area,'Record carrier action / response',async()=>{await request('/'+kind+'/'+id+'/transition',{status:next.value,external_reference:ref.value,note:notes.value,document_refs:evidence.value?[evidence.value]:[],paid_amount:paid.value?Number(paid.value):null,currency:cur.value||null});await refresh();});
          next=choices(tf,'New status',available[item.status].map(x=>[x,x]));ref=field(tf,'Carrier reference');notes=field(tf,'What the carrier confirmed','textarea');evidence=docOptions(tf);paid=field(tf,'Paid amount (only for paid status)','number');paid.required=false;paid.step='0.01';paid.min='0';cur=field(tf,'Payment currency','text','EUR');cur.required=false;
        }
      }
      const renewal=section('20 · Renewal');el('p','Renewal in '+snapshot.renewal_due_days+' days. Current policy remains the baseline.',renewal);
      if(!snapshot.renewal||snapshot.renewal.status==='completed')button(renewal,'Start renewal review',async()=>{await request('/renewal/start');await refresh();});
      else if(snapshot.applicant){
        const inputs={}; let confirm;
        const f=form(renewal,'Refresh renewal quotes',async()=>{
          if(!confirm.checked)throw new Error('Confirm the current applicant details.');
          const applicant={...snapshot.applicant};
          for(const [key,input] of Object.entries(inputs)) applicant[key]=input.type==='checkbox'?input.checked:input.type==='number'?(input.value===''?null:Number(input.value)):input.value;
          applicant.dependents=(snapshot.applicant.dependents||[]).map((d,i)=>({...d,age:Number(dependentAges[i].value)}));
          const data=await request('/renewal/refresh',{applicant,confirmed_current:true});await refresh();
          status.textContent=data.quotes.length+' registry quotes refreshed. Use HAL to compare your shortlist against the current policy; carrier quotations remain required.';
        });
        inputs.age=field(f,'Current age','number',snapshot.applicant.age);inputs.age.min='0';inputs.age.max='120';
        inputs.residence_country=field(f,'Current residence','text',snapshot.applicant.residence_country);
        const dependentAges=(snapshot.applicant.dependents||[]).map((d,i)=>{const input=field(f,'Dependent '+(i+1)+' ('+d.relationship+') current age','number',d.age);input.min='0';input.max='120';return input;});
        inputs.coverage_area=choices(f,'Coverage area',[['area1','Europe'],['area2','Worldwide excluding USA, Singapore, Hong Kong and China'],['area3','Worldwide excluding USA'],['area4','Worldwide including USA']]);inputs.coverage_area.value=snapshot.applicant.coverage_area;el('p','Ask HAL to update household membership or other intake details before confirming if they have changed.',f);
        inputs.budget_annual=field(f,'Annual budget (optional)','number',snapshot.applicant.budget_annual);inputs.budget_annual.required=false;inputs.budget_annual.min='0';
        for(const [key,label] of [['outpatient_required','Out-patient'],['maternity_required','Maternity'],['dental_required','Dental'],['mental_health_required','Mental health'],['wellness_required','Wellness'],['optical_required','Optical'],['evacuation_required','Evacuation'],['chronic_required','Chronic conditions']]) {inputs[key]=field(f,label,'checkbox');inputs[key].required=false;inputs[key].checked=!!snapshot.applicant[key];}
        confirm=field(f,'I confirm the applicant, dependent and cover details are current','checkbox');
      }
    }
    if(broker){const conflicts=section('8 · Resolve evidence conflicts');button(conflicts,'Rebuild comparison from verified facts',async()=>{await request('/comparison/reconcile');await refresh();status.textContent='Comparison rebuilt; proposal quality checks still apply.';});for(const c of snapshot.conflicts||[]){el('h3',c.subject+' · '+c.key,conflicts);let choice,note;const verified=(snapshot.facts||[]).filter(f=>c.fact_ids.includes(f.fact_id)&&f.status==='verified');if(!verified.length){el('p','No verified candidate. Obtain source verification first.',conflicts);continue;}const f=form(conflicts,'Record resolution',async()=>{await request('/conflicts/resolve',{winning_fact_id:choice.value,note:note.value});await refresh();});choice=choices(f,'Verified source to retain',verified.map(v=>[v.fact_id,JSON.stringify(v.value)+' — '+(v.source.source_ref||v.source.document_id)+' p.'+(v.source.page||'?')]));note=field(f,'Reason for resolution (minimum 10 characters)','textarea');note.minLength=10;}}
    const history=section('Case activity');for(const event of snapshot.audit||[])el('p',event.at+' · '+event.action,history);
  }
  open.onclick=async()=>{updateAccess();dialog.showModal();render();if(access)try{await refresh();}catch(e){status.textContent=e.message;}};
})();
