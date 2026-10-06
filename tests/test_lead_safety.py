"""A lead is saved before it is emailed, so a broken mail key never loses a prospect."""
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.api import leads as api
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.services import lead_store

client = TestClient(app)

LEAD = {"insurance_interest": "IPMI", "first_name": "Maria", "last_name": "K",
        "email": "maria@example.com", "phone": "+30 210 000 0000", "consent": True}
COMPARISON = {"name": "Maria", "email": "maria@example.com",
              "applicant_state": {"age": 40, "residence_country": "Greece", "coverage_area": "area1"},
              "plan_keys": ["morgan_price:standard"]}


@pytest.fixture
def calls(monkeypatch):
    """Record the order of store / send / mark calls; each can be made to fail."""
    log: list = []
    fail: set = set()

    async def store(kind, reference, payload, settings=None):
        log.append(("store", kind, reference))
        if "store" in fail:
            raise RuntimeError("Supabase returned 500: boom")

    async def mark(reference, *, sent, transport=None, error=None, settings=None):
        log.append(("mark", reference, sent, error))

    async def send(payload, *, reference=None):
        log.append(("send", reference))
        if "send" in fail:
            raise RuntimeError("Google OAuth returned 400: invalid_grant")
        return {"status": "sent", "reference": reference, "transport": "resend", "message_id": "m1"}

    async def ack(payload, reference):
        log.append(("ack", reference))
        return {"status": "sent"}

    async def comparison(name, email, state, keys, current_policy_token=None):
        log.append(("send_comparison", email))
        if "send" in fail:
            raise RuntimeError("Resend API returned 401: invalid key")
        return {"status": "sent", "transport": "resend", "message_id": "m2", "plans_sent": keys}

    monkeypatch.setattr(api, "store_lead", store)
    monkeypatch.setattr(api, "mark_delivery", mark)
    monkeypatch.setattr(api, "send_lead", send)
    monkeypatch.setattr(api, "send_lead_ack", ack)
    monkeypatch.setattr(api, "send_comparison_email", comparison)
    return log, fail


def test_lead_is_stored_before_the_email_and_marked_sent(calls):
    log, _ = calls
    r = client.post("/api/v1/leads", json=LEAD)
    assert r.status_code == 200
    body = r.json()
    assert body["delivered"] is True and body["stored"] is True and body["ack_sent"] is True
    ref = body["reference"]
    assert [c[0] for c in log] == ["store", "send", "mark", "ack"]
    assert log[0] == ("store", "proposal", ref) and log[1] == ("send", ref)
    assert log[2] == ("mark", ref, True, None) and log[3] == ("ack", ref)


def test_email_failure_still_accepts_a_stored_lead(calls, caplog):
    log, fail = calls
    fail.add("send")
    with caplog.at_level(logging.ERROR, logger="hal.leads"):
        r = client.post("/api/v1/leads", json=LEAD)
    assert r.status_code == 200, "the client must see the thank-you screen: the lead is on record"
    body = r.json()
    assert body["delivered"] is False and body["stored"] is True and body["status"] == "received"
    mark = [c for c in log if c[0] == "mark"][0]
    assert mark[2] is False and "invalid_grant" in mark[3]
    assert ("ack", body["reference"]) in log
    assert "invalid_grant" in caplog.text and body["reference"] in caplog.text


def test_nothing_saved_and_nothing_sent_returns_503_without_internal_detail(calls, caplog):
    _, fail = calls
    fail.update({"store", "send"})
    with caplog.at_level(logging.ERROR, logger="hal.leads"):
        r = client.post("/api/v1/leads", json=LEAD)
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail == api.UNAVAILABLE_DETAIL and "invalid_grant" not in detail
    assert "NOT STORED" in caplog.text and "invalid_grant" in caplog.text


def test_storage_outage_does_not_block_a_delivered_lead(calls):
    log, fail = calls
    fail.add("store")
    r = client.post("/api/v1/leads", json=LEAD)
    assert r.status_code == 200
    assert r.json()["delivered"] is True and r.json()["stored"] is False
    assert not [c for c in log if c[0] == "mark"]


def test_comparison_is_stored_and_marked_sent(calls):
    log, _ = calls
    r = client.post("/api/v1/leads/comparison", json=COMPARISON)
    assert r.status_code == 200
    assert r.json()["stored"] is True
    assert [c[0] for c in log] == ["store", "send_comparison", "mark"] and log[0][1] == "comparison"


def test_comparison_email_failure_tells_the_client_an_adviser_has_it(calls):
    log, fail = calls
    fail.add("send")
    r = client.post("/api/v1/leads/comparison", json=COMPARISON)
    assert r.status_code == 503
    assert r.json()["detail"] == api.COMPARISON_PENDING_DETAIL
    assert [c for c in log if c[0] == "mark"][0][2] is False


def test_store_lead_writes_the_expected_row(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-test")
    get_settings.cache_clear()
    sent = {}

    async def fake_post(self, url, **kwargs):
        sent["url"], sent["json"], sent["headers"] = url, kwargs["json"], kwargs["headers"]
        return httpx.Response(201)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    import asyncio
    try:
        asyncio.run(lead_store.store_lead("proposal", "HAL-20261006-ABCDEF12", dict(LEAD)))
    finally:
        get_settings.cache_clear()
    assert sent["url"] == "https://example.supabase.co/rest/v1/hal_leads"
    row = sent["json"]
    assert row["reference"] == "HAL-20261006-ABCDEF12" and row["kind"] == "proposal"
    assert row["email"] == "maria@example.com" and row["name"] == "Maria K"
    assert row["payload"]["phone"] == "+30 210 000 0000"
    assert sent["headers"]["Authorization"] == "Bearer service-role-test"


def test_store_lead_without_supabase_config_raises(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    import asyncio
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(lead_store.store_lead("proposal", "HAL-X", dict(LEAD)))
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("path,ctype", [
    ("/favicon.ico", "image/x-icon"),
    ("/favicon.svg", "image/svg+xml"),
    ("/apple-touch-icon.png", "image/png"),
    ("/apple-touch-icon-precomposed.png", "image/png"),
    ("/apple-touch-icon-120x120.png", "image/png"),
    ("/apple-touch-icon-120x120-precomposed.png", "image/png"),
])
def test_icons_are_served(path, ctype):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)


def test_robots_txt_keeps_quotes_and_api_out_of_search():
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "Disallow: /quote" in r.text and "Disallow: /api/" in r.text and "Allow: /" in r.text
