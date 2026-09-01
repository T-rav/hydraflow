"""A configured GC root that discovery can never produce a candidate from.

`WorkspaceGCLoop` phase 5 enumerates with `git worktree list` run at
`config.repo_root`, so it sees the worktrees of exactly one repository. The
configured roots are host-wide paths. When the running instance's repo is not
the repo that owns a root's contents — a factory workspace sweeping roots that
hold the *dev* checkout's worktrees — that root yields nothing, forever.

Nothing said so. A root holding 10 stale directories logged identically to a
clean one, which is how 14 GB accumulated unremarked and why #11908's
diagnosis landed on the wrong function (#11931).

The reach is deliberately NOT widened here: cross-repo enumeration would hand
a background loop authority to delete inside a human's working checkout, and
`config.worktree_gc_root_paths` documents single-repo enumeration as the
blast-radius guard that makes the broad root list safe. Only the silence is
fixed.
"""

from __future__ import annotations

from pathlib import Path

from workspace_gc_landed_safety import UnenumerableRoot, unenumerable_roots


def _dirs(root: Path, *names: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).mkdir()
    return root


class TestTheRootIsReported:
    """The case the warning exists for."""

    def test_a_root_holding_directories_yields_none_of_them(self, tmp_path):
        root = _dirs(tmp_path / "worktrees", "wtA", "wtB", "wtC")

        assert unenumerable_roots([], [root]) == [UnenumerableRoot(root, 3)]

    def test_the_count_is_the_directories_a_reader_would_find(self, tmp_path):
        root = _dirs(tmp_path / "worktrees", "one", "two")

        (reported,) = unenumerable_roots([], [root])

        assert reported.directories == 2

    def test_other_repos_worktrees_are_invisible_not_absent(self, tmp_path):
        # The real shape: enumeration produced worktrees, but all of them live
        # under a DIFFERENT root, so this one contributed nothing.
        mine = tmp_path / "factory" / "wt1"
        theirs = _dirs(tmp_path / "manual-repairs", "repair-a", "repair-b")

        reported = unenumerable_roots([mine], [tmp_path / "factory", theirs])

        assert reported == [UnenumerableRoot(theirs, 2)]


class TestTheDecoys:
    """Each of these looks like the target and must stay silent.

    Without them the check passes by warning about everything, which is the
    same silence inverted: a warning on every root is a warning on none.
    """

    def test_an_empty_root_is_not_reported(self, tmp_path):
        root = _dirs(tmp_path / "worktrees")

        assert unenumerable_roots([], [root]) == []

    def test_a_root_that_contributed_a_worktree_is_not_reported(self, tmp_path):
        root = _dirs(tmp_path / "worktrees", "live", "also-live")

        assert unenumerable_roots([root / "live"], [root]) == []

    def test_contributing_one_worktree_excuses_the_whole_root(self, tmp_path):
        # A root is reachable or it is not. One enumerable worktree proves
        # reachability; the other directories are the reaper's business, not
        # this check's, and reporting them would drown the real signal.
        root = _dirs(tmp_path / "worktrees", "live", "stale1", "stale2")

        assert unenumerable_roots([root / "live"], [root]) == []

    def test_a_root_that_does_not_exist_is_not_reported(self, tmp_path):
        # Configured-but-absent roots are normal and say nothing.
        assert unenumerable_roots([], [tmp_path / "never-created"]) == []

    def test_a_root_holding_only_files_is_not_reported(self, tmp_path):
        root = tmp_path / "worktrees"
        root.mkdir()
        (root / "notes.txt").write_text("x", encoding="utf-8")

        assert unenumerable_roots([], [root]) == []

    def test_a_root_that_is_a_file_is_not_reported(self, tmp_path):
        target = tmp_path / "not-a-dir"
        target.write_text("x", encoding="utf-8")

        assert unenumerable_roots([], [target]) == []

    def test_a_root_containing_the_worktree_as_a_descendant_counts(self, tmp_path):
        # `repo_root.parent` is a configured root and the primary worktree is
        # nested under it, not equal to it. Treating only direct children as
        # contributions would report the checkout's own parent every cycle.
        root = _dirs(tmp_path / "projects", "hydraflow")

        assert unenumerable_roots([root / "hydraflow" / "nested"], [root]) == []


class TestTheRootIsTheRootItself:
    def test_a_root_equal_to_an_enumerated_worktree_is_not_reported(self, tmp_path):
        root = _dirs(tmp_path / "repo", "sub")

        assert unenumerable_roots([root], [root]) == []
