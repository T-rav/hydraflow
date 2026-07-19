"""Regression: three divergent process-group kill guards in one night (#9641).

The killpg convention was re-derived independently at three sites with
THREE different guard strengths: unguarded (`os.killpg(proc.pid, ...)` —
mock pid coerces to 1 via ``__index__``), ``isinstance(pid, int)`` (lets
``True`` and ``0`` through — killpg(0) signals the CALLER'S OWN group,
the #10002 CI smoke deaths), and ``int and > 0``. One primitive now owns
the strongest guard; the architecture gate forbids new call sites.

Pins:
- Real positive int pid → group kill via os.killpg, child untouched.
- Mock/absent/bool/zero/negative pids → child-only proc.kill() fallback,
  os.killpg NEVER invoked.
- Already-dead group (ProcessLookupError) never escapes.
- Both legacy wrappers (runner_utils._kill_proc_group,
  execution._reap_process_group) route through the primitive.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from process_group import is_real_pid, kill_process_group


class _FakeProc:
    def __init__(self, pid: object) -> None:
        self.pid = pid
        self.killed = False

    def kill(self) -> None:
        self.killed = True


class TestIsRealPid:
    def test_positive_int_is_real(self) -> None:
        assert is_real_pid(4242)

    def test_hazard_pids_are_rejected(self) -> None:
        """0 = own group, negatives = pgid syntax, True passes naive isinstance."""
        assert not is_real_pid(0)
        assert not is_real_pid(-1)
        assert not is_real_pid(True)
        assert not is_real_pid(None)
        assert not is_real_pid(MagicMock())


class TestKillProcessGroup:
    def test_real_pid_group_killed_not_child(self) -> None:
        proc = _FakeProc(pid=4242)
        with patch("process_group.os.killpg") as killpg:
            kill_process_group(proc)
        killpg.assert_called_once_with(4242, signal.SIGKILL)
        assert proc.killed is False

    def test_mock_pid_takes_child_only_fallback(self) -> None:
        """The #10002 class: auto-attr .pid coerces to 1 — never killpg it."""
        proc = _FakeProc(pid=MagicMock())
        with patch("process_group.os.killpg") as killpg:
            kill_process_group(proc)
        killpg.assert_not_called()
        assert proc.killed is True

    def test_zero_pid_never_signals_own_group(self) -> None:
        proc = _FakeProc(pid=0)
        with patch("process_group.os.killpg") as killpg:
            kill_process_group(proc)
        killpg.assert_not_called()
        assert proc.killed is True

    def test_dead_group_suppressed(self) -> None:
        proc = _FakeProc(pid=4242)
        with patch("process_group.os.killpg", side_effect=ProcessLookupError):
            kill_process_group(proc)  # must not raise

    def test_pidless_object_is_a_noop(self) -> None:
        kill_process_group(object())  # no pid, no kill() — never raises

    def test_custom_signal_passes_through(self) -> None:
        proc = _FakeProc(pid=4242)
        with patch("process_group.os.killpg") as killpg:
            kill_process_group(proc, signal.SIGTERM)
        killpg.assert_called_once_with(4242, signal.SIGTERM)


class TestLegacyWrappersDelegate:
    def test_runner_utils_wrapper_routes_through_primitive(self) -> None:
        from runner_utils import _kill_proc_group

        proc = _FakeProc(pid=7777)
        with patch("process_group.os.killpg") as killpg:
            _kill_proc_group(proc)  # type: ignore[arg-type]
        killpg.assert_called_once_with(7777, signal.SIGKILL)

    def test_execution_wrapper_routes_through_primitive(self) -> None:
        from execution import _reap_process_group

        proc = _FakeProc(pid=8888)
        with patch("process_group.os.killpg") as killpg:
            _reap_process_group(proc)  # type: ignore[arg-type]
        killpg.assert_called_once_with(8888, signal.SIGKILL)

    def test_execution_wrapper_rejects_bool_pid(self) -> None:
        """The old inline guard let bool through; the primitive must not."""
        from execution import _reap_process_group

        proc = _FakeProc(pid=True)
        with patch("process_group.os.killpg") as killpg:
            _reap_process_group(proc)  # type: ignore[arg-type]
        killpg.assert_not_called()
        assert proc.killed is True
