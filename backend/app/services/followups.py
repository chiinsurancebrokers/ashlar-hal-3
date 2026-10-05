"""Follow-up and reminder emails for saved HAL quotes.

Sent to every client who saves a quote (the save consent covers contact
about the quote); every email carries an unsubscribe link.

Sequence (per saved quote, at most two emails):
* ``checkin`` — a few days after saving: "any questions?"
* ``expiry``  — a few days before the quote expires

Stops automatically when the client unsubscribes, requests a proposal
(an adviser has taken over) or the quote is deleted.

Writing: Claude writes the opening paragraph from the quote facts only. The
paragraph is rejected (and a fixed text used instead) if it contains any
number that is not in the facts, sales-pressure words, or the wrong language.
Everything else in the email (reference, price, links, disclaimer,
unsubscribe link) is fixed text.

Sending: a background loop claims due rows through the Postgres function
``claim_hal_followups`` (FOR UPDATE SKIP LOCKED), so several app replicas
never send the same email twice.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import httpx

from backend.app.core.config import Settings, get_settings

log = logging.getLogger("hal.followups")

KINDS = ("checkin", "expiry")
MAX_ATTEMPTS = 3
_FORBIDDEN = re.compile(
    r"guarantee|discount|\bfree\b|best price|cheapest|last chance|urgent|act now|hurry|limited time|"
    r"εγγυ|έκπτωσ|εκπτωσ|δωρεάν|δωρεαν|επείγ|επειγ|τελευταία ευκαιρία|τελευταια ευκαιρια|βιαστείτε|βιαστειτε",
    re.I,
)
_GREETING = re.compile(r"^(dear|hello|hi|αγαπητ|γεια)\b[^\n]*\n+", re.I)


# ---------------------------------------------------------------------------
# Supabase REST helpers
# ---------------------------------------------------------------------------

def _base(settings: Settings) -> tuple[str, dict[str, str]]:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Follow-ups are not configured.")
    key = settings.supabase_service_role_key
    return (f"{settings.supabase_url.rstrip('/')}/rest/v1",
            {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})


def _secret(settings: Settings) -> bytes:
    secret = settings.quote_retrieval_secret or settings.supabase_service_role_key
    if not secret:
        raise RuntimeError("Follow-ups are not configured.")
    return secret.encode("utf-8")


def unsubscribe_token(reference: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return hmac.new(_secret(settings), f"unsubscribe|{reference}".encode(), hashlib.sha256).hexdigest()[:32]


def valid_unsubscribe_token(reference: str, token: str, settings: Settings | None = None) -> bool:
    return hmac.compare_digest(unsubscribe_token(reference, settings), (token or "").strip())


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def plan_schedule(*, saved_at: datetime, valid_until: datetime, settings: Settings) -> list[tuple[str, datetime]]:
    """Return [(kind, when)] for a newly saved quote."""
    if settings.followup_fast_mode:
        return [("checkin", saved_at + timedelta(minutes=2)), ("expiry", saved_at + timedelta(minutes=4))]
    checkin = saved_at + timedelta(days=settings.followup_checkin_days)
    steps = [("checkin", checkin)]
    expiry = valid_until - timedelta(days=settings.followup_expiry_days_before)
    if expiry > checkin + timedelta(days=2):
        steps.append(("expiry", expiry))
    return steps


def schedule_followups(reference: str, *, saved_at: datetime, valid_until: datetime,
                       settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    rows = [{"reference": reference, "kind": kind, "scheduled_for": when.isoformat()}
            for kind, when in plan_schedule(saved_at=saved_at, valid_until=valid_until, settings=settings)]
    url, headers = _base(settings)
    response = httpx.post(f"{url}/hal_followups", params={"on_conflict": "reference,kind"},
                          headers={**headers, "Prefer": "resolution=ignore-duplicates,return=minimal"},
                          json=rows, timeout=10)
    if response.status_code >= 400:
        raise RuntimeError(f"Could not schedule follow-ups ({response.status_code}).")
    return rows


def cancel_followups(reference: str, reason: str, settings: Settings | None = None) -> None:
    """Cancel every follow-up still waiting for this quote (best effort)."""
    settings = settings or get_settings()
    url, headers = _base(settings)
    httpx.patch(f"{url}/hal_followups", headers={**headers, "Prefer": "return=minimal"},
                params={"reference": f"eq.{reference}", "status": "eq.scheduled"},
                json={"status": "cancelled", "error": reason[:200]}, timeout=10)


def unsubscribe(reference: str, token: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    from backend.app.services.saved_quotes import REFERENCE_RE
    reference = (reference or "").strip().upper()
    if not REFERENCE_RE.match(reference) or not valid_unsubscribe_token(reference, token, settings):
        return False
    url, headers = _base(settings)
    httpx.patch(f"{url}/hal_saved_quotes", headers={**headers, "Prefer": "return=minimal"},
                params={"reference": f"eq.{reference}"},
                json={"unsubscribed_at": datetime.now(timezone.utc).isoformat(), "followup_consent": False},
                timeout=10)
    cancel_followups(reference, "unsubscribed", settings)
    return True


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _fmt_date(value: str | date, greek: bool) -> str:
    d = value if isinstance(value, date) else datetime.fromisoformat(str(value)).date()
    if greek:
        return d.strftime("%d/%m/%Y")
    return f"{d.day} {d.strftime('%B %Y')}"


def _money(amount: Any, currency: str, greek: bool) -> str:
    text = f"{float(amount or 0):,.2f}"
    if greek:
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{currency} {text}"


def quote_facts(row: dict[str, Any], kind: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    greek = row.get("language") == "el"
    quote = row.get("quote_json") or {}
    state = row.get("state_json") or {}
    currency = quote.get("currency") or row.get("currency") or "EUR"
    valid_until = datetime.fromisoformat(row["valid_until"])
    if quote.get("kind") == "household":
        plans = [f"{b.get('label')}: {b.get('product_name')} ({_money(b.get('premium'), b.get('currency', currency), greek)})"
                 for b in quote.get("breakdown") or []]
    else:
        plans = [f"{c.get('product_name')} — {c.get('insurer')} ({_money(c.get('premium'), c.get('currency', currency), greek)})"
                 for c in (quote.get("cards") or [])[:3]]
    return {
        "kind": kind,
        "language": "Greek" if greek else "English",
        "client_first_name": (row.get("applicant_name") or "").split(" ")[0] or None,
        "quote_reference": row["reference"],
        "quote_type": "family" if quote.get("kind") == "household" else "individual",
        "total_annual_premium": _money(row.get("total_premium") or quote.get("total_premium"), currency, greek),
        "plans": plans,
        "valid_until": _fmt_date(valid_until.date(), greek),
        "days_until_expiry": max(0, (valid_until.date() - now.date()).days),
        "country_of_residence": state.get("residence_country"),
    }


_PURPOSE = {
    "checkin": "a friendly check-in a few days after they saved the quote: offer help if anything is unclear "
               "(plans, deductible, what is covered) and say they can simply reply to this email.",
    "expiry": "a reminder that the quote expires soon (state the date) and that after that prices may change "
              "and a new quote would be needed; they can reply or request a proposal from the quote page.",
}


def build_writer_instructions(facts: dict[str, Any]) -> str:
    return (
        "You write the opening paragraph of a short follow-up email from Ashlar Assurance, an insurance broker, "
        "to a client who saved a health insurance quote with HAL, Ashlar's quote assistant.\n"
        f"Purpose: {_PURPOSE[facts['kind']]}\n"
        "Rules:\n"
        f"- Write in {facts['language']}. 2-3 sentences, at most 70 words. Plain text, no markdown.\n"
        "- No greeting line and no sign-off; they are added separately.\n"
        "- Use ONLY the facts below. Never invent prices, benefits, discounts, deadlines, statistics or claims.\n"
        "- Copy any number exactly as written in the facts. Do not calculate new numbers.\n"
        "- Warm, calm and helpful. No pressure, no urgency words, no 'guarantee', 'discount' or 'free'.\n"
        "- You may address the client by first name if given.\n"
        f"Facts (JSON):\n{json.dumps(facts, ensure_ascii=False)}"
    )


def _number_tokens(text: str) -> set[str]:
    return {re.sub(r"[.,]", "", m) for m in re.findall(r"\d[\d.,]*\d|\d", text or "")}


def validate_intro(text: str, facts: dict[str, Any]) -> str | None:
    """Return the cleaned paragraph, or None if it must not be used."""
    clean = _GREETING.sub("", (text or "").strip()).strip().strip('"')
    clean = re.sub(r"\s+", " ", clean)
    if not (40 <= len(clean) <= 700):
        return None
    if _FORBIDDEN.search(clean):
        return None
    allowed = _number_tokens(json.dumps(facts, ensure_ascii=False))
    if not _number_tokens(clean) <= allowed:
        return None
    letters = re.findall(r"[A-Za-zͰ-Ͽ]", clean)
    greek_share = sum(1 for c in letters if "Ͱ" <= c <= "Ͽ") / max(len(letters), 1)
    if (facts["language"] == "Greek") != (greek_share > 0.5):
        return None
    return clean


def deterministic_intro(facts: dict[str, Any]) -> str:
    greek = facts["language"] == "Greek"
    ref, total, until = facts["quote_reference"], facts["total_annual_premium"], facts["valid_until"]
    kind = facts["kind"]
    if kind == "checkin":
        return (f"Πριν από λίγες μέρες αποθηκεύσατε την προσφορά {ref} στον HAL, με συνολικό ετήσιο ασφάλιστρο {total}. "
                "Αν κάτι δεν είναι ξεκάθαρο — τα προγράμματα, η απαλλαγή ή τι καλύπτεται — απαντήστε σε αυτό το email "
                f"και ένας σύμβουλος της Ashlar θα σας βοηθήσει. Η προσφορά ισχύει έως {until}."
                if greek else
                f"A few days ago you saved your HAL quote {ref}, with a total annual premium of {total}. "
                "If anything in it is unclear — the plans, the deductible or what is covered — just reply to this email "
                f"and an Ashlar adviser will help. Your quote is valid until {until}.")
    if kind == "expiry":
        return (f"Η προσφορά σας {ref} ισχύει έως {until}. Μετά από αυτή την ημερομηνία οι τιμές μπορεί να αλλάξουν "
                "και θα χρειαστεί νέα προσφορά. Αν θέλετε να προχωρήσετε ή να τη συζητήσουμε, απαντήστε σε αυτό το email "
                "ή ζητήστε πρόταση από τη σελίδα της προσφοράς σας."
                if greek else
                f"Your saved HAL quote {ref} is valid until {until}. After that date prices may change and a new quote "
                "would be needed. If you would like to go ahead or talk it through, reply to this email or request a "
                "proposal from your quote page.")
    raise ValueError(f"Unknown follow-up kind: {kind}")


async def write_intro(facts: dict[str, Any], settings: Settings | None = None) -> tuple[str, str]:
    """Return (paragraph, writer) where writer is 'ai' or 'template'."""
    settings = settings or get_settings()
    if settings.anthropic_api_key:
        try:
            from backend.app.services.anthropic_client import claude_response
            text = await claude_response(instructions=build_writer_instructions(facts),
                                         message="Write the paragraph now.", max_tokens=300)
            clean = validate_intro(text, facts)
            if clean:
                return clean, "ai"
        except Exception as exc:  # never block a reminder on the AI writer
            log.warning("follow-up writer failed: %s", exc)
    return deterministic_intro(facts), "template"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def build_followup_message(kind: str, row: dict[str, Any], intro: str, sender: str, bcc: str | None,
                           settings: Settings) -> EmailMessage:
    from backend.app.services.leads import _safe
    greek = row.get("language") == "el"
    facts = quote_facts(row, kind)
    ref = row["reference"]
    base = ((row.get("quote_json") or {}).get("public_base") or "").rstrip("/")
    if not base:
        raise RuntimeError("No public link is stored for this quote.")
    quote_url = f"{base}/quote/{ref}"
    unsub_url = f"{base}{settings.api_prefix}/followups/unsubscribe?ref={ref}&t={unsubscribe_token(ref, settings)}"
    name = facts["client_first_name"]
    if greek:
        hello = f"Αγαπητέ/ή {name}," if name else "Γεια σας,"
        subjects = {"checkin": f"Έχετε ερωτήσεις για την προσφορά σας; — {ref}",
                    "expiry": f"Η προσφορά σας λήγει στις {facts['valid_until']} — {ref}"}
        labels = ("Αριθμός προσφοράς", "Σύνολο ανά έτος", "Ισχύει έως")
        button = ("Άνοιγμα της προσφοράς μου", quote_url)
        footer = ("Η προσφορά είναι ενδεικτική· η τελική τιμή, η αποδοχή και οι όροι ορίζονται από τον ασφαλιστή μετά την αίτηση. "
                  "Λαμβάνετε αυτό το email επειδή αποθηκεύσατε την προσφορά σας στον HAL.")
        unsub = "Διακοπή υπενθυμίσεων"
    else:
        hello = f"Dear {name}," if name else "Hello,"
        subjects = {"checkin": f"Any questions about your HAL quote? — {ref}",
                    "expiry": f"Your HAL quote expires on {facts['valid_until']} — {ref}"}
        labels = ("Quote reference", "Total per year", "Valid until")
        button = ("Open my quote", quote_url)
        footer = ("This quote is indicative; the final premium, acceptance and terms are set by the insurer after application. "
                  "You are receiving this email because you saved your quote with HAL.")
        unsub = "Stop these reminders"

    lines = facts["plans"]
    plain = [hello, "", intro, "",
             f"{labels[0]}: {ref}", f"{labels[1]}: {facts['total_annual_premium']}", f"{labels[2]}: {facts['valid_until']}", "",
             *[f"- {l}" for l in lines], ""]
    plain += [f"{button[0]}: {button[1]}", "", footer, f"{unsub}: {unsub_url}", "", "Ashlar Assurance"]

    table = (
            "<table style='border-collapse:collapse;margin:8px 0 12px'>"
            f"<tr><td style='padding:3px 14px 3px 0;color:#687586'>{_safe(labels[0])}</td><td><strong>{_safe(ref)}</strong></td></tr>"
            f"<tr><td style='padding:3px 14px 3px 0;color:#687586'>{_safe(labels[1])}</td><td><strong>{_safe(facts['total_annual_premium'])}</strong></td></tr>"
            f"<tr><td style='padding:3px 14px 3px 0;color:#687586'>{_safe(labels[2])}</td><td>{_safe(facts['valid_until'])}</td></tr></table>"
        + ("<ul style='margin:0 0 14px;padding-left:18px'>" + "".join(f"<li>{_safe(l)}</li>" for l in lines) + "</ul>" if lines else "")
    )
    html_body = (
        "<html><body style='font-family:Arial,sans-serif;color:#172333;font-size:14px;line-height:1.5'>"
        f"<p>{_safe(hello)}</p><p>{_safe(intro)}</p>{table}"
        f"<p><a href='{_safe(button[1])}' style='display:inline-block;background:#0f1a2b;color:#fff;padding:11px 18px;"
        f"border-radius:10px;text-decoration:none;font-weight:bold'>{_safe(button[0])}</a></p>"
        f"<p style='color:#687586;font-size:12px;margin-top:18px'>{_safe(footer)} "
        f"<a href='{_safe(unsub_url)}' style='color:#687586'>{_safe(unsub)}</a></p><p>Ashlar Assurance</p></body></html>"
    )
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = row["email"]
    msg["Subject"] = subjects[kind]
    if bcc and bcc.lower() != str(row["email"]).lower():
        msg["Bcc"] = bcc
    if settings.resend_reply_to:
        msg["Reply-To"] = settings.resend_reply_to
    msg["List-Unsubscribe"] = f"<{unsub_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content("\n".join(plain))
    msg.add_alternative(html_body, subtype="html")
    return msg


# ---------------------------------------------------------------------------
# Processing due follow-ups
# ---------------------------------------------------------------------------

def _claim(settings: Settings, limit: int = 20) -> list[dict[str, Any]]:
    url, headers = _base(settings)
    response = httpx.post(f"{url}/rpc/claim_hal_followups", headers=headers, json={"p_limit": limit}, timeout=15)
    if response.status_code >= 400:
        raise RuntimeError(f"claim_hal_followups returned {response.status_code}: {response.text[:200]}")
    return response.json() or []


def _update(settings: Settings, followup_id: int, changes: dict[str, Any]) -> None:
    url, headers = _base(settings)
    httpx.patch(f"{url}/hal_followups", headers={**headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{followup_id}"}, json=changes, timeout=10)


def _saved_row(settings: Settings, reference: str) -> dict[str, Any] | None:
    url, headers = _base(settings)
    response = httpx.get(f"{url}/hal_saved_quotes", headers=headers,
                         params={"reference": f"eq.{reference}", "select": "*"}, timeout=10)
    if response.status_code >= 400:
        raise RuntimeError(f"hal_saved_quotes returned {response.status_code}")
    rows = response.json()
    return rows[0] if rows else None


def _skip_reason(kind: str, row: dict[str, Any] | None, now: datetime) -> str | None:
    if not row or row.get("status") == "deleted":
        return "quote not found"
    if not row.get("followup_consent") or row.get("unsubscribed_at"):
        return "no consent / unsubscribed"
    if kind == "expiry" and datetime.fromisoformat(row["valid_until"]) < now:
        return "quote already expired"
    return None


async def process_due(settings: Settings | None = None, limit: int = 20) -> dict[str, int]:
    from backend.app.services.leads import _mail_sender, _send_transactional
    settings = settings or get_settings()
    stats = {"claimed": 0, "sent": 0, "skipped": 0, "retry": 0, "failed": 0}
    claimed = await asyncio.to_thread(_claim, settings, limit)
    stats["claimed"] = len(claimed)
    for item in claimed:
        now = datetime.now(timezone.utc)
        try:
            row = await asyncio.to_thread(_saved_row, settings, item["reference"])
            reason = _skip_reason(item["kind"], row, now)
            if reason:
                await asyncio.to_thread(_update, settings, item["id"], {"status": "skipped", "error": reason})
                stats["skipped"] += 1
                continue
            facts = quote_facts(row, item["kind"], now)
            intro, writer = await write_intro(facts, settings)
            bcc = settings.gmail_lead_recipient if settings.followup_bcc_broker else None
            msg = build_followup_message(item["kind"], row, intro, _mail_sender(settings), bcc, settings)
            result = await _send_transactional(msg)
            await asyncio.to_thread(_update, settings, item["id"], {
                "status": "sent", "sent_at": now.isoformat(), "message_id": result.get("id"),
                "subject": str(msg["Subject"])[:240], "writer": writer, "error": None})
            stats["sent"] += 1
        except Exception as exc:  # retry later, give up after MAX_ATTEMPTS
            log.warning("follow-up %s failed: %s", item.get("id"), exc)
            final = int(item.get("attempts") or 1) >= MAX_ATTEMPTS
            await asyncio.to_thread(_update, settings, item["id"], {
                "status": "failed" if final else "scheduled", "error": str(exc)[:300],
                **({} if final else {"scheduled_for": (now + timedelta(hours=1)).isoformat()})})
            stats["failed" if final else "retry"] += 1
    return stats


async def followup_loop(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    await asyncio.sleep(20)
    while True:
        try:
            stats = await process_due(settings)
            if stats["claimed"]:
                log.info("follow-ups processed: %s", stats)
        except Exception as exc:
            log.warning("follow-up loop error: %s", exc)
        await asyncio.sleep(max(30, settings.followup_poll_seconds))
