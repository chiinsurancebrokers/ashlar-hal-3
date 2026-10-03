from __future__ import annotations
from copy import deepcopy
from backend.app.services.conversation_session import fact_find_summary, get_session
from backend.app.services.leads import send_lead
from backend.app.services.proposal_handoff import prefill_proposal_studio


def prepare_handoff(session_reference: str) -> dict:
    session = get_session(session_reference)
    summary = fact_find_summary(session)
    return {
        "session_reference": session_reference,
        "review_required": True,
        "transmission_allowed": session.consent_to_transmit,
        "fact_find": summary["facts"],
    }


async def submit_handoff(session_reference: str, reviewed_facts: dict, contact: dict) -> dict:
    session = get_session(session_reference)
    if not session.consent_to_transmit:
        raise PermissionError("Transmission consent is required before sending the Fact Find.")
    reviewed_session = session.model_copy(update={"state": deepcopy(reviewed_facts)})
    safe_facts = fact_find_summary(reviewed_session)["facts"]
    members = safe_facts.get("household_members") or []
    lead_payload = {
        "insurance_interest": "International Health Insurance",
        "first_name": str(contact.get("first_name") or ""),
        "last_name": str(contact.get("last_name") or ""),
        "email": str(contact.get("email") or ""),
        "phone": str(contact.get("phone") or ""),
        "residence_country": str(safe_facts.get("residence_country") or ""),
        "age": str(safe_facts.get("age") or ""),
        "coverage_area": str(safe_facts.get("coverage_area") or ""),
        "family_members": str(len(members) + 1 if safe_facts.get("family_requested") else ""),
        "budget": str(safe_facts.get("budget_annual") or ""),
        "message": "Reviewed HAL Fact Find",
        "consent": True,
        "fact_find": safe_facts,
    }
    lead = await send_lead(lead_payload, reference=session_reference)
    proposal = await prefill_proposal_studio(session_reference, safe_facts, contact)
    return {"status": "submitted", "session_reference": session_reference, "lead": lead, "proposal_studio": proposal}
