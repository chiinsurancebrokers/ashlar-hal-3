from __future__ import annotations


async def prefill_proposal_studio(session_reference: str, facts: dict, contact: dict) -> dict:
    """Fail closed until Proposal Studio publishes a case/prefill contract."""
    return {
        "status": "contract_unavailable",
        "session_reference": session_reference,
        "reason": "Proposal Studio has no published HAL case/prefill API contract yet.",
    }
