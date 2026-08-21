"""Real-git regressions for WorkspaceGC landed safety (#11502/#11503/#11507)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from state import StateTracker
from tests.helpers import make_bg_loop_deps
from workspace_gc_landed_safety import (
    GitProbe,
    PRProbe,
    active_workspace_snapshot,
    landed_proof,
    parse_issue_from_branch,
)
from workspace_gc_loop import WorkspaceGCLoop

_BRANCH = "fix/reused-workspace-gc"
_MOVED_BRANCH = "fix/moved-worktree-11507"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _seed_squash_merged_branch(tmp_path: Path) -> tuple[Path, str]:
    """Return a clean feature checkout after its squash landed and base advanced."""
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clone", str(remote), str(repo)],
        check=True,
        capture_output=True,
    )
    _git(repo, "config", "user.name", "Workspace GC Test")
    _git(repo, "config", "user.email", "workspace-gc@example.test")
    _git(repo, "checkout", "-b", "staging")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "seed staging")
    _git(repo, "push", "-u", "origin", "staging")

    _git(repo, "checkout", "-b", _BRANCH)
    (repo / "feature.txt").write_text("one\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature one")
    (repo / "feature.txt").write_text("one\ntwo\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature two")
    merged_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-u", "origin", _BRANCH)

    _git(repo, "checkout", "staging")
    _git(repo, "merge", "--squash", _BRANCH)
    _git(repo, "commit", "-m", "squash feature")
    # Advance staging after the squash. The two-rev tree diff is now nonempty,
    # so only the exact historical PR HEAD can prove the feature landed.
    (repo / "later.txt").write_text("unrelated staging advance\n")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "advance staging")
    _git(repo, "push", "origin", "staging")
    _git(repo, "checkout", _BRANCH)
    _git(repo, "fetch", "origin", "staging")
    return repo, merged_head


def _seed_moved_unique_worktree(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, str]:
    """Return a primary repo whose registered worktree path was moved away."""
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clone", str(remote), str(repo)],
        check=True,
        capture_output=True,
    )
    _git(repo, "config", "user.name", "Workspace GC Test")
    _git(repo, "config", "user.email", "workspace-gc@example.test")
    _git(repo, "checkout", "-b", "staging")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "seed staging")
    _git(repo, "push", "-u", "origin", "staging")

    gc_root = tmp_path / "gc-roots"
    registered_path = gc_root / "registered-worktree"
    _git(
        repo,
        "worktree",
        "add",
        "-b",
        _MOVED_BRANCH,
        str(registered_path),
        "staging",
    )
    (registered_path / "unique.txt").write_text("only copy of this work\n")
    _git(registered_path, "add", "unique.txt")
    _git(registered_path, "commit", "-m", "unique unlanded work")
    unique_head = _git(registered_path, "rev-parse", "HEAD")

    moved_path = tmp_path / "operator-salvage" / "moved-worktree"
    moved_path.parent.mkdir()
    registered_path.rename(moved_path)
    return repo, gc_root, registered_path, moved_path, unique_head


def _loop(tmp_path: Path, github: FakeGitHub) -> WorkspaceGCLoop:
    deps = make_bg_loop_deps(
        tmp_path,
        state_file=tmp_path / "state.json",
        staging_enabled=True,
        worktree_gc_min_age_seconds=0,
    )
    return WorkspaceGCLoop(
        config=deps.config,
        workspaces=MagicMock(),
        prs=github,
        state=StateTracker(deps.config.state_file),
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _issue: False,
    )


def test_pure_landed_proof_requests_exact_git_and_pr_identity(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: fake\n")
    head_sha = "a" * 40
    status = f"# branch.oid {head_sha}\n# branch.head fix/landed-42\n"
    proof = landed_proof(
        worktree,
        base_branch="staging",
        expected_branch="fix/landed-42",
        expected_issue=42,
        issue_from_branch=parse_issue_from_branch,
    )

    assert next(proof) == GitProbe(("rev-parse", "--show-toplevel"))
    assert proof.send(str(worktree.resolve())) == GitProbe(
        ("status", "--porcelain=v2", "--branch")
    )
    assert proof.send(status) == GitProbe(
        ("rev-list", "--count", f"origin/staging..{head_sha}")
    )
    assert proof.send("2\n") == GitProbe(
        ("diff", "--name-only", "origin/staging", head_sha)
    )
    assert proof.send("changed.py\n") == PRProbe("fix/landed-42", head_sha, "staging")
    assert proof.send("MERGED") == GitProbe(("status", "--porcelain=v2", "--branch"))
    with pytest.raises(StopIteration) as completed:
        proof.send(status)
    assert completed.value.value is True


def test_pure_ownership_snapshot_rejects_ambiguous_paths(tmp_path: Path) -> None:
    owned = tmp_path / "owned"

    snapshot = active_workspace_snapshot({42: str(owned), 99: str(owned)})

    assert snapshot is not None
    assert snapshot.path_owners == {owned.resolve(): {42, 99}}
    assert active_workspace_snapshot({42: "relative/worktree"}) is None


@pytest.mark.asyncio
async def test_squash_merged_exact_head_stays_landed_after_staging_advances(
    tmp_path: Path,
) -> None:
    repo, merged_head = _seed_squash_merged_branch(tmp_path)
    github = FakeGitHub()
    github.add_pr(
        number=11502,
        issue_number=11502,
        branch=_BRANCH,
        head_sha=merged_head,
        base_branch="staging",
        merged=True,
    )
    loop = _loop(tmp_path, github)

    landed = await loop._worktree_work_has_landed(
        repo,
        expected_branch=_BRANCH,
        expected_issue=None,
    )

    assert (
        int(_git(repo, "rev-list", "--count", "origin/staging..HEAD")) > 0,
        bool(_git(repo, "diff", "--name-only", "origin/staging", "HEAD")),
        landed,
    ) == (True, True, True)


@pytest.mark.asyncio
async def test_reused_branch_new_unpushed_head_is_not_laundered_by_old_merge(
    tmp_path: Path,
) -> None:
    repo, merged_head = _seed_squash_merged_branch(tmp_path)
    github = FakeGitHub()
    github.add_pr(
        number=11502,
        issue_number=11502,
        branch=_BRANCH,
        head_sha=merged_head,
        base_branch="staging",
        merged=True,
    )
    (repo / "new-work.txt").write_text("must survive\n")
    _git(repo, "add", "new-work.txt")
    _git(repo, "commit", "-m", "new work on reused branch")
    new_head = _git(repo, "rev-parse", "HEAD")
    loop = _loop(tmp_path, github)

    landed = await loop._worktree_work_has_landed(
        repo,
        expected_branch=_BRANCH,
        expected_issue=None,
    )

    assert (new_head != merged_head, landed) == (True, False)


@pytest.mark.asyncio
async def test_exact_head_merged_into_other_base_does_not_authorize_gc(
    tmp_path: Path,
) -> None:
    repo, merged_head = _seed_squash_merged_branch(tmp_path)
    github = FakeGitHub()
    github.add_pr(
        number=11502,
        issue_number=11502,
        branch=_BRANCH,
        head_sha=merged_head,
        base_branch="release",
        merged=True,
    )
    loop = _loop(tmp_path, github)

    landed = await loop._worktree_work_has_landed(
        repo,
        expected_branch=_BRANCH,
        expected_issue=None,
    )

    assert landed is False


@pytest.mark.asyncio
async def test_missing_base_ref_fails_closed_even_with_exact_merged_pr(
    tmp_path: Path,
) -> None:
    repo, merged_head = _seed_squash_merged_branch(tmp_path)
    github = FakeGitHub()
    github.add_pr(
        number=11502,
        issue_number=11502,
        branch=_BRANCH,
        head_sha=merged_head,
        base_branch="staging",
        merged=True,
    )
    _git(repo, "update-ref", "-d", "refs/remotes/origin/staging")
    loop = _loop(tmp_path, github)

    landed = await loop._worktree_work_has_landed(
        repo,
        expected_branch=_BRANCH,
        expected_issue=None,
    )

    assert landed is False


@pytest.mark.asyncio
async def test_full_cycle_authorizes_legitimate_exact_head_worktree(
    tmp_path: Path,
) -> None:
    """The root-identity fence permits a real registered worktree to collect."""
    repo, merged_head = _seed_squash_merged_branch(tmp_path)
    _git(repo, "checkout", "staging")
    gc_root = tmp_path / "gc-roots"
    worktree = gc_root / "landed-worktree"
    _git(repo, "worktree", "add", str(worktree), _BRANCH)
    deps = make_bg_loop_deps(
        tmp_path,
        state_file=tmp_path / "state.json",
        staging_enabled=True,
        worktree_gc_roots=[str(gc_root)],
        worktree_gc_min_age_seconds=0,
    )
    state = StateTracker(deps.config.state_file)
    github = FakeGitHub()
    github.add_pr(
        number=11502,
        issue_number=11502,
        branch=_BRANCH,
        head_sha=merged_head,
        base_branch="staging",
        merged=True,
    )
    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=MagicMock(),
        prs=github,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _issue: False,
    )

    result = await loop._do_work()

    assert result == {"collected": 1, "skipped": 0, "errors": 0}
    assert not worktree.exists()
    assert _git(repo, "branch", "--list", _BRANCH) == ""
    assert state.get_active_workspaces() == {}


@pytest.mark.asyncio
async def test_prunable_registry_with_moved_unique_worktree_preserves_branch(
    tmp_path: Path,
) -> None:
    repo, gc_root, registered_path, moved_path, unique_head = (
        _seed_moved_unique_worktree(tmp_path)
    )
    github = FakeGitHub()
    github.add_issue(11507, "Moved worktree", "", state="closed")
    deps = make_bg_loop_deps(
        tmp_path,
        state_file=tmp_path / "state.json",
        staging_enabled=True,
        worktree_gc_roots=[str(gc_root)],
        worktree_gc_min_age_seconds=0,
    )
    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=MagicMock(),
        prs=github,
        state=StateTracker(deps.config.state_file),
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _issue: False,
    )
    registry_before = _git(repo, "worktree", "list", "--porcelain")

    result = await loop._do_work()

    registry_after = _git(repo, "worktree", "list", "--porcelain")
    assert (result, registered_path.exists(), moved_path.exists()) == (
        {"collected": 0, "skipped": 0, "errors": 0},
        False,
        True,
    )
    assert (str(registered_path) in registry_before, "prunable" in registry_before) == (
        True,
        True,
    )
    assert str(registered_path) in registry_after
    assert _git(repo, "rev-parse", _MOVED_BRANCH) == unique_head
    assert (moved_path / "unique.txt").read_text() == "only copy of this work\n"
