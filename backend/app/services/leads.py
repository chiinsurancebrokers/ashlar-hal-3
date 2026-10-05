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
    required = {"GMAIL_CLIENT_ID": settings.gmail_client_id, "GMAIL_CLIENT_SECRET": settings.gmail_client_secret, "GMAIL_REFRESH_TOKEN": settings.gmail_refresh_token}
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError("Gmail OAuth is not configured: " + ", ".join(missing))
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={"client_id": settings.gmail_client_id, "client_secret": settings.gmail_client_secret, "refresh_token": settings.gmail_refresh_token, "grant_type": "refresh_token"})
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
        response = await client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"raw": raw})
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
    html_part = msg.get_body(preferencelist=("html",)); plain_part = msg.get_body(preferencelist=("plain",))
    payload = {"from": msg.get("From") or _resend_from(settings), "to": [str(msg.get("To"))], "subject": str(msg.get("Subject") or ""), "text": plain_part.get_content() if plain_part else ""}
    if html_part: payload["html"] = html_part.get_content()
    if msg.get("Reply-To"): payload["reply_to"] = [str(msg.get("Reply-To"))]
    if msg.get("Bcc"): payload["bcc"] = [str(msg.get("Bcc"))]
    extra = {h: str(msg.get(h)) for h in ("List-Unsubscribe", "List-Unsubscribe-Post") if msg.get(h)}
    if extra: payload["headers"] = extra
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"}, json=payload)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Resend API returned {response.status_code}: {(response.text or '')[:400]}")
    result = response.json(); return {"transport": "resend", "id": result.get("id")}


async def _send_transactional(msg: EmailMessage) -> dict:
    settings = get_settings()
    if _resend_configured(settings): return await _send_via_resend(msg)
    result = await _send_via_gmail(msg); result["transport"] = "gmail"; return result


def _mail_sender(settings: Settings) -> str:
    if _resend_configured(settings): return _resend_from(settings)
    if settings.gmail_sender_email: return settings.gmail_sender_email
    raise RuntimeError("No transactional email sender is configured.")


_NEED_LABELS = [
    ("outpatient_required", "Out-patient"), ("maternity_required", "Maternity"),
    ("dental_required", "Dental"), ("mental_health_required", "Mental health"),
    ("wellness_required", "Wellness / check-ups"), ("optical_required", "Optical"),
    ("evacuation_required", "Medical evacuation"), ("chronic_required", "Chronic condition cover"),
]


def _fmt_money(amount: object, currency: object) -> str:
    try:
        return f"{currency or 'EUR'} {float(amount):,.2f}"
    except (TypeError, ValueError):
        return ""


def _context_sections(ctx: dict) -> tuple[list[tuple[str, list[str]]], str]:
    """Turn the HAL conversation context into email sections.

    Everything here is what HAL showed the applicant on screen; prices are
    labelled indicative. Returns [(heading, lines)] for plain text and the
    same content as HTML.
    """
    if not isinstance(ctx, dict) or not ctx:
        return [], ""
    sections: list[tuple[str, list[str]]] = []

    profile = []
    for key, label in [("applicant_name", "Name given to HAL"), ("age", "Age"), ("sex", "Sex"),
                       ("nationality", "Nationality"), ("residence_country", "Residence"),
                       ("primary_healthcare_country", "Main healthcare country"),
                       ("coverage_area", "Area of cover"), ("deductible", "Deductible"),
                       ("budget", "Budget")]:
        value = ctx.get(key)
        if value not in (None, "", []):
            profile.append(f"{label}: {value}")
    if ctx.get("residency_purpose") is True:
        profile.append("Needs cover for a visa / residence permit: YES — check the authority's insurance requirement")
    if profile:
        sections.append(("Applicant profile", profile))

    needs = ctx.get("needs") if isinstance(ctx.get("needs"), dict) else {}
    if needs:
        wanted = [label for key, label in _NEED_LABELS if needs.get(key) is True]
        declined = [label for key, label in _NEED_LABELS if needs.get(key) is False]
        lines = [f"Requested: {', '.join(wanted) or 'None beyond in-patient'}"]
        if declined:
            lines.append(f"Declined: {', '.join(declined)}")
        if needs.get("chronic_conditions_disclosed"):
            lines.append("Applicant indicated an existing medical condition — underwriting review needed.")
        sections.append(("Requirements", lines))

    members = ctx.get("household_members") if isinstance(ctx.get("household_members"), list) else []
    if members:
        lines = []
        for m in members[:12]:
            if not isinstance(m, dict):
                continue
            bits = [str(m.get("relationship", "member")).capitalize()]
            if m.get("age") is not None:
                bits.append(f"age {m['age']}")
            if m.get("sex"):
                bits.append(str(m["sex"]))
            if m.get("maternity_required"):
                bits.append("maternity required")
            lines.append(", ".join(bits))
        if lines:
            sections.append(("Family members", lines))

    breakdown = ctx.get("household_breakdown") if isinstance(ctx.get("household_breakdown"), list) else []
    if breakdown:
        lines, total, currency = [], 0.0, None
        for b in breakdown[:12]:
            if not isinstance(b, dict):
                continue
            note = " (maternity)" if b.get("maternity") else ""
            lines.append(f"{b.get('label', b.get('member_id', ''))}: {b.get('product_name', '')}{note} — "
                         f"{_fmt_money(b.get('premium'), b.get('currency'))}")
            try:
                total += float(b.get("premium") or 0)
            except (TypeError, ValueError):
                pass
            currency = currency or b.get("currency")
        lines.append(f"Household total (indicative): {_fmt_money(total, currency)}")
        sections.append(("HAL household composition", lines))

    shortlist = ctx.get("shortlist") if isinstance(ctx.get("shortlist"), list) else []
    if shortlist:
        lines = []
        for q in shortlist[:6]:
            if not isinstance(q, dict):
                continue
            lines.append(f"{q.get('product_name', '')} — {q.get('insurer', '')}: "
                         f"{_fmt_money(q.get('premium'), q.get('currency'))}/year")
        if lines:
            sections.append(("Plans shown to the applicant", lines))

    plan_docs = ctx.get("plan_documents") if isinstance(ctx.get("plan_documents"), list) else []
    doc_lines: list[str] = []
    doc_html_items: list[str] = []
    for plan in plan_docs[:6]:
        if not isinstance(plan, dict):
            continue
        for doc in (plan.get("documents") or [])[:4]:
            url = str((doc or {}).get("url") or "")
            if not url.startswith("https://"):
                continue
            label = f"{plan.get('product_name', '')} — {doc.get('label', 'Document')}"
            doc_lines.append(f"{label}: {url}")
            doc_html_items.append(f"<li><a href='{_safe(url)}'>{_safe(label)}</a></li>")

    if ctx.get("saved_quote_reference"):
        sections.insert(0, ("Saved HAL quote", [f"{ctx['saved_quote_reference']} (client can reopen it with their date of birth)"]))

    if ctx.get("session_reference"):
        sections.append(("HAL session", [str(ctx["session_reference"])]))

    if doc_lines:
        sections.append(("Plan documents", doc_lines))
    html_parts = "".join(
        f"<h3 style='margin:18px 0 6px'>{_safe(h)}</h3><ul style='margin:0;padding-left:18px'>"
        + "".join(f"<li>{_safe(line)}</li>" for line in lines) + "</ul>"
        for h, lines in sections if h != "Plan documents"
    )
    if doc_html_items:
        html_parts += ("<h3 style='margin:18px 0 6px'>Plan documents</h3><ul style='margin:0;padding-left:18px'>"
                       + "".join(doc_html_items) + "</ul>")
    return sections, html_parts


def _build_lead_message(payload: dict, reference: str, sender: str, recipient: str) -> EmailMessage:
    submitted = datetime.now(timezone.utc).isoformat()
    name = " ".join(x for x in [payload.get("first_name", "").strip(), payload.get("last_name", "").strip()] if x)
    fact_find = payload.get("fact_find") if isinstance(payload.get("fact_find"), dict) else {}
    fact_lines = "\n".join(f"- {k}: {v}" for k, v in fact_find.items())
    sections, context_html = _context_sections(payload.get("hal_context") or {})
    context_plain = "\n\n".join(h + ":\n" + "\n".join(f"- {l}" for l in lines) for h, lines in sections)

    contact_rows = [
        ("Interest", payload.get("insurance_interest", "")), ("Name", name),
        ("Email", payload.get("email", "")), ("Phone", payload.get("phone", "")),
        ("Residence", payload.get("residence_country", "")), ("Age", payload.get("age", "")),
        ("Coverage area / destination", payload.get("coverage_area", "")),
        ("Family / travellers", payload.get("family_members", "")),
        ("Approx. budget", payload.get("budget", "")),
    ]
    plain = (
        "New Ashlar HAL enquiry\n\n"
        f"Reference: {reference}\nSubmitted: {submitted}\n\n"
        + "\n".join(f"{k}: {v}" for k, v in contact_rows)
        + "\n\n"
        + (context_plain + "\n\n" if context_plain else "")
        + ("Reviewed structured Fact Find:\n" + fact_lines + "\n\n" if fact_lines else "")
        + f"Applicant note:\n{payload.get('message', '') or '—'}\n\n"
        + f"Consent recorded: {'Yes' if payload.get('consent') else 'No'}\n"
        + "Prices are indicative figures shown by HAL and remain subject to insurer underwriting and confirmation.\n"
    )
    contact_html = "".join(
        f"<tr><td style='padding:3px 12px 3px 0;color:#555'>{_safe(k)}</td><td style='padding:3px 0'><strong>{_safe(v) or '—'}</strong></td></tr>"
        for k, v in contact_rows
    )
    fact_html = (
        "<h3 style='margin:18px 0 6px'>Reviewed Fact Find</h3><ul style='margin:0;padding-left:18px'>"
        + "".join(f"<li>{_safe(k)}: {_safe(v)}</li>" for k, v in fact_find.items()) + "</ul>"
    ) if fact_find else ""
    html_body = (
        "<html><body style='font-family:Arial,sans-serif;color:#172333;font-size:14px'>"
        "<h2 style='margin-bottom:4px'>New Ashlar HAL enquiry</h2>"
        f"<p style='margin-top:0'>Reference: <strong>{_safe(reference)}</strong></p>"
        f"<table style='border-collapse:collapse'>{contact_html}</table>"
        f"{context_html}{fact_html}"
        f"<h3 style='margin:18px 0 6px'>Applicant note</h3><p style='margin:0'>{_safe(payload.get('message', '')) or '—'}</p>"
        f"<p style='margin-top:18px;color:#687586;font-size:12px'>Consent recorded: {'Yes' if payload.get('consent') else 'No'}. "
        "Prices are indicative figures shown by HAL and remain subject to insurer underwriting and confirmation.</p>"
        "</body></html>"
    )
    msg = EmailMessage(); msg["From"] = sender; msg["To"] = recipient; msg["Subject"] = f"New HAL Lead — {payload.get('insurance_interest','Insurance Enquiry')} — {reference}"[:240]
    if payload.get("email"): msg["Reply-To"] = str(payload["email"]).strip()
    msg.set_content(plain); msg.add_alternative(html_body, subtype="html"); return msg


async def send_lead(payload: dict, *, reference: str | None = None) -> dict:
    settings = get_settings()
    if not settings.gmail_lead_recipient: raise RuntimeError("Lead recipient is not configured.")
    reference = reference or f"HAL-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    msg = _build_lead_message(payload, reference, _mail_sender(settings), settings.gmail_lead_recipient)
    result = await _send_transactional(msg)
    return {"status": "sent", "reference": reference, "transport": result.get("transport", "gmail"), "message_id": result.get("id")}


def _verified_plans_for(applicant_state: dict, plan_keys: list[str], settings: Settings) -> list[QuoteResult]:
    fields = {k: v for k, v in (applicant_state or {}).items() if k in Applicant.model_fields}; applicant = Applicant(**fields); all_current = quote_current(applicant, settings); by_key = {q.plan_key: q for q in all_current if q.plan_key}; selected = [by_key[k] for k in plan_keys if k in by_key]
    if not selected: raise ValueError("None of the requested plan_keys match a currently eligible plan for this applicant.")
    return selected


def _build_comparison_message(name: str, email: str, plans: list[QuoteResult], sender: str, bcc: str | None, current_policy: dict | None = None) -> EmailMessage:
    top = plans[0]; rows = ""; plain_lines = ["Your Ashlar health insurance comparison", ""]
    if current_policy:
        premium = current_policy.get("premium") or {}; cp_amount = premium.get("amount"); cp_currency = premium.get("currency") or ""; cp_premium = f"{cp_currency} {float(cp_amount):,.2f}" if cp_amount not in (None, "") else "Not confirmed"; cp_limit = current_policy.get("annual_limit") or "Not confirmed"; cp_name = current_policy.get("plan_name") or "Current policy"; cp_provider = current_policy.get("provider") or "Current insurer"; cp_area = current_policy.get("area_of_cover") or "Not confirmed"; cp_deductible = current_policy.get("deductible_or_excess") or "Not confirmed"
        rows += f"<tr><td><strong>Current policy: {_safe(cp_name)}</strong><br>{_safe(cp_provider)}</td><td>{_safe(cp_premium)}</td><td>{_safe(cp_limit)}</td><td>Area: {_safe(cp_area)}<br>Deductible: {_safe(cp_deductible)}</td></tr>"; plain_lines += [f"Current policy: {cp_name} — {cp_provider}", f"Annual premium: {cp_premium}", ""]
    rows += "".join(f"<tr><td><strong>{_safe(p.product_name)}</strong><br>{_safe(p.insurer)}</td><td>{_safe(p.currency)} {p.premium:,.2f}</td><td>{_safe(p.card_annual_limit)}</td><td>{_safe(p.card_why)}</td></tr>" for p in plans)
    for i,p in enumerate(plans,1): plain_lines += [f"{i}. {p.product_name} — {p.insurer}", f"Annual premium: {p.currency} {p.premium:,.2f}", ""]
    html_body = f"<html><body><h1>Your health insurance comparison</h1><p>Dear {_safe(name) if name else 'Client'},</p><p>HAL's current top option: {_safe(top.product_name)} — {_safe(top.insurer)}</p><table>{rows}</table><p>This is an indicative comparison, not confirmation of cover. Final premiums, eligibility, underwriting and policy terms remain subject to insurer confirmation.</p></body></html>"
    msg=EmailMessage(); msg["From"]=sender; msg["To"]=email
    if bcc and bcc.lower()!=email.lower(): msg["Bcc"]=bcc
    msg["Subject"]=f"Your Ashlar international health insurance comparison{(' — '+name) if name else ''}"[:240]; msg.set_content("\n".join(plain_lines)); msg.add_alternative(html_body, subtype="html"); return msg


async def send_comparison_email(name: str, email: str, applicant_state: dict, plan_keys: list[str], current_policy_token: str | None = None) -> dict:
    settings=get_settings(); plans=_verified_plans_for(applicant_state,plan_keys,settings); current_policy=verify_current_policy_token(current_policy_token) if current_policy_token else None; msg=_build_comparison_message(name,email,plans,_mail_sender(settings),settings.gmail_lead_recipient,current_policy=current_policy)
    if _resend_configured(settings) and settings.resend_reply_to: msg["Reply-To"]=settings.resend_reply_to
    result=await _send_transactional(msg); return {"status":"sent","transport":result.get("transport","gmail"),"message_id":result.get("id"),"plans_sent":[p.plan_key for p in plans],"current_policy_included":bool(current_policy)}


# ---------------------------------------------------------------------------
# Saved-quote email to the client (reference + retrieve link)
# ---------------------------------------------------------------------------

def _build_saved_quote_message(saved: dict, email: str, retrieve_url: str, sender: str, bcc: str | None) -> EmailMessage:
    greek = saved.get("language") == "el"
    snap = saved.get("snapshot") or {}
    ref, name = saved["reference"], saved.get("applicant_name") or ""
    currency = snap.get("currency", "EUR")
    total = f"{currency} {float(snap.get('total_premium') or 0):,.2f}"
    valid = saved.get("valid_until", "")
    try:
        from datetime import date as _date
        _d = _date.fromisoformat(valid)
        valid = _d.strftime("%d/%m/%Y") if saved.get("language") == "el" else f"{_d.day} {_d.strftime('%B %Y')}"
    except ValueError:
        pass
    if snap.get("kind") == "household":
        lines = [f"{b['label']}: {b['product_name']} — {b['currency']} {float(b['premium']):,.2f}" for b in snap.get("breakdown", [])]
    else:
        cards = snap.get("cards") or []
        lines = [f"{c.get('product_name')} ({c.get('insurer')}) — {c.get('currency', currency)} {float(c.get('premium') or 0):,.2f}" for c in cards[:3]]
    if greek:
        subject = f"Η προσφορά σας από τον HAL — {ref}"
        hello = f"Αγαπητέ/ή {name}," if name else "Γεια σας,"
        intro = "Αποθηκεύσαμε την προσφορά ασφάλισης υγείας που υπολογίσατε με τον HAL."
        labels = ("Αριθμός προσφοράς", "Σύνολο" if snap.get("kind") == "household" else "Πρώτη επιλογή", "Ισχύει έως")
        steps = ["Πατήστε τον σύνδεσμο παρακάτω.", "Ο αριθμός προσφοράς είναι ήδη συμπληρωμένος· βάλτε την ημερομηνία γέννησής σας.",
                 "Δείτε την προσφορά σας και, αν θέλετε, ζητήστε πρόταση από την Ashlar."]
        button, howto = "Άνοιγμα της προσφοράς μου", "Πώς ανοίγετε την προσφορά σας"
        footer = ("Η προσφορά είναι ενδεικτική· η τελική τιμή, η αποδοχή και οι όροι ορίζονται από τον ασφαλιστή μετά την αίτηση. "
                  "Δεν χρειάζεται να απαντήσετε σε αυτό το email — για οποιαδήποτε ερώτηση, απαντήστε και θα σας καλέσουμε.")
    else:
        subject = f"Your HAL quote — {ref}"
        hello = f"Dear {name}," if name else "Hello,"
        intro = "We have saved the health insurance quote you calculated with HAL."
        labels = ("Quote reference", "Total" if snap.get("kind") == "household" else "Top option", "Valid until")
        steps = ["Click the link below.", "Your quote reference is already filled in; enter your date of birth.",
                 "View your quote and, if you like, request a proposal from Ashlar."]
        button, howto = "Open my quote", "How to open your quote"
        footer = ("This quote is indicative; the final premium, acceptance and terms are set by the insurer after application. "
                  "Questions? Just reply to this email and we will call you.")
    plain = "\n".join([hello, "", intro, "", f"{labels[0]}: {ref}", f"{labels[1]}: {total}", f"{labels[2]}: {valid}", "",
                       *[f"- {l}" for l in lines], "", howto + ":", *[f"{i}. {s}" for i, s in enumerate(steps, 1)], "",
                       retrieve_url, "", footer, "", "Ashlar Assurance"])
    rows = "".join(f"<li style='margin:2px 0'>{_safe(l)}</li>" for l in lines)
    step_html = "".join(f"<li style='margin:4px 0'>{_safe(s)}</li>" for s in steps)
    html_body = (
        "<html><body style='font-family:Arial,sans-serif;color:#172333;font-size:14px;line-height:1.5'>"
        f"<p>{_safe(hello)}</p><p>{_safe(intro)}</p>"
        "<table style='border-collapse:collapse;margin:8px 0 12px'>"
        f"<tr><td style='padding:3px 14px 3px 0;color:#687586'>{_safe(labels[0])}</td><td><strong style='font-size:16px'>{_safe(ref)}</strong></td></tr>"
        f"<tr><td style='padding:3px 14px 3px 0;color:#687586'>{_safe(labels[1])}</td><td><strong>{_safe(total)}</strong></td></tr>"
        f"<tr><td style='padding:3px 14px 3px 0;color:#687586'>{_safe(labels[2])}</td><td>{_safe(valid)}</td></tr></table>"
        f"<ul style='margin:0 0 14px;padding-left:18px'>{rows}</ul>"
        f"<p style='margin:0 0 4px'><strong>{_safe(howto)}</strong></p><ol style='margin:0 0 16px;padding-left:20px'>{step_html}</ol>"
        f"<p><a href='{_safe(retrieve_url)}' style='display:inline-block;background:#0f1a2b;color:#fff;padding:11px 18px;border-radius:10px;text-decoration:none;font-weight:bold'>{_safe(button)}</a></p>"
        f"<p style='color:#687586;font-size:12px;margin-top:18px'>{_safe(footer)}</p><p>Ashlar Assurance</p></body></html>"
    )
    msg = EmailMessage(); msg["From"] = sender; msg["To"] = email; msg["Subject"] = subject
    if bcc and bcc.lower() != email.lower():
        msg["Bcc"] = bcc
    msg.set_content(plain); msg.add_alternative(html_body, subtype="html"); return msg


async def send_saved_quote_email(saved: dict, email: str, retrieve_url: str) -> dict:
    settings = get_settings()
    msg = _build_saved_quote_message(saved, email, retrieve_url, _mail_sender(settings), settings.gmail_lead_recipient)
    if _resend_configured(settings) and settings.resend_reply_to:
        msg["Reply-To"] = settings.resend_reply_to
    result = await _send_transactional(msg)
    return {"status": "sent", "transport": result.get("transport", "gmail"), "message_id": result.get("id")}
