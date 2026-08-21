"""Regression #11552: sandbox-seed teardown guard races parallel file removal.

Timeline that motivated this: PR #11484 (job 96368069089) failed when
``scenario.json`` disappeared between ``_sandbox_seed_mtimes()``'s ``glob()``
and ``stat()``; PR #11550 (job 96726836845) failed at the same seam while
tearing down ``test_above_threshold_stays_in_pipeline`` after
``s75_worker_stall_escalation.json`` vanished. Neither PR touched the guard
or affected seed ownership.

Root cause — ``tests/conftest.py::_sandbox_seed_mtimes`` snapshots the SHARED
committed seeds dir through a lazy generator:

    {p.name: p.stat().st_mtime_ns for p in _SANDBOX_SEEDS_DIR.glob("*.json")}

``glob`` yields paths one at a time and ``stat()`` runs per item, so anything
that removes or replaces an entry inside that window — another xdist /
``--forked`` worker's own guard pass, or the sandbox harness itself
(``scripts/sandbox_scenario.py::cmd_run`` materializes transient untracked
seeds plus a ``scenario.json`` symlink into this dir and removes them in a
``finally``; see regression_issue_10094.py) — leaves the comprehension calling
``stat()`` on a vanished path. The ``FileNotFoundError`` then propagates out
of ``pytest_runtest_setup`` / ``pytest_runtest_teardown`` and fails an
otherwise-green PR.

Pins (hermetic: every race test redirects ``tests.conftest._SANDBOX_SEEDS_DIR``
to ``tmp_path`` so the real committed dir is never touched):

* literal disappearance — a seed unlinked after ``glob`` discovers it but
  before ``stat()`` reaches it must not raise (RED today: FileNotFoundError).
  The unlink is injected at the exact seam via a Path subclass whose ``glob``
  yields the victim one heartbeat after removing it — the discovered-then-
  vanished interleaving itself is real, only its scheduling is controlled;
* dangling transient symlink — the ``scenario.json`` shape once its target
  seed is removed first must not raise (RED today: FileNotFoundError, because
  ``glob`` yields dangling links and ``stat()`` follows them);
* real interleaving — a concurrent deleter thread racing the snapshot loop
  must not raise (RED today). Both ``stat()`` and ``unlink()`` release the
  GIL, so a thread exercises the same seam a forked sibling process does.

Scope guards (green today, must stay green after the fix):

* content drift on a committed seed still fails loudly through the REAL
  ``pytest_runtest_setup`` / ``pytest_runtest_teardown`` pair (#10094) — the
  fix must not weaken the pollution guard;
* a stat error that is NOT the narrowly-handled disappearance (ELOOP on a
  symlink cycle) still propagates — the fix must catch ``FileNotFoundError``
  only, never a broad ``OSError``.
"""

from __future__ import annotations

import pathlib
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tests import conftest

# Real names from the two blocked PRs, so the pins read like the failures.
_STABLE_GOLDEN = "s01_happy_single_issue.json"
_TRANSIENT_SEED = "s75_worker_stall_escalation.json"  # vanished in PR #11550
_TRANSIENT_LINK = "scenario.json"  # vanished in PR #11484


@contextmanager
def _redirected_seed_dir(target: pathlib.Path) -> Iterator[None]:
    """Point the live guard's module global at *target*; restore on exit.

    Restoring in the ``finally`` (inside the test body) matters: this test's
    OWN ``pytest_runtest_teardown`` guard pass must see the real committed dir
    again by the time it runs.
    """
    saved = conftest._SANDBOX_SEEDS_DIR
    conftest._SANDBOX_SEEDS_DIR = target
    try:
        yield
    finally:
        conftest._SANDBOX_SEEDS_DIR = saved


def _write_seed_files(seeds_dir: pathlib.Path, names: list[str]) -> None:
    for name in names:
        (seeds_dir / name).write_text("{}\n")


def test_seed_unlinked_between_glob_and_stat_does_not_raise(
    tmp_path: pathlib.Path,
) -> None:
    """A seed that disappears after discovery must be skipped, not fatal.

    Injects the #11552 interleaving at its exact seam: the victim IS in the
    directory listing ``glob`` walks (it is discovered), and it is unlinked one
    heartbeat before the comprehension's ``stat()`` reaches it — what a
    parallel worker's removal does naturally under xdist/--forked.
    """
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    _write_seed_files(seeds, [_STABLE_GOLDEN, _TRANSIENT_SEED])

    class _RacingSeedsDir(type(seeds)):  # noqa: N818 — a scoped seam, not a type
        """Yields the transient seed immediately AFTER unlinking it."""

        def glob(self, pattern: str):
            unlinked = False
            for p in super().glob(pattern):
                if not unlinked and p.name == _TRANSIENT_SEED:
                    p.unlink()  # the other worker's removal lands right here
                    unlinked = True
                yield p

    racing_dir = _RacingSeedsDir(str(seeds))
    with _redirected_seed_dir(racing_dir):
        result = conftest._sandbox_seed_mtimes()

    assert _STABLE_GOLDEN in result, "guard must still snapshot surviving seeds"
    assert _TRANSIENT_SEED not in result, (
        "a seed that vanished between glob() and stat() must be absent from "
        "the snapshot, not raise FileNotFoundError through teardown (#11552)"
    )


def test_dangling_transient_symlink_does_not_raise(tmp_path: pathlib.Path) -> None:
    """A ``scenario.json`` left dangling mid-cleanup must not crash the guard.

    ``cmd_run`` symlinks ``scenario.json`` -> ``<seed>.json`` and its
    ``_cleanup_run_seed`` removes both; whenever the target goes first (or the
    symlink outlives its seed by a beat) ``glob`` still yields the link while
    ``stat()`` — which follows symlinks — finds nothing. This is the exact
    PR #11484 shape, reproduced with no scheduling control needed at all.
    """
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    _write_seed_files(seeds, [_STABLE_GOLDEN])
    (seeds / _TRANSIENT_LINK).symlink_to(_TRANSIENT_SEED)  # target never exists

    with _redirected_seed_dir(seeds):
        result = conftest._sandbox_seed_mtimes()

    assert _STABLE_GOLDEN in result, "guard must still snapshot surviving seeds"
    assert _TRANSIENT_LINK not in result, (
        "a dangling transient symlink must be skipped, not raise "
        "FileNotFoundError through teardown (#11552)"
    )


def test_concurrent_removal_during_snapshot_does_not_raise(
    tmp_path: pathlib.Path,
) -> None:
    """Real interleaving: a concurrent deleter racing the snapshot loop.

    A deleter thread removes the round's transient seeds (with a head start,
    like a sibling worker already inside its cleanup ``finally``) while the
    main thread snapshots the same directory — the genuine glob-then-stat
    window, no injection. ``stat()`` and ``unlink()`` both release the GIL, so
    threads interleave this seam exactly as forked sibling processes do in CI.
    """
    rounds = 25
    files_per_round = 400
    head_start = 25  # deletions the racing actor completes before we snapshot
    raced_at: tuple[int, str] | None = None
    total_snapshotted = 0

    for rnd in range(rounds):
        seeds = tmp_path / f"seeds_{rnd:02d}"
        seeds.mkdir()
        paths = [seeds / f"race_{rnd:02d}_{i:04d}.json" for i in range(files_per_round)]
        for p in paths:
            p.write_text("{}\n")

        go = threading.Event()

        def deleter() -> None:
            for i, p in enumerate(paths):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass  # main thread's snapshot consumed nothing; keep going
                if i + 1 == head_start:
                    go.set()
            go.set()

        actor = threading.Thread(target=deleter, daemon=True)
        actor.start()
        go.wait()  # the removals are already in flight — now snapshot

        with _redirected_seed_dir(seeds):
            try:
                snapshot = conftest._sandbox_seed_mtimes()
            except FileNotFoundError as exc:
                raced_at = (rnd, str(exc))
                actor.join()
                break
            total_snapshotted += len(snapshot)
        actor.join()
        shutil.rmtree(seeds, ignore_errors=True)

    assert raced_at is None, (
        f"#11552 reproduced in round {raced_at[0]}: _sandbox_seed_mtimes() "
        f"raised FileNotFoundError mid-snapshot ({raced_at[1]}) because a "
        "concurrent removal won the glob()->stat() race"
    )
    assert total_snapshotted >= 1, "liveness: surviving seeds were snapshotted"


def test_committed_seed_content_drift_still_fails_loudly() -> None:
    """Scope guard: real content drift on a committed seed must still fail.

    Drives the REAL ``pytest_runtest_setup`` / ``pytest_runtest_teardown``
    hooks (fake item, real Stash + StashKey, real seeds dir) through the exact
    #10094 violation — a test rewriting a committed seed's content — and
    asserts the guard still pins it by name. Whatever #11552's fix does to
    tolerate vanished paths must not weaken this.
    """
    smoke = conftest._SANDBOX_SEEDS_DIR / "_smoke.json"
    original = smoke.read_bytes()
    repo_root = pathlib.Path(conftest.__file__).resolve().parents[2]
    item = SimpleNamespace(
        nodeid="tests/regressions/test_issue_11552.py::liveness-probe",
        config=SimpleNamespace(rootpath=repo_root),
        stash=pytest.Stash(),
    )

    conftest.pytest_runtest_setup(item)  # type: ignore[arg-type]  # real snapshot, fake item
    smoke.write_bytes(original + b"\n")  # content drift — never allowed
    try:
        # pytest.fail's exception class (pytest 9 dropped the pytest.Failed alias)
        with pytest.raises(
            pytest.fail.Exception, match="Sandbox-seed tree-clean violation"
        ):
            conftest.pytest_runtest_teardown(item, None)  # type: ignore[arg-type]
    finally:
        # Byte-exact restore: content returns to committed state, so only the
        # mtime differs — which the #11016 content-based guard deliberately
        # tolerates (git stays clean).
        smoke.write_bytes(original)


def test_unexpected_stat_error_still_propagates(tmp_path: pathlib.Path) -> None:
    """Scope guard: stat errors other than disappearance must still raise.

    A symlink cycle makes ``stat()`` fail with ELOOP — an ``OSError`` that is
    NOT ``FileNotFoundError``. The #11552 fix must tolerate only the narrow
    raced-path disappearance; anything broader would silently mask real
    filesystem corruption during teardown.
    """
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "loop_a.json").symlink_to("loop_b.json")
    (seeds / "loop_b.json").symlink_to("loop_a.json")

    with _redirected_seed_dir(seeds), pytest.raises(OSError) as excinfo:
        conftest._sandbox_seed_mtimes()

    assert not isinstance(excinfo.value, FileNotFoundError), (
        "ELOOP is not the raced disappearance — it must propagate, so the "
        "fix cannot catch a broad OSError (#11552 acceptance criteria)"
    )
