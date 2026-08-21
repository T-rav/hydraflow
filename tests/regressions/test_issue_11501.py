"""Regression pins for #11501 — wrong-branch worktree creation.

The bug: ``git worktree add <dir> <branch>`` fails when ``<dir>`` already
exists, but in one chained shell invocation the later ``cd <dir>`` +
``git merge``/``git commit`` still run and report success — against whatever
stale branch the reused directory name was left on. Hit three times in one
session (2026-08-20); the worst case staged 1469 files from a merge into the
wrong branch. ``.claude/worktrees/`` accumulates stale directories, so any
name an agent picks can already exist.

The fix under test: ``scripts/hf_worktree.sh <dir> <branch>`` (thin
``make worktree DIR= BRANCH=`` wrapper) creates when absent, is idempotent
when already on the branch, and fails loudly on a mismatch — never deleting
the existing worktree, whose uncommitted work may be hand-written.

Pins cover the three core paths plus the edge cases prior attempts were
flagged for missing (empty args, non-repo invocation, unregistered dir,
detached HEAD, Makefile wiring) and a liveness counter-pin proving the
sandbox still models the bare-recipe defect the helper exists to catch.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "hf_worktree.sh"

# Isolate git from any global/system config so verdicts never depend on the
# operator's machine (same convention as tests/test_liveness_boot_guard.py).
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _env() -> dict[str, str]:
    return {**os.environ, **_GIT_ENV}


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd), env=_env(), capture_output=True, text=True
    )


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=_env(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"git {args} failed:\n{proc.stderr}"
    return proc.stdout


def _sandbox(path: Path) -> Path:
    """Fresh repo on ``main`` with free branches ``feature-x``/``rc-branch``."""
    path.mkdir(parents=True)
    _git(path, "init", "-b", "main")
    (path / "README.md").write_text("# sandbox\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "feature-x")
    _git(path, "branch", "rc-branch")
    return path


def _helper(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run([str(HELPER), *args], cwd)


def _branch_at(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _combined(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


# --- Helper existence -----------------------------------------------------


def test_helper_exists_and_is_executable() -> None:
    assert HELPER.is_file(), f"{HELPER} missing"
    assert os.access(HELPER, os.X_OK), f"{HELPER} not executable"
    assert HELPER.read_text(encoding="utf-8").startswith("#!")


# --- Core path 1: absent directory → create -------------------------------


def test_creates_worktree_when_dir_absent(tmp_path: Path) -> None:
    repo = _sandbox(tmp_path / "repo")

    proc = _helper(repo, "wt/new", "feature-x")

    assert proc.returncode == 0, _combined(proc)
    assert _branch_at(repo / "wt" / "new") == "feature-x"


def test_success_output_names_resolved_branch(tmp_path: Path) -> None:
    repo = _sandbox(tmp_path / "repo")

    proc = _helper(repo, "wt/x", "feature-x")

    assert proc.returncode == 0, _combined(proc)
    assert "feature-x" in proc.stdout


# --- Core path 2: already on requested branch → idempotent ----------------


def test_idempotent_when_already_on_requested_branch(tmp_path: Path) -> None:
    repo = _sandbox(tmp_path / "repo")
    assert _helper(repo, "wt/x", "feature-x").returncode == 0

    again = _helper(repo, "wt/x", "feature-x")

    assert again.returncode == 0, _combined(again)
    assert "feature-x" in again.stdout


# --- Core path 3: different branch → fail loudly, never delete ------------


def test_mismatch_exits_nonzero_naming_both_branches(tmp_path: Path) -> None:
    repo = _sandbox(tmp_path / "repo")
    _git(repo, "worktree", "add", str(repo / "wt" / "stale"), "feature-x")

    proc = _helper(repo, "wt/stale", "rc-branch")

    assert proc.returncode != 0
    out = _combined(proc)
    assert "rc-branch" in out  # expected
    assert "feature-x" in out  # actual


def test_mismatch_preserves_worktree_and_prints_remove_command(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")
    stale = repo / "wt" / "stale"
    _git(repo, "worktree", "add", str(stale), "feature-x")
    keep = stale / "uncommitted.txt"
    keep.write_text("hand-written work", encoding="utf-8")

    proc = _helper(repo, "wt/stale", "rc-branch")

    assert proc.returncode != 0
    # Nothing deleted, nothing repointed.
    assert keep.read_text(encoding="utf-8") == "hand-written work"
    assert _branch_at(stale) == "feature-x"
    assert "git worktree remove" in _combined(proc)


def test_detached_head_in_existing_worktree_is_mismatch(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")
    _git(repo, "worktree", "add", str(repo / "wt" / "d"), "feature-x")
    _git(repo / "wt" / "d", "checkout", "-q", "--detach")

    proc = _helper(repo, "wt/d", "rc-branch")

    assert proc.returncode != 0
    assert "detached" in _combined(proc).lower()


# --- Edge cases prior attempts were flagged for missing -------------------


def test_existing_unregistered_directory_fails_untouched(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")
    plain = repo / "wt" / "plain"
    plain.mkdir(parents=True)
    (plain / "note.txt").write_text("keep", encoding="utf-8")

    proc = _helper(repo, "wt/plain", "feature-x")

    assert proc.returncode != 0
    assert (plain / "note.txt").read_text(encoding="utf-8") == "keep"
    assert "worktree" in _combined(proc).lower()


def test_missing_or_extra_args_print_usage_and_fail(tmp_path: Path) -> None:
    for args in ([], ["only-dir"], ["a", "b", "c"]):
        proc = _helper(tmp_path, *args)
        assert proc.returncode != 0, f"args={args} unexpectedly succeeded"
        assert "usage" in _combined(proc).lower(), f"args={args}"


def test_empty_string_args_are_usage_errors(tmp_path: Path) -> None:
    for args in (["", ""], ["wt/x", ""]):
        proc = _helper(tmp_path, *args)
        assert proc.returncode != 0, f"args={args} unexpectedly succeeded"
        assert "usage" in _combined(proc).lower(), f"args={args}"


def test_invocation_outside_git_repo_fails(tmp_path: Path) -> None:
    norepo = tmp_path / "norepo"
    norepo.mkdir()

    proc = _helper(norepo, "wt/x", "feature-x")

    assert proc.returncode != 0
    assert "git repository" in _combined(proc).lower()


def test_relative_dir_from_subdirectory_resolves_against_cwd(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")
    sub = repo / "sub"
    sub.mkdir()

    proc = _helper(sub, "../wts/fromsub", "feature-x")

    assert proc.returncode == 0, _combined(proc)
    assert _branch_at(repo / "wts" / "fromsub") == "feature-x"


def test_add_failure_on_unknown_branch_propagates_git_error(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")

    proc = _helper(repo, "wt/x", "no-such-branch")

    assert proc.returncode != 0
    assert "no-such-branch" in _combined(proc)


def test_path_occupied_by_regular_file_fails_untouched(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")
    occupied = repo / "occupied"
    occupied.write_text("data", encoding="utf-8")

    proc = _helper(repo, "occupied", "feature-x")

    assert proc.returncode != 0
    assert occupied.read_text(encoding="utf-8") == "data"


def test_empty_unregistered_directory_fails_with_removal_hint(
    tmp_path: Path,
) -> None:
    repo = _sandbox(tmp_path / "repo")
    empty = repo / "wt" / "empty"
    empty.mkdir(parents=True)

    proc = _helper(repo, "wt/empty", "feature-x")

    assert proc.returncode != 0
    assert empty.is_dir()  # nothing deleted
    assert "rmdir" in _combined(proc)


# --- Makefile wiring -------------------------------------------------------


def test_makefile_declares_worktree_target_phony_and_help() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^worktree:", makefile, re.MULTILINE)
    assert re.search(r"^\.PHONY:.*\bworktree\b", makefile, re.MULTILINE)
    assert re.search(r"make worktree\s+.*DIR=<dir>", makefile)


def _make_sandbox(path: Path) -> Path:
    """Sandbox repo carrying the REAL Makefile + helper, for `make worktree`.

    Copies the production files (not re-implementations) so the recipe under
    test is exactly what ships — this is what pins the DIR/BRANCH wiring.
    """
    if shutil.which("make") is None:
        pytest.skip("make not available")
    repo = _sandbox(path)
    shutil.copy2(REPO_ROOT / "Makefile", repo / "Makefile")
    (repo / "scripts").mkdir()
    shutil.copy2(HELPER, repo / "scripts" / "hf_worktree.sh")
    os.chmod(repo / "scripts" / "hf_worktree.sh", 0o755)
    return repo


def test_make_worktree_target_end_to_end(tmp_path: Path) -> None:
    repo = _make_sandbox(tmp_path / "repo")

    proc = _run(
        ["make", "worktree", "DIR=wt/made", "BRANCH=feature-x"], repo
    )

    assert proc.returncode == 0, _combined(proc)
    assert _branch_at(repo / "wt" / "made") == "feature-x"


def test_make_worktree_without_args_prints_usage(tmp_path: Path) -> None:
    repo = _make_sandbox(tmp_path / "repo")

    proc = _run(["make", "worktree"], repo)

    assert proc.returncode != 0
    assert "usage" in _combined(proc).lower()
    assert not (repo / "wt").exists()  # nothing created


# --- Documentation ---------------------------------------------------------


def test_claude_md_names_the_helper() -> None:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "hf_worktree.sh" in text
    # The mirror rule: verify branch identity after creating a worktree.
    assert "rev-parse --abbrev-ref HEAD" in text


def test_gotchas_entry_names_the_helper() -> None:
    text = (REPO_ROOT / "docs" / "wiki" / "gotchas.md").read_text(
        encoding="utf-8"
    )
    assert "hf_worktree.sh" in text
    assert "git worktree remove" in text


# --- Liveness counter-pin ---------------------------------------------------


def test_liveness_bare_chained_recipe_succeeds_on_wrong_branch(
    tmp_path: Path,
) -> None:
    """The sandbox must keep modeling the real #11501 defect.

    A bare chained ``git worktree add <dir> <branch>; cd <dir> && ...``
    reports SUCCESS (exit 0, last command wins) while sitting on the WRONG
    branch: the ``add`` fails on the reused directory, but the ``cd`` and
    everything after it still run against the stale checkout. If this pin
    ever fails, the sandbox stopped reproducing the defect the helper
    exists to catch — re-validate before trusting the mismatch pins.
    """
    repo = _sandbox(tmp_path / "repo")
    stale = repo / "wt" / "stale"
    _git(repo, "worktree", "add", str(stale), "feature-x")

    chained = (
        f'git worktree add "{stale}" rc-branch; '
        f'cd "{stale}" && git rev-parse --abbrev-ref HEAD'
    )
    proc = _run(["bash", "-c", chained], repo)

    assert proc.returncode == 0  # the add failure is masked by the chain
    assert "already exists" in proc.stderr
    assert proc.stdout.strip().endswith("feature-x")  # wrong branch, silently
