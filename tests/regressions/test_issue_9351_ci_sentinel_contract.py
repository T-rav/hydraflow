"""Contract: the CI wait sentinels are single-sourced so producer and consumer
can never drift again.

Issue #9351 — ``PRManager.wait_for_ci`` emitted ``"Timeout after 60s"`` while
``StagingPromotionLoop`` guarded on the literal ``"timed out"`` (which that
string does not contain), so every slow-CI tick force-closed a GREEN rc PR and
``main`` silently stopped advancing for ~3 days. The producer string and the
consumer's "is this incomplete, retry?" classification are now one shared symbol
(``src/ci_sentinels.py``). This pins that contract: the exact string the
producer emits MUST be classified as incomplete by the consumer's predicate.
"""

from __future__ import annotations

from ci_sentinels import CI_STOPPED, ci_timeout, is_ci_incomplete


def test_producer_timeout_string_is_classified_incomplete() -> None:
    """The EXACT summary wait_for_ci returns on timeout -> incomplete (retry)."""
    # ci_timeout() is what pr_manager.wait_for_ci returns; is_ci_incomplete() is
    # what StagingPromotionLoop guards on. They must agree by construction.
    assert ci_timeout(60) == "Timeout after 60s"
    assert is_ci_incomplete(ci_timeout(60)) is True
    assert is_ci_incomplete(ci_timeout(1800)) is True


def test_stopped_sentinel_is_classified_incomplete() -> None:
    """Kill-switch 'Stopped' is not a CI failure — leave the PR open."""
    assert CI_STOPPED == "Stopped"
    assert is_ci_incomplete(CI_STOPPED) is True


def test_real_failure_summary_is_not_incomplete() -> None:
    """A genuine CI failure must NOT be misclassified as incomplete."""
    assert is_ci_incomplete("ci failed: scenario tests") is False
    assert is_ci_incomplete("Sandbox (rc/* promotion PR full suite) failed") is False


def test_legacy_timed_out_phrasing_still_tolerated() -> None:
    """Defensive: any alternate 'timed out' phrasing is also treated as pending."""
    assert is_ci_incomplete("timed out waiting for checks") is True
