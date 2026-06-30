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


from models import ConvergenceLedger, PolicyEvent  # noqa: E402


class TestConvergenceLedgerDriverFields:
    def test_driver_field_defaults(self) -> None:
        cl = ConvergenceLedger(issue_number=7)
        assert cl.driver_state == "TRIAGE"
        assert cl.suspend is None
        assert cl.pending_correction is None
        assert cl.hitl_origin is None
        assert cl.hitl_cause is None
        assert cl.route_backs == {}
        assert cl.issue_attempts == 0
        assert cl.policy_log == []

    def test_route_back_and_attempt_helpers(self) -> None:
        cl = ConvergenceLedger(issue_number=7)
        assert cl.get_route_backs("ready->plan") == 0
        assert cl.increment_route_backs("ready->plan") == 1
        assert cl.increment_route_backs("ready->plan") == 2
        assert cl.get_route_backs("ready->plan") == 2
        assert cl.get_route_backs("review->ready") == 0
        assert cl.increment_issue_attempts() == 1
        assert cl.increment_issue_attempts() == 2

    def test_append_policy_event(self) -> None:
        cl = ConvergenceLedger(issue_number=7)
        ev = PolicyEvent(
            at="2026-06-30T12:00:00+00:00",
            from_state="PLAN",
            to_state="READY",
            decision="ADVANCE",
            reason="plan approved",
        )
        cl.append_policy_event(ev)
        assert cl.policy_log == [ev]

    def test_driver_fields_round_trip(self) -> None:
        cl = ConvergenceLedger(issue_number=7, driver_state="REVIEW")
        cl.increment_route_backs("review->ready")
        cl.increment_issue_attempts()
        restored = ConvergenceLedger.model_validate_json(cl.model_dump_json())
        assert restored == cl
        assert restored.driver_state == "REVIEW"
        assert restored.route_backs == {"review->ready": 1}
        assert restored.issue_attempts == 1


from models import StateData  # noqa: E402


class TestDriverFieldBackwardCompat:
    def test_old_ledger_json_loads_with_defaults(self) -> None:
        # A ledger serialized BEFORE the driver fields existed.
        old_json = '{"issue_number": 7, "laps": 2, "blast_radius": "high"}'
        cl = ConvergenceLedger.model_validate_json(old_json)
        assert cl.laps == 2
        assert cl.blast_radius == "high"
        # New fields fall back to defaults.
        assert cl.driver_state == "TRIAGE"
        assert cl.suspend is None
        assert cl.route_backs == {}
        assert cl.issue_attempts == 0
        assert cl.policy_log == []

    def test_old_statedata_with_old_ledger_round_trips(self) -> None:
        old_state_json = (
            '{"schema_version": 1, '
            '"convergence_ledgers": {"7": {"issue_number": 7, "laps": 1}}}'
        )
        data = StateData.model_validate_json(old_state_json)
        led = data.convergence_ledgers["7"]
        assert led.laps == 1
        assert led.driver_state == "TRIAGE"
        # Re-serializing now includes the new fields with defaults.
        restored = StateData.model_validate_json(data.model_dump_json())
        assert restored.convergence_ledgers["7"].driver_state == "TRIAGE"
