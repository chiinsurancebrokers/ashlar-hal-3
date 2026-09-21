from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.evidence.compare_matrix import build_comparison_matrix


client = TestClient(app)


def test_verified_catalogue_separates_benefits_from_pricing():
    response = client.get("/api/v1/quotes/catalogue")
    assert response.status_code == 200
    plans = response.json()["plans"]
    by_key = {row["plan_key"]: row for row in plans}

    assert by_key["img:gpmi_bronze"]["benefit_evidence_status"] == "verified"
    assert by_key["img:gpmi_bronze"]["pricing_status"] == "quotation_required"
    assert by_key["cigna:inspire_executive_care"]["benefit_evidence_status"] == "verified"
    assert by_key["cigna:inspire_executive_care"]["pricing_status"] == "quotation_required"
    assert "No verified general Cigna price table" in by_key["cigna:inspire_executive_care"]["pricing_note"]


def test_img_gpmi_matrix_uses_verified_brochure_values():
    matrix = build_comparison_matrix([
        {
            "plan_key": "img:gpmi_bronze",
            "carrier": "img",
            "product_code": "bronze",
            "insurer": "IMG",
            "product_name": "IMG Bronze",
        },
        {
            "plan_key": "img:gpmi_platinum",
            "carrier": "img",
            "product_code": "platinum",
            "insurer": "IMG",
            "product_name": "IMG Platinum",
        },
    ])
    rows = {row.benefit_code: row for row in matrix.rows}
    assert rows["overall_maximum"].values["img:gpmi_bronze"] == "€1,000,000 — Bronze: no pre-existing condition cover"
    assert rows["overall_maximum"].values["img:gpmi_platinum"] == "€5,000,000"
    assert rows["outpatient_psychiatric"].values["img:gpmi_bronze"] == "Not covered"
    assert rows["outpatient_psychiatric"].values["img:gpmi_platinum"] == "€10,000 each year"


def test_cigna_inspire_is_comparable_without_fake_price():
    matrix = build_comparison_matrix([
        {
            "plan_key": "cigna:inspire_executive_care",
            "carrier": "cigna",
            "product_code": "executive_care",
            "insurer": "Cigna Healthcare",
            "product_name": "ExecutiveCare",
        },
        {
            "plan_key": "cigna:inspire_elite_care",
            "carrier": "cigna",
            "product_code": "elite_care",
            "insurer": "Cigna Healthcare",
            "product_name": "EliteCare",
        },
    ])
    rows = {row.benefit_code: row for row in matrix.rows}
    assert rows["overall_maximum"].values["cigna:inspire_executive_care"] == "€7,500,000"
    assert rows["overall_maximum"].values["cigna:inspire_elite_care"] == "Unlimited"
    assert rows["medical_evacuation_transport"].values["cigna:inspire_executive_care"] == "Paid in Full"
