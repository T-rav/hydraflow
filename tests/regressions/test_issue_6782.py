"""Regression tests for issue #6782.

Exception handling gaps in ``workspace_gc_loop`` and ``trace_rollup``:

1. **GC loop: no circuit-breaker for repeatedly failing issues.**
   ``workspace_gc_loop.py:73`` catches ``Exception`` and increments an
   ``errors`` counter, but the same broken issue is retried every cycle
   with no backoff or per-issue failure tracking.  A persistently broken
   worktree (e.g. corrupt git repo) produces log spam forever without
   self-healing.

2. **Orphaned-dir GC: same pattern** at ``workspace_gc_loop.py:272``.
   Orphaned dirs that persistently fail GC are retried every cycle.

3. **run_recorder list_runs: overly broad except + DEBUG logging.**
   ``run_recorder.py:150`` catches bare ``Exception`` and logs at DEBUG
   instead of WARNING.  A corrupt manifest is silently swallowed —
   operators get no visibility into data loss.

These tests will fail (RED) until:
- The GC loop tracks per-issue failures and skips after N consecutive
  failures.
- ``run_recorder.list_runs`` logs corrupt manifests at WARNING.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from run_recorder import RunRecorder  # noqa: E402
from state import StateTracker  # noqa: E402
from tests.helpers import ConfigFactory, make_bg_loop_deps  # noqa: E402
from workspace_gc_loop import WorkspaceGCLoop  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gc_loop(
    tmp_path: Path,
    *,
    active_workspaces: dict[int, str] | None = None,
) -> tuple[WorkspaceGCLoop, StateTracker]:
    """Build a WorkspaceGCLoop wired for testing repeated failures."""
    deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)
    state = StateTracker(deps.config.state_file)
    for num, path in (active_workspaces or {}).items():
        state.set_workspace(num, path)

    workspaces = MagicMock()
    workspaces.destroy = AsyncMock()
    prs = MagicMock()

    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _n: False,
    )
    loop._issue_has_pipeline_label = AsyncMock(return_value=False)
    loop._collect_orphaned_branches = AsyncMock(return_value=0)
    return loop, state


# ===========================================================================
# Test 1 — GC loop retries the same broken issue every cycle (no circuit-
#           breaker)
# ===========================================================================


class TestGCLoopNoCircuitBreaker:
    """The GC inner loop should stop retrying an issue after N consecutive
    failures, but currently it retries every cycle forever.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6782 — fix not yet landed", strict=False)
    async def test_same_issue_not_retried_after_consecutive_failures(
        self, tmp_path: Path
    ) -> None:
        """Run the GC cycle 4 times with ``destroy`` always raising for
        issue #99.  A correct implementation would skip #99 after (say) 3
        consecutive failures.  The current code retries every cycle.

        Fails until the GC loop tracks per-issue failures and skips after
        N consecutive failures.
        """
        loop, state = _make_gc_loop(tmp_path, active_workspaces={99: "/wt/issue-99"})

        # Issue is closed (eligible for GC) but destroy always fails.
        loop._get_issue_state = AsyncMock(return_value="closed")
        loop._workspaces.destroy = AsyncMock(
            side_effect=RuntimeError("corrupt git repo")
        )

        # Run 4 GC cycles.
        destroy_calls_per_cycle: list[int] = []
        for _ in range(4):
            # Re-add the workspace each cycle (simulates state still having it
            # because destroy failed and state.remove_workspace ran first).
            state.set_workspace(99, "/wt/issue-99")
            loop._workspaces.destroy.reset_mock()
            await loop._do_work()
            destroy_calls_per_cycle.append(loop._workspaces.destroy.await_count)

        # After several consecutive failures the GC should stop trying.
        # A correct circuit-breaker would have 0 calls in cycle 4.
        assert destroy_calls_per_cycle[3] == 0, (
            f"GC retried issue #99 on cycle 4 ({destroy_calls_per_cycle[3]} "
            f"destroy calls) despite 3 prior failures — no circuit-breaker "
            f"(issue #6782).  Per-cycle calls: {destroy_calls_per_cycle}"
        )


# ===========================================================================
# Test 2 — Orphaned dirs retried every cycle with no backoff
# ===========================================================================


class TestOrphanedDirNoCircuitBreaker:
    """Orphaned directory GC should stop retrying a dir that fails
    repeatedly, but currently retries every cycle.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6782 — fix not yet landed", strict=False)
    async def test_orphaned_dir_not_retried_after_consecutive_failures(
        self, tmp_path: Path
    ) -> None:
        """Create an orphaned ``issue-88`` dir on disk.  Make ``destroy``
        always raise.  After N failures the orphan should be skipped.

        Fails until ``_collect_orphaned_dirs`` has its own circuit-breaker.
        """
        loop, state = _make_gc_loop(tmp_path)

        # Create the orphaned directory on disk.
        wt_base = loop._config.workspace_base / loop._config.repo_slug
        orphan_dir = wt_base / "issue-88"
        orphan_dir.mkdir(parents=True)

        # Issue is closed (safe to GC) but destroy always fails.
        loop._get_issue_state = AsyncMock(return_value="closed")
        loop._workspaces.destroy = AsyncMock(
            side_effect=RuntimeError("permission denied")
        )

        destroy_calls_per_cycle: list[int] = []
        for _ in range(4):
            loop._workspaces.destroy.reset_mock()
            await loop._collect_orphaned_dirs({}, budget=20)
            destroy_calls_per_cycle.append(loop._workspaces.destroy.await_count)

        # After 3 failures, cycle 4 should skip.
        assert destroy_calls_per_cycle[3] == 0, (
            f"Orphaned dir issue-88 retried on cycle 4 "
            f"({destroy_calls_per_cycle[3]} destroy calls) despite 3 prior "
            f"failures — no circuit-breaker (issue #6782).  "
            f"Per-cycle calls: {destroy_calls_per_cycle}"
        )


# ===========================================================================
# Test 3 — run_recorder.list_runs logs corrupt manifest at DEBUG not WARNING
# ===========================================================================


class TestRunRecorderCorruptManifestLogLevel:
    """``RunRecorder.list_runs`` should log corrupt manifests at WARNING,
    not DEBUG — operators need visibility into data corruption.
    """

    @pytest.mark.xfail(reason="Regression for issue #6782 — fix not yet landed", strict=False)
    def test_corrupt_manifest_logged_at_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Write a corrupt manifest.json.  Call ``list_runs``.  Assert
        that the skip message is logged at WARNING level, not DEBUG.

        Fails until ``run_recorder.py:150`` changes from
        ``logger.debug(...)`` to ``logger.warning(...)``.
        """
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        recorder = RunRecorder(config)

        # Create a run directory with a corrupt manifest.
        runs_dir = tmp_path / "repo" / ".hydraflow" / "runs" / "42"
        corrupt_dir = runs_dir / "20260101T100000Z"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "manifest.json").write_text("NOT VALID JSON!!!")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.run_recorder"):
            runs = recorder.list_runs(42)

        assert runs == [], "Corrupt manifest should be skipped"

        # Find the log record about the corrupt manifest.
        skip_records = [
            r
            for r in caplog.records
            if r.name == "hydraflow.run_recorder"
            and ("corrupt" in r.message.lower() or "skip" in r.message.lower())
        ]
        assert skip_records, (
            "Expected a log message about skipping the corrupt manifest, "
            "but none was found"
        )

        # The bug: it logs at DEBUG instead of WARNING.
        for record in skip_records:
            assert record.levelno >= logging.WARNING, (
                f"Corrupt manifest logged at {record.levelname} instead of "
                f"WARNING — operators have no visibility into data corruption "
                f"(issue #6782, run_recorder.py:150)"
            )
