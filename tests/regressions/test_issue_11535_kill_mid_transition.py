"""Kill-mid-transition regression for the driver boundary (#11535, ADR-0137 B6/C8).

ADR-0137's adversarial panel rejected a spec that *asserted* crash-safety, and
named the behavioural test that would actually demonstrate it: kill the process
in each of the two gaps in the boundary transaction and prove recovery lands on
the right stage both times, with no audit record claiming a transition the label
never committed.

The boundary's order is::

    persist artifact  --(gap 1)--  swap label  --(gap 2)--  append checkpoint

The two gaps fail differently on purpose:

* **Gap 1** — the label never moved, so the transition did not happen. Recovery
  must find the issue at the OLD stage and re-run the phase. The journal must
  not carry a committed key, because a key there would make the replay skip the
  boundary and strand the issue at a stage nothing will move it from again.
* **Gap 2** — the label moved, so the transition DID happen, on GitHub, where
  truth lives. Recovery reads the label and lands on the NEW stage even though
  the audit record is missing. That lag is explicitly allowed; a wrong stage is
  not.

A "kill" here is a raise from the durable-side port, and recovery is a fresh
:class:`DriverJournal` over the same file plus a driver rebuilt from the live
label — the same two inputs a real restart has.
"""

from __future__ import annotations

import pytest

from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from issue_driver import AdvanceOutcome, IssueDriver, PhaseOutcome
from models import Task

PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"

STAGE_LABELS = {"PLAN": PLAN_LABEL, "READY": READY_LABEL}
ISSUE = 11535


class KillableLabels:
    """A label port that can die exactly at the swap (gap 1).

    Also carries the C5(a) intent slot, so a test can assert that a boundary
    killed before its swap leaves recovery the record it needs to finish the
    transition in the right direction.
    """

    def __init__(self, label: str, *, die_on_commit: bool = False) -> None:
        self.label = label
        self.die_on_commit = die_on_commit
        self.intent: tuple[str, str, int, int] | None = None

    async def read_stage_label(
        self, issue_number: int, *, epoch: int = 0, phase_attempt: int = 0
    ) -> str | None:
        return self.label

    def record_intent(
        self,
        issue_number: int,
        *,
        from_label: str,
        to_label: str,
        epoch: int,
        phase_attempt: int,
    ) -> None:
        self.intent = (from_label, to_label, epoch, phase_attempt)

    def clear_intent(self, issue_number: int) -> None:
        self.intent = None

    async def commit_stage_label(self, issue_number: int, label: str) -> None:
        if self.die_on_commit:
            raise RuntimeError("process killed between persist and label swap")
        self.label = label


class KillableJournal:
    """Wraps a real journal and can die exactly at the checkpoint (gap 2)."""

    def __init__(self, inner: DriverJournal, *, die_on_checkpoint: bool = False) -> None:
        self._inner = inner
        self.die_on_checkpoint = die_on_checkpoint

    def committed_keys(self, issue_number: int) -> frozenset[str]:
        return self._inner.committed_keys(issue_number)

    def persist_artifact(self, issue_number, key, artifact) -> None:
        self._inner.persist_artifact(issue_number, key, artifact)

    def append_checkpoint(self, issue_number, key, checkpoint) -> None:
        if self.die_on_checkpoint:
            raise RuntimeError("process killed between label swap and checkpoint")
        self._inner.append_checkpoint(issue_number, key, checkpoint)


class PlanAdapter:
    """A planner that always succeeds, counting how many times it ran."""

    phase = DriverPhase.PLAN
    target_label = READY_LABEL

    def __init__(self) -> None:
        self.runs = 0

    async def run(self, task: Task, *, lease) -> PhaseOutcome:
        self.runs += 1
        return PhaseOutcome(ok=True, next_label=READY_LABEL, artifact={"plan": "ok"})


def _driver(labels, journal, adapter, *, state: str, epoch: int = 0) -> IssueDriver:
    return IssueDriver(
        issue_number=ISSUE,
        driver_id=f"drv-{ISSUE}",
        repo_slug="acme/widgets",
        adapters={DriverPhase.PLAN: adapter},
        labels=labels,
        journal=journal,
        stage_labels=STAGE_LABELS,
        driver_state=state,
        epoch=epoch,
    )


def _task() -> Task:
    return Task(id=ISSUE, title="fenced driver")


# --------------------------------------------------------------------------
# Gap 1 — killed between the artifact persist and the label swap
# --------------------------------------------------------------------------


async def test_gap_one_kill_leaves_the_label_at_the_old_stage(tmp_path) -> None:
    labels = KillableLabels(PLAN_LABEL, die_on_commit=True)
    journal = DriverJournal(tmp_path / "driver_journal.jsonl")
    driver = _driver(labels, journal, PlanAdapter(), state="PLAN")

    with pytest.raises(RuntimeError, match="between persist and label swap"):
        await driver.advance(_task())

    assert labels.label == PLAN_LABEL


async def test_gap_one_kill_records_no_committed_boundary(tmp_path) -> None:
    # The load-bearing one. A committed key here would make the replay below
    # skip the transition entirely and strand the issue on the plan label.
    labels = KillableLabels(PLAN_LABEL, die_on_commit=True)
    path = tmp_path / "driver_journal.jsonl"
    driver = _driver(labels, DriverJournal(path), PlanAdapter(), state="PLAN")
    with pytest.raises(RuntimeError):
        await driver.advance(_task())

    assert DriverJournal(path).committed_keys(ISSUE) == frozenset()


async def test_gap_one_recovery_re_runs_the_phase_and_reaches_the_next_stage(
    tmp_path,
) -> None:
    labels = KillableLabels(PLAN_LABEL, die_on_commit=True)
    path = tmp_path / "driver_journal.jsonl"
    adapter = PlanAdapter()
    with pytest.raises(RuntimeError):
        await _driver(labels, DriverJournal(path), adapter, state="PLAN").advance(_task())

    # Restart: a fresh journal over the same file, a driver rebuilt from the
    # live label, at a higher epoch that fences the dead generation.
    labels.die_on_commit = False
    recovered = _driver(labels, DriverJournal(path), adapter, state="PLAN", epoch=1)
    await recovered.advance(_task())

    assert labels.label == READY_LABEL


async def test_gap_one_recovery_does_not_skip_the_boundary_as_already_done(
    tmp_path,
) -> None:
    labels = KillableLabels(PLAN_LABEL, die_on_commit=True)
    path = tmp_path / "driver_journal.jsonl"
    adapter = PlanAdapter()
    with pytest.raises(RuntimeError):
        await _driver(labels, DriverJournal(path), adapter, state="PLAN").advance(_task())

    labels.die_on_commit = False
    recovered = _driver(labels, DriverJournal(path), adapter, state="PLAN", epoch=1)
    advance = await recovered.advance(_task())

    assert advance.outcome is AdvanceOutcome.COMMITTED


# --------------------------------------------------------------------------
# Gap 2 — killed between the label swap and the checkpoint append
# --------------------------------------------------------------------------


async def test_gap_two_kill_leaves_the_label_on_the_new_stage(tmp_path) -> None:
    labels = KillableLabels(PLAN_LABEL)
    journal = KillableJournal(
        DriverJournal(tmp_path / "driver_journal.jsonl"), die_on_checkpoint=True
    )
    driver = _driver(labels, journal, PlanAdapter(), state="PLAN")

    with pytest.raises(RuntimeError, match="between label swap and checkpoint"):
        await driver.advance(_task())

    assert labels.label == READY_LABEL


async def test_gap_two_recovery_reads_the_new_stage_from_the_label(tmp_path) -> None:
    # The audit record never landed, but the label did. Label truth wins, and
    # the recovered driver must NOT re-plan an issue that is already ready.
    labels = KillableLabels(PLAN_LABEL)
    path = tmp_path / "driver_journal.jsonl"
    adapter = PlanAdapter()
    with pytest.raises(RuntimeError):
        await _driver(
            labels, KillableJournal(DriverJournal(path), die_on_checkpoint=True), adapter,
            state="PLAN",
        ).advance(_task())

    recovered = _driver(labels, DriverJournal(path), adapter, state="PLAN", epoch=1)
    advance = await recovered.advance(_task())

    assert advance.outcome is AdvanceOutcome.PREEMPTED, (
        "the live label already says ready; the driver follows it "
        "instead of re-planning"
    )


async def test_gap_two_recovery_lands_the_driver_on_the_stage_the_label_names(
    tmp_path,
) -> None:
    labels = KillableLabels(PLAN_LABEL)
    path = tmp_path / "driver_journal.jsonl"
    adapter = PlanAdapter()
    with pytest.raises(RuntimeError):
        await _driver(
            labels, KillableJournal(DriverJournal(path), die_on_checkpoint=True), adapter,
            state="PLAN",
        ).advance(_task())

    recovered = _driver(labels, DriverJournal(path), adapter, state="PLAN", epoch=1)
    await recovered.advance(_task())

    assert recovered.driver_state == "READY"


async def test_no_checkpoint_ever_records_a_transition_the_label_did_not_commit(
    tmp_path,
) -> None:
    # The single invariant both gaps exist to protect, stated once: after a
    # kill in gap 1 (label never moved) the journal holds no checkpoint at all.
    labels = KillableLabels(PLAN_LABEL, die_on_commit=True)
    path = tmp_path / "driver_journal.jsonl"
    with pytest.raises(RuntimeError):
        await _driver(labels, DriverJournal(path), PlanAdapter(), state="PLAN").advance(
            _task()
        )

    assert DriverJournal(path).last_epoch(ISSUE) is None


# --------------------------------------------------------------------------
# The two BACKWARD edges — the cases priority-based reconciliation reverts
# --------------------------------------------------------------------------
#
# ADR-0137 B6 requires these specifically, because a forward-only kill test
# passes against the *wrong* reconciliation rule and would have let #11627's
# most-advanced-wins repair ship looking green.


class BackwardAdapter:
    """A phase that moves the issue backward, as a route-back or resume does."""

    def __init__(self, phase: DriverPhase, from_label: str) -> None:
        self.phase = phase
        self.target_label = READY_LABEL
        self._from_label = from_label
        self.runs = 0

    async def run(self, task: Task, *, lease) -> PhaseOutcome:
        self.runs += 1
        return PhaseOutcome(ok=True, next_label=READY_LABEL, artifact={"back": "ok"})


REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"
BACKWARD_STAGE_LABELS = {
    "PLAN": PLAN_LABEL,
    "READY": READY_LABEL,
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": HITL_LABEL,
    "HITL_APPLY": HITL_LABEL,
}


async def _kill_backward_edge(tmp_path, *, state: str, from_label: str, phase):
    """Run a backward transition and kill it at the swap; return the intent."""
    labels = KillableLabels(from_label, die_on_commit=True)
    driver = IssueDriver(
        issue_number=ISSUE,
        driver_id=f"drv-{ISSUE}",
        repo_slug="acme/widgets",
        adapters={phase: BackwardAdapter(phase, from_label)},
        labels=labels,
        journal=DriverJournal(tmp_path / "driver_journal.jsonl"),
        stage_labels=BACKWARD_STAGE_LABELS,
        driver_state=state,
    )
    with pytest.raises(RuntimeError):
        await driver.advance(_task())
    return labels


async def test_a_killed_route_back_leaves_an_intent_naming_the_backward_target(
    tmp_path,
) -> None:
    # DIAGNOSE -> READY. Labels after the crash would be review(5) + ready(4);
    # most-advanced-wins picks review and the route-back is silently undone.
    # The recorded intent is what makes the backward target recoverable.
    labels = await _kill_backward_edge(
        tmp_path, state="DIAGNOSE", from_label=REVIEW_LABEL, phase=DriverPhase.REVIEW
    )

    assert labels.intent == (REVIEW_LABEL, READY_LABEL, 0, 0)


async def test_a_killed_hitl_resume_leaves_an_intent_naming_the_backward_target(
    tmp_path,
) -> None:
    # HITL_APPLY -> READY. hitl(6) beats ready(4) under priority, so the resume
    # is reverted; the intent record is what survives the window.
    labels = await _kill_backward_edge(
        tmp_path, state="HITL_APPLY", from_label=HITL_LABEL, phase=DriverPhase.HITL
    )

    assert labels.intent == (HITL_LABEL, READY_LABEL, 0, 0)


@pytest.mark.parametrize(
    ("state", "from_label", "phase"),
    [
        ("DIAGNOSE", REVIEW_LABEL, DriverPhase.REVIEW),
        ("HITL_APPLY", HITL_LABEL, DriverPhase.HITL),
    ],
)
async def test_a_killed_backward_edge_records_no_committed_boundary(
    tmp_path, state: str, from_label: str, phase
) -> None:
    path = tmp_path / "driver_journal.jsonl"
    await _kill_backward_edge(tmp_path, state=state, from_label=from_label, phase=phase)

    assert DriverJournal(path).committed_keys(ISSUE) == frozenset()
