"""Thin git adapter: materialize merged changes for a commit range (#10370).

The pure sampler/governor/metrics take explicit ``MergedChange`` inputs; this
module is the ONLY git-touching code in the engine — a failure-tolerant
``git log`` adapter mirroring ``escape.detect``'s convention (raw
``subprocess.run``, a local read-only git op, NOT the fleet-gated ``claude``/
subprocess spawn the sandbox seam guard covers). One ``MergedChange`` per commit
in the range, with the PR number parsed from the merge/squash subject and the
changed paths from a per-commit name-only pass.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from audit.models import MergedChange
from git_timeouts import GIT_READONLY_TIMEOUT_S

_COMMIT_SEP = "\x00"
_FIELD_SEP = "\x1f"
_LOG_FORMAT = f"%H{_FIELD_SEP}%cI{_FIELD_SEP}%s{_FIELD_SEP}%b"

# Built from `\x01` (SOH), NOT a Unicode line-boundary character -- unlike
# `\x1e` (Record Separator), which `str.splitlines()` treats as its own line
# break and would shred the marker into pieces before any line could match it
# whole (see escape.detect._SHA_MARKER, #10499 — the same defect class).
_SHA_MARKER = "\x01AUDITSHA\x01"

# Squash-merge subject ``... (#1234)`` and merge-commit ``Merge pull request #1234``.
_SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
_MERGE_PR_RE = re.compile(r"Merge pull request #(\d+)")


def parse_pr_number(subject: str) -> int:
    """Extract the PR number from a merge/squash subject; ``0`` when absent."""
    squash = _SQUASH_PR_RE.search(subject.strip())
    if squash:
        return int(squash.group(1))
    merge = _MERGE_PR_RE.search(subject)
    if merge:
        return int(merge.group(1))
    return 0


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    """Run a read-only ``git`` command, returning stdout or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_READONLY_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _changed_paths_for_range(
    repo_root: Path, commit_range: str
) -> dict[str, list[str]]:
    """Map each commit sha in *commit_range* to the paths it changed (any status)."""
    out = _run_git(
        repo_root,
        [
            "log",
            commit_range,
            "--reverse",
            "--name-only",
            "--no-merges",
            f"--pretty=format:{_SHA_MARKER}%H",
        ],
    )
    changed: dict[str, list[str]] = {}
    if not out:
        return changed
    current: str | None = None
    # `git log` output uses bare `\n` line endings; split explicitly rather
    # than `str.splitlines()`, whose wider line-boundary set can shred a
    # marker or path apart mid-line (#10499).
    for line in out.split("\n"):
        if line.startswith(_SHA_MARKER):
            current = line[len(_SHA_MARKER) :].strip()
            changed.setdefault(current, [])
            continue
        stripped = line.strip()
        if current is not None and stripped:
            changed[current].append(stripped)
    return changed


def merged_changes_for_range(
    repo_root: Path, commit_range: str
) -> list[MergedChange] | None:
    """Materialize ``MergedChange`` for every commit in *commit_range*.

    Returns ``None`` on any git failure so callers distinguish "no changes"
    (``[]``) from "couldn't read" (``None``); ``[]`` when the range is empty.
    """
    out = _run_git(
        repo_root,
        [
            "log",
            commit_range,
            "--reverse",
            "--no-merges",
            "-z",
            f"--pretty=format:{_LOG_FORMAT}",
        ],
    )
    if out is None:
        return None
    changed_map = _changed_paths_for_range(repo_root, commit_range)
    changes: list[MergedChange] = []
    for chunk in out.split(_COMMIT_SEP):
        if not chunk.strip():
            continue
        parts = chunk.split(_FIELD_SEP)
        if len(parts) < 4:
            continue
        sha, committed_at, subject, body = parts[0], parts[1], parts[2], parts[3]
        sha = sha.strip()
        if not sha:
            continue
        changes.append(
            MergedChange(
                pr_number=parse_pr_number(subject),
                merge_sha=sha,
                subject=subject,
                changed_paths=tuple(changed_map.get(sha, [])),
                merged_at=committed_at.strip(),
                body=body,
            )
        )
    return changes


def diff_for_sha(repo_root: Path, sha: str) -> str | None:
    """Return the unified diff a commit introduced, or ``None`` on git failure.

    ``git show`` of one commit — the merged-diff context the adversarial
    auditor re-reviews. Failure-tolerant; the loop caps the length before it
    reaches the prompt.
    """
    out = _run_git(repo_root, ["show", "--no-color", "--format=%b", sha])
    if out is None:
        return None
    return out


def current_head_sha(repo_root: Path) -> str | None:
    """Return *repo_root*'s current HEAD sha, or ``None`` on any git failure.

    Deliberately uncached (mirrors ``escape_ledger_loop._current_head_sha``):
    the loop must observe HEAD advancing across ticks.
    """
    out = _run_git(repo_root, ["rev-parse", "HEAD"])
    if out is None:
        return None
    sha = out.strip()
    return sha or None
