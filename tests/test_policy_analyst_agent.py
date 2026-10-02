from backend.app.services.policy_analyst_agent import analyze_current_policy


def test_policy_analyst_keeps_unconfirmed_terms_out_of_confirmed_facts():
    result = analyze_current_policy({"benefit_rows":[
        {"benefit_code":"outpatient","status":"confirmed","value":"Covered"},
        {"benefit_code":"dental","status":"unconfirmed","value":"Unknown"},
    ]})
    assert result.verdict == "WARN"
    assert [x["benefit_code"] for x in result.confirmed_facts] == ["outpatient"]
    assert [x["benefit_code"] for x in result.unconfirmed_facts] == ["dental"]
    assert result.safe_for_comparison is True


def test_policy_analyst_blocks_contradictory_evidence():
    result = analyze_current_policy({"benefit_rows":[
        {"benefit_code":"maternity","status":"confirmed"},
        {"benefit_code":"maternity","status":"not_covered"},
    ]})
    assert result.verdict == "BLOCK"
    assert result.safe_for_comparison is False
    assert result.issues[0].issue_type == "contradictory_benefit_evidence"


def test_policy_analyst_does_not_infer_when_rows_missing():
    result = analyze_current_policy({"policy_name":"Example"})
    assert result.verdict == "WARN"
    assert result.confirmed_facts == []
    assert result.issues[0].issue_type == "no_structured_benefit_rows"
