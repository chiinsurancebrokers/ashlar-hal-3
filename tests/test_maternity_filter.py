from backend.app.discovery.maternity_filter import maternity_question_relevant, normalise_sex


def test_maternity_question_only_for_explicit_female_18_to_47():
    assert maternity_question_relevant({"age": 18, "sex": "female"}) is True
    assert maternity_question_relevant({"age": 47, "sex": "female"}) is True
    assert maternity_question_relevant({"age": 32, "sex": "woman"}) is True


def test_maternity_question_not_for_other_age_or_sex():
    assert maternity_question_relevant({"age": 17, "sex": "female"}) is False
    assert maternity_question_relevant({"age": 48, "sex": "female"}) is False
    assert maternity_question_relevant({"age": 32, "sex": "male"}) is False
    assert maternity_question_relevant({"age": 32, "sex": "prefer_not_to_say"}) is False


def test_maternity_filter_never_infers_sex_from_other_fields():
    assert maternity_question_relevant({"age": 32, "applicant_name": "Maria"}) is False
    assert maternity_question_relevant({"age": 32, "nationality": "Greece"}) is False
    assert normalise_sex("unknown") is None
