"""#11480: the stall re-slice path must not decompose an issue whose fix landed.

Reproduces #11427's timeline against a real ``FakeGitHub`` world:

* 13:10 — the auto-agent opens PR #11461 on ``agent/auto-agent-11427``,
  titled ``Fixes #11427: ...``. Its CI is still running.
* 13:38 — the auto-agent's attempt cap (which trips on attempt *count*, never
  on attempt *outcome*) routes the issue to the decompose terminal, which
  created epic #11463 + re-slice children #11464/65/66.
* 14:06 — PR #11461 merges. The children were re-slices of work that was
  already complete: a full planning/implementation cycle burned.

Two properties are pinned here, both of which were false before #11480:

1. Zero issues are created — no epic, no children (``prs.create_issue`` is
   spied, so the assertion names the exact production call).
2. The in-flight PR is not closed as superseded.

The still-running CI is load-bearing, not incidental: it is why #10260's
green-PR dispatch guard did NOT suppress the dispatch at 13:38, and thus why
the terminal needed its own work-already-done gate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from base_background_loop import LoopDeps
from events import EventBus
from mockworld.fakes import FakeGitHub
from tests.helpers import ConfigFactory, make_tracker

ISSUE = 11427
PR = 11461


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *_a, **_k: None,
        enabled_cb=lambda _name: True,
    )


def _world(tmp_path: Path, *, check_state: str):
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    gh = FakeGitHub()
    gh.add_issue(
        ISSUE,
        "Stall re-slice machinery decomposes landed work",
        "The frobnicator never converges.",
        labels=["hitl-escalation", "flaky-test-stuck"],
    )
    gh.add_pr(
        number=PR,
        issue_number=ISSUE,
        branch=config.auto_agent_branch_for_issue(ISSUE),
        title=f"Fixes #{ISSUE}: stop the frobnicator from stalling",
        body=f"Fixes #{ISSUE}",
        checks=[("quality", check_state)],
    )
    state = make_tracker(tmp_path)
    for _ in range(config.auto_agent_max_attempts):
        state.bump_auto_agent_attempts(ISSUE)

    council = AsyncMock()
    council.decide = AsyncMock(
        side_effect=AssertionError("the council must not be asked about landed work")
    )
    audit = MagicMock()
    audit.daily_spend = MagicMock(return_value=0.0)
    loop = AutoAgentPreflightLoop(
        config=config,
        state=state,
        pr_manager=gh,
        wiki_store=None,
        audit_store=audit,
        deps=_deps(),
    )
    from issue_decomposer import IssueDecomposer

    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock()
    loop._decomposer = IssueDecomposer(gh, epic_manager, state, config)
    loop._council = council
    return loop, gh


@pytest.mark.asyncio
async def test_landed_fix_on_auto_agent_branch_creates_no_reslice_children(
    tmp_path: Path,
) -> None:
    loop, gh = _world(tmp_path, check_state="IN_PROGRESS")
    create_issue = AsyncMock(side_effect=AssertionError("no issue may be created"))
    gh.create_issue = create_issue  # type: ignore[method-assign]

    result = await loop._do_work()

    assert result is not None
    assert result["result_status"] == "skipped_already_satisfied"
    create_issue.assert_not_awaited()
    # Only the original issue exists: no epic #11463, no children.
    assert list(gh._issues) == [ISSUE]
    # The in-flight fix was not superseded, and the issue was not paged out
    # to a human either.
    assert gh._prs[PR].closed is False
    assert "human-required" not in gh.issue(ISSUE).labels


@pytest.mark.asyncio
async def test_liveness_red_ci_pr_on_the_same_branch_still_decomposes(
    tmp_path: Path,
) -> None:
    """Counter-pin: the gate keys on the fix being viable, not on a PR merely
    existing. A red-CI PR on the same branch IS the stall, and must still be
    re-sliced — otherwise #11480's fix silently disables the stall path."""
    from models import EpicDecompResult, NewIssueSpec

    loop, gh = _world(tmp_path, check_state="FAILURE")
    loop._council.decide = AsyncMock(  # type: ignore[union-attr]
        return_value=EpicDecompResult(
            should_decompose=True,
            epic_title="Epic: split the stalled issue",
            epic_body="## Sub-issues",
            children=[
                NewIssueSpec(title="Narrower slice A", body="A."),
                NewIssueSpec(title="Narrower slice B", body="B."),
            ],
            reasoning="Too broad for one autonomous pass",
        )
    )

    result = await loop._do_work()

    assert result is not None
    assert result["result_status"] == "skipped_decomposed"
    assert len(gh._issues) > 1  # epic + children
    assert gh._prs[PR].closed is True  # superseded, as designed
