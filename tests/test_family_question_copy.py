from backend.app.discovery.flow import _sex_question
from backend.app.discovery.family_flow import next_family_question


def test_primary_sex_question_is_client_friendly():
    question = _sex_question(False)
    assert question["reply"] == "What is your sex?"
    assert "rating" not in question["reply"].lower()


def test_family_member_sex_question_is_client_friendly():
    state = {
        "family_answered": True,
        "family_requested": True,
        "household_members": [{"member_id": "member-1", "relationship": "spouse", "age": 35}],
        "household_member_index": 0,
    }
    question = next_family_question(state, False)
    assert question["key"] == "family_sex"
    assert question["reply"] == "What is this family member's sex?"
    assert "rating" not in question["reply"].lower()
