"""Tests for caching_issue_store.CachingIssueStore (#6422 follow-up).

Verifies the read-through cache decorator: every queue read records
a fetch snapshot, enrich_with_comments serves cached data when fresh
and falls through when stale, and lifecycle writes pass through
unchanged. Uses an in-memory fake inner store so tests don't need
the full IssueStore + IssueFetcher + GitHub stack.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from caching_issue_store import CachingIssueStore
from issue_cache import CacheRecord, CacheRecordKind, IssueCache
from models import Task

# ---------------------------------------------------------------------------
# Fake inner store
# ---------------------------------------------------------------------------


class _FakeInnerStore:
    """Minimal IssueStorePort implementation for tests.

    Tracks every method call so tests can assert on what the
    decorator delegated and what it served from cache.
    """

    def __init__(self) -> None:
        self.triageable: list[Task] = []
        self.plannable: list[Task] = []
        self.implementable: list[Task] = []
        self.reviewable: list[Task] = []
        self.calls: list[tuple[str, tuple]] = []
        # enrich_with_comments returns the input task with a fixed
        # marker comment so tests can detect a fall-through.
        self.enrich_call_count = 0

    def get_triageable(self, max_count: int) -> list[Task]:
        self.calls.append(("get_triageable", (max_count,)))
        return self.triageable[:max_count]

    def get_plannable(self, max_count: int) -> list[Task]:
        self.calls.append(("get_plannable", (max_count,)))
        return self.plannable[:max_count]

    def get_implementable(self, max_count: int) -> list[Task]:
        self.calls.append(("get_implementable", (max_count,)))
        return self.implementable[:max_count]

    def get_reviewable(self, max_count: int) -> list[Task]:
        self.calls.append(("get_reviewable", (max_count,)))
        return self.reviewable[:max_count]

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self.calls.append(("enqueue_transition", (task.id, next_stage)))

    def mark_active(self, issue_number: int, stage: str) -> None:
        self.calls.append(("mark_active", (issue_number, stage)))

    def mark_complete(self, issue_number: int) -> None:
        self.calls.append(("mark_complete", (issue_number,)))

    def mark_merged(self, issue_number: int) -> None:
        self.calls.append(("mark_merged", (issue_number,)))

    def release_in_flight(self, issue_numbers: set[int]) -> None:
        self.calls.append(("release_in_flight", (frozenset(issue_numbers),)))

    def is_active(self, issue_number: int) -> bool:
        self.calls.append(("is_active", (issue_number,)))
        return False

    async def enrich_with_comments(self, task: Task) -> Task:
        self.enrich_call_count += 1
        self.calls.append(("enrich_with_comments", (task.id,)))
        return task.model_copy(
            update={
                "comments": [*task.comments, "fetched-from-inner"],
            }
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build(
    tmp_path: Path, *, ttl: int = 300
) -> tuple[CachingIssueStore, _FakeInnerStore, IssueCache]:
    cache = IssueCache(tmp_path / "cache", enabled=True)
    inner = _FakeInnerStore()
    decorator = CachingIssueStore(inner, cache=cache, cache_ttl_seconds=ttl)
    return decorator, inner, cache


def _task(issue_id: int, **kw) -> Task:
    return Task(id=issue_id, title=f"Issue {issue_id}", body="body", **kw)


# ---------------------------------------------------------------------------
# Construction + properties
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_exposes_cache(self, tmp_path: Path) -> None:
        decorator, _, cache = _build(tmp_path)
        assert decorator.cache is cache

    def test_exposes_ttl(self, tmp_path: Path) -> None:
        decorator, *_ = _build(tmp_path, ttl=600)
        assert decorator.cache_ttl_seconds == 600

    def test_default_ttl(self, tmp_path: Path) -> None:
        cache = IssueCache(tmp_path / "cache", enabled=True)
        decorator = CachingIssueStore(_FakeInnerStore(), cache=cache)
        assert decorator.cache_ttl_seconds == 300


# ---------------------------------------------------------------------------
# Queue accessors record fetches
# ---------------------------------------------------------------------------


class TestQueueFetchRecording:
    def test_get_triageable_delegates_and_records(self, tmp_path: Path) -> None:
        decorator, inner, cache = _build(tmp_path)
        inner.triageable = [_task(1), _task(2)]

        result = decorator.get_triageable(5)
        assert [t.id for t in result] == [1, 2]
        assert ("get_triageable", (5,)) in inner.calls

        # Each task got a fetch record with the right stage marker.
        for issue_id in (1, 2):
            history = cache.read_history(issue_id)
            assert any(r.kind == CacheRecordKind.FETCH for r in history)
            fetch = next(r for r in history if r.kind == CacheRecordKind.FETCH)
            assert fetch.payload["stage"] == "triage"

    def test_each_stage_marks_records_correctly(self, tmp_path: Path) -> None:
        decorator, inner, cache = _build(tmp_path)
        inner.triageable = [_task(1)]
        inner.plannable = [_task(2)]
        inner.implementable = [_task(3)]
        inner.reviewable = [_task(4)]

        decorator.get_triageable(1)
        decorator.get_plannable(1)
        decorator.get_implementable(1)
        decorator.get_reviewable(1)

        for issue_id, expected_stage in (
            (1, "triage"),
            (2, "plan"),
            (3, "implement"),
            (4, "review"),
        ):
            fetch = next(
                r
                for r in cache.read_history(issue_id)
                if r.kind == CacheRecordKind.FETCH
            )
            assert fetch.payload["stage"] == expected_stage

    def test_empty_result_records_nothing(self, tmp_path: Path) -> None:
        decorator, _, cache = _build(tmp_path)
        result = decorator.get_triageable(5)
        assert result == []
        assert cache.known_issue_ids() == []

    def test_fetch_record_failure_does_not_break_caller(self, tmp_path: Path) -> None:
        """A broken cache must not prevent the inner store from
        returning results — the decorator is best-effort."""
        decorator, inner, cache = _build(tmp_path)
        inner.triageable = [_task(42)]

        def _boom(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("disk full")

        cache.record_fetch = _boom  # type: ignore[assignment]
        # Must not raise.
        result = decorator.get_triageable(1)
        assert [t.id for t in result] == [42]


# ---------------------------------------------------------------------------
# Lifecycle pass-through
# ---------------------------------------------------------------------------


class TestLifecyclePassThrough:
    def test_enqueue_transition_passes_through(self, tmp_path: Path) -> None:
        decorator, inner, _ = _build(tmp_path)
        decorator.enqueue_transition(_task(1), "plan")
        assert ("enqueue_transition", (1, "plan")) in inner.calls

    def test_mark_methods_pass_through(self, tmp_path: Path) -> None:
        decorator, inner, _ = _build(tmp_path)
        decorator.mark_active(1, "plan")
        decorator.mark_complete(2)
        decorator.mark_merged(3)
        decorator.release_in_flight({4, 5})
        assert ("mark_active", (1, "plan")) in inner.calls
        assert ("mark_complete", (2,)) in inner.calls
        assert ("mark_merged", (3,)) in inner.calls
        # release_in_flight uses frozenset for comparison stability.
        assert any(call[0] == "release_in_flight" for call in inner.calls)

    def test_is_active_returns_inner_value(self, tmp_path: Path) -> None:
        decorator, inner, _ = _build(tmp_path)
        assert decorator.is_active(1) is False
        assert ("is_active", (1,)) in inner.calls


# ---------------------------------------------------------------------------
# enrich_with_comments — read-through with TTL
# ---------------------------------------------------------------------------


class TestEnrichRead:
    @pytest.mark.asyncio
    async def test_first_call_falls_through_to_inner(self, tmp_path: Path) -> None:
        decorator, inner, cache = _build(tmp_path)
        result = await decorator.enrich_with_comments(_task(42))
        assert "fetched-from-inner" in result.comments
        assert inner.enrich_call_count == 1

        # Cache now has an enriched record.
        history = cache.read_history(42)
        assert any(r.kind == CacheRecordKind.ENRICHED for r in history)

    @pytest.mark.asyncio
    async def test_second_call_serves_from_cache(self, tmp_path: Path) -> None:
        decorator, inner, _ = _build(tmp_path)
        await decorator.enrich_with_comments(_task(42))
        await decorator.enrich_with_comments(_task(42))
        # Inner was only hit once; the second call came from cache.
        assert inner.enrich_call_count == 1

    @pytest.mark.asyncio
    async def test_stale_cache_falls_through(self, tmp_path: Path) -> None:
        """A cache record older than TTL must be ignored — the decorator
        falls through to the inner store and writes a fresh record."""
        decorator, inner, cache = _build(tmp_path, ttl=60)

        # Seed a stale enriched record by writing one with an old ts.
        stale_ts = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.ENRICHED,
                ts=stale_ts,
                payload={
                    "title": "stale",
                    "body": "stale body",
                    "tags": [],
                    "comments": ["stale-comment"],
                },
            )
        )

        result = await decorator.enrich_with_comments(_task(42))
        assert inner.enrich_call_count == 1
        assert "fetched-from-inner" in result.comments
        assert "stale-comment" not in result.comments

    @pytest.mark.asyncio
    async def test_cache_serves_correct_payload(self, tmp_path: Path) -> None:
        decorator, _, _ = _build(tmp_path)
        first = await decorator.enrich_with_comments(_task(42))
        second = await decorator.enrich_with_comments(_task(42))
        assert second.id == first.id
        assert second.title == first.title
        assert second.comments == first.comments

    @pytest.mark.asyncio
    async def test_cache_miss_when_no_record(self, tmp_path: Path) -> None:
        """No prior record → falls through and records fresh."""
        decorator, inner, _ = _build(tmp_path)
        await decorator.enrich_with_comments(_task(42))
        assert inner.enrich_call_count == 1

    @pytest.mark.asyncio
    async def test_unparseable_cache_record_falls_through(self, tmp_path: Path) -> None:
        """A cached record with bad data must not crash; falls through
        to the inner store. Uses an integer for `tags` (which must be
        a list) — Pydantic rejects this and the decorator catches the
        ValidationError, returning to the inner store path.
        """
        decorator, inner, cache = _build(tmp_path)
        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.ENRICHED,
                payload={
                    "title": "x",
                    "body": "",
                    "tags": 12345,  # invalid for Task.tags (must be list)
                    "comments": [],
                },
            )
        )
        # Inner store gets the call regardless.
        await decorator.enrich_with_comments(_task(42))
        assert inner.enrich_call_count == 1

    @pytest.mark.asyncio
    async def test_independent_cache_per_issue(self, tmp_path: Path) -> None:
        decorator, inner, _ = _build(tmp_path)
        await decorator.enrich_with_comments(_task(1))
        await decorator.enrich_with_comments(_task(2))
        # Both issues hit the inner store independently.
        assert inner.enrich_call_count == 2
        # Repeating issue 1 serves from cache; issue 2 also.
        await decorator.enrich_with_comments(_task(1))
        await decorator.enrich_with_comments(_task(2))
        assert inner.enrich_call_count == 2

    @pytest.mark.asyncio
    async def test_record_failure_falls_through_returns_inner_result(
        self, tmp_path: Path
    ) -> None:
        """A cache write failure during enrich must not lose the inner
        result — the caller still gets the enriched task."""
        decorator, inner, cache = _build(tmp_path)

        def _boom(record: CacheRecord) -> None:
            del record
            raise RuntimeError("disk full")

        cache.record = _boom  # type: ignore[assignment]
        result = await decorator.enrich_with_comments(_task(42))
        assert "fetched-from-inner" in result.comments
        assert inner.enrich_call_count == 1


# ---------------------------------------------------------------------------
# TTL boundary
# ---------------------------------------------------------------------------


class TestTTLBoundary:
    @pytest.mark.asyncio
    async def test_record_just_inside_ttl_serves_cache(self, tmp_path: Path) -> None:
        decorator, inner, cache = _build(tmp_path, ttl=300)
        # Record from 100s ago — within 300s TTL.
        ts = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.ENRICHED,
                ts=ts,
                payload={
                    "title": "cached",
                    "body": "cached body",
                    "tags": [],
                    "comments": ["cached-comment"],
                },
            )
        )
        result = await decorator.enrich_with_comments(_task(42))
        assert inner.enrich_call_count == 0
        assert "cached-comment" in result.comments

    @pytest.mark.asyncio
    async def test_record_just_outside_ttl_falls_through(self, tmp_path: Path) -> None:
        decorator, inner, cache = _build(tmp_path, ttl=300)
        # Record from 400s ago — outside 300s TTL.
        ts = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.ENRICHED,
                ts=ts,
                payload={
                    "title": "cached",
                    "body": "",
                    "tags": [],
                    "comments": [],
                },
            )
        )
        await decorator.enrich_with_comments(_task(42))
        assert inner.enrich_call_count == 1

    @pytest.mark.asyncio
    async def test_malformed_timestamp_treated_as_stale(self, tmp_path: Path) -> None:
        decorator, inner, cache = _build(tmp_path)
        cache.record(
            CacheRecord(
                issue_id=42,
                kind=CacheRecordKind.ENRICHED,
                ts="not-a-timestamp",
                payload={
                    "title": "x",
                    "body": "",
                    "tags": [],
                    "comments": [],
                },
            )
        )
        await decorator.enrich_with_comments(_task(42))
        assert inner.enrich_call_count == 1
