(() => {
  'use strict';

  let proposalCase = null;
  let proposalBusy = false;

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

  function syncCaseIntoHalState() {
    if (typeof state !== 'object' || !state) return;
    if (proposalCase) {
      state._adviser_os_case_id = proposalCase.case_id;
      state._adviser_os_case_token = proposalCase.case_token;
    } else {
      delete state._adviser_os_case_id;
      delete state._adviser_os_case_token;
    }
  }

  function setProposalContext(response) {
    const button = ensureProposalControls();
    const status = document.getElementById('proposalPrepareStatus');
    if (!button) return;

    proposalCase = response && response.case_id && response.case_token
      ? {case_id: response.case_id, case_token: response.case_token}
      : null;
    syncCaseIntoHalState();

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
          language: (state && state.language) || 'en'
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
})();
