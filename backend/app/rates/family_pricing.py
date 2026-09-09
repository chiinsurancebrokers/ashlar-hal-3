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
  3. Premiums are summed.
  4. An optional, clearly-labelled family discount is applied for 2+ lives.
     This is illustrative until a carrier confirms its own figure — same
     philosophy as deductible_model.py.
"""
from __future__ import annotations
from dataclasses import dataclass

from backend.app.rates.registry import RateRecord


@dataclass(frozen=True)
class FamilyQuote:
    per_member_premiums: list[float]
    subtotal: float
    discount_applied: bool
    discount_pct: float
    total: float


def family_eligible(records_by_age: list[list[RateRecord]]) -> bool:
    """records_by_age[i] = candidate rate rows for family member i at this
    product/area. All members must have at least one matching row."""
    return all(bool(rows) for rows in records_by_age)


def price_family(
    member_premiums: list[float],
    *,
    family_discount_pct: float,
) -> FamilyQuote:
    subtotal = round(sum(member_premiums), 2)
    apply_discount = len(member_premiums) >= 2 and family_discount_pct > 0
    total = round(subtotal * (1 - family_discount_pct), 2) if apply_discount else subtotal
    return FamilyQuote(
        per_member_premiums=member_premiums,
        subtotal=subtotal,
        discount_applied=apply_discount,
        discount_pct=family_discount_pct if apply_discount else 0.0,
        total=total,
    )
