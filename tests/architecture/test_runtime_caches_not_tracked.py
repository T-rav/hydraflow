"""Proactive guard: no runtime cache/artifact may dirty the tracked tree (#9599).

Generalizes the reactive #9537 fix (``tests/architecture/test_wiki_runtime_caches_untracked.py``,
which pins three specific ``docs/wiki`` caches). Runtime state a background loop
rewrites every tick must live under the gitignored ``data_root`` (``.hydraflow/``)
or be gitignored — never committed to the tracked tree.

Two failure modes are covered:

* **Mode a (tracked-churn):** a cache-shaped file is git-tracked. Runs the pure
  ``classify_tracked_paths`` engine over the live ``git ls-files`` output and
  asserts zero offenders. Fails loudly (listing offenders + remediation) if a
  runtime cache is ever tracked again.
* **Mode b (untracked-dirt):** ``FitnessScorecardLoop`` writes
  ``docs/arch/generated/loop-fitness.md`` into the live repo root every tick. It
  was neither tracked nor gitignored, leaving a permanent ``??`` in
  ``git status`` (found 2026-07-19). Asserts it is now gitignored so the loop's
  rewrites cannot dirty the working tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_runtime_cache_tracked.py"
)
_spec = importlib.util.spec_from_file_location("check_runtime_cache_tracked", _SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_runtime_cache_tracked"] = guard
_spec.loader.exec_module(guard)

# The three #9537 caches — the general guard must remain a superset of the
# hard-coded regression that first untracked them.
WIKI_9537_CACHES = (
    "docs/wiki/log.jsonl",
    "docs/wiki/ingest_dedup.json",
    "docs/wiki/index.json",
)

# The mode-b live offender fixed by this issue (#9599 groom 2026-07-19).
UNTRACKED_LOOP_ARTIFACT = "docs/arch/generated/loop-fitness.md"


def _tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        check=True,
        cwd=root,
        capture_output=True,
        text=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def test_no_runtime_cache_is_git_tracked(real_repo_root: Path) -> None:
    offenders = guard.classify_tracked_paths(_tracked_files(real_repo_root))
    assert offenders == [], (
        "Runtime cache files are git-tracked — they churn every loop tick and "
        "leave the working tree perpetually dirty. Untrack each "
        "(git rm --cached <path>) and add it to .gitignore, or, if legitimately "
        f"tracked, add it to ALLOWLIST in {_SCRIPT.name} with a justification:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", WIKI_9537_CACHES)
def test_general_guard_flags_the_9537_caches(path: str) -> None:
    assert guard.classify_tracked_paths([path]) == [path]


def test_loop_fitness_artifact_is_gitignored(real_repo_root: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", UNTRACKED_LOOP_ARTIFACT],
        check=False,
        cwd=real_repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{UNTRACKED_LOOP_ARTIFACT} is not gitignored. FitnessScorecardLoop "
        "rewrites it into the live repo root every tick; without a .gitignore "
        "rule it shows as a permanent '??' in git status. Add it to .gitignore."
    )
