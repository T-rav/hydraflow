"""Beads runtime state stays out of git, credential included.

`.beads/.gitignore` covered two JSONL-era patterns. Beads moved to a Dolt-backed
store and the ignore file never followed, so eleven runtime files sat untracked
and un-ignored in the repo root — permanent `??` noise in every `git status`
(the #9599 untracked-dirt failure), and a **credential** one `git add -A` away
from being committed by an RC-cut or worktree flow that stages blindly.

This is the guard that makes the next storage-layout change loud. The last one
was silent, which is how eleven files accumulated.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BEADS = _REPO_ROOT / ".beads"

#: Everything a running beads daemon writes. Named individually rather than
#: ignoring `.beads/` wholesale: the JSONL store and README ARE tracked, and a
#: blanket ignore would silently stop tracking them.
_RUNTIME_PATHS: tuple[str, ...] = (
    ".beads-credential-key",
    ".local_version",
    "dolt-server.lock",
    "dolt-server.pid",
    "dolt-server.port",
    "interactions.jsonl",
    "last-touched",
    "push-state.json",
    "dolt/data.db",
    "embeddeddolt/data.db",
    "backup/anything.jsonl",
    ".issues.jsonl.lock",
    ".issues.jsonl-tmp123.tmp",
)


def _is_ignored(rel: str) -> bool:
    """``git check-ignore`` against a path that need not exist."""
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", f".beads/{rel}"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.parametrize("rel", _RUNTIME_PATHS)
def test_beads_runtime_state_is_ignored(rel: str) -> None:
    assert _is_ignored(rel), (
        f".beads/{rel} is not ignored. Beads runtime state belongs out of git: "
        "it clutters every `git status`, and a blind `git add -A` in an RC-cut "
        "or worktree flow would commit it."
    )


def test_the_credential_is_ignored_and_has_never_been_committed() -> None:
    """The one that is not merely noise."""
    assert _is_ignored(".beads-credential-key")
    history = subprocess.run(
        ["git", "log", "--all", "--oneline", "--", ".beads/.beads-credential-key"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert not history, (
        "the beads credential key appears in git history — this is exposure, "
        f"not exposure risk, and the key needs rotating:\n{history}"
    )


def test_the_committed_store_is_still_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", ".beads/"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert ".beads/.gitignore" in tracked
    assert ".beads/README.md" in tracked


@pytest.mark.parametrize(
    "rel",
    ["README.md", "notes.md", "schema.sql", "a-new-thing-someone-adds.md"],
)
def test_the_ignore_is_scoped_not_a_blanket(rel: str) -> None:
    """The real negative control, and the first version of it was vacuous.

    That version asserted the store was still tracked — which stays true under
    a blanket ``.beads/`` ignore, because gitignore does not untrack anything
    already tracked. It passed with the mutation applied, testing nothing.

    What a blanket ignore actually breaks is the NEXT file: something that
    should be committed under ``.beads/`` becomes invisible instead of showing
    up as untracked. So the property is that a non-runtime path is NOT ignored.
    """
    assert not _is_ignored(rel), (
        f".beads/{rel} is ignored — the ignore has become a blanket. A file "
        "that should be committed here would now be invisible rather than "
        "untracked. Ignore the runtime paths individually."
    )


def test_beads_leaves_no_untracked_dirt() -> None:
    """The whole point, stated once: `git status` must be quiet."""
    dirt = subprocess.run(
        ["git", "status", "--porcelain", "--ignored=no", ".beads/"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    untracked = [ln for ln in dirt.splitlines() if ln.startswith("??")]
    assert not untracked, (
        "untracked, un-ignored files under .beads/:\n  " + "\n  ".join(untracked)
    )
