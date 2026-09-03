"""#12036: verification is a budget an operator sets, not a number agents imply.

Before this, the dispatcher budgeted AGENTS and nothing budgeted VERIFICATION.
Each agent shelled `make quality`, so N dispatched agents meant N concurrent
full suites on one host, and the only thing between them was an ADVISORY lock
they discovered after they were already running. Past ~4 concurrent suites this
repo produces environmental failures indistinguishable from real ones — which
cost more agent-hours to investigate than the suites themselves.

`max_concurrent_verifications` is that budget. It is deliberately separate from
`max_workers`: agents are dispatched against the board, verification is bounded
by what the box can serve.

The slot mechanism is exercised for real — subprocesses contending on actual
`flock`ed files — because a counting semaphore that does not actually count is
the failure this is meant to prevent.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from config import HydraFlowConfig  # noqa: E402

_LOCK = Path(__file__).parents[2] / "scripts" / "quality_host_lock.py"
_SLEEP = 2


def _run_three(slots: int, tmp_path: Path) -> float:
    """Start three 2s commands under *slots* slots; return the wall clock."""
    env = {
        **os.environ,
        "TMPDIR": str(tmp_path),
        "HYDRAFLOW_QUALITY_SLOTS": str(slots),
        "HYDRAFLOW_QUALITY_LOCK_TIMEOUT": "60",
    }
    start = time.monotonic()
    procs = [
        subprocess.Popen(  # noqa: S603
            [sys.executable, str(_LOCK), "--", "sleep", str(_SLEEP)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(3)
    ]
    for proc in procs:
        assert proc.wait(timeout=120) == 0
    return time.monotonic() - start


def test_the_budget_is_a_separate_dial_from_the_agent_budget() -> None:
    """The whole point: two numbers, set independently."""
    fields = HydraFlowConfig.model_fields

    assert "max_concurrent_verifications" in fields
    assert "max_workers" in fields
    assert fields["max_concurrent_verifications"].default == 1, (
        "the default must preserve today's single-suite behaviour"
    )


def test_one_slot_still_serialises(tmp_path: Path) -> None:
    """The default must behave exactly like the single mutex it replaces."""
    elapsed = _run_three(slots=1, tmp_path=tmp_path)

    assert elapsed >= _SLEEP * 2, (
        f"three 2s commands finished in {elapsed:.1f}s under ONE slot — they "
        f"ran concurrently, so the budget is not gating anything"
    )


def test_three_slots_let_three_run_at_once(tmp_path: Path) -> None:
    """The budget is a real count, not a boolean.

    Without this, a 'budget' that always serialised would pass the test above
    and deliver nothing.
    """
    elapsed = _run_three(slots=3, tmp_path=tmp_path)

    assert elapsed < _SLEEP * 2, (
        f"three 2s commands took {elapsed:.1f}s under THREE slots — they "
        f"serialised, so the count is being ignored"
    )


def test_slot_zero_keeps_the_original_lock_name(tmp_path: Path) -> None:
    """A rollout must not run two suites while hosts disagree about the build.

    If slot 0 were renamed, a host on the old single-lock build and one on this
    build would take different files and both run — the exact oversubscription
    #11219 fixed, reintroduced by the fix for #12036.
    """
    sys.path.insert(0, str(_LOCK.parent))
    import quality_host_lock as lock  # noqa: PLC0415

    assert lock._slot_paths(1) == [lock.LOCK_PATH]
    assert lock._slot_paths(4)[0] == lock.LOCK_PATH


def test_the_default_slot_count_is_one() -> None:
    """The module's own constant, asserted directly.

    An earlier version of this test recomputed the fallback in the test body
    and therefore tested its own arithmetic: setting `DEFAULT_SLOTS = 99` in
    the module left it green. Assert the constant, then exercise the path.
    """
    sys.path.insert(0, str(_LOCK.parent))
    import quality_host_lock as lock  # noqa: PLC0415

    assert lock.DEFAULT_SLOTS == 1


@pytest.mark.parametrize("bad", ["", "not-a-number", "-3"])
def test_a_malformed_budget_serialises_rather_than_running_free(
    bad: str, tmp_path: Path
) -> None:
    """A bad env value must never mean 'unlimited concurrent suites'.

    Driven through the real script rather than by recomputing its fallback:
    three commands are started with the malformed value and asserted to
    SERIALISE, which is only true if the fallback is 1.
    """
    env = {
        **os.environ,
        "TMPDIR": str(tmp_path),
        "HYDRAFLOW_QUALITY_SLOTS": bad,
        "HYDRAFLOW_QUALITY_LOCK_TIMEOUT": "60",
    }
    start = time.monotonic()
    procs = [
        subprocess.Popen(  # noqa: S603
            [sys.executable, str(_LOCK), "--", "sleep", str(_SLEEP)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(3)
    ]
    for proc in procs:
        assert proc.wait(timeout=120) == 0
    elapsed = time.monotonic() - start

    assert elapsed >= _SLEEP * 2, (
        f"three commands finished in {elapsed:.1f}s with SLOTS={bad!r} — a "
        f"malformed budget is running them concurrently"
    )
