"""Regression: durable ``hydraflow-in-progress`` build-claim marker (#10168).

Before #10168 the label state machine went ``hydraflow-ready`` → (whole build)
→ ``hydraflow-review`` with no claim label in between. The only double-pick
protection was ``IssueStore._eagerly_transitioned`` — in-memory, single-process
— so a second factory instance / parallel operator session / out-of-band Agent
dispatch reading GitHub saw an unclaimed ready issue and could build it too
(the #10141 cross-actor collision).

This pins the load-bearing invariants of the fix so a future refactor can't
silently drop them:

1. ``in_progress_label`` defaults to ``["hydraflow-in-progress"]``.
2. The claim is a member of ``all_pipeline_labels`` — so every
   ``swap_pipeline_labels`` (notably ready→review at PR-open) clears it and an
   issue can never get stuck claimed.
3. It is guarded from IssueRefinement auto-close (an actively-building issue is
   never closed out from under its builder).
4. ``IssueStore._is_eligible`` skips an issue carrying the claim (the durable
   cross-actor belt-and-suspenders).
5. ``find_label_drift`` treats a ``ready + in-progress`` issue as ``ready`` —
   the claim marker is not mistaken for a pipeline stage.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from events import EventBus
from issue_store import IssueStore
from models import Task

_CLAIM = "hydraflow-in-progress"


def _store(ready_label: str) -> IssueStore:
    config = HydraFlowConfig(ready_label=[ready_label])
    return IssueStore(config, AsyncMock(), EventBus())


def test_in_progress_label_default() -> None:
    assert HydraFlowConfig().in_progress_label == [_CLAIM]


def test_claim_is_in_all_pipeline_labels_so_swaps_clear_it() -> None:
    # Membership is what makes the ready→review swap (and any escalation /
    # route-back swap) drop the claim — the guarantee it can't get stuck.
    assert _CLAIM in HydraFlowConfig().all_pipeline_labels


def test_claim_guarded_from_issue_refinement_autoclose() -> None:
    from issue_refinement import GUARDRAIL_SKIP_LABELS

    assert _CLAIM in GUARDRAIL_SKIP_LABELS
    # And the config-drift ratchet the guardrail rides on still holds.
    assert set(HydraFlowConfig().all_pipeline_labels) <= GUARDRAIL_SKIP_LABELS


def test_work_picker_skips_claimed_issue() -> None:
    store = _store("hydraflow-ready")
    store._route_issues(
        [Task(id=1, title="t", body="b", tags=["hydraflow-ready", _CLAIM])]
    )
    assert store.get_implementable(10) == []


def test_work_picker_returns_unclaimed_sibling() -> None:
    store = _store("hydraflow-ready")
    store._route_issues(
        [
            Task(id=1, title="t", body="b", tags=["hydraflow-ready", _CLAIM]),
            Task(id=2, title="t", body="b", tags=["hydraflow-ready"]),
        ]
    )
    assert [t.id for t in store.get_implementable(10)] == [2]


@pytest.mark.asyncio
async def test_find_label_drift_reads_claimed_issue_as_ready() -> None:
    # A ready+in-progress issue with an open review PR must classify as the
    # ordinary pr_ahead_of_issue drift (issue behind its PR), NOT be mistaken
    # for a stage because the claim marker sorts first in the label set.
    from mockworld.fakes.fake_github import FakeGitHub

    gh = FakeGitHub()
    gh.add_issue(1, "t", "b", labels=["hydraflow-ready", _CLAIM])
    gh.add_pr(number=10, issue_number=1, branch="agent/issue-1")
    gh.add_pr_label(10, "hydraflow-review")  # PR moved ahead; issue still ready

    drift = await gh.find_label_drift()

    assert len(drift) == 1
    # The claim marker was excluded, so the issue reads as its true stage.
    assert drift[0].issue_label == "hydraflow-ready"
    assert drift[0].kind == "pr_ahead_of_issue"
