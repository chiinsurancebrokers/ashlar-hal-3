from types import SimpleNamespace

import pytest

import backend.app.api.quotes as quotes_api


class FakeLibrary:
    configured = True

    def plan_context(self, *, provider_label: str, target_plan: str, product_hint: str | None = None):
        assert provider_label == "IMG"
        assert target_plan == "Silver"
        return {
            "provider": "IMG",
            "product": "Global Prima Medical Insurance",
            "version": "2026",
            "documents": [
                {
                    "doc_type": "brochure",
                    "title": "IMG GPMI Table of Benefits",
                    "extracted_text": "IMG Global Prima brochure",
                    "focused_table_context": "[Page 7] Annual overall benefit maximum => EUR 2,000,000\n[Page 8] Medical evacuation => Covered",
                }
            ],
        }


@pytest.mark.asyncio
async def test_shortlist_is_enriched_from_proposal_studio_provider_library(monkeypatch):
    monkeypatch.setattr(quotes_api, "get_proposal_library_client", lambda: FakeLibrary())
    quote = SimpleNamespace(insurer="IMG", product_name="IMG Silver")
    results = [{
        "plan_key": "img:silver",
        "provider": "IMG",
        "target_plan": "IMG Silver",
        "focused_rows": [],
        "library_source": False,
        "analysis": {
            "provider": "IMG",
            "plan_name": "IMG Silver",
            "premium": {"amount": 1234, "currency": "EUR", "frequency": "Annual"},
            "annual_limit": "Not specified",
            "deductible_or_excess": "EUR 150",
            "area_of_cover": "Europe",
            "benefits": {},
            "source_evidence": [],
        },
    }]

    enriched = await quotes_api._enrich_results_from_provider_library([quote], results)

    assert enriched[0]["library_source"] is True
    assert enriched[0]["provider_library_source"]["product"] == "Global Prima Medical Insurance"
    assert enriched[0]["analysis"]["annual_limit"] == "€ 2,000,000"
    assert "evacuation_repatriation" in enriched[0]["analysis"]["benefits"]
    assert enriched[0]["analysis"]["premium"]["amount"] == 1234
    assert enriched[0]["evidence_documents"][0]["title"] == "IMG GPMI Table of Benefits"
