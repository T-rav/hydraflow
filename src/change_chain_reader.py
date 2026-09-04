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

logger = logging.getLogger(__name__)


def read_plan(
    config: HydraFlowConfig, issue_number: int, *, worktree: Path | None = None
) -> str:
    """Return the plan text for *issue_number*, or "" when there is none.

    *worktree* is the checkout to search first — an issue worktree during
    implement and review, the primary repo afterwards. Callers that have no
    worktree in hand omit it and get ``config.repo_root``.
    """
    root = worktree if worktree is not None else config.repo_root
    directory = resolve_chain_dir(root, issue_number)
    if directory is not None:
        committed = directory / f"{ChainArtifact.PLAN.value}.md"
        try:
            return committed.read_text()
        except OSError:
            logger.debug(
                "Chain plan for issue #%d exists but could not be read; "
                "falling back to the cache",
                issue_number,
                exc_info=True,
            )
    try:
        return (config.plans_dir / f"issue-{issue_number}.md").read_text()
    except OSError:
        return ""
