from __future__ import annotations

from events import EventType


def test_loop_fitness_event_type_exists() -> None:
    assert EventType.LOOP_FITNESS_UPDATE == "loop_fitness_update"


def test_payload_typeddict_keys() -> None:
    from models import LoopFitnessUpdatePayload

    payload: LoopFitnessUpdatePayload = {
        "generated_at": "2026-06-30T00:00:00+00:00",
        "window_days": 30,
        "loop_count": 44,
        "scored_count": 3,
    }
    assert payload["loop_count"] == 44
