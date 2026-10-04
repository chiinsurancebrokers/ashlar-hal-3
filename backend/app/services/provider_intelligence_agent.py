from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


RuleType = Literal[
    "family_discount", "child_discount", "couple_discount", "promo",
    "payment_discount", "group_discount", "broker_offer", "rating_override",
]


class ProviderCommercialRule(BaseModel):
    rule_id: str
    provider: str
    product: str | None = None
    rule_type: RuleType
    percent: float | None = Field(default=None, ge=0, le=100)
    fixed_amount: float | None = Field(default=None, ge=0)
    currency: str | None = None
    min_household_size: int = Field(default=1, ge=1)
    relationships: list[str] = Field(default_factory=list)
    effective_from: date
    expires_on: date | None = None
    evidence_ref: str
    approved: bool = False

    def active_on(self, when: date) -> bool:
        return self.approved and self.effective_from <= when and (self.expires_on is None or when <= self.expires_on)


def applicable_rules(
    rules: list[ProviderCommercialRule], *, provider: str, product: str | None,
    household_size: int, when: date | None = None,
) -> list[ProviderCommercialRule]:
    """Return only approved, in-force, evidence-backed commercial rules.

    The provider agent never invents a discount and never performs premium
    arithmetic. Quote/rating code consumes these deterministic facts.
    """
    when = when or date.today()
    out: list[ProviderCommercialRule] = []
    for rule in rules:
        if not rule.evidence_ref.strip() or not rule.active_on(when):
            continue
        if rule.provider.casefold() != provider.casefold():
            continue
        if rule.product and (not product or rule.product.casefold() != product.casefold()):
            continue
        if household_size < rule.min_household_size:
            continue
        out.append(rule)
    return out
