"""HAL `/quotes/current-policy` accepts a 3-document intake (benefits +
policy wording OR brochure + invoice), mirrors it to Proposal Studio with
a backwards-compat `file` alias, and enforces per-file size caps."""
from __future__ import annotations

import io

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.api import quotes as quotes_api

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_proposal_studio(monkeypatch):
    """Point the HAL app at a dummy Proposal Studio endpoint for the test
    and clear the lru_cache so Settings reflect the overrides."""
    get_settings.cache_clear()
    monkeypatch.setenv("PROPOSAL_STUDIO_API_URL", "https://proposal-studio.test")
    monkeypatch.setenv("PROPOSAL_STUDIO_API_KEY", "hal-bridge-key")
    monkeypatch.setenv("PROPOSAL_STUDIO_TIMEOUT_SECONDS", "5")
    yield
    get_settings.cache_clear()


class _FakeProposalStudio:
    """Captures what HAL forwards to Proposal Studio so the tests can assert
    which field names arrived with which bytes."""

    def __init__(self):
        self.last_fields: list[str] = []
        self.last_filenames: dict[str, str] = {}
        self.response = httpx.Response(
            200,
            json={
                "plan_name": "Dummy Plan",
                "provider": "Dummy Insurer",
                "confidence": "high",
                "policy_wording_status": "attached",
            },
        )

    def install(self, monkeypatch):
        instance = self

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, files=None, **_):
                # files is passed as a list of (field_name, (filename, bytes, ctype))
                for field, (filename, _bytes, _ctype) in files:
                    instance.last_fields.append(field)
                    instance.last_filenames[field] = filename
                return instance.response

        monkeypatch.setattr(quotes_api.httpx, "AsyncClient", FakeClient)


def _pdf(name: str, size: int = 128) -> tuple[str, bytes, str]:
    return (name, b"%PDF-1.7\n" + b"x" * size, "application/pdf")


# ---------------------------------------------------------------------------
# Required-field validation
# ---------------------------------------------------------------------------

def test_rejects_when_no_benefits_file_is_attached(monkeypatch):
    _FakeProposalStudio().install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[("wording_file", _pdf("wording.pdf"))],
    )
    assert r.status_code == 400
    assert "Table of Benefits" in r.json()["detail"]


def test_rejects_when_wording_and_brochure_both_missing(monkeypatch):
    _FakeProposalStudio().install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[("benefits_file", _pdf("benefits.pdf"))],
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "policy wording" in detail.lower() and "brochure" in detail.lower()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_benefits_plus_wording_is_accepted_and_forwarded(monkeypatch):
    studio = _FakeProposalStudio()
    studio.install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[
            ("benefits_file", _pdf("benefits.pdf")),
            ("wording_file", _pdf("wording.pdf")),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_policy"]["plan_name"] == "Dummy Plan"
    # Proposal Studio receives the new canonical fields AND the backwards-compat
    # alias so an older Proposal Studio deployment still picks up the benefits.
    assert "benefits_file" in studio.last_fields
    assert "wording_file" in studio.last_fields
    assert "file" in studio.last_fields
    assert "brochure_file" not in studio.last_fields
    assert "invoice_file" not in studio.last_fields


def test_benefits_plus_brochure_is_accepted(monkeypatch):
    studio = _FakeProposalStudio()
    studio.install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[
            ("benefits_file", _pdf("benefits.pdf")),
            ("brochure_file", _pdf("brochure.pdf")),
        ],
    )
    assert r.status_code == 200
    assert "brochure_file" in studio.last_fields
    assert "wording_file" not in studio.last_fields


def test_all_three_documents_including_invoice_are_forwarded(monkeypatch):
    studio = _FakeProposalStudio()
    studio.install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[
            ("benefits_file", _pdf("benefits.pdf")),
            ("wording_file", _pdf("wording.pdf")),
            ("invoice_file", _pdf("invoice.pdf")),
        ],
    )
    assert r.status_code == 200
    for field in ("benefits_file", "wording_file", "invoice_file", "file"):
        assert field in studio.last_fields


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------

def test_legacy_single_file_field_is_treated_as_benefits(monkeypatch):
    """Any client still posting the old single-file contract must either
    continue to work OR be told clearly what's missing. Here we assert the
    'file' field is accepted as the benefits document but a wording /
    brochure is still required — mirroring the policy-review flow Chris
    already shipped."""
    studio = _FakeProposalStudio()
    studio.install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[
            ("file", _pdf("legacy.pdf")),
            ("wording_file", _pdf("wording.pdf")),
        ],
    )
    assert r.status_code == 200
    # Backwards-compat alias forwarded + canonical benefits_file populated.
    assert "benefits_file" in studio.last_fields
    assert studio.last_filenames["benefits_file"] == "legacy.pdf"


def test_single_legacy_file_without_wording_is_rejected_with_clear_detail(monkeypatch):
    _FakeProposalStudio().install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[("file", _pdf("legacy.pdf"))],
    )
    assert r.status_code == 400
    assert "policy wording" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Size / empty-file guards
# ---------------------------------------------------------------------------

def test_empty_benefits_file_is_rejected_with_a_label(monkeypatch):
    _FakeProposalStudio().install(monkeypatch)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[
            ("benefits_file", ("empty.pdf", b"", "application/pdf")),
            ("wording_file", _pdf("wording.pdf")),
        ],
    )
    assert r.status_code == 400
    assert "benefits" in r.json()["detail"].lower() and "empty" in r.json()["detail"].lower()


def test_oversized_wording_file_is_rejected(monkeypatch):
    _FakeProposalStudio().install(monkeypatch)
    too_big = b"%PDF-1.7" + b"x" * (20 * 1024 * 1024 + 1)
    r = client.post(
        "/api/v1/quotes/current-policy",
        files=[
            ("benefits_file", _pdf("benefits.pdf")),
            ("wording_file", ("huge.pdf", too_big, "application/pdf")),
        ],
    )
    assert r.status_code == 413
    assert "wording" in r.json()["detail"].lower() and "20 mb" in r.json()["detail"].lower()
