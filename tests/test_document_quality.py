from backend.app.documents.quality import assess_result_quality


def test_quality_blocks_when_no_selected_plan_and_missing_material_fields():
    result = {"analysis": {"provider": "X", "premium": {}, "benefits": {}, "confidence": "low"}}
    quality = assess_result_quality(result)
    assert quality["status"] == "blocked"
    assert quality["can_generate"] is False
    assert "selected plan" in quality["missing_fields"]


def test_quality_allows_complete_analysis():
    result = {
        "target_plan": "Executive",
        "analysis": {
            "plan_name": "Executive",
            "premium": {"amount": 1000},
            "annual_limit": "€1m",
            "deductible_or_excess": "€0",
            "area_of_cover": "Europe",
            "benefits": {
                "inpatient": "Covered", "outpatient": "Covered", "cancer": "Covered",
                "chronic_conditions": "Covered", "mental_health": "Covered", "evacuation_repatriation": "Covered"
            },
            "confidence": "high",
        },
    }
    quality = assess_result_quality(result)
    assert quality["status"] == "ready"
    assert quality["can_generate"] is True
