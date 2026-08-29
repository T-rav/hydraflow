"""Regression: the worktree GC could not see where worktrees are created.

`WorkspaceGCLoop` phase 5 enumerates via `git worktree list`, then applies a
fail-closed blast-radius gate: a worktree is reaped only if its path sits under
one of `config.worktree_gc_root_paths()`. That list named agent-harness
directories, while `scripts/hf_worktree.sh <dir> <branch>` hands `<dir>` to
`git worktree add` VERBATIM — so the sanctioned workflow writes worktrees
beside or inside the checkout, which the list did not cover.

Measured on this repo 2026-08-29 (#11729): of 100 registered worktrees the GC
could reach 53. The other 47 accumulated from April onward — 37 GB — split
across the repo root (13), a sibling `<repo>-worktrees/` directory (25), the
checkout's parent (5) and `manual-repairs` (4).

A collector that cannot see where the creator writes is a GC that only looks
like one.

Deliberately pins the ROOT SET as a pure function of an explicitly-built
config, not a scan of this host. A first draft asserted over live
`git worktree list` output and passed vacuously under pytest, because
`tests/conftest.py` sandboxes HOME and the data root — so the config under test
was not the config that runs in production. Host state is not the subject; the
derivation is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from config import HydraFlowConfig  # noqa: E402


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


@pytest.fixture
def roots(tmp_path: Path) -> list[Path]:
    """Roots for a checkout at a known location, independent of this host."""
    checkout = tmp_path / "projects" / "myrepo"
    checkout.mkdir(parents=True)
    config = HydraFlowConfig(repo_root=checkout)
    return [r.expanduser() for r in config.worktree_gc_root_paths()]


@pytest.mark.parametrize(
    ("label", "relative"),
    [
        # The four places this repo's 47 orphans actually lived.
        ("the checkout itself", "wt-somebranch"),
        ("a sibling of the checkout", "../myrepo-worktrees/somebranch"),
        ("the checkout's parent", "../genpr-something"),
        ("the claude agent harness", ".claude/worktrees/agent-1"),
    ],
)
def test_the_gc_can_reach_where_worktrees_are_actually_created(
    roots: list[Path], tmp_path: Path, label: str, relative: str
) -> None:
    checkout = tmp_path / "projects" / "myrepo"
    candidate = (checkout / relative).resolve()
    assert any(_within(candidate, r) for r in roots), (
        f"a worktree in {label} ({candidate}) sits outside every GC root, so "
        "it can never be reaped — the #11729 signature"
    )


def test_home_harness_roots_are_still_covered(roots: list[Path]) -> None:
    """The original coverage must not be lost while widening."""
    home = Path.home()
    for candidate in (
        home / ".hydraflow" / "worktrees" / "x",
        home / ".hydraflow" / "dev" / "x",
        home / ".hydraflow" / "manual-repairs" / "x",
    ):
        assert any(_within(candidate, r) for r in roots), (
            f"{candidate} lost coverage while widening the root set"
        )


def test_an_explicit_override_still_wins_verbatim(tmp_path: Path) -> None:
    """`HYDRAFLOW_WORKTREE_GC_ROOTS` must remain the operator's final say."""
    checkout = tmp_path / "projects" / "myrepo"
    checkout.mkdir(parents=True)
    only = tmp_path / "only-here"
    config = HydraFlowConfig(repo_root=checkout, worktree_gc_roots=[str(only)])
    assert [Path(r) for r in config.worktree_gc_root_paths()] == [only], (
        "an explicit root list must win verbatim, so an operator can narrow "
        "the blast radius as well as widen it"
    )
