"""Regression test for issue #6604.

Bug: ``ShapePhase._check_for_response`` (called ``_get_or_wait_for_response``
in the issue) wraps ``self._state.get_shape_response(issue.id)`` in a bare
``except Exception: pass`` at shape_phase.py lines 465-474.  When the state
accessor raises (corrupt state, unexpected key type, etc.), the exception is
silently dropped and the method falls through to GitHub comment polling.

This means a valid WhatsApp-channel human response can be **lost** with zero
diagnostic signal — no log, no metric, no Sentry breadcrumb — and the
operator's input is silently ignored, leaving the issue stuck.

Expected behaviour after fix:
  - The ``except Exception`` block logs at ``warning`` level with the issue
    number and ``exc_info=True`` so the failure is observable.
  - The exception is still caught (non-fatal) — fallback to GitHub comment
    polling still runs.

These tests assert the CORRECT (post-fix) behaviour and are therefore RED
against the current buggy code.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import HydraFlowConfig
from models import Task
from shape_phase import ShapePhase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_phase() -> tuple[ShapePhase, MagicMock, MagicMock]:
    """Build a minimal ShapePhase with mocked deps for _check_for_response."""
    config = MagicMock(spec=HydraFlowConfig)
    state = MagicMock()
    store = MagicMock()
    store.enrich_with_comments = AsyncMock(
        return_value=MagicMock(comments=[]),
    )
    prs = MagicMock()
    event_bus = MagicMock()
    stop_event = asyncio.Event()

    phase = ShapePhase(
        config=config,
        state=state,
        store=store,
        prs=prs,
        event_bus=event_bus,
        stop_event=stop_event,
    )
    return phase, state, store


@pytest.fixture()
def issue() -> Task:
    return Task(
        id=42,
        title="Feature: better onboarding",
        body="Vague idea about onboarding",
        labels=["hydraflow-shape"],
    )


# ---------------------------------------------------------------------------
# Test: WhatsApp response loss is silent (the bug)
# ---------------------------------------------------------------------------


class TestWhatsAppResponseLossSilent:
    """Issue #6604: state error in WhatsApp response path must emit a warning."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6604 — fix not yet landed", strict=False)
    async def test_state_error_emits_warning_log(
        self,
        issue: Task,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When get_shape_response raises, a warning-level log must be emitted.

        Currently FAILS because the bare ``except Exception: pass`` produces
        no log output whatsoever.
        """
        phase, state, _store = _make_phase()

        state.get_shape_response.side_effect = RuntimeError(
            "corrupt state: shape_responses key has unexpected type"
        )

        with caplog.at_level(logging.WARNING, logger="hydraflow.shape_phase"):
            result = await phase._check_for_response(issue)

        # Fallback to GitHub still works (returns None since mock has no comments)
        assert result is None

        # The bug: no warning is logged — this assertion is RED
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "Expected a warning log when get_shape_response raises, but "
            "no warning was emitted — the exception was silently swallowed "
            "by `except Exception: pass` at shape_phase.py:473-474. "
            "A WhatsApp response could be lost with no diagnostic signal."
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6604 — fix not yet landed", strict=False)
    async def test_warning_log_includes_issue_id(
        self,
        issue: Task,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The warning must include the issue number for traceability."""
        phase, state, _store = _make_phase()

        state.get_shape_response.side_effect = KeyError("shape_responses")

        with caplog.at_level(logging.WARNING, logger="hydraflow.shape_phase"):
            await phase._check_for_response(issue)

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "No warning log emitted — bare `except Exception: pass` swallows "
            "the error silently (issue #6604)"
        )
        log_text = warning_records[0].getMessage()
        assert "42" in log_text, (
            f"Warning log should mention issue id 42, got: {log_text!r}"
        )
