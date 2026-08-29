"""Regression: the beads runtime scan walked the working tree, not the repo.

`test_repo_runtime_has_no_database_backed_task_cli_path` built its corpus with
`rglob` over `repo/".claude"` and `repo/".beads"`. On a developer host that
pulled in 19 GB / 1,555,920 files of gitignored worktrees and a 206 MB
untracked Dolt database — 1,568,823 paths against the 13,498 the repo ships.

It was not merely slow (~102 s to walk, before reading a byte). The corpus it
produced FAILED, because worktree copies contain every literal the scan
forbids, including a copy of the scanning test itself. With `--reruns 2` the
whole thing ran three times and wedged one xdist worker for 30-50 minutes
while its siblings idled, with nothing in the output naming the test.

Pins the property that fixes it: the corpus comes from the COMMITTED tree, so
a gitignored path cannot enter it. This is the same ruling #11728 made for
"what is in the tree?"; the beads scan predated it and was the site it missed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.test_beads_manager import _tracked_paths  # noqa: E402


def test_the_scan_corpus_contains_no_gitignored_path() -> None:
    corpus = _tracked_paths(REPO_ROOT)

    # Anti-vacuity: an empty corpus would satisfy "nothing ignored" trivially.
    assert len(corpus) > 5000, (
        f"corpus is {len(corpus)} paths; too small to be the committed tree, "
        "and 'no ignored paths' would hold vacuously"
    )

    # git check-ignore exits 0 and echoes any path it would ignore. Feed the
    # whole corpus on stdin rather than per-path, so this stays one process.
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=REPO_ROOT,
        input="\n".join(str(p) for p in corpus),
        capture_output=True,
        text=True,
    )
    ignored = [line for line in proc.stdout.splitlines() if line.strip()]
    assert not ignored, (
        "the runtime scan corpus contains gitignored paths — it is walking the "
        "working tree again rather than the committed tree:\n  "
        + "\n  ".join(ignored[:10])
    )


def test_the_corpus_excludes_the_worktree_scratch_that_caused_the_hang() -> None:
    """The specific directories that made this a 30-minute failure."""
    corpus = _tracked_paths(REPO_ROOT)
    offenders = [
        p
        for p in corpus
        if ".claude/worktrees" in p.as_posix()
        or "node_modules" in p.as_posix()
        or "/.beads/dolt" in p.as_posix()
    ]
    assert not offenders, (
        "scratch directories are back in the scan corpus:\n  "
        + "\n  ".join(str(p) for p in offenders[:10])
    )
