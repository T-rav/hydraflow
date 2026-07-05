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


def test_window_respects_limit(tmp_path):
    store = ObservationStore(tmp_path / "tighten.jsonl")
    # Append 4 observations for ratchet "coverage"
    for ts in ["1", "2", "3", "4"]:
        store.append(
            Observation(
                ts=ts,
                ratchet_id="coverage",
                current=80.0 + float(ts),
                baseline=70.0,
                direction="tighter",
            )
        )
    # window with limit=2 should return the last 2 (most recent)
    w = store.window("coverage", limit=2)
    assert [o.ts for o in w] == ["3", "4"]
    assert len(w) == 2


def test_window_skips_corrupt_lines(tmp_path):
    store = ObservationStore(tmp_path / "tighten.jsonl")
    # Append one valid observation
    store.append(
        Observation(
            ts="1",
            ratchet_id="coverage",
            current=80.0,
            baseline=70.0,
            direction="tighter",
        )
    )
    # Append a garbage line directly to the file
    with open(tmp_path / "tighten.jsonl", "a", encoding="utf-8") as f:
        f.write("not json\n")
    # Append a second valid observation via the store
    store.append(
        Observation(
            ts="2",
            ratchet_id="coverage",
            current=81.0,
            baseline=70.0,
            direction="tighter",
        )
    )
    # window should return exactly the 2 valid observations
    w = store.window("coverage", limit=10)
    assert [o.ts for o in w] == ["1", "2"]
    assert len(w) == 2


def test_window_missing_file_returns_empty(tmp_path):
    store = ObservationStore(tmp_path / "nonexistent.jsonl")
    w = store.window("coverage", limit=10)
    assert w == []
