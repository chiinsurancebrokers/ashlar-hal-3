(() => {
  'use strict';

  let proposalCase = null;
  let proposalBusy = false;
  let pendingChatProposalDownloads = null;
  let pendingOrchestratorUi = null;
  let comparisonPlans = [];
  let pendingDocumentRefs = [];
  let uploadedDocuments = [];
  let documentBusy = false;

  function ensureProposalControls() {
    const modal = document.getElementById('compareModal');
    if (!modal) return null;
    const actions = modal.querySelector('.modal-actions');
    if (!actions) return null;

    let button = document.getElementById('prepareProposalBtn');
    if (!button) {
      button = document.createElement('button');
      button.id = 'prepareProposalBtn';
      button.className = 'btn-primary';
      button.textContent = 'Prepare proposal';
      button.style.display = 'none';
      button.onclick = prepareProposal;
      actions.appendChild(button);
    }

    let status = document.getElementById('proposalPrepareStatus');
    if (!status) {
      status = document.createElement('div');
      status.id = 'proposalPrepareStatus';
      status.style.cssText = 'font-size:12px;margin-top:12px;line-height:1.5;';
      const content = document.getElementById('compareContent');
      if (content) content.insertAdjacentElement('afterend', status);
    }
    return button;
  }

  function ensureDocumentControls() {
    const composer = document.querySelector('.composer');
    if (!composer) return null;

    let button = document.getElementById('attachCarrierDocumentBtn');
    if (!button) {
      button = document.createElement('button');
      button.id = 'attachCarrierDocumentBtn';
      button.className = 'mic-btn';
      button.type = 'button';
      button.textContent = '📎';
      button.title = 'Attach carrier quotation, brochure or policy wording';
      button.setAttribute('aria-label', button.title);
      button.style.display = 'none';
      button.onclick = openDocumentUpload;
      composer.insertBefore(button, composer.firstChild);
    }

    let status = document.getElementById('adviserDocumentStatus');
    if (!status) {
      status = document.createElement('div');
      status.id = 'adviserDocumentStatus';
      status.style.cssText = 'display:none;font-size:11px;color:var(--muted);margin:7px 0 2px;line-height:1.45;';
      const row = document.getElementById('dynamicInputRow');
      if (row) row.insertBefore(status, composer);
    }

    let modal = document.getElementById('carrierDocumentModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'modal-backdrop';
      modal.id = 'carrierDocumentModal';
      modal.innerHTML = '<div class="modal" style="max-width:520px">' +
        '<h3>Attach carrier evidence</h3>' +
        '<p style="font-size:12px;color:var(--muted);line-height:1.5">Documents are extracted on the server and bound to this case. HAL receives only an opaque reference.</p>' +
        '<label>Plan</label><select id="carrierDocumentPlan"></select>' +
        '<label>Document type</label><select id="carrierDocumentRole">' +
          '<option value="quotation">Applicant quotation / certificate</option>' +
          '<option value="brochure">Brochure / Table of Benefits</option>' +
          '<option value="wording">Policy wording / member guide</option>' +
        '</select>' +
        '<label>File</label><input id="carrierDocumentFile" type="file" multiple accept=".pdf,.txt,.html,.htm,application/pdf,text/plain,text/html">' +
        '<div id="carrierDocumentUploadStatus" style="font-size:12px;margin-top:8px"></div>' +
        '<div class="modal-actions">' +
          '<button class="btn-secondary" type="button" id="carrierDocumentCancel">Cancel</button>' +
          '<button class="btn-primary" type="button" id="carrierDocumentUpload">Attach to HAL</button>' +
        '</div></div>';
      document.body.appendChild(modal);
      modal.addEventListener('click', event => {
        if (event.target === modal) modal.classList.remove('open');
      });
      document.getElementById('carrierDocumentCancel').onclick = () => modal.classList.remove('open');
      document.getElementById('carrierDocumentUpload').onclick = uploadCarrierDocuments;
    }
    return button;
  }

  function renderDocumentStatus() {
    const status = document.getElementById('adviserDocumentStatus');
    const button = ensureDocumentControls();
    if (button) button.style.display = proposalCase ? '' : 'none';
    if (!status) return;

    if (!proposalCase || !uploadedDocuments.length) {
      status.style.display = 'none';
      status.textContent = '';
      return;
    }
    status.style.display = 'block';
    const waiting = uploadedDocuments.filter(item => !item.analysed).length;
    const labels = uploadedDocuments.slice(-4).map(item =>
      item.filename + ' · ' + item.role + (item.analysed ? ' ✓' : '')
    );
    status.textContent = labels.join('   |   ') + (waiting ? '   — ask HAL to compare/analyse them.' : '');
  }

  function openDocumentUpload() {
    if (!proposalCase) {
      if (typeof addMsg === 'function') addMsg('Compare at least two plans first so I can bind carrier documents to the correct case.', 'hal');
      return;
    }
    ensureDocumentControls();
    const select = document.getElementById('carrierDocumentPlan');
    select.innerHTML = '';
    comparisonPlans.forEach(plan => {
      const option = document.createElement('option');
      option.value = plan.plan_key || '';
      option.textContent = (plan.product_name || plan.plan_key || 'Plan') + ' — ' + (plan.insurer || '');
      select.appendChild(option);
    });
    const fileInput = document.getElementById('carrierDocumentFile');
    fileInput.value = '';
    document.getElementById('carrierDocumentUploadStatus').textContent = '';
    document.getElementById('carrierDocumentModal').classList.add('open');
  }

  async function uploadCarrierDocuments() {
    if (!proposalCase || documentBusy) return;
    const planKey = document.getElementById('carrierDocumentPlan').value;
    const plan = comparisonPlans.find(item => item.plan_key === planKey);
    const role = document.getElementById('carrierDocumentRole').value;
    const files = [...document.getElementById('carrierDocumentFile').files];
    const status = document.getElementById('carrierDocumentUploadStatus');
    if (!plan || !planKey) {
      status.textContent = 'Choose a plan first.';
      status.style.color = '#b3261e';
      return;
    }
    if (!files.length) {
      status.textContent = 'Choose at least one PDF, TXT or HTML document.';
      status.style.color = '#b3261e';
      return;
    }

    documentBusy = true;
    document.getElementById('carrierDocumentUpload').disabled = true;
    try {
      let uploaded = 0;
      for (const file of files) {
        status.textContent = 'Uploading and extracting ' + file.name + '…';
        status.style.color = 'var(--muted)';
        const form = new FormData();
        form.append('case_id', proposalCase.case_id);
        form.append('case_token', proposalCase.case_token);
        form.append('provider_label', plan.insurer || 'Carrier');
        form.append('target_plan', plan.product_name || planKey);
        form.append('plan_key', planKey);
        form.append('role', role);
        form.append('file', file, file.name);
        const response = await fetch(API + '/documents/upload', {method:'POST', body:form});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || ('Could not attach ' + file.name + '.'));
        if (!pendingDocumentRefs.includes(data.document_ref)) pendingDocumentRefs.push(data.document_ref);
        uploadedDocuments.push({
          document_ref: data.document_ref,
          filename: data.filename || file.name,
          role: data.role || role,
          plan_key: data.plan_key || planKey,
          analysed: false
        });
        uploaded += 1;
      }
      syncCaseIntoHalState();
      renderDocumentStatus();
      document.getElementById('carrierDocumentModal').classList.remove('open');
      if (typeof addMsg === 'function') {
        addMsg(uploaded + ' carrier document' + (uploaded === 1 ? ' is' : 's are') + ' attached to this case. You can ask me to compare them, explain what matters, or prepare the proposal.', 'hal');
      }
    } catch (error) {
      status.textContent = error.message || 'Could not attach the document.';
      status.style.color = '#b3261e';
    } finally {
      documentBusy = false;
      document.getElementById('carrierDocumentUpload').disabled = false;
    }
  }

  function applyOrchestratorUi(result) {
    if (!result || !Array.isArray(result.responses)) return;
    const documentCompleted = result.responses.some(
      item => item.specialist === 'document_analyst' && item.status === 'completed'
    );
    if (documentCompleted) {
      const analysedRefs = new Set(pendingDocumentRefs);
      uploadedDocuments = uploadedDocuments.map(item => (
        analysedRefs.has(item.document_ref) ? {...item, analysed:true} : item
      ));
      pendingDocumentRefs = [];
      syncCaseIntoHalState();
      renderDocumentStatus();
    }

    const action = result.next_best_action && result.next_best_action.action;
    const proposalButton = ensureProposalControls();
    const proposalStatus = document.getElementById('proposalPrepareStatus');
    if (action === 'prepare_proposal' && proposalButton) {
      proposalButton.style.display = '';
      proposalButton.disabled = false;
      proposalButton.textContent = 'Prepare proposal';
      if (proposalStatus) {
        proposalStatus.textContent = 'Carrier evidence analysed. Proposal Studio is ready when you are.';
        proposalStatus.style.color = 'var(--good)';
      }
    } else if (result.next_best_action && result.next_best_action.blocked && proposalStatus) {
      proposalStatus.textContent = result.next_best_action.reason || 'More evidence is needed before the proposal can be prepared.';
      proposalStatus.style.color = '#a15c00';
    }
  }

  function syncCaseIntoHalState() {
    if (typeof state !== 'object' || !state) return;
    if (proposalCase) {
      state._adviser_os_case_id = proposalCase.case_id;
      state._adviser_os_case_token = proposalCase.case_token;
      if (pendingDocumentRefs.length) state._adviser_os_document_refs = [...pendingDocumentRefs];
      else delete state._adviser_os_document_refs;
    } else {
      delete state._adviser_os_case_id;
      delete state._adviser_os_case_token;
      delete state._adviser_os_document_refs;
    }
  }

  function setProposalContext(response) {
    const button = ensureProposalControls();
    const status = document.getElementById('proposalPrepareStatus');
    if (!button) return;

    const previousCaseId = proposalCase && proposalCase.case_id;
    proposalCase = response && response.case_id && response.case_token
      ? {case_id: response.case_id, case_token: response.case_token}
      : null;
    comparisonPlans = response && Array.isArray(response.plans) ? response.plans : [];
    if (!proposalCase || proposalCase.case_id !== previousCaseId) {
      pendingDocumentRefs = [];
      uploadedDocuments = [];
    }
    syncCaseIntoHalState();
    ensureDocumentControls();
    renderDocumentStatus();

    if (!proposalCase) {
      button.style.display = 'none';
      if (status) status.textContent = '';
      return;
    }

    button.style.display = '';
    button.disabled = !response.proposal_available;
    button.textContent = response.proposal_available ? 'Prepare proposal' : 'Proposal needs broker review';
    if (status) {
      if (response.proposal_available) {
        const review = response.proposal_quality && response.proposal_quality.status === 'review';
        status.textContent = review
          ? 'Proposal Studio can prepare a draft, but some evidence points remain marked for review.'
          : 'Verified server-side comparison saved. Proposal Studio is ready.';
        status.style.color = review ? '#a15c00' : 'var(--good)';
      } else {
        status.textContent = 'The evidence quality gate is blocking automatic proposal generation. A broker review is required.';
        status.style.color = '#b3261e';
      }
    }
  }

  function renderProposalDownloadCard(downloads) {
    if (!downloads || !downloads.pdf || !downloads.pptx) return;
    const chat = document.getElementById('chat');
    if (!chat) return;

    const card = document.createElement('div');
    card.className = 'msg hal';
    card.innerHTML = '<div style="font-weight:700;margin-bottom:8px">Ashlar proposal files</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<a class="q-primary" style="text-decoration:none;text-align:center;display:inline-block;flex:0 0 auto;padding:9px 14px" href="' + esc(downloads.pdf) + '" target="_blank" rel="noopener">Download PDF</a>' +
      '<a class="q-secondary" style="text-decoration:none;text-align:center;display:inline-block;padding:9px 14px" href="' + esc(downloads.pptx) + '" target="_blank" rel="noopener">Download PowerPoint</a>' +
      '</div><div style="font-size:10px;color:var(--muted);margin-top:8px">These links are temporary and are not cached by the browser.</div>';
    chat.appendChild(card);
    card.scrollIntoView({behavior: 'smooth', block: 'start'});

    const ps3 = document.getElementById('ps3');
    if (ps3) {
      ps3.classList.add('active');
      ps3.classList.remove('done');
    }
  }

  // Observe only the existing HAL chat response. This lets the additive bridge
  // render proposal artifacts without rewriting the established sendMessage()
  // implementation in index.html.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async function adviserOsFetch(input, init) {
    const response = await nativeFetch(input, init);
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes(API + '/chat/turn')) {
      try {
        const data = await response.clone().json();
        pendingChatProposalDownloads = data && data.proposal_downloads
          ? data.proposal_downloads
          : null;
        pendingOrchestratorUi = data && data._adviser_os ? data._adviser_os : null;
      } catch (_) {
        pendingChatProposalDownloads = null;
        pendingOrchestratorUi = null;
      }
    }
    return response;
  };

  const originalAddMsg = window.addMsg;
  if (typeof originalAddMsg === 'function') {
    window.addMsg = function adviserOsAddMsg(...args) {
      const result = originalAddMsg.apply(this, args);
      const who = args.length > 1 ? args[1] : 'hal';
      if (who === 'hal' && pendingOrchestratorUi) {
        const orchestratorResult = pendingOrchestratorUi;
        pendingOrchestratorUi = null;
        applyOrchestratorUi(orchestratorResult);
      }
      if (who === 'hal' && pendingChatProposalDownloads) {
        const downloads = pendingChatProposalDownloads;
        pendingChatProposalDownloads = null;
        renderProposalDownloadCard(downloads);
      }
      return result;
    };
  }

  async function prepareProposal() {
    if (!proposalCase || proposalBusy) return;
    const button = ensureProposalControls();
    const status = document.getElementById('proposalPrepareStatus');
    proposalBusy = true;
    if (button) {
      button.disabled = true;
      button.textContent = 'Preparing…';
    }
    if (status) {
      status.textContent = 'Proposal Studio is building the evidence-grounded PDF and PowerPoint…';
      status.style.color = 'var(--muted)';
    }

    try {
      const response = await fetch(API + '/proposals/prepare', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          case_id: proposalCase.case_id,
          case_token: proposalCase.case_token,
          language: (state && state.language) || 'en'
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not prepare the proposal.');

      if (status) {
        status.innerHTML = '<strong>Proposal ready.</strong> ' +
          '<a href="' + esc(data.downloads.pdf) + '" target="_blank" rel="noopener">Download PDF</a>' +
          ' &nbsp;·&nbsp; ' +
          '<a href="' + esc(data.downloads.pptx) + '" target="_blank" rel="noopener">Download PowerPoint</a>';
        status.style.color = 'var(--good)';
      }
      if (button) {
        button.textContent = 'Proposal ready';
        button.disabled = true;
      }
      const ps3 = document.getElementById('ps3');
      if (ps3) {
        ps3.classList.add('active');
        ps3.classList.remove('done');
      }
      if (typeof addMsg === 'function') {
        addMsg('Your evidence-grounded Ashlar proposal is ready. You can download the PDF or PowerPoint from the comparison window.', 'hal');
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message || 'Could not prepare the proposal.';
        status.style.color = '#b3261e';
      }
      if (button) {
        button.disabled = false;
        button.textContent = 'Try proposal again';
      }
    } finally {
      proposalBusy = false;
    }
  }

  // Replace only the comparison network wrapper. Existing rendering and quote
  // selection functions remain untouched.
  window.openCompare = async function openCompareWithStoredCase() {
    const content = document.getElementById('compareContent');
    content.innerHTML = '<p style="color:var(--muted)">Building your detailed comparison…</p>';
    document.getElementById('compareModal').classList.add('open');
    setProposalContext(null);

    try {
      const response = await fetch(API + '/quotes/compare', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          applicant_state: state,
          plan_keys: [...compareSelected],
          language: (state && state.language) || 'en',
          case_id: state && state._adviser_os_case_id ? state._adviser_os_case_id : null,
          case_token: state && state._adviser_os_case_token ? state._adviser_os_case_token : null
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not build the comparison.');
      content.innerHTML = renderDetailedCompare(data);
      setProposalContext(data);
    } catch (error) {
      content.innerHTML = '<p style="color:#b3261e">' + esc(error.message) + '</p>';
      setProposalContext(null);
    }
  };

  ensureProposalControls();
  ensureDocumentControls();
  renderDocumentStatus();
})();
