import pytest

from backend.app.services.leads import _verified_plans_for, _build_comparison_message
from backend.app.core.config import Settings


def test_server_recomputes_real_premium_regardless_of_what_client_implies():
    applicant_state = {"age": 40, "residence_country": "Greece", "coverage_area": "area1"}
    settings = Settings()

    shortlist_plans = _verified_plans_for(applicant_state, ["morgan_price:standard"], settings)
    assert len(shortlist_plans) == 1
    # This must be the REAL, server-computed premium — €1490.80 — no matter
    # what a compromised/forged client request might have implied.
    assert shortlist_plans[0].premium == 1490.80


def test_unknown_or_forged_plan_key_is_rejected_not_silently_priced():
    applicant_state = {"age": 40, "residence_country": "Greece", "coverage_area": "area1"}
    settings = Settings()
    with pytest.raises(ValueError):
        _verified_plans_for(applicant_state, ["totally_made_up_carrier:fantasy_plan"], settings)


def test_comparison_email_body_only_ever_contains_server_side_premium_string():
    applicant_state = {"age": 40, "residence_country": "Greece", "coverage_area": "area1"}
    settings = Settings()
    plans = _verified_plans_for(applicant_state, ["morgan_price:standard"], settings)

    msg = _build_comparison_message("Chris", "chris@example.com", plans, "hal@ashlar.example", None)
    body = msg.get_body(preferencelist=("html",)).get_content()
    assert "1,490.80" in body
    # A forged lower price must never appear anywhere in the rendered email.
    assert "868.00" not in body


@pytest.mark.asyncio
async def test_siteground_smtp_is_primary_when_fully_configured(monkeypatch):
    import backend.app.services.leads as leads
    settings = leads.get_settings()
    monkeypatch.setattr(settings, "smtp_host", "mail.ashlarassurance.com")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_username", "quotes@ashlarassurance.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_from_email", "quotes@ashlarassurance.com")
    monkeypatch.setattr(settings, "smtp_from_name", "Ashlar Assurance")
    called = {"smtp": 0, "gmail": 0}

    async def smtp(_msg):
        called["smtp"] += 1
        return {"transport": "smtp", "message_id": "<smtp-test>"}

    async def gmail(_msg):
        called["gmail"] += 1
        return {"id": "gmail-test"}

    monkeypatch.setattr(leads, "_send_via_smtp", smtp)
    monkeypatch.setattr(leads, "_send_via_gmail", gmail)
    msg = leads.EmailMessage()
    msg["From"] = leads._mail_sender(settings)
    msg["To"] = "client@example.com"
    msg["Subject"] = "Test"
    msg.set_content("hello")
    result = await leads._send_transactional(msg)
    assert result["transport"] == "smtp"
    assert called == {"smtp": 1, "gmail": 0}
    assert msg["From"] == "Ashlar Assurance <quotes@ashlarassurance.com>"


@pytest.mark.asyncio
async def test_gmail_remains_fallback_until_smtp_password_is_present(monkeypatch):
    import backend.app.services.leads as leads
    settings = leads.get_settings()
    monkeypatch.setattr(settings, "smtp_host", "mail.ashlarassurance.com")
    monkeypatch.setattr(settings, "smtp_username", "quotes@ashlarassurance.com")
    monkeypatch.setattr(settings, "smtp_password", None)
    monkeypatch.setattr(settings, "smtp_from_email", "quotes@ashlarassurance.com")

    async def gmail(_msg):
        return {"id": "gmail-fallback"}

    monkeypatch.setattr(leads, "_send_via_gmail", gmail)
    msg = leads.EmailMessage()
    msg["From"] = "Ashlar Assurance <quotes@ashlarassurance.com>"
    msg["To"] = "client@example.com"
    msg["Subject"] = "Test"
    msg.set_content("hello")
    result = await leads._send_transactional(msg)
    assert result["id"] == "gmail-fallback"
