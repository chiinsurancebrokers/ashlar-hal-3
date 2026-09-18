from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def _attach_selected_quotations(compare_data, selected_plans):
    refs = []
    for plan in selected_plans:
        upload = client.post(
            "/api/v1/documents/upload",
            data={
                "case_id": compare_data["case_id"],
                "case_token": compare_data["case_token"],
                "provider_label": plan["insurer"],
                "target_plan": plan["product_name"],
                "plan_key": plan["plan_key"],
                "role": "quotation",
            },
            files={
                "file": (
                    f'{plan["product_code"]}-quotation.txt',
                    (
                        f'{plan["product_name"]} applicant quotation. '
                        f'Annual premium EUR {plan["premium"]}. '
                        'Area of cover Europe. Applicant-specific carrier quotation.'
                    ).encode(),
                    "text/plain",
                )
            },
        )
        assert upload.status_code == 200, upload.text
        refs.append(upload.json()["document_ref"])
    return refs


def test_server_owned_case_can_prepare_and_download_real_proposal():
    applicant = {
        "age": 51,
        "residence_country": "Greece",
        "coverage_area": "area1",
        "outpatient_required": True,
        "applicant_name": "Proposal Flow Test",
    }
    preview = client.post("/api/v1/quotes/preview", json=applicant)
    assert preview.status_code == 200
    shortlist = preview.json()["shortlist"]
    assert len(shortlist) >= 2
    selected_plans = shortlist[:2]
    plan_keys = [item["plan_key"] for item in selected_plans]

    comparison = client.post(
        "/api/v1/quotes/compare",
        json={"applicant_state": applicant, "plan_keys": plan_keys, "language": "en"},
    )
    assert comparison.status_code == 200
    compare_data = comparison.json()
    assert compare_data["proposal_available"] is False

    blocked = client.post(
        "/api/v1/proposals/prepare",
        json={
            "case_id": compare_data["case_id"],
            "case_token": compare_data["case_token"],
            "language": "en",
        },
    )
    assert blocked.status_code == 422

    refs = _attach_selected_quotations(compare_data, selected_plans)
    analysed = client.post(
        "/api/v1/adviser/handle",
        json={
            "case_id": compare_data["case_id"],
            "case_token": compare_data["case_token"],
            "message": "Compare these carrier quotations.",
            "document_refs": refs,
        },
    )
    assert analysed.status_code == 200, analysed.text
    analysed_data = analysed.json()
    assert analysed_data["next_best_action"]["action"] == "prepare_proposal"

    prepared = client.post(
        "/api/v1/proposals/prepare",
        json={
            "case_id": compare_data["case_id"],
            "case_token": compare_data["case_token"],
            "language": "en",
        },
    )
    assert prepared.status_code == 200, prepared.text
    data = prepared.json()
    assert data["status"] == "ready"
    assert data["case_status"] == "proposal"
    assert data["case_intelligence"]["journey"]["current_phase"] == "decide"

    pdf = client.get(data["downloads"]["pdf"])
    pptx = client.get(data["downloads"]["pptx"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"].startswith("no-store")
    assert pptx.status_code == 200
    assert pptx.content.startswith(b"PK")
    assert pptx.headers["cache-control"].startswith("no-store")
