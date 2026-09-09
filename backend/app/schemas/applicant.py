from pydantic import BaseModel, Field


class Dependent(BaseModel):
    relationship: str = Field(pattern="^(spouse|partner|child|other)$")
    age: int = Field(ge=0, le=120)


class Applicant(BaseModel):
    age: int = Field(ge=0, le=120)
    residence_country: str = "Greece"
    nationality: str | None = None
    coverage_area: str = Field(default="area1", pattern="^(area1|area2|area3|area4)$")
    currency: str = "EUR"

    # Deductible: explicit preference, not just a raw number. "flexible"
    # means "no opinion" so pricing logic can tell that apart from "chose 0".
    deductible: float | None = Field(default=None, ge=0)
    deductible_preference: str = Field(default="flexible", pattern="^(flexible|fixed)$")

    outpatient_required: bool = False
    maternity_required: bool = False
    dental_required: bool = False
    mental_health_required: bool = False
    wellness_required: bool = False
    optical_required: bool = False
    evacuation_required: bool = False
    chronic_required: bool = False

    # Separate from chronic_required: this is "I already have a condition to
    # flag", which is an underwriting-relevant disclosure, not a benefit
    # preference. HAL never uses this to silently include/exclude plans -
    # it is surfaced to the broker so a human handles it appropriately.
    chronic_conditions_disclosed: bool = False
    chronic_conditions_note: str | None = Field(default=None, max_length=500)

    # Service/wealth-profile preferences. These do not alter premium
    # calculation unless a carrier adapter explicitly supports them; they
    # guide matching/explanation only.
    client_segment: str | None = None
    private_hospital_choice_required: bool = False
    cross_border_treatment_required: bool = False
    home_country_treatment_required: bool = False
    continuity_portability_required: bool = False
    high_annual_limit_required: bool = False
    private_room_required: bool = False
    direct_billing_required: bool = False
    second_medical_opinion_required: bool = False

    budget_annual: float | None = Field(default=None, ge=0)

    dependents: list[Dependent] = Field(default_factory=list)

    def family_size(self) -> int:
        return 1 + len(self.dependents)

    def all_ages(self) -> list[int]:
        return [self.age] + [d.age for d in self.dependents]

    def must_have_keys(self) -> list[str]:
        return [
            k for k in (
                "outpatient_required", "maternity_required", "dental_required",
                "mental_health_required", "wellness_required", "optical_required",
                "evacuation_required", "chronic_required",
            )
            if getattr(self, k)
        ]
