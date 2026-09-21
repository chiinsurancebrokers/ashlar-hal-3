from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from backend.app.applications.adapters import ApplicationAdapterRegistry, get_application_adapters
from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.models import AshlarCase, CaseStatus, FactStatus, FactSourceType

from .models import (
    ApplicationRecord,
    ApplicationStatus,
    ClaimRecord,
    PlanSelectionRecord,
    PolicyRecord,
    PolicyWallet,
    PreauthorisationRecord,
    RenewalRecord,
    WorkflowResult,
)


class WorkflowError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_workflow_state"):
        super().__init__(message)
        self.code = code


class JourneyWorkflowService:
    """Deterministic lifecycle services for Adviser OS stages 13–20.

    These methods mutate only an in-memory AshlarCase copy supplied by the
    orchestrator. They never call an LLM and never bypass FactLedger/Policy
    Engine authority.
    """

    def __init__(self, application_adapters: ApplicationAdapterRegistry | None = None):
        self.application_adapters = application_adapters or get_application_adapters()

    @staticmethod
    def _require_selected_plan(case: AshlarCase) -> str:
        plan_key = str(case.selected_plan_key or "").strip()
        if not plan_key:
            raise WorkflowError(
                "A final plan must be selected before this workflow can continue.",
                code="plan_selection_required",
            )
        return plan_key

    def select_plan(
        self,
        case: AshlarCase,
        *,
        plan_key: str,
        selected_by: str = "client",
        note: str | None = None,
    ) -> WorkflowResult:
        selected = str(plan_key or "").strip()
        if not selected or selected not in case.selected_plan_keys:
            raise WorkflowError(
                "The selected plan must belong to the active 2–4 plan shortlist.",
                code="invalid_selected_plan",
            )

        record = PlanSelectionRecord(
            plan_key=selected,
            selected_by="broker" if selected_by == "broker" else "client",
            note=note,
        )
        if case.policy and not case.renewal:
            raise WorkflowError("Start a renewal review before changing an issued plan.")
        if case.selected_plan_key != selected and case.application:
            case.metadata.setdefault("application_history", []).append(deepcopy(case.application))
            case.application = None
        case.selected_plan_key = selected
        case.metadata["plan_selection"] = record.model_dump(mode="json")
        case.touch()
        return WorkflowResult(
            action="prepare_application",
            message="The final plan choice has been recorded on the AshlarCase.",
            payload={
                "selected_plan_key": selected,
                "selection": record.model_dump(mode="json"),
            },
        )

    def prepare_application(self, case: AshlarCase) -> WorkflowResult:
        plan_key = self._require_selected_plan(case)
        if case.application:
            current = ApplicationRecord.model_validate(case.application)
            if current.plan_key != plan_key:
                raise WorkflowError("Application does not match the selected plan.")
        else:
            adapter = self.application_adapters.for_plan(plan_key)
            blueprint = adapter.blueprint(case, plan_key)
            current = ApplicationRecord(
                plan_key=plan_key,
                required_sections=blueprint.required_sections,
            )
            case.application = current.model_dump(mode="json")
            case.metadata["application_blueprint"] = {
                "carrier": blueprint.carrier,
                "source_status": blueprint.source_status,
                "note": blueprint.note,
                "requirements": [
                    {
                        "key": item.key,
                        "label": item.label,
                        "owner": item.owner,
                        "required": item.required,
                        "sensitive": item.sensitive,
                        "requires_signature": item.requires_signature,
                        "help_text": item.help_text,
                    }
                    for item in blueprint.requirements
                ],
            }

        if not case.policy:
            case.status = CaseStatus.APPLICATION
        case.touch()
        return WorkflowResult(
            action="complete_application",
            message="The application workspace is ready.",
            payload={
                "application": current.model_dump(mode="json"),
                "missing_sections": current.missing_sections,
                "blueprint": deepcopy(case.metadata.get("application_blueprint") or {}),
            },
        )

    def complete_application_section(
        self,
        case: AshlarCase,
        *,
        section: str,
        broker_authorized: bool = False,
        note: str = "",
        document_refs: list[str] | None = None,
    ) -> WorkflowResult:
        self._require_selected_plan(case)
        if not case.application:
            raise WorkflowError(
                "Prepare the application before completing its sections.",
                code="application_not_prepared",
            )
        record = ApplicationRecord.model_validate(case.application)
        if record.status == ApplicationStatus.SUBMITTED:
            raise WorkflowError("Submitted application sections are immutable.")
        requirement = next((x for x in case.metadata.get("application_blueprint", {}).get("requirements", []) if x["key"] == section), {})
        if requirement.get("owner") == "broker" and not broker_authorized:
            raise WorkflowError("This section requires an authorised broker.", code="broker_authorisation_required")
        if not note.strip():
            raise WorkflowError("Record the information or evidence reviewed for this section.")
        if requirement.get("requires_signature") and not document_refs:
            raise WorkflowError("Attach the signed application document; a checklist tick is not a signature.")
        record.section_data[section] = {"note": note, "document_refs": list(document_refs or []), "recorded_by": "broker" if broker_authorized else "client", "at": datetime.now(timezone.utc).isoformat()}
        record.updated_at = datetime.now(timezone.utc)
        value = str(section or "").strip()
        if value not in record.required_sections:
            raise WorkflowError(
                "That section is not part of this application checklist.",
                code="unknown_application_section",
            )
        if value not in record.completed_sections:
            record.completed_sections.append(value)
        record.status = (
            ApplicationStatus.READY
            if not record.missing_sections
            else ApplicationStatus.DRAFT
        )
        case.application = record.model_dump(mode="json")
        case.touch()
        return WorkflowResult(
            action="submit_application" if record.status == ApplicationStatus.READY else "complete_application",
            message=(
                "The application is ready for submission."
                if record.status == ApplicationStatus.READY
                else "Application section completed."
            ),
            payload={
                "application": record.model_dump(mode="json"),
                "missing_sections": record.missing_sections,
            },
        )

    def submit_application(self, case: AshlarCase, *, broker_authorized: bool = False, external_reference: str = "") -> WorkflowResult:
        if not broker_authorized:
            raise WorkflowError("A broker must record the actual carrier submission.", code="broker_authorisation_required")
        if not external_reference.strip():
            raise WorkflowError("A real carrier submission reference is required.")
        if not case.application:
            raise WorkflowError("No application is prepared.", code="application_not_prepared")
        record = ApplicationRecord.model_validate(case.application)
        if record.missing_sections:
            raise WorkflowError(
                "The application still has incomplete required sections.",
                code="application_incomplete",
            )
        if record.status == ApplicationStatus.SUBMITTED:
            raise WorkflowError("The submission has already been recorded.")
        record.submission_reference = external_reference
        record.updated_at = datetime.now(timezone.utc)
        record.status = ApplicationStatus.SUBMITTED
        case.application = record.model_dump(mode="json")
        case.status = CaseStatus.APPLICATION
        case.touch()
        return WorkflowResult(
            action="await_policy_issue",
            message="The broker’s external carrier submission reference has been recorded. Ashlar did not transmit the application.",
            payload={"application": record.model_dump(mode="json")},
        )

    def issue_policy(
        self,
        case: AshlarCase,
        *,
        policy_number: str,
        provider: str,
        start_date: date,
        renewal_date: date,
        document_refs: list[str] | None = None,
    ) -> WorkflowResult:
        plan_key = self._require_selected_plan(case)
        if not case.application:
            raise WorkflowError(
                "An application record is required before policy issue.",
                code="application_required",
            )
        application = ApplicationRecord.model_validate(case.application)
        if application.status != ApplicationStatus.SUBMITTED:
            raise WorkflowError(
                "The application must be submitted before policy issue is recorded.",
                code="application_not_submitted",
            )

        if renewal_date <= start_date:
            raise WorkflowError("Renewal date must be after the policy start date.")
        carrier = plan_key.split(":")[0]
        if carrier in {"img", "cigna", "bupa"} and not provider.strip().lower().startswith(carrier):
            raise WorkflowError("Carrier must match the selected plan.")
        if str(application.application_id) in case.metadata.get("issued_application_ids", []):
            raise WorkflowError("This application already has an issued policy.")
        if not document_refs:
            raise WorkflowError("Attach the issued policy schedule before recording issuance.")
        case.metadata.setdefault("issued_application_ids", []).append(str(application.application_id))
        if case.policy:
            case.metadata.setdefault("policy_history", []).append(deepcopy(case.policy))
        policy = PolicyRecord(
            policy_number=policy_number,
            provider=provider,
            plan_key=plan_key,
            start_date=start_date,
            renewal_date=renewal_date,
            document_refs=list(document_refs or []),
        )
        case.policy = policy.model_dump(mode="json")
        if case.renewal:
            case.renewal["status"] = "completed"
            case.renewal["selected_plan_key"] = plan_key
        case.status = CaseStatus.ACTIVE_POLICY
        case.touch()
        return WorkflowResult(
            action="open_policy_wallet",
            message="The issued policy has been recorded on the AshlarCase.",
            payload={"policy": policy.model_dump(mode="json")},
        )

    def build_policy_wallet(self, case: AshlarCase) -> WorkflowResult:
        if not case.policy:
            raise WorkflowError("No issued policy is stored on this case.", code="policy_required")
        policy = PolicyRecord.model_validate(case.policy)
        issued = issued_policy_facts(case)
        ledger = FactLedger(issued)
        subject = f"plan:{policy.plan_key}"

        core_keys = (
            "annual_limit",
            "deductible_or_excess",
            "area_of_cover",
            "underwriting_basis",
            "premium_amount",
        )
        core: dict[str, Any] = {}
        for key in core_keys:
            fact = ledger.current(key, subject=subject)
            if fact is not None and fact.status == FactStatus.VERIFIED:
                core[key] = deepcopy(fact.value)

        benefits: dict[str, Any] = {}
        for fact in issued:
            if (
                fact.subject == subject
                and fact.status == FactStatus.VERIFIED
                and fact.key.startswith("benefit.")
            ):
                current = ledger.current(fact.key, subject=subject)
                if current is not None and current.status == FactStatus.VERIFIED:
                    benefits[fact.key.removeprefix("benefit.")] = deepcopy(current.value)

        conflicts = [
            conflict.key
            for conflict in ledger.conflicts()
            if conflict.subject == subject
        ]
        wallet = PolicyWallet(
            policy_number=policy.policy_number,
            provider=policy.provider,
            plan_key=policy.plan_key,
            start_date=policy.start_date,
            renewal_date=policy.renewal_date,
            core_facts=core,
            verified_benefits=benefits,
            unresolved_conflicts=conflicts,
            evidence=[f.model_dump(mode="json") for f in issued if f.status == FactStatus.VERIFIED],
            terms_status="verified_issued_terms" if core or benefits else "issued_terms_unverified",
        )
        case.metadata["policy_wallet"] = wallet.model_dump(mode="json")
        case.touch()
        return WorkflowResult(
            action="use_policy_wallet",
            message="The Policy Wallet has been built from issued-policy data and verified facts only.",
            payload={"wallet": wallet.model_dump(mode="json")},
        )

    def create_preauthorisation(
        self,
        case: AshlarCase,
        *,
        service_key: str,
        provider_name: str | None = None,
        facility_name: str | None = None,
        planned_date: date | None = None,
        document_refs: list[str] | None = None,
    ) -> WorkflowResult:
        plan_key = str((case.policy or {}).get("plan_key") or "")
        if not case.policy or case.policy.get("status") != "active":
            raise WorkflowError(
                "An active issued policy is required before pre-authorisation.",
                code="active_policy_required",
            )
        service_day = planned_date or date.today()
        if not (date.fromisoformat(case.policy["start_date"]) <= service_day < date.fromisoformat(case.policy["renewal_date"])):
            raise WorkflowError("The planned service falls outside the recorded policy period.")
        record = PreauthorisationRecord(
            plan_key=plan_key,
            service_key=service_key,
            provider_name=provider_name,
            facility_name=facility_name,
            planned_date=planned_date,
            document_refs=list(document_refs or []),
        )
        case.preauthorisations.append(record.model_dump(mode="json"))
        case.touch()
        return WorkflowResult(
            action="check_policy_and_submit_preauthorisation",
            message="A pre-authorisation request has been opened on the active policy.",
            payload={"preauthorisation": record.model_dump(mode="json")},
        )

    def create_claim(
        self,
        case: AshlarCase,
        *,
        service_date: date | None = None,
        amount: float | None = None,
        currency: str | None = None,
        document_refs: list[str] | None = None,
        note: str | None = None,
    ) -> WorkflowResult:
        plan_key = str((case.policy or {}).get("plan_key") or "")
        if not case.policy:
            raise WorkflowError(
                "An issued policy is required before a claim can be opened.",
                code="policy_required",
            )
        if service_date and not (date.fromisoformat(case.policy["start_date"]) <= service_date < date.fromisoformat(case.policy["renewal_date"])):
            raise WorkflowError("Claim service date falls outside the recorded policy period.")
        claim = ClaimRecord(
            plan_key=plan_key,
            service_date=service_date,
            amount=amount,
            currency=currency,
            document_refs=list(document_refs or []),
            note=note,
        )
        case.claims.append(claim.model_dump(mode="json"))
        case.status = CaseStatus.CLAIM
        case.touch()
        return WorkflowResult(
            action="collect_claim_evidence",
            message="A claim case has been opened.",
            payload={"claim": claim.model_dump(mode="json")},
        )

    def start_renewal(self, case: AshlarCase) -> WorkflowResult:
        if not case.policy:
            raise WorkflowError(
                "An issued policy is required before renewal comparison.",
                code="policy_required",
            )
        policy = PolicyRecord.model_validate(case.policy)
        if case.renewal and case.renewal.get("status") != "completed":
            raise WorkflowError("A renewal review is already open.")
        case.metadata["renewal_baseline"] = {"policy": deepcopy(case.policy), "facts": [f.model_dump(mode="json") for f in issued_policy_facts(case)]}
        renewal = RenewalRecord(
            current_plan_key=policy.plan_key,
            renewal_date=policy.renewal_date,
        )
        if case.application:
            case.metadata.setdefault("application_history", []).append(deepcopy(case.application))
            case.application = None
        case.metadata.pop("renewal_intake_confirmed", None)
        case.renewal = renewal.model_dump(mode="json")
        case.status = CaseStatus.RENEWAL
        case.touch()
        return WorkflowResult(
            action="refresh_renewal_quotes",
            message="The renewal review has started.",
            payload={"renewal": renewal.model_dump(mode="json")},
        )


def issued_policy_facts(case: AshlarCase):
    """Only evidence explicitly reconciled with this issued schedule is authoritative."""
    if not case.policy:
        return []
    ids = set(case.metadata.get("issued_terms_fact_ids", {}).get(str(case.policy.get("policy_id")), []))
    return [f for f in case.facts if str(f.fact_id) in ids and f.source.source_type in {FactSourceType.POLICY_SCHEDULE, FactSourceType.POLICY_WORDING}]


_JOURNEY_WORKFLOW = JourneyWorkflowService()


def get_journey_workflow() -> JourneyWorkflowService:
    return _JOURNEY_WORKFLOW
