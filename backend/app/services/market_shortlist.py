from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.evidence.catalogue import verified_plan_catalogue
from backend.app.evidence.catalogue_plan import catalogue_plan
from backend.app.rates.quote_engine import quote_current, quote_exclusions
from backend.app.schemas.applicant import Applicant

PUBLIC_CATALOGUE_PLAN_KEYS = (
    'img:gpmi_bronze_plus', 'img:gpmi_silver', 'img:gpmi_gold', 'img:gpmi_platinum',
    'cigna:inspire_essential_care', 'cigna:inspire_executive_care', 'cigna:inspire_elite_care',
)


def matched_catalogue_plan(row: dict, applicant: Applicant):
    plan = catalogue_plan(row)
    checks = {item['field']: item for item in plan.benefit_checklist}
    for field in applicant.must_have_keys():
        item = checks[field]
        if item['covered'] is False:
            plan.unmatched_requirements.append(item['label'])
        elif item['covered'] is True:
            plan.matched_requirements.append(item['label'])
        else:
            plan.unconfirmed_requirements.append(item['label'])
    # Service preferences have no structured eligibility evidence yet. Do not
    # count them as matches, or treat disclosure as an exclusion.
    for field in Applicant.model_fields:
        if field.endswith('_required') and field not in checks and getattr(applicant, field):
            plan.unconfirmed_requirements.append(field.removesuffix('_required').replace('_', ' '))
    plan.eligibility_status = 'requires_carrier_confirmation'
    plan.eligibility_checks = ['Age, residence, nationality and chosen geographic area require carrier confirmation.']
    if row['carrier'] == 'cigna':
        plan.eligibility_checks.append('Inspire is an employer/group product. Group eligibility and local-national acceptance require confirmation.')
    if applicant.chronic_conditions_disclosed:
        plan.eligibility_checks.append('Existing conditions require an individual underwriting decision; brochure cover is not acceptance.')
    if applicant.budget_annual:
        plan.eligibility_checks.append('Budget fit cannot be checked until the personal quotation is received.')
    if applicant.deductible_preference == 'fixed':
        plan.eligibility_checks.append('The requested deductible needs confirmation in the personal quotation.')
    plan.match_status = 'not_suitable' if plan.unmatched_requirements else 'conditional_match' if plan.unconfirmed_requirements else 'benefits_match'
    plan.card_why = ('Verified needs: ' + ', '.join(plan.matched_requirements) + '. ' if plan.matched_requirements else '') + ('Confirm: ' + ', '.join(plan.unconfirmed_requirements) + '. ' if plan.unconfirmed_requirements else '') + 'Acceptance and price require a personal quotation.'
    return plan


def _catalogue_candidates(applicant):
    rows = {r['plan_key']: r for r in verified_plan_catalogue()}
    return [matched_catalogue_plan(rows[key], applicant) for key in PUBLIC_CATALOGUE_PLAN_KEYS if key in rows]


def public_market_shortlist(applicant: Applicant, settings: Settings) -> list:
    priced = [q for q in quote_current(applicant, settings) if q.official_rate]
    # Preserve the engine's needs/budget ordering. No price-only winner across
    # a market that also contains unpriced plans.
    for q in priced:
        q.recommended = False
        q.fit_badges = [b for b in q.fit_badges if b != 'Best value']
    catalogue = [p for p in _catalogue_candidates(applicant) if not p.unmatched_requirements]
    catalogue.sort(key=lambda p: (len(p.unconfirmed_requirements), -len(p.matched_requirements), PUBLIC_CATALOGUE_PLAN_KEYS.index(p.plan_key)))
    options = [*priced, *catalogue]
    options.sort(key=lambda p: (
        sum(1 for c in p.benefit_checklist if c['field'] in applicant.must_have_keys() and c['covered'] is None),
        -len(p.matched_requirements),
    ))
    return options


def public_market_exclusions(applicant: Applicant, settings: Settings) -> list[dict]:
    excluded = [r for r in quote_exclusions(applicant, settings) if r['plan_key'].startswith('morgan_price:')]
    excluded.extend({'plan_key': p.plan_key, 'product_name': p.product_name, 'insurer': p.insurer, 'gaps': p.unmatched_requirements} for p in _catalogue_candidates(applicant) if p.unmatched_requirements)
    return excluded
