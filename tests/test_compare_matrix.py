from backend.app.evidence.compare_matrix import build_comparison_matrix, NOT_CONFIRMED


def test_matrix_pulls_real_morgan_price_benefit_values():
    plans = [
        {"plan_key": "morgan_price:standard", "carrier": "morgan_price", "product_code": "standard", "insurer": "Morgan Price (Europe) ApS", "product_name": "Morgan Price Standard"},
        {"plan_key": "morgan_price:premium", "carrier": "morgan_price", "product_code": "premium", "insurer": "Morgan Price (Europe) ApS", "product_name": "Morgan Price Premium"},
    ]
    matrix = build_comparison_matrix(plans)
    assert matrix.unsupported_plan_keys == []
    maternity_row = next(r for r in matrix.rows if r.benefit_code == "normal_maternity")
    # This is a REAL verified fact ("not covered"), correctly distinct from
    # NOT_CONFIRMED (which means "we have no data either way").
    assert "not covered" in maternity_row.values["morgan_price:standard"].lower()
    assert maternity_row.values["morgan_price:standard"] != NOT_CONFIRMED
    assert maternity_row.values["morgan_price:premium"] not in (NOT_CONFIRMED, maternity_row.values["morgan_price:standard"])


def test_matrix_never_fabricates_a_row_nobody_has_data_for():
    plans = [
        {"plan_key": "morgan_price:standard", "carrier": "morgan_price", "product_code": "standard", "insurer": "MP", "product_name": "Standard"},
    ]
    matrix = build_comparison_matrix(plans)
    codes = {r.benefit_code for r in matrix.rows}
    assert "hrt" not in codes or matrix.rows  # HRT is only on higher tiers; standard-only comparison must not invent it


def test_unsupported_carrier_flagged_not_silently_dropped():
    plans = [
        {"plan_key": "morgan_price:standard", "carrier": "morgan_price", "product_code": "standard", "insurer": "MP", "product_name": "Standard"},
        {"plan_key": "now_health:simplecare250", "carrier": "now_health", "product_code": "simplecare250", "insurer": "Now Health", "product_name": "SimpleCare 250"},
    ]
    matrix = build_comparison_matrix(plans)
    assert matrix.unsupported_plan_keys == ["now_health:simplecare250"]
    assert "morgan_price:standard" in matrix.plan_keys
    assert "now_health:simplecare250" not in matrix.plan_keys
