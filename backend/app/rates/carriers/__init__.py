"""Per-carrier commercial policy: family discounts, instalment loading,
who the carrier will issue a policy to, and how premium tax is treated.

WHY ONE MODULE PER CARRIER
--------------------------
These are an insurer's own commercial terms, not properties of
international health insurance. Morgan Price gives 5% for a couple rising
to 15% for four lives, requires two adults on the policy, charges 8% to
pay monthly and will not insure a child under 10 on their own. APRIL, IMG,
Bupa Global, Allianz Care, Cigna and Now Health each set their own, and
some give none at all.

Until 15 Oct 2026 HAL carried a single global `family_discount_pct` in
Settings. The moment a second carrier's workbook loaded, that carrier's
families would have been quoted on Morgan Price's commercial terms without
anyone noticing.

So each carrier gets a module of its own. Python rather than data files
because these rules carry logic, not just numbers: "the four highest-
premium lives", "minimum two adults", "every further child at full rate".
A new carrier may need "third child free" or a per-band ladder, and a JSON
schema flexible enough for all of that is a programming language with
worse error messages. Document transcriptions — the Table of Benefits,
the claims evidence — stay in JSON under data/evidence/, because those are
frozen copies of a document rather than decisions we make.

ADDING A CARRIER
----------------
Copy `_template.py`, fill it in from that carrier's own documents with the
document code and page beside every figure, and register it in `_REGISTRY`
below. A carrier that is not registered gets NO discount, NO instalment
loading and NO child limits — quoting terms an insurer has not confirmed
is inventing a price. Over-quoting is the safe direction: a broker corrects
it downward and the client is pleasantly surprised, where under-quoting
means they meet a bigger number at proposal stage.

WHEN A CARRIER CHANGES ITS RATES OR TERMS
-----------------------------------------
Open that carrier's module, change the figures, update `verified_on` and
the evidence list, and run the carrier's reconciliation tests. Nothing
else in HAL needs touching.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


# ---------------------------------------------------------------------------
# The shared contract every carrier module fills in
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FamilyDiscountRule:
    """A carrier's family discount ladder.

    discount_pct = step_pct * min(lives - 1, max_steps), applied to the
    `max_discounted_members` highest-premium lives, and only when at least
    `min_adults` adults are on the policy.
    """
    step_pct: float = 0.0
    max_steps: int = 0
    max_discounted_members: int = 0
    min_adults: int = 0
    adult_from_age: int = 19
    # Largest household actually reconciled against the carrier's own quote
    # engine. Above this HAL has no evidence and must not extrapolate.
    max_verified_lives: int | None = None

    @property
    def gives_discount(self) -> bool:
        return self.step_pct > 0 and self.max_steps > 0

    def adults_in(self, ages: list[int] | None) -> int:
        """With no ages supplied we cannot tell, so assume the condition is
        met rather than silently stripping a discount the client is due."""
        if ages is None:
            return self.min_adults
        return sum(1 for age in ages if age >= self.adult_from_age)

    def pct_for(self, lives: int, ages: list[int] | None = None) -> float:
        if lives < 2 or not self.gives_discount:
            return 0.0
        if self.min_adults and self.adults_in(ages) < self.min_adults:
            return 0.0
        return self.step_pct * min(lives - 1, self.max_steps)


@dataclass(frozen=True)
class InstalmentLoading:
    """What the carrier adds for paying in instalments rather than annually.

    HAL used to show a monthly figure as annual/12, which is every carrier's
    annual price divided by twelve — a number no client is ever charged.
    """
    monthly_pct: float = 0.0
    quarterly_pct: float = 0.0
    semi_annual_pct: float = 0.0
    annual_pct: float = 0.0
    annual_bank_transfer_fee: dict = field(default_factory=dict)

    FREQUENCIES = ("monthly", "quarterly", "semi_annual", "annual")
    INSTALMENTS_PER_YEAR = {"monthly": 12, "quarterly": 4, "semi_annual": 2, "annual": 1}

    @property
    def has_loading(self) -> bool:
        return any(p > 0 for p in (self.monthly_pct, self.quarterly_pct,
                                   self.semi_annual_pct, self.annual_pct))

    def pct_for(self, frequency: str) -> float:
        return {
            "monthly": self.monthly_pct,
            "quarterly": self.quarterly_pct,
            "semi_annual": self.semi_annual_pct,
            "annual": self.annual_pct,
        }.get(frequency, 0.0)

    def bank_fee(self, currency: str) -> float:
        return float((self.annual_bank_transfer_fee or {}).get((currency or "EUR").upper(), 0) or 0)

    def schedule(self, annual_premium: float, currency: str = "EUR") -> list[dict]:
        """Every way this carrier lets a client pay, with the real figures.

        The annual option carries a flat bank transfer fee rather than a
        percentage, so it is added after the loading, not multiplied in."""
        out = []
        for freq in self.FREQUENCIES:
            pct = self.pct_for(freq)
            total = round(annual_premium * (1 + pct), 2)
            if freq == "annual":
                total = round(total + self.bank_fee(currency), 2)
            n = self.INSTALMENTS_PER_YEAR[freq]
            out.append({
                "frequency": freq,
                "loading_pct": pct,
                "instalment_amount": round(total / n, 2),
                "instalments_per_year": n,
                "annual_total": total,
            })
        return out


@dataclass(frozen=True)
class PolicyIssuanceRule:
    """Who the carrier will issue a policy to, independent of price.

    A quote for a policy the insurer would refuse is worth nothing: the
    client applies, is declined, and the quote wasted their time.
    """
    child_only_min_age: int | None = None
    child_only_max_age: int | None = None
    child_only_excess_per_claim: dict = field(default_factory=dict)
    under_min_age_requires_an_adult: bool = False
    max_entry_age_fmu: int | None = None
    max_entry_age_moratorium: int | None = None

    @property
    def has_child_rules(self) -> bool:
        return self.child_only_min_age is not None

    def blocks_single_life(self, age: int) -> bool:
        if not self.has_child_rules or not self.under_min_age_requires_an_adult:
            return False
        return age < self.child_only_min_age

    def is_child_only_policy(self, ages: list[int]) -> bool:
        if not self.has_child_rules or len(ages) != 1:
            return False
        return self.child_only_min_age <= ages[0] <= (self.child_only_max_age or 17)

    def compulsory_excess(self, currency: str) -> float:
        return float((self.child_only_excess_per_claim or {}).get((currency or "EUR").upper(), 0) or 0)


@dataclass(frozen=True)
class PremiumTaxTreatment:
    """How insurance premium tax sits against the carrier's quoted price.

    HAL never DERIVES a tax rate. Rates depend on the country of residence
    and the contract type, they are in no rate workbook, and a table of
    guesses for forty countries would be wrong somewhere — exactly the
    invented number HAL exists not to produce.

    It does carry rates the carrier has confirmed in writing, country by
    country, with the source recorded. That is not a guess, it is the same
    class of fact as a rate table. For a country with no confirmed rate HAL
    says the premium is before tax and leaves the figure to the broker,
    rather than reasoning by analogy from a neighbour.
    """
    included_in_quoted_premium: bool = False
    note_en: str = ""
    note_el: str = ""
    # country (lower-case) -> rate, e.g. {"france": 0.14}
    confirmed_rates: dict = field(default_factory=dict)
    confirmed_rates_source: str = ""

    @property
    def needs_disclosure(self) -> bool:
        return not self.included_in_quoted_premium and bool(self.note_en)

    def rate_for(self, country: str | None) -> float | None:
        """The confirmed rate for this country of residence, or None when
        the carrier has not told us — never an inferred one."""
        if self.included_in_quoted_premium or not country:
            return None
        return self.confirmed_rates.get(" ".join(str(country).strip().lower().split()))


@dataclass(frozen=True)
class CarrierPolicy:
    """Everything HAL knows about how one carrier prices and sells."""
    carrier: str
    carrier_name: str = ""
    product_family: str = ""
    family_discount: FamilyDiscountRule = field(default_factory=FamilyDiscountRule)
    instalment: InstalmentLoading = field(default_factory=InstalmentLoading)
    issuance: PolicyIssuanceRule = field(default_factory=PolicyIssuanceRule)
    tax: PremiumTaxTreatment = field(default_factory=PremiumTaxTreatment)
    # Carrier quotes HAL reconciles against, so a rate change that breaks
    # the ladder fails loudly. See tests/test_carrier_family_discount.py.
    reconciliation_quotes: tuple = ()


# A carrier HAL holds no policy for. Deliberately empty: no discount, no
# loading, no child limits. See the module docstring.
NO_POLICY = CarrierPolicy(carrier="")

# The individual empty rules, for callers that want to say "no discount"
# explicitly — the kill switch in quote_engine, and tests.
NO_FAMILY_DISCOUNT = NO_POLICY.family_discount
NO_INSTALMENT_LOADING = NO_POLICY.instalment
NO_ISSUANCE_RULES = NO_POLICY.issuance


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _build_registry() -> dict[str, CarrierPolicy]:
    from backend.app.rates.carriers import morgan_price
    return {morgan_price.POLICY.carrier: morgan_price.POLICY}


_REGISTRY: dict[str, CarrierPolicy] | None = None


def policy_for(carrier: str) -> CarrierPolicy:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY.get((carrier or "").strip().lower(), NO_POLICY)


def registered_carriers() -> tuple[str, ...]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return tuple(sorted(_REGISTRY))


# ---------------------------------------------------------------------------
# What the rest of HAL calls
# ---------------------------------------------------------------------------

def family_discount_rule(carrier: str) -> FamilyDiscountRule:
    return policy_for(carrier).family_discount


def instalment_loading(carrier: str) -> InstalmentLoading:
    return policy_for(carrier).instalment


def policy_issuance_rule(carrier: str) -> PolicyIssuanceRule:
    return policy_for(carrier).issuance


def premium_tax_treatment(carrier: str) -> PremiumTaxTreatment:
    return policy_for(carrier).tax


def carrier_will_not_issue(carrier: str, ages: list[int]) -> bool:
    """True when this household cannot be issued as a policy at all —
    today, a lone child below the carrier's minimum age."""
    if len(ages) != 1:
        return False
    return policy_issuance_rule(carrier).blocks_single_life(ages[0])


def household_exceeds_verified_size(carrier: str, lives: int) -> bool:
    """True when this household is larger than anything reconciled against
    the carrier's own quote engine. Extrapolating a discount ladder past
    its evidence invents a premium, and a big family is where that error
    compounds hardest."""
    limit = family_discount_rule(carrier).max_verified_lives
    return limit is not None and lives > limit


__all__ = [
    "CarrierPolicy", "FamilyDiscountRule", "InstalmentLoading",
    "PolicyIssuanceRule", "PremiumTaxTreatment", "NO_POLICY",
    "policy_for", "registered_carriers", "family_discount_rule",
    "instalment_loading", "policy_issuance_rule", "premium_tax_treatment",
    "carrier_will_not_issue", "household_exceeds_verified_size", "replace",
    "NO_FAMILY_DISCOUNT", "NO_INSTALMENT_LOADING", "NO_ISSUANCE_RULES",
]
