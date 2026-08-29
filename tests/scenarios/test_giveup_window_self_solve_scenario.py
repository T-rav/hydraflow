"""MockWorld scenario: plan-retry thrash → SELF-SOLVE, not human (#10735).

Reproduces the #10731 class end-to-end against MockWorld fakes: a plan whose
adversarial review keeps flagging blocking findings is routed back to PLAN by
the READY-stage precondition gate, cycle after cycle. This wires the REAL
``PreconditionGate`` → ``RouteBackCoordinator`` → ``GiveUpTracker`` →
``PlanRetrySelfSolver`` chain against a real ``StateTracker``, ``IssueCache``,
``EpicManager`` and ``IssueDecomposer`` — only the decomposition ensemble's LLM
seam is scripted (mirroring test_decompose_to_converge_scenario.py).

Proves the corrected escalation (ADR-0105, epic #10733 child 2):

  (a) after N non-converging route-backs within T, the give-up window fires and
      the issue is DECOMPOSED into convergent children — it does NOT thrash and
      does NOT get parked to ``human-required``. Give-up state is visible.
  (b) a plan that DOES converge (clean review) passes the gate untouched — the
      window never fires for a convergent issue.
  (c) when the self-solve path itself is exhausted (ensemble declines AND no
      diagnose stage), ``human-required`` IS applied — the genuine last resort.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from giveup_window import GiveUpClass, GiveUpTracker, resolve_window
from issue_cache import IssueCache
from models import Task
from precondition_gate import PreconditionGate
from route_back import RouteBackCoordinator
from stage_preconditions import Stage
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Ensemble scripting (mirrors test_decompose_to_converge_scenario.py)
# ---------------------------------------------------------------------------


def _direction_reply(**fields: object) -> str:
    fields.setdefault("epic_title", "Epic: split the non-convergent plan")
    fields.setdefault(
        "epic_body", "## Sub-issues\n\n- [ ] Narrower slice A\n- [ ] Narrower slice B"
    )
    fields.setdefault(
        "children",
        [
            {"title": "Narrower slice A", "body": "Independently shippable slice A."},
            {"title": "Narrower slice B", "body": "Independently shippable slice B."},
        ],
    )
    fields.setdefault("rationale", "Two independently shippable, narrower slices.")
    return json.dumps(fields)


def _validation_reply(**fields: object) -> str:
    fields.setdefault("decision", "approve")
    fields.setdefault("confidence", "high")
    fields.setdefault("reasoning", "Sound, non-overlapping split.")
    return json.dumps(fields)


def _script_ensemble(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> None:
    from execution import SimpleResult  # noqa: PLC0415

    remaining = list(replies)

    async def _fake_seam(**_kwargs: object) -> SimpleResult:
        stdout = remaining.pop(0) if remaining else replies[-1]
        return SimpleResult(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)


# ---------------------------------------------------------------------------
# Wiring: the real precondition-gate → route-back → give-up → self-solve chain
# ---------------------------------------------------------------------------


def _wire_chain(
    world: MockWorld, cache: IssueCache, *, diagnose_label: str | None = None
) -> tuple[PreconditionGate, RouteBackCoordinator]:
    from decomposition_ensemble import DecompositionEnsemble  # noqa: PLC0415
    from epic import EpicManager  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from giveup_self_solve import PlanRetrySelfSolver  # noqa: PLC0415
    from issue_decomposer import IssueDecomposer  # noqa: PLC0415

    cfg = world.harness.config
    state = world.harness.state
    github = world.github

    epic_manager = EpicManager(
        config=cfg,
        state=state,
        prs=github,
        fetcher=MagicMock(),
        event_bus=EventBus(),
    )
    decomposer = IssueDecomposer(github, epic_manager, state, cfg)
    ensemble = DecompositionEnsemble(AsyncMock(), cfg)
    diag = cfg.diagnose_label[0] if diagnose_label is None else diagnose_label
    self_solver = PlanRetrySelfSolver(
        config=cfg,
        state=state,
        prs=github,
        decomposer=decomposer,
        ensemble=ensemble,
        diagnose_label=diag,
    )
    coordinator = RouteBackCoordinator(
        cache=cache,
        prs=github,
        counter=state,  # StateTracker satisfies RouteBackCounterPort
        hitl_label=cfg.hitl_label[0],
        diagnose_label=diag,
        max_route_backs=2,
        give_up_tracker=GiveUpTracker(state),
        plan_retry_window=resolve_window(cfg, GiveUpClass.PLAN_RETRY),  # N=2
        self_solve=self_solver,
    )
    gate = PreconditionGate(cache=cache, coordinator=coordinator, enabled=True)
    return gate, coordinator


def _seed_blocking_plan(cache: IssueCache, issue_number: int) -> None:
    """A plan exists but its adversarial review is blocking → route back to PLAN."""
    cache.record_plan_stored(issue_number, plan_text="a plan", actionability_score=5)
    cache.record_review_stored(
        issue_number,
        review_text="critical: unvalidated core mechanism",
        has_blocking=True,
        findings=[{"severity": "critical", "summary": "unvalidated core mechanism"}],
    )


def _epic_numbers(world: MockWorld) -> list[int]:
    label = world.harness.config.epic_label[0]
    return sorted(n for n, i in world.github._issues.items() if label in i.labels)


# ---------------------------------------------------------------------------
# (a) thrash → decompose (self-solve), NOT human-required
# ---------------------------------------------------------------------------


class TestThrashSelfSolvesViaDecompose:
    async def test_non_converging_plan_decomposes_not_human(
        self, tmp_path, monkeypatch
    ) -> None:
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 10731
        world.add_issue(
            issue_number,
            "Sampled-audit adjudication that never converges",
            "The adjudication keeps failing plan review no matter the plan.",
            labels=[cfg.ready_label[0]],
        )
        cache = IssueCache(tmp_path / "cache", enabled=True)
        _seed_blocking_plan(cache, issue_number)
        gate, _coordinator = _wire_chain(world, cache)
        _script_ensemble(
            monkeypatch,
            [_direction_reply(), _validation_reply(decision="approve")],
        )

        task = Task(
            id=issue_number,
            title="Sampled-audit adjudication that never converges",
            body="The adjudication keeps failing plan review no matter the plan.",
        )

        # Cycle 1: below the window (N=2) → routed back to PLAN, not solved.
        passed_1 = await gate.filter_and_route([task], Stage.READY)
        assert passed_1 == []  # blocked out of the READY batch
        assert _epic_numbers(world) == []  # no self-solve yet
        assert world.github.issue(issue_number).state == "open"

        # Cycle 2: N-in-T exhausted → SELF-SOLVE via decompose.
        passed_2 = await gate.filter_and_route([task], Stage.READY)
        assert passed_2 == []

        # The give-up window fired a machine self-solve, NOT a human hand-off.
        epics = _epic_numbers(world)
        assert len(epics) == 1, f"expected exactly one epic from decompose, got {epics}"
        assert world.harness.state.get_issue_status(issue_number) == "decomposed"
        assert world.github.issue(issue_number).state == "closed"
        assert "human-required" not in world.github.issue(issue_number).labels

        # Children are convergent, narrower slices (not clones of the parent).
        epic_state = world.harness.state.get_epic_state(epics[0])
        assert epic_state is not None
        assert len(epic_state.child_issues) == 2

        # Give-up state is surfaced: the fired action is recorded for /api.
        snap = world.harness.state.get_give_up_snapshot(issue_number)
        assert snap["plan_retry"]["last_action"] == "decompose"
        assert snap["plan_retry"]["action_count"] == 1


# ---------------------------------------------------------------------------
# (b) a convergent plan is untouched — the window never fires
# ---------------------------------------------------------------------------


class TestConvergentPlanUntouched:
    async def test_clean_review_passes_gate_no_self_solve(
        self, tmp_path, monkeypatch
    ) -> None:
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 5000
        world.add_issue(
            issue_number,
            "A plan that converges",
            "Straightforward.",
            labels=[cfg.ready_label[0]],
        )
        cache = IssueCache(tmp_path / "cache", enabled=True)
        # A clean (non-blocking) review → preconditions PASS.
        cache.record_plan_stored(
            issue_number, plan_text="a plan", actionability_score=8
        )
        cache.record_review_stored(
            issue_number, review_text="looks good", has_blocking=False
        )
        gate, _coordinator = _wire_chain(world, cache)
        _script_ensemble(monkeypatch, [_direction_reply(), _validation_reply()])

        task = Task(id=issue_number, title="A plan that converges", body="ok")

        # Drive several cycles: a convergent plan passes every time and is never
        # routed back, decomposed, or parked.
        for _ in range(4):
            passed = await gate.filter_and_route([task], Stage.READY)
            assert passed == [task]

        assert _epic_numbers(world) == []
        assert world.harness.state.get_issue_status(issue_number) != "decomposed"
        assert world.harness.state.get_give_up_snapshot(issue_number) == {}
        assert "human-required" not in world.github.issue(issue_number).labels


# ---------------------------------------------------------------------------
# (c) human-required only when the self-solve path itself exhausts
# ---------------------------------------------------------------------------


class TestHumanRequiredOnlyAsLastResort:
    async def test_undecomposable_no_diagnose_reaches_human(
        self, tmp_path, monkeypatch
    ) -> None:
        world = MockWorld(tmp_path)
        cfg = world.harness.config
        issue_number = 6001
        world.add_issue(
            issue_number,
            "Atomic off-by-one; nothing to split",
            "Single-line arithmetic bug.",
            labels=[cfg.ready_label[0]],
        )
        cache = IssueCache(tmp_path / "cache", enabled=True)
        _seed_blocking_plan(cache, issue_number)
        # No diagnose stage AND the ensemble declines high-confidence → the
        # self-solve ladder is fully exhausted, so human-required is correct.
        gate, _coordinator = _wire_chain(world, cache, diagnose_label="")
        _script_ensemble(
            monkeypatch,
            [
                _direction_reply(),
                _validation_reply(
                    decision="reject",
                    confidence="high",
                    reasoning="Atomic fix; children would be near-duplicates.",
                ),
            ],
        )

        task = Task(id=issue_number, title="Atomic off-by-one", body="one line")

        await gate.filter_and_route([task], Stage.READY)  # cycle 1: routed
        await gate.filter_and_route([task], Stage.READY)  # cycle 2: exhausted

        # Genuine dead end → human-required (the rare last resort).
        assert _epic_numbers(world) == []
        assert "human-required" in world.github.issue(issue_number).labels
        assert world.harness.state.get_issue_status(issue_number) != "decomposed"
        snap = world.harness.state.get_give_up_snapshot(issue_number)
        assert snap["plan_retry"]["last_action"] == "human-required"
