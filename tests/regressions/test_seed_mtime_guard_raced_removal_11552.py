"""Regression pins: the seed teardown guard tolerates a raced removal (#11552).

``tests/conftest.py::_sandbox_seed_mtimes`` discovers committed sandbox seeds
with ``glob()`` and then ``stat()``s each hit. Under ``-n auto --forked`` a
DIFFERENT worker can remove a transient seed between those two calls —
``regression_issue_10094.py`` materializes and deletes the seedless
``s75_worker_stall_escalation.json`` (plus a ``scenario.json`` symlink) in the
real seeds dir — so the guard raised ``FileNotFoundError`` straight out of
``pytest_runtest_teardown`` and reddened unrelated green PRs (#11484 job
96368069089, #11550 job 96726836845).

The fix tolerates ONLY a path disappearing after discovery. Everything the
guard exists for is pinned here too: a committed seed whose content a test
really changed is still reported (even while a sibling races), and any
``stat()`` failure other than the disappearance still propagates.
"""

from __future__ import annotations

import errno
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.conftest import _mutated_committed_seeds, _sandbox_seed_mtimes

_RACED = "s75_worker_stall_escalation.json"
_COMMITTED = "s01_happy_single_issue.json"


def _race_stat(monkeypatch: pytest.MonkeyPatch, name: str, exc: OSError) -> None:
    """Make ``Path.stat`` raise *exc* for the file called *name* only.

    Simulates another worker unlinking that path between ``glob()`` (which
    already yielded it) and the guard's ``stat()`` call.
    """
    real_stat = Path.stat

    def racing_stat(self: Path, *args: object, **kwargs: object):
        if self.name == name:
            raise exc
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", racing_stat)


def _write_seeds(seeds_dir: Path) -> None:
    seeds_dir.mkdir(parents=True, exist_ok=True)
    (seeds_dir / _COMMITTED).write_text('{"a": 1}', encoding="utf-8")
    (seeds_dir / _RACED).write_text('{"b": 2}', encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def committed_seeds_repo(tmp_path: Path) -> Path:
    """A throwaway git repo whose ``seeds/`` dir holds two committed seeds."""
    repo = tmp_path / "repo"
    seeds = repo / "seeds"
    _write_seeds(seeds)
    _git(repo, "init", "-q")
    _git(repo, "add", "seeds")
    _git(repo, "commit", "-q", "-m", "seeds")
    return seeds


class TestRacedRemovalIsTolerated:
    def test_seed_removed_between_glob_and_stat_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeds = tmp_path / "seeds"
        _write_seeds(seeds)
        _race_stat(
            monkeypatch, _RACED, FileNotFoundError(errno.ENOENT, "raced", _RACED)
        )

        snapshot = _sandbox_seed_mtimes(seeds_dir=seeds)

        assert _COMMITTED in snapshot
        assert _RACED not in snapshot

    def test_teardown_comparison_ignores_the_raced_seed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeds = tmp_path / "seeds"
        _write_seeds(seeds)
        before = _sandbox_seed_mtimes(seeds_dir=seeds)
        _race_stat(
            monkeypatch, _RACED, FileNotFoundError(errno.ENOENT, "raced", _RACED)
        )

        assert _mutated_committed_seeds(before, seeds_dir=seeds) == []

    def test_concurrent_churn_of_a_transient_seed_never_raises(
        self, tmp_path: Path
    ) -> None:
        """A real interleaving: one thread creates/unlinks while we snapshot."""
        seeds = tmp_path / "seeds"
        _write_seeds(seeds)
        transient = seeds / "scenario.json"
        stop = threading.Event()

        def churn() -> None:
            while not stop.is_set():
                transient.write_text("{}", encoding="utf-8")
                transient.unlink()

        worker = threading.Thread(target=churn, daemon=True)
        worker.start()
        deadline = time.monotonic() + 0.5
        try:
            while time.monotonic() < deadline:
                snapshot = _sandbox_seed_mtimes(seeds_dir=seeds)
                assert _COMMITTED in snapshot
        finally:
            stop.set()
            worker.join(timeout=5)


class TestGuardStillFailsLoud:
    def test_other_stat_errors_still_propagate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeds = tmp_path / "seeds"
        _write_seeds(seeds)
        _race_stat(monkeypatch, _RACED, PermissionError(errno.EACCES, "denied", _RACED))

        with pytest.raises(PermissionError):
            _sandbox_seed_mtimes(seeds_dir=seeds)

    def test_untouched_committed_seeds_report_nothing(
        self, committed_seeds_repo: Path
    ) -> None:
        before = _sandbox_seed_mtimes(seeds_dir=committed_seeds_repo)

        assert _mutated_committed_seeds(before, seeds_dir=committed_seeds_repo) == []

    def test_modified_committed_seed_is_reported_while_a_sibling_races(
        self, committed_seeds_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = _sandbox_seed_mtimes(seeds_dir=committed_seeds_repo)
        mutated = committed_seeds_repo / _COMMITTED
        mutated.write_text('{"a": 1, "comments": {}}', encoding="utf-8")
        # Force a visible mtime change even on coarse-grained filesystems.
        bumped = before[_COMMITTED] + 1_000_000_000
        os.utime(mutated, ns=(bumped, bumped))
        _race_stat(
            monkeypatch, _RACED, FileNotFoundError(errno.ENOENT, "raced", _RACED)
        )

        assert _mutated_committed_seeds(before, seeds_dir=committed_seeds_repo) == [
            _COMMITTED
        ]
