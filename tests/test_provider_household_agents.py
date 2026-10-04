from datetime import date

from backend.app.services.provider_intelligence_agent import ProviderCommercialRule, applicable_rules
from backend.app.services.household_portfolio_agent import MemberPlanOption, optimise_household, compose_household_payload


def test_provider_rules_require_approval_evidence_and_validity():
    approved = ProviderCommercialRule(
        rule_id="mp-family-2026", provider="Morgan Price", product=None,
        rule_type="family_discount", percent=10, min_household_size=2,
        effective_from=date(2026, 1, 1), expires_on=date(2026, 12, 31),
        evidence_ref="official-2026-rate-workbook", approved=True,
    )
    pending = approved.model_copy(update={"rule_id": "pending", "approved": False})
    expired = approved.model_copy(update={"rule_id": "expired", "expires_on": date(2025, 12, 31)})
    found = applicable_rules([approved, pending, expired], provider="Morgan Price", product="Standard Plus", household_size=2, when=date(2026, 10, 3))
    assert [r.rule_id for r in found] == ["mp-family-2026"]


def _opt(member, plan, insurer, premium, *, ok=True):
    return MemberPlanOption(member_id=member, plan_key=plan, insurer=insurer, product_name=plan, premium=premium, currency="EUR", requirements_satisfied=ok, verified=True)


def test_household_optimiser_can_split_maternity_member_without_inventing_price():
    options = {
        "father": [_opt("father", "fit", "A", 2000), _opt("father", "maternity", "B", 3200)],
        "spouse": [_opt("spouse", "fit", "A", 2100, ok=False), _opt("spouse", "maternity", "B", 3200)],
        "child": [_opt("child", "fit", "A", 900), _opt("child", "maternity", "B", 1500)],
    }
    portfolios = optimise_household(options)
    assert portfolios[0].total_premium == 6100
    assert {a.plan_key for a in portfolios[0].allocations} == {"fit", "maternity"}
    payload = compose_household_payload(portfolios)
    assert payload["status"] == "verified_household_options"


def test_household_without_verified_member_quote_requires_personal_quote():
    options = {
        "primary": [_opt("primary", "standard-plus", "Morgan Price", 2694.72)],
        "spouse": [],
    }
    assert compose_household_payload(optimise_household(options))["status"] == "personal_family_quotation_required"
