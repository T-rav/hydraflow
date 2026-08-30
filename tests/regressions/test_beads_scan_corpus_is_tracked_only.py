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


# The scratch directories that made this a 30-minute failure, as PATH SEGMENTS
# anchored where they actually live. ``.claude/worktrees`` and ``.beads/dolt``
# are repo-root-relative; ``node_modules`` can nest at any depth.
_SCRATCH_PREFIXES = ((".claude", "worktrees"), (".beads", "dolt"))
_SCRATCH_ANYWHERE = ("node_modules",)


def _is_scratch(relative_posix: str) -> bool:
    """Is *relative_posix* (relative to the repo root) gitignored scratch?

    Takes a REPO-RELATIVE path on purpose. The first version of this predicate
    matched substrings of the ABSOLUTE path::

        if ".claude/worktrees" in p.as_posix()

    which asks a different question than the one the test name states. Agent
    worktrees are created by ``scripts/hf_worktree.sh`` *under*
    ``<repo>/.claude/worktrees/`` — that is the #11729 fix, and CLAUDE.md
    mandates it — so every tracked file of a sanctioned worktree has
    ``.claude/worktrees`` in its absolute path merely by living there. The
    predicate flagged the container instead of the contents, and local
    ``make quality`` failed for every agent following the documented workflow
    while passing in the primary checkout. Same class as the path-membership
    defects of #11669: a check that silently stops meaning what it says once
    its subject moves.

    Matching on SEGMENTS rather than substrings also stops a directory named
    ``my_node_modules_backup`` from reading as scratch.
    """
    parts = tuple(relative_posix.split("/"))
    if any(part in _SCRATCH_ANYWHERE for part in parts):
        return True
    return any(parts[: len(prefix)] == prefix for prefix in _SCRATCH_PREFIXES)


def test_the_corpus_excludes_the_worktree_scratch_that_caused_the_hang() -> None:
    """The specific directories that made this a 30-minute failure."""
    corpus = _tracked_paths(REPO_ROOT)
    offenders = [p for p in corpus if _is_scratch(p.relative_to(REPO_ROOT).as_posix())]
    assert not offenders, (
        "scratch directories are back in the scan corpus:\n  "
        + "\n  ".join(str(p) for p in offenders[:10])
    )


def test_the_scratch_predicate_reads_contents_not_the_container() -> None:
    """The predicate must fire on scratch IN the repo, not on the repo's own home.

    Anti-vacuity for the fix above: a predicate that simply returned ``False``
    would make the corpus test pass everywhere, including on the 1.5M-path
    corpus this whole file exists to prevent.
    """
    # Genuine scratch inside the repo — must still be caught.
    assert _is_scratch(".claude/worktrees/feature-x/tests/test_thing.py")
    assert _is_scratch(".beads/dolt/data.chunk")
    assert _is_scratch("src/ui/node_modules/pkg/index.js")

    # Files the repo actually ships, including from a checkout that HAPPENS to
    # live under .claude/worktrees/. These are repo-relative, so the container
    # is invisible here — which is the entire point of the fix.
    assert not _is_scratch("tests/regressions/test_beads_scan_corpus_is_tracked_only.py")
    assert not _is_scratch(".claude/agents/hydraflow-review-advisor.md")
    assert not _is_scratch(".claude/commands/hf.adr.md")
    assert not _is_scratch(".beads/README.md")
    assert not _is_scratch("my_node_modules_backup/keep.txt")
