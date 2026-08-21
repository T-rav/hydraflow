"""Regression pin for #11480: stall re-slice machinery could decompose an
issue whose fix already landed on the base branch.

Incident: the stall handler for a parent issue created re-slice children
(#11464-11466 under epic #11463) even though a fix commit ("Fixes #11427")
had already landed on staging earlier the same day -- the parent then
auto-closed 5 seconds after the children were minted. The re-slice path
never checked whether a fix for the stalled issue had already landed before
decomposing it. This pins the fix: ``decompose_or_escalate`` now scans (a)
the base branch's recent commit history (``PRPort.list_branch_commits``)
and (b) this tick's already-gathered ``PreflightContext.recent_commits``
for a GitHub closing-keyword reference to the stalled issue before ever
consulting the decomposition council, and skips re-slicing entirely when
either channel finds one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mockworld.fakes.fake_github import FakeGitHub  # noqa: E402
from preflight.context import PreflightContext  # noqa: E402
from preflight.decompose_terminal import decompose_or_escalate  # noqa: E402
from subprocess_util import CreditExhaustedError  # noqa: E402
from tests.helpers import ConfigFactory, make_tracker  # noqa: E402


def _ctx(issue_number: int) -> PreflightContext:
    return PreflightContext(
        issue_number=issue_number,
        issue_body="Stalled issue body",
        issue_comments=[],
        sub_label="flaky-test-stuck",
        escalation_context=None,
        wiki_excerpts="",
        sentry_events=[],
        recent_commits=[],
    )


async def test_landed_fix_on_base_branch_skips_reslice(tmp_path: Path) -> None:
    """A closing-keyword commit already on the base branch must stop the
    stall terminal from manufacturing an epic + children for a stalled
    issue whose fix is already done (#11480)."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    issue_number = 11427
    prs.add_issue(issue_number, "Stalled issue", "body")
    prs.add_gc_branch(
        config.base_branch(),
        [
            {
                "date": "2026-08-18T07:08:00Z",
                "message": "Fixes #11427: retry-cap arithmetic",
            }
        ],
    )
    state = make_tracker(tmp_path)
    decomposer = AsyncMock()
    council = AsyncMock()
    council.decide = AsyncMock(
        side_effect=AssertionError(
            "the council must never run once a landed-fix commit is found"
        )
    )

    issue_count_before = len(prs._issues)

    outcome = await decompose_or_escalate(
        issue_number=issue_number,
        ctx=_ctx(issue_number),
        config=config,
        decomposer=decomposer,
        council=council,
        state=state,
        prs=prs,
    )

    assert outcome == "decomposed", (
        "a landed fix must short-circuit the terminal the same way an "
        "already-decomposed issue does -- the caller must NOT escalate to "
        "human-required"
    )
    council.decide.assert_not_called()
    decomposer.create_epic_from_result.assert_not_called()
    # No re-slice children (or epic) were manufactured for already-finished
    # work -- the issue count is unchanged.
    assert len(prs._issues) == issue_count_before


async def test_closing_ref_for_a_different_issue_still_decomposes(
    tmp_path: Path,
) -> None:
    """Specificity boundary (#11480): a landed closing-keyword commit exists
    on the base branch, but it closes a DIFFERENT issue than the one
    stalled -- the guard must not treat "some fix landed" as evidence for
    THIS issue, and the council must still run."""
    from models import EpicDecompResult, NewIssueSpec

    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    issue_number = 11427
    prs.add_issue(issue_number, "Stalled issue", "body")
    prs.add_gc_branch(
        config.base_branch(),
        [
            {
                "date": "2026-08-18T07:08:00Z",
                "message": "Fixes #11428: an entirely different issue",
            }
        ],
    )
    epic_manager = AsyncMock()
    epic_manager.register_epic = AsyncMock()
    state = make_tracker(tmp_path)
    decomposer = AsyncMock()
    decomposer.create_epic_from_result = AsyncMock(return_value=501)
    council = AsyncMock()
    council.decide = AsyncMock(
        return_value=EpicDecompResult(
            should_decompose=True,
            epic_title="Epic: split the stalled issue",
            epic_body="## Sub-issues",
            children=[
                NewIssueSpec(title="Child 1", body="Do 1"),
                NewIssueSpec(title="Child 2", body="Do 2"),
            ],
            reasoning="Too broad for one autonomous pass",
            confidence="high",
        )
    )

    outcome = await decompose_or_escalate(
        issue_number=issue_number,
        ctx=_ctx(issue_number),
        config=config,
        decomposer=decomposer,
        council=council,
        state=state,
        prs=prs,
    )

    assert outcome == "decomposed"
    council.decide.assert_awaited_once()
    decomposer.create_epic_from_result.assert_awaited_once()


@pytest.mark.parametrize("scan_failure", [RuntimeError("gh api unavailable")])
async def test_scan_failure_does_not_block_the_existing_terminal(
    tmp_path: Path, scan_failure: Exception
) -> None:
    """The landed-fix pre-check is an optimization layered in front of the
    existing decompose/escalate terminal (#11480); if the scan itself
    breaks with an ordinary transient error, decomposition must proceed
    exactly as it did before this guard existed -- never silently escalate
    or block on a scan bug."""
    from models import EpicDecompResult, NewIssueSpec

    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = AsyncMock()
    prs.find_open_pr_for_branch = AsyncMock(return_value=None)
    prs.get_pr_diff_names = AsyncMock(return_value=[])
    prs.close_pr = AsyncMock()
    prs.list_branch_commits = AsyncMock(side_effect=scan_failure)
    state = make_tracker(tmp_path)
    decomposer = AsyncMock()
    decomposer.create_epic_from_result = AsyncMock(return_value=501)
    council = AsyncMock()
    council.decide = AsyncMock(
        return_value=EpicDecompResult(
            should_decompose=True,
            epic_title="Epic: split the stalled issue",
            epic_body="## Sub-issues",
            children=[
                NewIssueSpec(title="Child 1", body="Do 1"),
                NewIssueSpec(title="Child 2", body="Do 2"),
            ],
            reasoning="Too broad for one autonomous pass",
            confidence="high",
        )
    )

    outcome = await decompose_or_escalate(
        issue_number=7,
        ctx=_ctx(7),
        config=config,
        decomposer=decomposer,
        council=council,
        state=state,
        prs=prs,
    )

    assert outcome == "decomposed"
    council.decide.assert_awaited_once()
    decomposer.create_epic_from_result.assert_awaited_once()


async def test_credit_exhausted_during_scan_propagates_uncaught(
    tmp_path: Path,
) -> None:
    """A credit-exhaustion signal raised mid-scan is NOT an ordinary
    transient failure (#11480) -- it must propagate out of
    ``decompose_or_escalate`` uncaught, matching every other broad
    ``except Exception`` handler in this module (``reraise_on_credit_or_bug``,
    docs/wiki/dark-factory.md §2.2), or the orchestrator's global
    credit-pause signal is silently eaten and the loop keeps burning attempt
    budget against an exhausted billing signal."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = AsyncMock()
    prs.find_open_pr_for_branch = AsyncMock(return_value=None)
    prs.get_pr_diff_names = AsyncMock(return_value=[])
    prs.close_pr = AsyncMock()
    prs.list_branch_commits = AsyncMock(
        side_effect=CreditExhaustedError("credits exhausted")
    )
    state = make_tracker(tmp_path)
    decomposer = AsyncMock()
    council = AsyncMock()
    council.decide = AsyncMock(
        side_effect=AssertionError("council must not run once credits raise")
    )

    with pytest.raises(CreditExhaustedError, match="credits exhausted"):
        await decompose_or_escalate(
            issue_number=7,
            ctx=_ctx(7),
            config=config,
            decomposer=decomposer,
            council=council,
            state=state,
            prs=prs,
        )

    council.decide.assert_not_called()
