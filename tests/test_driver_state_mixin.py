"""StateTracker driver-state accessor + crash-resume tests (HydraFlow v2)."""

from __future__ import annotations

from pathlib import Path

from models import SuspendRecord
from tests.helpers import make_tracker


class TestDriverStateMixin:
    def test_set_and_get_driver_state_persists(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_driver_state(7) == "TRIAGE"  # default, no ledger yet
        tracker.set_driver_state(7, "READY")

        reloaded = make_tracker(tmp_path)
        reloaded.load()
        assert reloaded.get_driver_state(7) == "READY"

    def test_suspend_and_clear(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        rec = SuspendRecord(
            reason="shape_human_select",
            suspended_at="2026-06-30T12:00:00+00:00",
            wake_signal="comment",
            resume_state="PLAN",
        )
        tracker.suspend_driver(7, rec)

        reloaded = make_tracker(tmp_path)
        reloaded.load()
        led = reloaded.get_convergence_ledger(7)
        assert led is not None and led.suspend is not None
        assert led.suspend.resume_state == "PLAN"

        reloaded.clear_suspend(7)
        again = make_tracker(tmp_path)
        again.load()
        led2 = again.get_convergence_ledger(7)
        assert led2 is not None and led2.suspend is None

    def test_take_pending_correction_reads_and_clears(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_pending_correction(7, "use a bounded queue")
        # First take returns the text...
        assert tracker.take_pending_correction(7) == "use a bounded queue"
        # ...and clears it durably.
        reloaded = make_tracker(tmp_path)
        reloaded.load()
        assert reloaded.take_pending_correction(7) is None

    def test_take_pending_correction_missing_ledger_returns_none(
        self, tmp_path: Path
    ) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.take_pending_correction(999) is None
