import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents
from backend.app.main import app

client = TestClient(app)
OFFICIAL = "https://morgan-price.eu/media/xl0bmfdo/evolutionhealth_eu_ipid_premium_si_04-26.pdf"


@pytest.mark.parametrize("url", [
    "https://evil.example.com/x.pdf",
    "http://morgan-price.eu/media/xl0bmfdo/evolutionhealth_eu_ipid_premium_si_04-26.pdf",
    "https://morgan-price.eu/media/other.pdf",
    "http://169.254.169.254/latest/meta-data/",
])
def test_rejects_urls_not_in_manifest(url):
    response = client.get("/api/v1/documents/view", params={"url": url})
    assert response.status_code == 404


def test_serves_allowlisted_pdf_inline(monkeypatch):
    documents._cache.clear()

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            assert url == OFFICIAL
            return httpx.Response(200, content=b"%PDF-1.7 test")

    monkeypatch.setattr(documents.httpx, "AsyncClient", FakeClient)
    response = client.get("/api/v1/documents/view", params={"url": OFFICIAL})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "x-frame-options" not in {k.lower() for k in response.headers}
    assert response.content == b"%PDF-1.7 test"


def test_rejects_non_pdf_upstream(monkeypatch):
    documents._cache.clear()

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            return httpx.Response(200, content=b"<html>not a pdf</html>")

    monkeypatch.setattr(documents.httpx, "AsyncClient", FakeClient)
    response = client.get("/api/v1/documents/view", params={"url": OFFICIAL})
    assert response.status_code == 502
