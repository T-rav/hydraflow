"""A configured root that enumeration cannot reach says so (#11931).

`WorkspaceGCLoop` Phase 5 enumerates with `git worktree list` run at
`config.repo_root`. That is single-repo **by design** — it is the blast-radius
property that lets the roots list name `repo_root.parent` without handing a
background loop authority to delete inside repositories it was never pointed
at. This does not widen it and must never be "fixed" by making discovery
cross-repo.

The defect is reporting. Measured on the running instance: five of seven
configured roots enumerated ZERO worktrees while holding thirteen directories,
and a root that is configured, exists, and holds directories but can never
produce a candidate is indistinguishable in the logs from one that is clean.

That is the recurring class — a check that reports "nothing found" when it
means "I could not look". 26 worktrees reached 14 GB with no signal (#11908),
and the diagnosis that followed landed on the wrong function as a direct
result: it blamed the orphan scan's `issue-*` predicate, which was never the
constraint.

The decoy matters as much as the finding. Most roots are legitimately empty
most of the time, so warning on "enumerated zero" alone would train an
operator to ignore the warning — the same outcome as not emitting it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from workspace_gc_roots import describe_unenumerable, unenumerable_roots

_A, _B, _C = Path("/roots/a"), Path("/roots/b"), Path("/roots/c")


def _counts(mapping: dict[Path, int]):
    return lambda root: mapping.get(root, 0)


def test_a_root_with_dirs_and_no_enumerable_worktrees_is_reported() -> None:
    """The measured shape: directories present, discovery blind to them."""
    findings = unenumerable_roots(
        [_A, _B], [Path("/roots/a/wt")], dir_count=_counts({_B: 3})
    )

    assert findings == [(_B, 3)]
    assert "3 dirs" in describe_unenumerable(findings)


def test_a_genuinely_empty_root_is_silent() -> None:
    """The decoy. Without it the warning fires on every idle root and is tuned out."""
    assert unenumerable_roots([_C], [], dir_count=_counts({_C: 0})) == []


def test_a_root_that_enumerates_is_silent_even_with_many_dirs() -> None:
    """Enumeration reaching the root is the whole question.

    A root holding twenty directories of which discovery sees one is working
    correctly — the other nineteen are non-worktree directories, which is
    normal and not a finding.
    """
    findings = unenumerable_roots(
        [_A], [Path("/roots/a/wt")], dir_count=_counts({_A: 20})
    )
    assert findings == []


def test_an_unreadable_root_does_not_manufacture_a_finding() -> None:
    """A stat failure must not become a warning about a root nobody can see into.

    Reporting is the whole purpose here, so an error in the reporting path
    inventing a report would be the defect this guards against, one level up.
    """

    def _raises(root: Path) -> int:  # noqa: ARG001
        raise OSError("permission denied")

    with pytest.raises(OSError, match="permission denied"):
        unenumerable_roots([_A], [], dir_count=_raises)


def test_the_loop_publishes_the_finding_not_only_logs_it() -> None:
    """Wiring, by reference: a log line only reaches whoever greps for it.

    Read from the loop's SOURCE because the failure being guarded is "the
    reporting exists but nothing calls it" — the vacuous-wiring shape — and a
    test that mocks the caller cannot observe the caller's absence.
    """
    import inspect

    from workspace_gc_loop import WorkspaceGCLoop

    sweep = inspect.getsource(WorkspaceGCLoop._collect_orphaned_worktrees)
    assert "unenumerable_roots(" in sweep, (
        "the all-root sweep never computes the mismatch — the predicate is "
        "dead code"
    )

    do_work = inspect.getsource(WorkspaceGCLoop._do_work)
    assert '"unenumerable_roots"' in do_work, (
        "the finding never reaches the published cycle result, so it is "
        "invisible to a reader of the running system"
    )


def test_the_finding_is_cleared_between_cycles() -> None:
    """A stale finding is worse than none: it reports a root already fixed.

    The attribute is initialised empty and reassigned (not appended to) on
    every sweep, so an early return publishes nothing rather than last cycle's
    answer.
    """
    import inspect

    from workspace_gc_loop import WorkspaceGCLoop

    src = inspect.getsource(WorkspaceGCLoop)
    assert "self._last_unenumerable: list[tuple[Path, int]] = []" in src
    assert "self._last_unenumerable = unenumerable_roots(" in src, (
        "the finding is accumulated rather than replaced — it would grow "
        "across cycles and keep naming roots that are no longer a problem"
    )
