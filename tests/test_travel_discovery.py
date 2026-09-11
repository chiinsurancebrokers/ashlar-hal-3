from backend.app.travel.discovery import deterministic_travel_updates, next_travel_question, _looks_like_place


def test_full_travel_sequence():
    state = {}
    q = next_travel_question(state)
    assert q["key"] == "trip_type"

    state["travel_pending_question"] = "trip_type"
    state.update(deterministic_travel_updates("single trip", state))
    assert state["travel_trip_type"] == "single"

    q = next_travel_question(state)
    assert q["key"] == "destination"

    state["travel_pending_question"] = "destination"
    state.update(deterministic_travel_updates("Italy", state))
    assert state["travel_destination"] == "Italy"
    assert state["travel_destination_scope"] == "europe"

    q = next_travel_question(state)
    assert q["key"] == "age"

    state["travel_pending_question"] = "age"
    state.update(deterministic_travel_updates("45", state))
    assert state["travel_age"] == 45

    q = next_travel_question(state)
    assert q["key"] == "cover_preference"

    state["travel_pending_question"] = "cover_preference"
    state.update(deterministic_travel_updates("balanced", state))
    assert next_travel_question(state) is None


def test_garbage_transcription_never_accepted_as_destination():
    state = {"travel_pending_question": "destination"}
    out = deterministic_travel_updates(">>>>>>>>", state)
    assert out == {}
    assert next_travel_question({**state, "trip_type_answered": True}) is not None  # still asks


def test_skip_on_trip_type_defaults_to_single():
    state = {"travel_pending_question": "trip_type"}
    out = deterministic_travel_updates("skip", state)
    assert out["travel_trip_type"] == "single"


def test_skip_on_age_has_no_default_and_is_ignored():
    state = {"travel_pending_question": "age"}
    out = deterministic_travel_updates("skip", state)
    assert "travel_age" not in out


def test_long_stay_flag_set_on_relocation_language():
    state = {"travel_pending_question": "destination"}
    out = deterministic_travel_updates("I'm moving to Berlin", state)
    assert out.get("travel_long_stay_flag") is True


def test_looks_like_place_rejects_noise_accepts_real_names():
    assert _looks_like_place(">>>>>>>>") is False
    assert _looks_like_place("Italy") is True
    assert _looks_like_place("Νότια Γαλλία") is True
