"""Saved HAL quotes, retrievable by reference number + date of birth.

Mirrors the Europesure model the brokerage already uses: the client saves a
quote, receives an email with a reference number and a link, and later
opens it with the reference and their date of birth.

* Prices are never taken from the browser: the snapshot is recomputed
  server-side from the client's answers with the same deterministic engine.
* The date of birth is stored only as an HMAC (keyed by a server secret and
  the reference), never in clear.
* Five wrong dates of birth lock the reference for 15 minutes.
* Storage: Supabase table public.hal_saved_quotes (server-side access only).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.rates.quote_engine import quote_shortlist
from backend.app.schemas.applicant import Applicant
from backend.app.services.household_quote_service import compose_verified_household, household_member_states

REFERENCE_RE = re.compile(r"^HAL-\d{8}-[A-Z0-9]{8}$")
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
_CARD_FIELDS = (
    "plan_key", "product_code", "product_name", "insurer", "premium", "currency", "card_badge",
    "card_annual_limit", "coverage_area_label", "card_coverage", "card_deductible", "card_evacuation",
    "benefit_checklist", "plan_documents", "household_card", "household_members", "family_size",
)
_NEED_FIELDS = (
    "outpatient_required", "maternity_required", "dental_required", "mental_health_required",
    "wellness_required", "optical_required", "evacuation_required", "chronic_required",
)
_STATE_FIELDS = (
    "applicant_name", "age", "sex", "nationality", "residence_country", "primary_healthcare_country",
    "coverage_area", "deductible", "budget_annual", "family_requested", "household_members",
    "household_complete", "discovery_complete", "language", "journey", *_NEED_FIELDS,
)


class SavedQuoteError(Exception):
    """Client-facing problem (bad input, not found, locked)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_reference(today: date | None = None) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return f"HAL-{(today or date.today()).strftime('%Y%m%d')}-{''.join(secrets.choice(alphabet) for _ in range(8))}"


def parse_dob(value: str) -> date:
    try:
        dob = date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise SavedQuoteError("Please enter a valid date of birth (YYYY-MM-DD).") from exc
    if dob > date.today() or dob.year < 1900:
        raise SavedQuoteError("Please enter a valid date of birth.")
    return dob


def age_on(dob: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _secret(settings: Settings) -> bytes:
    secret = settings.quote_retrieval_secret or settings.supabase_service_role_key
    if not secret:
        raise RuntimeError("Quote saving is not configured.")
    return secret.encode("utf-8")


def dob_hash(reference: str, dob: date, settings: Settings) -> str:
    return hmac.new(_secret(settings), f"{reference}|{dob.isoformat()}".encode(), hashlib.sha256).hexdigest()


def _rest(settings: Settings) -> tuple[str, dict[str, str]]:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Quote saving is not configured.")
    key = settings.supabase_service_role_key
    return (f"{settings.supabase_url.rstrip('/')}/rest/v1/hal_saved_quotes",
            {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})


def _applicant(state: dict[str, Any]) -> Applicant | None:
    fields = {k: v for k, v in state.items() if k in Applicant.model_fields}
    if not fields.get("age") or not fields.get("coverage_area"):
        return None
    try:
        return Applicant(**fields)
    except Exception:
        return None


def _trim_card(card: dict[str, Any]) -> dict[str, Any]:
    return {k: card.get(k) for k in _CARD_FIELDS if card.get(k) is not None}


# ---------------------------------------------------------------------------
# Snapshot (recomputed server-side)
# ---------------------------------------------------------------------------

def build_snapshot(state: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Recompute the quote from the client's answers. Raises if no verified
    price can be produced (nothing worth saving)."""
    from backend.app.services.family_live_orchestrator import (
        _household_plan_cards, _maternity_member_ids, _member_labels,
    )

    greek = state.get("language") == "el"
    needs = {k: bool(state.get(k)) for k in _NEED_FIELDS}
    family = bool(state.get("family_requested") and state.get("household_members"))

    if family:
        quotes_by_member: dict[str, list[dict]] = {}
        for member_id, member_state in household_member_states(state):
            applicant = _applicant(member_state)
            if applicant is None:
                raise SavedQuoteError("This quote is incomplete and cannot be saved yet.")
            quotes_by_member[member_id] = [q.model_dump(mode="json") for q in quote_shortlist(applicant, settings)]
        household = compose_verified_household(quotes_by_member, commercial_rules=[])
        if household["status"] != "verified_household_options":
            raise SavedQuoteError("A verified family price is not available, so this quote cannot be saved.")
        top = household["options"][0]
        labels, maternity = _member_labels(state, greek), _maternity_member_ids(state)
        cards = _household_plan_cards(top, quotes_by_member, labels, maternity, greek)
        breakdown = [{"member_id": a["member_id"], "label": labels.get(a["member_id"], a["member_id"]),
                      "product_name": a["product_name"], "insurer": a["insurer"], "premium": a["premium"],
                      "currency": a["currency"], "maternity": a["member_id"] in maternity}
                     for a in top["allocations"]]
        return {"kind": "household", "currency": top["currency"], "total_premium": top["total_premium"],
                "breakdown": breakdown, "cards": [_trim_card(c) for c in cards], "needs": needs}

    applicant = _applicant(state)
    if applicant is None:
        raise SavedQuoteError("This quote is incomplete and cannot be saved yet.")
    quotes = [q.model_dump(mode="json") for q in quote_shortlist(applicant, settings)]
    quotes = [q for q in quotes if q.get("premium") is not None]
    if not quotes:
        raise SavedQuoteError("No verified price is available, so this quote cannot be saved.")
    top = quotes[0]
    return {"kind": "individual", "currency": top.get("currency", "EUR"), "total_premium": round(float(top["premium"]), 2),
            "breakdown": [], "cards": [_trim_card(q) for q in quotes[:6]], "needs": needs}


# ---------------------------------------------------------------------------
# Save / retrieve
# ---------------------------------------------------------------------------

def save_quote(*, state: dict[str, Any], email: str, date_of_birth: str, consent: bool,
               public_base: str | None = None,
               settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not consent:
        raise SavedQuoteError("Please confirm that HAL may keep your quote.")
    if not state.get("discovery_complete"):
        raise SavedQuoteError("Please finish the questions before saving your quote.")
    dob = parse_dob(date_of_birth)
    stated_age = int(state.get("age") or 0)
    if abs(age_on(dob) - stated_age) > 1:
        raise SavedQuoteError(f"This date of birth does not match the age you gave ({stated_age}).")

    snapshot = build_snapshot(state, settings)
    reference = new_reference()
    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=settings.quote_validity_days)
    clean_state = {k: state.get(k) for k in _STATE_FIELDS if k in state}
    row = {
        "reference": reference, "valid_until": valid_until.isoformat(),
        "language": "el" if state.get("language") == "el" else "en",
        "journey": "ipmi", "applicant_name": (state.get("applicant_name") or "")[:80] or None,
        "email": email.strip()[:254], "dob_hash": dob_hash(reference, dob, settings),
        "consent_to_retain": True, "state_json": clean_state,
        "quote_json": {**snapshot, "quoted_on": now.date().isoformat(),
                       **({"public_base": public_base.rstrip("/")} if public_base else {})},
        "total_premium": snapshot["total_premium"], "currency": snapshot["currency"],
        "followup_consent": True,  # reminders about the saved quote; the client can unsubscribe
    }
    url, headers = _rest(settings)
    try:
        response = httpx.post(url, headers={**headers, "Prefer": "return=minimal"}, json=row, timeout=10)
    except httpx.HTTPError as exc:
        raise RuntimeError("The quote store is temporarily unavailable.") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"The quote store rejected the quote ({response.status_code}).")
    from backend.app.services.followups import schedule_followups
    try:
        schedule_followups(reference, saved_at=now, valid_until=valid_until, settings=settings)
        followups_scheduled = True
    except Exception:
        followups_scheduled = False  # the quote itself is saved; reminders are a bonus
    return {"reference": reference, "valid_until": valid_until.date().isoformat(), "snapshot": row["quote_json"],
            "language": row["language"], "applicant_name": row["applicant_name"],
            "followups_scheduled": followups_scheduled}


def _get_row(reference: str, settings: Settings) -> dict[str, Any] | None:
    url, headers = _rest(settings)
    try:
        response = httpx.get(url, headers=headers, params={"reference": f"eq.{reference}", "select": "*"}, timeout=10)
    except httpx.HTTPError as exc:
        raise RuntimeError("The quote store is temporarily unavailable.") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"The quote store returned {response.status_code}.")
    rows = response.json()
    return rows[0] if rows else None


def _patch(reference: str, changes: dict[str, Any], settings: Settings) -> None:
    url, headers = _rest(settings)
    try:
        httpx.patch(url, headers={**headers, "Prefer": "return=minimal"},
                    params={"reference": f"eq.{reference}"}, json=changes, timeout=10)
    except httpx.HTTPError:
        pass  # bookkeeping only; never block a retrieval on it


def retrieve_quote(*, reference: str, date_of_birth: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    reference = (reference or "").strip().upper()
    generic = SavedQuoteError("We could not find a quote with these details. Please check the reference "
                              "number and date of birth.", status=404)
    if not REFERENCE_RE.match(reference):
        raise generic
    dob = parse_dob(date_of_birth)
    row = _get_row(reference, settings)
    if not row or row.get("status") == "deleted":
        raise generic
    now = datetime.now(timezone.utc)
    locked_until = row.get("locked_until")
    if locked_until and datetime.fromisoformat(locked_until) > now:
        raise SavedQuoteError("Too many attempts. Please try again in a few minutes.", status=429)
    if not hmac.compare_digest(row["dob_hash"], dob_hash(reference, dob, settings)):
        failed = int(row.get("failed_attempts") or 0) + 1
        changes: dict[str, Any] = {"failed_attempts": failed}
        if failed >= MAX_FAILED_ATTEMPTS:
            changes.update(failed_attempts=0, locked_until=(now + timedelta(minutes=LOCK_MINUTES)).isoformat())
        _patch(reference, changes, settings)
        raise generic
    _patch(reference, {"failed_attempts": 0, "locked_until": None,
                       "retrieve_count": int(row.get("retrieve_count") or 0) + 1,
                       "last_retrieved_at": now.isoformat()}, settings)
    valid_until = datetime.fromisoformat(row["valid_until"])
    proposal = None
    try:
        from backend.app.services.lead_store import latest_proposal_for_saved_quote
        found = latest_proposal_for_saved_quote(reference, settings)
        if found and found.get("reference"):
            proposal = {"reference": found["reference"], "requested_at": found.get("created_at")}
    except Exception:
        proposal = None  # unknown: the page simply offers "Request a proposal"
    return {
        "reference": reference,
        "applicant_name": row.get("applicant_name"),
        "language": row.get("language", "en"),
        "created_at": row["created_at"],
        "valid_until": valid_until.date().isoformat(),
        "expired": valid_until < now,
        "status": row.get("status"),
        "quote": row.get("quote_json") or {},
        "state": row.get("state_json") or {},
        # Earlier proposal request for this quote (reference + time only).
        "proposal": proposal,
    }
