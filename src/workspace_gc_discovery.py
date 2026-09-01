"""Worktree enumeration across every sibling clone of this project (#11931).

Separated from ``WorkspaceGCLoop`` because it answers a different question.
The loop owns cadence, policy and every destructive action; this owns only
*what exists* — which checkouts of this project are on disk, and which
worktrees they register. It decides nothing about whether any of them may be
removed, and it runs no destructive command.

The split is also what keeps the loop under the god-class threshold: adding
discovery inline pushed it to 662 LOC / 18 methods and the mass ratchet
refused it, correctly.

Git is injected as ``run_git`` rather than imported, so the whole module is
testable without a repository and cannot reach a subprocess this file chose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from workspace_gc_landed_safety import (
    WorktreeEntry,
    child_directories,
    normalized_remote,
    parse_git_worktrees,
    repo_root_from_common_dir,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import logging
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    RunGit = Callable[..., Awaitable[str]]


async def sibling_clones(
    *,
    primary: Path,
    roots: Sequence[Path],
    run_git: RunGit,
    logger: logging.Logger,
) -> list[Path]:
    """Every checkout of THIS project that owns a directory under a root.

    ``git worktree list`` reports only the worktrees of the repo it runs in, so
    worktrees living in another clone were invisible at any predicate width.
    This finds those clones: each root's direct children are asked who owns them
    via ``--git-common-dir``, the one command that answers from inside a linked
    worktree — ``--show-toplevel`` returns the linked worktree itself and would
    send enumeration back where it started.

    Scoped to SIBLINGS by remote. ``repo_root.parent`` is a configured root and
    on a developer machine that directory holds dozens of unrelated projects;
    discovering repos without this filter would turn one project's collector
    into a collector for everything the operator owns, which no amount of
    per-candidate proof makes acceptable. A clone whose remote does not match,
    or that has none, is skipped — not assumed safe.
    """
    clones: dict[Path, None] = {primary: None}
    try:
        ours = normalized_remote(
            await run_git("remote", "get-url", "origin", cwd=primary)
        )
    except (RuntimeError, OSError):
        logger.warning("GC: could not read this repo's origin — primary only")
        return list(clones)
    if not ours:
        return list(clones)

    for child in child_directories(roots):
        try:
            owner = repo_root_from_common_dir(
                await run_git("rev-parse", "--git-common-dir", cwd=child), cwd=child
            )
        except (RuntimeError, OSError):
            continue  # not a checkout, or unreadable — owns nothing here
        if owner is None or owner in clones:
            continue
        try:
            theirs = normalized_remote(
                await run_git("remote", "get-url", "origin", cwd=owner)
            )
        except (RuntimeError, OSError):
            continue
        if theirs and theirs == ours:
            clones[owner] = None
    return list(clones)


async def enumerate_worktrees(
    *,
    primary: Path,
    roots: Sequence[Path],
    run_git: RunGit,
    logger: logging.Logger,
    include_siblings: bool,
) -> list[WorktreeEntry]:
    """Registered worktrees across the primary repo and its sibling clones.

    The PRIMARY repo's failure PROPAGATES, unchanged: if this repo cannot be
    enumerated the sweep must not proceed on a partial picture. A SECONDARY
    clone's failure is logged and skipped instead — one unreadable checkout
    must not hold a veto over collecting all the others.
    """
    entries: dict[Path, WorktreeEntry] = {}
    for entry in parse_git_worktrees(
        await run_git("worktree", "list", "--porcelain", cwd=primary)
    ):
        entries.setdefault(entry.path, entry)

    if not include_siblings:
        return list(entries.values())

    for clone in await sibling_clones(
        primary=primary, roots=roots, run_git=run_git, logger=logger
    ):
        if clone == primary:
            continue
        try:
            output = await run_git("worktree", "list", "--porcelain", cwd=clone)
        except (RuntimeError, OSError):
            logger.warning(
                "GC: could not enumerate worktrees in sibling clone %s", clone
            )
            continue
        for entry in parse_git_worktrees(output):
            entries.setdefault(entry.path, entry)
    return list(entries.values())
