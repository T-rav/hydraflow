from __future__ import annotations

from convergence_recording import record_stage_verdict, signatures_from_concerns


def test_records_verdict(tmp_path):
    from tests.helpers import make_tracker

    t = make_tracker(tmp_path)
    record_stage_verdict(
        t,
        issue_number=7,
        stage="triage",
        decision="ADVANCE",
        signatures=[],
    )
    led = t.get_convergence_ledger(7)
    assert led is not None
    assert led.stage_state["triage"].last_verdict == "ADVANCE"


def test_signatures_from_concerns_filters_high_critical():
    from datetime import UTC, datetime

    from pending_concerns import Concern

    def c(sev, text):
        return Concern(
            id=text,
            raised_in_phase="plan",
            raised_in_stage="s",
            severity=sev,
            concern=text,
            raised_at=datetime.now(UTC),
            must_address_by="next",
        )

    out = signatures_from_concerns([c("CRITICAL", "a"), c("LOW", "b"), c("HIGH", "c")])
    assert out == ["a", "c"]
