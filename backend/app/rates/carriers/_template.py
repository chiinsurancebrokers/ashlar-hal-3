"""TEMPLATE — copy to <carrier>.py when a new carrier's workbook arrives.

This module is not registered and nothing imports it. It exists so that
adding a carrier is filling in a form rather than reverse-engineering
morgan_price.py.

HOW TO ADD A CARRIER
  1. Copy this file to backend/app/rates/carriers/<carrier>.py
  2. Fill in every block from THAT carrier's own documents. Put the
     document code and page beside each figure — the next person should
     never have to re-read the wording to check a number.
  3. Register it in carriers/__init__.py `_build_registry()`.
  4. Add its rate workbook to data/rates/ and its evidence folder to
     data/evidence/.
  5. Write reconciliation tests: run a handful of quotes on the carrier's
     own quote engine and assert HAL reproduces each total to the cent.
     See tests/test_carrier_family_discount.py for the pattern.

LEAVE A BLOCK OUT RATHER THAN GUESSING AT IT
  Every default here is "no discount, no loading, no limits". That is the
  safe direction: HAL quotes the plain sum of the members, a broker
  corrects it downward, and the client is pleasantly surprised. A guessed
  discount under-quotes, and the client meets the real number at proposal
  stage — the exact failure HAL exists to prevent.
"""
from __future__ import annotations

from backend.app.rates.carriers import (
    CarrierPolicy, FamilyDiscountRule, InstalmentLoading,
    PolicyIssuanceRule, PremiumTaxTreatment,
)

# --- Family discount -------------------------------------------------------
# Source: <document code>, page <n>, "<heading>"
# Quote the wording verbatim here so the figures can be checked without
# opening the PDF.
#
# If this carrier's ladder does not fit step/cap/min-adults, do NOT force
# it. Give this module its own FamilyDiscountRule subclass overriding
# pct_for(), which is why these live in Python rather than a data file.
FAMILY_DISCOUNT = FamilyDiscountRule()          # no discount until confirmed

# --- Instalment loading ----------------------------------------------------
# Source: <where the carrier states its instalment / administration fees>
# Leave at zero unless the carrier publishes them; HAL will then show the
# annual premium divided evenly, which is only correct when there is no fee.
INSTALMENT = InstalmentLoading()

# --- Who the carrier will issue to ----------------------------------------
# Source: <document code>, "Who can apply?" or equivalent
# Minimum ages for a policy in a child's own name, any compulsory excess on
# those, and the maximum entry ages.
ISSUANCE = PolicyIssuanceRule()

# --- Premium tax -----------------------------------------------------------
# Does the carrier's quoted premium include insurance premium tax?
# HAL never computes a tax rate — it only says whether the figure is before
# tax, and leaves the amount to the broker and the insurer.
TAX = PremiumTaxTreatment(
    included_in_quoted_premium=False,
    note_en="",
    note_el="",
)

# --- Reconciliation evidence ----------------------------------------------
# Quotes from the carrier's OWN engine that HAL must reproduce to the cent.
# Without these there is nothing to catch a rate change that breaks the
# ladder. Record the quote reference so it can be re-run.
RECONCILIATION_QUOTES: tuple = ()


POLICY = CarrierPolicy(
    carrier="",                 # the key used in plan_key, e.g. "april"
    carrier_name="",            # as it should read to a client
    product_family="",
    family_discount=FAMILY_DISCOUNT,
    instalment=INSTALMENT,
    issuance=ISSUANCE,
    tax=TAX,
    reconciliation_quotes=RECONCILIATION_QUOTES,
)
