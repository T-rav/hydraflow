"""Single read path for a change's plan (ADR-0149).

Six call sites built ``config.plans_dir / f"issue-{n}.md"`` by hand. They
call here instead, so the committed-file-first rule is stated once.

``.hydraflow/plans/`` becomes a cache: still written by the planner, still
the answer on a host that never checked the branch out, never the preferred
answer when the branch carries the file. The committed copy is the one the
gate verified and the one that travels with the PR; the cache is local
state that a GC sweep may reap.

Resolution goes through ``change_chain.resolve_chain_dir``, so a plan stays
readable after quarterly compaction moves it into
``docs/changes/archive/YYYY-Qn/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from change_chain import ChainArtifact, resolve_chain_dir

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from state import StateTracker

logger = logging.getLogger(__name__)


def read_plan(
    config: HydraFlowConfig, issue_number: int, *, worktree: Path | None = None
) -> str:
    """Return the plan text for *issue_number*, or "" when there is none.

    *worktree* is the checkout to search first — an issue worktree during
    implement and review, the primary repo afterwards. Callers that have no
    worktree in hand omit it and get ``config.repo_root``.
    """
    if worktree is not None:
        committed = _committed_plan(worktree, issue_number)
        if committed:
            return committed

    cached = _cached_plan(config, issue_number)
    if cached:
        return cached

    # Last resort: the primary checkout. Deliberately AFTER the cache, and
    # only when no worktree was given. Once issue N merges, ``repo_root``
    # carries ``docs/changes/issue-N/plan.md`` forever — so preferring it
    # would hand a re-opened, re-planned issue the plan of its own previous
    # attempt. In a worktree the committed file IS the in-flight plan and
    # wins outright; outside one, the cache is the fresher signal.
    return _committed_plan(config.repo_root, issue_number)


def _committed_plan(root: Path, issue_number: int) -> str:
    """The chain's committed plan under *root*, live or archived."""
    directory = resolve_chain_dir(root, issue_number)
    if directory is None:
        return ""
    try:
        return (directory / f"{ChainArtifact.PLAN.value}.md").read_text(
            encoding="utf-8"
        )
    except OSError:
        logger.debug(
            "Chain plan for issue #%d resolved but could not be read",
            issue_number,
            exc_info=True,
        )
        return ""


def _cached_plan(config: HydraFlowConfig, issue_number: int) -> str:
    """The planner's disk cache for *issue_number*."""
    try:
        return (config.plans_dir / f"issue-{issue_number}.md").read_text(
            encoding="utf-8"
        )
    except OSError:
        return ""


def active_worktree(state: StateTracker, issue_number: int) -> Path | None:
    """The live worktree for *issue_number*, or None.

    Lets a caller holding a StateTracker hand ``read_plan`` the checkout that
    actually carries the in-flight chain. Without it the committed-file rule
    is inert exactly where the chain is committed — ``config.repo_root`` sits
    on the integration branch and never carries an in-flight change's
    ``docs/changes/issue-N/``.
    """
    try:
        raw = state.get_active_workspaces().get(issue_number)
    except OSError:
        # A state read failure is a cache miss, not a crash: the caller falls
        # back to the plan cache. Deliberately NOT a bare getattr probe —
        # duck-typing this would turn a rename of get_active_workspaces into
        # a silent, permanent revert to pre-chain behaviour with no failing
        # test anywhere.
        logger.warning(
            "Could not read active workspaces for issue #%d",
            issue_number,
            exc_info=True,
        )
        return None
    return Path(raw) if raw else None
