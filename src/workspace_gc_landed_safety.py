"""Pure identity and landed-evidence guards for destructive workspace GC.

``WorkspaceGCLoop`` owns cadence, policy, and every destructive action.  This
module owns the non-destructive evidence model used immediately before those
actions: lossless state-path ownership, Git worktree/status parsing, and the
HEAD-aware proof ladder.  The proof is a synchronous request generator so it
cannot perform I/O or accidentally create a second subprocess seam.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable, Generator, Mapping
from pathlib import Path
from typing import NamedTuple

from config import AUTO_AGENT_BRANCH_PREFIX

_GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ISSUE_BRANCH_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:agent/)?issue-(\d+)$"),
    re.compile(r"^(?:fix|feat|refactor|chore|test|docs)/.*-(\d+)$"),
    re.compile(rf"^{re.escape(AUTO_AGENT_BRANCH_PREFIX)}(\d+)$"),
)


class WorktreeEntry(NamedTuple):
    """One worktree parsed from ``git worktree list --porcelain``."""

    path: Path
    branch: str | None


class ActiveWorkspaceSnapshot(NamedTuple):
    """Lossless, path-aware active-workspace state for one GC cycle."""

    workspaces: dict[int, str]
    path_owners: dict[Path, set[int]]


class GitProbe(NamedTuple):
    """One local-Git read requested by :func:`landed_proof`."""

    args: tuple[str, ...]


class PRProbe(NamedTuple):
    """One exact historical PR-state read requested by :func:`landed_proof`."""

    branch: str
    head_sha: str
    base_branch: str


def path_within(path: Path, root: Path) -> bool:
    """Return whether *path* is *root* itself or nested under it."""
    try:
        return path == root or path.is_relative_to(root)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False


def parse_issue_from_branch(branch: str | None) -> int | None:
    """Resolve an issue number across every branch namespace GC recognizes."""
    if not branch:
        return None
    name = branch.strip().removeprefix("refs/heads/")
    for pattern in _ISSUE_BRANCH_RES:
        match = pattern.match(name)
        if match:
            return int(match.group(1))
    return None


def canonical_active_path_owners(
    active_workspaces: Mapping[int, str],
) -> dict[Path, set[int]] | None:
    """Reverse active state into canonical path to owning issue IDs.

    A malformed path makes ownership unknowable, so callers must stop the
    destructive cycle rather than risk treating an owned path as an orphan.
    Multiple issue IDs may conservatively own one canonical path.
    """
    owners: dict[Path, set[int]] = {}
    try:
        for issue_number, raw_path in active_workspaces.items():
            if type(raw_path) is not str or not raw_path.strip() or "\0" in raw_path:
                return None
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                return None
            canonical = candidate.resolve()
            owners.setdefault(canonical, set()).add(issue_number)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return owners


def active_workspace_snapshot(
    workspaces: dict[int, str] | None,
) -> ActiveWorkspaceSnapshot | None:
    """Build one canonical ownership snapshot, or fail closed on ambiguity."""
    if workspaces is None:
        return None
    path_owners = canonical_active_path_owners(workspaces)
    if path_owners is None:
        return None
    return ActiveWorkspaceSnapshot(workspaces, path_owners)


def parse_git_worktrees(output: str) -> list[WorktreeEntry]:
    """Parse ``git worktree list --porcelain``, excluding locked/bare rows."""
    entries: list[WorktreeEntry] = []
    path: Path | None = None
    branch: str | None = None
    locked = False
    is_bare = False

    def flush() -> None:
        nonlocal path, branch, locked, is_bare
        if path is not None and not locked and not is_bare:
            entries.append(WorktreeEntry(path=path, branch=branch))
        path, branch, locked, is_bare = None, None, False, False

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if line.startswith("worktree "):
            flush()
            with contextlib.suppress(OSError):
                path = Path(line[len("worktree ") :]).expanduser().resolve()
        elif line.startswith("branch "):
            branch = line[len("branch ") :].strip().removeprefix("refs/heads/")
        elif line == "detached":
            branch = None
        elif line == "bare":
            is_bare = True
        elif line.startswith("locked"):
            locked = True
    flush()
    return entries


def worktree_too_new(path: Path, min_age_seconds: int) -> bool:
    """Return whether age policy blocks collection; stat errors fail closed."""
    if min_age_seconds <= 0:
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return True
    return (time.time() - mtime) < min_age_seconds


def tracked_path_matches_destroy_target(
    recorded_path: Path, destroy_path: Path
) -> bool:
    """Return whether phase 1 inspected the path the workspace port deletes."""
    try:
        recorded = recorded_path.expanduser().resolve()
        target = destroy_path.expanduser().resolve()
        return recorded == target
    except OSError:
        return False


def parse_worktree_status(output: str) -> tuple[str, str | None, bool] | None:
    """Parse ``git status --porcelain=v2 --branch`` identity and dirtiness."""
    head_sha: str | None = None
    branch: str | None = None
    saw_branch = False
    dirty = False
    for line in output.splitlines():
        if line.startswith("# branch.oid "):
            if head_sha is not None:
                return None
            head_sha = line.removeprefix("# branch.oid ").strip().lower()
        elif line.startswith("# branch.head "):
            if saw_branch:
                return None
            raw_branch = line.removeprefix("# branch.head ").strip()
            if not raw_branch or (
                raw_branch.startswith("(") and raw_branch != "(detached)"
            ):
                return None
            branch = None if raw_branch == "(detached)" else raw_branch
            saw_branch = True
        elif line and not line.startswith("# "):
            dirty = True
    if not saw_branch or head_sha is None or _GIT_OID_RE.fullmatch(head_sha) is None:
        return None
    return head_sha, branch, dirty


def _canonical_candidate_root(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _reported_root_matches(output: str, candidate_root: Path) -> bool:
    reported_root = output.strip()
    try:
        reported_path = Path(reported_root)
        return (
            bool(reported_root)
            and "\0" not in reported_root
            and len(output.splitlines()) == 1
            and reported_path.is_absolute()
            and reported_path.expanduser().resolve() == candidate_root
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _status_matches_captured_identity(
    output: str, head_sha: str, branch: str | None
) -> bool:
    parsed = parse_worktree_status(output)
    if parsed is None:
        return False
    verified_head, verified_branch, verified_dirty = parsed
    return (
        not verified_dirty and verified_head == head_sha and verified_branch == branch
    )


def _candidate_preflight(
    path: Path,
    expected_branch: str | None,
    expected_issue: int | None,
) -> tuple[Path | None, bool | None]:
    """Return ``(root, None)`` to probe Git, otherwise a terminal result."""
    if not path.exists() or not path.is_dir():
        return None, False
    if not (path / ".git").exists():
        if expected_branch is not None or expected_issue is not None:
            return None, False
        empty = False
        with contextlib.suppress(OSError):
            empty = next(path.iterdir(), None) is None
        return None, empty
    root = _canonical_candidate_root(path)
    return (root, None) if root is not None else (None, False)


def _expected_status_identity(
    output: str,
    *,
    expected_branch: str | None,
    expected_issue: int | None,
    issue_from_branch: Callable[[str | None], int | None],
) -> tuple[str, str | None] | None:
    parsed = parse_worktree_status(output)
    if parsed is None:
        return None
    head_sha, actual_branch, dirty = parsed
    normalized_expected = (
        expected_branch.removeprefix("refs/heads/") if expected_branch else None
    )
    if (
        dirty
        or (normalized_expected is not None and actual_branch != normalized_expected)
        or (
            expected_issue is not None
            and issue_from_branch(actual_branch) != expected_issue
        )
    ):
        return None
    return head_sha, actual_branch


def _nonnegative_int(output: str) -> int | None:
    try:
        value = int(output.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def landed_proof(
    path: Path,
    *,
    base_branch: str,
    expected_branch: str | None,
    expected_issue: int | None,
    issue_from_branch: Callable[[str | None], int | None],
) -> Generator[GitProbe | PRProbe, str, bool]:
    """Prove the exact clean worktree HEAD landed, or fail closed.

    The caller drives the yielded reads but this generator owns their order:
    ancestry first, then squash-tree equality, then a merged PR whose base,
    branch, and historical head SHA exactly match.  It re-reads status after
    positive proof so a concurrent HEAD move cannot mix identities.

    An attributed candidate must exist, contain a ``.git`` marker, and report
    its own canonical top level.  This prevents parent-repository discovery or
    a stale/misdirected gitfile from proving a different tree than GC targets.
    The sole non-Git positive case is an existing empty unattributed directory.
    """
    candidate_root, terminal = _candidate_preflight(
        path, expected_branch, expected_issue
    )
    if terminal is not None or candidate_root is None:
        return terminal is True
    reported_root = yield GitProbe(("rev-parse", "--show-toplevel"))
    if not _reported_root_matches(reported_root, candidate_root):
        return False

    status = yield GitProbe(("status", "--porcelain=v2", "--branch"))
    identity = _expected_status_identity(
        status,
        expected_branch=expected_branch,
        expected_issue=expected_issue,
        issue_from_branch=issue_from_branch,
    )
    if identity is None:
        return False
    head_sha, actual_branch = identity

    rev_count = yield GitProbe(
        ("rev-list", "--count", f"origin/{base_branch}..{head_sha}")
    )
    unique_commits = _nonnegative_int(rev_count)
    if unique_commits is None:
        return False

    proof_established = unique_commits == 0
    if unique_commits > 0:
        tree_diff = yield GitProbe(
            ("diff", "--name-only", f"origin/{base_branch}", head_sha)
        )
        proof_established = not tree_diff.strip()
        if not proof_established and actual_branch is not None:
            pr_state = yield PRProbe(actual_branch, head_sha, base_branch)
            proof_established = pr_state == "MERGED"
    if not proof_established:
        return False

    verified = yield GitProbe(("status", "--porcelain=v2", "--branch"))
    return _status_matches_captured_identity(verified, head_sha, actual_branch)
