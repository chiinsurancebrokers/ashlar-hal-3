from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.evidence.catalogue import verified_plan_catalogue
from backend.app.evidence.catalogue_plan import catalogue_plan
from backend.app.rates.quote_engine import quote_exclusions, quote_shortlist
from backend.app.schemas.applicant import Applicant


PUBLIC_CATALOGUE_PLAN_KEYS = {
    "img:gpmi_bronze_plus",
    "img:gpmi_silver",
    "img:gpmi_gold",
    "img:gpmi_platinum",
    "cigna:inspire_essential_care",
    "cigna:inspire_executive_care",
    "cigna:inspire_elite_care",
}


def public_market_shortlist(applicant: Applicant, settings: Settings) -> list:
    """Client-facing market options with rate provenance kept explicit.

    The historical IMG rate rows are not GPMI quotations and must never be
    presented as current GPMI options. Current IMG/Cigna catalogue plans are
    benefit-only until a carrier quotation is attached.
    """
    priced = [
        quote
        for quote in quote_shortlist(applicant, settings)
        if not str(quote.plan_key or "").startswith("img:")
    ]
    rows = {
        row["plan_key"]: row
        for row in verified_plan_catalogue()
        if row["plan_key"] in PUBLIC_CATALOGUE_PLAN_KEYS
    }
    catalogue = [catalogue_plan(rows[key]) for key in PUBLIC_CATALOGUE_PLAN_KEYS if key in rows]
    catalogue.sort(key=lambda plan: (
        0 if plan.plan_key.startswith("img:") else 1,
        [
            "img:gpmi_bronze_plus", "img:gpmi_silver", "img:gpmi_gold", "img:gpmi_platinum",
            "cigna:inspire_essential_care", "cigna:inspire_executive_care", "cigna:inspire_elite_care",
        ].index(plan.plan_key),
    ))
    return [*priced, *catalogue]


def public_market_exclusions(applicant: Applicant, settings: Settings) -> list[dict]:
    """Do not surface exclusions for obsolete IMG products in the client UI."""
    return [
        row for row in quote_exclusions(applicant, settings)
        if not str(row.get("plan_key") or "").startswith("img:")
    ]


__all__ = ["PUBLIC_CATALOGUE_PLAN_KEYS", "public_market_exclusions", "public_market_shortlist"]
