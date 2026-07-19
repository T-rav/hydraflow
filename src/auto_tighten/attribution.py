from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Pragmatic fallback lookback when git history for the baseline file is
# unavailable (no repo, file never committed, git missing from PATH, etc).
# Attribution failure safely HOLDS (no tightening) downstream — an
# imperfect/wider window here is safe, not dangerous, so a fixed lookback
# beats blocking tightening entirely on git plumbing being present.
_FALLBACK_LOOKBACK = timedelta(days=30)


class AttributionResolver:
    def __init__(self, list_merged_prs: Callable[[str], list[dict]]) -> None:
        self._list = list_merged_prs

    def attribute(self, paths_of_interest: list[str], since_iso: str) -> int | None:
        for pr in self._list(since_iso):
            for f in pr.get("files", []):
                if any(f.startswith(p) for p in paths_of_interest):
                    return int(pr["number"])
        return None


def baseline_since(repo_root: Path, rel_path: str) -> str:
    """Return an ISO-8601 lower bound for the attribution scan window.

    Prefers the committer date of the last commit that touched *rel_path*
    (via ``git log -1 --format=%cI``), since that's the most precise signal
    for "when did the current baseline value take effect". Falls back to a
    fixed lookback window when git is unavailable, the path was never
    committed, or the directory isn't a git repo at all — attribution
    failure is a safe HOLD (no tightening), so a wider fallback window is
    conservative rather than risky.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", rel_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ):
        return _fallback_since()

    stamp = result.stdout.strip()
    if not stamp:
        return _fallback_since()
    return stamp


def _fallback_since() -> str:
    return (datetime.now(UTC) - _FALLBACK_LOOKBACK).isoformat()
