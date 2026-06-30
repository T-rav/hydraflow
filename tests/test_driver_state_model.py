"""Unit tests for the IssueDriver state-model types (HydraFlow v2)."""

from __future__ import annotations

from models import PolicyEvent, SuspendRecord


class TestSuspendRecord:
    def test_round_trips_and_defaults(self) -> None:
        rec = SuspendRecord(
            reason="shape_human_select",
            suspended_at="2026-06-30T12:00:00+00:00",
            wake_signal="comment",
            resume_state="SHAPE",
        )
        restored = SuspendRecord.model_validate_json(rec.model_dump_json())
        assert restored == rec
        assert restored.resume_state == "SHAPE"


class TestPolicyEvent:
    def test_round_trips_with_default_counters(self) -> None:
        ev = PolicyEvent(
            at="2026-06-30T12:00:00+00:00",
            from_state="REVIEW",
            to_state="READY",
            decision="LOOP_BACK",
            reason="reviewer requested changes",
        )
        restored = PolicyEvent.model_validate_json(ev.model_dump_json())
        assert restored == ev
        assert restored.counters == {}
