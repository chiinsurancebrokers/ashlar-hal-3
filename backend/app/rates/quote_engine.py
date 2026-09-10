from __future__ import annotations
from datetime import date

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant
from backend.app.schemas.quote import QuoteResult
from backend.app.rates.registry import load_rates, load_card_meta, RateRecord
from backend.app.rates.deductible_model import apply_deductible
from backend.app.rates.family_pricing import price_family
from backend.app.matching.engine import evaluate_requirements
from backend.app.evidence.morgan_price_2026 import verified_fact_texts, load_manifest

SUPPORTED_RESIDENCE = {"greece", "gr", "hellas", "ελλάδα", "ellada"}


def _carrier_key(carrier: str) -> str:
    return carrier


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


def quote_current(applicant: Applicant, settings: Settings, *, today: date | None = None) -> list[QuoteResult]:
    """Every eligible product for this applicant (family-aware), hard-filtered
    on any selected MUST-HAVE, never merely down-scored."""
    residence = applicant.residence_country.strip().lower()
    if residence not in SUPPORTED_RESIDENCE:
        return []

    today = today or date.today()
    ages = applicant.all_ages()
    quotes: list[QuoteResult] = []

    for carrier, product_code in _distinct_products(applicant.coverage_area):
        rows = _rows_for(carrier, product_code, applicant.coverage_area)
        if not rows:
            continue

        # Area 2/3/4: only Morgan Price has a verified 2026 geographic
        # definition for these areas in our evidence set.
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

        family_quote = price_family(adjusted_each, family_discount_pct=settings.family_discount_pct)

        if official:
            warnings = [
                "Official Morgan Price Europe 2026 rate from the supplied workbook.",
                "Final premium and acceptance remain subject to insurer eligibility, underwriting and confirmation.",
            ]
            if applicant.chronic_conditions_disclosed:
                warnings.append("A pre-existing condition was disclosed — this quote does not reflect any underwriting decision and must be reviewed by a broker before proceeding.")
            facts = verified_fact_texts(product_code)
            docs = [d["official_url"] for d in load_manifest()["documents"] if d["document_type"] in {"policy_wording", "table_of_benefits"}]
            evidence_status = "verified_2026_tob_and_policy"
        else:
            warnings = [
                "Indicative quotation using a legacy rate dataset for this carrier.",
                "Benefit matching is not scored until this carrier's current official documents are loaded.",
            ]
            facts, docs = [], []
            evidence_status = "legacy_unverified_benefits"

        reasons = []
        if outcome.matched:
            reasons.append("Verified match: " + ", ".join(outcome.matched))
        if outcome.unmatched:
            reasons.append("Verified gap: " + ", ".join(outcome.unmatched))

        carrier_name = member_rows[0].carrier_name  # type: ignore[union-attr]
        area_label = member_rows[0].area_label if official else f"{applicant.coverage_area} (legacy definition)"  # type: ignore[union-attr]
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
            coverage_area_label=area_label,
            official_rate=official,
            evidence_status=evidence_status,
            evidence_confidence=outcome.evidence_confidence,
            requirements_score=outcome.requirements_score,
            matched_requirements=outcome.matched,
            unmatched_requirements=outcome.unmatched,
            verified_facts=facts,
            source_documents=docs,
            reasons=reasons,
            warnings=warnings,
            quoted_on=today,
            valid_until=QuoteResult.validity_window(today, settings.quote_validity_days),
        ))

    def rank(q: QuoteResult):
        over_budget = bool(applicant.budget_annual and q.premium > applicant.budget_annual)
        gap = abs(q.premium - (applicant.budget_annual or q.premium))
        return (over_budget, gap, q.premium)

    quotes.sort(key=rank)
    return quotes


def quote_shortlist(applicant: Applicant, settings: Settings, *, limit: int = 5, today: date | None = None) -> list[QuoteResult]:
    candidates = quote_current(applicant, settings, today=today)
    shortlist: list[QuoteResult] = []
    seen_carriers: set[str] = set()

    for q in candidates:
        meta = _card_meta(_carrier_key_from_insurer(q.insurer), q.product_code)
        q.card_badge = meta.get("badge") or (q.insurer.split()[0][:3].upper() if q.insurer else "PLAN")
        q.card_coverage = meta.get("coverage") or "International medical cover"
        q.card_annual_limit = meta.get("annual_limit") or "See plan schedule"
        q.card_deductible = meta.get("deductible") or "See selected option"
        q.card_evacuation = meta.get("evacuation") or "Subject to plan terms"
        q.plan_key = f"{_carrier_key_from_insurer(q.insurer)}:{q.product_code}"
        q.must_have_checks = list(q.matched_requirements) if q.evidence_confidence == 1.0 else []

        if q.evidence_confidence == 1.0 and q.matched_requirements:
            q.card_why = "Matches your priorities: " + ", ".join(q.matched_requirements[:3]) + "."
        elif q.evidence_confidence < 1.0:
            q.card_why = meta.get("why") or "Alternative provider option."
            q.client_note = "Current benefits should be confirmed before proposal."
        else:
            q.card_why = meta.get("why") or "International health insurance option."

        key = _carrier_key_from_insurer(q.insurer)
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

    lowest = min((q.premium for q in shortlist), default=None)
    for i, q in enumerate(shortlist):
        q.recommended = (i == 0)
        q.recommendation_rank = i + 1
        if lowest is not None and q.premium == lowest and "Best value" not in q.fit_badges:
            q.fit_badges = (q.fit_badges + ["Best value"])[:3]

    return shortlist


def quote_exclusions(applicant: Applicant, settings: Settings, *, today: date | None = None) -> list[dict]:
    """Client-safe explanation of verified plans hard-excluded by MUST-HAVEs."""
    residence = applicant.residence_country.strip().lower()
    if residence not in SUPPORTED_RESIDENCE:
        return []
    out = []
    for carrier, product_code in _distinct_products(applicant.coverage_area):
        outcome = evaluate_requirements(applicant, carrier, product_code)
        if outcome.eligible or outcome.evidence_confidence != 1.0:
            continue
        rows = _rows_for(carrier, product_code, applicant.coverage_area)
        if not rows:
            continue
        out.append({
            "plan_key": f"{carrier}:{product_code}",
            "insurer": rows[0].carrier_name,
            "product_name": rows[0].product_name,
            "gaps": outcome.unmatched,
        })
    return out


def _carrier_key_from_insurer(insurer: str) -> str:
    if "Morgan Price" in insurer:
        return "morgan_price"
    if "APRIL" in insurer:
        return "april"
    if "IMG" in insurer:
        return "img"
    return insurer.lower().replace(" ", "_")[:40]
