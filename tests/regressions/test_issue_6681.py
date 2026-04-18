"""Regression test for issue #6681.

``RetrospectiveCollector.record`` (line 118), ``WorkspaceGCLoop._do_work``
(line 73), ``_collect_orphaned_dirs`` (line 272),
``_collect_orphaned_branches`` (line 333), and ``_prune_stale_branch_entries``
(line 358) all catch ``except Exception`` without first calling
``reraise_on_credit_or_bug``.

A ``TypeError`` or ``AttributeError`` from a logic bug inside these paths is
silently logged as a warning and the loop continues, hiding code defects.

Each test injects a programming error (TypeError / AttributeError) into one
of the five call sites and asserts that it propagates.  All tests are RED
today because the broad handlers swallow these exceptions.

A green-guard test at the end verifies that a transient ``RuntimeError``
(e.g. subprocess failure) is still caught and logged — this must remain GREEN.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import ReviewVerdict
from retrospective import RetrospectiveCollector
from state import StateTracker
from tests.conftest import ReviewResultFactory
from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(tmp_path: Path) -> tuple[RetrospectiveCollector, StateTracker]:
    """Build a RetrospectiveCollector with mocked PRManager."""
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    state = StateTracker(config.state_file)
    mock_prs = AsyncMock()
    mock_prs.get_pr_diff_names = AsyncMock(return_value=[])
    mock_prs.create_issue = AsyncMock(return_value=0)
    collector = RetrospectiveCollector(config, state, mock_prs)
    return collector, state


def _make_gc_loop(
    tmp_path: Path,
    *,
    active_workspaces: dict[int, str] | None = None,
) -> tuple[WorkspaceGCLoop, StateTracker, asyncio.Event]:
    """Build a WorkspaceGCLoop with test-friendly defaults."""
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
        is_in_pipeline_cb=lambda n: False,
    )
    loop._issue_has_pipeline_label = AsyncMock(return_value=False)  # type: ignore[method-assign]
    return loop, state, deps.stop_event


# ---------------------------------------------------------------------------
# Test 1: TypeError in RetrospectiveCollector.record must propagate
# ---------------------------------------------------------------------------


class TestRetrospectiveRecordTypeError:
    """A TypeError during _collect is a programming bug and must propagate
    from ``record``.  The bare ``except Exception`` on line 118 currently
    swallows it."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6681 — fix not yet landed", strict=False)
    async def test_type_error_in_collect_propagates(self, tmp_path: Path) -> None:
        collector, _state = _make_collector(tmp_path)
        review = ReviewResultFactory.create(verdict=ReviewVerdict.APPROVE)

        with patch.object(
            collector,
            "_collect",
            new_callable=AsyncMock,
            side_effect=TypeError("'NoneType' object is not subscriptable"),
        ):
            # BUG: should raise TypeError, but the except Exception on
            # line 118 catches it and logs a warning
            with pytest.raises(TypeError, match="NoneType"):
                await collector.record(
                    issue_number=1, pr_number=10, review_result=review
                )


# ---------------------------------------------------------------------------
# Test 2: TypeError in WorkspaceGCLoop._do_work (Phase 1) must propagate
# ---------------------------------------------------------------------------


class TestGCDoWorkPhase1TypeError:
    """A TypeError during _is_safe_to_gc is a programming bug.  The bare
    ``except Exception`` on line 73 currently swallows it."""

    @pytest.mark.asyncio
    async def test_type_error_in_is_safe_to_gc_propagates(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_gc_loop(
            tmp_path,
            active_workspaces={42: "/fake/path"},
        )

        with patch.object(
            loop,
            "_is_safe_to_gc",
            new_callable=AsyncMock,
            side_effect=TypeError("unsupported operand type(s)"),
        ):
            # Stub out phase 2/3 so only phase 1 fires
            loop._collect_orphaned_dirs = AsyncMock(return_value=0)  # type: ignore[method-assign]
            loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
            loop._prune_stale_branch_entries = AsyncMock(return_value=0)  # type: ignore[method-assign]

            # BUG: should raise TypeError, but the except Exception on
            # line 73 catches it and logs a warning
            with pytest.raises(TypeError, match="unsupported operand"):
                await loop._do_work()


# ---------------------------------------------------------------------------
# Test 3: AttributeError in _collect_orphaned_dirs must propagate
# ---------------------------------------------------------------------------


class TestCollectOrphanedDirsAttributeError:
    """An AttributeError during _is_safe_to_gc inside _collect_orphaned_dirs
    is a programming bug.  The bare ``except Exception`` on line 272
    currently swallows it."""

    @pytest.mark.asyncio
    async def test_attribute_error_in_orphaned_dirs_propagates(
        self, tmp_path: Path
    ) -> None:
        loop, _state, _stop = _make_gc_loop(tmp_path)

        # Create an orphaned dir so the inner try block on line 264 fires
        ws_base = loop._config.workspace_base / loop._config.repo_slug
        ws_base.mkdir(parents=True, exist_ok=True)
        (ws_base / "issue-99").mkdir()

        with patch.object(
            loop,
            "_is_safe_to_gc",
            new_callable=AsyncMock,
            side_effect=AttributeError("'NoneType' object has no attribute 'get'"),
        ):
            # BUG: should raise AttributeError, but the except Exception
            # on line 272 catches it and logs a warning
            with pytest.raises(AttributeError, match="has no attribute"):
                await loop._collect_orphaned_dirs(tracked={}, budget=10)


# ---------------------------------------------------------------------------
# Test 4: TypeError in _collect_orphaned_branches must propagate
# ---------------------------------------------------------------------------


class TestCollectOrphanedBranchesTypeError:
    """A TypeError during branch processing is a programming bug.  The bare
    ``except Exception`` on line 333 currently swallows it."""

    @pytest.mark.asyncio
    async def test_type_error_in_orphaned_branches_propagates(
        self, tmp_path: Path
    ) -> None:
        loop, _state, _stop = _make_gc_loop(tmp_path)

        # Simulate git branch --list returning a matching branch
        with (
            patch(
                "workspace_gc_loop.run_subprocess",
                new_callable=AsyncMock,
                return_value="  agent/issue-123\n",
            ),
            patch.object(
                loop,
                "_is_in_pipeline",
                return_value=False,
            ),
            patch.object(
                loop,
                "_issue_has_pipeline_label",
                new_callable=AsyncMock,
                side_effect=TypeError("argument of type 'int' is not iterable"),
            ),
        ):
            # BUG: should raise TypeError, but the except Exception on
            # line 333 catches it and logs a warning
            with pytest.raises(TypeError, match="not iterable"):
                await loop._collect_orphaned_branches(budget=10)


# ---------------------------------------------------------------------------
# Test 5: AttributeError in _prune_stale_branch_entries must propagate
# ---------------------------------------------------------------------------


class TestPruneStaleBranchEntriesAttributeError:
    """An AttributeError during _is_safe_to_gc inside
    _prune_stale_branch_entries is a programming bug.  The bare
    ``except Exception`` on line 358 currently swallows it."""

    @pytest.mark.asyncio
    async def test_attribute_error_in_prune_propagates(self, tmp_path: Path) -> None:
        loop, state, _stop = _make_gc_loop(tmp_path)

        # Insert a stale branch entry with no matching workspace
        state.set_branch(42, "agent/issue-42")

        with patch.object(
            loop,
            "_is_safe_to_gc",
            new_callable=AsyncMock,
            side_effect=AttributeError("'NoneType' object has no attribute 'closed'"),
        ):
            # BUG: should raise AttributeError, but the except Exception
            # on line 358 catches it and logs a warning
            with pytest.raises(AttributeError, match="has no attribute"):
                await loop._prune_stale_branch_entries(budget=10)


# ---------------------------------------------------------------------------
# Test 6 (green guard): RuntimeError in GC phase 1 is transient — keep
# ---------------------------------------------------------------------------


class TestGCDoWorkTransientRuntimeError:
    """A RuntimeError from a subprocess failure is NOT a programming bug —
    it should be caught and logged.  This test is GREEN today and guards
    against over-correction when fixing the bug."""

    @pytest.mark.asyncio
    async def test_runtime_error_is_caught(self, tmp_path: Path) -> None:
        loop, _state, _stop = _make_gc_loop(
            tmp_path,
            active_workspaces={42: "/fake/path"},
        )

        with patch.object(
            loop,
            "_is_safe_to_gc",
            new_callable=AsyncMock,
            side_effect=RuntimeError("subprocess exited with code 128"),
        ):
            loop._collect_orphaned_dirs = AsyncMock(return_value=0)  # type: ignore[method-assign]
            loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
            loop._prune_stale_branch_entries = AsyncMock(return_value=0)  # type: ignore[method-assign]

            # RuntimeError should be caught and logged — NOT propagated
            result = await loop._do_work()
            assert result is not None
            assert result["errors"] == 1
