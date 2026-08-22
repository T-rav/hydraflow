"""Tests for PlanPhase ↔ PlanTouchpointExpander wiring (ADR-0063 W3b).

Renamed from ``test_plan_phase_touchpoint_expander_wiring.py`` when
``_write_plan_records`` / ``_maybe_expand_touchpoints`` moved to
``src/plan_phase_records.py`` (#11547).

The expander is invoked at one specific seam: inside
``PlanPhase._write_plan_records`` immediately after the FIRST
``PlanReviewer.review`` call returns blocking findings. The expander's
output is rendered into a context block, appended to the plan text, and
a SECOND ``PlanReviewer.review`` call runs against the enriched plan.
The cache record reflects the second review's verdict.

Pattern: ``make_plan_phase`` builds the phase with mocks; we inject a
stub ``PlanReviewer`` and a stub expander and drive
``_write_plan_records`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    PlanFinding,
    PlanFindingSeverity,
    PlanResult,
    PlanReview,
    Task,
)
from plan_touchpoint_expander import (
    ExpandedTouchpoints,
    Touchpoint,
)
from tests.helpers import make_plan_phase

# ---------------------------------------------------------------------------
# Stub PlanReviewer and PlanTouchpointExpander
# ---------------------------------------------------------------------------


class _StubReviewer:
    """Returns a scripted sequence of ``PlanReview`` objects per call."""

    def __init__(self, reviews: list[PlanReview]) -> None:
        self._reviews = list(reviews)
        self.calls: list[tuple[Task, PlanResult]] = []

    async def review(
        self,
        task: Task,
        plan_result: PlanResult,
        *,
        plan_version: int = 1,
        prior_summary: str | None = None,
        prior_findings: list | None = None,
    ) -> PlanReview:
        self.calls.append((task, plan_result))
        self.prior_contexts = getattr(self, "prior_contexts", [])
        self.prior_contexts.append((prior_summary, prior_findings))
        if not self._reviews:
            raise AssertionError("ran out of scripted reviews")
        return self._reviews.pop(0)


class _StubExpander:
    """Returns a scripted ``ExpandedTouchpoints`` and records calls."""

    def __init__(self, output: ExpandedTouchpoints) -> None:
        self.output = output
        self.calls: list[tuple[str, PlanReview]] = []

    async def expand_touchpoints(
        self,
        *,
        original_plan: str,
        reviewer_failure: PlanReview,
    ) -> ExpandedTouchpoints:
        self.calls.append((original_plan, reviewer_failure))
        return self.output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blocking_review(issue_id: int = 42) -> PlanReview:
    return PlanReview(
        issue_number=issue_id,
        plan_version=1,
        success=True,
        findings=[
            PlanFinding(
                severity=PlanFindingSeverity.HIGH,
                dimension="correctness",
                description="missed ADR-0021 state schema rule",
            ),
        ],
        summary="1 high finding",
    )


def _clean_review(issue_id: int = 42) -> PlanReview:
    return PlanReview(
        issue_number=issue_id,
        plan_version=1,
        success=True,
        findings=[],
        summary="clean",
    )


def _result() -> PlanResult:
    return PlanResult(
        issue_number=42,
        success=True,
        plan="step 1: do it",
        summary="done",
    )


def _task() -> Task:
    return Task(id=42, title="t", body="b")


# ---------------------------------------------------------------------------
# Wiring tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExpanderWiring:
    async def test_expander_invoked_on_first_blocking_review(self, config) -> None:
        """First review returns blocking findings → expander dispatched once."""
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        reviewer = _StubReviewer([_blocking_review(), _clean_review()])
        expander = _StubExpander(
            ExpandedTouchpoints(
                touchpoints=[
                    Touchpoint(
                        kind="adr",
                        ref="ADR-0021",
                        title="Persistence",
                        why="state schema",
                    ),
                ]
            )
        )
        phase._plan_reviewer = reviewer  # type: ignore[assignment]
        phase._touchpoint_expander = expander  # type: ignore[attr-defined]

        # Wire a minimal issue cache stub so _write_plan_records exercises
        # the review path.
        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 1
        cache.record_review_stored = lambda *_a, **_kw: None
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        assert len(expander.calls) == 1, "expander should run on first failure"
        # Second review's plan_result.plan must include the expanded
        # touchpoints block so the reviewer has the enriched context.
        assert len(reviewer.calls) == 2
        first_plan = reviewer.calls[0][1].plan
        second_plan = reviewer.calls[1][1].plan
        assert "ADR-0021" not in first_plan
        assert "ADR-0021" in second_plan
        assert "EXPANDED_TOUCHPOINTS" in second_plan

    async def test_expander_not_invoked_on_clean_first_review(self, config) -> None:
        """Clean first review → expander never called, single review run."""
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        reviewer = _StubReviewer([_clean_review()])
        expander = _StubExpander(ExpandedTouchpoints())
        phase._plan_reviewer = reviewer  # type: ignore[assignment]
        phase._touchpoint_expander = expander  # type: ignore[attr-defined]

        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 1
        cache.record_review_stored = lambda *_a, **_kw: None
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        assert expander.calls == []
        assert len(reviewer.calls) == 1

    async def test_expander_not_invoked_when_not_wired(self, config) -> None:
        """Backward-compat: no expander wired → single review, no error."""
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        reviewer = _StubReviewer([_blocking_review()])
        phase._plan_reviewer = reviewer  # type: ignore[assignment]
        # No touchpoint_expander assigned — should default to None.

        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 1
        cache.record_review_stored = lambda *_a, **_kw: None
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        assert len(reviewer.calls) == 1

    async def test_expander_skipped_on_second_failure(self, config) -> None:
        """Second review also blocking → no third try.

        Per ADR-0063 W3b: the expander runs on FIRST failure only. If the
        enriched re-review still fails, the issue routes back to plan via
        the existing READY-stage gate — we don't loop on expansion.
        """
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        reviewer = _StubReviewer([_blocking_review(), _blocking_review()])
        expander = _StubExpander(
            ExpandedTouchpoints(
                touchpoints=[Touchpoint(kind="adr", ref="ADR-0001", title="t", why="w")]
            )
        )
        phase._plan_reviewer = reviewer  # type: ignore[assignment]
        phase._touchpoint_expander = expander  # type: ignore[attr-defined]

        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 1
        cache.record_review_stored = lambda *_a, **_kw: None
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        # The expander runs exactly once, the reviewer exactly twice.
        assert len(expander.calls) == 1
        assert len(reviewer.calls) == 2

    async def test_empty_touchpoints_skips_second_review(self, config) -> None:
        """Expander returned no touchpoints → no re-review (nothing to enrich)."""
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        reviewer = _StubReviewer([_blocking_review()])
        expander = _StubExpander(ExpandedTouchpoints(touchpoints=[]))
        phase._plan_reviewer = reviewer  # type: ignore[assignment]
        phase._touchpoint_expander = expander  # type: ignore[attr-defined]

        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 1
        cache.record_review_stored = lambda *_a, **_kw: None
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        # Expander ran but no second review happened.
        assert len(expander.calls) == 1
        assert len(reviewer.calls) == 1

    async def test_cache_records_second_review_findings(self, config) -> None:
        """The review_stored record reflects the SECOND review's findings."""
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        reviewer = _StubReviewer([_blocking_review(), _clean_review()])
        expander = _StubExpander(
            ExpandedTouchpoints(
                touchpoints=[Touchpoint(kind="adr", ref="ADR-0001", title="t", why="w")]
            )
        )
        phase._plan_reviewer = reviewer  # type: ignore[assignment]
        phase._touchpoint_expander = expander  # type: ignore[attr-defined]

        recorded: dict = {}

        def _record(issue_id, *, review_text, has_blocking, findings):
            recorded["issue_id"] = issue_id
            recorded["has_blocking"] = has_blocking
            recorded["findings"] = findings
            recorded["review_text"] = review_text

        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 1
        cache.record_review_stored = _record
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        assert recorded["has_blocking"] is False
        assert recorded["findings"] == []


class TestPriorReviewContext:
    """#11298 delta re-review: the cache-backed prior-round reader."""

    def _phase(self):
        from plan_phase import PlanPhase

        phase = PlanPhase.__new__(PlanPhase)
        phase._issue_cache = None  # type: ignore[attr-defined]
        return phase

    def test_none_without_cache(self) -> None:
        phase = self._phase()
        assert phase._prior_review_context(1) == (None, None)

    def test_reads_summary_and_findings_from_record(self) -> None:
        from types import SimpleNamespace

        phase = self._phase()
        record = SimpleNamespace(
            payload={
                "review_text": "2 blocking findings",
                "has_blocking": True,
                "findings": [
                    {
                        "severity": "high",
                        "dimension": "correctness",
                        "description": "claims Foo exists",
                    },
                    {"not": "a finding"},  # malformed row skipped
                ],
            }
        )
        cache = SimpleNamespace(latest_review=lambda _id: record)
        phase._issue_cache = cache  # type: ignore[attr-defined]
        summary, findings = phase._prior_review_context(1)
        assert summary == "2 blocking findings"
        assert findings is not None and len(findings) == 1
        assert findings[0].dimension == "correctness"

    def test_malformed_cache_degrades_to_full_review(self) -> None:
        from types import SimpleNamespace

        phase = self._phase()
        # AsyncMock-style cache whose latest_review returns a coroutine-ish
        # object with no payload — the exact shape that broke round 1 of
        # this feature in the wiring tests.
        cache = SimpleNamespace(latest_review=lambda _id: object())
        phase._issue_cache = cache  # type: ignore[attr-defined]
        assert phase._prior_review_context(1) == (None, None)


@pytest.mark.asyncio
class TestPrimaryReviewThreading:
    """#11301 review find: the PRIMARY review call must receive the cached
    prior round — both halves were unit-tested but the glue was not."""

    async def test_primary_review_receives_cached_prior_round(self, config) -> None:
        from types import SimpleNamespace

        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)
        reviewer = _StubReviewer([_clean_review(303)])
        phase._plan_reviewer = reviewer  # type: ignore[assignment]

        record = SimpleNamespace(
            payload={
                "review_text": "1 blocking finding",
                "findings": [
                    {
                        "severity": "critical",
                        "dimension": "test_strategy",
                        "description": "no failing test named",
                    }
                ],
            }
        )
        cache = AsyncMock()
        cache.record_plan_stored = lambda *_a, **_kw: 2
        cache.record_review_stored = lambda *_a, **_kw: None
        cache.latest_review = lambda _id: record
        phase._issue_cache = cache  # type: ignore[assignment]

        await phase._write_plan_records(_task(), _result())

        assert reviewer.prior_contexts, "review() was never called"
        summary, findings = reviewer.prior_contexts[0]
        assert summary == "1 blocking finding"
        assert findings is not None and findings[0].dimension == "test_strategy"
