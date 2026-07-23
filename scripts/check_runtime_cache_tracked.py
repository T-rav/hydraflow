"""Guard against runtime cache/artifact files dirtying the git tree (#9599).

Runtime state that a background loop rewrites every tick must live under the
gitignored ``data_root`` (``.hydraflow/``) or be gitignored — never committed to
the tracked repo tree. Two failure modes have bitten the factory:

  (a) *Tracked-churn* — ``docs/wiki/{log.jsonl, ingest_dedup.json, index.json}``
      were git-tracked runtime caches the ``RepoWikiLoop`` rewrote every cycle, so
      the dev checkout's working tree was perpetually dirty (fixed reactively in
      #9537). Maintenance PRs are built in ephemeral worktrees that never clean the
      originals in ``repo_root``, and the caches churn faster than any PR cadence.

  (b) *Untracked-dirt* — ``FitnessScorecardLoop`` writes
      ``docs/arch/generated/loop-fitness.md`` into the live repo root every tick.
      It was neither tracked nor gitignored, so it showed as a permanent ``??`` in
      ``git status`` (found 2026-07-19). The inverse of mode (a): an artifact under
      a tracked directory that is neither tracked nor ignored.

This is a proactive, stdlib-only static gate modelled on
``scripts/check_conflict_markers.py`` (#9482): a pure classifier over
``git ls-files`` (mode a) / ``git ls-files --others --exclude-standard`` (mode b),
wired into ``make cache-check``, a dedicated ungated CI job, the pre-commit hook,
and a ``tests/architecture/`` test. It flags the *next* runtime cache before it
dirties the tree instead of after an incident.

Detection is deliberately narrow to avoid a false-positive storm: cache-shaped
**basenames** and **cache-dir path segments**, never whole extensions (a plain
``*.jsonl`` rule would storm on the tracked per-issue ``repo_wiki/.../log/*.jsonl``
snapshots and test fixtures). ``tests/`` and ``repo_wiki/`` are excluded wholesale
and ``ALLOWLIST`` is the escape hatch for any legitimately-tracked exception.

Usage:
    check_runtime_cache_tracked.py <file> [<file> ...]  # classify given paths (pre-commit)
    check_runtime_cache_tracked.py --tracked            # scan all git-tracked files (mode a)
    check_runtime_cache_tracked.py --untracked          # scan untracked/un-ignored files (mode b)
    check_runtime_cache_tracked.py                       # same as --tracked
"""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

# fnmatch globs matched (case-insensitively) against a path's basename. Narrow by
# design — these catch the #9537 caches and generic cache shapes without hitting
# the numbered ``repo_wiki/.../log/NNNN.jsonl`` snapshots or test fixtures.
CACHE_BASENAME_PATTERNS: tuple[str, ...] = (
    "log.jsonl",  # ingest log (#9537) — NOT NNNN.jsonl / legacy.jsonl
    "index.json",  # machine index (#9537)
    "ingest_dedup.json",  # dedup cache (#9537)
    "*_dedup.json",  # generic dedup caches
    "dedup.json",
    "*_cache.json",  # generic caches
    "*.cache.json",
    "*_cache.jsonl",
    "ingest_*.json",  # ingest state
)

# A tracked path containing one of these as a path segment is a runtime cache.
# ``log`` is intentionally excluded: ``repo_wiki/.../log/NNNN.jsonl`` are tracked
# write-once per-issue snapshots, not caches.
CACHE_DIR_SEGMENTS: frozenset[str] = frozenset(
    {"cache", "caches", ".cache", "__cache__", "dedup"}
)

# Prefixes that legitimately hold cache-shaped tracked files (fixtures, cassettes,
# corpora, seeds, and the migrated static wiki snapshot per ADR-0032). Excluded
# wholesale so the guard never storms on them.
EXCLUDED_PREFIXES: tuple[str, ...] = ("tests/", "repo_wiki/")

# Directories whose contents must be fully tracked OR gitignored — a runtime loop
# artifact left here un-ignored (mode b) is the FitnessScorecardLoop footgun.
GENERATED_ARTIFACT_DIRS: tuple[str, ...] = ("docs/arch/generated/",)

# Exact repo-relative paths that match a pattern but are legitimately tracked.
# Empty by design; each future entry needs an inline "# why:" justification.
ALLOWLIST: frozenset[str] = frozenset()


def _is_excluded(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def _matches_cache_shape(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    if any(seg in CACHE_DIR_SEGMENTS for seg in parts):
        return True
    basename = parts[-1].lower() if parts else ""
    return any(
        fnmatch.fnmatchcase(basename, pattern.lower())
        for pattern in CACHE_BASENAME_PATTERNS
    )


def classify_tracked_paths(paths: Iterable[str]) -> list[str]:
    """Return sorted paths that look like git-tracked runtime caches (mode a)."""
    offenders = {
        rel
        for rel in paths
        if rel
        and rel not in ALLOWLIST
        and not _is_excluded(rel)
        and _matches_cache_shape(rel)
    }
    return sorted(offenders)


def classify_untracked_artifacts(untracked_paths: Iterable[str]) -> list[str]:
    """Return sorted untracked/un-ignored paths under a generated-artifact dir (mode b)."""
    offenders = {
        rel
        for rel in untracked_paths
        if rel
        and rel not in ALLOWLIST
        and any(rel.startswith(directory) for directory in GENERATED_ARTIFACT_DIRS)
    }
    return sorted(offenders)


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def _untracked_unignored_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def _report_tracked(offenders: list[str]) -> None:
    print(
        "git-tracked runtime caches found — refusing to proceed. These churn every "
        "loop tick and leave the working tree perpetually dirty (#9599):",
        file=sys.stderr,
    )
    for rel in offenders:
        print(f"  {rel}", file=sys.stderr)
    print(
        "\nUntrack each and gitignore it:\n"
        "  git rm --cached <path> && echo <path> >> .gitignore\n"
        "If it is legitimately tracked, add it to ALLOWLIST in "
        "scripts/check_runtime_cache_tracked.py with a justification.",
        file=sys.stderr,
    )


def _report_untracked(offenders: list[str]) -> None:
    print(
        "untracked/un-ignored loop artifacts found under a generated dir — a runtime "
        "loop rewrites these every tick, leaving a permanent '??' in git status "
        "(#9599):",
        file=sys.stderr,
    )
    for rel in offenders:
        print(f"  {rel}", file=sys.stderr)
    print(
        "\nGitignore each (or commit it into the tracked arch-regen set):\n"
        "  echo <path> >> .gitignore",
        file=sys.stderr,
    )


def main(argv: list[str]) -> int:
    root = _repo_root()

    if "--untracked" in argv:
        offenders = classify_untracked_artifacts(_untracked_unignored_files(root))
        if offenders:
            _report_untracked(offenders)
            return 1
        return 0

    file_args = [arg for arg in argv if not arg.startswith("--")]
    paths = (
        _tracked_files(root) if ("--tracked" in argv or not file_args) else file_args
    )
    offenders = classify_tracked_paths(paths)
    if offenders:
        _report_tracked(offenders)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
