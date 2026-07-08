"""Integration scenario: Phase 2c counter migration into the convergence ledger.

Proves that when SandboxFailureFixerLoop runs _do_work() against a REAL
StateTracker, the per-PR attempt counter written by the loop flows through
the production accessor code (bump_sandbox_failure_fixer_attempts) into the
ConvergenceLedger — not a hand-set value.

This test drives the full _do_work() cycle with a real StateTracker and fake
port/runner objects to reach the bump at sandbox_failure_fixer_loop.py:166,
then reads back the ledger via get_convergence_ledger to confirm the counter
landed in stage_state["sandbox_fix"].attempts.

Rationale: Tasks 1-3 (committed on phase2c) migrated the per-issue counters
for auto_agent, sandbox_fix, and quality_fix stages out of bespoke StateData
dicts into the shared ConvergenceLedger. This test is the integration proof
that the live loop code (not just the mixin unit tests) uses the new path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
from state import StateTracker
from tests.helpers import make_bg_loop_deps

pytestmark = pytest.mark.scenario

PR_NUMBER = 42


def _make_loop_with_real_tracker(
    tmp_path,
    *,
    prs,
    runner,
):
    """Build a SandboxFailureFixerLoop wired to a real StateTracker.

    Replicates the _make_loop helper from tests/test_sandbox_failure_fixer_loop.py
    but substitutes the MagicMock state with a real StateTracker backed by a
    temp-dir state.json.  The loop is built with sandbox_failure_fixer_enabled=True
    so _do_work() skips the static-config gate and reaches the body.
    """
    tracker = StateTracker(state_file=tmp_path / "state.json")
    deps = make_bg_loop_deps(tmp_path, enabled=True, sandbox_failure_fixer_enabled=True)
    loop = SandboxFailureFixerLoop(
        config=deps.config,
        state=tracker,
        prs=prs,
        runner=runner,
        deps=deps.loop_deps,
        workspaces=None,
    )
    return loop, tracker


class TestSandboxFixCounterLandsInLedger:
    """Full _do_work() drive: bump reaches the real ledger via real loop code.

    The loop must never be hand-set; the ledger must be populated exclusively
    by the real accessor invoked inside SandboxFailureFixerLoop._do_work().
    """

    @pytest.mark.asyncio
    async def test_do_work_increments_sandbox_fix_stage_in_ledger(
        self, tmp_path
    ) -> None:
        """After one _do_work() cycle the ledger records sandbox_fix.attempts >= 1.

        Non-vacuity probe: the 'ledger is not None' assert carries a message
        that names the exact wiring regression so a future failure is
        immediately actionable.

        Observed ledger after the run (confirmed in task-4-report):
            stage_state={"sandbox_fix": StageRecord(attempts=1)}
        """
        pr_port = MagicMock()
        pr_port.list_prs_by_label = AsyncMock(
            return_value=[
                SimpleNamespace(number=PR_NUMBER, branch="rc/2026-06-01", labels=[]),
            ]
        )
        pr_port.add_pr_labels = AsyncMock()
        pr_port.remove_pr_label = AsyncMock()
        # Fetch helpers called by _build_prompt; return empty strings so the
        # fallback placeholder text is used — this keeps the test self-contained.
        pr_port.fetch_ci_failure_logs = AsyncMock(return_value="")
        pr_port.get_pr_recent_commit_diffs = AsyncMock(return_value="")

        runner = MagicMock()
        runner.run = AsyncMock(
            return_value=SimpleNamespace(crashed=False, output_text="ok")
        )

        loop, tracker = _make_loop_with_real_tracker(
            tmp_path, prs=pr_port, runner=runner
        )

        result = await loop._do_work()

        assert result is not None
        assert result.get("status") == "ok", (
            f"_do_work returned unexpected status: {result}"
        )

        # --- non-vacuity probe ---
        ledger = tracker.get_convergence_ledger(PR_NUMBER)
        assert ledger is not None, (
            "no ledger after _do_work — "
            "bump_sandbox_failure_fixer_attempts did not reach the ledger "
            "(Phase 2c counter migration wiring regression)"
        )

        # --- integration assertion: counter flowed through real code ---
        assert ledger.stage_state["sandbox_fix"].attempts >= 1, (
            f"expected sandbox_fix.attempts >= 1, got "
            f"{ledger.stage_state.get('sandbox_fix')}"
        )
