"""Regression #11609: the give-up self-solve handler owes the standing reraise.

``PlanRetrySelfSolver.solve`` promises in its own docstring that "a
credit-exhaustion / real-bug exception is re-raised via
``reraise_on_credit_or_bug`` so the loop's global pause/bug signal is not
silently eaten", and ``src/preflight/decompose_terminal.py`` honours that on
every one of the fallible ``gh`` reads behind it (``get_issue_state``,
``get_pr_title_and_body``, ``get_pr_mergeable``, ``get_pr_reviews``,
``get_pr_checks``, ``list_branch_commits``).

The sole caller — ``RouteBackCoordinator._self_solve_terminal`` — then caught
``Exception`` with no reraise, so the signal died one frame above the code
that carefully preserved it: ``CreditExhaustedError`` was logged as a warning
and converted into ``SelfSolveOutcome.EXHAUSTED`` → ``human-required``. The
loop burned attempt budget against an exhausted account, and a genuine
``TypeError``/``KeyError`` in the give-up path was filed as "self-solve
exhausted" rather than as the bug it was. This is the exact failure mode
CLAUDE.md's "subprocess-spawning runners MUST call
``reraise_on_credit_or_bug``" rule exists to prevent.

Pins: fatal infrastructure errors and likely-bug exceptions propagate out of
``route_back`` untouched, while ordinary/transient failures keep the
documented fall-back-to-human behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from unittest.mock import AsyncMock

from giveup_window import GiveUpClass, GiveUpTracker, GiveUpWindow, SelfSolveOutcome
from issue_cache import IssueCache
from mockworld.fakes.fake_route_back_counter import FakeRouteBackCounter
from route_back import RouteBackCoordinator, RouteBackOutcome
from state import StateTracker
from subprocess_util import AuthenticationError, CreditExhaustedError

_ISSUE = 11609
_MAX_RESTARTS = 2


class _RaisingSelfSolve:
    """A self-solver whose ``solve`` always raises — the shape the six new
    ``gh`` reads produce once ``reraise_on_credit_or_bug`` has done its job
    inside ``decompose_or_escalate``."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    async def solve(
        self, issue_id: int, *, from_stage: str, reason: str, issue_body: str = ""
    ) -> SelfSolveOutcome:
        del issue_id, from_stage, reason, issue_body
        self.calls += 1
        raise self.exc


def _coordinator(
    tmp_path: Path, self_solve: _RaisingSelfSolve
) -> tuple[RouteBackCoordinator, AsyncMock]:
    prs = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()
    coordinator = RouteBackCoordinator(
        cache=IssueCache(tmp_path / "cache", enabled=True),
        prs=prs,
        counter=FakeRouteBackCounter(),
        hitl_label="human-required",
        diagnose_label="hydraflow-diagnose",
        max_route_backs=2,
        give_up_tracker=GiveUpTracker(StateTracker(tmp_path / "state.json")),
        plan_retry_window=GiveUpWindow(
            GiveUpClass.PLAN_RETRY, max_restarts=_MAX_RESTARTS, window_seconds=3600
        ),
        self_solve=self_solve,
    )
    return coordinator, prs


async def _exhaust_window(coordinator: RouteBackCoordinator):
    """Route back until the give-up window is spent — the last call is the
    one that reaches ``_self_solve_terminal``."""
    result = None
    for _ in range(_MAX_RESTARTS):
        result = await coordinator.route_back(
            _ISSUE,
            from_stage="ready",
            to_stage="plan",
            reason="review v3 has critical findings",
            issue_body="the frobnicator never converges",
        )
    return result


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(CreditExhaustedError("credit balance too low"), id="credit"),
        pytest.param(AuthenticationError("invalid api key"), id="auth"),
        pytest.param(TypeError("NoneType is not subscriptable"), id="bug-type"),
        pytest.param(KeyError("headRefName"), id="bug-key"),
        pytest.param(ValueError("malformed commit dict"), id="bug-value"),
    ],
)
@pytest.mark.asyncio
async def test_fatal_and_bug_exceptions_propagate_out_of_route_back(
    tmp_path: Path, exc: BaseException
) -> None:
    """The signal reaches the loop instead of becoming human-required."""
    self_solve = _RaisingSelfSolve(exc)
    coordinator, prs = _coordinator(tmp_path, self_solve)

    with pytest.raises(type(exc)) as raised:
        await _exhaust_window(coordinator)

    # The very exception instance, not a re-wrapped one — the loop's global
    # pause keys off identity/type, and no human-required label was applied.
    assert (raised.value is exc, self_solve.calls) == (True, 1)
    assert prs.swap_pipeline_labels.await_args_list[-1].args[1] != "human-required"


@pytest.mark.asyncio
async def test_transient_failure_still_falls_back_to_human_required(
    tmp_path: Path,
) -> None:
    """A non-fatal, non-bug failure keeps the documented last-resort path —
    the reraise must not turn every self-solve hiccup into a loop crash."""
    self_solve = _RaisingSelfSolve(RuntimeError("gh: connection reset by peer"))
    coordinator, prs = _coordinator(tmp_path, self_solve)

    result = await _exhaust_window(coordinator)

    assert (result.outcome, self_solve.calls) == (RouteBackOutcome.ESCALATED, 1)
    assert prs.swap_pipeline_labels.await_args_list[-1].args[1] == "human-required"
