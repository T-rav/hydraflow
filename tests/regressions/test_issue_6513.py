"""Regression test for issue #6513.

Fire-and-forget ``asyncio.create_task()`` calls without stored references
or done-callbacks silently discard exceptions.  Python logs a
"Task exception was never retrieved" warning only in debug mode, meaning
production failures in these paths go completely unnoticed.

Two test strategies:

1. **AST scan** — parse the four affected source files and assert that every
   ``create_task()`` call either stores its return value or is not a bare
   expression statement.  Currently four call sites discard the task, so
   this test fails (RED).

2. **Runtime proof** — demonstrate that ``IssueStore._publish_queue_update_nowait``
   silently swallows a publish exception with no log output, proving the
   real-world consequence of the missing done-callback.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus, HydraFlowEvent

SRC = Path(__file__).resolve().parents[2] / "src"

# ---------------------------------------------------------------------------
# Affected files and the log-message substrings that identify each bare
# create_task() call (so the test survives minor line-number drift).
# ---------------------------------------------------------------------------
AFFECTED_FILES: list[Path] = [
    SRC / "orchestrator.py",
    SRC / "issue_store.py",
    SRC / "dashboard_routes" / "_hitl_routes.py",
    SRC / "server.py",
]


def _is_create_task_call(node: ast.AST) -> bool:
    """Return True if *node* is a call to ``*.create_task(...)``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    )


def _bare_create_task_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """Find ``create_task(...)`` calls whose return value is discarded.

    Catches two patterns:
    1. Bare expression statements: ``asyncio.create_task(coro)``
    2. Lambda bodies: ``lambda: asyncio.create_task(coro)`` — the lambda
       discards the Task reference just as effectively.

    Returns ``(lineno, source_snippet)`` for each violation.
    """
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # Pattern 1: bare expression statement
        if isinstance(node, ast.Expr) and _is_create_task_call(node.value):
            results.append((node.lineno, ast.dump(node.value)))
            continue

        # Pattern 2: lambda whose body is a create_task call
        if isinstance(node, ast.Lambda) and _is_create_task_call(node.body):
            results.append((node.lineno, ast.dump(node.body)))

    return results


# ---------------------------------------------------------------------------
# AST-based test: every create_task() must store its return value
# ---------------------------------------------------------------------------


class TestFireAndForgetTasksMustStoreReference:
    """Assert that all create_task() calls in affected files store the task.

    A bare ``asyncio.create_task(coro)`` expression discards the task
    reference, making it impossible to attach a done-callback or observe
    exceptions.  The fix is to assign the result:

        task = asyncio.create_task(coro)
        task.add_done_callback(...)

    This test scans the AST and fails if any bare create_task() calls exist.
    """

    @pytest.mark.parametrize(
        "src_file",
        AFFECTED_FILES,
        ids=[p.relative_to(SRC).as_posix() for p in AFFECTED_FILES],
    )
    def test_no_bare_create_task_calls(self, src_file: Path) -> None:
        source = src_file.read_text()
        tree = ast.parse(source, filename=str(src_file))
        bare_calls = _bare_create_task_calls(tree)

        relative = src_file.relative_to(SRC)
        assert bare_calls == [], (
            f"{relative} has {len(bare_calls)} fire-and-forget create_task() "
            f"call(s) with no stored reference (lines: "
            f"{', '.join(str(ln) for ln, _ in bare_calls)}). "
            f"Each create_task() must store the returned Task and attach a "
            f"done_callback to observe exceptions."
        )


# ---------------------------------------------------------------------------
# Runtime test: prove that _publish_queue_update_nowait silently loses errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_queue_update_silently_loses_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``_publish_queue_update_nowait`` fires a task that raises,
    no *application-level* log is emitted — proving the bug.

    asyncio's default exception handler may log a generic "Task exception
    was never retrieved" via the ``asyncio`` logger, but that is unreliable
    (depends on GC timing) and carries no application context.  A correct
    implementation attaches a done-callback that logs via the application
    logger (``hydraflow.issue_store``).

    This test:
    1. Creates an IssueStore with a bus whose ``publish`` always raises.
    2. Calls ``_publish_queue_update_nowait()`` which fires a task.
    3. Lets the event loop drain.
    4. Asserts that an *application* logger (not ``asyncio``) recorded the
       failure.

    Since no done-callback exists, the assertion fails (RED).
    """
    from issue_store import IssueStore

    bus = EventBus()

    async def exploding_publish(event: HydraFlowEvent) -> None:
        raise RuntimeError("publish kaboom — this should be logged")

    bus.publish = exploding_publish  # type: ignore[assignment]

    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])

    config = MagicMock()
    config.repo = "test-org/test-repo"

    store = IssueStore(config=config, fetcher=fetcher, event_bus=bus)

    with caplog.at_level(logging.ERROR):
        store._publish_queue_update_nowait()

        # Give the event loop a chance to run the fire-and-forget task
        await asyncio.sleep(0)
        # Extra tick for good measure
        await asyncio.sleep(0)

    # Filter to application-level loggers only — the ``asyncio`` logger's
    # generic "Task exception was never retrieved" doesn't count because
    # it depends on GC timing and carries no actionable context.
    app_records = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and not r.name.startswith("asyncio")
    ]
    assert any("publish" in r.message.lower() for r in app_records), (
        "Expected a log record about the failed publish task, but none was "
        "found. This proves the fire-and-forget task silently discarded the "
        "exception (issue #6513)."
    )
