"""Unit tests for the orphaned pytest-worker reaper (#10734).

All selection logic is exercised over synthetic ``ps`` snapshots; the only kill
path is tested with a monkeypatched ``os.kill`` so no real process is ever
signalled.
"""

from __future__ import annotations

import os

import pytest
from scripts.liveness import orphan_reaper

_FLOOR = orphan_reaper.DEFAULT_AGE_FLOOR_SECONDS

_HEADER = "  PID  PPID     ELAPSED COMMAND"


def _ps(*rows: str) -> str:
    return "\n".join([_HEADER, *rows]) + "\n"


class TestIsReapablePid:
    @pytest.mark.parametrize("bad", [0, 1, -5, True, False, "7", 7.0, None])
    def test_rejects_unsafe_values(self, bad: object) -> None:
        assert orphan_reaper.is_reapable_pid(bad) is False

    def test_accepts_a_genuine_pid(self) -> None:
        assert orphan_reaper.is_reapable_pid(999_999) is True

    def test_rejects_self_and_parent(self) -> None:
        assert orphan_reaper.is_reapable_pid(os.getpid()) is False
        assert orphan_reaper.is_reapable_pid(os.getppid()) is False


class TestParseEtimeSeconds:
    @pytest.mark.parametrize(
        ("etime", "expected"),
        [
            ("05:00", 300),
            ("00:30", 30),
            ("01:00:00", 3600),
            ("2-03:00:00", 2 * 86400 + 3 * 3600),
            ("10:00", 600),
        ],
    )
    def test_parses_known_formats(self, etime: str, expected: int) -> None:
        assert orphan_reaper.parse_etime_seconds(etime) == expected

    @pytest.mark.parametrize("bad", ["", "  ", "notatime", "1:2:3:4", "x-01:00"])
    def test_malformed_returns_none(self, bad: str) -> None:
        assert orphan_reaper.parse_etime_seconds(bad) is None


class TestSelectOrphanPids:
    def test_orphaned_old_pytest_worker_is_selected(self) -> None:
        ps = _ps("12345     1    10:00 python -m pytest -n auto tests/")
        assert orphan_reaper.select_orphan_pids(ps) == [12345]

    def test_pytest_with_live_parent_is_not_selected(self) -> None:
        # ppid != 1 (a live pytest master) — never a leaked orphan.
        ps = _ps("12345  4242    10:00 python -m pytest -n auto tests/")
        assert orphan_reaper.select_orphan_pids(ps) == []

    def test_young_orphan_below_floor_is_not_selected(self) -> None:
        ps = _ps("12345     1    00:10 python -m pytest -n auto tests/")
        assert orphan_reaper.select_orphan_pids(ps, age_floor_seconds=_FLOOR) == []

    def test_non_pytest_orphan_is_not_selected(self) -> None:
        ps = _ps("12345     1    99:00 /usr/bin/some-daemon --serve")
        assert orphan_reaper.select_orphan_pids(ps) == []

    def test_pid_zero_one_and_negative_rejected(self) -> None:
        ps = _ps(
            "0     1    99:00 python -m pytest -n auto",
            "1     1    99:00 python -m pytest -n auto",
            "-3     1    99:00 python -m pytest -n auto",
        )
        assert orphan_reaper.select_orphan_pids(ps) == []

    def test_non_integer_pid_line_is_skipped(self) -> None:
        ps = _ps("notapid     1    99:00 python -m pytest -n auto")
        assert orphan_reaper.select_orphan_pids(ps) == []

    def test_header_only_output_selects_nothing(self) -> None:
        assert orphan_reaper.select_orphan_pids(_ps()) == []

    def test_mixed_snapshot_selects_only_the_orphan(self) -> None:
        ps = _ps(
            "100  4242    50:00 python -m pytest -n auto tests/",  # live parent
            "200     1    50:00 python -m pytest -n auto tests/",  # orphan -> pick
            "300     1    00:05 python -m pytest -n auto tests/",  # too young
            "400     1    50:00 /usr/sbin/sshd",  # not pytest
        )
        assert orphan_reaper.select_orphan_pids(ps) == [200]


class TestReapOrphans:
    def test_signals_only_reapable_pids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        killed: list[int] = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(pid))
        # 1 (init) and 0 are unsafe and must be filtered before any kill.
        result = orphan_reaper.reap_orphans([12345, 1, 0, 67890])
        assert killed == [12345, 67890]
        assert result == [12345, 67890]

    def test_process_lookup_error_is_tolerated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(pid: int, sig: int) -> None:
            raise ProcessLookupError

        monkeypatch.setattr(os, "kill", _raise)
        assert orphan_reaper.reap_orphans([12345]) == []  # already gone, no crash

    def test_empty_list_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = False

        def _kill(pid: int, sig: int) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(os, "kill", _kill)
        assert orphan_reaper.reap_orphans([]) == []
        assert called is False


class TestEnumerateProcesses:
    def test_returns_real_ps_output(self) -> None:
        # A real, read-only ps snapshot — safe, no mutation.
        out = orphan_reaper.enumerate_processes()
        assert out is not None
        assert "PID" in out.splitlines()[0].upper()
