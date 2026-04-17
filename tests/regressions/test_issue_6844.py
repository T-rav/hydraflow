"""Regression test for issue #6844.

``RepoRuntime.start()`` creates a background task via ``asyncio.create_task()``
but never attaches an ``add_done_callback`` for exception logging.  If the
orchestrator raises an unhandled exception during ``run()``, the exception sits
silently on the ``Task`` object and is only surfaced as "Task exception was
never retrieved" when GC collects it.

In multi-repo mode each repo gets a separate ``RepoRuntime``; a startup crash
in one repo is completely invisible to operators until (maybe) the GC warning
fires with no actionable context.

These tests will fail (RED) until ``RepoRuntime.start()`` adds a
``done_callback`` that logs orchestrator exceptions at ERROR level.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repo_runtime import RepoRuntime
from tests.helpers import ConfigFactory


def _make_crashing_orchestrator(error: Exception) -> MagicMock:
    """Return a mock orchestrator whose ``run()`` raises *error*."""
    orch = MagicMock()

    async def _run() -> None:
        raise error

    orch.run = _run
    orch.stop = AsyncMock()
    orch.running = False
    return orch


def _make_runtime(tmp_path, orchestrator: MagicMock) -> RepoRuntime:
    """Build a ``RepoRuntime`` with all heavy deps patched out."""
    config = ConfigFactory.create(repo="org/crashing-repo", repo_root=tmp_path)
    with (
        patch("repo_runtime.EventLog"),
        patch("repo_runtime.EventBus"),
        patch("repo_runtime.build_state_tracker"),
        patch("repo_runtime.HydraFlowOrchestrator", return_value=orchestrator),
    ):
        return RepoRuntime(config)


# ---------------------------------------------------------------------------
# Test 1 — Orchestrator crash in start() must be logged at ERROR level
# ---------------------------------------------------------------------------


class TestOrchestratorCrashLogged:
    """RepoRuntime must log orchestrator exceptions, not swallow them."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6844 — fix not yet landed", strict=False)
    async def test_orchestrator_exception_is_logged_at_error(
        self, tmp_path, caplog
    ) -> None:
        """When the orchestrator raises during ``run()``, the runtime must
        emit an ERROR log with the exception details.

        Fails until ``start()`` attaches a ``done_callback`` that logs
        the task exception.
        """
        error = RuntimeError("sanitize_repo blew up")
        orch = _make_crashing_orchestrator(error)
        runtime = _make_runtime(tmp_path, orch)

        with caplog.at_level(logging.ERROR, logger="hydraflow.repo_runtime"):
            await runtime.start()
            # Let the event loop process the task and fire callbacks.
            # A few ticks are needed: one to run the task, one for the
            # done-callback to fire.
            for _ in range(5):
                await asyncio.sleep(0)

        error_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and "sanitize_repo blew up" in r.message
        ]
        assert error_records, (
            "Orchestrator crash was silently swallowed — no ERROR log was "
            "emitted for the exception. (issue #6844: start() creates task "
            "with no done_callback)"
        )


# ---------------------------------------------------------------------------
# Test 2 — Exception details must include the repo slug for triage
# ---------------------------------------------------------------------------


class TestCrashLogIncludesSlug:
    """The error log must identify *which* repo crashed (critical in multi-repo)."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6844 — fix not yet landed", strict=False)
    async def test_error_log_contains_repo_slug(self, tmp_path, caplog) -> None:
        """Operators need to know which repo's orchestrator failed.

        Fails until the done-callback includes the runtime slug in the log
        message.
        """
        error = RuntimeError("label sync failed")
        orch = _make_crashing_orchestrator(error)
        runtime = _make_runtime(tmp_path, orch)

        with caplog.at_level(logging.ERROR, logger="hydraflow.repo_runtime"):
            await runtime.start()
            for _ in range(5):
                await asyncio.sleep(0)

        slug_error_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and "org-crashing-repo" in r.message
        ]
        assert slug_error_records, (
            "Orchestrator crash log does not include the repo slug — in "
            "multi-repo mode, operators cannot tell which repo failed. "
            "(issue #6844)"
        )
