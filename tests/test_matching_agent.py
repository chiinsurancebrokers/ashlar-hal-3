from backend.app.services.matching_agent import deterministic_matching_summary


def test_matching_agent_preserves_deterministic_order_and_values():
    quotes = [
        {"plan_key":"a:one","product_name":"One","insurer":"A","premium":1200,"currency":"EUR","recommendation_rank":1,"matched_requirements":["Out-patient cover"]},
        {"plan_key":"b:two","product_name":"Two","insurer":"B","premium":900,"currency":"EUR","recommendation_rank":2,"matched_requirements":[]},
    ]
    before = [dict(q) for q in quotes]
    result = deterministic_matching_summary(quotes, [], greek=False)
    assert result.top_plan_key == "a:one"
    assert result.ranked_plan_keys == ["a:one", "b:two"]
    assert quotes == before
    assert "EUR 1,200.00" in result.explanation


def test_matching_agent_reports_deterministic_exclusions_without_reintroducing_them():
    quotes = [{"plan_key":"a:one","product_name":"One","insurer":"A","premium":1200,"currency":"EUR"}]
    excluded = [{"plan_key":"x:no","gaps":["Routine maternity"]}]
    result = deterministic_matching_summary(quotes, excluded, greek=False)
    assert result.ranked_plan_keys == ["a:one"]
    assert "1 plan" in result.explanation
    assert "x:no" not in result.ranked_plan_keys


def test_matching_agent_handles_empty_shortlist():
    result = deterministic_matching_summary([], [], greek=False)
    assert result.top_plan_key is None
    assert result.ranked_plan_keys == []
    assert result.explanation == ""
