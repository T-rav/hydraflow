"""Regression (#11820): stop must reap descendants across session boundaries.

Measured live 2026-08-31 — a factory build's real ancestry, three process
groups deep:

    pid=2867    ppid=2862    pgid=2862    make quality       <- orphans
    pid=2862    ppid=787     pgid=2862    /bin/zsh -c ...    <- agent Bash tool
    pid=787     ppid=71871   pgid=787     claude -p ...      <- agent CLI
    pid=71871   ppid=71868   pgid=71770   python -m server
    pid=71772   ppid=1       pgid=71770   make factory

The reaping machinery is already correct and already wired: `execution.py`
spawns with ``start_new_session=True`` and ``track()``, `_reap_process_group`
runs on timeout and cancel, and `orchestrator_lifecycle.stop()` calls
``reap_all_tracked_processes()`` (#9911). It still leaked an 11h53m
``pytest -n auto`` holding 2.4 GB.

It fails because **group reaping cannot cross a ``start_new_session``
boundary, and there are two of them**: the factory owns 71770, the agent CLI
starts 787, the agent's Bash tool starts 2862. ``killpg(-71770)`` reaches
nothing at or below 787, and even ``killpg(-787)`` misses 2862. Every layer
does the documented right thing; the leak lives in the gap between two of them.

The load-bearing constraint: **once a process reparents to PPID=1 its ancestry
is gone.** Nothing records that 2867 ever descended from the factory, so a walk
performed after the parents die can only guess by command name — the predicate
that matched the factory's own live triage agent in #11840. Hence descendants
must be collected BEFORE anything is signalled.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from process_group import descendant_pids

# The measured chain above, in `ps -eo pid,ppid` form.
_LIVE = """\
  PID  PPID
71772     1
71791 71772
71864 71791
71866 71864
71868 71866
71871 71868
  787 71871
 2862   787
 2867  2862
"""


def test_finds_descendants_across_two_session_boundaries() -> None:
    """The whole point: 787, 2862 and 2867 all trace back to the factory.

    Group-based reaping provably misses these — they are in pgids 787 and 2862
    while the factory owns 71770.
    """
    found = descendant_pids(_LIVE, 71772)
    assert {787, 2862, 2867} <= found


def test_returns_the_complete_chain_and_nothing_else() -> None:
    assert descendant_pids(_LIVE, 71772) == {
        71791,
        71864,
        71866,
        71868,
        71871,
        787,
        2862,
        2867,
    }


def test_root_itself_is_not_included() -> None:
    """The caller reaps its own children, not itself — including the root would
    make a stop path kill the process performing the stop."""
    assert 71772 not in descendant_pids(_LIVE, 71772)


def test_a_mid_chain_pid_yields_only_its_own_subtree() -> None:
    assert descendant_pids(_LIVE, 787) == {2862, 2867}


def test_unrelated_processes_are_never_included() -> None:
    """A sibling tree under init must not be swept in.

    This is the safety direction: over-reaping on a shared host kills an
    operator's work, which is worse than the leak being fixed.
    """
    ps = _LIVE + "  999     1\n 1000   999\n"
    found = descendant_pids(ps, 71772)
    assert 999 not in found
    assert 1000 not in found


def test_pid_with_no_children_is_empty() -> None:
    assert descendant_pids(_LIVE, 2867) == set()


def test_unknown_root_is_empty_not_everything() -> None:
    """Anti-vacuity in the dangerous direction: an unknown root must return
    nothing, never the whole table. A stop path that reaped everything on a
    missing pid would take down the host."""
    assert descendant_pids(_LIVE, 4242) == set()


def test_orphaned_rows_are_not_reachable() -> None:
    """After reparenting, ppid=1 severs the link — this pins WHY collection
    must happen before signalling. 2867 here is the same pid as in _LIVE, but
    reparented; it must no longer be attributed to the factory."""
    orphaned = "  PID  PPID\n71772     1\n 2867     1\n"
    assert descendant_pids(orphaned, 71772) == set()


def test_cycles_do_not_hang() -> None:
    """Malformed ps output must not spin the stop path forever."""
    cyclic = "  PID  PPID\n  10    11\n  11    10\n71772     1\n"
    assert descendant_pids(cyclic, 71772) == set()
    assert descendant_pids(cyclic, 10) == {11, 10}


def test_malformed_rows_are_skipped() -> None:
    assert descendant_pids("  PID  PPID\ngarbage\n\nx y\n71772 1\n", 71772) == set()


def test_empty_input_is_empty() -> None:
    assert descendant_pids("", 71772) == set()


# ---------------------------------------------------------------------------
# The WIRING. A pure function nobody calls fixes nothing — and the ordering
# between snapshot and reap is the whole design, so it needs its own assertion.
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from orchestrator import HydraFlowOrchestrator  # noqa: E402


def _orch(config) -> HydraFlowOrchestrator:
    orch = HydraFlowOrchestrator(config)
    orch._svc = MagicMock()
    orch._state = MagicMock()
    orch._loop_tasks = {}
    return orch


@pytest.mark.asyncio
async def test_stop_reaps_surviving_descendants(config) -> None:
    orch = _orch(config)
    with (
        patch.object(orch, "_build_interrupted_issues", AsyncMock(return_value=[])),
        patch("orchestrator_lifecycle.reap_all_tracked_processes", return_value=0),
        patch(
            "orchestrator_lifecycle._snapshot_descendants",
            AsyncMock(return_value={2862, 2867}),
        ),
        patch("orchestrator_lifecycle._reap_surviving_descendants") as reap_tree,
    ):
        await orch.stop()
    reap_tree.assert_called_once_with({2862, 2867})


@pytest.mark.asyncio
async def test_snapshot_happens_before_any_reaping(config) -> None:
    """The ordering IS the fix.

    Reaping first reparents the deep children to PID 1, which erases the
    ancestry the snapshot depends on — the tree walk would then find nothing
    and the check would silently do nothing forever. Asserting both calls
    happened cannot catch that; only their order can.
    """
    calls: list[str] = []
    with (
        patch.object(orch := _orch(config), "_build_interrupted_issues", AsyncMock(return_value=[])),
        patch(
            "orchestrator_lifecycle._snapshot_descendants",
            AsyncMock(side_effect=lambda: (calls.append("snapshot"), set())[1]),
        ),
        patch(
            "orchestrator_lifecycle.reap_all_tracked_processes",
            side_effect=lambda: (calls.append("reap_groups"), 0)[1],
        ),
        patch(
            "orchestrator_lifecycle._reap_surviving_descendants",
            side_effect=lambda pids: (calls.append("reap_tree"), 0)[1],
        ),
    ):
        await orch.stop()
    assert calls.index("snapshot") < calls.index("reap_groups") < calls.index("reap_tree")


@pytest.mark.asyncio
async def test_snapshot_degrades_to_empty_when_ps_fails() -> None:
    """A stop must never be blocked by an unusable `ps`.

    Routed through the reap-aware helper (a raw spawn orphans its own child
    on cancellation — the defect this function exists to close), so the seam
    patched here is that helper.
    """
    from orchestrator_lifecycle import _snapshot_descendants

    with patch(
        "orchestrator_lifecycle.run_subprocess_result",
        side_effect=OSError("boom"),
    ):
        assert await _snapshot_descendants() == set()


@pytest.mark.asyncio
async def test_snapshot_parses_real_ps_output_from_the_async_seam() -> None:
    """Positive path: proves the async spawn is actually wired to the parser.

    Without this the failure test above passes even if the function always
    returned an empty set.
    """
    import os

    from orchestrator_lifecycle import _snapshot_descendants

    me = os.getpid()
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = f"  PID  PPID\n{me} 1\n4242 {me}\n9001 4242\n"
    with patch(
        "orchestrator_lifecycle.run_subprocess_result", AsyncMock(return_value=fake)
    ):
        assert await _snapshot_descendants() == {4242, 9001}


def test_reap_survivors_skips_the_already_dead_and_counts_the_rest() -> None:
    from orchestrator_lifecycle import _reap_surviving_descendants

    with patch("orchestrator_lifecycle.os.kill") as kill:
        kill.side_effect = [None, ProcessLookupError, None]
        assert _reap_surviving_descendants({10, 20, 30}) == 2


def test_reap_survivors_signals_deepest_pid_first() -> None:
    """Descending order so a parent cannot fork a replacement mid-reap."""
    from orchestrator_lifecycle import _reap_surviving_descendants

    with patch("orchestrator_lifecycle.os.kill") as kill:
        _reap_surviving_descendants({10, 30, 20})
    assert [c.args[0] for c in kill.call_args_list] == [30, 20, 10]
