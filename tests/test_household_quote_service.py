from datetime import date

from backend.app.services.household_quote_service import (
    apply_evidence_backed_discount,
    compose_verified_household,
    household_member_states,
    quote_to_member_option,
)
from backend.app.services.provider_intelligence_agent import ProviderCommercialRule


def _quote(member_suffix: str, premium: float = 1000, *, verified: bool = True, unmatched=None):
    return {
        "eligible": True,
        "plan_key": f"plan-{member_suffix}",
        "insurer": "Carrier A",
        "product_name": "Plan A",
        "premium": premium,
        "currency": "EUR",
        "official_rate": verified,
        "evidence_confidence": 1.0 if verified else 0.5,
        "unmatched_requirements": unmatched or [],
    }


def test_family_member_states_keep_maternity_member_specific():
    state = {
        "age": 42,
        "sex": "male",
        "maternity_required": False,
        "coverage_area": "europe",
        "outpatient_required": True,
        "household_members": [
            {"member_id": "spouse", "relationship": "spouse", "age": 35, "sex": "female", "maternity_required": True},
            {"member_id": "child-1", "relationship": "child", "age": 8, "sex": "female"},
            {"member_id": "child-2", "relationship": "child", "age": 5, "sex": "male"},
        ],
    }
    members = dict(household_member_states(state))
    assert set(members) == {"primary", "spouse", "child-1", "child-2"}
    assert members["spouse"]["maternity_required"] is True
    assert members["child-1"]["maternity_required"] is False
    assert members["child-2"]["maternity_required"] is False
    assert all(m["outpatient_required"] is True for m in members.values())


def test_household_total_requires_verified_quote_for_every_member():
    quotes = {
        "primary": [_quote("p", 1000)],
        "spouse": [_quote("s", 1200)],
        "child-1": [_quote("c1", 500)],
        "child-2": [_quote("c2", 450, verified=False)],
    }
    result = compose_verified_household(quotes)
    assert result["status"] == "personal_family_quotation_required"
    assert result["options"] == []


def test_verified_household_total_is_sum_of_all_four_members():
    quotes = {
        "primary": [_quote("p", 1000)],
        "spouse": [_quote("s", 1200)],
        "child-1": [_quote("c1", 500)],
        "child-2": [_quote("c2", 450)],
    }
    result = compose_verified_household(quotes)
    assert result["status"] == "verified_household_options"
    assert result["member_count"] == 4
    assert result["options"][0]["total_premium"] == 3150


def test_unmatched_member_requirement_blocks_that_option():
    option = quote_to_member_option("spouse", _quote("s", unmatched=["maternity"]))
    assert option is not None
    assert option.requirements_satisfied is False


def test_discount_requires_approved_active_evidence():
    option = quote_to_member_option("primary", _quote("p", 1000))
    assert option is not None
    unapproved = ProviderCommercialRule(
        rule_id="r1", provider="Carrier A", product="Plan A", rule_type="family_discount",
        percent=10, min_household_size=2, effective_from=date(2026, 1, 1),
        evidence_ref="carrier-bulletin-2026", approved=False,
    )
    unchanged, refs = apply_evidence_backed_discount(option, rules=[unapproved], household_size=4, when=date(2026, 10, 3))
    assert unchanged.premium == 1000
    assert refs == []

    approved = unapproved.model_copy(update={"approved": True})
    discounted, refs = apply_evidence_backed_discount(option, rules=[approved], household_size=4, when=date(2026, 10, 3))
    assert discounted.premium == 900
    assert refs == ["carrier-bulletin-2026"]
