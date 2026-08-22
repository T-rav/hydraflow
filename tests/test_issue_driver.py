"""Unit tests for the fenced per-issue driver (#11535, ADR-0137 C1/C5/C7/C8).

The driver's whole job is a transaction with a fixed order and a fence at both
ends of it, so these tests are about ordering and refusal rather than about
phases doing work: the phase adapter here is a recorder, and what is asserted is
what the driver did around it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from driver_contracts import DriverPhase, RejectionReason
from issue_driver import AdvanceOutcome, IssueDriver, PhaseOutcome
from models import Task

if TYPE_CHECKING:
    from collections.abc import Mapping

    from driver_contracts import DriverCheckpoint

PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"
REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"

STAGE_LABELS = {
    "PLAN": PLAN_LABEL,
    "READY": READY_LABEL,
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": HITL_LABEL,
    "HITL_APPLY": HITL_LABEL,
}


class RecordingLabels:
    """A label port over a single mutable label, recording every write."""

    def __init__(self, label: str | None) -> None:
        self.label = label
        self.events: list[str] = []

    async def read_stage_label(self, issue_number: int) -> str | None:
        return self.label

    async def commit_stage_label(self, issue_number: int, label: str) -> None:
        self.events.append(f"label:{label}")
        self.label = label


class RecordingJournal:
    """An in-memory journal that records the order of its two write kinds."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.committed: set[str] = set()
        self.checkpoints: list[DriverCheckpoint] = []

    def committed_keys(self, issue_number: int) -> frozenset[str]:
        return frozenset(self.committed)

    def persist_artifact(
        self, issue_number: int, key: str, artifact: Mapping[str, object]
    ) -> None:
        self.events.append("artifact")

    def append_checkpoint(
        self, issue_number: int, key: str, checkpoint: DriverCheckpoint
    ) -> None:
        self.events.append("checkpoint")
        self.committed.add(key)
        self.checkpoints.append(checkpoint)


class ScriptedAdapter:
    """A phase adapter that returns a canned outcome and counts its runs."""

    def __init__(
        self,
        phase: DriverPhase,
        outcome: PhaseOutcome,
        *,
        labels: RecordingLabels | None = None,
        commits_label: str | None = None,
        on_run: object = None,
    ) -> None:
        self.phase = phase
        self._outcome = outcome
        self._labels = labels
        self._commits_label = commits_label
        self._on_run = on_run
        self.runs = 0

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        self.runs += 1
        if self._on_run is not None:
            self._on_run()
        if self._labels is not None and self._commits_label is not None:
            # Mimics a real stage worker swapping its own transition label.
            self._labels.events.append(f"label:{self._commits_label}")
            self._labels.label = self._commits_label
        return self._outcome


def _task(number: int = 501) -> Task:
    return Task(id=number, title="a task")


def _driver(
    *,
    labels: RecordingLabels,
    journal: RecordingJournal,
    adapter: ScriptedAdapter,
    driver_state: str = "PLAN",
    epoch: int = 0,
) -> IssueDriver:
    return IssueDriver(
        issue_number=501,
        driver_id="drv-501-test",
        repo_slug="acme/widgets",
        adapters={adapter.phase: adapter},
        labels=labels,
        journal=journal,
        stage_labels=STAGE_LABELS,
        driver_state=driver_state,
        epoch=epoch,
    )


def _plan_ok() -> PhaseOutcome:
    return PhaseOutcome(ok=True, next_label=READY_LABEL, artifact={"phase": "PLAN"})


# --------------------------------------------------------------------------
# C8 — the boundary transaction order
# --------------------------------------------------------------------------


async def test_a_committed_boundary_persists_the_artifact_before_the_label() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    driver = _driver(
        labels=labels,
        journal=journal,
        adapter=ScriptedAdapter(DriverPhase.PLAN, _plan_ok()),
    )

    await driver.advance(_task())

    assert journal.events.index("artifact") < journal.events.index("checkpoint")


async def test_the_checkpoint_is_appended_only_after_the_label_is_committed() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(labels=labels, journal=journal, adapter=adapter)

    await driver.advance(_task())

    assert labels.events == ["label:hydraflow-ready"], (
        "the label swap must land before the checkpoint records the boundary"
    )


async def test_a_boundary_killed_before_the_label_leaves_no_committed_key() -> None:
    # The kill window ADR-0137 C8 names: the artifact is persisted, then the
    # process dies before the swap. Recovery must NOT believe the boundary
    # committed, or the transition is skipped and the issue is stuck.
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()

    def _die() -> None:
        raise RuntimeError("killed mid-transition")

    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok(), on_run=_die)
    driver = _driver(labels=labels, journal=journal, adapter=adapter)

    await driver.advance(_task())

    assert journal.committed == set()


async def test_the_driver_does_not_re_swap_a_label_its_stage_worker_committed() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(
        DriverPhase.PLAN, _plan_ok(), labels=labels, commits_label=READY_LABEL
    )
    driver = _driver(labels=labels, journal=journal, adapter=adapter)

    await driver.advance(_task())

    assert labels.events == ["label:hydraflow-ready"], (
        "one write, made by the stage worker — the driver must not duplicate it"
    )


async def test_a_stage_worker_committing_its_own_label_still_commits_the_boundary() -> (
    None
):
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(
        DriverPhase.PLAN, _plan_ok(), labels=labels, commits_label=READY_LABEL
    )
    driver = _driver(labels=labels, journal=journal, adapter=adapter)

    advance = await driver.advance(_task())

    assert advance.outcome is AdvanceOutcome.COMMITTED


async def test_a_committed_plan_boundary_moves_the_driver_to_the_ready_state() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    driver = _driver(
        labels=labels,
        journal=RecordingJournal(),
        adapter=ScriptedAdapter(DriverPhase.PLAN, _plan_ok()),
    )

    await driver.advance(_task())

    assert driver.driver_state == "READY"


# --------------------------------------------------------------------------
# The fence — epoch and phase attempt
# --------------------------------------------------------------------------


async def test_a_result_from_a_fenced_out_epoch_is_rejected() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(labels=labels, journal=journal, adapter=adapter)
    # Recovery bumps the epoch while the phase is mid-flight, so the result
    # that comes back belongs to a generation that no longer owns the issue.
    adapter._on_run = driver.recover  # noqa: SLF001

    advance = await driver.advance(_task())

    assert advance.reason is RejectionReason.STALE_EPOCH


async def test_a_fenced_out_result_commits_nothing() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(labels=labels, journal=journal, adapter=adapter)
    adapter._on_run = driver.recover  # noqa: SLF001

    await driver.advance(_task())

    assert journal.events == []


async def test_recover_raises_the_epoch_so_the_previous_generation_is_fenced() -> None:
    driver = _driver(
        labels=RecordingLabels(PLAN_LABEL),
        journal=RecordingJournal(),
        adapter=ScriptedAdapter(DriverPhase.PLAN, _plan_ok()),
        epoch=3,
    )

    assert driver.recover() == 4


async def test_recover_clears_the_phase_attempt_counters() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    adapter = ScriptedAdapter(
        DriverPhase.PLAN, PhaseOutcome(ok=False, next_label=PLAN_LABEL, detail="nope")
    )
    driver = _driver(labels=labels, journal=RecordingJournal(), adapter=adapter)
    await driver.advance(_task())

    driver.recover()

    assert driver.phase_attempt(DriverPhase.PLAN) == 0


async def test_a_failed_phase_advances_its_attempt_counter() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    adapter = ScriptedAdapter(
        DriverPhase.PLAN, PhaseOutcome(ok=False, next_label=PLAN_LABEL, detail="nope")
    )
    driver = _driver(labels=labels, journal=RecordingJournal(), adapter=adapter)

    await driver.advance(_task())

    assert driver.phase_attempt(DriverPhase.PLAN) == 1


# --------------------------------------------------------------------------
# Idempotency and stop fencing
# --------------------------------------------------------------------------


async def test_re_entering_an_already_committed_boundary_does_not_re_run_the_phase() -> (
    None
):
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(labels=labels, journal=journal, adapter=adapter)
    await driver.advance(_task())
    # Put the driver back where it started, as a crash-and-restart would.
    driver.adopt_live_state("PLAN")
    labels.label = PLAN_LABEL

    await driver.advance(_task())

    assert adapter.runs == 1


async def test_re_entering_an_already_committed_boundary_reports_already_committed() -> (
    None
):
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(labels=labels, journal=journal, adapter=adapter)
    await driver.advance(_task())
    driver.adopt_live_state("PLAN")
    labels.label = PLAN_LABEL

    advance = await driver.advance(_task())

    assert advance.outcome is AdvanceOutcome.ALREADY_COMMITTED


async def test_a_stopped_factory_never_runs_the_phase() -> None:
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(
        labels=RecordingLabels(PLAN_LABEL),
        journal=RecordingJournal(),
        adapter=adapter,
    )

    await driver.advance(_task(), stop_requested=True)

    assert adapter.runs == 0


async def test_a_stopped_factory_reports_the_stop_fence_reason() -> None:
    driver = _driver(
        labels=RecordingLabels(PLAN_LABEL),
        journal=RecordingJournal(),
        adapter=ScriptedAdapter(DriverPhase.PLAN, _plan_ok()),
    )

    advance = await driver.advance(_task(), stop_requested=True)

    assert advance.reason is RejectionReason.STOP_FENCE


# --------------------------------------------------------------------------
# C5 — the label is authoritative
# --------------------------------------------------------------------------


async def test_a_label_dragged_before_the_phase_preempts_the_driver() -> None:
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(
        labels=RecordingLabels(HITL_LABEL),
        journal=RecordingJournal(),
        adapter=adapter,
    )

    advance = await driver.advance(_task())

    assert advance.outcome is AdvanceOutcome.PREEMPTED


async def test_a_preempted_driver_adopts_the_state_the_live_label_implies() -> None:
    driver = _driver(
        labels=RecordingLabels(HITL_LABEL),
        journal=RecordingJournal(),
        adapter=ScriptedAdapter(DriverPhase.PLAN, _plan_ok()),
    )

    await driver.advance(_task())

    assert driver.driver_state == "HITL_WAIT"


async def test_a_label_dragged_before_the_phase_never_runs_the_phase() -> None:
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(
        labels=RecordingLabels(HITL_LABEL),
        journal=RecordingJournal(),
        adapter=adapter,
    )

    await driver.advance(_task())

    assert adapter.runs == 0


async def test_a_label_dragged_while_the_phase_ran_preempts_rather_than_commits() -> (
    None
):
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    # The phase runs, but an operator drags the card to HITL meanwhile — a
    # label that is neither where the driver started nor where the phase was
    # going. ADR-0002 calls that the escape hatch; the driver must not clobber it.
    adapter = ScriptedAdapter(
        DriverPhase.PLAN, _plan_ok(), labels=labels, commits_label=HITL_LABEL
    )
    driver = _driver(labels=labels, journal=journal, adapter=adapter)

    advance = await driver.advance(_task())

    assert advance.outcome is AdvanceOutcome.PREEMPTED


async def test_a_label_dragged_while_the_phase_ran_commits_no_checkpoint() -> None:
    labels = RecordingLabels(PLAN_LABEL)
    journal = RecordingJournal()
    adapter = ScriptedAdapter(
        DriverPhase.PLAN, _plan_ok(), labels=labels, commits_label=HITL_LABEL
    )
    driver = _driver(labels=labels, journal=journal, adapter=adapter)

    await driver.advance(_task())

    assert journal.committed == set()


# --------------------------------------------------------------------------
# Retirement
# --------------------------------------------------------------------------


async def test_a_merged_issue_retires_its_driver() -> None:
    labels = RecordingLabels(REVIEW_LABEL)
    adapter = ScriptedAdapter(
        DriverPhase.REVIEW,
        PhaseOutcome(ok=True, next_label=None, next_state="MERGED", artifact={}),
    )
    driver = _driver(
        labels=labels,
        journal=RecordingJournal(),
        adapter=adapter,
        driver_state="REVIEW",
    )

    await driver.advance(_task())

    assert driver.is_retired


async def test_a_retired_driver_reports_retired_and_runs_nothing() -> None:
    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok())
    driver = _driver(
        labels=RecordingLabels(PLAN_LABEL),
        journal=RecordingJournal(),
        adapter=adapter,
        driver_state="MERGED",
    )

    advance = await driver.advance(_task())

    assert advance.outcome is AdvanceOutcome.RETIRED


async def test_a_state_with_no_adapter_is_not_driven() -> None:
    # P1 leaves Triage to Classic; a driver holding a triage state has nothing
    # to do rather than crashing on a missing adapter.
    driver = IssueDriver(
        issue_number=501,
        driver_id="drv-501-test",
        repo_slug="acme/widgets",
        adapters={},
        labels=RecordingLabels(PLAN_LABEL),
        journal=RecordingJournal(),
        stage_labels=STAGE_LABELS,
        driver_state="PLAN",
    )

    advance = await driver.advance(_task())

    assert advance.outcome is AdvanceOutcome.RETIRED


# --------------------------------------------------------------------------
# Fatal errors are never swallowed
# --------------------------------------------------------------------------


async def test_a_credit_exhaustion_inside_a_phase_is_re_raised() -> None:
    from subprocess_util import CreditExhaustedError

    def _burn() -> None:
        raise CreditExhaustedError("no credit")

    adapter = ScriptedAdapter(DriverPhase.PLAN, _plan_ok(), on_run=_burn)
    driver = _driver(
        labels=RecordingLabels(PLAN_LABEL),
        journal=RecordingJournal(),
        adapter=adapter,
    )

    with pytest.raises(CreditExhaustedError):
        await driver.advance(_task())
