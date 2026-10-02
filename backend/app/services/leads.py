from __future__ import annotations
import base64
import html
from datetime import datetime, timezone
from email.message import EmailMessage
from uuid import uuid4

import httpx

from backend.app.core.config import get_settings, Settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.quote_engine import quote_current
from backend.app.schemas.quote import QuoteResult
from backend.app.services.current_policy_token import verify_current_policy_token


def _safe(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


async def _gmail_access_token() -> str:
    settings = get_settings()
    required = {
        "GMAIL_CLIENT_ID": settings.gmail_client_id, "GMAIL_CLIENT_SECRET": settings.gmail_client_secret,
        "GMAIL_REFRESH_TOKEN": settings.gmail_refresh_token,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError("Gmail OAuth is not configured: " + ", ".join(missing))

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": settings.gmail_client_id, "client_secret": settings.gmail_client_secret,
                  "refresh_token": settings.gmail_refresh_token, "grant_type": "refresh_token"},
        )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Google OAuth returned {response.status_code}: {(response.text or '')[:300]}")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Google OAuth did not return an access token.")
    return str(token)


async def _send_via_gmail(msg: EmailMessage) -> dict:
    token = await _gmail_access_token()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"raw": raw},
        )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Gmail API returned {response.status_code}: {(response.text or '')[:400]}")
    return response.json()


def _resend_configured(settings: Settings) -> bool:
    return bool(settings.resend_api_key and settings.resend_from_email)


def _resend_from(settings: Settings) -> str:
    return f"{settings.resend_from_name} <{settings.resend_from_email}>" if settings.resend_from_name else settings.resend_from_email


async def _send_via_resend(msg: EmailMessage) -> dict:
    settings = get_settings()
    if not _resend_configured(settings):
        raise RuntimeError("Resend delivery is not configured.")

    html_part = msg.get_body(preferencelist=("html",))
    plain_part = msg.get_body(preferencelist=("plain",))
    payload = {
        "from": msg.get("From") or _resend_from(settings),
        "to": [str(msg.get("To"))],
        "subject": str(msg.get("Subject") or ""),
        "text": plain_part.get_content() if plain_part else "",
    }
    if html_part:
        payload["html"] = html_part.get_content()
    if msg.get("Reply-To"):
        payload["reply_to"] = [str(msg.get("Reply-To"))]
    if msg.get("Bcc"):
        payload["bcc"] = [str(msg.get("Bcc"))]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Resend API returned {response.status_code}: {(response.text or '')[:400]}")
    result = response.json()
    return {"transport": "resend", "id": result.get("id")}


async def _send_transactional(msg: EmailMessage) -> dict:
    """Prefer Resend HTTPS; keep Gmail only as a temporary fallback."""
    settings = get_settings()
    if _resend_configured(settings):
        return await _send_via_resend(msg)
    result = await _send_via_gmail(msg)
    result["transport"] = "gmail"
    return result


def _mail_sender(settings: Settings) -> str:
    if _resend_configured(settings):
        return _resend_from(settings)
    if settings.gmail_sender_email:
        return settings.gmail_sender_email
    raise RuntimeError("No transactional email sender is configured.")


# ---------------------------------------------------------------------------
# Enquiry / lead emails (from the "Request a proposal" form)
# ---------------------------------------------------------------------------

def _build_lead_message(payload: dict, reference: str, sender: str, recipient: str) -> EmailMessage:
    submitted = datetime.now(timezone.utc).isoformat()
    name = " ".join(x for x in [payload.get("first_name", "").strip(), payload.get("last_name", "").strip()] if x)

    plain = f"""New Ashlar HAL enquiry

Reference: {reference}
Submitted: {submitted}

Insurance interest: {payload.get('insurance_interest', '')}
Name: {name}
Email: {payload.get('email', '')}
Phone: {payload.get('phone', '')}
Residence: {payload.get('residence_country', '')}
Age: {payload.get('age', '')}

Coverage area / destination: {payload.get('coverage_area', '')}
Family / travellers: {payload.get('family_members', '')}
Approx. budget: {payload.get('budget', '')}

Applicant note:
{payload.get('message', '')}

Consent recorded: {'Yes' if payload.get('consent') else 'No'}
"""
    html_body = f"""<html><body style="font-family:Arial,sans-serif">
    <h2>New Ashlar HAL enquiry</h2>
    <p>Reference: <strong>{_safe(reference)}</strong></p>
    <p><strong>Interest:</strong> {_safe(payload.get('insurance_interest', ''))}</p>
    <p><strong>Name:</strong> {_safe(name)}<br>
    <strong>Email:</strong> {_safe(payload.get('email', ''))}<br>
    <strong>Residence:</strong> {_safe(payload.get('residence_country', ''))}<br>
    <strong>Age:</strong> {_safe(payload.get('age', ''))}</p>
    <p><strong>Note:</strong> {_safe(payload.get('message', ''))}</p>
    </body></html>"""

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"New HAL Lead — {payload.get('insurance_interest', 'Insurance Enquiry')} — {reference}"[:240]
    if payload.get("email"):
        msg["Reply-To"] = str(payload["email"]).strip()
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")
    return msg


async def send_lead(payload: dict) -> dict:
    settings = get_settings()
    if not settings.gmail_lead_recipient:
        raise RuntimeError("Lead recipient is not configured.")
    reference = f"HAL-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    msg = _build_lead_message(payload, reference, _mail_sender(settings), settings.gmail_lead_recipient)
    if _resend_configured(settings) and settings.resend_reply_to:
        msg["Reply-To"] = settings.resend_reply_to
    result = await _send_transactional(msg)
    return {
        "status": "sent",
        "reference": reference,
        "transport": result.get("transport", "gmail"),
        "message_id": result.get("id"),
    }


# ---------------------------------------------------------------------------
# Comparison emails — SERVER-SIDE RE-VERIFICATION
#
# The client sends `plan_keys` (which plans were selected) and the raw
# `applicant_state` (age, residence, requirements etc) — never a premium.
# We recompute the shortlist here, server-side, from the real rate table,
# and only ever put SERVER-COMPUTED numbers in the email. A client cannot
# make HAL send a forged "€868" comparison for a plan that actually costs
# €6,868 — the browser's numbers are advisory UI only, never authoritative.
# ---------------------------------------------------------------------------

def _verified_plans_for(applicant_state: dict, plan_keys: list[str], settings: Settings) -> list[QuoteResult]:
    fields = {k: v for k, v in (applicant_state or {}).items() if k in Applicant.model_fields}
    applicant = Applicant(**fields)
    all_current = quote_current(applicant, settings)
    by_key = {q.plan_key: q for q in all_current if q.plan_key}
    selected = [by_key[k] for k in plan_keys if k in by_key]
    if not selected:
        raise ValueError("None of the requested plan_keys match a currently eligible plan for this applicant.")
    return selected


def _build_comparison_message(
    name: str,
    email: str,
    plans: list[QuoteResult],
    sender: str,
    bcc: str | None,
    current_policy: dict | None = None,
) -> EmailMessage:
    top = plans[0]
    rows = ""
    plain_lines = ["Your Ashlar health insurance comparison", ""]

    if current_policy:
        premium = current_policy.get("premium") or {}
        cp_amount = premium.get("amount")
        cp_currency = premium.get("currency") or ""
        cp_premium = f"{cp_currency} {float(cp_amount):,.2f}" if cp_amount not in (None, "") else "Not confirmed"
        cp_limit = current_policy.get("annual_limit") or "Not confirmed"
        cp_name = current_policy.get("plan_name") or "Current policy"
        cp_provider = current_policy.get("provider") or "Current insurer"
        cp_area = current_policy.get("area_of_cover") or "Not confirmed"
        cp_deductible = current_policy.get("deductible_or_excess") or "Not confirmed"
        rows += f"""<tr style='background:#f7f8fa'>
          <td style='padding:12px;border-bottom:1px solid #e7ebef'><strong>Current policy: {_safe(cp_name)}</strong><br><span>{_safe(cp_provider)}</span></td>
          <td style='padding:12px;border-bottom:1px solid #e7ebef'>{_safe(cp_premium)}</td>
          <td style='padding:12px;border-bottom:1px solid #e7ebef'>{_safe(cp_limit)}</td>
          <td style='padding:12px;border-bottom:1px solid #e7ebef'>Area: {_safe(cp_area)}<br>Deductible: {_safe(cp_deductible)}</td>
        </tr>"""
        plain_lines += [
            f"Current policy: {cp_name} — {cp_provider}",
            f"Annual premium: {cp_premium}",
            f"Area: {cp_area}",
            f"Annual limit: {cp_limit}",
            f"Deductible: {cp_deductible}",
            "",
        ]

    rows += "".join(f"""<tr>
      <td style='padding:12px;border-bottom:1px solid #e7ebef'><strong>{_safe(p.product_name)}</strong><br><span>{_safe(p.insurer)}</span></td>
      <td style='padding:12px;border-bottom:1px solid #e7ebef'>{_safe(p.currency)} {p.premium:,.2f}</td>
      <td style='padding:12px;border-bottom:1px solid #e7ebef'>{_safe(p.card_annual_limit)}</td>
      <td style='padding:12px;border-bottom:1px solid #e7ebef'>{_safe(p.card_why)}</td>
    </tr>""" for p in plans)

    for i, p in enumerate(plans, 1):
        plain_lines += [f"{i}. {p.product_name} — {p.insurer}", f"Annual premium: {p.currency} {p.premium:,.2f}", ""]

    html_body = f"""<html><body style='font-family:Arial,sans-serif'>
    <div style='max-width:760px;margin:auto'>
      <div style='font-weight:700'>ASHLAR ASSURANCE</div>
      <h1>Your health insurance comparison</h1>
      <p>Dear {_safe(name) if name else 'Client'},</p>
      <p>Following your HAL session, here is the shortlist you asked us to send you.</p>
      <p style='background:#f3f0ff;border-radius:12px;padding:14px'><strong>HAL's current top option:</strong> {_safe(top.product_name)} — {_safe(top.insurer)}</p>
      <table style='border-collapse:collapse;width:100%;font-size:13px'>
        <thead><tr><th align='left'>Plan</th><th align='left'>Premium</th><th align='left'>Annual limit</th><th align='left'>Why it may fit</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style='font-size:12px;color:#697789'>This is an indicative comparison, not confirmation of cover. All figures were recalculated by Ashlar's server at send time. Final premiums, eligibility, underwriting and policy terms remain subject to insurer confirmation.</p>
      <p>Kind regards,<br><strong>Ashlar Assurance</strong></p>
    </div></body></html>"""

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = email
    if bcc and bcc.lower() != email.lower():
        msg["Bcc"] = bcc
    msg["Subject"] = f"Your Ashlar international health insurance comparison{(' — ' + name) if name else ''}"[:240]
    msg.set_content("\n".join(plain_lines))
    msg.add_alternative(html_body, subtype="html")
    return msg


async def send_comparison_email(
    name: str,
    email: str,
    applicant_state: dict,
    plan_keys: list[str],
    current_policy_token: str | None = None,
) -> dict:
    settings = get_settings()

    # Re-verify plan prices and eligibility server-side. Current-policy facts
    # are accepted only from HAL's signed token created immediately after
    # Proposal Studio analysis; arbitrary browser-edited policy data is ignored.
    plans = _verified_plans_for(applicant_state, plan_keys, settings)
    current_policy = None
    if current_policy_token:
        current_policy = verify_current_policy_token(current_policy_token)

    msg = _build_comparison_message(
        name, email, plans, _mail_sender(settings),
        settings.gmail_lead_recipient, current_policy=current_policy,
    )
    if _resend_configured(settings) and settings.resend_reply_to:
        msg["Reply-To"] = settings.resend_reply_to
    result = await _send_transactional(msg)
    return {
        "status": "sent",
        "transport": result.get("transport", "gmail"),
        "message_id": result.get("id"),
        "plans_sent": [p.plan_key for p in plans],
        "current_policy_included": bool(current_policy),
    }
