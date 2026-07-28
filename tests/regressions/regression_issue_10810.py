"""Regression guard for PR #10810 — kill the wiki self-maintenance flux.

`RepoWikiLoop` fires whenever there are pending ``ingest-entry`` maintenance
tasks, and those tasks are promoted on every pipeline merge by the reflection
bridge in ``PostMergeHandler._run_post_merge_hooks``. When the merged item was
the factory's OWN self-maintenance chore (a ``chore(wiki)/chore(arch)/
chore(rc)/feat(ul)`` title, or a ``hydraflow/wiki-maint-*`` / ``arch-regen-auto``
/ ``ul-*`` / ``rc/`` branch), that promotion made the wiki document its own
busywork: self-chore merge -> ingest-entry -> another ``chore(wiki):
maintenance`` PR -> merge -> reflect again (4 such PRs observed in one 5.5h IDLE
window).

The fix gates the wiki reflection / shipped-gap emission on
``factory_maintenance.is_factory_self_maintenance``. These guards pin the two
halves of the contract:

- a self-maintenance merge enqueues **no** wiki ``ingest-entry`` (and its
  reflection log is dropped, not accumulated), while
- a genuine ``feat``/``fix`` merge still enqueues its reflection ingest so the
  wiki stays current on meaningful product change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus
from post_merge_handler import PostMergeHandler
from reflections import append_reflection, read_reflections
from repo_wiki import RepoWikiStore
from state import StateTracker
from wiki_maint_queue import MaintenanceQueue, default_queue_path

if TYPE_CHECKING:
    from config import HydraFlowConfig

ISSUE_NUMBER = 4242
PR_NUMBER = 9999


def _handler_with_wiki(config: HydraFlowConfig) -> PostMergeHandler:
    """A PostMergeHandler wired with a wiki store/compiler and no other hooks.

    Only the wiki-ingest path is exercised; every other post-merge hook is
    disabled (None) so the guard is tested in isolation.
    """
    return PostMergeHandler(
        config=config,
        state=StateTracker(config.state_file),
        prs=AsyncMock(),
        event_bus=EventBus(),
        ac_generator=None,
        retrospective=None,
        verification_judge=None,
        epic_checker=None,
        wiki_store=RepoWikiStore(config.repo_root / "wiki"),
        wiki_compiler=MagicMock(),
    )


def _queued(config: HydraFlowConfig) -> list:
    return MaintenanceQueue(path=default_queue_path(config)).peek()


def _pr(config: HydraFlowConfig, *, branch: str):
    from models import PRInfo  # noqa: PLC0415

    return PRInfo(
        number=PR_NUMBER,
        issue_number=ISSUE_NUMBER,
        branch=branch,
        url=f"https://github.com/test-org/test-repo/pull/{PR_NUMBER}",
    )


def _issue(*, title: str, tags: list[str] | None = None):
    from models import Task  # noqa: PLC0415

    return Task(id=ISSUE_NUMBER, title=title, body="", tags=tags or [])


def _result():
    from models import ReviewResult, ReviewVerdict  # noqa: PLC0415

    return ReviewResult(
        pr_number=PR_NUMBER,
        issue_number=ISSUE_NUMBER,
        verdict=ReviewVerdict.APPROVE,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("branch", "title", "tags"),
    [
        # Branch-prefix signal: the RepoWikiLoop's own maintenance branch.
        ("hydraflow/wiki-maint-20260728", "chore(wiki): maintenance 2026-07-28", None),
        # Branch-prefix signal: DiagramLoop's fixed regen branch.
        ("arch-regen-auto", "chore(arch): regenerate architecture knowledge", None),
        # Title-scope signal on a normal pipeline branch (agent/issue-N).
        ("agent/issue-4242", "feat(ul): term-proposer batch — 3 drafts", None),
        # Label signal on a normal pipeline branch.
        ("agent/issue-4242", "regenerate coverage", ["hydraflow-ready", "arch-regen"]),
    ],
)
async def test_self_maintenance_merge_does_not_ingest_into_wiki(
    config: HydraFlowConfig,
    branch: str,
    title: str,
    tags: list[str] | None,
) -> None:
    handler = _handler_with_wiki(config)
    append_reflection(
        config, ISSUE_NUMBER, phase="implement", content="must not reach the wiki"
    )

    await handler._run_post_merge_hooks(
        _pr(config, branch=branch), _issue(title=title, tags=tags), _result(), "diff"
    )

    # No ingest-entry was enqueued, and the reflection log was dropped so it
    # cannot accumulate and leak into a later tick.
    assert _queued(config) == []
    assert read_reflections(config, ISSUE_NUMBER) == ""


@pytest.mark.asyncio
async def test_genuine_feature_merge_still_ingests_into_wiki(
    config: HydraFlowConfig,
) -> None:
    handler = _handler_with_wiki(config)
    append_reflection(
        config,
        ISSUE_NUMBER,
        phase="implement",
        content="gotcha: guard the port against None before dereferencing",
    )

    await handler._run_post_merge_hooks(
        _pr(config, branch="agent/issue-4242"),
        _issue(title="feat: add the widget endpoint", tags=["ready"]),
        _result(),
        "diff",
    )

    tasks = _queued(config)
    assert len(tasks) == 1
    assert tasks[0].kind == "ingest-entry"
    # A successful promote clears the reflection log.
    assert read_reflections(config, ISSUE_NUMBER) == ""
