"""Per-carrier commercial pricing rules (family discounts, instalment
loading, tax treatment).

WHY THIS IS PER CARRIER AND NOT A GLOBAL SETTING
------------------------------------------------
A family discount is an insurer's own commercial policy, not a property of
international health insurance. Morgan Price gives 5% for two lives rising
to 15% for four; APRIL, IMG, Bupa Global, Allianz Care, Cigna and Now
Health each set their own, and some give none at all. Before 15 Oct 2026
HAL carried a single global `family_discount_pct` in Settings, which meant
that the moment a second carrier's workbook was loaded, that carrier's
families would silently be quoted on Morgan Price's commercial terms.

So: rules live beside the carrier's own evidence, in
`data/evidence/<carrier>_<year>/pricing_rules.json`, and a carrier with no
file gets NO discount and NO instalment loading. Quoting a discount an
insurer has not confirmed is inventing a price, which HAL does not do.
Over-quoting is recoverable — a broker corrects it downward and the client
is pleasantly surprised. Under-quoting means the client meets a higher
number at proposal stage, which is the exact failure HAL exists to prevent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "data" / "evidence"

# Which evidence folder holds each carrier's rules. Add a row when a new
# carrier's workbook and pricing rules are loaded.
_CARRIER_EVIDENCE_DIRS = {
    "morgan_price": "morgan_price_2026",
}


@dataclass(frozen=True)
class FamilyDiscountRule:
    """One carrier's family discount ladder.

    discount_pct = step_pct * min(lives - 1, max_steps), applied to the
    `max_discounted_members` highest-premium lives only, and only when the
    policy carries at least `min_adults` adults.
    """
    step_pct: float = 0.0
    max_steps: int = 0
    max_discounted_members: int = 0
    # Morgan Price: "Eligibility - minimum of 2 adults per policy"
    # (EU/EVO/SI/PW/04/26 page 10). A single adult with children gets no
    # family discount at all, whatever the household size.
    min_adults: int = 0
    adult_from_age: int = 19
    # Largest household actually checked against the carrier's own quote
    # engine. Above this HAL has no evidence and must not extrapolate.
    max_verified_lives: int | None = None

    @property
    def gives_discount(self) -> bool:
        return self.step_pct > 0 and self.max_steps > 0

    def adults_in(self, ages: list[int] | None) -> int:
        """How many lives count as adults. With no ages supplied we cannot
        tell, so we assume the eligibility condition is met rather than
        silently stripping a discount the client is entitled to."""
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
class PolicyIssuanceRule:
    """Who a carrier will issue a policy to, independent of price.

    Morgan Price covers children 10-17 on a policy of their own, with a
    compulsory per-claim excess; a child under 10 must have an adult on the
    policy. HAL must not quote a policy the insurer would refuse to issue:
    the client applies, is declined, and the quote was worthless.
    """
    child_only_min_age: int | None = None
    child_only_max_age: int | None = None
    child_only_excess_per_claim: dict | None = None
    under_min_age_requires_an_adult: bool = False

    @property
    def has_child_rules(self) -> bool:
        return self.child_only_min_age is not None

    def blocks_single_life(self, age: int) -> bool:
        """True when this carrier will not issue a policy covering this one
        life on its own."""
        if not self.has_child_rules or not self.under_min_age_requires_an_adult:
            return False
        return age < self.child_only_min_age

    def is_child_only_policy(self, ages: list[int]) -> bool:
        if not self.has_child_rules or len(ages) != 1:
            return False
        return self.child_only_min_age <= ages[0] <= (self.child_only_max_age or 17)

    def compulsory_excess(self, currency: str) -> float:
        fees = self.child_only_excess_per_claim or {}
        return float(fees.get((currency or "EUR").upper(), 0) or 0)


NO_ISSUANCE_RULES = PolicyIssuanceRule()


@dataclass(frozen=True)
class InstalmentLoading:
    """Administration fee the carrier adds for paying in instalments."""
    monthly_pct: float = 0.0
    quarterly_pct: float = 0.0
    semi_annual_pct: float = 0.0
    annual_pct: float = 0.0
    annual_bank_transfer_fee: dict | None = None

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
        fees = self.annual_bank_transfer_fee or {}
        return float(fees.get((currency or "EUR").upper(), 0) or 0)


# A carrier we hold no pricing rules for: no discount, no loading. This is
# the deliberate conservative default — see the module docstring.
NO_FAMILY_DISCOUNT = FamilyDiscountRule()
NO_INSTALMENT_LOADING = InstalmentLoading()


@lru_cache
def _rules_for(carrier: str) -> dict:
    folder = _CARRIER_EVIDENCE_DIRS.get((carrier or "").strip().lower())
    if not folder:
        return {}
    path = EVIDENCE_DIR / folder / "carrier_rules.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # A malformed rules file must not silently become "some other
        # carrier's discount" — it becomes no discount.
        return {}


@lru_cache
def family_discount_rule(carrier: str) -> FamilyDiscountRule:
    block = (_rules_for(carrier) or {}).get("family_discount") or {}
    if not block:
        return NO_FAMILY_DISCOUNT
    return FamilyDiscountRule(
        step_pct=float(block.get("step_pct", 0.0) or 0.0),
        max_steps=int(block.get("max_steps", 0) or 0),
        max_discounted_members=int(block.get("max_discounted_members", 0) or 0),
        min_adults=int(block.get("min_adults", 0) or 0),
        adult_from_age=int(block.get("adult_from_age", 19) or 19),
        max_verified_lives=(int(block["max_verified_lives"])
                            if block.get("max_verified_lives") is not None else None),
    )


@lru_cache
def instalment_loading(carrier: str) -> InstalmentLoading:
    block = (_rules_for(carrier) or {}).get("instalment_loading") or {}
    if not block:
        return NO_INSTALMENT_LOADING
    return InstalmentLoading(
        monthly_pct=float(block.get("monthly_pct", 0.0) or 0.0),
        quarterly_pct=float(block.get("quarterly_pct", 0.0) or 0.0),
        semi_annual_pct=float(block.get("semi_annual_pct", 0.0) or 0.0),
        annual_pct=float(block.get("annual_pct", 0.0) or 0.0),
        annual_bank_transfer_fee=block.get("annual_bank_transfer_fee") or {},
    )


@lru_cache
def policy_issuance_rule(carrier: str) -> PolicyIssuanceRule:
    block = (_rules_for(carrier) or {}).get("policy_issuance") or {}
    if not block:
        return NO_ISSUANCE_RULES
    return PolicyIssuanceRule(
        child_only_min_age=(int(block["child_only_min_age"])
                            if block.get("child_only_min_age") is not None else None),
        child_only_max_age=(int(block["child_only_max_age"])
                            if block.get("child_only_max_age") is not None else None),
        child_only_excess_per_claim=block.get("child_only_compulsory_excess_per_claim") or {},
        under_min_age_requires_an_adult=bool(
            block.get("under_min_age_requires_an_adult_on_the_policy", False)
        ),
    )


def carrier_will_not_issue(carrier: str, ages: list[int]) -> bool:
    """True when this household cannot be issued as a policy by this carrier.

    Today that means a lone child below the carrier's child-only minimum
    age: the wording requires an adult on the policy, so a quote for that
    child alone would be declined at application."""
    if len(ages) != 1:
        return False
    return policy_issuance_rule(carrier).blocks_single_life(ages[0])


def household_exceeds_verified_size(carrier: str, lives: int) -> bool:
    """True when this household is larger than anything we have actually
    checked against the carrier's own quote engine. The quote engine must
    not price these online — extrapolating a discount ladder past its
    evidence is exactly the kind of invented number HAL forbids."""
    rule = family_discount_rule(carrier)
    if rule.max_verified_lives is None:
        return False
    return lives > rule.max_verified_lives
