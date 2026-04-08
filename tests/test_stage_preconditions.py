"""Tests for stage_preconditions — pipeline state-machine gates (#6423).

Predicates are pure functions of the issue cache. Tests use real
``IssueCache`` instances against ``tmp_path`` to exercise the read path
end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_cache import IssueCache
from stage_preconditions import (
    STAGE_PRECONDITIONS,
    Stage,
    check_preconditions,
    has_clean_review,
    has_plan,
    has_reproduction_for_bug,
)


def _cache(tmp_path: Path) -> IssueCache:
    return IssueCache(tmp_path / "cache", enabled=True)


# ---------------------------------------------------------------------------
# has_plan
# ---------------------------------------------------------------------------


class TestHasPlan:
    def test_passes_when_plan_exists(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="a plan")
        assert has_plan(cache, 42).ok is True

    def test_fails_when_no_plan(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        result = has_plan(cache, 42)
        assert result.ok is False
        assert "no plan_stored" in result.reason

    def test_passes_after_multiple_plan_versions(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="v1")
        cache.record_plan_stored(42, plan_text="v2")
        assert has_plan(cache, 42).ok is True


# ---------------------------------------------------------------------------
# has_clean_review
# ---------------------------------------------------------------------------


class TestHasCleanReview:
    def test_passes_when_clean_review(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="looks good", has_critical=False)
        assert has_clean_review(cache, 42).ok is True

    def test_fails_when_no_review(self, tmp_path: Path) -> None:
        result = has_clean_review(_cache(tmp_path), 42)
        assert result.ok is False
        assert "no review_stored" in result.reason

    def test_fails_when_critical_findings(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_review_stored(
            42, review_text="missing edge cases", has_critical=True
        )
        result = has_clean_review(cache, 42)
        assert result.ok is False
        assert "critical findings" in result.reason

    def test_uses_latest_review(self, tmp_path: Path) -> None:
        """When v1 was critical and v2 is clean, the gate must pass."""
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="bad", has_critical=True)
        cache.record_review_stored(42, review_text="good", has_critical=False)
        assert has_clean_review(cache, 42).ok is True


# ---------------------------------------------------------------------------
# has_reproduction_for_bug
# ---------------------------------------------------------------------------


class TestHasReproductionForBug:
    def test_passes_when_no_classification_yet(self, tmp_path: Path) -> None:
        """Defers to upstream classifier — does not block when no record."""
        assert has_reproduction_for_bug(_cache(tmp_path), 42).ok is True

    def test_passes_when_not_a_bug(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
        )
        assert has_reproduction_for_bug(cache, 42).ok is True

    def test_fails_when_bug_without_repro(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
        )
        result = has_reproduction_for_bug(cache, 42)
        assert result.ok is False
        assert "no reproduction_stored" in result.reason

    def test_passes_when_bug_with_successful_repro(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
        )
        cache.record_reproduction_stored(
            42,
            outcome="success",
            test_path="tests/regressions/test_issue_42.py",
        )
        assert has_reproduction_for_bug(cache, 42).ok is True

    def test_fails_when_bug_repro_unable(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
        )
        cache.record_reproduction_stored(
            42,
            outcome="unable",
            details="lacks stack trace",
        )
        result = has_reproduction_for_bug(cache, 42)
        assert result.ok is False
        assert "escalate to HITL" in result.reason


# ---------------------------------------------------------------------------
# check_preconditions / STAGE_PRECONDITIONS
# ---------------------------------------------------------------------------


class TestCheckPreconditions:
    def test_known_stages_registered(self) -> None:
        # Stage.READY value as a fake stage substitute — but using the
        # documented enum, all stages should be in the registry.
        assert Stage.READY in STAGE_PRECONDITIONS
        assert Stage.REVIEW in STAGE_PRECONDITIONS

    def test_ready_passes_with_full_setup_for_feature(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="feature",
            complexity_score=3,
            complexity_rank="low",
        )
        cache.record_plan_stored(42, plan_text="full plan")
        cache.record_review_stored(42, review_text="LGTM", has_critical=False)
        result = check_preconditions(cache, 42, Stage.READY)
        assert result.ok is True

    def test_ready_fails_without_plan(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_review_stored(42, review_text="LGTM", has_critical=False)
        result = check_preconditions(cache, 42, Stage.READY)
        assert result.ok is False
        assert "no plan_stored" in result.reason

    def test_ready_short_circuits_on_first_failure(self, tmp_path: Path) -> None:
        """has_plan fails first; check_preconditions should not proceed
        to has_clean_review and concatenate reasons."""
        result = check_preconditions(_cache(tmp_path), 42, Stage.READY)
        assert result.ok is False
        # Only the first failure's reason is included.
        assert "no plan_stored" in result.reason
        assert "no review_stored" not in result.reason

    def test_ready_blocks_bug_without_reproduction(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_classification(
            42,
            issue_type="bug",
            complexity_score=5,
            complexity_rank="medium",
        )
        cache.record_plan_stored(42, plan_text="fix the bug")
        cache.record_review_stored(42, review_text="LGTM", has_critical=False)
        result = check_preconditions(cache, 42, Stage.READY)
        assert result.ok is False
        assert "no reproduction_stored" in result.reason

    def test_review_stage_requires_plan_and_review(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="plan")
        cache.record_review_stored(42, review_text="clean", has_critical=False)
        assert check_preconditions(cache, 42, Stage.REVIEW).ok is True

    def test_review_stage_blocks_when_review_has_critical(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="plan")
        cache.record_review_stored(42, review_text="bad", has_critical=True)
        result = check_preconditions(cache, 42, Stage.REVIEW)
        assert result.ok is False
        assert "critical findings" in result.reason


# ---------------------------------------------------------------------------
# PreconditionResult
# ---------------------------------------------------------------------------


class TestPreconditionResult:
    def test_truthy_when_ok(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path)
        cache.record_plan_stored(42, plan_text="x")
        assert bool(has_plan(cache, 42)) is True

    def test_falsy_when_not_ok(self, tmp_path: Path) -> None:
        assert bool(has_plan(_cache(tmp_path), 42)) is False
