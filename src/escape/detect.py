"""Pure escape detection (#10367) + a thin git adapter.

``detect_escapes`` is the pure core: it reads a list of ``CommitInfo`` and
returns one ``EscapeCandidate`` per commit that carries a post-merge-defect
signal — mirroring ``erosion.spread.compute``'s purity contract (explicit
inputs, no git, unit-testable with synthetic data). ``commits_for_range`` and
``commit_committed_at`` are the thin ``git log`` adapters that materialize
``CommitInfo`` for a real commit range; the pure core never shells out.

Detection sources (v1, decided): revert commits, regression-pin commits
(a new file under ``tests/regressions/``), hotfix commits referencing a prior
merge, and bug-issue fixes (a ``fix`` commit closing ``#N``). Sentry-sourced
escapes are attributed in the ``SentryLoop`` flow, not here. Exactly one
candidate is emitted per commit — the strongest signal wins by precedence
(revert > regression-pin > hotfix > bug-issue), so a merged revert / hotfix /
regression-pin each produce exactly one ledger row.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from escape import attribution
from escape.models import (
    AttributionConfidence,
    AttributionMethod,
    CommitInfo,
    DetectionSource,
    EscapeCandidate,
)
from false_close import has_skip_regression
from git_timeouts import GIT_READONLY_TIMEOUT_S

# NUL separates commits (`-z`); 0x1f separates fields within a commit. Neither
# appears in a sha / ISO date / subject / body, so the split is unambiguous
# even across multi-line bodies.
_COMMIT_SEP = "\x00"
_FIELD_SEP = "\x1f"
_LOG_FORMAT = f"%H{_FIELD_SEP}%cI{_FIELD_SEP}%s{_FIELD_SEP}%b"

# Marker line prefix for the added-paths pass (distinct from any real path).
# Built from `\x01` (SOH), NOT a Unicode line-boundary character -- unlike
# `\x1e` (Record Separator), which `str.splitlines()` treats as its own line
# break and would shred the marker into pieces before any line could match
# it whole (#10499). `_added_paths_for_range` below also avoids
# `str.splitlines()` entirely for the same reason: `git log` output uses
# bare `\n` line endings, so an explicit `str.split("\n")` is both correct
# and immune to any future marker/path colliding with `splitlines()`'s wider
# line-boundary set (\v, \f, \x1c, \x1d, \x1e, \x85, U+2028, U+2029).
_SHA_MARKER = "\x01ESCSHA\x01"


def _fix_subject(subject: str) -> bool:
    """True for a conventional-commit fix subject (``fix:`` / ``fix(scope):``)."""
    head = subject.strip().lower()
    return head.startswith(("fix:", "fix(", "fix!:", "bug:", "bugfix"))


def _origin_pointer(commit: CommitInfo) -> tuple[str, int | None]:
    """Extract the best originating pointer + closing ref from *commit*.

    Prefers a stated sha (resolvable to a merge time so
    ``time_to_detection_hours`` can be populated) over a ``#N`` closing-keyword
    reference. Returns ``(originating_ref, closes_ref)``; ``originating_ref``
    is a bare sha, ``#N``, or ``""`` when nothing was found. ``closes_ref`` is
    the number a GitHub closing keyword (``Fixes``/``Closes``/``Resolves #N``)
    names — the issue/PR THIS commit closes, which points downstream at
    resolved work, never upstream at the merge that introduced the defect.
    Callers use it only to select ``attribution_method``/gate emission; it must
    never be written to ``EscapeCandidate.originating_pr``.
    """
    text = f"{commit.subject}\n{commit.body}"
    fixes = attribution.extract_fixes_refs(text)
    closes_ref = fixes[0] if fixes else None
    shas = attribution.extract_referenced_shas(commit.body, exclude=commit.sha)
    if shas:
        return shas[0], closes_ref
    if closes_ref is not None:
        return f"#{closes_ref}", closes_ref
    return "", closes_ref


def _classify(commit: CommitInfo) -> EscapeCandidate | None:
    """Return the single strongest escape candidate for *commit*, or ``None``.

    Precedence (decided): revert > regression-pin > hotfix > bug-issue. Pure.
    """
    subject, body = commit.subject, commit.body

    if attribution.is_revert(subject, body):
        reverted = attribution.parse_reverted_sha(body) or ""
        confidence: AttributionConfidence = "high" if reverted else "medium"
        return EscapeCandidate(
            detection_source="revert",
            detection_ref=commit.sha,
            detected_at=commit.committed_at,
            attribution_method="revert-parse",
            attribution_confidence=confidence,
            originating_ref=reverted,
            notes="Revert commit — reverses a prior merged change.",
        )

    if attribution.adds_regression_pin(commit.added_paths):
        ref = _origin_pointer(commit)[0]
        return EscapeCandidate(
            detection_source="regression-pin",
            detection_ref=commit.sha,
            detected_at=commit.committed_at,
            attribution_method="regression-pin",
            attribution_confidence="medium",
            originating_ref=ref,
            notes="Adds a tests/regressions/ pin for a post-merge failure.",
        )

    if attribution.is_hotfix(subject, body):
        ref, closes_ref = _origin_pointer(commit)
        method: AttributionMethod = (
            "fixes-chain" if closes_ref is not None else "blame-intersect"
        )
        conf: AttributionConfidence = "medium" if ref else "low"
        return EscapeCandidate(
            detection_source="hotfix",
            detection_ref=commit.sha,
            detected_at=commit.committed_at,
            attribution_method=method,
            attribution_confidence=conf,
            originating_ref=ref,
            notes="Hotfix referencing a prior merged change.",
        )

    if _fix_subject(subject):
        # A commit that declares itself behaviour-neutral (the P10.6/P10.7
        # Skip-Regression opt-out trailer) is not a post-merge defect, even
        # when its subject carries a `fix(...)` prefix — e.g. a docs-only
        # diagram refresh. Scoped to this branch only: reverts/hotfixes must
        # still be recorded even if their body happens to carry the trailer.
        if has_skip_regression(f"{subject}\n{body}"):
            return None
        ref, closes_ref = _origin_pointer(commit)
        if closes_ref is not None:
            return EscapeCandidate(
                detection_source="bug-issue",
                detection_ref=commit.sha,
                detected_at=commit.committed_at,
                attribution_method="fixes-chain",
                attribution_confidence="low",
                originating_ref=ref,
                notes=(
                    "Fix commit closing an issue — bug-issue escape pending a "
                    "human bug-label confirmation (HITL)."
                ),
            )

    return None


def detect_escapes(commits: list[CommitInfo]) -> list[EscapeCandidate]:
    """Pure: one ``EscapeCandidate`` per commit carrying an escape signal.

    Order-preserving over *commits*. No git, no I/O — the thin adapters
    below feed it real commit ranges; unit tests feed it synthetic data.
    """
    candidates: list[EscapeCandidate] = []
    for commit in commits:
        candidate = _classify(commit)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    """Run a read-only ``git`` command, returning stdout or ``None`` on failure.

    Failure-tolerant like every git adapter in this family (missing git,
    non-zero exit, timeout, non-repo all return ``None``). Raw
    ``subprocess.run`` mirrors ``erosion.spread.changed_files_for_range``'s
    convention — a local read-only git op, not the fleet-gated spawn path
    the sandbox seam guard covers.
    """
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


def _added_paths_for_range(repo_root: Path, commit_range: str) -> dict[str, list[str]]:
    """Map each commit sha in *commit_range* to the paths it ADDED (status ``A``)."""
    out = _run_git(
        repo_root,
        [
            # core.quotepath defaults to true, which octal-escapes non-ASCII
            # path bytes (e.g. `"tests/regressions/test_\303\251.py"`) and
            # would defeat `adds_regression_pin`'s startswith() check below;
            # disable it so name-only output round-trips real UTF-8 paths.
            "-c",
            "core.quotepath=false",
            "log",
            commit_range,
            "--reverse",
            "--diff-filter=A",
            "--name-only",
            f"--pretty=format:{_SHA_MARKER}%H",
        ],
    )
    added: dict[str, list[str]] = {}
    if not out:
        return added
    current: str | None = None
    # `git log` output uses bare `\n` line endings; split explicitly rather
    # than `str.splitlines()`, whose wider line-boundary set (see
    # `_SHA_MARKER` above) can shred a marker or path apart mid-line (#10499).
    for line in out.split("\n"):
        if line.startswith(_SHA_MARKER):
            current = line[len(_SHA_MARKER) :].strip()
            added.setdefault(current, [])
            continue
        stripped = line.strip()
        if current is not None and stripped:
            added[current].append(stripped)
    return added


def commits_for_range(repo_root: Path, commit_range: str) -> list[CommitInfo] | None:
    """Materialize ``CommitInfo`` for every commit in *commit_range*.

    Thin ``git log`` adapter — NOT part of the pure detector. Returns
    ``None`` on any git failure so callers distinguish "no commits" (``[]``)
    from "couldn't read" (``None``); ``[]`` when the range is empty.
    """
    out = _run_git(
        repo_root,
        ["log", commit_range, "--reverse", "-z", f"--pretty=format:{_LOG_FORMAT}"],
    )
    if out is None:
        return None
    added_map = _added_paths_for_range(repo_root, commit_range)
    commits: list[CommitInfo] = []
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
        commits.append(
            CommitInfo(
                sha=sha,
                subject=subject,
                body=body,
                committed_at=committed_at.strip(),
                added_paths=tuple(added_map.get(sha, [])),
            )
        )
    return commits


def commit_committed_at(repo_root: Path, sha: str) -> str | None:
    """Return *sha*'s committer date (ISO-8601), or ``None`` on any git failure."""
    out = _run_git(repo_root, ["show", "-s", "--format=%cI", sha])
    if out is None:
        return None
    stamp = out.strip()
    return stamp or None


def count_commits_since(repo_root: Path, days: int) -> int | None:
    """Count commits reachable from HEAD in the last *days* — merge-volume proxy.

    Used as the denominator for ``escapes per 100 merges``. A rolling count
    of merged changes; ``None`` on git failure.
    """
    out = _run_git(
        repo_root, ["rev-list", "--count", f"--since={days}.days.ago", "HEAD"]
    )
    if out is None:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


__all__ = [
    "AttributionMethod",
    "DetectionSource",
    "commit_committed_at",
    "commits_for_range",
    "count_commits_since",
    "detect_escapes",
]
