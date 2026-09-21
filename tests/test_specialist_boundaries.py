from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from backend.app.agents import orchestrator as orchestrator_module
from backend.app.agents import orchestrator_admin
from backend.app.api import chat as chat_api
from backend.app.api import proposals as proposals_api
from backend.app.proposals.engine import ProposalBundle


FORBIDDEN_API_IMPORTS = (
    "backend.app.agents.hal_adviser",
    "backend.app.agents.document_analyst",
    "backend.app.agents.proposal_writer",
    "backend.app.agents.health_navigator",
    "backend.app.agents.asklepios_backend",
    "backend.app.services.anthropic_client",
    "backend.app.services.openai_client",
)


def test_public_chat_api_enters_ashlar_orchestrator():
    source = inspect.getsource(chat_api)
    assert "backend.app.services.orchestrator" not in source
    assert "backend.app.services.anthropic_client" not in source
    assert "backend.app.services.openai_client" not in source
    assert "get_ashlar_orchestrator" in source
    assert ".handle(" in source


def test_public_proposal_api_does_not_import_or_invoke_proposal_writer_directly():
    source = inspect.getsource(proposals_api)
    assert "backend.app.agents.proposal_writer" not in source
    assert "get_proposal_writer" not in source
    assert "backend.app.proposals.engine import" not in source
    assert "generate_case_proposal" not in source
    assert "get_ashlar_orchestrator" in source


def test_public_prepare_route_enters_ashlar_orchestrator_handle():
    source = inspect.getsource(proposals_api.prepare_stored_case_proposal)
    assert "get_ashlar_orchestrator().handle" in source
    assert "get_proposal_writer" not in source
    assert ".generate(" not in source


def test_api_layer_cannot_import_concrete_specialists_or_model_clients_directly():
    api_root = Path(proposals_api.__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted(api_root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_API_IMPORTS:
            if forbidden in source:
                offenders.append(f"{path.name}: {forbidden}")
    assert offenders == []


def test_ashlar_orchestrator_coordinates_but_never_calls_models_directly():
    source = inspect.getsource(orchestrator_module)
    assert "backend.app.services.anthropic_client" not in source
    assert "backend.app.services.openai_client" not in source
    assert "claude_response" not in source
    assert "openai_response" not in source
    assert "get_hal_adviser" in source
    assert "get_document_analyst" in source
    assert "get_proposal_writer" in source
    assert "get_health_navigator" in source


def test_internal_broker_gateway_also_enters_orchestrator_handle():
    source = inspect.getsource(orchestrator_admin)
    assert "orchestrator.handle(" in source
    assert ".proposal_writer" not in source
    assert "get_proposal_writer" not in source


class _FakeOrchestrator:
    pass


@pytest.mark.asyncio
async def test_broker_bundle_generation_delegates_to_internal_orchestrator_gateway(monkeypatch):
    orchestrator = _FakeOrchestrator()
    calls = []

    async def _fake_gateway(owner, **kwargs):
        calls.append((owner, kwargs))
        return ProposalBundle(
            report={"executive_summary": "Grounded"},
            pdf_bytes=b"%PDF-fake",
            pptx_bytes=b"PK-fake",
            quality={"can_generate": True},
        )

    monkeypatch.setattr(proposals_api, "get_ashlar_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(proposals_api, "generate_admin_proposal_bundle", _fake_gateway)

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
    assert len(calls) == 1
    owner, kwargs = calls[0]
    assert owner is orchestrator
    assert kwargs["case"] is case
    assert kwargs["results"] == [{"provider": "Carrier A"}]
