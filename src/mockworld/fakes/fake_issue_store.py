"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub state.

Standalone class created for the sandbox entrypoint (Task 1.10), which
constructs Fakes via build_services() overrides — monkeypatching only
works in-process and can't reach the docker container.

Task 2.5b widening: implements the full IssueStorePort surface plus the
concrete-only methods the orchestrator dispatches via
``cast("IssueStore", self._svc.store)`` (``start``, ``clear_active``,
``get_active_issues``, ``get_queue_stats``, ``get_pipeline_snapshot``,
``is_in_pipeline``, ``get_merged_numbers``, ``get_cached``,
``get_hitl_issues``, ``has_completed_initial_refresh``).

Implementation strategy:

The Fake derives queue state from FakeGitHub's ``_issues`` dict (keyed
by issue number, carrying labels/state/comments/updated_at) on every
read. There's no separate routing/dedup machinery — labels are the source
of truth, mirroring the real IssueStore's *eventual* state but without
the in-flight protection / eager-transition / refresh-cycle plumbing.

Active / merged / processed_count tracking lives on the Fake itself
(``_active``, ``_merged_numbers``, ``_processed_count``) so the
orchestrator's stats / snapshot calls return populated payloads.

This is sufficient for the sandbox scenario tier: scenarios assert on
end-state outcomes (issue merged, label transitions visible) rather
than on the queue's intermediate dedup / in-flight semantics.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from events import EventType, HydraFlowEvent
from models import (
    HITLItem,
    PipelineIssueStatus,
    PipelineSnapshotEntry,
    QueueStats,
    Task,
)

if TYPE_CHECKING:
    from events import EventBus
    from mockworld.fakes.fake_github import FakeGitHub
    from mockworld.seed import MockWorldSeed


logger = logging.getLogger("hydraflow.mockworld.fake_issue_store")


# Stage constants — match issue_store.IssueStoreStage values without
# importing the real module (keeps the Fake source-of-truth contained).
STAGE_FIND = "find"
STAGE_PLAN = "plan"
STAGE_READY = "ready"
STAGE_REVIEW = "review"
STAGE_HITL = "hitl"
STAGE_MERGED = "merged"
STAGE_DIAGNOSE = "diagnose"

_LABEL_TO_STAGE: dict[str, str] = {
    "hydraflow-find": STAGE_FIND,
    "hydraflow-plan": STAGE_PLAN,
    "hydraflow-ready": STAGE_READY,
    "hydraflow-review": STAGE_REVIEW,
    "hydraflow-hitl": STAGE_HITL,
    # Review-fix-cap escalation routes through the diagnostic loop:
    # enqueue_transition(task, "diagnose") must map to hydraflow-diagnose,
    # else the transition is silently dropped and the issue never reaches
    # the DiagnosticLoop (which polls hydraflow-diagnose). See s05.
    "hydraflow-diagnose": STAGE_DIAGNOSE,
}

_CLAIMABLE_STAGES = frozenset({STAGE_FIND, STAGE_PLAN, STAGE_READY, STAGE_REVIEW})


@dataclass
class FakeIssueRecord:
    """Minimal IssueStore-shaped payload."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueStore:
    """In-memory IssueStorePort impl backed by a FakeGitHub world.

    Wider than PR A's narrow surface — covers the full
    ``IssueStorePort`` plus IssueStore-only methods the orchestrator
    invokes via ``cast("IssueStore", store)``. See module docstring for
    the design tradeoff (labels as source of truth vs. real-store dedup).
    """

    _is_fake_adapter = True

    def __init__(self, github: FakeGitHub, event_bus: EventBus) -> None:
        self._github = github
        self._bus = event_bus
        # Unlike the real IssueStore, the Fake computes every read straight
        # from FakeGitHub's live issue state — there is no polling gap to
        # model, so a freshly-constructed Fake is immediately authoritative.
        # Defaults True; a scenario simulating the #11279 boot-window race
        # can flip it False and call refresh() to flip it back, mirroring
        # the real store's lifecycle.
        self._has_completed_initial_refresh = True

        # Active issue tracking: issue_number -> stage
        self._active: dict[int, str] = {}
        # In-flight (between dequeue and mark_active) tracking
        self._in_flight: dict[int, str] = {}
        # Stage-scoped release mirrors the real store, where dequeue removes
        # the queue entry until the next refresh reconciles GitHub labels.
        self._released_stage_claims: set[tuple[int, str]] = set()
        # Merged issues for snapshot reporting
        self._merged_numbers: set[int] = set()
        # Issues ever observed in HITL, even after they've since left it
        # (resolved, merged, etc). Folded in by get_hitl_issues() as a side
        # effect of every poll — mirrors IssueStore._hitl_visited (#10509).
        self._hitl_visited: set[int] = set()
        # Per-stage throughput counters
        self._processed_count: dict[str, int] = {
            STAGE_FIND: 0,
            STAGE_PLAN: 0,
            STAGE_READY: 0,
            STAGE_REVIEW: 0,
            STAGE_HITL: 0,
        }
        # Dedup diagnostics — real store tracks real dedups; Fake just
        # exposes the shape so QueueStats serializes cleanly.
        self._dedup_stats: dict[str, int] = {
            "incoming_tasks": 0,
            "queued_entries": 0,
            "snapshot_entries": 0,
        }
        self._last_poll_ts: str | None = None

    @classmethod
    def from_seed(cls, seed: MockWorldSeed, event_bus: EventBus) -> FakeIssueStore:
        from mockworld.fakes.fake_github import FakeGitHub

        github = FakeGitHub.from_seed(seed)
        return cls(github=github, event_bus=event_bus)

    @property
    def has_completed_initial_refresh(self) -> bool:
        """Mirrors ``IssueStore.has_completed_initial_refresh`` (#11279)."""
        return self._has_completed_initial_refresh

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stage_for(self, issue: Any) -> str | None:
        """Pick the most-advanced HydraFlow stage label on *issue*."""
        # Higher index in this list = later in pipeline = takes precedence
        priority = [
            STAGE_FIND,
            STAGE_PLAN,
            STAGE_READY,
            STAGE_REVIEW,
            STAGE_HITL,
        ]
        best: str | None = None
        best_idx = -1
        for label in issue.labels:
            stage = _LABEL_TO_STAGE.get(label)
            if stage is None:
                continue
            try:
                idx = priority.index(stage)
            except ValueError:
                continue
            if idx > best_idx:
                best_idx = idx
                best = stage
        return best

    def _issue_to_task(self, issue: Any) -> Task:
        return Task(
            id=issue.number,
            title=issue.title,
            body=issue.body,
            tags=list(issue.labels),
            comments=list(getattr(issue, "comments", [])),
            source_url="",
            created_at="",
        )

    def _queued_for_stage(self, stage: str) -> list[Task]:
        """Issues whose top label maps to *stage* and which aren't active/in-flight."""
        out: list[Task] = []
        for issue in self._github._issues.values():
            if issue.state != "open":
                continue
            if self._stage_for(issue) != stage:
                continue
            if (issue.number, stage) in self._released_stage_claims:
                continue
            if issue.number in self._active or issue.number in self._in_flight:
                continue
            out.append(self._issue_to_task(issue))
        return out

    # ------------------------------------------------------------------
    # Lifecycle (orchestrator-only via cast("IssueStore", store))
    # ------------------------------------------------------------------

    async def start(self, stop_event: asyncio.Event) -> None:
        """Run the polling-equivalent loop until *stop_event* is set.

        For the Fake, "polling" is a no-op because FakeGitHub state is
        the canonical source — any label change is immediately visible
        to ``_queued_for_stage``. We still run the loop body so the
        orchestrator's restart/supervision behavior matches production.
        """
        await self.refresh()
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                break
            except TimeoutError:
                pass
            await self.refresh()

    async def refresh(self) -> None:
        """Publish a queue-update event to keep the dashboard in sync."""
        self._released_stage_claims.clear()
        self._last_poll_ts = datetime.now(UTC).isoformat()
        self._has_completed_initial_refresh = True
        try:
            stats = self.get_queue_stats()
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.QUEUE_UPDATE,
                    data=stats.model_dump(),
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("FakeIssueStore.refresh publish failed", exc_info=True)

    # ------------------------------------------------------------------
    # Queue accessors
    # ------------------------------------------------------------------

    def get_triageable(self, max_count: int) -> list[Task]:
        return self._take(STAGE_FIND, max_count)

    def get_plannable(self, max_count: int) -> list[Task]:
        return self._take(STAGE_PLAN, max_count)

    def get_implementable(self, max_count: int) -> list[Task]:
        return self._take(STAGE_READY, max_count)

    def get_reviewable(self, max_count: int) -> list[Task]:
        return self._take(STAGE_REVIEW, max_count)

    def get_hitl_issues(self) -> set[int]:
        current = {
            issue.number
            for issue in self._github._issues.values()
            if issue.state == "open" and self._stage_for(issue) == STAGE_HITL
        }
        self._hitl_visited.update(current)
        return current

    def _take(self, stage: str, max_count: int) -> list[Task]:
        tasks = self._queued_for_stage(stage)[:max_count]
        for t in tasks:
            self._in_flight[t.id] = stage
        return tasks

    # ------------------------------------------------------------------
    # Active / lifecycle tracking
    # ------------------------------------------------------------------

    def mark_active(self, issue_number: int, stage: str) -> None:
        self._in_flight.pop(issue_number, None)
        self._active[issue_number] = stage

    def try_claim_stage(self, task: Task, expected_stage: str) -> bool:
        """Reserve a task only when FakeGitHub still exposes that stage."""
        if expected_stage not in _CLAIMABLE_STAGES:
            return False
        if (
            task.id in self._active
            or task.id in self._in_flight
            or task.id in self._merged_numbers
            or (task.id, expected_stage) in self._released_stage_claims
        ):
            return False
        issue = self._github._issues.get(task.id)
        if (
            issue is None
            or issue.state != "open"
            or self._stage_for(issue) != expected_stage
        ):
            return False
        self._in_flight[task.id] = expected_stage
        return True

    def mark_complete(self, issue_number: int) -> None:
        self._in_flight.pop(issue_number, None)
        stage = self._active.pop(issue_number, None)
        if stage and stage in self._processed_count:
            self._processed_count[stage] += 1

    def mark_merged(self, issue_number: int) -> None:
        self._merged_numbers.add(issue_number)

    def get_merged_numbers(self) -> frozenset[int]:
        return frozenset(self._merged_numbers)

    def is_active(self, issue_number: int) -> bool:
        return issue_number in self._active

    def is_in_pipeline(self, issue_number: int) -> bool:
        if issue_number in self._active or issue_number in self._in_flight:
            return True
        issue = self._github._issues.get(issue_number)
        return issue is not None and self._stage_for(issue) is not None

    def get_active_issues(self) -> dict[int, str]:
        return dict(self._active)

    def get_worker_held_issues(self) -> dict[int, str]:
        """Worker-held issues (``_active`` ∪ ``_in_flight``); mirrors IssueStore.

        Ground truth for worker-derived epic execution state (#10299).
        """
        held: dict[int, str] = {num: str(s) for num, s in self._in_flight.items()}
        held.update({num: str(s) for num, s in self._active.items()})
        return held

    def get_queued_issues(self) -> dict[int, str]:
        """Issues awaiting dispatch in a stage queue (not active/in-flight)."""
        queued: dict[int, str] = {}
        for stage in (STAGE_FIND, STAGE_PLAN, STAGE_READY, STAGE_REVIEW):
            for task in self._queued_for_stage(stage):
                queued.setdefault(task.id, stage)
        return queued

    def clear_active(self) -> None:
        self._active.clear()
        self._in_flight.clear()
        self._released_stage_claims.clear()

    def release_in_flight(
        self,
        issue_numbers: set[int],
        *,
        expected_stage: str | None = None,
    ) -> None:
        for n in issue_numbers:
            if expected_stage is None or self._in_flight.get(n) == expected_stage:
                self._in_flight.pop(n, None)
                if expected_stage is not None:
                    self._released_stage_claims.add((n, expected_stage))

    def get_cached(self, issue_number: int) -> Task | None:
        issue = self._github._issues.get(issue_number)
        if issue is None:
            return None
        return self._issue_to_task(issue)

    # ------------------------------------------------------------------
    # Transition / enrichment
    # ------------------------------------------------------------------

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        """Apply the stage transition immediately by mutating issue labels.

        Real IssueStore caches an eager-transition flag separate from
        GitHub state; the Fake collapses both views into FakeGitHub's
        labels because there's no async GitHub round-trip to wait on.
        """
        stage_to_label = {v: k for k, v in _LABEL_TO_STAGE.items()}
        new_label = stage_to_label.get(next_stage)
        if new_label is None:
            return
        issue = self._github._issues.get(task.id)
        if issue is None:
            return
        self._released_stage_claims = {
            claim for claim in self._released_stage_claims if claim[0] != task.id
        }
        issue.labels = [lbl for lbl in issue.labels if lbl not in _LABEL_TO_STAGE]
        issue.labels.append(new_label)
        self._in_flight.pop(task.id, None)

    async def enrich_with_comments(self, task: Task) -> Task:
        issue = self._github._issues.get(task.id)
        if issue is None:
            return task
        comments = list(getattr(issue, "comments", []))
        if not comments:
            return task
        return task.model_copy(update={"comments": comments})

    # ------------------------------------------------------------------
    # Stats / snapshot (orchestrator-only via cast)
    # ------------------------------------------------------------------

    def get_queue_stats(self) -> QueueStats:
        queue_depth: dict[str, int] = {}
        for stage in (
            STAGE_FIND,
            STAGE_PLAN,
            STAGE_READY,
            STAGE_REVIEW,
        ):
            queue_depth[stage] = len(self._queued_for_stage(stage))
        queue_depth[STAGE_HITL] = len(self.get_hitl_issues())
        queue_depth[STAGE_MERGED] = len(self._merged_numbers)

        active_count: dict[str, int] = {}
        for stage in (
            STAGE_FIND,
            STAGE_PLAN,
            STAGE_READY,
            STAGE_REVIEW,
            STAGE_HITL,
        ):
            active_count[stage] = sum(1 for s in self._active.values() if s == stage)

        return QueueStats(
            queue_depth=queue_depth,
            active_count=active_count,
            total_processed=dict(self._processed_count),
            last_poll_timestamp=self._last_poll_ts,
            dedup_stats=dict(self._dedup_stats),
            in_flight_count=len(self._in_flight),
        )

    def get_pipeline_snapshot(self) -> dict[str, list[PipelineSnapshotEntry]]:
        snapshot: dict[str, list[PipelineSnapshotEntry]] = {}

        def _entry(
            num: int, status: str, *, hitl_visited: bool = False
        ) -> PipelineSnapshotEntry:
            issue = self._github._issues.get(num)
            return PipelineSnapshotEntry(
                issue_number=num,
                title=issue.title if issue else f"Issue #{num}",
                url="",
                status=status,
                hitl_visited=hitl_visited,
            )

        for stage in (
            STAGE_FIND,
            STAGE_PLAN,
            STAGE_READY,
            STAGE_REVIEW,
        ):
            queued = [
                _entry(t.id, PipelineIssueStatus.QUEUED)
                for t in self._queued_for_stage(stage)
            ]
            in_flight = [
                _entry(num, PipelineIssueStatus.PROCESSING)
                for num, s in self._in_flight.items()
                if s == stage
            ]
            active = [
                _entry(num, PipelineIssueStatus.PROCESSING)
                for num, s in self._active.items()
                if s == stage
            ]
            entries = queued + in_flight + active
            if entries:
                snapshot[stage] = entries

        # get_hitl_issues() also folds the current HITL set into
        # _hitl_visited, so it must run before the merged entries below are
        # built.
        hitl_now = self.get_hitl_issues()
        snapshot[STAGE_HITL] = [
            _entry(num, PipelineIssueStatus.HITL, hitl_visited=True) for num in hitl_now
        ]
        snapshot[STAGE_MERGED] = [
            _entry(
                num,
                PipelineIssueStatus.MERGED,
                hitl_visited=num in self._hitl_visited,
            )
            for num in self._merged_numbers
        ]
        return snapshot

    # ------------------------------------------------------------------
    # PR A's narrower surface (kept for backward compatibility with the
    # FakeIssueStore unit tests written before Task 2.5b widening).
    # ------------------------------------------------------------------

    async def get(self, issue_number: int) -> FakeIssueRecord:
        issue = self._github._issues[issue_number]
        return FakeIssueRecord(
            number=issue.number,
            title=issue.title,
            body=issue.body,
            labels=list(issue.labels),
        )

    async def transition(
        self, issue_number: int, from_label: str, to_label: str
    ) -> None:
        issue = self._github._issues[issue_number]
        if from_label in issue.labels:
            issue.labels.remove(from_label)
        if to_label not in issue.labels:
            issue.labels.append(to_label)

    async def list_by_label(self, label: str) -> list[FakeIssueRecord]:
        out = []
        for issue in self._github._issues.values():
            if label in issue.labels and issue.state == "open":
                out.append(
                    FakeIssueRecord(
                        number=issue.number,
                        title=issue.title,
                        body=issue.body,
                        labels=list(issue.labels),
                    )
                )
        return out

    # HITLItem-list — required by some loops, returns empty by default
    async def list_hitl_items(self, *_a: Any, **_kw: Any) -> list[HITLItem]:
        return []
