"""Regression pins for P3b of epic #10682 — the review phase on the flow primitive.

``ReviewPhase._review_one_inner`` is a structural refactor onto the P0
``src/flows`` DAG runtime (ADR-0111): the same per-PR review pipeline, now
expressed as an explicit ``Node``/``Edge`` graph

    guards -> pre-review -> pre-flight -> review -> post-review -> gate
        guards       --(issue-missing / merge-conflict)--> done
        pre-review   --(baseline block)-------------------> done
        gate         --(APPROVE handled by convergence gate)--> cleanup
        gate         --> route -> cleanup -> done

instead of a straight-line method. Review is a core phase and this ships with
NO feature flag, so parity is the only safety net.

These tests pin the load-bearing invariants of that cutover:

1. **Flow shape / node order.** The pipeline is an ``src.flows.Flow`` entered at
   ``guards``; a happy review walks ``guards -> pre-review -> pre-flight ->
   review -> post-review -> gate -> cleanup -> done`` with the reviewer (the LLM
   actuator / adversarial-review node) confined to ``review``.
2. **Output parity — approve/merge path.** A converged APPROVE merges the PR.
3. **Request-changes path.** A REQUEST_CHANGES verdict loops back (re-queue to
   ``ready``) and never merges.
4. **Convergence gate stops before approve.** Open code-scanning alerts make the
   gate's deterministic check RED → LOOP_BACK *before* the post-verify judge and
   the merge — the merge never fires and the judge never runs.
5. **Escalate / HITL.** A rejected review that exhausts the outer lap budget
   escalates to HITL instead of merging.
6. **Blocking review records the route-back signal.** ``review_prs`` mirrors a
   REQUEST_CHANGES verdict into the issue cache as ``has_blocking=True`` (the
   signal the downstream READY-stage gate uses).
7. **Fail-closed early exit.** An issue-not-found guard stops the walk at
   ``done`` without running the reviewer, the post-review tail, or worktree
   cleanup — exactly as the old early ``return`` did.

If any regress, the converted phase could drop a step, skip the convergence
gate, merge a PR the gate blocked, or silently change the delivered
``ReviewResult``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from flows import Flow
from models import CodeScanningAlert, ReviewVerdict
from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory
from tests.helpers import make_review_phase

if TYPE_CHECKING:
    from config import HydraFlowConfig

pytestmark = pytest.mark.asyncio

_HAPPY_ORDER = [
    "guards",
    "pre-review",
    "pre-flight",
    "review",
    "post-review",
    "gate",
    "cleanup",
    "done",
]


def _is_subsequence(sub: list[str], seq: list[str]) -> bool:
    """True if *sub* appears in *seq* in order (not necessarily contiguously)."""
    it = iter(seq)
    return all(item in it for item in sub)


# ---------------------------------------------------------------------------
# 1. Flow shape + node order
# ---------------------------------------------------------------------------


async def test_review_one_builds_a_flow_entered_at_guards(
    config: HydraFlowConfig,
) -> None:
    """The per-PR pipeline is an ``src.flows.Flow`` whose entry is ``guards``."""
    phase = make_review_phase(config, default_mocks=True)

    flow = phase._build_review_flow()

    assert isinstance(flow, Flow)
    assert flow.entry == "guards"


async def test_happy_path_node_order_confines_reviewer_to_review_node(
    config: HydraFlowConfig,
) -> None:
    """A successful review walks the documented order; reviewer runs in ``review``."""
    issue = TaskFactory.create(id=42)
    pr = PRInfoFactory.create(issue_number=42)
    phase = make_review_phase(config, default_mocks=True)

    recorded: list[str] = []
    flow = phase._build_review_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    result = await flow.run(
        phase._initial_review_state(0, pr, {42: issue}, "pr_review")
    )

    assert _is_subsequence(_HAPPY_ORDER, result.path)
    # Checkpoint fires once per node, in walk order (the resume substrate).
    assert recorded == result.path
    assert result.terminal == "done"
    # The primary reviewer (LLM actuator) fires exactly once, in ``review`` —
    # before ``post-review`` and the convergence ``gate``.
    phase._reviewers.review.assert_awaited_once()
    assert recorded.index("review") < recorded.index("post-review")
    assert recorded.index("review") < recorded.index("gate")


# ---------------------------------------------------------------------------
# 2. Output parity — approve/merge path
# ---------------------------------------------------------------------------


async def test_happy_path_approves_and_merges(config: HydraFlowConfig) -> None:
    """A converged APPROVE merges the PR (full review_prs path)."""
    phase = make_review_phase(config, default_mocks=True)
    issue = TaskFactory.create(id=42)
    pr = PRInfoFactory.create(issue_number=42)

    results = await phase.review_prs([pr], [issue])

    assert results[0].merged is True
    phase._prs.merge_pr.assert_awaited_once_with(101)


# ---------------------------------------------------------------------------
# 3. Request-changes path loops back, never merges
# ---------------------------------------------------------------------------


async def test_request_changes_path_loops_back_and_does_not_merge(
    config: HydraFlowConfig,
) -> None:
    """REQUEST_CHANGES → convergence loop-back (re-queue to ready), no merge."""
    phase = make_review_phase(
        config,
        default_mocks=True,
        review_result=ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES),
    )
    issue = TaskFactory.create(id=42)
    pr = PRInfoFactory.create(issue_number=42)

    results = await phase.review_prs([pr], [issue])

    assert results[0].merged is False
    phase._prs.merge_pr.assert_not_awaited()
    ledger = phase._state.get_convergence_ledger(42)
    assert ledger is not None
    assert ledger.stage_state["review"].last_verdict == "LOOP_BACK"


# ---------------------------------------------------------------------------
# 4. Convergence gate stops before the approve/merge
# ---------------------------------------------------------------------------


async def test_gate_stops_before_merge_on_code_scanning_alerts(
    config: HydraFlowConfig,
) -> None:
    """Open code-scanning alerts → gate det RED → LOOP_BACK before judge + merge.

    Pins the convergence gate node as the stop-before-approve boundary: an
    APPROVE verdict is NOT merged when the deterministic check is red, and the
    post-verify lens judge never runs.
    """
    phase = make_review_phase(config, default_mocks=True)
    phase._prs.fetch_code_scanning_alerts = AsyncMock(
        return_value=[CodeScanningAlert(number=1, severity="high", rule="xss")]
    )
    # The lens judge must never run when the deterministic check is RED.
    phase._run_post_verify_for_surface = AsyncMock()

    issue = TaskFactory.create(id=42)
    pr = PRInfoFactory.create(issue_number=42)  # verdict defaults to APPROVE

    results = await phase.review_prs([pr], [issue])

    assert results[0].merged is False
    phase._prs.merge_pr.assert_not_awaited()
    phase._run_post_verify_for_surface.assert_not_awaited()
    ledger = phase._state.get_convergence_ledger(42)
    assert ledger is not None
    assert ledger.stage_state["review"].last_verdict == "LOOP_BACK"


# ---------------------------------------------------------------------------
# 5. Escalate / HITL on lap-budget exhaustion
# ---------------------------------------------------------------------------


async def test_reject_escalates_to_hitl_on_lap_budget_exhaustion(
    config: HydraFlowConfig,
) -> None:
    """A rejected review that exhausts the outer lap budget escalates to HITL."""
    config.max_review_fix_attempts = 100  # keep the attempt cap out of the way
    config.max_convergence_laps = 1  # escalate on the very first lap
    phase = make_review_phase(
        config,
        default_mocks=True,
        review_result=ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES),
    )
    phase._escalate_to_hitl = AsyncMock()

    issue = TaskFactory.create(id=42)
    pr = PRInfoFactory.create(issue_number=42)

    results = await phase.review_prs([pr], [issue])

    assert results[0].merged is False
    phase._prs.merge_pr.assert_not_awaited()
    phase._escalate_to_hitl.assert_awaited_once()
    ledger = phase._state.get_convergence_ledger(42)
    assert ledger is not None
    assert ledger.stage_state["review"].last_verdict == "ESCALATE"


# ---------------------------------------------------------------------------
# 6. Blocking review records the route-back signal
# ---------------------------------------------------------------------------


async def test_blocking_review_records_route_back_signal(
    config: HydraFlowConfig,
) -> None:
    """A REQUEST_CHANGES verdict is mirrored to the issue cache has_blocking=True.

    The review flow records the route-back signal; the downstream READY-stage
    precondition gate is what actually routes the issue back.
    """
    phase = make_review_phase(
        config,
        default_mocks=True,
        review_result=ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES),
    )

    recorded: dict[str, object] = {}
    cache = AsyncMock()

    def _capture(*_a: object, **kw: object) -> None:
        recorded.update(kw)

    cache.record_review_stored = _capture
    phase._issue_cache = cache  # type: ignore[assignment]

    issue = TaskFactory.create(id=42)
    pr = PRInfoFactory.create(issue_number=42)

    await phase.review_prs([pr], [issue])

    assert recorded.get("has_blocking") is True


# ---------------------------------------------------------------------------
# 7. Fail-closed early exit walks straight to done
# ---------------------------------------------------------------------------


async def test_issue_not_found_early_exit_skips_review_and_cleanup(
    config: HydraFlowConfig,
) -> None:
    """An issue-not-found guard stops at ``done`` — no review, tail, or cleanup."""
    phase = make_review_phase(config, default_mocks=True)
    pr = PRInfoFactory.create(issue_number=999)  # not in the issue map

    recorded: list[str] = []
    flow = phase._build_review_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    result = await flow.run(phase._initial_review_state(0, pr, {}, "pr_review"))

    assert result.terminal == "done"
    assert recorded == ["guards", "done"]
    assert "review" not in recorded
    assert "post-review" not in recorded
    assert "cleanup" not in recorded
    phase._reviewers.review.assert_not_awaited()
    assert result.state["result"].summary == "Issue not found"
