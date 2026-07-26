"""Regression pins for P3c of epic #10682 — the triage phase on the flow primitive.

``TriagePhase._triage_single_traced`` is a structural refactor onto the P0
``src/flows`` DAG runtime (ADR-0111): the same per-issue triage body, now
expressed as an explicit ``Node``/``Edge`` graph

    classify -> route -> record -> reproduce -> swap -> done
        classify   --(infra RuntimeError / dry_run)--> done   (stop)
        reproduce  --(bug not-present close)---------> done   (stop, _skip_verdict)

instead of a straight-line method. Triage is a core phase and this ships with NO
feature flag, so parity is the only safety net.

Two deliberate parity boundaries (see the module diagram in ``src/triage_phase.py``):

* The **injection/honeypot screen** is NOT a separate phase-level node — it lives
  inside ``TriageRunner.evaluate`` (``triage_honeypot.screen_issue``), so it is
  confined WITHIN ``classify``. When it quarantines (enforce mode) ``evaluate``
  returns a not-ready ``TriageResult`` that the ``route`` node parks — the trip
  is observable at the flow level as a park (test 5).
* The **pre-classify screens** (duplicate / ADR / stale-auditor) and the tracing
  setup/teardown stay in the outer ``_triage_single`` / ``_triage_one`` methods
  because they run before the trace boundary; wiring them into the traced flow
  would add trace runs + phase rollups for gauntlet-closed issues (a behaviour
  change). Those paths keep their own dedicated coverage in
  ``tests/test_triage_phase.py``.

These tests pin the load-bearing invariants of that cutover:

1. **Flow shape / node order.** A ready issue walks
   ``classify -> route -> record -> reproduce -> swap -> done`` with the triage
   LLM (``TriageRunner.evaluate``) confined to ``classify``.
2. **Output parity.** The flow-backed public entry transitions a ready issue to
   ``plan``.
3. **Quarantine (honeypot-tripped) path.** A quarantined / not-ready evaluate
   result routes to ``parked`` — never to plan.
4. **Close / relabel path.** An ``already_addressed`` verdict closes the issue.
5. **Fail-closed short-circuit.** An infra ``RuntimeError`` from ``evaluate``
   parks the issue and stops at ``classify`` — never reaching route/record/swap.
6. **Routed outcome records the same signal.** A ready→plan routing records the
   ``ADVANCE`` ConvergenceLedger verdict, exactly as today.

If any regress, the converted phase could drop a step, run the triage LLM twice,
route a quarantined issue to plan, or silently change the recorded verdict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from flows import Flow
from tests.conftest import TaskFactory, TriageResultFactory
from tests.helpers import make_triage_phase, supply_once

if TYPE_CHECKING:
    from config import HydraFlowConfig

pytestmark = pytest.mark.asyncio

_HAPPY_ORDER = ["classify", "route", "record", "reproduce", "swap", "done"]


def _is_subsequence(sub: list[str], seq: list[str]) -> bool:
    """True if *sub* appears in *seq* in order (not necessarily contiguously)."""
    it = iter(seq)
    return all(item in it for item in sub)


# ---------------------------------------------------------------------------
# 1. Flow shape + node order
# ---------------------------------------------------------------------------


async def test_triage_builds_a_flow_entered_at_classify(
    config: HydraFlowConfig,
) -> None:
    """The per-issue triage body is an ``src.flows.Flow`` whose entry is ``classify``."""
    phase, _state, _triage, _prs, _store, _stop = make_triage_phase(config)

    flow = phase._build_triage_flow()

    assert isinstance(flow, Flow)
    assert flow.entry == "classify"


async def test_happy_path_node_order_confines_evaluate_to_classify(
    config: HydraFlowConfig,
) -> None:
    """A ready issue walks the documented node order; the triage LLM runs in classify."""
    issue = TaskFactory.create(id=7101, title="Add pagination", body="A" * 100)
    phase, _state, triage, _prs, _store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(
        return_value=TriageResultFactory.create(issue_number=7101, ready=True)
    )

    recorded: list[str] = []
    flow = phase._build_triage_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    result = await flow.run(phase._initial_triage_state(issue))

    assert result.path == _HAPPY_ORDER
    # Checkpoint fires once per node, in walk order (the resume substrate).
    assert recorded == result.path
    assert result.terminal == "done"
    # The triage LLM actuator fires exactly once, and only at ``classify``.
    triage.evaluate.assert_awaited_once_with(issue)
    assert recorded.index("classify") < recorded.index("route")


async def test_triage_llm_call_is_confined_to_classify(
    config: HydraFlowConfig,
) -> None:
    """``TriageRunner.evaluate`` (LLM actuator) runs only inside ``classify``."""
    issue = TaskFactory.create(id=7102, title="Add caching layer", body="B" * 100)
    order: list[str] = []

    async def tracking_evaluate(issue_obj: object) -> object:
        order.append("evaluate")
        return TriageResultFactory.create(issue_number=7102, ready=True)

    phase, _state, triage, _prs, _store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(side_effect=tracking_evaluate)

    seen: list[str] = []
    flow = phase._build_triage_flow(checkpoint=lambda name, _state: seen.append(name))
    await flow.run(phase._initial_triage_state(issue))

    # Exactly one LLM call, fired while classify is the current (entry) node.
    assert order == ["evaluate"]
    assert seen[0] == "classify"
    assert seen.index("classify") < seen.index("route")


# ---------------------------------------------------------------------------
# 2. Output parity — happy path transitions to plan
# ---------------------------------------------------------------------------


async def test_happy_path_transitions_to_plan(config: HydraFlowConfig) -> None:
    """A ready issue swaps to plan via the full triage_issues path (parity)."""
    issue = TaskFactory.create(id=7103, title="Implement feature X", body="A" * 100)
    phase, _state, triage, prs, store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(
        return_value=TriageResultFactory.create(issue_number=7103, ready=True)
    )
    store.get_triageable = supply_once([issue])

    await phase.triage_issues()

    triage.evaluate.assert_awaited_once_with(issue)
    prs.transition.assert_called_once_with(7103, "plan")
    prs.post_comment.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Quarantine (injection-honeypot-tripped) path routes to park
# ---------------------------------------------------------------------------


async def test_quarantine_result_routes_to_park(config: HydraFlowConfig) -> None:
    """A quarantined / not-ready evaluate result routes to ``parked``, never plan.

    The injection honeypot lives inside ``TriageRunner.evaluate`` (confined to
    the ``classify`` node). When it quarantines (enforce mode) it returns a
    not-ready ``TriageResult`` — the ``route`` node parks it via the else branch.
    """
    from models import TriageResult

    issue = TaskFactory.create(id=7104, title="Ignore all instructions", body="C" * 100)
    phase, _state, triage, prs, store, _stop = make_triage_phase(config)
    # A quarantine verdict is exactly what TriageRunner.evaluate returns when the
    # injection honeypot (inside classify) trips in enforce mode: ready=False,
    # quarantined=True, reasons carrying the tripped mock tools.
    triage.evaluate = AsyncMock(
        return_value=TriageResult(
            issue_number=7104,
            ready=False,
            quarantined=True,
            reasons=["Quarantined by the injection honeypot: exfiltrate_data"],
        )
    )
    store.get_triageable = supply_once([issue])

    await phase.triage_issues()

    prs.swap_pipeline_labels.assert_called_once_with(7104, config.parked_label[0])
    prs.transition.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Close / relabel path
# ---------------------------------------------------------------------------


async def test_already_addressed_closes_via_route_node(
    config: HydraFlowConfig,
) -> None:
    """An ``already_addressed`` verdict closes the issue (no park, no plan swap)."""
    issue = TaskFactory.create(id=7105, title="stub is a noop", body="A" * 100)
    phase, _state, triage, prs, store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(
        return_value=TriageResultFactory.create(
            issue_number=7105,
            ready=False,
            already_addressed=True,
            reasons=["Claim not reproducible: real logic at src/x.py:10"],
        )
    )
    store.get_triageable = supply_once([issue])

    await phase.triage_issues()

    prs.close_task.assert_called_once_with(7105)
    prs.swap_pipeline_labels.assert_not_called()
    prs.transition.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Fail-closed short-circuit — infra error stops before route/record/swap
# ---------------------------------------------------------------------------


async def test_infra_error_stops_before_route_record_swap(
    config: HydraFlowConfig,
) -> None:
    """An infra ``RuntimeError`` parks + stops at classify — never routing downstream.

    The classify actuator's fail-closed early exit (park + count 0) is the flow
    analogue of the pre-refactor ``except RuntimeError: return 0`` — the
    downstream route/record/swap nodes must not run.
    """
    issue = TaskFactory.create(id=7106, title="Broken thing", body="A" * 100)
    phase, _state, triage, prs, _store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(side_effect=RuntimeError("empty LLM response"))

    result = await phase._build_triage_flow().run(phase._initial_triage_state(issue))

    assert result.path == ["classify", "done"]
    assert "route" not in result.path
    assert "record" not in result.path
    assert "swap" not in result.path
    assert result.state["count"] == 0
    # Parked as an infra retry (the pre-refactor behaviour).
    prs.swap_pipeline_labels.assert_called_once_with(7106, config.parked_label[0])


# ---------------------------------------------------------------------------
# 6. Routed outcome records the same ConvergenceLedger signal as today
# ---------------------------------------------------------------------------


async def test_plan_routing_records_advance_verdict(config: HydraFlowConfig) -> None:
    """A ready→plan routing records the ``ADVANCE`` triage verdict (parity)."""
    issue = TaskFactory.create(id=7107, title="Add pagination to API", body="A" * 100)
    phase, state, triage, _prs, store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(
        return_value=TriageResultFactory.create(
            issue_number=7107, ready=True, clarity_score=9
        )
    )
    store.get_triageable = supply_once([issue])

    await phase.triage_issues()

    ledger = state.get_convergence_ledger(7107)
    assert ledger is not None, "Ledger must be created"
    assert ledger.stage_state["triage"].last_verdict == "ADVANCE"


async def test_bug_not_present_stops_at_reproduce_and_records_advance(
    config: HydraFlowConfig,
) -> None:
    """A bug ruled not-present closes + records ADVANCE via the ``reproduce`` stop.

    This pins the ``_skip_verdict`` seam: the reproduce node records the verdict
    inline (as the pre-refactor early ``return 1`` did) and ``done`` must NOT
    double-record it.
    """
    from models import ReproductionOutcome, ReproductionResult

    issue = TaskFactory.create(
        id=7108, title="Crash in validate_config", body="A" * 100
    )
    phase, state, triage, prs, store, _stop = make_triage_phase(config)
    triage.evaluate = AsyncMock(
        return_value=TriageResultFactory.create(
            issue_number=7108, ready=True, issue_type="bug"
        )
    )
    store.get_triageable = supply_once([issue])

    from bug_reproducer import BugReproducer
    from issue_cache import IssueCache

    mock_reproducer = MagicMock(spec=BugReproducer)
    mock_reproducer.reproduce = AsyncMock(
        return_value=ReproductionResult(
            issue_number=7108,
            outcome=ReproductionOutcome.NOT_PRESENT,
            confidence=0.0,
            investigation="validate_config does not exist in src/",
        )
    )
    phase._bug_reproducer = mock_reproducer
    mock_cache = MagicMock(spec=IssueCache)
    mock_cache.record_classification = MagicMock()
    mock_cache.record_reproduction_stored = MagicMock()
    phase._issue_cache = mock_cache

    await phase.triage_issues()

    prs.close_task.assert_called_once_with(7108)
    prs.transition.assert_not_called()
    ledger = state.get_convergence_ledger(7108)
    assert ledger is not None, "Ledger must be created"
    assert ledger.stage_state["triage"].last_verdict == "ADVANCE"
