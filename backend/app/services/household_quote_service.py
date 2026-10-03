from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from backend.app.services.household_portfolio_agent import MemberPlanOption, compose_household_payload, optimise_household
from backend.app.services.provider_intelligence_agent import ProviderCommercialRule, applicable_rules


INHERITED_REQUIREMENTS = (
    "outpatient_required", "dental_required", "mental_health_required", "wellness_required",
    "optical_required", "evacuation_required", "chronic_required", "private_hospital_choice_required",
    "cross_border_treatment_required", "home_country_treatment_required", "continuity_portability_required",
    "high_annual_limit_required", "private_room_required", "direct_billing_required",
    "second_medical_opinion_required",
)


def household_member_states(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Build deterministic per-member quote states without inferring personal facts.

    The primary applicant is always included. Family members inherit household-level
    coverage preferences, but maternity is always member-specific and is never
    inherited from another person.
    """
    primary = deepcopy(state)
    primary["maternity_required"] = bool(state.get("maternity_required"))
    members: list[tuple[str, dict[str, Any]]] = [("primary", primary)]

    for raw in state.get("household_members") or []:
        if not isinstance(raw, dict) or raw.get("age") is None or not raw.get("member_id"):
            continue
        member = deepcopy(state)
        member["age"] = int(raw["age"])
        member["sex"] = raw.get("sex", "unspecified")
        member["maternity_required"] = bool(raw.get("maternity_required", False))
        member["household_members"] = []
        member["family_requested"] = False
        for key in INHERITED_REQUIREMENTS:
            if key in raw:
                member[key] = raw[key]
        members.append((str(raw["member_id"]), member))
    return members


def quote_to_member_option(member_id: str, quote: dict[str, Any]) -> MemberPlanOption | None:
    """Convert only evidence-backed, eligible quote output into a household option."""
    if not quote.get("eligible", True):
        return None
    premium = quote.get("premium")
    if premium is None or not quote.get("plan_key"):
        return None
    # A household total must never be built from a legacy/unverified price.
    verified = bool(quote.get("official_rate")) and float(quote.get("evidence_confidence") or 0) >= 1.0
    requirements_satisfied = not bool(quote.get("unmatched_requirements"))
    return MemberPlanOption(
        member_id=member_id,
        plan_key=str(quote["plan_key"]),
        insurer=str(quote.get("insurer") or ""),
        product_name=str(quote.get("product_name") or ""),
        premium=float(premium),
        currency=str(quote.get("currency") or "EUR"),
        requirements_satisfied=requirements_satisfied,
        verified=verified,
    )


def apply_evidence_backed_discount(
    option: MemberPlanOption,
    *,
    rules: list[ProviderCommercialRule],
    household_size: int,
    when: date | None = None,
) -> tuple[MemberPlanOption, list[str]]:
    """Apply at most one explicitly approved/evidenced percentage or fixed rule.

    No rule means no discount. Evidence references are returned for audit/UI use.
    """
    matched = applicable_rules(
        rules,
        provider=option.insurer,
        product=option.product_name,
        household_size=household_size,
        when=when,
    )
    if not matched:
        return option, []
    # Avoid stacking commercial rules unless a future carrier rule explicitly
    # models stacking. Deterministically use the first approved rule supplied.
    rule = matched[0]
    premium = option.premium
    if rule.percent is not None:
        premium = premium * (1 - rule.percent / 100)
    elif rule.fixed_amount is not None and (not rule.currency or rule.currency == option.currency):
        premium = max(0.0, premium - rule.fixed_amount)
    else:
        return option, []
    return option.model_copy(update={"premium": round(premium, 2)}), [rule.evidence_ref]


def compose_verified_household(
    quotes_by_member: dict[str, list[dict[str, Any]]],
    *,
    commercial_rules: list[ProviderCommercialRule] | None = None,
) -> dict[str, Any]:
    """Create a household total only when every member has a verified option."""
    options_by_member: dict[str, list[MemberPlanOption]] = {}
    evidence_refs: set[str] = set()
    household_size = len(quotes_by_member)
    for member_id, quotes in quotes_by_member.items():
        options: list[MemberPlanOption] = []
        for quote in quotes:
            option = quote_to_member_option(member_id, quote)
            if option is None:
                continue
            if commercial_rules:
                option, refs = apply_evidence_backed_discount(
                    option, rules=commercial_rules, household_size=household_size
                )
                evidence_refs.update(refs)
            options.append(option)
        options_by_member[member_id] = options

    payload = compose_household_payload(optimise_household(options_by_member))
    payload["member_count"] = household_size
    payload["commercial_rule_evidence"] = sorted(evidence_refs)
    payload["discounts_applied"] = bool(evidence_refs)
    return payload
