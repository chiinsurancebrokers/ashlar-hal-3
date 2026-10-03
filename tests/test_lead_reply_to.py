import pytest

from backend.app.core.config import Settings
from backend.app.services import leads


def test_lead_message_has_exactly_one_prospect_reply_to():
    msg = leads._build_lead_message(
        {"first_name": "Chris", "last_name": "T", "email": "prospect@example.com", "insurance_interest": "IPMI", "consent": True},
        "HAL-TEST", "Ashlar <quotes@ashlarassurance.com>", "broker@example.com",
    )
    assert msg.get_all("Reply-To") == ["prospect@example.com"]


@pytest.mark.asyncio
async def test_resend_configured_lead_does_not_append_second_reply_to(monkeypatch):
    settings = Settings(
        RESEND_API_KEY="test-key",
        RESEND_FROM_EMAIL="quotes@ashlarassurance.com",
        RESEND_FROM_NAME="Ashlar Assurance",
        RESEND_REPLY_TO="info@ashlarassurance.com",
        GMAIL_LEAD_RECIPIENT="broker@example.com",
    )
    captured = {}

    monkeypatch.setattr(leads, "get_settings", lambda: settings)

    async def fake_send(msg):
        captured["reply_to"] = msg.get_all("Reply-To")
        return {"transport": "resend", "id": "test-message"}

    monkeypatch.setattr(leads, "_send_transactional", fake_send)
    result = await leads.send_lead({
        "first_name": "Chris", "last_name": "T", "email": "prospect@example.com",
        "insurance_interest": "IPMI", "consent": True,
    })
    assert result["transport"] == "resend"
    assert captured["reply_to"] == ["prospect@example.com"]
