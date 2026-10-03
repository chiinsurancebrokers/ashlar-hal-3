from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Relationship = Literal["primary", "spouse", "partner", "child", "other"]
Sex = Literal["female", "male", "unspecified"]


class HouseholdMember(BaseModel):
    member_id: str
    relationship: Relationship
    age: int = Field(ge=0, le=120)
    sex: Sex = "unspecified"
    requirements: dict[str, bool] = Field(default_factory=dict)


class FamilyHouseholdDecision(BaseModel):
    family_requested: bool
    members: list[HouseholdMember] = Field(default_factory=list)
    maternity_member_ids: list[str] = Field(default_factory=list)
    household_size: int = 1
    pricing_mode: Literal["individual", "family_requires_verified_rating"] = "individual"
    warnings: list[str] = Field(default_factory=list)


def maternity_relevant(member: HouseholdMember) -> bool:
    """Deterministic relevance gate; never infer sex from name or other proxies."""
    return member.sex == "female" and 18 <= member.age <= 47


def assess_household(primary: HouseholdMember, dependents: list[HouseholdMember]) -> FamilyHouseholdDecision:
    members = [primary, *dependents]
    maternity_ids = [m.member_id for m in members if maternity_relevant(m)]
    family_requested = bool(dependents)
    warnings: list[str] = []
    if family_requested:
        warnings.append(
            "Family premium must come from verified carrier family-rating rules; do not sum individual premiums unless the carrier adapter explicitly supports that method."
        )
    return FamilyHouseholdDecision(
        family_requested=family_requested,
        members=members,
        maternity_member_ids=maternity_ids,
        household_size=len(members),
        pricing_mode="family_requires_verified_rating" if family_requested else "individual",
        warnings=warnings,
    )


def member_from_dict(raw: dict[str, Any], *, fallback_id: str, relationship: Relationship) -> HouseholdMember:
    return HouseholdMember(
        member_id=str(raw.get("member_id") or fallback_id),
        relationship=relationship,
        age=int(raw.get("age") or 0),
        sex=str(raw.get("sex") or "unspecified").lower(),
        requirements=dict(raw.get("requirements") or {}),
    )
