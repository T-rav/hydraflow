"""The shadow director's fail-closed boundary and its comparison record (#11537).

Six things must fail closed — stop, timeout, malformed command, stale epoch,
process-tree teardown, and an unverified sandbox — and "fail closed" here has a
precise meaning that these tests pin: the turn's output is discarded, **zero**
hypothetical dispatches are recorded, and the boundary is written down as a
failure rather than as a director that chose to yield. That last part is not
pedantry: agreement is the number ADR-0137 B5's rollout bar reads, and a broken
runtime scoring as agreement would launder the evidence the next phase's
go/no-go depends on.

The other half is reconstruction. Every capsule is rebuilt from live state and
no turn is ever resumed, so "fresh reconstruction succeeds without vendor
session history" is met by never having a session to lose.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

import pytest

from director_broker import ShadowDispatchBroker
from director_sandbox import DirectorSandboxError, ProbeEvidence
from director_shadow_log import (
    ShadowAgreement,
    ShadowObservationLog,
    TurnFailure,
    classify_agreement,
)
from director_turn_runner import DirectorTurnResult, extract_command_json
from driver_contracts import DirectorCommandKind, DriverPhase
from fable_director import FableDirector
from issue_driver import AdvanceOutcome, DriverAdvance, IssueDriver
from models import Task

if TYPE_CHECKING:
    from pathlib import Path

READY_LABEL = "hydraflow-ready"
STAGE_LABELS = {
    "PLAN": "hydraflow-plan",
    "READY": READY_LABEL,
    "REVIEW": "hydraflow-review",
    "HITL_WAIT": "hydraflow-hitl",
}

EVIDENCE = ProbeEvidence(
    agent_cli_version="2.1.239",
    residual_agents=5,
    residual_skills=15,
    residual_slash_commands=42,
)

CLEAN_INIT = {
    "type": "system",
    "subtype": "init",
    "tools": [],
    "mcp_servers": [],
    "plugins": [],
    "agents": [],
    "skills": [],
    "slash_commands": [],
    "version": "2.1.239",
}


def _assistant(text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }


def _result(*, is_error: bool = False, cost: float = 0.0) -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "total_cost_usd": cost,
    }


class FakeTurnRunner:
    """A director turn, scripted. Spawns nothing; the real one is seam-declared."""

    def __init__(self, result: DirectorTurnResult | Exception) -> None:
        self._result = result
        self.prompts: list[str] = []
        self.cli_version = "2.1.239"
        self.preflights = 0

    async def preflight(self) -> str:
        self.preflights += 1
        return self.cli_version

    async def run_turn(self, prompt: str) -> DirectorTurnResult:
        self.prompts.append(prompt)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _turn(
    frames: list[dict[str, Any]] | None = None, **kwargs: Any
) -> DirectorTurnResult:
    return DirectorTurnResult(frames=frames if frames is not None else [], **kwargs)


def _yield_turn(cost: float = 0.0) -> DirectorTurnResult:
    return _turn(
        [
            CLEAN_INIT,
            _assistant(json.dumps({"kind": "yield", "rationale": "waiting on CI"})),
            _result(cost=cost),
        ],
        usd_cost=cost,
        latency_ms=1234,
    )


def _dispatch_turn() -> DirectorTurnResult:
    command = {
        "kind": "dispatch_workers",
        "rationale": "the issue needs code",
        "dispatches": [
            {
                "request_id": "req-1",
                "driver_id": "drv-7",
                "epoch": 0,
                "phase_attempt": 0,
                "worker_role": "implementer",
                "model_requirement": {
                    "kind": "literal_family",
                    "value": "claude-sonnet",
                },
                "task_contract": "implement it",
                "reason": "code is needed",
                "expected_route_policy_revision": "route-v1",
                "idempotency_key": "key-1",
            }
        ],
    }
    return _turn([CLEAN_INIT, _assistant(json.dumps(command)), _result()])


def _driver() -> IssueDriver:
    return IssueDriver(
        issue_number=7,
        driver_id="drv-7",
        repo_slug="acme/widgets",
        adapters={},
        labels=object(),  # type: ignore[arg-type]
        journal=object(),  # type: ignore[arg-type]
        stage_labels=STAGE_LABELS,
        driver_state="READY",
    )


def _advance(outcome: AdvanceOutcome = AdvanceOutcome.COMMITTED) -> DriverAdvance:
    return DriverAdvance(
        issue_number=7,
        driver_id="drv-7",
        epoch=0,
        phase=DriverPhase.IMPLEMENT,
        outcome=outcome,
        state="READY",
    )


def _director(
    tmp_path: Path,
    runner: FakeTurnRunner,
    *,
    stop_event: asyncio.Event | None = None,
    budget: float = 5.0,
    ceiling: float = 25.0,
    is_enabled=None,
) -> tuple[FableDirector, ShadowObservationLog]:
    log = ShadowObservationLog(tmp_path / "director_shadow_log.jsonl")
    director = FableDirector(
        runner=runner,  # type: ignore[arg-type]
        broker=ShadowDispatchBroker(),
        shadow_log=log,
        evidence=EVIDENCE,
        repo_slug="acme/widgets",
        route_policy_revision="route-v1",
        stage_labels=STAGE_LABELS,
        stop_event=stop_event,
        usd_budget_per_boundary=budget,
        usd_ceiling=ceiling,
        is_enabled=is_enabled,
    )
    return director, log


async def _observe(
    director: FableDirector, outcome: AdvanceOutcome = AdvanceOutcome.COMMITTED
) -> None:
    await director.observe_boundary(
        task=Task(id=7, title="fix the widget", tags=[READY_LABEL]),
        advance=_advance(outcome),
        driver=_driver(),
    )


# --------------------------------------------------------------------------
# The happy path — and that it really is shadow
# --------------------------------------------------------------------------


async def test_a_clean_dispatch_turn_records_a_hypothetical_worker(
    tmp_path: Path,
) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_dispatch_turn()))

    await _observe(director)

    assert len(log.recent()[0].would_dispatch) == 1


async def test_no_worker_is_ever_recorded_as_dispatched(tmp_path: Path) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_dispatch_turn()))

    await _observe(director)

    assert log.summary()["workers_dispatched"] == 0


async def test_a_dispatch_turn_at_a_committed_boundary_records_agreement(
    tmp_path: Path,
) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_dispatch_turn()))

    await _observe(director, AdvanceOutcome.COMMITTED)

    assert log.recent()[0].agreement is ShadowAgreement.AGREED


async def test_a_yield_turn_at_a_committed_boundary_records_divergence(
    tmp_path: Path,
) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()))

    await _observe(director, AdvanceOutcome.COMMITTED)

    assert log.recent()[0].agreement is ShadowAgreement.DIVERGED


async def test_the_turn_cost_is_recorded(tmp_path: Path) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn(cost=0.031)))

    await _observe(director)

    assert log.recent()[0].usd_cost == pytest.approx(0.031)


async def test_the_turn_latency_is_recorded(tmp_path: Path) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()))

    await _observe(director)

    assert log.recent()[0].latency_ms == 1234


# --------------------------------------------------------------------------
# Fresh reconstruction, never resume
# --------------------------------------------------------------------------


async def test_every_turn_receives_a_freshly_reconstructed_capsule(
    tmp_path: Path,
) -> None:
    # Two consecutive boundaries produce byte-identical context once the lease's
    # own expiry clock is normalised out: nothing accumulates across turns — no
    # transcript, no session, no receipt from the turn before. That is what
    # makes "fresh reconstruction succeeds without vendor session history" true
    # by construction rather than by recovery.
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner)

    await _observe(director)
    await _observe(director)

    assert _without_clock(runner.prompts[0]) == _without_clock(runner.prompts[1])


def _without_clock(prompt: str) -> str:
    """Blank the lease expiry, the one field that legitimately moves per turn."""
    return re.sub(r'"expires_at":"[^"]+"', '"expires_at":"<clock>"', prompt)


async def test_no_vendor_session_id_is_ever_carried_into_a_capsule(
    tmp_path: Path,
) -> None:
    # The capsule contract has no field for one, and the runner is never asked
    # to resume. Pinned because "we never resume" is the claim, and a session id
    # appearing in the prompt would be the first sign it had stopped being true.
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner)

    await _observe(director)

    assert "session_id" not in runner.prompts[0]


async def test_the_capsule_carries_the_issue_goal_and_the_lease(
    tmp_path: Path,
) -> None:
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner)

    await _observe(director)

    assert "fix the widget" in runner.prompts[0]


async def test_the_capsule_offers_only_the_roles_the_phase_allows(
    tmp_path: Path,
) -> None:
    # IMPLEMENT permits explorer, implementer and debugger. A planner or a
    # reviewer must not be on the menu, or the director would be invited to ask
    # for something the rule table will refuse.
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner)

    await _observe(director)

    assert '"reviewer"' not in runner.prompts[0]


async def test_the_reconstruction_is_recorded_rather_than_assumed(
    tmp_path: Path,
) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()))

    await _observe(director)

    assert log.recent()[0].capsule_reconstructed_fresh is True


# --------------------------------------------------------------------------
# Fail closed, six ways
# --------------------------------------------------------------------------


async def test_a_stop_request_starts_no_turn_at_all(tmp_path: Path) -> None:
    stop = asyncio.Event()
    stop.set()
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner, stop_event=stop)

    await _observe(director)

    assert runner.prompts == []


async def test_a_stop_request_is_recorded_as_a_failure_not_as_a_yield(
    tmp_path: Path,
) -> None:
    stop = asyncio.Event()
    stop.set()
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()), stop_event=stop)

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.STOPPED


async def test_a_timed_out_turn_is_recorded_as_timed_out(tmp_path: Path) -> None:
    director, log = _director(
        tmp_path, FakeTurnRunner(_turn([CLEAN_INIT], timed_out=True))
    )

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.TIMED_OUT


async def test_a_timed_out_turn_records_no_hypothetical_work(tmp_path: Path) -> None:
    director, log = _director(
        tmp_path, FakeTurnRunner(_turn([CLEAN_INIT], timed_out=True))
    )

    await _observe(director)

    assert log.recent()[0].would_dispatch == ()


async def test_a_malformed_command_is_discarded(tmp_path: Path) -> None:
    # An object that is not a DirectorCommand — extra="forbid" refuses it, so
    # the schema is the parser rather than a hand-written validator.
    turn = _turn(
        [
            CLEAN_INIT,
            _assistant('{"kind": "dispatch_workers", "shell": "bash"}'),
            _result(),
        ]
    )
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.MALFORMED_OUTPUT


async def test_prose_with_no_command_is_discarded(tmp_path: Path) -> None:
    turn = _turn([CLEAN_INIT, _assistant("I think we should wait."), _result()])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.MALFORMED_OUTPUT


async def test_unframed_output_is_recorded_as_malformed(tmp_path: Path) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_turn([], unframed_output=True)))

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.MALFORMED_OUTPUT


async def test_an_unverified_tool_surface_discards_the_turn(tmp_path: Path) -> None:
    # S4 is applied BEFORE the command is parsed: a turn that held Bash for its
    # lifetime must have its output discarded, not parsed and then refused.
    hostile_init = dict(CLEAN_INIT, tools=["Bash"])
    turn = _turn([hostile_init, _assistant('{"kind": "yield"}'), _result()])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.SANDBOX_UNVERIFIED


async def test_an_unverified_turn_records_no_command_kind(tmp_path: Path) -> None:
    hostile_init = dict(CLEAN_INIT, tools=["Bash"])
    turn = _turn([hostile_init, _assistant('{"kind": "yield"}'), _result()])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].command_kind is None


async def test_a_cli_upgrade_disarms_the_director_for_that_turn(
    tmp_path: Path,
) -> None:
    upgraded = dict(CLEAN_INIT, version="9.9.9")
    turn = _turn([upgraded, _assistant('{"kind": "yield"}'), _result()])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].sandbox_verdict == "cli_version_mismatch"


async def test_a_failed_turn_is_recorded_as_a_turn_error(tmp_path: Path) -> None:
    turn = _turn([CLEAN_INIT, _assistant("{}"), _result(is_error=True)])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.TURN_ERROR


async def test_a_vendor_dropped_session_is_counted_as_a_resume_failure(
    tmp_path: Path,
) -> None:
    # A terminal error frame with no assistant turn: the shape the probe
    # recorded. Counted apart from a generic error because "successful fresh
    # reconstruction on every resume failure" is a line on the rollout bar.
    turn = _turn([CLEAN_INIT, _result(is_error=True)])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.summary()["resume_failures"] == 1


async def test_an_unconstructible_sandbox_does_not_take_the_pipeline_down(
    tmp_path: Path,
) -> None:
    director, log = _director(
        tmp_path, FakeTurnRunner(DirectorSandboxError("no tmpdir"))
    )

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.SANDBOX_UNVERIFIED


async def test_a_credit_exhausted_turn_propagates(tmp_path: Path) -> None:
    from exception_classify import CreditExhaustedError

    director, _log = _director(
        tmp_path, FakeTurnRunner(CreditExhaustedError("weekly limit"))
    )

    with pytest.raises(CreditExhaustedError):
        await _observe(director)


async def test_a_stale_epoch_dispatch_is_refused_by_the_broker(
    tmp_path: Path,
) -> None:
    # The director's command names epoch 0; the driver is at epoch 0 too, so to
    # exercise the fence the request itself claims a superseded epoch.
    command = json.loads(_stale_epoch_command())
    turn = _turn([CLEAN_INIT, _assistant(json.dumps(command)), _result()])
    director, log = _director(tmp_path, FakeTurnRunner(turn))

    await _observe(director)

    assert log.recent()[0].rejection_reasons == ("stale_epoch",)


def _stale_epoch_command() -> str:
    return json.dumps(
        {
            "kind": "dispatch_workers",
            "rationale": "from a generation that no longer owns the issue",
            "dispatches": [
                {
                    "request_id": "req-1",
                    "driver_id": "drv-7",
                    "epoch": 99,
                    "phase_attempt": 0,
                    "worker_role": "implementer",
                    "model_requirement": {
                        "kind": "literal_family",
                        "value": "claude-sonnet",
                    },
                    "task_contract": "implement it",
                    "reason": "code is needed",
                    "expected_route_policy_revision": "route-v1",
                    "idempotency_key": "key-1",
                }
            ],
        }
    )


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


async def test_preflight_asks_the_runner_to_prove_the_boundary(
    tmp_path: Path,
) -> None:
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner)

    await director.preflight()

    assert runner.preflights == 1


# --------------------------------------------------------------------------
# The agreement comparison, on its own
# --------------------------------------------------------------------------


def test_a_finish_command_agrees_with_a_retired_driver() -> None:
    assert (
        classify_agreement(AdvanceOutcome.RETIRED, DirectorCommandKind.FINISH)
        is ShadowAgreement.AGREED
    )


def test_a_yield_command_agrees_with_an_idle_driver() -> None:
    assert (
        classify_agreement(AdvanceOutcome.IDLE, DirectorCommandKind.YIELD)
        is ShadowAgreement.AGREED
    )


def test_no_command_is_neither_agreement_nor_disagreement() -> None:
    assert (
        classify_agreement(AdvanceOutcome.COMMITTED, None) is ShadowAgreement.NO_COMMAND
    )


def test_every_advance_outcome_has_an_agreement_rule() -> None:
    # An unmapped outcome must raise rather than default. Scoring an outcome
    # nobody wired up as agreement would inflate the exact number ADR-0137 B5's
    # bar depends on — the queue_strategy silent-fallback shape.
    for outcome in AdvanceOutcome:
        classify_agreement(outcome, DirectorCommandKind.YIELD)


# --------------------------------------------------------------------------
# Command extraction
# --------------------------------------------------------------------------


def test_a_narrated_answer_still_yields_its_command() -> None:
    frames = [_assistant('Thinking about it.\n{"kind": "yield"}')]

    assert extract_command_json(frames) == '{"kind": "yield"}'


def test_the_last_json_object_wins_when_a_turn_shows_its_working() -> None:
    frames = [_assistant('{"kind": "finish"}\nActually:\n{"kind": "yield"}')]

    assert extract_command_json(frames) == '{"kind": "yield"}'


def test_prose_with_no_json_yields_nothing() -> None:
    assert extract_command_json([_assistant("let us wait and see")]) is None


# --------------------------------------------------------------------------
# What must NOT cost a turn
# --------------------------------------------------------------------------


async def test_an_idle_tick_starts_no_turn(tmp_path: Path) -> None:
    # A parked or barrier-blocked driver reaches IDLE on every poll. Spawning a
    # Fable turn every poll_interval, indefinitely, is the cost defect; and
    # because IDLE maps to "yield" — trivially correct — those no-op ticks would
    # then dominate the agreement rate the rollout bar reads.
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner)

    await _observe(director, AdvanceOutcome.IDLE)

    assert runner.prompts == []


async def test_an_idle_tick_is_recorded_rather_than_dropped(tmp_path: Path) -> None:
    # Recorded, so the ratio of real boundaries to idle ticks stays visible.
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()))

    await _observe(director, AdvanceOutcome.IDLE)

    assert log.recent()[0].turn_failure is TurnFailure.NOT_A_BOUNDARY


async def test_an_idle_tick_never_scores_as_agreement(tmp_path: Path) -> None:
    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()))

    await _observe(director, AdvanceOutcome.IDLE)

    assert log.summary()["agreed"] == 0


async def test_the_live_kill_switch_stops_every_turn(tmp_path: Path) -> None:
    # The dials that select the director are restart-required; this one must
    # not be, because a director turn costs money.
    runner = FakeTurnRunner(_yield_turn())
    director, _log = _director(tmp_path, runner, is_enabled=lambda: False)

    await _observe(director)

    assert runner.prompts == []


async def test_the_kill_switch_records_why_it_declined(tmp_path: Path) -> None:
    director, log = _director(
        tmp_path, FakeTurnRunner(_yield_turn()), is_enabled=lambda: False
    )

    await _observe(director)

    assert log.recent()[0].turn_failure is TurnFailure.DISABLED


async def test_the_aggregate_spend_ceiling_stops_further_turns(
    tmp_path: Path,
) -> None:
    # The per-boundary budget bounds what a director may REQUEST and still costs
    # a turn to discover. Nothing else in the design bounds turn *count*, so
    # without this a driver reaching a boundary every poll spends indefinitely.
    runner = FakeTurnRunner(_yield_turn(cost=0.5))
    director, _log = _director(tmp_path, runner, ceiling=0.4)

    await _observe(director)
    await _observe(director)

    assert len(runner.prompts) == 1


async def test_the_spend_ceiling_is_recorded_when_it_bites(tmp_path: Path) -> None:
    director, log = _director(
        tmp_path, FakeTurnRunner(_yield_turn(cost=0.5)), ceiling=0.4
    )
    await _observe(director)

    await _observe(director)

    assert log.summary()["spend_ceiling_reached"] == 1


async def test_an_unmapped_outcome_records_the_boundary_rather_than_losing_it(
    tmp_path: Path,
) -> None:
    # classify_agreement raises for an unmapped outcome on purpose. Raising
    # *through* the observer would travel into the allocator's containment and
    # the observation would be dropped entirely — "fails loudly" becoming
    # "silently records nothing", which is worse than what it replaced.
    import director_shadow_log as shadow_log_module

    director, log = _director(tmp_path, FakeTurnRunner(_yield_turn()))
    original = dict(shadow_log_module._AGREEING_COMMAND)
    del shadow_log_module._AGREEING_COMMAND[AdvanceOutcome.COMMITTED]
    try:
        await _observe(director, AdvanceOutcome.COMMITTED)
    finally:
        shadow_log_module._AGREEING_COMMAND.update(original)

    assert log.summary()["observations"] == 1
