"""#12036: the lock's wait and the agent's timeout were equal, so queueing killed the run.

`BaseRunner._verify_quality` runs `make quality` with `timeout=quality_timeout`
(default 3600s). That invocation BEGINS by waiting on
`scripts/quality_host_lock.py`, whose wait bound defaults to 3600s and which,
on timeout, runs the suite anyway.

Two independent budgets, numerically equal, governing one invocation: an agent
that queues for the bound has its suite killed at the exact moment the lock
would have stopped waiting and let it run. It reports
``make quality timed out after 3600s`` — a failure caused entirely by
contention and indistinguishable at the call site from a genuine hang.

The lock cannot fix this alone; it has no idea what budget its caller holds. So
the caller passes one, and these tests pin the RELATIONSHIP rather than either
number — writing `1800` here would re-create the defect one level up, passing
while `quality_timeout` moved underneath it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from base_runner import BaseRunner  # noqa: E402

_LOCK_ENV = "HYDRAFLOW_QUALITY_LOCK_TIMEOUT"


class _Runner(BaseRunner):
    """Minimal concrete runner — `_quality_env` needs only `_config`."""

    def __init__(self, quality_timeout: int) -> None:  # noqa: D107
        self._config = type("C", (), {"quality_timeout": quality_timeout})()


@pytest.mark.parametrize("budget", [600, 3600, 7200])
def test_the_lock_may_never_consume_the_whole_budget(budget: int) -> None:
    """The defect itself: queueing must leave time for the suite to run."""
    wait = int(_Runner(budget)._quality_env()[_LOCK_ENV])

    assert wait < budget, (
        f"the host lock may wait {wait}s of a {budget}s budget — an agent that "
        f"queues for the bound has its suite killed the moment the lock would "
        f"have released it, and reports a timeout it did not cause"
    )


@pytest.mark.parametrize("budget", [600, 3600, 7200])
def test_the_suite_keeps_a_meaningful_share(budget: int) -> None:
    """A 1-second allowance would satisfy the test above and help nobody."""
    wait = int(_Runner(budget)._quality_env()[_LOCK_ENV])

    assert budget - wait >= budget // 4, (
        f"only {budget - wait}s of {budget}s left for the suite after queueing"
    )


def test_the_bound_scales_with_the_budget_rather_than_being_a_literal() -> None:
    """Pins the derivation: a changed `quality_timeout` moves the wait with it.

    Without this, someone could hardcode the current 1800 and the two numbers
    would drift apart again the first time the budget changed.
    """
    small = int(_Runner(600)._quality_env()[_LOCK_ENV])
    large = int(_Runner(7200)._quality_env()[_LOCK_ENV])

    assert large > small, "the lock wait is a literal, not derived from the budget"
    assert large == small * 12, "the wait is not proportional to the budget"


def test_the_environment_is_inherited_not_replaced() -> None:
    """`make quality` needs PATH and the rest; a bare dict would break the spawn."""
    env = _Runner(3600)._quality_env()

    assert "PATH" in env, "the quality spawn lost its inherited environment"
    assert env[_LOCK_ENV] != ""
