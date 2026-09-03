"""The fatal signals `verify_proposals` raises must survive its callers.

#6680 made `verify_proposals` stop swallowing `INFRA_FATAL_EXCEPTIONS`. That
is only half the path: two of its three callers caught them straight back.

- `ReviewPhase._record_review_insight` wraps the call in
  `except (RuntimeError, OSError)`, and both `CreditExhaustedError` and
  `AuthenticationError` are `RuntimeError` subclasses — so the clause caught
  precisely the exceptions the fix exists to let out, and reported them as an
  ordinary "review insight recording failed".
- `HealthMonitorLoop._run_proposal_verification_cycle` wrapped it in a bare
  `except Exception` with a `logger.debug`. Both sibling methods in that same
  file already call `reraise_on_credit_or_bug` first, which is what made this
  one a gap rather than a decision.

The decoy in each case is an ordinary `RuntimeError`: without it these tests
would pass just as well against a caller that had stopped catching anything,
which is the obvious wrong way to make them green.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from subprocess_util import AuthenticationError, CreditExhaustedError

_FATALS = [CreditExhaustedError("budget exhausted"), AuthenticationError("bad creds")]
_IDS = [type(e).__name__ for e in _FATALS]


def _health_loop(tmp_path: Path):
    """A HealthMonitorLoop on the inline-fallback path (no queue wired)."""
    from health_monitor_loop import HealthMonitorLoop  # noqa: PLC0415
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

    bg = make_bg_loop_deps(tmp_path)
    loop = HealthMonitorLoop.__new__(HealthMonitorLoop)
    loop._config = bg.config
    loop._retrospective_queue = None  # forces the inline fallback
    return loop


@pytest.mark.parametrize("exc", _FATALS, ids=_IDS)
def test_health_monitor_lets_the_fatal_out(tmp_path: Path, exc: Exception) -> None:
    loop = _health_loop(tmp_path)
    with (
        patch("review_insights.verify_proposals", side_effect=exc),
        pytest.raises(type(exc)),
    ):
        loop._run_proposal_verification_cycle()


def test_health_monitor_still_swallows_an_ordinary_error(tmp_path: Path) -> None:
    """Decoy: a non-fatal failure must stay contained to a debug line."""
    loop = _health_loop(tmp_path)
    with patch(
        "review_insights.verify_proposals",
        side_effect=RuntimeError("ordinary verification failure"),
    ):
        loop._run_proposal_verification_cycle()  # must not raise


def _review_phase(tmp_path: Path):
    """A ReviewInsightsMixin instance wired far enough to reach the handler."""
    from review_phase._insights import ReviewInsightsMixin  # noqa: PLC0415

    phase = ReviewInsightsMixin.__new__(ReviewInsightsMixin)
    phase._config = MagicMock()
    phase._config.review_insight_window = 10
    phase._insights = MagicMock()
    phase._insights.load_recent.return_value = []
    phase._insights.get_proposed_categories.return_value = set()
    phase._update_bg_worker_status = None
    phase._transitioner = MagicMock()
    phase._insight_escalated_at = {}
    return phase


def _review_result():
    from models import ReviewResult, ReviewVerdict  # noqa: PLC0415

    return ReviewResult(
        issue_number=1,
        pr_number=2,
        verdict=ReviewVerdict.REQUEST_CHANGES,
        summary="needs work",
        fixes_made=False,
    )


@pytest.mark.parametrize("exc", _FATALS, ids=_IDS)
async def test_review_phase_lets_the_fatal_out(tmp_path: Path, exc: Exception) -> None:
    """`except (RuntimeError, OSError)` must not absorb a fatal subclass."""
    assert isinstance(exc, RuntimeError), (
        "this test only means something while the fatal types are "
        "RuntimeError subclasses — that is why the clause caught them"
    )
    phase = _review_phase(tmp_path)
    phase._insights.append_review.side_effect = exc

    with pytest.raises(type(exc)):
        await phase._record_review_insight(_review_result())


async def test_review_phase_still_absorbs_an_ordinary_error(tmp_path: Path) -> None:
    """Decoy: the clause must keep doing its job for real recording failures."""
    phase = _review_phase(tmp_path)
    phase._insights.append_review.side_effect = RuntimeError("disk gone")

    await phase._record_review_insight(_review_result())  # must not raise


def test_the_guard_is_actually_wired_at_both_call_sites() -> None:
    """Both callers must carry the reraise — not just behave right in a mock.

    The behavioural tests above patch `verify_proposals`, so they would also
    pass if a caller were deleted outright. This reads the source.
    """
    import inspect  # noqa: PLC0415

    from health_monitor_loop import _heavy  # noqa: PLC0415
    from review_phase import _insights  # noqa: PLC0415

    heavy_src = inspect.getsource(
        _heavy.HealthMonitorHeavyPassMixin._run_proposal_verification_cycle
    )
    assert "reraise_on_credit_or_bug" in heavy_src, (
        "_run_proposal_verification_cycle dropped its reraise"
    )
    # Scoped to the METHOD, not the module: the module keeps its
    # `from exception_classify import reraise_on_credit_or_bug` line whether
    # or not the call survives, so a module-wide substring check stays green
    # while the guard is gone.
    insights_src = inspect.getsource(
        _insights.ReviewInsightsMixin._record_review_insight
    )
    assert "reraise_on_credit_or_bug" in insights_src, (
        "_record_review_insight dropped its reraise"
    )
