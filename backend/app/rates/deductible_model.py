"""
Deductible pricing model.

IMPORTANT: as of the 2026 Morgan Price rate table, premiums are NOT
deductible-tiered — there is one annual_premium per age band/product/area,
full stop. Asking the applicant for a deductible preference and then not
using it anywhere was flagged in the v8 audit as actively misleading.

Until a carrier supplies real deductible-tiered rates, this module applies
a documented, editable illustrative discount so the question the applicant
answers actually changes the number they see — but every quote produced
this way carries an explicit warning that the figure is a HAL estimate
pending carrier confirmation, never presented as an official premium.

This entire model is OFF by default (see core/config.py,
`deductible_model_enabled`). Turn it on only after you've reviewed/agreed
the discount percentages below with the carrier or your own pricing team.
"""
from __future__ import annotations

# deductible amount (EUR) -> illustrative discount off the base premium
DEDUCTIBLE_DISCOUNT: dict[float, float] = {
    0: 0.0,
    500: 0.06,
    1000: 0.11,
    2000: 0.18,
}


def apply_deductible(
    base_premium: float,
    deductible: float | None,
    preference: str,
    *,
    enabled: bool,
) -> tuple[float, str]:
    """Returns (adjusted_premium, note). Never silently misleads:
    - If the model is disabled, or the applicant has no fixed preference,
      the base premium is returned untouched and the note says so.
    - If it IS applied, the note always says "illustrative, unconfirmed".
    """
    if not enabled:
        return base_premium, "deductible_preference_not_used_in_pricing"
    if preference != "fixed" or deductible is None:
        return base_premium, "no_fixed_deductible_no_adjustment_applied"

    tiers = sorted(DEDUCTIBLE_DISCOUNT)
    nearest = min(tiers, key=lambda t: abs(t - deductible))
    discount = DEDUCTIBLE_DISCOUNT[nearest]
    adjusted = round(base_premium * (1 - discount), 2)
    note = (
        f"illustrative_estimate_{int(discount * 100)}pct_discount_at_eur{int(nearest)}_deductible"
        "_pending_carrier_confirmation"
    )
    return adjusted, note
