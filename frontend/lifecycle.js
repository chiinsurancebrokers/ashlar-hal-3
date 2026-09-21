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
    if(snapshot.storage !== 'encrypted_sqlite') el('p','This advice case is temporary. Save the reviewed handoff pack; permanent client documents belong in the CHI Insurance Portal.',body);
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
    role = choices(df, 'Document purpose', [['existing_policy','Your existing policy'],['application','Application / signed form']]);
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
    if (snapshot.application?.status === 'submitted') {
      const portal = section('Continue in CHI Insurance Portal');
      el('p','The CHI Portal is the system of record for the issued policy, permanent client documents, claims and renewals.',portal);
      if (broker) el('p','Download the reviewed handoff pack, then upload it to the correct client record in the Portal. No client document is sent automatically.',portal);
      if (broker) button(portal,'Download reviewed handoff pack',async()=>download(await request('/handoff-pack',{document_refs:snapshot.documents.flatMap(d=>d.refs||[])},true),'ashlar-application-handoff.zip'));
      if (snapshot.portal_handoff?.url) {
        const link=el('a','Open CHI Insurance Portal',portal);link.href=snapshot.portal_handoff.url;link.target='_blank';link.rel='noopener noreferrer';link.style.display='inline-block';link.style.margin='8px 5px';
      }
    }
    if(broker){const conflicts=section('8 · Resolve evidence conflicts');button(conflicts,'Rebuild comparison from verified facts',async()=>{await request('/comparison/reconcile');await refresh();status.textContent='Comparison rebuilt; proposal quality checks still apply.';});for(const c of snapshot.conflicts||[]){el('h3',c.subject+' · '+c.key,conflicts);let choice,note;const verified=(snapshot.facts||[]).filter(f=>c.fact_ids.includes(f.fact_id)&&f.status==='verified');if(!verified.length){el('p','No verified candidate. Obtain source verification first.',conflicts);continue;}const f=form(conflicts,'Record resolution',async()=>{await request('/conflicts/resolve',{winning_fact_id:choice.value,note:note.value});await refresh();});choice=choices(f,'Verified source to retain',verified.map(v=>[v.fact_id,JSON.stringify(v.value)+' — '+(v.source.source_ref||v.source.document_id)+' p.'+(v.source.page||'?')]));note=field(f,'Reason for resolution (minimum 10 characters)','textarea');note.minLength=10;}}
    const history=section('Case activity');for(const event of snapshot.audit||[])el('p',event.at+' · '+event.action,history);
  }
  open.onclick=async()=>{updateAccess();dialog.showModal();render();if(access)try{await refresh();}catch(e){status.textContent=e.message;}};
})();
