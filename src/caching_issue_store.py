"""CachingIssueStore — read-through cache decorator for IssueStorePort (#6422).

Wraps any ``IssueStorePort`` implementation and adds:

  1. **Fetch recording**: every queue read (``get_triageable``,
     ``get_plannable``, ``get_implementable``, ``get_reviewable``)
     records a ``fetch`` cache snapshot per issue. Downstream consumers
     and audit tooling can replay the cache to see what the data
     layer observed at each polling cycle.
  2. **Stale-bounded enrich lookup**: ``enrich_with_comments`` checks
     for a recent ``enriched`` cache record before delegating to the
     inner store. Records within the configured ``cache_ttl_seconds``
     window are returned directly, bypassing the GitHub round-trip.
  3. **Pass-through writes**: lifecycle methods (``mark_active``,
     ``enqueue_transition``, etc.) delegate to the inner store
     unchanged. The cache is read-through, not write-through —
     producers still talk to the real store.

This decorator is opt-in via :class:`HydraFlowConfig`. When the
``caching_issue_store_enabled`` flag is False, ``service_registry``
hands phases the raw ``IssueStore`` instance and the cache is not
involved at all — the decorator never wraps the inner store, so
there is zero performance or correctness impact for operators who
have not opted in.

The decorator does NOT change the cache schema. It uses the existing
``CacheRecordKind.FETCH`` for queue snapshots and a new ``ENRICHED``
kind for enriched-task snapshots.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from issue_cache import CacheRecord, CacheRecordKind, IssueCache
from models import Task

if TYPE_CHECKING:
    from ports import IssueStorePort

logger = logging.getLogger("hydraflow.caching_issue_store")

__all__ = ["CachingIssueStore"]


class CachingIssueStore:
    """Read-through cache decorator wrapping an ``IssueStorePort``.

    Implements ``IssueStorePort`` structurally so it can be used
    anywhere the protocol is consumed without changes to the
    consumer side.
    """

    def __init__(
        self,
        inner: IssueStorePort,
        *,
        cache: IssueCache,
        cache_ttl_seconds: int = 300,
    ) -> None:
        """Build the decorator.

        ``cache_ttl_seconds`` controls how long an enriched cache
        record is considered fresh. Defaults to 5 minutes — long
        enough to absorb the per-cycle GitHub poll, short enough that
        stale comment data does not poison downstream phases.
        """
        self._inner = inner
        self._cache = cache
        self._ttl = cache_ttl_seconds

    @property
    def cache(self) -> IssueCache:
        return self._cache

    @property
    def cache_ttl_seconds(self) -> int:
        return self._ttl

    # ------------------------------------------------------------------
    # Queue accessors — record fetches, return inner result
    # ------------------------------------------------------------------

    def get_triageable(self, max_count: int) -> list[Task]:
        result = self._inner.get_triageable(max_count)
        self._record_fetches(result, stage="triage")
        return result

    def get_plannable(self, max_count: int) -> list[Task]:
        result = self._inner.get_plannable(max_count)
        self._record_fetches(result, stage="plan")
        return result

    def get_implementable(self, max_count: int) -> list[Task]:
        result = self._inner.get_implementable(max_count)
        self._record_fetches(result, stage="implement")
        return result

    def get_reviewable(self, max_count: int) -> list[Task]:
        result = self._inner.get_reviewable(max_count)
        self._record_fetches(result, stage="review")
        return result

    def _record_fetches(self, tasks: list[Task], *, stage: str) -> None:
        """Record one ``fetch`` snapshot per task. Best-effort."""
        for task in tasks:
            try:
                self._cache.record_fetch(
                    task.id,
                    {
                        "stage": stage,
                        "title": task.title,
                        "tags": list(task.tags),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "CachingIssueStore: fetch record failed for #%d",
                    task.id,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Lifecycle pass-through (writes go to inner store unchanged)
    # ------------------------------------------------------------------

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self._inner.enqueue_transition(task, next_stage)

    def mark_active(self, issue_number: int, stage: str) -> None:
        self._inner.mark_active(issue_number, stage)

    def mark_complete(self, issue_number: int) -> None:
        self._inner.mark_complete(issue_number)

    def mark_merged(self, issue_number: int) -> None:
        self._inner.mark_merged(issue_number)

    def release_in_flight(self, issue_numbers: set[int]) -> None:
        self._inner.release_in_flight(issue_numbers)

    def is_active(self, issue_number: int) -> bool:
        return self._inner.is_active(issue_number)

    # ------------------------------------------------------------------
    # Enrichment — read-through with TTL
    # ------------------------------------------------------------------

    async def enrich_with_comments(self, task: Task) -> Task:
        """Return an enriched copy of *task*, using cached data when fresh.

        If the cache has an ``enriched`` record for this issue younger
        than ``cache_ttl_seconds``, return the cached enrichment
        without calling the inner store. Otherwise call the inner
        store, write the result to the cache, and return it.

        Cache misses (no record / stale / parse error) silently fall
        through to the inner store. The cache is best-effort.
        """
        cached = self._cached_enrichment(task.id)
        if cached is not None:
            logger.debug(
                "CachingIssueStore: serving cached enrichment for #%d",
                task.id,
            )
            return cached

        enriched = await self._inner.enrich_with_comments(task)
        try:
            self._cache.record(
                CacheRecord(
                    issue_id=task.id,
                    kind=CacheRecordKind.ENRICHED,
                    payload={
                        "title": enriched.title,
                        "body": enriched.body,
                        "tags": list(enriched.tags),
                        "comments": list(enriched.comments),
                    },
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "CachingIssueStore: enriched record write failed for #%d",
                task.id,
                exc_info=True,
            )
        return enriched

    def _cached_enrichment(self, issue_id: int) -> Task | None:
        """Return a fresh cached enriched Task for *issue_id*, or None.

        "Fresh" means an ``ENRICHED`` record exists with a timestamp
        within the last ``cache_ttl_seconds``. Stale records and
        records that fail to materialize as a Task return None so the
        caller falls through to the inner store.
        """
        record = self._cache.latest_record_of_kind(issue_id, CacheRecordKind.ENRICHED)
        if record is None:
            return None
        if not self._is_fresh(record):
            return None
        try:
            return Task(
                id=issue_id,
                title=str(record.payload.get("title", "")),
                body=str(record.payload.get("body", "")),
                tags=list(record.payload.get("tags", [])),
                comments=list(record.payload.get("comments", [])),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "CachingIssueStore: enriched record for #%d could not be "
                "materialized as Task — falling through to inner store",
                issue_id,
            )
            return None

    def _is_fresh(self, record: CacheRecord) -> bool:
        """Return True if *record*'s timestamp is within the TTL window."""
        try:
            from datetime import datetime  # noqa: PLC0415

            ts = datetime.fromisoformat(record.ts)
            now = datetime.now(ts.tzinfo)
            age = (now - ts).total_seconds()
            return age <= self._ttl
        except (ValueError, TypeError):
            return False
