"""Follow-up / reminder emails for saved quotes."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.services import followups as fu

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-test")
    monkeypatch.setenv("QUOTE_RETRIEVAL_SECRET", "secret-test")
    monkeypatch.setenv("GMAIL_LEAD_RECIPIENT", "broker@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def _row(language="en", **extra):
    return {
        "reference": "HAL-20261005-ABCD1234", "language": language, "applicant_name": "Chris Papas",
        "email": "chris@example.com", "created_at": NOW.isoformat(),
        "valid_until": (NOW + timedelta(days=30)).isoformat(), "status": "saved",
        "followup_consent": True, "unsubscribed_at": None, "residency_purpose": False,
        "total_premium": 8271.77, "currency": "EUR",
        "state_json": {"residence_country": "Portugal"},
        "quote_json": {"kind": "household", "currency": "EUR", "total_premium": 8271.77,
                       "public_base": "https://hal.ashlarassurance.com",
                       "breakdown": [{"label": "Chris (51)", "product_name": "Premium", "premium": 4000.0, "currency": "EUR"},
                                     {"label": "Spouse (35)", "product_name": "Standard", "premium": 4271.77, "currency": "EUR"}]},
        **extra,
    }


# ----------------------------------------------------------------- schedule

def test_schedule_checkin_and_expiry(settings):
    steps = dict(fu.plan_schedule(saved_at=NOW, valid_until=NOW + timedelta(days=30), settings=settings))
    assert steps == {"checkin": NOW + timedelta(days=3), "expiry": NOW + timedelta(days=25)}


def test_schedule_skips_expiry_when_too_close_to_checkin(settings):
    steps = dict(fu.plan_schedule(saved_at=NOW, valid_until=NOW + timedelta(days=9), settings=settings))
    assert list(steps) == ["checkin"]


def test_fast_mode_for_staging(settings, monkeypatch):
    monkeypatch.setenv("FOLLOWUP_FAST_MODE", "true")
    get_settings.cache_clear()
    steps = dict(fu.plan_schedule(saved_at=NOW, valid_until=NOW + timedelta(days=30), settings=get_settings()))
    assert steps == {"checkin": NOW + timedelta(minutes=2), "expiry": NOW + timedelta(minutes=4)}


# ----------------------------------------------------------------- writing

def test_validator_accepts_grounded_text_and_strips_greeting(settings):
    facts = fu.quote_facts(_row(), "checkin", NOW)
    text = "Dear Chris,\nThanks for saving quote HAL-20261005-ABCD1234. The total is EUR 8,271.77 a year and it is valid until 4 November 2026."
    clean = fu.validate_intro(text, facts)
    assert clean and not clean.startswith("Dear")


@pytest.mark.parametrize("text", [
    "Your quote HAL-20261005-ABCD1234 is EUR 7,900.00 a year — a great deal you should review today.",   # invented number
    "We can offer a discount on quote HAL-20261005-ABCD1234 if you reply to us this week, Chris.",         # sales pressure
    "Η προσφορά σας HAL-20261005-ABCD1234 είναι έτοιμη και μπορείτε να μας απαντήσετε για ερωτήσεις.",     # wrong language
    "Hi.",                                                                                                   # too short
])
def test_validator_rejects(settings, text):
    assert fu.validate_intro(text, fu.quote_facts(_row(), "checkin", NOW)) is None


def test_ai_writer_falls_back_to_template(settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()

    async def fake_claude(**_kwargs):
        return "Act now: your price of EUR 1.00 is guaranteed!"
    monkeypatch.setattr("backend.app.services.anthropic_client.claude_response", fake_claude)
    facts = fu.quote_facts(_row(), "expiry", NOW)
    text, writer = asyncio.run(fu.write_intro(facts, get_settings()))
    assert writer == "template" and "HAL-20261005-ABCD1234" in text


@pytest.mark.parametrize("kind", fu.KINDS)
@pytest.mark.parametrize("language", ["en", "el"])
def test_templates_exist_for_every_kind(settings, kind, language):
    facts = fu.quote_facts(_row(language), kind, NOW)
    text = fu.deterministic_intro(facts)
    assert "HAL-20261005-ABCD1234" in text
    assert fu.validate_intro(text, facts) == text   # templates pass their own validator


def test_greek_money_format(settings):
    facts = fu.quote_facts(_row("el"), "checkin", NOW)
    assert facts["total_annual_premium"] == "EUR 8.271,77"


# ----------------------------------------------------------------- email

def test_email_has_links_unsubscribe_and_bcc(settings):
    msg = fu.build_followup_message("checkin", _row(), "Intro text.", "Ashlar <quotes@x.com>", "broker@example.com", settings)
    html = msg.get_body(preferencelist=("html",)).get_content()
    token = fu.unsubscribe_token("HAL-20261005-ABCD1234", settings)
    assert "https://hal.ashlarassurance.com/quote/HAL-20261005-ABCD1234" in html
    assert f"/api/v1/followups/unsubscribe?ref=HAL-20261005-ABCD1234&amp;t={token}" in html
    assert token in msg["List-Unsubscribe"] and msg["Bcc"] == "broker@example.com"
    assert "8,271.77" in html and "Chris (51)" in html


def test_unsubscribe_token_is_per_reference(settings):
    t = fu.unsubscribe_token("HAL-20261005-ABCD1234", settings)
    assert fu.valid_unsubscribe_token("HAL-20261005-ABCD1234", t, settings)
    assert not fu.valid_unsubscribe_token("HAL-20261005-ZZZZ9999", t, settings)


# ----------------------------------------------------------------- processing

class Harness:
    def __init__(self, monkeypatch, row, claimed, send_error=None):
        self.updates, self.sent = [], []
        monkeypatch.setattr(fu, "_claim", lambda s, limit=20: claimed)
        monkeypatch.setattr(fu, "_saved_row", lambda s, ref: row)
        monkeypatch.setattr(fu, "_update", lambda s, fid, changes: self.updates.append((fid, changes)))

        async def send(msg):
            if send_error:
                raise RuntimeError(send_error)
            self.sent.append(msg)
            return {"transport": "resend", "id": "msg_1"}
        monkeypatch.setattr("backend.app.services.leads._send_transactional", send)


def test_process_sends_and_marks_sent(settings, monkeypatch):
    h = Harness(monkeypatch, _row(), [{"id": 1, "reference": "HAL-20261005-ABCD1234", "kind": "checkin", "attempts": 1}])
    stats = asyncio.run(fu.process_due(settings))
    assert stats["sent"] == 1 and h.sent[0]["To"] == "chris@example.com"
    assert h.updates[0][1]["status"] == "sent" and h.updates[0][1]["writer"] == "template"


def test_process_skips_unsubscribed(settings, monkeypatch):
    h = Harness(monkeypatch, _row(unsubscribed_at=NOW.isoformat()),
                [{"id": 2, "reference": "HAL-20261005-ABCD1234", "kind": "checkin", "attempts": 1}])
    stats = asyncio.run(fu.process_due(settings))
    assert stats["skipped"] == 1 and not h.sent and h.updates[0][1]["status"] == "skipped"


def test_process_retries_then_fails(settings, monkeypatch):
    h = Harness(monkeypatch, _row(), [{"id": 3, "reference": "HAL-20261005-ABCD1234", "kind": "checkin", "attempts": 1}],
                send_error="boom")
    assert asyncio.run(fu.process_due(settings))["retry"] == 1
    assert h.updates[-1][1]["status"] == "scheduled" and "scheduled_for" in h.updates[-1][1]
    h = Harness(monkeypatch, _row(), [{"id": 3, "reference": "HAL-20261005-ABCD1234", "kind": "checkin", "attempts": 3}],
                send_error="boom")
    assert asyncio.run(fu.process_due(settings))["failed"] == 1
    assert h.updates[-1][1]["status"] == "failed"


# ----------------------------------------------------------------- API

def test_unsubscribe_endpoint(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(fu.httpx, "patch", lambda url, **kw: calls.append((url, kw)) or httpx.Response(204))
    from backend.app.main import app
    client = TestClient(app)
    ref = "HAL-20261005-ABCD1234"
    bad = client.get(f"/api/v1/followups/unsubscribe?ref={ref}&t=wrong")
    assert bad.status_code == 400 and not calls
    ok = client.get(f"/api/v1/followups/unsubscribe?ref={ref}&t={fu.unsubscribe_token(ref, settings)}")
    assert ok.status_code == 200 and "more reminders" in ok.text
    assert any("hal_saved_quotes" in c[0] for c in calls) and any("hal_followups" in c[0] for c in calls)


def test_run_endpoint_needs_admin_token(settings):
    from backend.app.main import app
    assert TestClient(app).post("/api/v1/followups/run").status_code == 404


def test_proposal_request_cancels_reminders(settings, monkeypatch):
    cancelled = []

    async def fake_send(payload, reference=None):
        return {"status": "sent", "reference": "HAL-LEAD"}
    monkeypatch.setattr("backend.app.api.leads.send_lead", fake_send)
    monkeypatch.setattr(fu, "cancel_followups", lambda ref, reason, settings=None: cancelled.append(ref))
    from backend.app.main import app
    r = TestClient(app).post("/api/v1/leads", json={
        "insurance_interest": "IPMI", "first_name": "Chris", "last_name": "P", "email": "c@example.com", "consent": True,
        "hal_context": {"saved_quote_reference": "HAL-20261005-ABCD1234"}})
    assert r.status_code == 200 and cancelled == ["HAL-20261005-ABCD1234"]


def test_save_rejects_forged_host(settings):
    from backend.app.main import app
    r = TestClient(app).post("/api/v1/saved-quotes", headers={"x-forwarded-host": "evil.example.com"},
                             json={"state": {}, "email": "a@example.com", "date_of_birth": "1980-01-01", "consent": True})
    assert r.status_code == 400
