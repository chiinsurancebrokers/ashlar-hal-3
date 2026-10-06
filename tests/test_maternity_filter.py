from backend.app.discovery.maternity_filter import maternity_question_relevant


def test_only_explicit_female_18_to_47_is_relevant():
    assert maternity_question_relevant({"age": 18, "sex": "female"})
    assert maternity_question_relevant({"age": 47, "sex": "woman"})
    assert not maternity_question_relevant({"age": 17, "sex": "female"})
    assert not maternity_question_relevant({"age": 48, "sex": "female"})
    assert not maternity_question_relevant({"age": 32, "sex": "male"})


def test_never_infer_sex_from_name_or_other_proxies():
    assert not maternity_question_relevant({"age": 32, "applicant_name": "Maria"})
    assert not maternity_question_relevant({"age": 32, "nationality": "Greece"})
