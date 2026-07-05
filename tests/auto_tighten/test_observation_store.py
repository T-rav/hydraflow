from auto_tighten.models import Observation
from auto_tighten.observation_store import ObservationStore


def test_append_then_window_filters_by_ratchet(tmp_path):
    store = ObservationStore(tmp_path / "tighten.jsonl")
    store.append(
        Observation(
            ts="1",
            ratchet_id="coverage",
            current=80.0,
            baseline=70.0,
            direction="tighter",
        )
    )
    store.append(
        Observation(
            ts="2", ratchet_id="other", current=1, baseline=2, direction="tighter"
        )
    )
    store.append(
        Observation(
            ts="3",
            ratchet_id="coverage",
            current=81.0,
            baseline=70.0,
            direction="tighter",
        )
    )
    w = store.window("coverage", limit=10)
    assert [o.ts for o in w] == ["1", "3"]
