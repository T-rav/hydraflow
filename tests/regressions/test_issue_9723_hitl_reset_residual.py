"""Regression: HITL reset runbook residuals — Fix J (#9723).

Two manual runbook steps are automated; these pins hold them.

1. Main-repo ``core.worktree`` heal. A docker factory run can write
   ``core.worktree=/workspace`` into the MAIN checkout's ``.git/config``
   (not just a worktree's — that was WS-8). Every host-side git command
   then dies with "fatal: Invalid path '/workspace'" — including
   ``sanitize_repo``'s own fetch — so the factory could not start until an
   operator ran the documented out-of-repo ``git config --unset``.
   ``sanitize_repo`` now heals this before its first git call, behind a
   fail-safe predicate: only a ``core.worktree`` that resolves OUTSIDE the
   checkout root is ever unset. A value resolving to the root itself is a
   legitimately-configured worktree checkout and must never be touched.

2. Attempt-counter close-to-clear. ``issue_attempts``, review attempts
   (inside ``convergence_ledgers`` stage state), and
   ``hitl_summary_failures`` survived issue close, so a reopened or
   re-filed issue inherited a burned attempt budget. The StaleIssueGC
   state prune (#9905) now also sweeps ``hitl_summary_failures``; the
   pins below hold the close-to-clear contract for all three counters —
   and that counters for still-open issues are never cleared.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import ConvergenceLedger, StageRecord
from state import StateTracker
from tests.helpers import ConfigFactory
from workspace import WorkspaceManager

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, **_GIT_ENV}
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _make_repo(base: Path, name: str, branch: str) -> Path:
    repo = base / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", branch)
    (repo / "README.md").write_text("# Test\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


class TestMainRepoCoreWorktreeHeal:
    """Pin 1: ``sanitize_repo`` heals main-checkout ``core.worktree``
    corruption, and only ever unsets a value pointing outside the root."""

    def _make_cloned_manager(self, tmp_path: Path) -> tuple[WorkspaceManager, Path]:
        """A WorkspaceManager over a clone of a local origin.

        The origin's branch matches ``config.base_branch()`` so
        ``sanitize_repo``'s fetch succeeds offline.
        """
        clone = tmp_path / "repo"
        config = ConfigFactory.create(
            repo_root=clone,
            workspace_base=tmp_path / "worktrees",
            execution_mode="host",
        )
        origin = _make_repo(tmp_path, "origin", config.base_branch())
        env = {**os.environ, **_GIT_ENV}
        subprocess.run(
            ["git", "clone", str(origin), str(clone)],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return WorkspaceManager(config), clone

    @pytest.mark.asyncio
    async def test_sanitize_repo_heals_corrupt_main_checkout(
        self, tmp_path: Path
    ) -> None:
        """The runbook residual: a container path in the MAIN checkout's
        config must be healed by sanitize_repo, not left for an operator."""
        mgr, clone = self._make_cloned_manager(tmp_path)
        config_file = clone / ".git" / "config"
        _git(clone, "config", "core.worktree", "/nonexistent/workspace")
        # Pre-condition: the corruption breaks host git in the main checkout.
        broken = subprocess.run(
            ["git", "status", "--porcelain"],
            check=False,
            cwd=clone,
            capture_output=True,
            text=True,
        )
        assert broken.returncode != 0

        await mgr.sanitize_repo()

        assert "/nonexistent/workspace" not in config_file.read_text()
        assert _git(clone, "status", "--porcelain") == ""

    @pytest.mark.asyncio
    async def test_sanitize_repo_leaves_legitimate_core_worktree(
        self, tmp_path: Path
    ) -> None:
        """Fail-safe predicate: a core.worktree resolving to the checkout
        root is a legitimately-configured worktree — never unset."""
        mgr, clone = self._make_cloned_manager(tmp_path)
        _git(clone, "config", "core.worktree", str(clone))

        await mgr.sanitize_repo()

        assert _git(clone, "config", "--get", "core.worktree") == str(clone)
        assert _git(clone, "status", "--porcelain") == ""


class TestAttemptCounterCloseToClear:
    """Pin 2: closing an issue clears its attempt counters via the
    StaleIssueGC state prune; open issues keep theirs."""

    def _tracker(self, tmp_path: Path) -> StateTracker:
        tracker = StateTracker(tmp_path / "state.json")
        tracker._data.issue_attempts = {"100": 2, "999": 3}
        open_ledger = ConvergenceLedger(issue_number=100)
        open_ledger.stage_state["review"] = StageRecord(attempts=1)
        closed_ledger = ConvergenceLedger(issue_number=999)
        closed_ledger.stage_state["review"] = StageRecord(attempts=2)
        tracker._data.convergence_ledgers = {"100": open_ledger, "999": closed_ledger}
        tracker.set_hitl_summary_failure(100, "summary llm failed")
        tracker.set_hitl_summary_failure(999, "summary llm failed")
        return tracker

    def test_closed_issue_attempt_counters_are_cleared(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100})

        assert removed["hitl_summary_failures"] == 1
        assert set(tracker._data.hitl_summary_failures) == {"100"}
        # issue_attempts + review attempts (ledger) follow the same contract.
        assert set(tracker._data.issue_attempts) == {"100"}
        assert set(tracker._data.convergence_ledgers) == {"100"}

    def test_open_issue_counters_survive_sweep(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100, 999})

        assert removed == {}
        assert set(tracker._data.hitl_summary_failures) == {"100", "999"}
        assert set(tracker._data.issue_attempts) == {"100", "999"}
        assert set(tracker._data.convergence_ledgers) == {"100", "999"}

    def test_cleared_counters_persist_to_disk(self, tmp_path: Path) -> None:
        """A reopened issue must see fresh budget even across a restart."""
        tracker = self._tracker(tmp_path)
        tracker.save()

        tracker.prune_issue_scoped_state({100})

        reloaded = StateTracker(tmp_path / "state.json")
        assert set(reloaded._data.hitl_summary_failures) == {"100"}
        assert set(reloaded._data.issue_attempts) == {"100"}
