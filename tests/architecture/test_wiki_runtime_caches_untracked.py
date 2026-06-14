"""Runtime wiki caches must stay untracked — they are rewritten every loop tick.

``docs/wiki/log.jsonl`` (ingest log), ``docs/wiki/ingest_dedup.json`` (dedup
cache), and ``docs/wiki/index.json`` (machine index) are runtime state the
``RepoWikiLoop`` rewrites on every cycle. Tracking them means the factory's
working tree is *permanently* dirty: each maintenance PR is built in an ephemeral
worktree (``auto_pr.open_automated_pr_async``) that never cleans the originals in
``repo_root``, and these three churn faster than any PR cadence. They are
recreated on demand and read from disk at runtime (no consumer needs the
committed copy — verified: no mkdocs/CI/test references the repo copy), so this
guard keeps them out of git to stop the perpetual-dirt footgun.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Runtime caches that must never be git-tracked.
RUNTIME_CACHES = (
    "docs/wiki/log.jsonl",
    "docs/wiki/ingest_dedup.json",
    "docs/wiki/index.json",
)


@pytest.mark.parametrize("path", RUNTIME_CACHES)
def test_runtime_cache_not_git_tracked(real_repo_root: Path, path: str) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        check=False,
        cwd=real_repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"{path} is git-tracked but it is runtime state the wiki loop rewrites "
        "every tick — untrack it (git rm --cached) and add it to .gitignore."
    )


@pytest.mark.parametrize("path", RUNTIME_CACHES)
def test_runtime_cache_is_gitignored(real_repo_root: Path, path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", path],
        check=False,
        cwd=real_repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{path} is not gitignored; add it so the loop's rewrites do not dirty "
        "the working tree."
    )
