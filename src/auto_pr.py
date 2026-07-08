"""Auto PR — shared helper for automated worktree+commit+push+PR flows.

This module encapsulates the repeated "create an ephemeral worktree, stage
a set of files, commit, push the branch, open a PR, and clean up" pattern
used by agents that emit PRs on behalf of HydraFlow (ADR acceptance, repo
wiki maintenance, etc.).

Callers write the desired file contents into `repo_root` *before* invoking
`open_automated_pr`; the helper copies each file (preserving relative path)
into a fresh worktree branched off `origin/{base}`, commits it with the
caller-supplied identity (defaulting to the HydraFlow bot, or falling back
to ambient git config when both name and email are empty), pushes, and
opens the PR via `gh`.  The worktree is always removed in a `finally`
block, even on failure.

See `src/adr_reviewer.py::_commit_acceptance` for the original pattern this
helper generalizes.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
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
# ^^ Defaults used when the caller does not supply
# `commit_author_name` / `commit_author_email`.  HydraFlow callers should
# pass `self._config.git_user_name` / `self._config.git_user_email` so a
# user-configured identity is respected.

# Characters that are not safe for a filesystem path component. Branch names
# may contain "/" and other characters; sanitize for the worktree dir name.
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Default color/description used when auto-creating PR labels. ``gh label
# create`` (no ``--force``) only applies these on first creation; if the
# label already exists, the call fails with "already exists" which we treat
# as success — existing labels keep their hand-tuned color/description.
_AUTO_LABEL_COLOR = "ededed"
_AUTO_LABEL_DESCRIPTION = "Auto-created by HydraFlow"

# Hard timeout for every ``subprocess.run`` invocation in this module.
# ``open_automated_pr_async`` runs these wrappers under ``asyncio.to_thread``,
# so an unbounded subprocess (hung ``git push`` against a stale remote, ``gh``
# blocking on auth refresh, pre-push hook deadlock, etc.) leaks the worker
# thread and eventually exhausts the asyncio thread pool. Same deadlock class
# as PR #8454 / regression test ``test_async_subprocess_timeouts.py``.
# 120 s comfortably covers the slowest legitimate operation (a ``git push``
# that triggers a slow pre-push hook against origin); anything beyond is a
# hang we want to surface, not wait on.
_SUBPROCESS_TIMEOUT_S = 120


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class AutoPrError(RuntimeError):
    """Raised when the automated PR flow fails (push, gh create, etc.)."""


@dataclass(frozen=True)
class AutoPrResult:
    """Outcome of an `open_automated_pr` call."""

    status: Literal["opened", "no-diff", "failed"]
    pr_url: str | None
    branch: str
    error: str | None = None


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
        timeout=_SUBPROCESS_TIMEOUT_S,
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
        timeout=_SUBPROCESS_TIMEOUT_S,
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
        # Per docs/wiki/patterns.md: handled cleanup failures log at
        # `warning` minimum — never bare `except: pass` or debug-silent.
        logger.warning("git worktree remove failed for %s", worktree_path)

    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)

    if branch is not None:
        # Best-effort: delete the local branch. Harmless if it was already
        # removed by `git worktree remove`.
        _run_git(["branch", "-D", branch], cwd=repo_root, check=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_commit_args(author_name: str, author_email: str, message: str) -> list[str]:
    """Build the arg list for `git commit`, skipping identity overrides when
    the caller-supplied name or email is empty.

    Empty values mean "fall back to git's ambient config" per the
    `HydraFlowConfig.git_user_name/email` contract. Passing `-c user.email=`
    to git would instead force an empty identity and fail with
    "Author identity unknown".
    """
    args: list[str] = []
    if author_name and author_email:
        args.extend(["-c", f"user.email={author_email}"])
        args.extend(["-c", f"user.name={author_name}"])
    args.extend(["commit", "-m", message])
    return args


def open_automated_pr(
    *,
    repo_root: Path,
    branch: str,
    files: list[Path],
    title: str,
    body: str,
    base: str = "main",
    auto_merge: bool = True,
    worktree_parent: Path | None = None,
    commit_author_name: str = BOT_NAME,
    commit_author_email: str = BOT_EMAIL,
    labels: list[str] | None = None,
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
        worktree_parent: Directory to create the ephemeral worktree under.
            Defaults to ``repo_root.parent``. Callers that keep worktrees in
            a dedicated workspace (e.g. HydraFlow's ``workspace_base``) pass
            that path here.
        commit_author_name: Name for ``git -c user.name`` on the commit.
            Defaults to the HydraFlow bot. When both name and email are
            empty strings, the ``-c`` overrides are omitted and git uses
            the ambient worktree/global config instead.
        commit_author_email: Email for ``git -c user.email``. See above
            regarding empty-string fallback.

    Returns:
        ``AutoPrResult`` describing the outcome.

    Raises:
        AutoPrError: If the worktree-add, stage, commit, push, or
            ``gh pr create`` step fails.
    """
    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    wt_name = f"autopr-{_sanitize_branch_for_path(branch)}-{timestamp}"
    wt_parent = (worktree_parent or repo_root.parent).resolve()
    wt_parent.mkdir(parents=True, exist_ok=True)
    worktree_path = wt_parent / wt_name

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

        # Commit with the caller-supplied identity when provided; when either
        # value is empty, omit the `-c user.*` overrides so git falls back to
        # ambient config (worktree → user global → system). This matches the
        # documented `HydraFlowConfig.git_user_name/email` contract that an
        # empty config value falls back to global git config.
        commit_args = _build_commit_args(commit_author_name, commit_author_email, title)
        try:
            _run_git(commit_args, cwd=worktree_path, check=True)
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

        create_cmd = [
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
        ]
        for label in labels or []:
            create_cmd.extend(["--label", label])
        create_proc = _run_gh(create_cmd, cwd=worktree_path)
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


# ---------------------------------------------------------------------------
# Async API — used from HydraFlow's async call sites (ADR reviewer, etc.)
# ---------------------------------------------------------------------------


async def _ensure_labels_async(
    labels: list[str], *, cwd: Path, gh_token: str
) -> list[str]:
    """Return the subset of ``labels`` that exist on the repo.

    For each requested label: try ``gh label create NAME --color … --desc …``.
    If gh exits 0 the label was just created; if it exits non-zero with an
    "already exists" stderr, that's still a success for our purposes.
    Anything else is logged as a warning and the label is dropped from the
    returned list, so the downstream ``gh pr create`` doesn't fail wholesale
    on a label that the repo refuses to host.
    """
    from subprocess_util import run_subprocess  # local import: avoids cycles

    ensured: list[str] = []
    for name in labels:
        try:
            await run_subprocess(
                "gh",
                "label",
                "create",
                name,
                "--color",
                _AUTO_LABEL_COLOR,
                "--description",
                _AUTO_LABEL_DESCRIPTION,
                cwd=cwd,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            if "already exists" in str(exc).lower():
                ensured.append(name)
                continue
            logger.warning(
                "could not ensure label %r exists; dropping from PR: %s", name, exc
            )
            continue
        ensured.append(name)
    return ensured


async def _finalize_pr_from_worktree(
    *,
    worktree_path: Path,
    branch: str,
    pr_title: str,
    pr_body: str,
    commit_message: str,
    base: str,
    auto_merge: bool,
    gh_token: str,
    labels: list[str] | None,
    commit_author_name: str,
    commit_author_email: str,
    fail: Callable[[str], AutoPrResult],
) -> AutoPrResult:
    """Commit already-staged worktree changes, push, open the PR, auto-merge.

    Shared tail for ``open_automated_pr_async`` (which stages by copying files
    from ``repo_root``) and ``generate_and_open_pr_async`` (which stages content
    generated directly in the worktree). The caller owns worktree creation,
    staging (``git add``), and teardown (``finally``); this only runs the
    commit → push → label → pr-create → auto-merge tail.
    """
    from subprocess_util import run_subprocess  # noqa: PLC0415

    # Empty staged diff → nothing to PR.
    try:
        await run_subprocess(
            "git", "diff", "--cached", "--quiet", cwd=worktree_path, gh_token=gh_token
        )
        logger.info("auto_pr: empty staged diff for %s", branch)
        return AutoPrResult(status="no-diff", pr_url=None, branch=branch)
    except RuntimeError:
        pass  # non-zero → there IS a diff; proceed.

    commit_args = _build_commit_args(
        commit_author_name, commit_author_email, commit_message
    )
    try:
        await run_subprocess("git", *commit_args, cwd=worktree_path, gh_token=gh_token)
    except RuntimeError as exc:
        return fail(f"git commit failed: {exc}")

    try:
        await run_subprocess(
            "git", "push", "-u", "origin", branch, cwd=worktree_path, gh_token=gh_token
        )
    except RuntimeError as exc:
        return fail(f"git push failed for {branch!r}: {exc}")

    ensured_labels = (
        await _ensure_labels_async(labels or [], cwd=worktree_path, gh_token=gh_token)
        if labels
        else []
    )

    create_args: list[str] = [
        "gh",
        "pr",
        "create",
        "--title",
        pr_title,
        "--body",
        pr_body,
        "--base",
        base,
        "--head",
        branch,
    ]
    for label in ensured_labels:
        create_args.extend(["--label", label])
    try:
        create_stdout = await run_subprocess(
            *create_args, cwd=worktree_path, gh_token=gh_token
        )
    except RuntimeError as exc:
        return fail(f"gh pr create failed for {branch!r}: {exc}")

    pr_url = _extract_pr_url(create_stdout)
    if pr_url is None:
        logger.warning(
            "gh pr create succeeded for %s but no URL parsed: %r", branch, create_stdout
        )

    if auto_merge and pr_url is not None:
        try:
            await run_subprocess(
                "gh",
                "pr",
                "merge",
                pr_url,
                "--auto",
                "--squash",
                cwd=worktree_path,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            logger.warning("gh pr merge --auto failed for %s: %s", pr_url, exc)

    return AutoPrResult(status="opened", pr_url=pr_url, branch=branch)


async def open_automated_pr_async(  # noqa: PLR0911 — linear step-by-step guards, each with its own fail path
    *,
    repo_root: Path,
    branch: str,
    files: list[Path],
    pr_title: str,
    pr_body: str,
    commit_message: str | None = None,
    base: str = "main",
    auto_merge: bool = True,
    gh_token: str = "",
    raise_on_failure: bool = True,
    worktree_parent: Path | None = None,
    commit_author_name: str = BOT_NAME,
    commit_author_email: str = BOT_EMAIL,
    labels: list[str] | None = None,
) -> AutoPrResult:
    """Async variant that routes subprocess calls through `run_subprocess`.

    Same high-level behavior as the sync `open_automated_pr`:
    worktree → copy files → stage → commit → push → gh pr create → gh pr merge
    → clean up.

    Differences from the sync version:

    - Uses :func:`subprocess_util.run_subprocess` so it participates in the
      HydraFlow async loop and the `gh/git` concurrency semaphore.
    - Accepts an explicit `gh_token` that's threaded through every call.
    - Accepts an independent `commit_message` for callers where the commit
      message differs from the PR title (e.g. the ADR reviewer embeds the
      council summary in the commit).
    - When `raise_on_failure=False`, logs + returns an
      ``AutoPrResult(status="failed", error=...)`` instead of raising —
      matching the ADR reviewer's "log and continue" contract.

    Args:
        repo_root: Root of the primary git checkout.
        branch: New branch name (must not already exist on origin).
        files: Paths under `repo_root` whose current contents should be
            staged into the PR. Empty → no-diff short-circuit.
        pr_title: Title for the PR.
        pr_body: Body for the PR.
        commit_message: Commit message; defaults to `pr_title` when None.
        base: Base branch. Defaults to ``"main"``.
        auto_merge: If True, attempt `gh pr merge --auto --squash`.
        gh_token: Value injected as GH_TOKEN for each subprocess call.
        raise_on_failure: If False, failures become
            ``AutoPrResult(status="failed")`` instead of raising.
        worktree_parent: Directory to create the ephemeral worktree under.
            Defaults to ``repo_root.parent``.
        commit_author_name: Name for ``git -c user.name`` on the commit.
            Defaults to the HydraFlow bot. When both name and email are
            empty strings, the ``-c`` overrides are omitted and git uses
            the ambient worktree/global config instead.
        commit_author_email: Email for ``git -c user.email``. See above
            regarding empty-string fallback.

    Returns:
        ``AutoPrResult`` describing the outcome.

    Raises:
        AutoPrError: If a step fails and `raise_on_failure` is True.
    """
    from subprocess_util import run_subprocess  # local import: avoids cycles

    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    wt_name = f"autopr-{_sanitize_branch_for_path(branch)}-{timestamp}"
    wt_parent = (worktree_parent or repo_root.parent).resolve()
    wt_parent.mkdir(parents=True, exist_ok=True)
    worktree_path = wt_parent / wt_name
    msg = commit_message if commit_message is not None else pr_title

    def _fail(err: str) -> AutoPrResult:
        if raise_on_failure:
            raise AutoPrError(err)
        # These are transient subprocess failures (git/gh network, auth, race
        # conditions) — operational, not code bugs. Per docs/wiki/patterns.md,
        # handled transient failures log at `warning`, not `error`.
        # Plain .warning (not .exception) because we may be called outside an
        # except handler; .exception would attach a misleading
        # `NoneType: None` traceback in Sentry.
        logger.warning("open_automated_pr_async failed for %s: %s", branch, err)
        return AutoPrResult(status="failed", pr_url=None, branch=branch, error=err)

    # Best-effort fetch of the base ref. If the fetch fails (offline,
    # transient auth hiccup), fall through: the subsequent `git worktree add`
    # will use whatever cached `origin/{base}` the local repo already has,
    # which is usually recent enough. Only a missing local `origin/{base}`
    # ref will fail, at which point `git worktree add` surfaces a clear
    # error and we route through `_fail` like any other failure.
    try:
        await run_subprocess(
            "git",
            "fetch",
            "origin",
            base,
            "--quiet",
            cwd=repo_root,
            gh_token=gh_token,
        )
    except RuntimeError as exc:
        logger.warning(
            "git fetch origin %s failed for %s; continuing with cached ref: %s",
            base,
            branch,
            exc,
        )

    # From here on every exit path must go through `finally` so the worktree
    # + branch are torn down regardless of outcome.
    try:
        try:
            await run_subprocess(
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                f"origin/{base}",
                cwd=repo_root,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            return _fail(f"git worktree add failed for {branch!r}: {exc}")
        if not files:
            logger.info("open_automated_pr_async: no files supplied for %s", branch)
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)

        # Copy each file, stage by relative path (targeted; no `git add -A`).
        try:
            for src_path in files:
                rel = src_path.resolve().relative_to(repo_root)
                dst_path = worktree_path / rel
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                dst_path.write_bytes(src_path.read_bytes())
                await run_subprocess(
                    "git",
                    "add",
                    str(rel),
                    cwd=worktree_path,
                    gh_token=gh_token,
                )
        except (RuntimeError, OSError, ValueError) as exc:
            return _fail(f"failed to stage files for {branch!r}: {exc}")

        return await _finalize_pr_from_worktree(
            worktree_path=worktree_path,
            branch=branch,
            pr_title=pr_title,
            pr_body=pr_body,
            commit_message=msg,
            base=base,
            auto_merge=auto_merge,
            gh_token=gh_token,
            labels=labels,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
            fail=_fail,
        )

    finally:
        await _remove_worktree_async(repo_root, worktree_path, branch, gh_token)


async def generate_and_open_pr_async(
    *,
    repo_root: Path,
    branch: str,
    generate: Callable[[Path], Awaitable[None]],
    path_specs: list[str],
    pr_title: str,
    pr_body: str | Callable[[], str],
    commit_message: str | None = None,
    base: str = "main",
    auto_merge: bool = True,
    gh_token: str = "",
    raise_on_failure: bool = True,
    worktree_parent: Path | None = None,
    commit_author_name: str = BOT_NAME,
    commit_author_email: str = BOT_EMAIL,
    labels: list[str] | None = None,
) -> AutoPrResult:
    """Open a PR for content GENERATED inside the worktree — never touching repo_root.

    The generate-in-worktree counterpart to :func:`open_automated_pr_async`.
    Instead of the caller pre-writing files under ``repo_root`` (which leaves the
    factory's checkout perpetually dirty — see #9539 /
    ``docs/proposals/factory-tree-self-clean.md``), the caller supplies a
    ``generate`` coroutine that writes into the freshly-created worktree (branched
    off ``origin/{base}``). The worktree is the only thing mutated, and it is torn
    down in ``finally`` — so ``repo_root`` stays clean.

    Args:
        generate: ``async (worktree_path) -> None`` — produce the desired file
            state inside ``worktree_path`` (e.g. run an arch/diagram regen with
            ``out_dir`` under the worktree). Credit/auth/bug exceptions propagate
            via ``reraise_on_credit_or_bug``; other errors become a ``failed``
            result (or raise when ``raise_on_failure``).
        path_specs: repo-relative paths/dirs to ``git add`` after generation
            (e.g. ``["docs/arch/generated", "docs/arch/.meta.json"]``). An empty
            staged diff short-circuits to ``no-diff``.
        pr_body: the PR body, or a zero-arg callable returning it. A callable is
            resolved AFTER ``generate`` + staging, so bodies that summarise what
            the generator produced (counts, changed files) can read state the
            callback populated. Resolution happens before the no-diff check, so
            the callable must not assume a PR will actually be opened.

    All other args mirror :func:`open_automated_pr_async`.
    """
    from exception_classify import reraise_on_credit_or_bug  # noqa: PLC0415
    from subprocess_util import run_subprocess  # noqa: PLC0415

    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    wt_name = f"genpr-{_sanitize_branch_for_path(branch)}-{timestamp}"
    wt_parent = (worktree_parent or repo_root.parent).resolve()
    wt_parent.mkdir(parents=True, exist_ok=True)
    worktree_path = wt_parent / wt_name
    msg = commit_message if commit_message is not None else pr_title

    def _fail(err: str) -> AutoPrResult:
        if raise_on_failure:
            raise AutoPrError(err)
        logger.warning("generate_and_open_pr_async failed for %s: %s", branch, err)
        return AutoPrResult(status="failed", pr_url=None, branch=branch, error=err)

    try:
        await run_subprocess(
            "git", "fetch", "origin", base, "--quiet", cwd=repo_root, gh_token=gh_token
        )
    except RuntimeError as exc:
        logger.warning(
            "git fetch origin %s failed for %s; continuing with cached ref: %s",
            base,
            branch,
            exc,
        )

    try:
        try:
            await run_subprocess(
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                f"origin/{base}",
                cwd=repo_root,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            return _fail(f"git worktree add failed for {branch!r}: {exc}")

        # Generate the desired file state INSIDE the worktree (never repo_root).
        try:
            await generate(worktree_path)
        except Exception as exc:  # noqa: BLE001 — classify then convert to a result
            reraise_on_credit_or_bug(exc)
            return _fail(f"generate callback failed for {branch!r}: {exc}")

        # Stage the generated paths (targeted; mirrors the no-`git add -A` rule).
        # Skip specs the generator didn't materialise — `git add` errors on a
        # pathspec that matches nothing, and "the generator produced none of
        # this path" is a legitimate no-op (→ empty staged diff → no-diff).
        try:
            for spec in path_specs:
                if not (worktree_path / spec).exists():
                    continue
                await run_subprocess(
                    "git", "add", "--", spec, cwd=worktree_path, gh_token=gh_token
                )
        except RuntimeError as exc:
            return _fail(f"failed to stage generated paths for {branch!r}: {exc}")

        # Resolve a lazy body now — after generate + staging — so summaries can
        # reflect what the generator produced.
        resolved_body = pr_body() if callable(pr_body) else pr_body

        return await _finalize_pr_from_worktree(
            worktree_path=worktree_path,
            branch=branch,
            pr_title=pr_title,
            pr_body=resolved_body,
            commit_message=msg,
            base=base,
            auto_merge=auto_merge,
            gh_token=gh_token,
            labels=labels,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
            fail=_fail,
        )
    finally:
        await _remove_worktree_async(repo_root, worktree_path, branch, gh_token)


async def _remove_worktree_async(
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    gh_token: str,
) -> None:
    """Best-effort async worktree cleanup. Never raises."""
    from subprocess_util import run_subprocess  # local import: avoids cycles

    try:
        await run_subprocess(
            "git",
            "worktree",
            "remove",
            str(worktree_path),
            "--force",
            cwd=repo_root,
            gh_token=gh_token,
        )
    except RuntimeError:
        # Per docs/wiki/patterns.md: handled cleanup failures log at
        # `warning` minimum.
        logger.warning("git worktree remove failed for %s", worktree_path)

    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)

    try:
        await run_subprocess(
            "git",
            "branch",
            "-D",
            branch,
            cwd=repo_root,
            gh_token=gh_token,
        )
    except RuntimeError:
        logger.warning("git branch -D failed for %s", branch)


# ---------------------------------------------------------------------------
# Arch-staleness self-heal — merge base + regenerate generated/ + push
# ---------------------------------------------------------------------------

# Path prefixes whose merge conflicts are auto-resolvable by re-running
# arch-regen. A bot PR commits `docs/arch/generated/` artifacts; when the base
# branch advances, every OTHER open bot PR's committed generated files go stale
# and conflict on merge. Re-emitting them from source resolves the conflict.
# `.meta.json` carries the regen stamp and conflicts the same way.
_ARCH_GENERATED_PREFIX = "docs/arch/generated/"
_ARCH_META_PATH = "docs/arch/.meta.json"

# Outcome of an arch-staleness refresh attempt.
ArchRefreshStatus = Literal["refreshed", "no-diff", "real-conflict", "failed"]


@dataclass(frozen=True)
class ArchRefreshResult:
    """Outcome of :func:`refresh_branch_with_arch_regen`.

    - ``refreshed``: merged base, regenerated artifacts, committed + pushed.
    - ``no-diff``: base merged cleanly with nothing to regenerate/commit
      (already up to date) — nothing pushed.
    - ``real-conflict``: a non-generated file conflicted; merge aborted, no
      push. The caller must fall through to its failure strategy.
    - ``failed``: a git/gh step errored (network, auth, regen crash).
    """

    status: ArchRefreshStatus
    error: str | None = None


def _is_arch_only_conflict(conflicted_paths: list[str]) -> bool:
    """True iff every conflicting path is an arch-generated artifact.

    An empty list (no conflicts) is *not* an arch conflict — the caller treats
    a clean merge separately. Returns False the moment a non-generated path
    appears, because regen cannot resolve a real content conflict.
    """
    if not conflicted_paths:
        return False
    return all(
        p == _ARCH_META_PATH or p.startswith(_ARCH_GENERATED_PREFIX)
        for p in conflicted_paths
    )


async def refresh_branch_with_arch_regen(  # noqa: PLR0911 — linear step-by-step guards, each with its own fail/outcome path
    *,
    repo_root: Path,
    branch: str,
    base: str,
    gh_token: str = "",
    worktree_parent: Path | None = None,
    commit_author_name: str = BOT_NAME,
    commit_author_email: str = BOT_EMAIL,
) -> ArchRefreshResult:
    """Self-heal a bot PR stuck red on stale ``docs/arch/generated/`` artifacts.

    In an ephemeral worktree checked out on the PR's existing remote head
    (``origin/{branch}``):

    1. ``git merge origin/{base} --no-edit`` (a merge commit, not a rebase —
       rebase needs a force-push, which the pre-push hook blocks; squash-merge
       collapses the merge commit anyway).
    2. If the merge conflicts only under ``docs/arch/generated/`` (+
       ``.meta.json``), regenerate the artifacts (``arch.runner --emit``),
       ``git add -A``, and commit. If ANY non-generated path conflicts, abort
       the merge and return ``real-conflict`` — a genuine content conflict
       cannot be auto-healed.
    3. If the merge was clean, still re-emit so source/generated drift
       introduced by the newly-merged base is resolved, then stage + commit
       only if there is a diff.
    4. Push the temp branch to ``origin/{branch}``.

    The worktree + temp local branch are always removed in a ``finally``.
    Never force-pushes. Returns an :class:`ArchRefreshResult`.
    """
    from subprocess_util import run_subprocess  # local import: avoids cycles

    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    safe = _sanitize_branch_for_path(branch)
    wt_parent = (worktree_parent or repo_root.parent).resolve()
    wt_parent.mkdir(parents=True, exist_ok=True)
    worktree_path = wt_parent / f"archheal-{safe}-{timestamp}"
    # Temp LOCAL branch name — never the PR's real branch, so cleanup's
    # `branch -D` can't delete the PR head. We push it to `origin/{branch}`.
    local_branch = f"archheal-{safe}-{timestamp}"

    async def _git(*args: str, cwd: Path) -> str:
        return await run_subprocess("git", *args, cwd=cwd, gh_token=gh_token)

    # Refresh both refs we need: the PR head and the base.
    for ref in (branch, base):
        try:
            await run_subprocess(
                "git",
                "fetch",
                "origin",
                ref,
                "--quiet",
                cwd=repo_root,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            logger.warning(
                "arch-refresh: git fetch origin %s failed for %s; "
                "continuing with cached ref: %s",
                ref,
                branch,
                exc,
            )

    try:
        try:
            await _git(
                "worktree",
                "add",
                "-b",
                local_branch,
                str(worktree_path),
                f"origin/{branch}",
                cwd=repo_root,
            )
        except RuntimeError as exc:
            return ArchRefreshResult(
                status="failed",
                error=f"git worktree add failed for {branch!r}: {exc}",
            )

        # Merge the base into the PR head. A non-zero exit can mean conflicts
        # OR a genuine error; we disambiguate by inspecting the unmerged set.
        merge_conflicted = False
        try:
            await _git("merge", f"origin/{base}", "--no-edit", cwd=worktree_path)
        except RuntimeError:
            merge_conflicted = True

        if merge_conflicted:
            try:
                unmerged_out = await _git(
                    "diff", "--name-only", "--diff-filter=U", cwd=worktree_path
                )
            except RuntimeError as exc:
                await _abort_merge(worktree_path, gh_token)
                return ArchRefreshResult(
                    status="failed",
                    error=f"could not inspect merge conflicts for {branch!r}: {exc}",
                )
            conflicted = [p for p in unmerged_out.splitlines() if p.strip()]
            if not _is_arch_only_conflict(conflicted):
                # Real content conflict (or an empty/odd merge failure) — abort
                # and let the caller's failure strategy take over.
                await _abort_merge(worktree_path, gh_token)
                return ArchRefreshResult(
                    status="real-conflict",
                    error="non-generated merge conflict: " + ", ".join(conflicted[:10]),
                )

        # Regenerate the architecture artifacts from source. This resolves an
        # arch-only conflict AND repairs plain staleness from the merged base.
        try:
            await run_subprocess(
                "uv",
                "run",
                "python",
                "-m",
                "arch.runner",
                "--emit",
                "--repo-root",
                str(worktree_path),
                cwd=worktree_path,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            await _abort_merge(worktree_path, gh_token)
            return ArchRefreshResult(
                status="failed", error=f"arch.runner --emit failed: {exc}"
            )

        # Stage everything (the merged base files + regenerated artifacts).
        try:
            await _git("add", "-A", cwd=worktree_path)
        except RuntimeError as exc:
            await _abort_merge(worktree_path, gh_token)
            return ArchRefreshResult(status="failed", error=f"git add failed: {exc}")

        # On a CLEAN merge with no regen diff there is nothing to commit and the
        # branch is already current — report no-diff so the caller does NOT burn
        # a refresh attempt on a no-op (a real failure stays red and the cap
        # still bounds it).
        staged_empty = await _staged_diff_empty(worktree_path, gh_token)
        if staged_empty and not merge_conflicted:
            return ArchRefreshResult(status="no-diff")

        commit_args = _build_commit_args(
            commit_author_name,
            commit_author_email,
            f"chore(arch): refresh generated artifacts after merging {base}",
        )
        try:
            await run_subprocess(
                "git", *commit_args, cwd=worktree_path, gh_token=gh_token
            )
        except RuntimeError as exc:
            return ArchRefreshResult(status="failed", error=f"git commit failed: {exc}")

        # Push the temp branch's head to the PR's remote branch. NOT a
        # force-push: a merge commit fast-forwards the remote head cleanly.
        try:
            await _git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=worktree_path)
        except RuntimeError as exc:
            return ArchRefreshResult(
                status="failed", error=f"git push failed for {branch!r}: {exc}"
            )

        return ArchRefreshResult(status="refreshed")
    finally:
        await _remove_worktree_async(repo_root, worktree_path, local_branch, gh_token)


async def _abort_merge(worktree_path: Path, gh_token: str) -> None:
    """Best-effort ``git merge --abort``. Never raises."""
    from subprocess_util import run_subprocess  # local import: avoids cycles

    try:
        await run_subprocess(
            "git", "merge", "--abort", cwd=worktree_path, gh_token=gh_token
        )
    except RuntimeError:
        logger.warning("git merge --abort failed in %s", worktree_path)


async def _staged_diff_empty(worktree_path: Path, gh_token: str) -> bool:
    """True when ``git diff --cached --quiet`` exits 0 (no staged changes)."""
    from subprocess_util import run_subprocess  # local import: avoids cycles

    try:
        await run_subprocess(
            "git",
            "diff",
            "--cached",
            "--quiet",
            cwd=worktree_path,
            gh_token=gh_token,
        )
        return True  # exit 0 → no staged diff
    except RuntimeError:
        return False  # non-zero → there IS a staged diff
