"""Save a HAL quote and retrieve it with reference + date of birth."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.services import family_live_orchestrator as live
from backend.app.services import saved_quotes as sq


class FakeStore:
    def __init__(self):
        self.rows = {}

    def post(self, url, headers=None, json=None, timeout=None):
        self.rows[json["reference"]] = {**json, "created_at": datetime.now(timezone.utc).isoformat(),
                                        "status": "saved", "retrieve_count": 0, "failed_attempts": 0, "locked_until": None}
        return httpx.Response(201)

    def get(self, url, headers=None, params=None, timeout=None):
        ref = params["reference"].removeprefix("eq.")
        return httpx.Response(200, json=[self.rows[ref]] if ref in self.rows else [])

    def patch(self, url, headers=None, params=None, json=None, timeout=None):
        self.rows[params["reference"].removeprefix("eq.")].update(json)
        return httpx.Response(204)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-test")
    get_settings.cache_clear()
    fake = FakeStore()
    monkeypatch.setattr(sq.httpx, "post", fake.post)
    monkeypatch.setattr(sq.httpx, "get", fake.get)
    monkeypatch.setattr(sq.httpx, "patch", fake.patch)
    yield fake
    get_settings.cache_clear()


MSGS = ["chris", "51", "male", "greece", "Same as residence", "greek", "Europe only",
        "yes", "spouse", "35", "female", "yes", "yes", "child", "5", "male", "yes", "child", "5", "male", "no",
        "€0 deductible", "Include outpatient cover", "No", "No dental needed", "No mental health cover needed",
        "Yes, wellness is important", "No optical cover needed", "Yes, evacuation is important", "No fixed budget"]


def _family_state():
    async def go():
        state = {"pending_question": "name"}
        for m in MSGS:
            state = (await live.chat_turn(m, state, []))["state"]
        return state
    return asyncio.run(go())


def _dob_for_age(age):
    return date(date.today().year - age, 1, 1).isoformat()   # birthday already passed this year


def test_save_recomputes_server_side_and_never_stores_plain_dob(store):
    state = _family_state()
    state["injected_price"] = 1.0          # anything the browser adds is ignored
    dob = _dob_for_age(51)
    saved = sq.save_quote(state=state, email="chris@example.com", date_of_birth=dob, consent=True)
    assert sq.REFERENCE_RE.match(saved["reference"])
    row = store.rows[saved["reference"]]
    assert row["total_premium"] == 8271.77 and row["currency"] == "EUR"
    assert row["quote_json"]["kind"] == "household" and len(row["quote_json"]["breakdown"]) == 4
    assert dob not in str(row) and len(row["dob_hash"]) == 64
    assert "injected_price" not in row["state_json"]
    assert row["quote_json"]["cards"][0]["plan_documents"]


def test_dob_must_match_stated_age(store):
    state = _family_state()
    with pytest.raises(sq.SavedQuoteError, match="does not match the age"):
        sq.save_quote(state=state, email="c@example.com", date_of_birth="1990-01-01", consent=True)


def test_consent_and_completed_quote_required(store):
    with pytest.raises(sq.SavedQuoteError):
        sq.save_quote(state=_family_state(), email="c@example.com", date_of_birth=_dob_for_age(51), consent=False)
    with pytest.raises(sq.SavedQuoteError):
        sq.save_quote(state={"age": 51}, email="c@example.com", date_of_birth=_dob_for_age(51), consent=True)


def test_retrieve_with_reference_and_dob(store):
    dob = _dob_for_age(51)
    saved = sq.save_quote(state=_family_state(), email="c@example.com", date_of_birth=dob, consent=True)
    got = sq.retrieve_quote(reference=saved["reference"].lower(), date_of_birth=dob)
    assert got["quote"]["total_premium"] == 8271.77 and got["expired"] is False
    assert "email" not in got and "dob_hash" not in got
    assert store.rows[saved["reference"]]["retrieve_count"] == 1


def test_wrong_dob_is_generic_and_locks_after_five(store):
    dob = _dob_for_age(51)
    ref = sq.save_quote(state=_family_state(), email="c@example.com", date_of_birth=dob, consent=True)["reference"]
    for _ in range(sq.MAX_FAILED_ATTEMPTS):
        with pytest.raises(sq.SavedQuoteError) as err:
            sq.retrieve_quote(reference=ref, date_of_birth="1980-02-02")
        assert err.value.status == 404
    with pytest.raises(sq.SavedQuoteError) as err:
        sq.retrieve_quote(reference=ref, date_of_birth=dob)       # even the right DOB while locked
    assert err.value.status == 429
    with pytest.raises(sq.SavedQuoteError) as err:
        sq.retrieve_quote(reference="HAL-20990101-AAAAAAAA", date_of_birth=dob)
    assert err.value.status == 404


def test_expired_quote_is_flagged(store):
    dob = _dob_for_age(51)
    ref = sq.save_quote(state=_family_state(), email="c@example.com", date_of_birth=dob, consent=True)["reference"]
    store.rows[ref]["valid_until"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert sq.retrieve_quote(reference=ref, date_of_birth=dob)["expired"] is True


def test_api_save_emails_link_and_page_is_served(store, monkeypatch):
    from backend.app.api import saved_quotes as api
    from backend.app.main import app
    sent = {}

    async def fake_send(saved, email, url):
        sent.update(saved=saved, email=email, url=url)
        return {"status": "sent"}
    monkeypatch.setattr(api, "send_saved_quote_email", fake_send)
    client = TestClient(app)
    r = client.post("/api/v1/saved-quotes", headers={"host": "hal.ashlarassurance.com", "x-forwarded-proto": "https"},
                    json={"state": _family_state(), "email": "c@example.com", "date_of_birth": _dob_for_age(51), "consent": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email_sent"] is True
    assert body["retrieve_url"] == f"https://hal.ashlarassurance.com/quote/{body['reference']}" == sent["url"]
    page = client.get(f"/quote/{body['reference']}")
    assert page.status_code == 200 and "saved-quotes/retrieve" in page.text
    assert page.headers["x-robots-tag"] == "noindex"
    r2 = client.post("/api/v1/saved-quotes/retrieve", json={"reference": body["reference"], "date_of_birth": "1970-01-01"})
    assert r2.status_code == 404


def test_saved_quote_email_has_reference_link_and_greek_steps():
    from backend.app.services.leads import _build_saved_quote_message
    saved = {"reference": "HAL-20261004-ABCDEFGH", "applicant_name": "Chris", "language": "el", "valid_until": "2026-11-03",
             "snapshot": {"kind": "household", "currency": "EUR", "total_premium": 8271.77,
                          "breakdown": [{"label": "Chris (51)", "product_name": "Morgan Price Standard Plus", "premium": 2694.72, "currency": "EUR"}]}}
    msg = _build_saved_quote_message(saved, "c@example.com", "https://hal.ashlarassurance.com/quote/HAL-20261004-ABCDEFGH",
                                     "Ashlar <quotes@ashlarassurance.com>", "broker@example.com")
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "HAL-20261004-ABCDEFGH" in msg["Subject"] and "Αριθμός προσφοράς" in html
    assert "https://hal.ashlarassurance.com/quote/HAL-20261004-ABCDEFGH" in html
    assert "ημερομηνία γέννησής" in html and "EUR 8,271.77" in html and "03/11/2026" in html
    assert msg["Bcc"] == "broker@example.com"



def test_reminders_scheduled_for_every_saved_quote(store, monkeypatch):
    from backend.app.services import followups
    calls = []
    monkeypatch.setattr(followups, "schedule_followups", lambda ref, **kw: calls.append((ref, kw)) or [])
    saved = sq.save_quote(state=_family_state(), email="c@example.com", date_of_birth=_dob_for_age(51), consent=True,
                          public_base="https://hal.ashlarassurance.com/")
    row = store.rows[saved["reference"]]
    assert saved["followups_scheduled"] is True and calls[0][0] == saved["reference"]
    assert row["followup_consent"] is True and row["quote_json"]["public_base"] == "https://hal.ashlarassurance.com"
