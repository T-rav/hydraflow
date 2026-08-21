"""MockWorld scenario for the PR auto-rebase actuator (#11595 option 3).

End-to-end over FakeGitHub + a real (tiny) git repo fixture on disk — the
actuator's engine (``auto_pr.refresh_branch_with_arch_regen``) shells out to
real git against ``config.repo_root`` (ephemeral worktree, merge base, regen,
push), so this scenario builds an actual repo with a bare "origin" rather
than seeding FakeGitHub state alone (the same split as
``test_erosion_metrics_scenario.py``: FakeGitHub carries the PR metadata,
real git carries the branch surgery). ``arch.runner --emit`` is intercepted
at the ``run_subprocess`` boundary exactly like
``tests/regressions/test_issue_10167_archmeta_heal_pin.py``.

Proves through a full ``MergeStateWatcherLoop._do_work`` tick:

* staging advances → the factory's own PR is reported CONFLICTING → the
  actuator merges base + regenerates the generated artifact + pushes → the
  PR's remote head is updated (CI would re-dispatch) and no HITL escalation;
* a seeded SOURCE-file conflict → the merge is aborted, the remote head is
  untouched, one comment is surfaced, and the PR escalates to HITL;
* a second tick at the same staging head does not re-attempt (dedup).

Why MockWorld is the proof (not sandbox s70): the sandbox world models PR
dirtiness through FakeGitHub only — its ``update_pr_branch`` succeeds, and
there is no real git repo behind the seeded PR branches for the local
merge+regen engine to operate on. s70 keeps covering the cheap update-branch
lane; the engine lane needs the real-git fixture that only exists here.
"""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_PR = 11583
_ISSUE = 11500
_BRANCH = f"agent/issue-{_ISSUE}"
_BASE = "staging"


# --- real tiny git repo (10167 fixture pattern) ------------------------------


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.name", "t"], check=True)
    (local / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(local), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "main"], check=True
    )
    return local


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _seed_generated_conflict(local_repo: Path) -> None:
    """Base advance + factory branch that conflict ONLY on a generated file."""
    gen = local_repo / "docs" / "arch" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "x.md").write_text("seed v0\n")
    _git(local_repo, "add", "-A")
    _git(local_repo, "commit", "-m", "seed generated artifact")
    _git(local_repo, "push", "origin", "main")

    _git(local_repo, "checkout", "-b", _BASE)
    (gen / "x.md").write_text("STAGING ADVANCED\n")
    _git(local_repo, "add", "-A")
    _git(local_repo, "commit", "-m", "staging advances the artifact")
    _git(local_repo, "push", "-u", "origin", _BASE)

    _git(local_repo, "checkout", "-b", _BRANCH, "main")
    (gen / "x.md").write_text("FACTORY PR STALE COPY\n")
    _git(local_repo, "add", "-A")
    _git(local_repo, "commit", "-m", "factory PR carries a stale artifact")
    _git(local_repo, "push", "-u", "origin", _BRANCH)
    _git(local_repo, "checkout", "main")


def _seed_source_conflict(local_repo: Path) -> None:
    """Base advance + factory branch that conflict on a SOURCE file."""
    (local_repo / "src").mkdir(exist_ok=True)
    (local_repo / "src" / "app.py").write_text("VALUE = 0\n")
    _git(local_repo, "add", "-A")
    _git(local_repo, "commit", "-m", "seed source file")
    _git(local_repo, "push", "origin", "main")

    _git(local_repo, "checkout", "-b", _BASE)
    (local_repo / "src" / "app.py").write_text("VALUE = 1\n")
    _git(local_repo, "add", "-A")
    _git(local_repo, "commit", "-m", "staging edits the source")
    _git(local_repo, "push", "-u", "origin", _BASE)

    _git(local_repo, "checkout", "-b", _BRANCH, "main")
    (local_repo / "src" / "app.py").write_text("VALUE = 2\n")
    _git(local_repo, "add", "-A")
    _git(local_repo, "commit", "-m", "factory PR edits the source differently")
    _git(local_repo, "push", "-u", "origin", _BRANCH)
    _git(local_repo, "checkout", "main")


def _regen_stub() -> Callable[..., Awaitable[str]]:
    """Real git at the ``run_subprocess`` boundary; intercept arch.runner."""

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, timeout, runner
        if "arch.runner" in cmd:
            assert cwd is not None
            gen = Path(cwd) / "docs" / "arch" / "generated" / "x.md"
            gen.parent.mkdir(parents=True, exist_ok=True)
            gen.write_text("REGENERATED FROM SOURCE\n")
            return ""
        try:
            return subprocess.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    return fake_run


def _remote_head(bare_remote: Path, branch: str) -> str:
    return subprocess.run(
        ["git", "-C", str(bare_remote), "rev-parse", branch],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _remote_show(bare_remote: Path, ref: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(bare_remote), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


# --- loop under test ---------------------------------------------------------


def _build_loop(tmp_path: Path, local_repo: Path, github: Any) -> Any:
    from merge_state_watcher_loop import MergeStateWatcherLoop
    from pr_autorebase import PRAutoRebase
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", local_repo)
    object.__setattr__(bg.config, "pr_autorebase_enabled", True)
    object.__setattr__(bg.config, "git_user_name", "t")
    object.__setattr__(bg.config, "git_user_email", "t@t")
    # The seeds branch off "staging" — pin the two-tier model (ADR-0042) so
    # base_branch() matches regardless of the test config's default.
    object.__setattr__(bg.config, "staging_enabled", True)
    object.__setattr__(bg.config, "staging_branch", _BASE)
    assert bg.config.base_branch() == _BASE

    # A genuinely CONFLICTING PR cannot be API-updated — mirror production's
    # 422 so the tick reaches the actuator (the fake's default optimistically
    # succeeds, which is the s70 cheap-update lane).
    github.update_pr_branch = AsyncMock(return_value=False)

    reconciler = MagicMock()
    reconciler.reconcile = AsyncMock(return_value={"merged_seen": 0, "recorded": 0})

    return MergeStateWatcherLoop(
        config=bg.config,
        prs=github,
        deps=bg.loop_deps,
        approval_reconciler=reconciler,
        autorebase=PRAutoRebase(config=bg.config, prs=github),
    )


class TestPRAutoRebaseScenario:
    async def test_staging_advance_dirty_factory_pr_gets_rebased(
        self,
        tmp_path: Path,
        local_repo: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """staging moved → own PR dirty → actuator pushes a fresh head."""
        world = MockWorld(tmp_path)
        github = world.github
        _seed_generated_conflict(local_repo)
        github.add_pr(number=_PR, issue_number=_ISSUE, branch=_BRANCH, mergeable=False)
        monkeypatch.setattr("subprocess_util.run_subprocess", _regen_stub())
        head_before = _remote_head(bare_remote, _BRANCH)

        loop = _build_loop(tmp_path, local_repo, github)
        result = await loop._do_work()

        assert result is not None and result["autorebased"] == 1
        assert _remote_head(bare_remote, _BRANCH) != head_before
        assert "REGENERATED FROM SOURCE" in _remote_show(
            bare_remote, _BRANCH, "docs/arch/generated/x.md"
        )

    async def test_rebased_pr_is_not_escalated_to_hitl(
        self,
        tmp_path: Path,
        local_repo: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        _seed_generated_conflict(local_repo)
        github.add_pr(number=_PR, issue_number=_ISSUE, branch=_BRANCH, mergeable=False)
        monkeypatch.setattr("subprocess_util.run_subprocess", _regen_stub())

        loop = _build_loop(tmp_path, local_repo, github)
        result = await loop._do_work()

        assert result is not None and result["escalated"] == 0
        assert "hydraflow-hitl" not in github._prs[_PR].labels

    async def test_source_conflict_aborts_untouched_and_surfaces(
        self,
        tmp_path: Path,
        local_repo: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A non-generated conflict is never half-resolved: abort, comment,
        escalate to HITL — the remote head must not move."""
        world = MockWorld(tmp_path)
        github = world.github
        _seed_source_conflict(local_repo)
        github.add_pr(number=_PR, issue_number=_ISSUE, branch=_BRANCH, mergeable=False)
        monkeypatch.setattr("subprocess_util.run_subprocess", _regen_stub())
        head_before = _remote_head(bare_remote, _BRANCH)

        loop = _build_loop(tmp_path, local_repo, github)
        result = await loop._do_work()

        assert result is not None and result["escalated"] == 1
        assert _remote_head(bare_remote, _BRANCH) == head_before
        assert "hydraflow-hitl" in github._prs[_PR].labels

    async def test_source_conflict_comment_names_the_conflicting_file(
        self,
        tmp_path: Path,
        local_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        _seed_source_conflict(local_repo)
        github.add_pr(number=_PR, issue_number=_ISSUE, branch=_BRANCH, mergeable=False)
        monkeypatch.setattr("subprocess_util.run_subprocess", _regen_stub())

        loop = _build_loop(tmp_path, local_repo, github)
        await loop._do_work()

        conflict_comments = [body for (num, body) in github._comments if num == _PR]
        assert len(conflict_comments) == 1
        assert "src/app.py" in conflict_comments[0]

    async def test_second_tick_at_same_staging_head_does_not_reattempt(
        self,
        tmp_path: Path,
        local_repo: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One attempt per (pr, staging head): the fake still reports the PR
        CONFLICTING on tick 2, but the dedup blocks a second worktree run and
        the PR falls through to the HITL escalation instead."""
        world = MockWorld(tmp_path)
        github = world.github
        _seed_generated_conflict(local_repo)
        github.add_pr(number=_PR, issue_number=_ISSUE, branch=_BRANCH, mergeable=False)
        monkeypatch.setattr("subprocess_util.run_subprocess", _regen_stub())

        loop = _build_loop(tmp_path, local_repo, github)
        first = await loop._do_work()
        assert first is not None and first["autorebased"] == 1
        head_after_first = _remote_head(bare_remote, _BRANCH)

        second = await loop._do_work()

        assert second is not None and second["autorebased"] == 0
        assert second["escalated"] == 1
        assert _remote_head(bare_remote, _BRANCH) == head_after_first
