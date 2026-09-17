from __future__ import annotations

import inspect

import pytest

from backend.app.api import chat as chat_api
from backend.app.api import proposals as proposals_api
from backend.app.proposals.engine import ProposalBundle


def test_public_chat_api_does_not_bypass_hal_specialist():
    source = inspect.getsource(chat_api)
    assert "backend.app.services.orchestrator" not in source
    assert "backend.app.services.anthropic_client" not in source
    assert "backend.app.services.openai_client" not in source
    assert "get_ashlar_orchestrator" in source


def test_public_proposal_api_does_not_bypass_proposal_writer():
    source = inspect.getsource(proposals_api)
    assert "backend.app.proposals.engine import" not in source
    assert "generate_case_proposal" not in source
    assert "get_proposal_writer" in source


class _FakeWriter:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return ProposalBundle(
            report={"executive_summary": "Grounded"},
            pdf_bytes=b"%PDF-fake",
            pptx_bytes=b"PK-fake",
            quality={"can_generate": True},
        )


@pytest.mark.asyncio
async def test_proposal_api_bundle_generation_delegates_to_specialist(monkeypatch):
    writer = _FakeWriter()
    monkeypatch.setattr(proposals_api, "get_proposal_writer", lambda: writer)

    class _Case:
        pass

    case = _Case()
    bundle = await proposals_api._generate_bundle(
        case=case,
        results=[{"provider": "Carrier A"}],
        language="English",
        strict_narrative=False,
    )

    assert bundle.report["executive_summary"] == "Grounded"
    assert len(writer.calls) == 1
    assert writer.calls[0]["case"] is case
    assert writer.calls[0]["results"] == [{"provider": "Carrier A"}]
