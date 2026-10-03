/* HAL Corporate & Group UI extension.
 * Loaded after the core UI so it can extend the existing proposal modal
 * without duplicating the large single-file frontend.
 */
(() => {
  const coreOpenLeadForm = window.openLeadForm;
  const coreSubmitLead = window.submitLead;
  const halState = () => (typeof state !== 'undefined' && state) ? state : {};
  const halJourney = () => (typeof currentJourney !== 'undefined' ? currentJourney : halState().journey);

  function isCorporate() {
    return halJourney() === 'corporate_group' || halState().journey === 'corporate_group';
  }

  function ensureCorporateFields() {
    let box = document.getElementById('corporateLeadFields');
    if (box) return box;
    box = document.createElement('div');
    box.id = 'corporateLeadFields';
    box.style.cssText = 'margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--bg)';
    box.innerHTML = `
      <label style="display:block;font-size:12px;font-weight:700;margin-bottom:5px">Company / organisation</label>
      <input id="groupCompanyName" type="text" maxlength="160" style="width:100%;margin-bottom:12px" autocomplete="organization">
      <label style="display:block;font-size:12px;font-weight:700;margin-bottom:5px">Census list <span style="font-weight:400;color:var(--muted)">(optional CSV/XLSX, max 5 MB)</span></label>
      <input id="groupCensusFile" type="file" accept=".csv,.xlsx" style="width:100%;margin-bottom:8px">
      <label style="display:flex;gap:8px;align-items:flex-start;font-size:11px;line-height:1.4;color:var(--muted)">
        <input id="groupNoMedicalData" type="checkbox" style="margin-top:2px">
        <span>I confirm the census contains administrative quoting data only and no diagnoses, medical histories, treatments or other clinical information.</span>
      </label>`;
    const message = document.getElementById('leadMessage');
    if (message?.parentElement) message.parentElement.insertBefore(box, message.nextSibling);
    return box;
  }

  window.openLeadForm = function(journey) {
    coreOpenLeadForm(journey);
    const box = ensureCorporateFields();
    box.style.display = isCorporate() ? 'block' : 'none';
    if (!isCorporate()) return;

    const s = halState();
    document.getElementById('leadTitle').textContent = 'Request a Group Proposal';
    document.getElementById('leadSubtitle').textContent = 'Your group fact-find is pre-filled below. An Ashlar specialist will review insurer terms and underwriting; HAL will not calculate a group premium automatically.';
    document.getElementById('leadResidence').value = s.company_country || s.residence_country || '';
    document.getElementById('leadCoverage').value = s.coverage_area_label || '';
    document.getElementById('leadFamily').value = s.employee_count ? `${s.employee_count} employees` : '';
    document.getElementById('leadBudget').value = '';
    document.getElementById('leadMessage').value = s.group_fact_find_summary || '';
    document.getElementById('groupCompanyName').value = s.company_name || '';
    document.getElementById('groupNoMedicalData').checked = false;
    document.getElementById('groupCensusFile').value = '';
  };

  window.submitLead = async function() {
    if (!isCorporate()) return coreSubmitLead();

    const status = document.getElementById('leadStatus');
    const first = document.getElementById('leadFirstName').value.trim();
    const last = document.getElementById('leadLastName').value.trim();
    const email = document.getElementById('leadEmail').value.trim();
    const consent = document.getElementById('leadConsent').checked;
    const file = document.getElementById('groupCensusFile')?.files?.[0] || null;
    const noMedical = document.getElementById('groupNoMedicalData')?.checked || false;

    if (!first || !last || !email) {
      status.textContent = typeof t === 'function' ? t('fillNameEmail') : 'Please complete your name and email.';
      status.style.color = '#b3261e'; return;
    }
    if (!consent) {
      status.textContent = typeof t === 'function' ? t('confirmConsent') : 'Please confirm consent.';
      status.style.color = '#b3261e'; return;
    }
    if (file && file.size > 5 * 1024 * 1024) {
      status.textContent = 'The census file must be no larger than 5 MB.';
      status.style.color = '#b3261e'; return;
    }
    if (file && !noMedical) {
      status.textContent = 'Please confirm that the census contains no medical or clinical information.';
      status.style.color = '#b3261e'; return;
    }

    const form = new FormData();
    form.append('contact_name', `${first} ${last}`.trim());
    form.append('email', email);
    form.append('company_name', document.getElementById('groupCompanyName')?.value.trim() || '');
    form.append('fact_find_json', JSON.stringify(halState()));
    form.append('consent', String(consent));
    form.append('no_medical_data_confirmed', String(noMedical));
    if (file) form.append('census', file, file.name);

    status.textContent = typeof t === 'function' ? t('sending') : 'Sending…';
    status.style.color = 'var(--muted)';
    try {
      const response = await fetch(API + '/corporate/enquiry', {method: 'POST', body: form});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not send group enquiry.');
      status.textContent = (typeof t === 'function' ? t('sentRef') : 'Sent. Reference: ') + (data.reference || '');
      status.style.color = 'var(--good)';
      setTimeout(() => closeModal('leadModal'), 1600);
    } catch (error) {
      status.textContent = error.message || 'Could not send group enquiry.';
      status.style.color = '#b3261e';
    }
  };
})();
