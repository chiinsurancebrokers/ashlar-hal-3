"""Morgan Price (Europe) ApS — Evolution Health Plan EU and EEA.

Commercial terms for the one carrier HAL quotes online as at 15 Oct 2026.
Every figure below is followed by the document and page it comes from.

SOURCE DOCUMENTS
  EU/EVO/SI/PW/04/26   Evolution Health Plan EU, Policy Wording (April 2026)
  EU/EVO/SI/TOB/04/26  Evolution Health Plan EU, Table of Benefits
  Quick-quote PDFs      morgan-price.com/quick-quote, run 15 Oct 2026

Careful: Morgan Price also sells "Evolution Health Plan" through Morgan
Price International (UK), insured by Antea, document code ANT/EVO/PW/04/26.
That is a DIFFERENT product with fourteen geographical areas instead of
four, and its terms do not apply here. If a document you are working from
says ANT/ rather than EU/, it belongs to the other product.

TO UPDATE AFTER A RATE OR TERMS CHANGE
  1. Change the figures below and the `verified_on` dates.
  2. Replace RECONCILIATION_QUOTES with fresh quick-quotes from the
     carrier's own engine.
  3. Run: pytest tests/test_carrier_family_discount.py
     Those tests reproduce each quote to the cent and fail loudly if the
     ladder no longer matches what the carrier charges.
"""
from __future__ import annotations

from backend.app.rates.carriers import (
    CarrierPolicy, FamilyDiscountRule, InstalmentLoading,
    PolicyIssuanceRule, PremiumTaxTreatment,
)

# ---------------------------------------------------------------------------
# Family discount
# ---------------------------------------------------------------------------
# EU/EVO/SI/PW/04/26 page 10, "Family discount means:"
#
#     Couple 5%
#     Family of 3 10%
#     Family of 4 15%
#     Eligibility - minimum of 2 adults per policy
#     Family of 5 will still receive the 15% discount on 4 members
#     (2 parents/2 children) but the 5th child will be normal premium.
#
# So: one 5% step per life beyond the first, capped at three steps, applied
# to four lives at most, and only where two adults are on the policy. In
# this rate table the premium rises monotonically with age, so "the four
# highest-premium lives" and the wording's "2 parents/2 children" are
# always the same set.
#
# Reconciled against five quick-quotes on 15 Oct 2026 — see
# RECONCILIATION_QUOTES below. The percentages were derived from those
# quotes first and then found printed in the wording, which is how the
# eligibility condition came to light: every quote run happened to have
# two adults on it, so the condition never showed up in the numbers.
FAMILY_DISCOUNT = FamilyDiscountRule(
    step_pct=0.05,
    max_steps=3,                  # caps the headline at 15%
    max_discounted_members=4,     # a fifth life pays the full rate
    min_adults=2,                 # "minimum of 2 adults per policy"
    adult_from_age=19,            # the policy's own definition of a child
    max_verified_lives=5,         # six lives has never been reconciled
)

# ---------------------------------------------------------------------------
# Instalment loading
# ---------------------------------------------------------------------------
# Printed on every Evolution Health EU quick-quote PDF, "Administration Fee":
#
#     "Morgan Price charges an administration fee for premium instalment
#      facilities of 8% for monthly payments, 5% for quarterly payments and
#      4% for semi annual payments for premiums payable by credit card and
#      Sepa Direct Debit. If you choose to pay annually by bank transfer
#      there is a bank transfer fee of £10 / €15 / $30."
#
# Verified to the cent against quote bcf5cc74: annual 3,608.04 ->
# 3,896.68 monthly (x1.08), 3,788.44 quarterly (x1.05), 3,752.36
# semi-annual (x1.04).
INSTALMENT = InstalmentLoading(
    monthly_pct=0.08,
    quarterly_pct=0.05,
    semi_annual_pct=0.04,
    annual_pct=0.0,
    annual_bank_transfer_fee={"GBP": 10, "EUR": 15, "USD": 30},
)

# ---------------------------------------------------------------------------
# Who the carrier will issue to
# ---------------------------------------------------------------------------
# EU/EVO/SI/PW/04/26 page 5, section 2a "Who can apply?":
#
#     "We offer cover exclusively for children between the age of 10 and 17
#      without any parent or guardian being covered under the policy. A
#      compulsory excess applies to these policies of $/€/£ 100 per claim
#      ... Any children under the age of 10 have to have an adult covered
#      on the policy."
#     "Maximum age of entry at the start date of the policy on an FMU basis
#      is 74. Maximum age of entry ... on a Moratorium basis is 55."
#
# An 18 or 19 year old may hold a policy in their own name (confirmed by
# Chris Iatropoulos, 15 Oct 2026). They price on the 0-19 Child rate band
# but are not a child-only policy, so the compulsory excess does not apply.
ISSUANCE = PolicyIssuanceRule(
    child_only_min_age=10,
    child_only_max_age=17,
    child_only_excess_per_claim={"GBP": 100, "EUR": 100, "USD": 100},
    under_min_age_requires_an_adult=True,
    max_entry_age_fmu=74,
    max_entry_age_moratorium=55,
)

# ---------------------------------------------------------------------------
# Premium tax
# ---------------------------------------------------------------------------
# Printed on every quick-quote PDF:
#
#     "Taxes are not included in your quote. In some countries an insurance
#      premium tax will be payable on top of your insurance premium; it is
#      calculated as a percentage of the premium."
#
# HAL does not compute it. The rate depends on the country of residence and
# the contract type, it is in no rate workbook, and for France alone the
# plausible range runs from nothing to over 20% — a spread far too wide to
# guess at in front of a client.
TAX = PremiumTaxTreatment(
    included_in_quoted_premium=False,
    note_en=("Premiums are shown before insurance premium tax. Whether tax applies, "
             "and at what rate, depends on your country of residence — your broker "
             "confirms the final figure with the insurer before anything is placed."),
    note_el=("Τα ασφάλιστρα εμφανίζονται προ φόρου ασφαλίστρων. Το αν επιβάλλεται φόρος, "
             "και με ποιον συντελεστή, εξαρτάται από τη χώρα κατοικίας σας — ο "
             "διαμεσολαβητής επιβεβαιώνει το τελικό ποσό με τον ασφαλιστή πριν την "
             "τοποθέτηση."),
)

# ---------------------------------------------------------------------------
# Reconciliation evidence
# ---------------------------------------------------------------------------
# Quick-quotes from the carrier's own engine that HAL must reproduce.
# All: Standard Plus, Area 1 Europe, EUR 0 excess, 0% co-insurance,
# country of residence France, run 15 Oct 2026.
#
# The last two cover the same five lives entered in different orders. Both
# returned 5,170.62 with exactly one member at the full rate, and in both
# it was the youngest child — which is what distinguishes a rule from an
# artefact of how the members were typed in.
RECONCILIATION_QUOTES = (
    {"ages": (36, 33), "annual_total": 2903.14, "discount": 0.05,
     "reference": "quick-quote screenshot"},
    {"ages": (36, 33, 3), "annual_total": 3608.04, "discount": 0.10,
     "reference": "bcf5cc74-0ea4-4008-a0b9-04da3e0b0ea4"},
    {"ages": (36, 33, 10, 3), "annual_total": 4217.63, "discount": 0.15,
     "reference": "03ea8231-ec73-47b5-aabb-f6e6f22637ac"},
    {"ages": (36, 33, 10, 3, 15), "annual_total": 5170.62, "discount": 0.15,
     "reference": "Morgan_Price_Health_Insurance_Quote_4"},
    {"ages": (36, 5, 10, 8, 33), "annual_total": 5170.62, "discount": 0.15,
     "reference": "7c06f5b0-314a-4cd2-ae3c-4b46cb8e9916"},
)


POLICY = CarrierPolicy(
    carrier="morgan_price",
    carrier_name="Morgan Price (Europe) ApS",
    product_family="Evolution Health Plan EU and EEA",
    family_discount=FAMILY_DISCOUNT,
    instalment=INSTALMENT,
    issuance=ISSUANCE,
    tax=TAX,
    reconciliation_quotes=RECONCILIATION_QUOTES,
)
