"""Regression for #11503 — closed-issue path must not skip the landed check.

``WorkspaceGCLoop._reap_worktree_if_safe`` used to bypass the unmerged-commit
guard entirely whenever the attributed issue's state was ``"closed"``, on the
assumption that a closed issue is authoritatively merged or abandoned. That
assumption is false for an issue closed as not-planned/duplicate/wontfix
while its worktree still holds commits that were never pushed or merged — the
exact #10459/#6413 data-loss invariant the guard exists to protect.

The fix applies one unlanded-work guard uniformly on every path: a worktree
is only reaped when it has no unique commits, OR those commits' CONTENT is
already reflected on ``origin/<base>`` (tolerating squash merges, which
``git rev-list`` ancestry can never see).

These tests run against a REAL git repository (bare remote + local clone +
worktree) — no mocked git — so the fix is proven against actual git
semantics, not a stubbed contract.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from state import StateTracker  # noqa: E402
from tests.helpers import make_bg_loop_deps  # noqa: E402
from workspace_gc_loop import WorkspaceGCLoop  # noqa: E402

_ISSUE = 11503


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """Clone at ``tmp_path / "repo"`` so it matches ``make_bg_loop_deps``'s
    hardcoded ``repo_root``, with an initial commit pushed to ``origin/main``.
    """
    local = tmp_path / "repo"
    _git("clone", str(bare_remote), str(local), cwd=tmp_path)
    _git("checkout", "-b", "main", cwd=local)
    _git("config", "user.email", "t@t", cwd=local)
    _git("config", "user.name", "t", cwd=local)
    (local / "README.md").write_text("init\n")
    _git("add", "README.md", cwd=local)
    _git("commit", "-m", "init", cwd=local)
    _git("push", "-u", "origin", "main", cwd=local)
    return local


def _make_loop(tmp_path: Path) -> WorkspaceGCLoop:
    deps = make_bg_loop_deps(
        tmp_path,
        worktree_gc_min_age_seconds=0,
        staging_enabled=False,  # base_branch() == main_branch == "main"
    )
    workspaces = MagicMock()
    workspaces.destroy = AsyncMock()
    prs = MagicMock()
    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=StateTracker(deps.config.state_file),
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _n: False,
    )
    assert loop._config.base_branch() == "main"
    return loop


class TestClosedIssueStillRequiresLandedWork:
    """#11503: closed-issue attribution must not bypass the landed check."""

    @pytest.mark.asyncio
    async def test_closed_issue_with_unpushed_commit_is_kept(
        self, tmp_path: Path, local_repo: Path
    ) -> None:
        """A closed-as-not-planned issue whose worktree has a real, never
        pushed commit must NOT be reaped — that commit would be lost."""
        wt = tmp_path / "wt-unlanded"
        branch = f"fix/thing-{_ISSUE}"
        _git("worktree", "add", str(wt), "-b", branch, cwd=local_repo)
        (wt / "feature.txt").write_text("work in progress\n")
        _git("add", "feature.txt", cwd=wt)
        _git("commit", "-m", "unpushed work", cwd=wt)
        # Never pushed to origin — the exact data-loss scenario from the issue.

        loop = _make_loop(tmp_path)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]

        reaped = await loop._reap_worktree_if_safe(wt, branch, _ISSUE)

        assert reaped is False
        # The worktree and its unpushed commit must still be on disk.
        assert wt.exists()
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=str(wt),
            check=True,
            capture_output=True,
            text=True,
        )
        assert log.stdout.strip() == "unpushed work"

    @pytest.mark.asyncio
    async def test_closed_issue_with_no_unique_commits_is_reaped(
        self, tmp_path: Path, local_repo: Path
    ) -> None:
        """Sanity check: a closed issue with a worktree that has no unpushed
        work at all is still reaped — the fix must not freeze all collection.
        """
        wt = tmp_path / "wt-clean"
        branch = f"fix/thing-{_ISSUE}"
        _git("worktree", "add", str(wt), "-b", branch, cwd=local_repo)
        # No new commits — worktree is identical to origin/main.

        loop = _make_loop(tmp_path)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]

        reaped = await loop._reap_worktree_if_safe(wt, branch, _ISSUE)

        assert reaped is True
        assert not wt.exists()

    @pytest.mark.asyncio
    async def test_closed_issue_with_squash_merged_content_is_reaped(
        self, tmp_path: Path, local_repo: Path
    ) -> None:
        """A squash-merged branch has unique commits by ANCESTRY (its
        original commit hash never appears in ``origin/main``'s history), but
        its CONTENT is fully landed — the content-based fallback must still
        allow the reap so the fix isn't over-conservative.
        """
        wt = tmp_path / "wt-squashed"
        branch = f"fix/thing-{_ISSUE}"
        _git("worktree", "add", str(wt), "-b", branch, cwd=local_repo)
        (wt / "feature.txt").write_text("squash me\n")
        _git("add", "feature.txt", cwd=wt)
        _git("commit", "-m", "work to be squashed", cwd=wt)

        # Simulate a GitHub squash-merge: apply the same content change
        # directly on main as a NEW commit (different hash from the
        # worktree's commit), then push — origin/main now has the same
        # content, but the worktree's commit is not its ancestor.
        _git("checkout", "main", cwd=local_repo)
        (local_repo / "feature.txt").write_text("squash me\n")
        _git("add", "feature.txt", cwd=local_repo)
        _git("commit", "-m", f"squash-merge #{_ISSUE}", cwd=local_repo)
        _git("push", "origin", "main", cwd=local_repo)

        loop = _make_loop(tmp_path)
        loop._is_safe_to_gc = AsyncMock(return_value=True)  # type: ignore[method-assign]

        # Ancestry still reports the worktree's commit as unmerged.
        assert await loop._worktree_has_unmerged_commits(wt) is True
        # But content has landed via the squash.
        assert await loop._worktree_work_has_landed(wt) is True

        reaped = await loop._reap_worktree_if_safe(wt, branch, _ISSUE)

        assert reaped is True
        assert not wt.exists()
