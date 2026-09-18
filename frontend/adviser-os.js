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
  let lastCaseIntelligence = null;
  let lastNextBestAction = null;
  let applicationState = null;
  let lifecycleBusy = false;

  function ensureAdviserOsStyles() {
    if (document.getElementById('adviserOsWorkspaceStyles')) return;
    const style = document.createElement('style');
    style.id = 'adviserOsWorkspaceStyles';
    style.textContent = `
      .adviser-case-workspace{display:none;margin:0 16px 12px;border:1px solid var(--border);border-radius:16px;background:#fff;overflow:hidden;box-shadow:0 8px 26px rgba(12,23,39,.05)}
      .adviser-case-workspace.show{display:block}
      .adviser-case-head{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--border)}
      .adviser-case-title{font-size:12px;font-weight:800;letter-spacing:.02em}
      .adviser-case-ref{font-size:10px;color:var(--muted);margin-top:2px}
      .adviser-case-badge{margin-left:auto;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:800;background:var(--accent-soft);color:var(--accent)}
      .adviser-journey{display:grid;grid-template-columns:repeat(6,1fr);gap:5px;padding:10px 14px 5px}
      .adviser-phase{font-size:9.5px;text-align:center;color:var(--muted);padding:6px 3px;border-bottom:3px solid var(--border);white-space:nowrap}
      .adviser-phase.completed{color:var(--good);border-color:var(--good)}
      .adviser-phase.current{color:var(--navy);font-weight:800;border-color:var(--accent)}
      .adviser-case-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:9px 14px}
      .adviser-metric{background:var(--bg);border-radius:10px;padding:8px 9px;min-width:0}
      .adviser-metric strong{display:block;font-size:14px}
      .adviser-metric span{display:block;font-size:9.5px;color:var(--muted);margin-top:1px}
      .adviser-evidence{padding:2px 14px 10px}
      .adviser-evidence-title{font-size:10px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin:5px 0 7px}
      .adviser-plan-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--border)}
      .adviser-plan-name{min-width:125px;max-width:190px;font-size:11px;font-weight:700;line-height:1.25}
      .adviser-plan-evidence{display:flex;gap:5px;flex-wrap:wrap;flex:1}
      .evidence-pill{font-size:9.5px;padding:4px 7px;border-radius:999px;background:var(--bg);color:var(--muted);border:1px solid var(--border)}
      .evidence-pill.ok{background:#eaf7ef;color:var(--good);border-color:#cfe9d9}
      .evidence-pill.pending{background:#fff6e8;color:#9a5b00;border-color:#f1dfbd}
      .evidence-pill.conflict{background:#fdecec;color:#b3261e;border-color:#f3c9c9}
      .adviser-next-action{margin:0 14px 13px;padding:11px 12px;border-radius:12px;background:var(--navy);color:#fff;display:flex;gap:10px;align-items:center}
      .adviser-next-copy{flex:1;min-width:0}
      .adviser-next-label{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:#aeb9c9;font-weight:800}
      .adviser-next-title{font-size:12px;font-weight:800;margin-top:2px}
      .adviser-next-reason{font-size:10.5px;color:#d3dae5;margin-top:2px;line-height:1.35}
      .adviser-next-action button{border:none;border-radius:9px;background:#fff;color:var(--navy);padding:8px 10px;font-size:10.5px;font-weight:800;cursor:pointer;white-space:nowrap}
      .adviser-doc-chip{display:inline-flex;align-items:center;gap:4px;background:var(--bg);border:1px solid var(--border);border-radius:999px;padding:4px 8px;font-size:10px;color:var(--muted);margin:2px 4px 2px 0}
      .adviser-doc-chip.done{background:#eaf7ef;color:var(--good);border-color:#cfe9d9}
      .adviser-proposal-card{background:linear-gradient(135deg,#0c1727,#1c2a3c);color:#fff;border:none!important}
      .adviser-proposal-card .q-primary{background:#fff;color:var(--navy)}
      .adviser-proposal-card .q-secondary{background:transparent;color:#fff;border-color:#59677b}
      .adviser-plan-choice{display:block;border:1px solid var(--border);border-radius:12px;padding:10px 11px;margin:7px 0;cursor:pointer;background:#fff}
      .adviser-plan-choice:hover{border-color:var(--accent)}
      .adviser-plan-choice input{margin-right:8px}
      .adviser-plan-choice strong{font-size:12px}
      .adviser-plan-choice small{display:block;color:var(--muted);font-size:10px;margin:3px 0 0 24px}
      .adviser-application-card{background:#fff;border:1px solid var(--border)!important}
      .adviser-checklist{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
      .adviser-checkitem{font-size:10px;background:var(--bg);border:1px solid var(--border);border-radius:999px;padding:5px 8px;color:var(--muted)}
      @media(max-width:720px){
        .adviser-case-workspace{margin:0 10px 10px}
        .adviser-journey{overflow-x:auto;grid-template-columns:repeat(6,minmax(74px,1fr));padding-bottom:8px}
        .adviser-case-metrics{grid-template-columns:repeat(2,1fr)}
        .adviser-plan-row{align-items:flex-start;flex-direction:column;gap:5px}
        .adviser-plan-name{max-width:none}
        .adviser-next-action{align-items:flex-start;flex-direction:column}
        .adviser-next-action button{width:100%}
      }
    `;
    document.head.appendChild(style);
  }

  function ensureCaseWorkspace() {
    ensureAdviserOsStyles();
    let workspace = document.getElementById('adviserCaseWorkspace');
    if (workspace) return workspace;
    const progress = document.querySelector('.chat-card .progress-bar');
    if (!progress) return null;
    workspace = document.createElement('section');
    workspace.id = 'adviserCaseWorkspace';
    workspace.className = 'adviser-case-workspace';
    workspace.setAttribute('aria-live', 'polite');
    progress.insertAdjacentElement('afterend', workspace);
    return workspace;
  }

  function casePlanLabel(planKey) {
    const plan = comparisonPlans.find(item => item.plan_key === planKey)
      || ((typeof lastQuotes !== 'undefined' && Array.isArray(lastQuotes))
        ? lastQuotes.find(item => item.plan_key === planKey)
        : null);
    return plan
      ? ((plan.product_name || planKey) + (plan.insurer ? ' · ' + plan.insurer : ''))
      : planKey;
  }

  function phaseLabel(key) {
    return {
      discover:'Discover', compare:'Compare', decide:'Decide',
      policy:'Policy', care:'Care', renew:'Renew'
    }[key] || key;
  }

  function actionUi(action) {
    const key = action && action.action ? action.action : '';
    const map = {
      select_shortlist_plans: ['Choose the plans to compare', 'Select 2–4 plans', () => {
        const quotes = document.querySelector('.quotes-row');
        if (quotes) quotes.scrollIntoView({behavior:'smooth', block:'center'});
      }],
      upload_carrier_documents: ['Attach carrier evidence', 'Attach documents', openDocumentUpload],
      complete_plan_evidence: ['Complete plan evidence', 'Attach missing evidence', openDocumentUpload],
      verify_material_plan_facts: ['Strengthen evidence', 'Attach evidence', openDocumentUpload],
      resolve_evidence_conflicts: ['Resolve evidence conflicts', 'Review conflicts', () => askHal('Show me the evidence conflicts and tell me exactly what needs to be checked.')],
      prepare_proposal: ['Prepare the client proposal', 'Prepare proposal', prepareProposal],
      explain_document_findings: ['Explain the evidence', 'Ask HAL to explain', () => askHal('Explain the document findings and the important differences between these plans.')],
      explain_shortlist: ['Understand the shortlist', 'Explain shortlist', () => askHal('Explain why these plans made the shortlist and what the trade-offs are.')],
      present_proposal_to_client: ['Review the proposal and choose', 'Choose plan', openPlanSelection],
      prepare_application: ['Prepare the application', 'Start application', prepareApplication],
      complete_application: ['Complete the application', 'View checklist', renderApplicationCard],
      await_policy_issue: ['Application submitted', 'View application', renderApplicationCard],
      use_policy_wallet: ['Open Policy Wallet', 'Policy Wallet', () => askHal('Show me my Policy Wallet and explain the verified cover.')],
      collect_claim_evidence: ['Complete the claim file', 'Add claim evidence', () => askHal('Help me complete the claim file and tell me which documents are still needed.')],
      compare_renewal_options: ['Review renewal options', 'Compare renewal', () => askHal('Explain my renewal options and what changed versus the current policy.')],
      obtain_verified_policy_evidence: ['Add policy evidence', 'Attach policy wording', openDocumentUpload],
      continue_adviser_conversation: ['Continue with HAL', 'Continue', () => document.getElementById('input')?.focus()]
    };
    const selected = map[key] || ['Continue the case', 'Continue', () => document.getElementById('input')?.focus()];
    return {title:selected[0], label:selected[1], handler:selected[2]};
  }

  function askHal(message) {
    const input = document.getElementById('input');
    if (!input || typeof sendMessage !== 'function') return;
    input.value = message;
    sendMessage();
  }

  function ensurePlanSelectionModal() {
    let modal = document.getElementById('adviserPlanSelectionModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.className = 'modal-backdrop';
    modal.id = 'adviserPlanSelectionModal';
    modal.innerHTML = '<div class="modal" style="max-width:560px">' +
      '<h3>Which plan do you want to proceed with?</h3>' +
      '<p style="font-size:12px;color:var(--muted);line-height:1.5">This is your decision. HAL will record the plan you choose and continue the same AshlarCase into application.</p>' +
      '<div id="adviserPlanChoices"></div>' +
      '<div id="adviserPlanSelectionStatus" style="font-size:12px;margin-top:8px"></div>' +
      '<div class="modal-actions">' +
        '<button class="btn-secondary" type="button" id="adviserPlanSelectionCancel">Cancel</button>' +
        '<button class="btn-primary" type="button" id="adviserPlanSelectionConfirm">Use this plan</button>' +
      '</div></div>';
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) modal.classList.remove('open');
    });
    document.getElementById('adviserPlanSelectionCancel').onclick = () => modal.classList.remove('open');
    document.getElementById('adviserPlanSelectionConfirm').onclick = confirmPlanSelection;
    return modal;
  }

  function openPlanSelection() {
    if (!proposalCase || !comparisonPlans.length) {
      if (typeof addMsg === 'function') addMsg('I need the active comparison before I can record your final plan choice.', 'hal');
      return;
    }
    const modal = ensurePlanSelectionModal();
    const choices = document.getElementById('adviserPlanChoices');
    choices.innerHTML = comparisonPlans.map((plan, index) =>
      '<label class="adviser-plan-choice">' +
        '<input type="radio" name="adviserFinalPlan" value="' + esc(plan.plan_key || '') + '"' + (index === 0 ? ' checked' : '') + '>' +
        '<strong>' + esc(plan.product_name || plan.plan_key || 'Plan') + '</strong>' +
        '<small>' + esc(plan.insurer || '') + (plan.premium != null ? ' · ' + esc((plan.currency || 'EUR') + ' ' + Number(plan.premium).toLocaleString()) + '/year' : '') + '</small>' +
      '</label>'
    ).join('');
    const status = document.getElementById('adviserPlanSelectionStatus');
    status.textContent = '';
    modal.classList.add('open');
  }

  async function confirmPlanSelection() {
    if (!proposalCase || lifecycleBusy) return;
    const selected = document.querySelector('input[name="adviserFinalPlan"]:checked');
    const status = document.getElementById('adviserPlanSelectionStatus');
    if (!selected || !selected.value) {
      status.textContent = 'Choose one plan to continue.';
      status.style.color = '#b3261e';
      return;
    }
    lifecycleBusy = true;
    const button = document.getElementById('adviserPlanSelectionConfirm');
    if (button) {
      button.disabled = true;
      button.textContent = 'Recording…';
    }
    try {
      const response = await fetch(
        API + '/journey/' + encodeURIComponent(proposalCase.case_id) + '/select-plan',
        {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            case_token:proposalCase.case_token,
            plan_key:selected.value,
            selected_by:'client'
          })
        }
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not record the selected plan.');
      lastCaseIntelligence = data.case_intelligence || lastCaseIntelligence;
      lastNextBestAction = {
        action:data.action || 'prepare_application',
        reason:data.message || 'Your plan choice is recorded. The application can now be prepared.'
      };
      document.getElementById('adviserPlanSelectionModal').classList.remove('open');
      renderCaseWorkspace();
      const plan = comparisonPlans.find(item => item.plan_key === selected.value);
      if (typeof addMsg === 'function') {
        addMsg('I have recorded your choice of ' + (plan ? (plan.product_name + ' by ' + plan.insurer) : selected.value) + '. Your decision is now part of this AshlarCase. Next we can prepare the application.', 'hal');
      }
    } catch (error) {
      status.textContent = error.message || 'Could not record the selected plan.';
      status.style.color = '#b3261e';
    } finally {
      lifecycleBusy = false;
      if (button) {
        button.disabled = false;
        button.textContent = 'Use this plan';
      }
    }
  }

  async function prepareApplication() {
    if (!proposalCase || lifecycleBusy) return;
    lifecycleBusy = true;
    try {
      const response = await fetch(
        API + '/journey/' + encodeURIComponent(proposalCase.case_id) + '/application/prepare',
        {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({case_token:proposalCase.case_token})
        }
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not prepare the application workspace.');
      applicationState = data.payload && data.payload.application ? data.payload.application : null;
      lastCaseIntelligence = data.case_intelligence || lastCaseIntelligence;
      lastNextBestAction = {
        action:data.action || 'complete_application',
        reason:data.message || 'The application workspace is ready.'
      };
      renderCaseWorkspace();
      renderApplicationCard();
    } catch (error) {
      if (typeof addMsg === 'function') addMsg(error.message || 'I could not prepare the application workspace.', 'hal');
    } finally {
      lifecycleBusy = false;
    }
  }

  function renderApplicationCard() {
    if (!applicationState) {
      prepareApplication();
      return;
    }
    const chat = document.getElementById('chat');
    if (!chat) return;
    const required = Array.isArray(applicationState.required_sections) ? applicationState.required_sections : [];
    const completed = new Set(Array.isArray(applicationState.completed_sections) ? applicationState.completed_sections : []);
    const labels = {
      applicant_identity:'Identity',
      contact_and_residency:'Contact & residency',
      coverage_selection:'Coverage selection',
      declarations:'Declarations',
      medical_underwriting_questionnaire:'Medical underwriting',
      signature:'Signature'
    };
    const checklist = required.map(section =>
      '<span class="adviser-checkitem">' + (completed.has(section) ? '✓ ' : '○ ') + esc(labels[section] || section.replaceAll('_',' ')) + '</span>'
    ).join('');
    const card = document.createElement('div');
    card.className = 'msg hal adviser-application-card';
    card.innerHTML =
      '<div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:800">Application workspace</div>' +
      '<div style="font-weight:800;font-size:14px;margin-top:3px">Your selected plan is moving into application</div>' +
      '<div style="font-size:11px;color:var(--muted);margin-top:4px">HAL will keep the checklist on this AshlarCase. Carrier-specific answers and signatures must be collected explicitly; they are not inferred from the conversation.</div>' +
      '<div class="adviser-checklist">' + checklist + '</div>' +
      '<div style="margin-top:10px"><button class="q-primary adviser-application-help" style="padding:8px 12px">Continue application with HAL</button></div>';
    const help = card.querySelector('.adviser-application-help');
    if (help) help.onclick = () => askHal('Help me complete the application checklist for the plan I selected.');
    chat.appendChild(card);
    card.scrollIntoView({behavior:'smooth',block:'start'});
  }

  function renderCaseWorkspace() {
    const workspace = ensureCaseWorkspace();
    const legacyProgress = document.querySelector('.chat-card .progress-bar');
    const activeCaseId = proposalCase && proposalCase.case_id
      ? proposalCase.case_id
      : (typeof state === 'object' && state ? state._adviser_os_case_id : null);

    if (!workspace || !activeCaseId) {
      if (workspace) workspace.classList.remove('show');
      if (legacyProgress) legacyProgress.style.display = 'flex';
      return;
    }

    workspace.classList.add('show');
    if (legacyProgress) legacyProgress.style.display = 'none';

    const intel = lastCaseIntelligence || {};
    const journey = intel.journey || {};
    const phases = Array.isArray(journey.phases) && journey.phases.length
      ? journey.phases
      : [
          {key:'discover',state:'completed'}, {key:'compare',state:'current'},
          {key:'decide',state:'upcoming'}, {key:'policy',state:'upcoming'},
          {key:'care',state:'upcoming'}, {key:'renew',state:'upcoming'}
        ];
    const completeness = Math.round(Number(intel.material_completeness || 0) * 100);
    const docs = Number(intel.document_count || uploadedDocuments.length || 0);
    const conflicts = Number(intel.conflict_count || 0);
    const confidence = String(intel.evidence_confidence || (docs ? 'building' : 'quote only'));
    const currentPhase = journey.current_phase || (comparisonPlans.length ? 'compare' : 'discover');

    let action = lastNextBestAction;
    if (pendingDocumentRefs.length) {
      action = {
        action:'explain_document_findings',
        reason:'New carrier evidence is attached and waiting for analysis.',
        blocked:false
      };
    } else if (!action && Array.isArray(intel.next_actions) && intel.next_actions.length) {
      action = intel.next_actions[0];
    }
    const actionView = actionUi(action || {action:'continue_adviser_conversation'});

    const plans = Array.isArray(intel.plans) && intel.plans.length
      ? intel.plans
      : comparisonPlans.map(plan => ({
          plan_key:plan.plan_key, fact_count:0, document_roles:[],
          missing_material_keys:[], conflicting_material_keys:[]
        }));

    const documentChips = uploadedDocuments.map(item =>
      '<span class="adviser-doc-chip ' + (item.analysed ? 'done' : '') + '">' +
      (item.analysed ? '✓ ' : '↻ ') + esc(item.filename) + ' · ' + esc(item.role) +
      '</span>'
    ).join('');

    const evidenceRows = plans.map(plan => {
      const roles = new Set(plan.document_roles || []);
      const quotation = plan.has_quotation || roles.has('quotation') || roles.has('quote') || roles.has('carrier_quote');
      const benefits = plan.has_brochure_or_tob || roles.has('brochure') || roles.has('tob') || roles.has('carrier_tob');
      const wording = plan.has_wording || roles.has('wording') || roles.has('policy_wording') || roles.has('member_guide');
      const pending = uploadedDocuments.filter(item => item.plan_key === plan.plan_key && !item.analysed).length;
      const conflictCount = (plan.conflicting_material_keys || []).length;
      const missingCount = (plan.missing_material_keys || []).length;
      return '<div class="adviser-plan-row">' +
        '<div class="adviser-plan-name">' + esc(casePlanLabel(plan.plan_key)) + '</div>' +
        '<div class="adviser-plan-evidence">' +
          '<span class="evidence-pill ' + (quotation?'ok':'pending') + '">' + (quotation?'✓':'○') + ' Quote</span>' +
          '<span class="evidence-pill ' + (benefits?'ok':'pending') + '">' + (benefits?'✓':'○') + ' Benefits</span>' +
          '<span class="evidence-pill ' + (wording?'ok':'pending') + '">' + (wording?'✓':'○') + ' Wording</span>' +
          (pending ? '<span class="evidence-pill pending">↻ ' + pending + ' awaiting analysis</span>' : '') +
          (conflictCount ? '<span class="evidence-pill conflict">! ' + conflictCount + ' conflict' + (conflictCount===1?'':'s') + '</span>' : '') +
          (!conflictCount && missingCount ? '<span class="evidence-pill pending">' + missingCount + ' fact' + (missingCount===1?'':'s') + ' to verify</span>' : '') +
        '</div></div>';
    }).join('');

    const phaseHtml = phases.map(phase =>
      '<div class="adviser-phase ' + esc(phase.state || 'upcoming') + '">' + esc(phase.label || phaseLabel(phase.key)) + '</div>'
    ).join('');

    workspace.innerHTML =
      '<div class="adviser-case-head">' +
        '<div><div class="adviser-case-title">Ashlar Case</div><div class="adviser-case-ref">#' + esc(String(activeCaseId).slice(0,8).toUpperCase()) + ' · one case across the full journey</div></div>' +
        '<span class="adviser-case-badge">' + esc(phaseLabel(currentPhase)) + '</span>' +
      '</div>' +
      '<div class="adviser-journey">' + phaseHtml + '</div>' +
      '<div class="adviser-case-metrics">' +
        '<div class="adviser-metric"><strong>' + completeness + '%</strong><span>material facts ready</span></div>' +
        '<div class="adviser-metric"><strong>' + docs + '</strong><span>carrier documents</span></div>' +
        '<div class="adviser-metric"><strong>' + conflicts + '</strong><span>evidence conflicts</span></div>' +
        '<div class="adviser-metric"><strong>' + esc(confidence) + '</strong><span>evidence confidence</span></div>' +
      '</div>' +
      (documentChips ? '<div class="adviser-evidence"><div class="adviser-evidence-title">Case documents</div>' + documentChips + '</div>' : '') +
      (evidenceRows ? '<div class="adviser-evidence"><div class="adviser-evidence-title">Evidence by plan</div>' + evidenceRows + '</div>' : '') +
      '<div class="adviser-next-action">' +
        '<div class="adviser-next-copy"><div class="adviser-next-label">HAL · next best action</div>' +
        '<div class="adviser-next-title">' + esc(actionView.title) + '</div>' +
        '<div class="adviser-next-reason">' + esc((action && action.reason) || 'HAL is ready to continue this case.') + '</div></div>' +
        '<button type="button" id="adviserNextActionBtn">' + esc(actionView.label) + '</button>' +
      '</div>';

    const actionButton = document.getElementById('adviserNextActionBtn');
    if (actionButton) actionButton.onclick = actionView.handler;
  }

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
    if (button) button.style.display = (proposalCase && comparisonPlans.length) ? '' : 'none';
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
      renderCaseWorkspace();
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
    if (result.case_id && typeof state === 'object' && state && state._adviser_os_case_token) {
      proposalCase = {
        case_id: result.case_id,
        case_token: state._adviser_os_case_token
      };
    }
    if (result.payload && result.payload.case_intelligence) {
      lastCaseIntelligence = result.payload.case_intelligence;
    }
    lastNextBestAction = result.next_best_action || lastNextBestAction;
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
    renderCaseWorkspace();

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
    if (response && response.case_intelligence) {
      lastCaseIntelligence = response.case_intelligence;
      const firstAction = Array.isArray(response.case_intelligence.next_actions)
        ? response.case_intelligence.next_actions[0]
        : null;
      if (firstAction) lastNextBestAction = firstAction;
    }
    ensureDocumentControls();
    renderDocumentStatus();
    renderCaseWorkspace();

    if (!proposalCase) {
      button.style.display = 'none';
      if (status) status.textContent = '';
      return;
    }

    button.style.display = '';
    button.disabled = !response.proposal_available;
    button.textContent = response.proposal_available ? 'Prepare proposal' : 'Carrier quotations required';
    if (status) {
      if (response.proposal_available) {
        const review = response.proposal_quality && response.proposal_quality.status === 'review';
        status.textContent = review
          ? 'Proposal Studio can prepare a draft, but some evidence points remain marked for review.'
          : 'Verified server-side comparison saved. Proposal Studio is ready.';
        status.style.color = review ? '#a15c00' : 'var(--good)';
      } else {
        status.textContent = 'Attach the applicant-specific carrier quotation for each selected plan. HAL will analyse them, check conflicts and then unlock the proposal.';
        status.style.color = '#a15c00';
      }
    }
  }

  function renderProposalDownloadCard(downloads) {
    if (!downloads || !downloads.pdf || !downloads.pptx) return;
    const chat = document.getElementById('chat');
    if (!chat) return;

    const card = document.createElement('div');
    card.className = 'msg hal adviser-proposal-card';
    card.innerHTML = '<div style="font-size:10px;color:#aeb9c9;text-transform:uppercase;letter-spacing:.06em;font-weight:800">Ashlar Assessment</div>' +
      '<div style="font-weight:800;font-size:15px;margin:3px 0 6px">Your client proposal is ready</div>' +
      '<div style="font-size:12px;color:#d3dae5;margin-bottom:10px">The PDF and PowerPoint use the same server-owned case evidence HAL has been discussing with you.</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<a class="q-primary" style="text-decoration:none;text-align:center;display:inline-block;flex:0 0 auto;padding:9px 14px" href="' + esc(downloads.pdf) + '" target="_blank" rel="noopener">PDF proposal</a>' +
      '<a class="q-secondary" style="text-decoration:none;text-align:center;display:inline-block;padding:9px 14px" href="' + esc(downloads.pptx) + '" target="_blank" rel="noopener">PowerPoint</a>' +
      '<button class="q-secondary explain-proposal-btn" style="padding:9px 14px">Ask HAL to explain</button>' +
      '<button class="q-secondary choose-final-plan-btn" style="padding:9px 14px">Choose plan</button>' +
      '</div><div style="font-size:10px;color:#aeb9c9;margin-top:8px">Temporary, no-store download links.</div>';
    const explainButton = card.querySelector('.explain-proposal-btn');
    if (explainButton) explainButton.onclick = () => askHal('Walk me through the Ashlar Assessment and explain the trade-offs in this proposal.');
    const chooseButton = card.querySelector('.choose-final-plan-btn');
    if (chooseButton) chooseButton.onclick = openPlanSelection;
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
      if (data.case_intelligence) lastCaseIntelligence = data.case_intelligence;
      lastNextBestAction = {
        action:'present_proposal_to_client',
        reason:'The evidence-grounded Ashlar proposal is ready for client review.'
      };
      renderCaseWorkspace();
      const assessment = data.report && data.report.ashlar_assessment
        ? data.report.ashlar_assessment
        : null;
      const assessmentHeadline = assessment && assessment.headline
        ? String(assessment.headline)
        : 'Your evidence-grounded Ashlar proposal is ready.';
      if (typeof addMsg === 'function') {
        addMsg(assessmentHeadline + ' I can walk you through the reasoning and trade-offs in the same conversation.', 'hal');
      }
      renderProposalDownloadCard(data.downloads);
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
    const proposalButton = ensureProposalControls();
    const proposalStatus = document.getElementById('proposalPrepareStatus');
    if (proposalButton) {
      proposalButton.style.display = 'none';
      proposalButton.disabled = true;
    }
    if (proposalStatus) {
      proposalStatus.textContent = 'Building the server-owned comparison…';
      proposalStatus.style.color = 'var(--muted)';
    }

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
      if (proposalStatus) {
        proposalStatus.textContent = 'The comparison could not be completed. Your active AshlarCase has been kept.';
        proposalStatus.style.color = '#b3261e';
      }
      renderCaseWorkspace();
    }
  };

  ensureProposalControls();
  ensureDocumentControls();
  ensureCaseWorkspace();
  renderDocumentStatus();
  renderCaseWorkspace();
})();
