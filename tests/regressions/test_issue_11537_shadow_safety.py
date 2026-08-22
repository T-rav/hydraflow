"""Shadow mode is a safety property, and this file is where it is proven (#11537).

"Shadow mode" means the Fable director and its broker compute and record what
they *would* dispatch while the live pipeline remains untouched and
authoritative. That claim is worth nothing asserted; it is worth something
demonstrated. So the proof here is differential rather than descriptive: run the
same allocator tick twice over the same inputs, once with no observer and once
with a shadow director attached, and require every live effect to be
**byte-identical**.

Three properties, one test each:

* the observable pipeline effects — label swaps, journal bytes, store claims,
  driver state, and the tick report the loop acts on — do not move;
* an observer that *raises* still does not move them, because a shadow component
  must not be able to fail the thing it is observing;
* the observer really did run, so the two above are not passing vacuously.

The journal comparison is on the file's bytes, not on a parsed view, because a
shadow component that added so much as an extra audit line would have changed
the factory's durable output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from issue_driver import PhaseOutcome
from models import Task

if TYPE_CHECKING:
    from pathlib import Path

    from issue_driver import DriverAdvance, IssueDriver

PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"
REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"
FIND_LABEL = "hydraflow-find"

ORDERED_LABELS = (FIND_LABEL, PLAN_LABEL, READY_LABEL, REVIEW_LABEL, HITL_LABEL)

STAGE_LABELS = {
    "TRIAGE": FIND_LABEL,
    "PLAN": PLAN_LABEL,
    "READY": READY_LABEL,
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": HITL_LABEL,
    "HITL_APPLY": HITL_LABEL,
}


class RecordingGitHub:
    """The ``PRPort`` surface the driver touches, with every call recorded."""

    def __init__(self, labels: dict[int, list[str]]) -> None:
        self.labels = labels
        self.calls: list[tuple[str, int, str]] = []

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        self.calls.append(("read", issue_number, ""))
        return list(self.labels.get(issue_number, []))

    async def swap_pipeline_labels(
        self, issue_number: int, new_label: str, *, pr_number: int | None = None
    ) -> None:
        self.calls.append(("swap", issue_number, new_label))
        self.labels[issue_number] = [new_label]


class RecordingStore:
    """The four ``IssueStorePort`` methods the allocator uses, with a call log."""

    def __init__(self, plannable: list[Task]) -> None:
        self._plannable = list(plannable)
        self.calls: list[tuple[str, Any]] = []

    def get_plannable(self, max_count: int) -> list[Task]:
        taken, self._plannable = (
            self._plannable[:max_count],
            self._plannable[max_count:],
        )
        self.calls.append(("get_plannable", tuple(t.id for t in taken)))
        return taken

    def get_implementable(self, max_count: int) -> list[Task]:
        return []

    def get_reviewable(self, max_count: int) -> list[Task]:
        return []

    def release_in_flight(
        self, issue_numbers: set[int], *, expected_stage: str | None = None
    ) -> None:
        self.calls.append(("release", tuple(sorted(issue_numbers))))

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self.calls.append(("enqueue", (task.id, next_stage)))


class PlanningAdapter:
    """Plans one issue to the ready label — a real boundary, really committed."""

    phase = DriverPhase.PLAN
    target_label = READY_LABEL
    sub_state_target = None

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(
            ok=True,
            next_label=READY_LABEL,
            artifact={"phase": "PLAN", "issue": task.id},
            detail="planned",
        )


class SpyDirector:
    """A stand-in shadow director: observes every boundary, changes nothing.

    What this file proves is the **seam's shape** — that an observer returns
    nothing the allocator consults, and that its exception is contained. It does
    NOT prove anything about the shipped ``FableDirector``, and it does not take
    time: the comparison here is over *values*, so a slow observer would look
    identical to a fast one. That the real director produces byte-identical
    effects through the real ports is
    ``tests/scenarios/test_fable_director_shadow_scenario.py``'s job, and the
    latency cost of running one is bounded by ``director_turn_timeout_seconds``
    and by the aggregate spend ceiling, not by anything asserted here.
    """

    def __init__(self) -> None:
        self.seen: list[tuple[int, str, str]] = []

    async def observe_boundary(
        self, *, task: Task, advance: DriverAdvance, driver: IssueDriver
    ) -> None:
        self.seen.append((task.id, advance.outcome.value, driver.driver_state))


class ExplodingDirector:
    """A shadow director that fails on every boundary."""

    def __init__(self) -> None:
        self.calls = 0

    async def observe_boundary(
        self, *, task: Task, advance: DriverAdvance, driver: IssueDriver
    ) -> None:
        self.calls += 1
        raise RuntimeError("the director turn blew up")


class _DeterministicUUID:
    """A ``uuid4`` stand-in so two runs mint the same driver ids.

    Driver ids are random by construction, so the journal's bytes cannot match
    across runs unless that one field is pinned. Pinning it is the honest move:
    the claim under test is that the *pipeline* effects are identical, and a
    random identifier is not a pipeline effect. Everything else in the journal
    line stays exactly as production writes it.
    """

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> _DeterministicUUID:
        self._n += 1
        return self

    @property
    def hex(self) -> str:
        return f"{self._n:032x}"


def _manager(
    tmp_path: Path,
    *,
    name: str,
    observer: object | None,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DriverManager, RecordingGitHub, RecordingStore, Path]:
    """One allocator over its own private journal file, so bytes are comparable."""
    import driver_manager as driver_manager_module

    monkeypatch.setattr(
        driver_manager_module.uuid, "uuid4", _DeterministicUUID(), raising=True
    )
    tasks = [Task(id=1, title="issue 1", tags=[PLAN_LABEL])]
    github = RecordingGitHub({1: [PLAN_LABEL]})
    store = RecordingStore(tasks)
    journal_path = tmp_path / f"{name}-driver_journal.jsonl"
    manager = DriverManager(
        store=store,
        labels=PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(journal_path),
        ownership=DriverOwnershipRegistry(enabled=True),
        adapters={DriverPhase.PLAN: PlanningAdapter()},
        stage_labels=STAGE_LABELS,
        repo_slug="acme/widgets",
        max_in_flight=4,
        stage_caps={DriverPhase.PLAN: 4},
        observer=observer,
    )
    return manager, github, store, journal_path


async def _run(
    tmp_path: Path,
    *,
    name: str,
    observer: object | None,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Tick twice and return every observable live effect of the run."""
    manager, github, store, journal_path = _manager(
        tmp_path, name=name, observer=observer, monkeypatch=monkeypatch
    )
    reports = [await manager.tick(), await manager.tick()]
    return {
        "github_calls": github.calls,
        "labels": github.labels,
        "store_calls": store.calls,
        "journal_bytes": journal_path.read_bytes() if journal_path.exists() else b"",
        "admitted": [report.admitted for report in reports],
        "released": [report.released for report in reports],
        "advances": [
            [(a.issue_number, a.outcome.value, a.state) for a in report.advanced]
            for report in reports
        ],
    }


def _digest(effects: dict[str, object]) -> dict[str, object]:
    """Everything except the journal, which is compared as raw bytes."""
    return {key: value for key, value in effects.items() if key != "journal_bytes"}


async def test_a_shadow_director_leaves_every_live_pipeline_effect_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = await _run(
        tmp_path, name="baseline", observer=None, monkeypatch=monkeypatch
    )

    shadowed = await _run(
        tmp_path, name="shadowed", observer=SpyDirector(), monkeypatch=monkeypatch
    )

    assert _digest(shadowed) == _digest(baseline)


async def test_a_shadow_director_leaves_the_durable_journal_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = await _run(
        tmp_path, name="baseline", observer=None, monkeypatch=monkeypatch
    )

    shadowed = await _run(
        tmp_path, name="shadowed", observer=SpyDirector(), monkeypatch=monkeypatch
    )

    assert shadowed["journal_bytes"] == baseline["journal_bytes"]


async def test_a_director_that_raises_still_changes_no_live_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A shadow component must not be able to fail the thing it observes. If the
    # director's exception escaped, the allocator's ``except`` would log the
    # driver as having raised and skip the rest of its tick — the observation
    # would have become an actuator.
    baseline = await _run(
        tmp_path, name="baseline", observer=None, monkeypatch=monkeypatch
    )

    shadowed = await _run(
        tmp_path, name="shadowed", observer=ExplodingDirector(), monkeypatch=monkeypatch
    )

    assert _digest(shadowed) == _digest(baseline)


async def test_a_director_that_raises_does_not_propagate_out_of_the_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, _github, _store, _journal = _manager(
        tmp_path,
        name="raises",
        observer=ExplodingDirector(),
        monkeypatch=monkeypatch,
    )

    report = await manager.tick()

    assert report.admitted == (1,)


async def test_the_observer_actually_ran_so_the_equality_is_not_vacuous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without this the three tests above would pass just as happily against an
    # observer seam that was never called at all.
    director = SpyDirector()
    manager, _github, _store, _journal = _manager(
        tmp_path, name="spied", observer=director, monkeypatch=monkeypatch
    )

    await manager.tick()

    assert director.seen == [(1, "committed", "READY")]


async def test_a_credit_exhausted_director_still_stops_the_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one exception a shadow component MUST be allowed to propagate: a burnt
    # credit balance is a factory-wide signal, not a shadow failure, and
    # swallowing it would burn attempt budget against an exhausted account.
    from exception_classify import CreditExhaustedError

    class CreditBurntDirector:
        async def observe_boundary(
            self, *, task: Task, advance: DriverAdvance, driver: IssueDriver
        ) -> None:
            raise CreditExhaustedError("weekly limit reached")

    manager, _github, _store, _journal = _manager(
        tmp_path,
        name="credit",
        observer=CreditBurntDirector(),
        monkeypatch=monkeypatch,
    )

    with pytest.raises(CreditExhaustedError):
        await manager.tick()
