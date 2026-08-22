"""The shared operator-Start transition (#11611).

``apply_operator_start`` is what ``POST /api/control/start`` (both branches),
``POST /api/runtimes/{slug}/start`` and boot-time autostart all apply, so the
three doors cannot drift apart. These are the pure-state tests; the route-level
behaviour lives in ``tests/test_operator_stopped_latch_routes.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from operator_start import DEFAULT_PIPELINE_WORKERS, apply_operator_start


class _FakeLineState:
    """Minimal StateTracker stand-in recording what the transition wrote."""

    def __init__(
        self, disabled: set[str] | None = None, *, operator_stopped: bool = True
    ) -> None:
        self._disabled = set(disabled or set())
        self.operator_stopped = operator_stopped
        self.disabled_writes = 0

    def set_operator_stopped(self, stopped: bool) -> None:
        self.operator_stopped = stopped

    def get_disabled_workers(self) -> set[str]:
        return set(self._disabled)

    def set_disabled_workers(self, names: set[str]) -> None:
        self._disabled = set(names)
        self.disabled_writes += 1


def test_default_pipeline_workers_are_the_board_to_ready_path() -> None:
    assert set(DEFAULT_PIPELINE_WORKERS) == {
        "triage",
        "plan",
        "implement",
        "review",
        "hitl",
    }


class TestApplyOperatorStart:
    """Pure-state behaviour of the shared Start transition."""

    def test_clears_the_operator_stopped_latch(self) -> None:
        line_state = _FakeLineState()

        apply_operator_start(line_state)

        assert line_state.operator_stopped is False

    def test_returns_the_pipeline_workers_it_reenabled(self) -> None:
        line_state = _FakeLineState({"plan", "triage", "principles_audit"})

        assert apply_operator_start(line_state) == {"plan", "triage"}

    def test_leaves_non_pipeline_kill_switches_disabled(self) -> None:
        line_state = _FakeLineState({"plan", "principles_audit"})

        apply_operator_start(line_state)

        assert line_state.get_disabled_workers() == {"principles_audit"}

    def test_writes_nothing_when_no_pipeline_worker_is_disabled(self) -> None:
        line_state = _FakeLineState({"principles_audit"})

        assert apply_operator_start(line_state) == set()
        assert line_state.disabled_writes == 0

    def test_can_leave_the_factory_level_latch_alone(self) -> None:
        """Per-repo Start and boot autostart run one line — neither may unlatch
        the whole factory."""
        line_state = _FakeLineState({"plan"})

        apply_operator_start(line_state, clear_latch=False)

        assert line_state.operator_stopped is True

    def test_flips_the_live_orchestrators_in_memory_flags(self) -> None:
        line_state = _FakeLineState({"plan", "principles_audit"})
        orchestrator = MagicMock()

        apply_operator_start(line_state, orchestrator)

        orchestrator.set_bg_worker_enabled.assert_called_once_with("plan", True)

    def test_state_wins_over_the_orchestrators_recomputed_set(self) -> None:
        """set_bg_worker_enabled rebuilds the persisted set from the in-memory
        map, which may not carry kill-switches this process never loaded — the
        authoritative write must land last."""
        line_state = _FakeLineState({"plan", "principles_audit"})
        orchestrator = MagicMock()
        orchestrator.set_bg_worker_enabled.side_effect = lambda name, enabled: (
            line_state.set_disabled_workers(set())
        )

        apply_operator_start(line_state, orchestrator)

        assert line_state.get_disabled_workers() == {"principles_audit"}
