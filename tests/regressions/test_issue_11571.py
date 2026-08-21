"""Real-git regression for #11571 — phase 3 branch deletes require the landed proof.

``WorkspaceGCLoop._collect_orphaned_branches`` (phase 3) listed every local
branch in an issue namespace and force-deleted it unless the issue was
tracked, active, in the pipeline, inside a retry window, or labelled. It
consulted neither issue state nor the shared landed ladder that #11530 placed
in front of every worktree destroy on phases 1, 2 and 5 — so a branch whose
worktree registration was already pruned, and whose commits were never
pushed, lost those commits to ``git branch -D`` on the next cycle. The fourth
site of the #11502 "closed/merged is not landed" class, on branch refs.

These pins run full ``_do_work`` cycles against a REAL git repository (bare
remote + clone + real local branches) with the real ``FakeGitHub`` PRPort —
no mocked ``run_subprocess`` — so the branch-tip proof is proven against
actual git semantics, including the landed shapes that must still reap.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_workspace import FakeWorkspace
from state import StateTracker
from tests.helpers import BgLoopDeps, make_bg_loop_deps
from workspace_gc_landed_safety import GitProbe, PRProbe, branch_landed_proof
from workspace_gc_loop import WorkspaceGCLoop

_UNPUSHED = 11571
_ANCESTRAL = 11573
_SQUASHED = 11574
_EXACT_HEAD = 11575
_CHECKED_OUT = 11576
_GIT_LOGGER = "hydraflow.workspace_gc_loop"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "branch", "--list", branch) != ""


def _commit_exists(repo: Path, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.fixture
def deps(tmp_path: Path) -> BgLoopDeps:
    """Loop deps whose ``repo_root`` is a real clone with ``origin/staging``.

    Phase 5 is disabled so the pins isolate phase 3; no ``issue-<N>``
    directory is ever created, so phases 1-2 and 4 have nothing to judge.
    """
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "clone", str(remote), str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.name", "Workspace GC Test")
    _git(repo, "config", "user.email", "workspace-gc@example.test")
    _git(repo, "checkout", "-b", "staging")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "seed staging")
    _git(repo, "push", "-u", "origin", "staging")
    return make_bg_loop_deps(
        tmp_path,
        staging_enabled=True,
        workspace_base=tmp_path / "workspaces",
        worktree_gc_all_roots_enabled=False,
        worktree_gc_min_age_seconds=0,
    )


def _commit_on_branch(
    deps: BgLoopDeps, branch: str, filename: str, *, start: str = "staging"
) -> str:
    """Create *branch* off *start* with one commit, leaving NO worktree behind.

    The only copy of the commit lives on the local branch ref — exactly the
    shape an agent leaves after its worktree registration is pruned.
    """
    repo = deps.config.repo_root
    scratch = repo.parent / f"scratch-{branch.replace('/', '-')}"
    _git(repo, "worktree", "add", "-b", branch, str(scratch), start)
    (scratch / filename).write_text(f"only copy on {branch}\n")
    _git(scratch, "add", filename)
    _git(scratch, "commit", "-m", f"work on {branch}")
    sha = _git(scratch, "rev-parse", "HEAD")
    _git(repo, "worktree", "remove", str(scratch))
    return sha


def _squash_onto_staging(deps: BgLoopDeps, branch: str, *, advance: bool) -> None:
    """Replay *branch* onto staging as one NEW commit (GitHub squash merge)."""
    repo = deps.config.repo_root
    _git(repo, "merge", "--squash", branch)
    _git(repo, "commit", "-m", f"squash-merge {branch}")
    if advance:
        (repo / f"advance-after-{branch.replace('/', '-')}.txt").write_text("on\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "advance staging")
    _git(repo, "push", "origin", "staging")


def _make_loop(
    deps: BgLoopDeps, github: FakeGitHub
) -> tuple[WorkspaceGCLoop, FakeWorkspace]:
    workspaces = FakeWorkspace(deps.config.workspace_base)
    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=github,
        state=StateTracker(deps.config.state_file),
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _issue: False,
    )
    return loop, workspaces


def _closed(github: FakeGitHub, issue_number: int, *, reason: str = "") -> None:
    github.add_issue(issue_number, f"Issue {issue_number}", "", state="closed")
    github.issue(issue_number).state_reason = reason


def _gc_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _GIT_LOGGER and record.levelno >= logging.WARNING
    ]


class TestPhaseThreeRequiresLandedTip:
    """#11571: a local issue branch is deleted only when its tip provably landed."""

    @pytest.mark.asyncio
    async def test_closed_not_planned_issue_branch_with_unpushed_commit_survives(
        self, deps: BgLoopDeps, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The data-loss shape from the issue: closed as not-planned, no
        worktree registration, the only copy of a commit on the local
        branch. Must NOT be deleted — and not as an error, as a decision."""
        repo = deps.config.repo_root
        branch = deps.config.branch_for_issue(_UNPUSHED)
        sha = _commit_on_branch(deps, branch, "only-copy.txt")
        github = FakeGitHub()
        _closed(github, _UNPUSHED, reason="NOT_PLANNED")
        loop, workspaces = _make_loop(deps, github)

        with caplog.at_level(logging.DEBUG, logger=_GIT_LOGGER):
            result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 0, "errors": 0}
        assert (
            _branch_exists(repo, branch),
            _git(repo, "rev-parse", branch),
            _commit_exists(repo, sha),
        ) == (True, sha, True)
        assert workspaces.destroyed == []
        assert _gc_warnings(caplog) == []
        assert any(
            "unlanded work" in record.getMessage() and record.levelno == logging.DEBUG
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_landed_branches_are_still_deleted_in_one_cycle(
        self, deps: BgLoopDeps
    ) -> None:
        """Liveness across every rung of the ladder: an ancestral tip, a
        squash whose tree still equals ``origin/staging``, and a squash that
        only an exact-HEAD merged PR can prove (base advanced since) are all
        deleted in one cycle."""
        repo = deps.config.repo_root
        exact_branch = deps.config.branch_for_issue(_EXACT_HEAD)
        squash_branch = deps.config.branch_for_issue(_SQUASHED)
        ancestral_branch = deps.config.branch_for_issue(_ANCESTRAL)
        exact_head = _commit_on_branch(deps, exact_branch, "exact.txt")
        _squash_onto_staging(deps, exact_branch, advance=True)
        # Branch off the ADVANCED staging so the tree diff can be empty after
        # its own squash lands (no later advance).
        _commit_on_branch(deps, squash_branch, "squash.txt")
        _squash_onto_staging(deps, squash_branch, advance=False)
        _git(repo, "branch", ancestral_branch, "staging")

        github = FakeGitHub()
        for issue_number in (_EXACT_HEAD, _SQUASHED, _ANCESTRAL):
            _closed(github, issue_number)
        github.add_pr(
            number=_EXACT_HEAD,
            issue_number=_EXACT_HEAD,
            branch=exact_branch,
            head_sha=exact_head,
            base_branch="staging",
            merged=True,
        )
        loop, _workspaces = _make_loop(deps, github)

        assert (
            int(_git(repo, "rev-list", "--count", f"origin/staging..{exact_branch}"))
            > 0
        )
        assert _git(repo, "diff", "--name-only", "origin/staging", exact_branch) != ""
        assert (
            int(_git(repo, "rev-list", "--count", f"origin/staging..{squash_branch}"))
            > 0
        )
        assert _git(repo, "diff", "--name-only", "origin/staging", squash_branch) == ""
        result = await loop._do_work()

        assert result == {"collected": 3, "skipped": 0, "errors": 0}
        assert [
            _branch_exists(repo, branch)
            for branch in (exact_branch, squash_branch, ancestral_branch)
        ] == [False, False, False]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("registration", ["registered", "prunable"])
    async def test_branch_checked_out_in_a_worktree_is_skipped_quietly(
        self, deps: BgLoopDeps, caplog: pytest.LogCaptureFixture, registration: str
    ) -> None:
        """A branch checked out in any registered worktree — including one
        whose directory is already gone (prunable) — is left to the worktree
        sweep at DEBUG. Before, ``git branch -D`` refused and phase 3 logged
        it as an "error processing branch" WARNING on every cycle."""
        repo = deps.config.repo_root
        branch = deps.config.branch_for_issue(_CHECKED_OUT)
        worktree = deps.config.repo_root.parent / "elsewhere" / f"wt-{_CHECKED_OUT}"
        worktree.parent.mkdir(parents=True)
        _git(repo, "worktree", "add", "-b", branch, str(worktree), "staging")
        if registration == "prunable":
            shutil.rmtree(worktree)
        github = FakeGitHub()
        _closed(github, _CHECKED_OUT)
        loop, _workspaces = _make_loop(deps, github)

        with caplog.at_level(logging.DEBUG, logger=_GIT_LOGGER):
            result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 0, "errors": 0}
        assert _branch_exists(repo, branch)
        assert (worktree.exists(), _gc_warnings(caplog)) == (
            registration == "registered",
            [],
        )
        assert any(
            "checked out in a registered worktree" in record.getMessage()
            and record.levelno == logging.DEBUG
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_git_error_inside_the_tip_proof_keeps_the_branch(
        self, deps: BgLoopDeps, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``origin/staging`` missing makes every rung unprovable; the branch
        is kept without counting an error and without a deletion attempt."""
        repo = deps.config.repo_root
        branch = deps.config.branch_for_issue(_ANCESTRAL)
        _git(repo, "branch", branch, "staging")
        _git(repo, "update-ref", "-d", "refs/remotes/origin/staging")
        github = FakeGitHub()
        _closed(github, _ANCESTRAL)
        loop, _workspaces = _make_loop(deps, github)

        with caplog.at_level(logging.DEBUG, logger=_GIT_LOGGER):
            result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 0, "errors": 0}
        assert _branch_exists(repo, branch)
        assert _gc_warnings(caplog) == []


def test_pure_branch_proof_requests_tip_identity_then_shared_ladder() -> None:
    """The branch front-end re-reads the tip after proof, like the worktree
    front-end re-reads status: a concurrent commit cannot mix identities."""
    tip = "b" * 40
    proof = branch_landed_proof("refs/heads/fix/landed-42", base_branch="staging")

    assert next(proof) == GitProbe(
        ("rev-parse", "--verify", "refs/heads/fix/landed-42^{commit}")
    )
    assert proof.send(f"{tip}\n") == GitProbe(
        ("rev-list", "--count", f"origin/staging..{tip}")
    )
    assert proof.send("2\n") == GitProbe(("diff", "--name-only", "origin/staging", tip))
    assert proof.send("changed.py\n") == PRProbe("fix/landed-42", tip, "staging")
    assert proof.send("MERGED") == GitProbe(
        ("rev-parse", "--verify", "refs/heads/fix/landed-42^{commit}")
    )
    with pytest.raises(StopIteration) as completed:
        proof.send(f"{tip}\n")
    assert completed.value.value is True


@pytest.mark.parametrize(
    ("tip_after", "verdict"),
    [
        pytest.param("c" * 40, False, id="tip-moved-after-proof"),
        pytest.param("not-a-sha", False, id="malformed-reread"),
        pytest.param("b" * 40, True, id="stable-tip"),
    ],
)
def test_pure_branch_proof_fails_closed_unless_tip_is_stable(
    tip_after: str, verdict: bool
) -> None:
    tip = "b" * 40
    proof = branch_landed_proof("agent/issue-7", base_branch="staging")
    next(proof)
    assert proof.send(tip) == GitProbe(
        ("rev-list", "--count", f"origin/staging..{tip}")
    )
    # Ancestral tip: proof established on the first rung, then the re-read.
    assert proof.send("0") == GitProbe(
        ("rev-parse", "--verify", "refs/heads/agent/issue-7^{commit}")
    )
    with pytest.raises(StopIteration) as completed:
        proof.send(tip_after)
    assert completed.value.value is verdict


@pytest.mark.parametrize(
    "tip_output",
    [
        pytest.param("", id="empty"),
        pytest.param("fatal: Needed a single revision", id="git-error-text"),
        pytest.param(f"{'b' * 40}\n{'c' * 40}", id="two-lines"),
        pytest.param("B" * 39, id="short-oid"),
    ],
)
def test_pure_branch_proof_rejects_malformed_tip(tip_output: str) -> None:
    proof = branch_landed_proof("agent/issue-7", base_branch="staging")
    next(proof)
    with pytest.raises(StopIteration) as completed:
        proof.send(tip_output)
    assert completed.value.value is False


@pytest.mark.parametrize("branch", ["", "   ", "refs/heads/", "-D", "bad\0name"])
def test_pure_branch_proof_rejects_unusable_branch_names(branch: str) -> None:
    proof = branch_landed_proof(branch, base_branch="staging")
    with pytest.raises(StopIteration) as completed:
        next(proof)
    assert completed.value.value is False
