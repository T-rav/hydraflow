"""#11931 — worktrees living in another clone were invisible at any width.

`WorkspaceGCLoop` phase 5 enumerates with `git worktree list` run at
`config.repo_root`, so it sees exactly one repository's worktrees, while the
configured roots are host-wide paths. A root whose contents belong to a
different clone therefore yielded nothing on every cycle — not because the
predicate was too narrow, but because discovery never produced a candidate for
it to judge.

The boundary is the PROJECT, not the checkout: every clone of this repository,
wherever it lives; nothing belonging to another. `repo_root.parent` is a
configured root and on a developer machine that directory holds dozens of
unrelated projects, so discovering repos without the remote filter would turn
one project's collector into a collector for everything the operator owns —
which no amount of per-candidate proof makes acceptable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workspace_gc_landed_safety import (
    child_directories,
    normalized_remote,
    repo_root_from_common_dir,
)


class TestFindingTheOwningClone:
    def test_an_absolute_common_dir_resolves_to_the_main_repo(
        self, tmp_path: Path
    ) -> None:
        # What `--git-common-dir` returns from inside a LINKED worktree, and
        # the reason it is used instead of `--show-toplevel`: that would return
        # the linked worktree and send enumeration back where it started.
        main = tmp_path / "main"
        (main / ".git").mkdir(parents=True)

        assert (
            repo_root_from_common_dir(f"{main / '.git'}\n", cwd=tmp_path / "elsewhere")
            == main.resolve()
        )

    def test_a_relative_common_dir_is_resolved_against_the_checkout(
        self, tmp_path: Path
    ) -> None:
        # What it returns when run in the main repo itself: a bare `.git`.
        main = tmp_path / "main"
        (main / ".git").mkdir(parents=True)

        assert repo_root_from_common_dir(".git\n", cwd=main) == main.resolve()

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("", id="empty"),
            pytest.param("   \n", id="whitespace"),
            pytest.param("/some/bare-repo.git\n", id="not-a-dot-git-dir"),
        ],
    )
    def test_output_that_names_no_working_tree_owns_nothing(
        self, output: str, tmp_path: Path
    ) -> None:
        assert repo_root_from_common_dir(output, cwd=tmp_path) is None


class TestTheProjectBoundary:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            pytest.param(
                "https://github.com/o/r.git",
                "git@github.com:o/r.git",
                id="ssh-vs-https",
            ),
            pytest.param(
                "https://github.com/o/r", "https://github.com/o/r.git/", id="suffix"
            ),
            pytest.param(
                "https://user@github.com/o/r.git",
                "https://github.com/o/r",
                id="credential-in-url",
            ),
            pytest.param(
                "https://GitHub.com/O/R.git", "https://github.com/o/r", id="case"
            ),
        ],
    )
    def test_two_spellings_of_one_project_are_siblings(self, a: str, b: str) -> None:
        assert normalized_remote(a) == normalized_remote(b)

    def test_two_projects_are_never_siblings(self) -> None:
        # The decoy that matters: a normalizer aggressive enough to collapse
        # these would hand the collector every repo the operator owns.
        assert normalized_remote("https://github.com/o/r.git") != normalized_remote(
            "https://github.com/o/other.git"
        )

    def test_a_clone_with_no_remote_is_not_a_sibling(self) -> None:
        # Skipped, not proven safe. An unattributable checkout is exactly the
        # case where "probably ours" is the wrong answer.
        assert normalized_remote("") == ""


class TestTheScanIsShallow:
    def test_direct_children_are_returned(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        (root / "a").mkdir(parents=True)
        (root / "b").mkdir()

        found = child_directories([root])

        assert {p.name for p in found} == {"a", "b"}

    def test_it_does_not_descend_into_a_worktrees_own_contents(
        self, tmp_path: Path
    ) -> None:
        # A checkout nested inside somebody's worktree is their business. A
        # recursive walk would also be slow on a root like `repo_root.parent`.
        root = tmp_path / "roots"
        (root / "a" / "nested" / "deeper").mkdir(parents=True)

        found = child_directories([root])

        assert [p.name for p in found] == ["a"]

    def test_files_are_not_candidates(self, tmp_path: Path) -> None:
        root = tmp_path / "roots"
        root.mkdir()
        (root / "notes.txt").write_text("x", encoding="utf-8")

        assert child_directories([root]) == []

    def test_a_missing_root_contributes_nothing(self, tmp_path: Path) -> None:
        assert child_directories([tmp_path / "never-created"]) == []

    def test_the_same_directory_reached_by_two_roots_appears_once(
        self, tmp_path: Path
    ) -> None:
        # `repo_root` and `repo_root.parent` are both configured roots, so
        # overlapping roots are the normal case, not an edge one.
        root = tmp_path / "roots"
        (root / "a").mkdir(parents=True)

        assert len(child_directories([root, root])) == 1


class TestTheLoopActuallyEnumeratesThem:
    """The wiring, not just the helpers.

    Pinning the pure functions alone would leave the call site unguarded — the
    failure mode is that discovery never produces a candidate, which is
    invisible from inside a helper that was never called.
    """

    @staticmethod
    def _dispatch(
        *, remotes: dict[str, str], listings: dict[str, str], owners: dict[str, str]
    ):
        from unittest.mock import AsyncMock

        async def _fn(*cmd: str, cwd: object = None, **_kw: object) -> str:
            key = str(Path(str(cwd)).resolve())
            if cmd[:3] == ("git", "remote", "get-url"):
                if key not in remotes:
                    raise RuntimeError(f"no remote for {key}")
                return remotes[key]
            if cmd[:3] == ("git", "rev-parse", "--git-common-dir"):
                if key not in owners:
                    raise RuntimeError(f"not a checkout: {key}")
                return owners[key]
            if cmd[:3] == ("git", "worktree", "list"):
                if key not in listings:
                    raise RuntimeError(f"cannot enumerate {key}")
                return listings[key]
            return ""

        return AsyncMock(side_effect=_fn)

    @pytest.mark.asyncio
    async def test_a_sibling_clones_worktree_becomes_visible(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from tests.test_workspace_gc_loop import _make_loop

        root = tmp_path / "roots"
        sibling = root / "other-clone"
        (sibling / ".git").mkdir(parents=True)
        theirs = sibling / "wt"
        theirs.mkdir()

        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        primary = str(loop._config.repo_root.expanduser().resolve())
        dispatch = self._dispatch(
            remotes={
                primary: "https://github.com/o/r.git\n",
                str(sibling.resolve()): "git@github.com:o/r.git\n",
            },
            owners={str(sibling.resolve()): f"{sibling / '.git'}\n"},
            listings={
                primary: f"worktree {primary}\nHEAD {'a' * 40}\nbranch refs/heads/main\n",
                str(sibling.resolve()): (
                    f"worktree {theirs}\nHEAD {'b' * 40}\nbranch refs/heads/fix/x-1\n"
                ),
            },
        )

        with patch("workspace_gc_loop.run_subprocess", dispatch):
            entries = await loop._list_git_worktrees()

        assert theirs.resolve() in {e.path for e in entries}

    @pytest.mark.asyncio
    async def test_another_projects_worktree_stays_invisible(
        self, tmp_path: Path
    ) -> None:
        # The decoy. `repo_root.parent` is a configured root, so without the
        # remote filter this is every project on the machine.
        from unittest.mock import patch

        from tests.test_workspace_gc_loop import _make_loop

        root = tmp_path / "roots"
        stranger = root / "someone-elses-project"
        (stranger / ".git").mkdir(parents=True)
        theirs = stranger / "wt"
        theirs.mkdir()

        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        primary = str(loop._config.repo_root.expanduser().resolve())
        dispatch = self._dispatch(
            remotes={
                primary: "https://github.com/o/r.git\n",
                str(stranger.resolve()): "https://github.com/o/UNRELATED.git\n",
            },
            owners={str(stranger.resolve()): f"{stranger / '.git'}\n"},
            listings={
                primary: f"worktree {primary}\nHEAD {'a' * 40}\nbranch refs/heads/main\n",
                str(stranger.resolve()): (
                    f"worktree {theirs}\nHEAD {'b' * 40}\nbranch refs/heads/their/work\n"
                ),
            },
        )

        with patch("workspace_gc_loop.run_subprocess", dispatch):
            entries = await loop._list_git_worktrees()

        assert theirs.resolve() not in {e.path for e in entries}

    @pytest.mark.asyncio
    async def test_the_primary_repos_failure_still_propagates(
        self, tmp_path: Path
    ) -> None:
        """Unchanged contract: a partial picture must not drive a sweep.

        `_collect_orphaned_worktrees` catches this and reaps nothing. A sibling
        clone's failure is different and is skipped — see below — because one
        unreadable checkout must not veto collecting the others.
        """
        from unittest.mock import patch

        from tests.test_workspace_gc_loop import _make_loop

        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(tmp_path / "roots")])
        dispatch = self._dispatch(remotes={}, owners={}, listings={})

        with (
            patch("workspace_gc_loop.run_subprocess", dispatch),
            pytest.raises(RuntimeError),
        ):
            await loop._list_git_worktrees()

    @pytest.mark.asyncio
    async def test_an_unreadable_sibling_does_not_stop_the_others(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from tests.test_workspace_gc_loop import _make_loop

        root = tmp_path / "roots"
        broken, good = root / "broken", root / "good"
        for clone in (broken, good):
            (clone / ".git").mkdir(parents=True)
        theirs = good / "wt"
        theirs.mkdir()

        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        primary = str(loop._config.repo_root.expanduser().resolve())
        ours = "https://github.com/o/r.git\n"
        dispatch = self._dispatch(
            remotes={
                primary: ours,
                str(broken.resolve()): ours,
                str(good.resolve()): ours,
            },
            owners={
                str(broken.resolve()): f"{broken / '.git'}\n",
                str(good.resolve()): f"{good / '.git'}\n",
            },
            listings={
                primary: f"worktree {primary}\nHEAD {'a' * 40}\nbranch refs/heads/main\n",
                # `broken` deliberately absent -> enumeration raises for it
                str(good.resolve()): (
                    f"worktree {theirs}\nHEAD {'b' * 40}\nbranch refs/heads/fix/x-1\n"
                ),
            },
        )

        with patch("workspace_gc_loop.run_subprocess", dispatch):
            entries = await loop._list_git_worktrees()

        assert theirs.resolve() in {e.path for e in entries}

    @pytest.mark.asyncio
    async def test_the_kill_switch_restores_single_repo_enumeration(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from tests.test_workspace_gc_loop import _make_loop

        root = tmp_path / "roots"
        sibling = root / "other-clone"
        (sibling / ".git").mkdir(parents=True)
        theirs = sibling / "wt"
        theirs.mkdir()

        loop, _s, _e = _make_loop(tmp_path, worktree_gc_roots=[str(root)])
        # The kill switch is a deploy-time setting, not a ConfigFactory kwarg;
        # set it on the built config so this pins the loop's read of it.
        object.__setattr__(loop._config, "worktree_gc_sibling_clones_enabled", False)
        primary = str(loop._config.repo_root.expanduser().resolve())
        dispatch = self._dispatch(
            remotes={primary: "https://github.com/o/r.git\n"},
            owners={str(sibling.resolve()): f"{sibling / '.git'}\n"},
            listings={
                primary: f"worktree {primary}\nHEAD {'a' * 40}\nbranch refs/heads/main\n",
                str(sibling.resolve()): (
                    f"worktree {theirs}\nHEAD {'b' * 40}\nbranch refs/heads/fix/x-1\n"
                ),
            },
        )

        with patch("workspace_gc_loop.run_subprocess", dispatch):
            entries = await loop._list_git_worktrees()

        assert theirs.resolve() not in {e.path for e in entries}
