"""Auto PR — shared helper for automated worktree+commit+push+PR flows.

This module encapsulates the repeated "create an ephemeral worktree, stage
a set of files, commit, push the branch, open a PR, and clean up" pattern
used by agents that emit PRs on behalf of HydraFlow (ADR acceptance, repo
wiki maintenance, etc.).

Callers write the desired file contents into `repo_root` *before* invoking
`open_automated_pr`; the helper copies each file (preserving relative path)
into a fresh worktree branched off `origin/{base}`, commits it with a bot
identity, pushes, and opens the PR via `gh`.  The worktree is always
removed in a `finally` block, even on failure.

See `src/adr_reviewer.py::_commit_acceptance` for the original pattern this
helper generalizes.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOT_EMAIL = "hydraflow@noreply"
BOT_NAME = "HydraFlow"

# Characters that are not safe for a filesystem path component. Branch names
# may contain "/" and other characters; sanitize for the worktree dir name.
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class AutoPrError(RuntimeError):
    """Raised when the automated PR flow fails (push, gh create, etc.)."""


@dataclass(frozen=True)
class AutoPrResult:
    """Outcome of an `open_automated_pr` call."""

    status: Literal["opened", "no-diff"]
    pr_url: str | None
    branch: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitize_branch_for_path(branch: str) -> str:
    """Return a filesystem-safe version of a branch name."""
    cleaned = _SANITIZE_RE.sub("-", branch).strip("-")
    return cleaned or "autopr"


def _run_git(
    args: list[str], *, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process.

    Separated from `_run_gh` so test code can stub `gh` without also stubbing
    the many git calls this module makes against a real repo.
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


def _run_gh(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Thin wrapper around `subprocess.run` for `gh` invocations.

    Kept as a module-level function so tests can monkeypatch
    `auto_pr._run_gh` without intercepting every `subprocess.run` call.
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )


def _remove_worktree(
    repo_root: Path, worktree_path: Path, branch: str | None = None
) -> None:
    """Best-effort worktree cleanup. Never raises.

    When `branch` is provided, also deletes the local branch so a retry with
    the same branch name doesn't hit "branch already exists".
    """
    try:
        _run_git(
            ["worktree", "remove", str(worktree_path), "--force"],
            cwd=repo_root,
            check=False,
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("git worktree remove failed for %s", worktree_path)

    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)

    if branch is not None:
        # Best-effort: delete the local branch. Harmless if it was already
        # removed by `git worktree remove`.
        _run_git(["branch", "-D", branch], cwd=repo_root, check=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_automated_pr(
    *,
    repo_root: Path,
    branch: str,
    files: list[Path],
    title: str,
    body: str,
    base: str = "main",
    auto_merge: bool = True,
) -> AutoPrResult:
    """Open a PR for `files` on a fresh worktree branched from `origin/{base}`.

    Callers write the desired contents to each path under `repo_root` before
    calling; the helper copies each file into a new worktree (preserving
    the path relative to `repo_root`), commits with the HydraFlow bot
    identity, pushes, and opens the PR via `gh`.

    If `files` is empty or the staged diff is empty, returns an
    ``AutoPrResult`` with ``status="no-diff"`` and no push/PR side effects.

    Args:
        repo_root: Root of the primary git checkout.
        branch: New branch name to create (must not already exist on origin).
        files: Paths (under `repo_root`) whose current contents should be
            staged into the PR.  An empty list short-circuits to no-diff.
        title: PR title (also used as the commit message).
        body: PR body.
        base: Base branch the PR targets. Defaults to ``"main"``.
        auto_merge: If True, attempt to enable auto-merge via
            ``gh pr merge --auto --squash``.  Best-effort — failure here is
            logged but does not raise.

    Returns:
        ``AutoPrResult`` describing the outcome.

    Raises:
        AutoPrError: If the push or ``gh pr create`` step fails.
    """
    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    wt_name = f"autopr-{_sanitize_branch_for_path(branch)}-{timestamp}"
    worktree_path = repo_root.parent / wt_name

    # Ensure we have an up-to-date origin ref for the base branch.
    _run_git(["fetch", "origin", base, "--quiet"], cwd=repo_root, check=False)

    # Create the worktree on a new branch that starts from origin/{base}.
    try:
        _run_git(
            [
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                f"origin/{base}",
            ],
            cwd=repo_root,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AutoPrError(
            f"git worktree add failed for branch {branch!r}: {exc.stderr}"
        ) from exc

    try:
        # Short-circuit when the caller supplied no files to stage.
        if not files:
            logger.info("open_automated_pr: no files supplied for %s, skipping", branch)
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)

        # Copy each file into the worktree and stage it by relative path.
        try:
            for src_path in files:
                rel = src_path.resolve().relative_to(repo_root)
                dst_path = worktree_path / rel
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                dst_path.write_bytes(src_path.read_bytes())
                _run_git(
                    ["add", str(rel)],
                    cwd=worktree_path,
                    check=True,
                )
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            raise AutoPrError(
                f"failed to stage files for branch {branch!r}: {exc}"
            ) from exc

        # Detect empty staged diff — e.g. the file contents matched origin.
        diff_check = _run_git(
            ["diff", "--cached", "--quiet"],
            cwd=worktree_path,
            check=False,
        )
        if diff_check.returncode == 0:
            logger.info(
                "open_automated_pr: staged diff is empty for %s, skipping",
                branch,
            )
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)

        # Commit with a stable bot identity — do not rely on the user's git
        # config, which may not be set in automation contexts.
        try:
            _run_git(
                [
                    "-c",
                    f"user.email={BOT_EMAIL}",
                    "-c",
                    f"user.name={BOT_NAME}",
                    "commit",
                    "-m",
                    title,
                ],
                cwd=worktree_path,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise AutoPrError(f"git commit failed: {exc.stderr}") from exc

        try:
            _run_git(
                ["push", "-u", "origin", branch],
                cwd=worktree_path,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise AutoPrError(
                f"git push failed for branch {branch!r}: {exc.stderr}"
            ) from exc

        create_proc = _run_gh(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base,
                "--head",
                branch,
            ],
            cwd=worktree_path,
        )
        if create_proc.returncode != 0:
            raise AutoPrError(
                f"gh pr create failed for branch {branch!r}: "
                f"{create_proc.stderr or create_proc.stdout}"
            )

        pr_url = _extract_pr_url(create_proc.stdout)
        if pr_url is None:
            logger.warning(
                "gh pr create succeeded for %s but no URL was parsed from stdout: %r",
                branch,
                create_proc.stdout,
            )

        if auto_merge and pr_url is not None:
            merge_proc = _run_gh(
                ["gh", "pr", "merge", pr_url, "--auto", "--squash"],
                cwd=worktree_path,
            )
            if merge_proc.returncode != 0:
                # Auto-merge is best-effort; many repos disallow it and that
                # shouldn't fail the whole flow.
                logger.warning(
                    "gh pr merge --auto failed for %s: %s",
                    pr_url,
                    merge_proc.stderr or merge_proc.stdout,
                )

        return AutoPrResult(status="opened", pr_url=pr_url, branch=branch)

    finally:
        _remove_worktree(repo_root, worktree_path, branch=branch)


def _extract_pr_url(stdout: str) -> str | None:
    """Pull the PR URL from `gh pr create` stdout.

    `gh` may emit warnings after the URL; scan from the end for the first
    non-empty line that looks like an HTTPS URL.
    """
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("https://"):
            return stripped
    return None
