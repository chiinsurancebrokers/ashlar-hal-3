from backend.app.applications.adapters import (
    BupaApplicationAdapter,
    CignaApplicationAdapter,
    IMGApplicationAdapter,
)
from backend.app.cases.models import AshlarCase
from backend.app.workflows.service import JourneyWorkflowService


def test_cigna_adapter_adds_carrier_requirements_without_inventing_current_form_fields():
    case = AshlarCase(
        selected_plan_keys=["cigna:executive"],
        selected_plan_key="cigna:executive",
    )
    result = JourneyWorkflowService().prepare_application(case)

    blueprint = result.payload["blueprint"]
    assert blueprint["carrier"] == "cigna"
    assert blueprint["source_status"] == "adapter_ready_requirements_unverified"
    assert "cigna_employment_or_eligibility" in result.payload["application"]["required_sections"]
    assert "cigna_underwriting_basis_confirmation" in result.payload["application"]["required_sections"]


def test_medical_questionnaire_is_added_but_sensitive_answers_are_not_in_blueprint():
    case = AshlarCase(
        selected_plan_keys=["img:silver"],
        selected_plan_key="img:silver",
        needs_profile={"medical_disclosure_present": True},
    )
    result = JourneyWorkflowService().prepare_application(case)

    assert result.payload["blueprint"]["carrier"] == "img"
    assert "medical_underwriting_questionnaire" in result.payload["application"]["required_sections"]
    assert "medical_disclosure_present" not in str(result.payload["blueprint"])


def test_bupa_adapter_boundary_exists():
    adapter = BupaApplicationAdapter()
    assert adapter.supports("bupa:lifeline_classic")
    assert not adapter.supports("img:silver")
    assert CignaApplicationAdapter().supports("cigna:global")
    assert IMGApplicationAdapter().supports("img:gold")
