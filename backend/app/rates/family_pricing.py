"""
Family / dependents pricing.

Insurers price each insured life individually against the same rate table
(there is no separate "family rate" in the Morgan Price 2026 data) and then
bundle them under one policy. This module mirrors that:

  1. Every family member (primary + each dependent) is priced against the
     SAME carrier/product/area for their own age.
  2. A product is only offered as a family option if EVERY member's age
     falls inside that product's age band. If one dependent doesn't
     qualify for a product, that product is not offered for the family at
     all (rather than silently quoting only part of the family).
  3. The CARRIER's own family discount ladder is applied.

The ladder itself is deliberately NOT defined here. It is one insurer's
commercial policy, so it lives beside that insurer's evidence and is read
through `rates/carrier_pricing.py`; a carrier with no recorded rule gets
no discount. See that module's docstring for why.

This module only knows how to *apply* a rule: a headline percentage that
steps up with household size and caps, applied to the N highest-premium
lives, with every further life charged the undiscounted rate.
"""
from __future__ import annotations
from dataclasses import dataclass

from backend.app.rates.registry import RateRecord
from backend.app.rates.carrier_pricing import FamilyDiscountRule, NO_FAMILY_DISCOUNT


@dataclass(frozen=True)
class FamilyQuote:
    # The amount actually charged for each member, in the order the members
    # were supplied — i.e. what the carrier's quote document shows per line,
    # already net of any discount that member received.
    per_member_premiums: list[float]
    # Undiscounted sum, before the family ladder.
    subtotal: float
    discount_applied: bool
    discount_pct: float
    # How many lives actually received the discount.
    discounted_member_count: int
    total: float


def family_eligible(records_by_age: list[list[RateRecord]]) -> bool:
    """records_by_age[i] = candidate rate rows for family member i at this
    product/area. All members must have at least one matching row."""
    return all(bool(rows) for rows in records_by_age)


def price_family(
    member_premiums: list[float],
    *,
    rule: FamilyDiscountRule = NO_FAMILY_DISCOUNT,
    member_ages: list[int] | None = None,
) -> FamilyQuote:
    """Apply one carrier's family discount rule to a priced household.

    `rule` comes from carrier_pricing.family_discount_rule(carrier). The
    default is no discount, so a carrier HAL holds no rules for is quoted
    at the plain sum of its members.
    """
    n = len(member_premiums)
    subtotal = round(sum(member_premiums), 2)
    if n == 0:
        return FamilyQuote([], 0.0, False, 0.0, 0, 0.0)

    pct = rule.pct_for(n)
    if pct <= 0:
        return FamilyQuote([round(p, 2) for p in member_premiums], subtotal, False, 0.0, 0, subtotal)

    discounted_count = min(n, rule.max_discounted_members) if rule.max_discounted_members else n

    # Rank members by premium (desc); age breaks ties so the older life keeps
    # the discount, which reproduces the carrier's own per-line figures. Ages
    # are optional — without them the ranking is by premium alone, which
    # yields the same family total either way.
    ages = member_ages if member_ages and len(member_ages) == n else [0] * n
    order = sorted(range(n), key=lambda i: (-member_premiums[i], -ages[i]))
    discounted_idx = set(order[:discounted_count])

    # The carrier computes the household total from the undiscounted figures
    # and rounds ONCE at the end; rounding each member first and then adding
    # them up drifts by a cent on some compositions. Verified against the
    # five Morgan Price quick-quotes recorded in pricing_rules.json.
    exact = [premium * (1 - pct) if i in discounted_idx else premium
             for i, premium in enumerate(member_premiums)]
    total = round(sum(exact), 2)

    # Per-member figures are a display of that total, so they must reconcile
    # to it. Round each line, then give the leftover cent to the largest
    # member rather than letting the lines disagree with the total on screen.
    charged = [round(value, 2) for value in exact]
    drift = round(total - round(sum(charged), 2), 2)
    if drift and charged:
        biggest = max(range(len(charged)), key=lambda i: charged[i])
        charged[biggest] = round(charged[biggest] + drift, 2)

    return FamilyQuote(
        per_member_premiums=charged,
        subtotal=subtotal,
        discount_applied=True,
        discount_pct=pct,
        discounted_member_count=discounted_count,
        total=total,
    )
