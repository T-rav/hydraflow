"""Which configured GC roots hold directories that enumeration cannot reach.

`WorkspaceGCLoop` Phase 5 discovers worktrees with `git worktree list` run at
`config.repo_root`. That is a deliberate blast-radius property, not an
oversight: enumeration is single-repo, so no other repository's files are ever
visible, and it is *why* the roots list can afford to name `repo_root.parent`
(`config.py`, `worktree_gc_root_paths`). Widening discovery to be cross-repo
would hand a background loop authority to delete inside repositories it was
never pointed at.

The defect is not the reach. It is that a root which is **configured, exists,
and holds directories, but from which discovery can never produce a single
candidate** is indistinguishable in the logs from a root that is genuinely
clean. Measured on the running instance (#11931): five of seven roots
enumerated zero worktrees while holding thirteen directories, and 26 worktrees
reached 14 GB with no signal at all (#11908) — the misdiagnosis that followed
landed on the wrong function precisely because "nothing found" and "I could not
look" read identically.

This module answers only the reporting question. It never widens what is
swept and never decides anything is deletable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from workspace_gc_landed_safety import path_within

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Sequence
    from pathlib import Path


def unenumerable_roots(
    roots: Sequence[Path],
    enumerated: Sequence[Path],
    *,
    dir_count: Callable[[Path], int],
) -> list[tuple[Path, int]]:
    """``(root, dirs_on_disk)`` for roots holding dirs but enumerating nothing.

    **Pure over its inputs**: the filesystem read arrives as *dir_count* so the
    predicate is testable without a disk, and so a caller that cannot stat a
    root can decide what zero means for itself.

    A root with no directories is silent — that is the decoy case, and it is
    the reason this cannot simply warn on "enumerated zero". Most roots are
    legitimately empty most of the time; warning on those trains an operator to
    ignore the warning, which is the same outcome as not emitting it.
    """
    findings: list[tuple[Path, int]] = []
    for root in roots:
        if any(path_within(path, root) for path in enumerated):
            continue
        count = dir_count(root)
        if count > 0:
            findings.append((root, count))
    return findings


def describe_unenumerable(findings: Sequence[tuple[Path, int]]) -> str:
    """One operator-readable line naming each root and its on-disk count."""
    return ", ".join(f"{root} ({count} dirs)" for root, count in findings)
