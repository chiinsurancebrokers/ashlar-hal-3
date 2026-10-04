from __future__ import annotations

from itertools import product
from typing import Any

from pydantic import BaseModel, Field


class MemberPlanOption(BaseModel):
    member_id: str
    plan_key: str
    insurer: str
    product_name: str
    premium: float = Field(ge=0)
    currency: str
    requirements_satisfied: bool
    verified: bool


class HouseholdPortfolio(BaseModel):
    allocations: list[MemberPlanOption]
    currency: str
    total_premium: float
    insurer_count: int
    plan_count: int
    complexity_notes: list[str] = Field(default_factory=list)


def optimise_household(options_by_member: dict[str, list[MemberPlanOption]], *, limit: int = 5) -> list[HouseholdPortfolio]:
    """Compose verified member quotes without inventing prices or benefits.

    Invalid/unverified options are discarded. Results prefer full requirement
    satisfaction, then lower household premium, then lower fragmentation.
    """
    member_ids = list(options_by_member)
    if not member_ids:
        return []
    pools = [[o for o in options_by_member[mid] if o.verified and o.requirements_satisfied] for mid in member_ids]
    if any(not pool for pool in pools):
        return []
    portfolios: list[HouseholdPortfolio] = []
    for allocation in product(*pools):
        currencies = {o.currency for o in allocation}
        if len(currencies) != 1:
            continue
        insurers = {o.insurer for o in allocation}
        plans = {o.plan_key for o in allocation}
        notes: list[str] = []
        if len(insurers) > 1:
            notes.append("Separate insurers may mean separate claims processes and renewal administration.")
        if len(plans) > 1:
            notes.append("Household members are allocated to different plans to better match their individual requirements.")
        portfolios.append(HouseholdPortfolio(
            allocations=list(allocation), currency=next(iter(currencies)),
            total_premium=round(sum(o.premium for o in allocation), 2),
            insurer_count=len(insurers), plan_count=len(plans), complexity_notes=notes,
        ))
    portfolios.sort(key=lambda p: (p.total_premium, p.insurer_count, p.plan_count))
    return portfolios[:limit]


def compose_household_payload(portfolios: list[HouseholdPortfolio]) -> dict[str, Any]:
    """Deterministic API/UI payload for the final household synthesis."""
    if not portfolios:
        return {"status": "personal_family_quotation_required", "options": []}
    return {
        "status": "verified_household_options",
        "options": [p.model_dump(mode="json") for p in portfolios],
    }
