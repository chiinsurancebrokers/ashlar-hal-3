from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.cases.models import AshlarCase


@dataclass(frozen=True, slots=True)
class ApplicationRequirement:
    key: str
    label: str
    owner: str = "client"
    required: bool = True
    sensitive: bool = False
    requires_signature: bool = False
    help_text: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationBlueprint:
    carrier: str
    plan_key: str
    requirements: tuple[ApplicationRequirement, ...]
    source_status: str
    note: str | None = None

    @property
    def required_sections(self) -> list[str]:
        return [item.key for item in self.requirements if item.required]


class ApplicationAdapter(Protocol):
    carrier: str

    def supports(self, plan_key: str) -> bool: ...

    def blueprint(self, case: AshlarCase, plan_key: str) -> ApplicationBlueprint: ...


_BASE = (
    ApplicationRequirement("applicant_identity", "Applicant identity"),
    ApplicationRequirement("contact_and_residency", "Contact & residency"),
    ApplicationRequirement("coverage_selection", "Coverage selection"),
    ApplicationRequirement("declarations", "Applicant declarations"),
)


class BaseCarrierApplicationAdapter:
    carrier = "generic"
    source_status = "generic_foundation"
    note = (
        "Generic application foundation only. Carrier-specific declarations and "
        "forms must be verified from the carrier's current application material."
    )

    def supports(self, plan_key: str) -> bool:
        return True

    def extra_requirements(self, case: AshlarCase) -> tuple[ApplicationRequirement, ...]:
        return ()

    def blueprint(self, case: AshlarCase, plan_key: str) -> ApplicationBlueprint:
        items = list(_BASE)
        items.extend(self.extra_requirements(case))
        if bool(case.needs_profile.get("medical_disclosure_present")):
            items.append(ApplicationRequirement(
                "medical_underwriting_questionnaire",
                "Medical underwriting questionnaire",
                sensitive=True,
                help_text="Collect in the underwriting boundary; do not infer medical answers from general HAL chat.",
            ))
        items.append(ApplicationRequirement(
            "signature",
            "Applicant signature",
            requires_signature=True,
        ))
        return ApplicationBlueprint(
            carrier=self.carrier,
            plan_key=plan_key,
            requirements=tuple(items),
            source_status=self.source_status,
            note=self.note,
        )


class CignaApplicationAdapter(BaseCarrierApplicationAdapter):
    carrier = "cigna"
    source_status = "adapter_ready_requirements_unverified"
    note = (
        "Cigna adapter boundary is ready. Exact current application fields, "
        "declarations and signatures must be loaded from broker-supplied Cigna "
        "application documents before automatic submission is enabled."
    )

    def supports(self, plan_key: str) -> bool:
        return plan_key.casefold().startswith("cigna:")

    def extra_requirements(self, case: AshlarCase) -> tuple[ApplicationRequirement, ...]:
        return (
            ApplicationRequirement("cigna_employment_or_eligibility", "Cigna eligibility / employment details"),
            ApplicationRequirement("cigna_underwriting_basis_confirmation", "Cigna underwriting basis confirmation", owner="broker"),
        )


class IMGApplicationAdapter(BaseCarrierApplicationAdapter):
    carrier = "img"
    source_status = "adapter_ready_requirements_unverified"
    note = (
        "IMG adapter boundary is ready. Exact current IMG application fields "
        "must be verified from the broker's current IMG application material."
    )

    def supports(self, plan_key: str) -> bool:
        return plan_key.casefold().startswith("img:")

    def extra_requirements(self, case: AshlarCase) -> tuple[ApplicationRequirement, ...]:
        return (
            ApplicationRequirement("img_eligibility_confirmation", "IMG eligibility confirmation"),
            ApplicationRequirement("img_underwriting_basis_confirmation", "IMG underwriting basis confirmation", owner="broker"),
        )


class BupaApplicationAdapter(BaseCarrierApplicationAdapter):
    carrier = "bupa"
    source_status = "adapter_ready_requirements_unverified"
    note = (
        "Bupa adapter boundary is ready. Exact current Bupa application fields "
        "must be verified from the broker's current Bupa application material."
    )

    def supports(self, plan_key: str) -> bool:
        return plan_key.casefold().startswith("bupa:")

    def extra_requirements(self, case: AshlarCase) -> tuple[ApplicationRequirement, ...]:
        return (
            ApplicationRequirement("bupa_eligibility_confirmation", "Bupa eligibility confirmation"),
            ApplicationRequirement("bupa_underwriting_basis_confirmation", "Bupa underwriting basis confirmation", owner="broker"),
        )


class ApplicationAdapterRegistry:
    def __init__(self, adapters: tuple[ApplicationAdapter, ...] | None = None):
        self.adapters = adapters or (
            CignaApplicationAdapter(),
            IMGApplicationAdapter(),
            BupaApplicationAdapter(),
        )
        self.fallback = BaseCarrierApplicationAdapter()

    def for_plan(self, plan_key: str) -> ApplicationAdapter:
        for adapter in self.adapters:
            if adapter.supports(plan_key):
                return adapter
        return self.fallback


_APPLICATION_ADAPTERS = ApplicationAdapterRegistry()


def get_application_adapters() -> ApplicationAdapterRegistry:
    return _APPLICATION_ADAPTERS
