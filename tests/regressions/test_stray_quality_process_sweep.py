"""Regression: a suite run left over from a previous cycle must be reported.

Measured on the live factory, 2026-08-30 (#11820). A `make quality` spawned by
a factory build survived the factory's own stop and ran for **11h53m** at
`PPID=1`, holding 2.4 GB and driving load average to 25.

The cost was not the CPU. A fresh `make quality` on that host produced **60
failures across dozens of unrelated files** — every one passing standalone,
spread thinly enough (2-3 per file) to read as ordinary flakiness rather than
resource starvation. A defect that fabricates other defects is more expensive
than its own footprint, and it was nearly reported as a regression in an
unrelated change.

Nothing looked. This makes something look, before the new run starts competing
with the old one.
"""

from __future__ import annotations

import pytest

from preflight import (
    STRAY_PROCESS_AGE_SECONDS,
    CheckStatus,
    _check_stray_quality_processes,
    _etime_seconds,
    _stray_process_lines,
)

# The real row, as `ps -eo pid,etime,command` printed it that night.
_ORPHAN_ROW = (
    "  PID     ELAPSED COMMAND\n"
    " 4774    11:53:26 /bin/zsh -c source /Users/x/.claude/shell-snapshots/s.sh "
    "&& eval 'make quality 2>&1 | tail -150'\n"
)


class TestElapsedParsing:
    @pytest.mark.parametrize(
        ("etime", "expected"),
        [
            pytest.param("11:53:26", 42_806, id="hours_minutes_seconds"),
            pytest.param("02:20", 140, id="minutes_seconds"),
            pytest.param("16-03:49:24", 1_396_164, id="days"),
            pytest.param("garbage", 0, id="unparseable_is_zero_not_a_crash"),
        ],
    )
    def test_parses_ps_elapsed(self, etime: str, expected: int) -> None:
        assert _etime_seconds(etime) == expected


class TestStrayDetection:
    def test_the_real_orphan_is_reported(self) -> None:
        stray = _stray_process_lines(
            _ORPHAN_ROW, min_age_seconds=STRAY_PROCESS_AGE_SECONDS
        )
        assert len(stray) == 1
        assert "4774" in stray[0]

    def test_a_live_run_is_not_reported(self) -> None:
        """Anti-vacuity in the other direction: a check that flagged every
        suite run would fire on the operator's own `make quality` and be
        muted within a day."""
        fresh = "  PID     ELAPSED COMMAND\n 5000       02:20 make quality\n"
        assert (
            _stray_process_lines(fresh, min_age_seconds=STRAY_PROCESS_AGE_SECONDS) == []
        )

    def test_unrelated_long_running_processes_are_not_reported(self) -> None:
        """The marker set is deliberately narrow — a broad pattern would name
        an operator's editor and train everyone to ignore the warning."""
        noise = (
            "  PID     ELAPSED COMMAND\n"
            "  323 16-03:49:24 /System/Library/.../fseventsd\n"
            "  400 10:00:00 /Applications/Some.app/Contents/MacOS/Some\n"
        )
        assert (
            _stray_process_lines(noise, min_age_seconds=STRAY_PROCESS_AGE_SECONDS) == []
        )


class TestPreflightCheck:
    def test_reports_warn_and_names_the_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Result:
            returncode = 0
            stdout = _ORPHAN_ROW

        monkeypatch.setattr("preflight.subprocess.run", lambda *a, **k: _Result())
        result = _check_stray_quality_processes(config=None)  # type: ignore[arg-type]

        assert result.status == CheckStatus.WARN
        assert "4774" in result.message
        assert "#11820" in result.message

    def test_a_clean_host_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Result:
            returncode = 0
            stdout = "  PID     ELAPSED COMMAND\n"

        monkeypatch.setattr("preflight.subprocess.run", lambda *a, **k: _Result())
        assert (
            _check_stray_quality_processes(config=None).status  # type: ignore[arg-type]
            == CheckStatus.PASS
        )

    def test_an_unusable_ps_warns_rather_than_crashing_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This runs at factory boot. A diagnostic must never be the thing
        that stops the factory starting."""

        def _boom(*_a: object, **_k: object) -> None:
            raise OSError("no ps")

        monkeypatch.setattr("preflight.subprocess.run", _boom)
        assert (
            _check_stray_quality_processes(config=None).status  # type: ignore[arg-type]
            == CheckStatus.WARN
        )
