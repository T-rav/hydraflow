from __future__ import annotations

from convergence_recording import record_stage_verdict, signatures_from_concerns


def test_shared_helper_consistency():
    """M3 drift guard: signatures_from_concerns and _signature_for produce equivalent sets."""
    from datetime import UTC, datetime

    from adversarial_retry_loop import _signature_for
    from convergence_recording import signatures_from_concerns
    from pending_concerns import Concern

    def make_concern(sev, text):
        return Concern(
            id=text,
            raised_in_phase="plan",
            raised_in_stage="s",
            severity=sev,
            concern=text,
            raised_at=datetime.now(UTC),
            must_address_by="next",
        )

    concerns = [
        make_concern("CRITICAL", "missing auth check"),
        make_concern("LOW", "style issue"),
        make_concern("HIGH", "sql injection"),
    ]

    class FakeFindings:
        findings = concerns

    sfc_out = signatures_from_concerns(concerns)
    sig_out = _signature_for(FakeFindings()).split("|")
    # Both must produce the same sorted set of CRITICAL/HIGH concern texts.
    assert sfc_out == sorted(sig_out)


def test_signatures_from_concerns_normalization():
    """_normalize_text is available as a module-level helper."""
    from convergence_recording import _normalize_text

    assert _normalize_text("  hello   world  ") == "hello world"
    assert _normalize_text("  ") == ""
    assert _normalize_text("x") == "x"


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
