from models import StateData, SteeringState


def test_steering_state_round_trips_through_json():
    s = StateData()
    s.human_steering["42"] = SteeringState(
        guidance="focus on error handling",
        flow="paused",
        redo_phase=None,
        redo_count=1,
        last_applied_ts="2026-07-03T10:00:00Z",
    )
    reloaded = StateData.model_validate_json(s.model_dump_json())
    got = reloaded.human_steering["42"]
    assert got.guidance == "focus on error handling"
    assert got.flow == "paused"
    assert got.redo_count == 1
    assert got.last_applied_ts == "2026-07-03T10:00:00Z"


def test_steering_defaults():
    st = SteeringState()
    assert st.flow == "running" and st.guidance is None and st.redo_count == 0
