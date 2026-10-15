from __future__ import annotations
from datetime import date

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant
from backend.app.schemas.quote import QuoteResult
from backend.app.rates.registry import load_rates, load_card_meta, RateRecord
from backend.app.rates.deductible_model import apply_deductible
from backend.app.rates.family_pricing import price_family
from backend.app.rates.carriers import (
    family_discount_rule, household_exceeds_verified_size, carrier_will_not_issue,
    policy_issuance_rule, policy_for as carrier_policy, NO_FAMILY_DISCOUNT,
)
from backend.app.matching.engine import evaluate_requirements, benefit_checklist
from backend.app.evidence.eligibility_rules import evaluate_plan_eligibility
from backend.app.evidence.morgan_price_2026 import verified_fact_texts, load_manifest, plan_documents

from backend.app.rates.residence import area_includes, residence_status


def residence_gate(applicant: Applicant) -> str | None:
    """Why HAL cannot price this applicant online, or None if it can."""
    status = residence_status(applicant.residence_country)
    if status != "priced":
        return status
    if not area_includes(applicant.coverage_area, applicant.residence_country):
        return "area_excludes_residence"
    return None


# As of 13 Oct 2026 only Morgan Price has an official 2026 workbook loaded in
# registry.py. The old per-carrier residence gate (APRIL/IMG limited to
# Greek residents) was removed with the legacy workbook — see registry.py.


def _card_meta(carrier: str, product_code: str) -> dict:
    return load_card_meta().get(carrier, {}).get(product_code, {})


def _rows_for(carrier: str, product_code: str, area: str) -> list[RateRecord]:
    return [r for r in load_rates() if r.carrier == carrier and r.product_code == product_code and r.area == area]


def _distinct_products(area: str) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for r in load_rates():
        if r.area != area:
            continue
        key = (r.carrier, r.product_code)
        if key not in seen:
            seen.append(key)
    return seen


def _enrich_card_meta(q: QuoteResult) -> None:
    carrier = (q.plan_key or "").split(":")[0]
    meta = _card_meta(carrier, q.product_code)
    q.benefit_checklist = benefit_checklist(carrier, q.product_code)
    q.card_badge = meta.get("badge") or (q.insurer.split()[0][:3].upper() if q.insurer else "PLAN")
    q.card_coverage = meta.get("coverage") or "International medical cover"
    q.card_annual_limit = meta.get("annual_limit") or "See plan schedule"
    q.card_deductible = meta.get("deductible") or "See selected option"
    q.card_evacuation = meta.get("evacuation") or "Subject to plan terms"
    # Deductible preference recorded but not priced in — be honest about it
    # on the card so the user doesn't think their choice changed the number.
    # The deductible_model_enabled flag defaults False (no carrier-confirmed
    # tiered rates yet), so we must say the preference is saved for the
    # broker rather than silently ignoring it.
    if q.deductible is not None and q.deductible_note == "deductible_preference_not_used_in_pricing":
        q.card_deductible_note = (
            f"Your €{int(q.deductible):,} deductible preference is recorded for the broker. "
            "The price above is the undiscounted indicative rate — the final figure is set with the insurer at proposal stage."
        )
    q.must_have_checks = list(q.matched_requirements) if q.evidence_confidence == 1.0 else []

    if q.evidence_confidence == 1.0 and q.matched_requirements:
        q.card_why = "Matches your priorities: " + ", ".join(q.matched_requirements[:3]) + "."
    elif q.evidence_confidence < 1.0:
        q.card_why = meta.get("why") or "Alternative provider option."
        q.client_note = "Current benefits should be confirmed before proposal."
    else:
        q.card_why = meta.get("why") or "International health insurance option."


def quote_current(applicant: Applicant, settings: Settings, *, today: date | None = None,
                  standalone_policy: bool = True) -> list[QuoteResult]:
    """Every eligible product for this applicant (family-aware), hard-filtered
    on any selected MUST-HAVE, never merely down-scored.

    `standalone_policy` says whether this applicant would be the only life on
    the policy. The household flows price each member on their own to build a
    per-member breakdown, which is an internal step and NOT a standalone
    policy — a three-year-old priced that way still ends up on a policy with
    a parent. Those callers pass False so the child-only issuance rule does
    not reject a member who is in fact accompanied by an adult."""
    if residence_gate(applicant):
        return []

    today = today or date.today()
    ages = applicant.all_ages()
    quotes: list[QuoteResult] = []

    for carrier, product_code in _distinct_products(applicant.coverage_area):
        rows = _rows_for(carrier, product_code, applicant.coverage_area)
        if not rows:
            continue

        # Area 2/3/4: only Morgan Price has a verified 2026 geographic
        # definition for these areas in our evidence set. (Harmless with the
        # 13 Oct 2026 workbook, which already is Morgan-Price-only, but kept
        # so adding a Europe-only carrier later does not accidentally price
        # worldwide requests.)
        if applicant.coverage_area in {"area2", "area3", "area4"} and carrier != "morgan_price":
            continue

        # Every family member must individually match an age band on this
        # product, otherwise we don't offer it as a family option at all.
        member_rows: list[RateRecord | None] = []
        for age in ages:
            match = next((r for r in rows if r.age_min <= age <= r.age_max), None)
            member_rows.append(match)
        if any(m is None for m in member_rows):
            continue

        # Households larger than anything we have checked against this
        # carrier's own quote engine are not priced online. Extrapolating a
        # discount ladder past its evidence would invent a premium, and a
        # large family is exactly the case where the error compounds.
        if household_exceeds_verified_size(carrier, len(ages)):
            continue

        # A policy the insurer would refuse to issue is worth nothing to the
        # client. Morgan Price requires an adult on the policy for any child
        # under 10 (EU/EVO/SI/PW/04/26 p.5), so a lone young child is not
        # quotable however well the rate table matches their age.
        if standalone_policy and carrier_will_not_issue(carrier, ages):
            continue

        eligibility = evaluate_plan_eligibility(applicant, carrier, product_code)
        if eligibility.status != "eligible":
            # An active rule that is unresolved is not safe to display as an
            # eligible option. The Eligibility Agent can ask for the missing
            # information; the quote engine never guesses.
            continue

        outcome = evaluate_requirements(applicant, carrier, product_code)
        if not outcome.eligible:
            continue  # HARD exclusion — never shown, never scored

        official = member_rows[0].official  # type: ignore[union-attr]
        base_each = [m.annual_premium for m in member_rows]  # type: ignore[union-attr]

        # Deductible adjustment applies per member, then family pricing sums.
        adjusted_each = []
        deductible_note = "deductible_preference_not_used_in_pricing"
        for base in base_each:
            adj, note = apply_deductible(
                base, applicant.deductible, applicant.deductible_preference,
                enabled=settings.deductible_model_enabled,
            )
            adjusted_each.append(adj)
            deductible_note = note

        # The family discount is THIS carrier's commercial policy, read from
        # its own evidence folder. A carrier with no recorded rule gets none.
        discount_rule = (family_discount_rule(carrier)
                         if settings.apply_carrier_family_discounts else NO_FAMILY_DISCOUNT)
        family_quote = price_family(adjusted_each, rule=discount_rule, member_ages=ages)

        # Every quote in flight today is Morgan Price official (the only loaded
        # workbook). The old "legacy" branch is unreachable and was removed on
        # 13 Oct 2026 together with the APRIL/IMG rate loader.
        warnings = [
            "Official Morgan Price Europe 2026 rate from the supplied workbook.",
            "Final premium and acceptance remain subject to insurer eligibility, underwriting and confirmation.",
        ]
        if applicant.chronic_conditions_disclosed:
            warnings.append("A pre-existing condition was disclosed — this quote does not reflect any underwriting decision and must be reviewed by a broker before proceeding.")
        facts = verified_fact_texts(product_code)
        docs = [d["official_url"] for d in load_manifest()["documents"] if d["document_type"] in {"policy_wording", "table_of_benefits"}]
        evidence_status = "verified_2026_tob_and_policy"
        card_docs = plan_documents(product_code)

        reasons = []
        if outcome.matched:
            reasons.append("Verified match: " + ", ".join(outcome.matched))
        if outcome.unmatched:
            reasons.append("Verified gap: " + ", ".join(outcome.unmatched))

        carrier_name = member_rows[0].carrier_name  # type: ignore[union-attr]
        area_label = member_rows[0].area_label  # type: ignore[union-attr]
        rate_version = member_rows[0].rate_version  # type: ignore[union-attr]

        quotes.append(QuoteResult(
            insurer=carrier_name, product_code=product_code, product_name=member_rows[0].product_name,  # type: ignore[union-attr]
            plan_key=f"{carrier}:{product_code}",
            eligible=True,
            base_premium=base_each[0],
            premium=family_quote.total,
            currency=applicant.currency,
            rate_version=rate_version,
            deductible=applicant.deductible,
            deductible_note=deductible_note,
            family_size=applicant.family_size(),
            per_member_premiums=family_quote.per_member_premiums,
            family_discount_applied=family_quote.discount_applied,
            family_discount_pct=family_quote.discount_pct,
            family_discounted_member_count=family_quote.discounted_member_count,
            coverage_area_label=area_label,
            official_rate=official,
            evidence_status=evidence_status,
            evidence_confidence=outcome.evidence_confidence,
            requirements_score=outcome.requirements_score,
            matched_requirements=outcome.matched,
            unmatched_requirements=outcome.unmatched,
            verified_facts=facts,
            source_documents=docs,
            plan_documents=card_docs,
            reasons=reasons,
            warnings=warnings,
            quoted_on=today,
            valid_until=QuoteResult.validity_window(today, settings.quote_validity_days),
        ))
        _enrich_card_meta(quotes[-1])

        # What the client actually pays on each payment frequency, with the
        # carrier's instalment administration fee included. Paying monthly
        # is not the annual price in twelve pieces.
        policy = carrier_policy(carrier)
        quotes[-1].payment_options = policy.instalment.schedule(
            quotes[-1].premium, applicant.currency
        )
        if policy.tax.needs_disclosure:
            quotes[-1].premium_tax_note = policy.tax.note_en

        # A child insured without a parent or guardian on the policy carries a
        # compulsory per-claim excess. It is a term of the cover, not an
        # option the client chose, so it belongs on the card rather than
        # surfacing for the first time on the certificate.
        issuance = policy_issuance_rule(carrier)
        if standalone_policy and issuance.is_child_only_policy(ages):
            excess = issuance.compulsory_excess(applicant.currency)
            if excess:
                q = quotes[-1]
                q.child_only_policy = True
                q.compulsory_excess_per_claim = excess
                q.card_deductible = f"{applicant.currency} {excess:,.0f} per claim (compulsory)"

    def rank(q: QuoteResult):
        over_budget = bool(applicant.budget_annual and q.premium > applicant.budget_annual)
        # evidence_confidence is 1.0 whenever there's nothing to verify (no
        # must-haves selected) OR the plan is a verified Morgan Price match;
        # it drops to 0.0 only when must-haves WERE selected but this
        # carrier has no benefit-level evidence to confirm it meets them.
        # A plan we could not verify must never outrank a verified match on
        # price alone — being cheap is not the same as being confirmed to fit.
        unverified_against_stated_musts = q.evidence_confidence < 1.0
        gap = abs(q.premium - (applicant.budget_annual or q.premium))
        return (over_budget, unverified_against_stated_musts, gap, q.premium)

    quotes.sort(key=rank)
    return quotes


def quote_shortlist(applicant: Applicant, settings: Settings, *, limit: int = 5, today: date | None = None,
                    standalone_policy: bool = True) -> list[QuoteResult]:
    candidates = quote_current(applicant, settings, today=today, standalone_policy=standalone_policy)
    shortlist: list[QuoteResult] = []
    seen_carriers: set[str] = set()

    for q in candidates:
        key = (q.plan_key or "").split(":")[0]
        if key in seen_carriers:
            continue
        shortlist.append(q)
        seen_carriers.add(key)
        if len(shortlist) >= min(3, limit):
            break

    for q in candidates:
        if q in shortlist:
            continue
        shortlist.append(q)
        if len(shortlist) >= limit:
            break

    # "Recommended" is a signal we only earn when the user has told HAL what
    # matters. Without any must-have and without a budget, the engine's rank
    # devolves to "cheapest eligible" — labelling that as "Recommended" would
    # be a false signal (plain price != plain fit) and misaligns with HAL
    # fairness rule 2 (every recommendation reviewed by a broker). When the
    # user has stated priorities, the top of a verified ranking IS a real
    # recommendation and we mark it.
    meaningful_recommendation = bool(applicant.must_have_keys()) or applicant.budget_annual is not None

    lowest = min((q.premium for q in shortlist), default=None)
    for i, q in enumerate(shortlist):
        q.recommended = (i == 0 and meaningful_recommendation)
        q.recommendation_rank = i + 1
        # "Best value" highlights the cheapest plan — but only when it is NOT
        # the one already carrying the Recommended ribbon, so the two badges
        # don't tautologically label the same card.
        is_cheapest = lowest is not None and q.premium == lowest
        if is_cheapest and not q.recommended and "Best value" not in q.fit_badges:
            q.fit_badges = (q.fit_badges + ["Best value"])[:3]

    return shortlist


def quote_exclusions(applicant: Applicant, settings: Settings, *, today: date | None = None) -> list[dict]:
    """Client-safe explanation of verified plans hard-excluded by MUST-HAVEs."""
    if residence_gate(applicant):
        return []
    out = []
    for carrier, product_code in _distinct_products(applicant.coverage_area):
        rows = _rows_for(carrier, product_code, applicant.coverage_area)
        if not rows:
            continue

        eligibility = evaluate_plan_eligibility(applicant, carrier, product_code)
        if eligibility.status != "eligible":
            out.append({
                "plan_key": f"{carrier}:{product_code}",
                "insurer": rows[0].carrier_name,
                "product_name": rows[0].product_name,
                "gaps": ["Eligibility criteria"],
                "eligibility_status": eligibility.status,
                "eligibility_reason": eligibility.reason,
            })
            continue

        outcome = evaluate_requirements(applicant, carrier, product_code)
        if outcome.eligible or outcome.evidence_confidence != 1.0:
            continue
        out.append({
            "plan_key": f"{carrier}:{product_code}",
            "insurer": rows[0].carrier_name,
            "product_name": rows[0].product_name,
            "gaps": outcome.unmatched,
        })
    return out


