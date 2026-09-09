import pytest

from backend.app.services.leads import _verified_plans_for, _build_comparison_message
from backend.app.core.config import Settings


def test_server_recomputes_real_premium_regardless_of_what_client_implies():
    applicant_state = {"age": 40, "residence_country": "Greece", "coverage_area": "area1"}
    settings = Settings()

    shortlist_plans = _verified_plans_for(applicant_state, ["morgan_price:standard"], settings)
    assert len(shortlist_plans) == 1
    # This must be the REAL, server-computed premium — €1490.80 — no matter
    # what a compromised/forged client request might have implied.
    assert shortlist_plans[0].premium == 1490.80


def test_unknown_or_forged_plan_key_is_rejected_not_silently_priced():
    applicant_state = {"age": 40, "residence_country": "Greece", "coverage_area": "area1"}
    settings = Settings()
    with pytest.raises(ValueError):
        _verified_plans_for(applicant_state, ["totally_made_up_carrier:fantasy_plan"], settings)


def test_comparison_email_body_only_ever_contains_server_side_premium_string():
    applicant_state = {"age": 40, "residence_country": "Greece", "coverage_area": "area1"}
    settings = Settings()
    plans = _verified_plans_for(applicant_state, ["morgan_price:standard"], settings)

    msg = _build_comparison_message("Chris", "chris@example.com", plans, "hal@ashlar.example", None)
    body = msg.get_body(preferencelist=("html",)).get_content()
    assert "1,490.80" in body
    # A forged lower price must never appear anywhere in the rendered email.
    assert "868.00" not in body
