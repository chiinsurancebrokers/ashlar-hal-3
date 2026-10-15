"""Waiting periods and pre-authorisation must match the printed footnotes.

The Table of Benefits puts its conditions in a footnote under each section,
and most of those footnotes name the specific benefit letters they apply to:

    Section 3, Out-Patient Benefits:
      "Benefit J is subject to a 12 month waiting period and
       pre-authorisation is required"

An earlier ingestion applied each footnote to every row in its section. The
result was HAL telling clients that routine out-patient consultations,
diagnostic tests, MRI/CT/PET scans and physiotherapy all carried a 12-month
waiting period, when only out-patient psychiatric treatment does. For a
client buying exactly twelve months of cover — a long-stay visa applicant,
say — that reads as "you will never have out-patient cover at all", and
they walk away from a plan that in fact covers them from day one.

Eleven of the sixty-five rows were wrong. These tests re-derive every row's
flags from the footnote map recorded alongside the benefits, so a future
re-ingestion cannot quietly reintroduce the same mistake.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

TOB_PATH = Path(__file__).resolve().parents[1] / "data" / "evidence" / "morgan_price_2026" / "table_of_benefits.json"


@pytest.fixture(scope="module")
def tob() -> dict:
    return json.loads(TOB_PATH.read_text(encoding="utf-8"))


def _expected(footnote: dict, letter: str | None) -> tuple[bool, str | None, str | None]:
    """What the printed footnote says for one benefit letter."""
    def scoped(value, letters):
        if letters == "all benefits in this section":
            return value
        return value if (letters and letter in letters) else None

    pre_auth = footnote.get("pre_authorisation")
    pa = bool(pre_auth == "all benefits in this section" or (pre_auth and letter in pre_auth))
    wp = scoped(footnote.get("waiting_period"), footnote.get("waiting_period_benefits"))
    ci = scoped(footnote.get("coinsurance"), footnote.get("coinsurance_benefits"))
    return pa, wp, ci


def test_every_benefit_row_records_its_section_and_letter(tob):
    """Without the benefit letter there is no way to check a footnote that
    names letters, which is how the original error went unnoticed."""
    for benefit in tob["benefits"]:
        if benefit["benefit_code"] == "overall_maximum":
            continue
        assert benefit.get("tob_section"), f"{benefit['benefit_code']} has no section number"
        assert benefit.get("benefit_letter"), f"{benefit['benefit_code']} has no benefit letter"


def test_every_row_matches_the_footnote_printed_for_its_section(tob):
    footnotes = tob["footnotes"]["by_section"]
    mismatches = []
    for benefit in tob["benefits"]:
        section = benefit.get("tob_section")
        if not section:
            continue
        footnote = footnotes.get(str(section))
        assert footnote, f"section {section} has no recorded footnote"
        want = _expected(footnote, benefit.get("benefit_letter"))
        got = (bool(benefit.get("pre_authorisation_required")),
               benefit.get("waiting_period"), benefit.get("coinsurance"))
        if got != want:
            mismatches.append(f"{benefit['benefit_code']} (s{section}{benefit.get('benefit_letter')}): "
                              f"ingested {got}, footnote says {want}")
    assert not mismatches, "rows disagree with the printed footnotes:\n  " + "\n  ".join(mismatches)


def test_out_patient_waiting_period_applies_only_to_psychiatric_treatment(tob):
    """The specific regression. Section 3's footnote names Benefit J alone."""
    rows = [b for b in tob["benefits"] if b.get("tob_section") == 3]
    assert len(rows) == 11, "section 3 should have benefits A to K"

    with_wait = {b["benefit_letter"] for b in rows if b.get("waiting_period")}
    assert with_wait == {"J"}, f"only Benefit J waits; found {sorted(with_wait)}"

    with_preauth = {b["benefit_letter"] for b in rows if b.get("pre_authorisation_required")}
    assert with_preauth == {"J"}, f"only Benefit J needs pre-auth; found {sorted(with_preauth)}"


@pytest.mark.parametrize("code", [
    "outpatient_services_combined",   # physicians and consultants
    "outpatient_diagnostics",         # diagnostic tests, x-rays, pathology
    "outpatient_mri_ct_pet",
    "outpatient_physiotherapy",
])
def test_everyday_out_patient_care_is_covered_from_day_one(tob, code):
    """These are the benefits a client asks about by name. Telling someone
    on a twelve-month policy that they carry a twelve-month wait is the
    same as telling them they are not covered."""
    benefit = next(b for b in tob["benefits"] if b["benefit_code"] == code)
    assert benefit["waiting_period"] is None
    assert benefit["pre_authorisation_required"] is False


def test_hospital_pre_authorisation_follows_the_named_letters(tob):
    """Section 1's footnote names A, B, D, G, H and I. Benefit A is printed
    as six sub-rows, so eleven rows carry pre-auth and six do not."""
    rows = [b for b in tob["benefits"] if b.get("tob_section") == 1]
    needing = {b["benefit_letter"] for b in rows if b["pre_authorisation_required"]}
    assert needing == set("ABDGHI")
    not_needing = {b["benefit_letter"] for b in rows if not b["pre_authorisation_required"]}
    assert not_needing == set("CEFJKL")


def test_conditions_that_genuinely_apply_are_still_recorded(tob):
    """The fix removed conditions that were never in the document. It must
    not have removed the real ones."""
    by_code = {b["benefit_code"]: b for b in tob["benefits"]}
    assert by_code["outpatient_psychiatric"]["waiting_period"] == "12 months"
    assert by_code["hiv_aids_transfusion"]["waiting_period"] == "2 years"
    assert by_code["routine_dental"]["waiting_period"] == "6 months"
    assert by_code["routine_dental"]["coinsurance"] == "10%"
    assert by_code["emergency_dental"]["coinsurance"] is None
    assert by_code["normal_maternity"]["waiting_period"] == "10 months"
    assert by_code["maternity_cash"]["waiting_period"] == "10 months"
    assert by_code["hospital_cash"]["waiting_period"] is None
    assert by_code["infertility_investigations"]["waiting_period"] == "12 months"
    assert by_code["congenital_birth_defects"]["waiting_period"] is None
    assert all(b["waiting_period"] == "12 months"
               for b in tob["benefits"] if b.get("tob_section") == 5)
    assert by_code["hospice_care"]["pre_authorisation_required"] is True
    assert by_code["medical_evacuation_transport"]["pre_authorisation_required"] is True


def test_footnote_map_is_recorded_with_its_source(tob):
    footnotes = tob["footnotes"]
    assert footnotes["source_document"] == "EU/EVO/SI/TOB/04/26"
    assert "Benefit J" in footnotes["by_section"]["3"]["text"]
    assert footnotes["by_section"]["5"]["waiting_period_benefits"] == "all benefits in this section"
    assert footnotes["by_section"]["6"]["coinsurance_benefits"] == ["B", "C", "D", "E"]
