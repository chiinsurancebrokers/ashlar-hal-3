from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_homepage_loads_corporate_group_extension_and_keeps_no_cache():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert '/static/corporate-group.js' in response.text
    assert 'no-store' in response.headers.get('cache-control', '')


def test_corporate_ui_posts_prefilled_fact_find_to_dedicated_endpoint():
    js = (ROOT / 'frontend' / 'corporate-group.js').read_text(encoding='utf-8')
    assert "API + '/corporate/enquiry'" in js
    assert "JSON.stringify(halState())" in js
    assert "group_fact_find_summary" in js
    assert "groupCensusFile" in js
    assert "no_medical_data_confirmed" in js
    assert "5 * 1024 * 1024" in js


def test_corporate_ui_does_not_replace_normal_lead_submission():
    js = (ROOT / 'frontend' / 'corporate-group.js').read_text(encoding='utf-8')
    assert "if (!isCorporate()) return coreSubmitLead();" in js
    assert "if (!isCorporate()) return;" in js
