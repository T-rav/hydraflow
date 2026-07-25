"""Regression for #10411/#10403: exhausted diagnose routes to the Auto-Agent
autofix stage, NOT the human-visible HITL queue.

Both HITL escalations that surfaced (#10411 ADR-drift, #10403 erosion) were
auto-resolvable multi-concern issues that exhausted their diagnostic attempts on
a too-big scope. The DiagnosticLoop escalated them to ``hydraflow-hitl`` (human
queue) AND the Auto-Agent path — so they transited the human queue for a poll
cycle before the Auto-Agent decomposed + resolved them. Attempts-exhausted is an
auto-resolvable "too-big / wrong-strategy" signal, not a human-judgment need, so
it now routes straight to the ``hydraflow-hitl-autofix`` claim stage (which the
Auto-Agent poll also covers), excluded from the human queue from the start;
``human-required`` remains the fallback if the Auto-Agent also exhausts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from models import AttemptRecord
from tests.test_diagnostic_loop import _make_loop


def _exhausted_attempts(max_attempts: int) -> list[AttemptRecord]:
    return [
        AttemptRecord(
            attempt_number=i + 1,
            changes_made=False,
            error_summary="failed",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        for i in range(max_attempts)
    ]


@pytest.mark.asyncio
async def test_exhausted_routes_to_autofix_stage_by_default(tmp_path: Path) -> None:
    """Flag on (default): exhausted → hydraflow-hitl-autofix, not the human queue."""
    loop, _runner, prs, state, _ = _make_loop(tmp_path)
    state.get_diagnostic_attempts.return_value = _exhausted_attempts(
        loop._config.max_diagnostic_attempts
    )

    outcome = await loop._process_issue(1, "Title", "Body")

    assert outcome == "escalated"
    prs.swap_pipeline_labels.assert_awaited_once_with(
        1, loop._config.hitl_autofix_label[0]
    )


@pytest.mark.asyncio
async def test_exhausted_stays_human_visible_when_flag_off(tmp_path: Path) -> None:
    """Flag off restores the pre-#10411 human-visible HITL escalation."""
    loop, _runner, prs, state, _ = _make_loop(tmp_path)
    object.__setattr__(loop._config, "diagnostic_exhausted_routes_autofix", False)
    state.get_diagnostic_attempts.return_value = _exhausted_attempts(
        loop._config.max_diagnostic_attempts
    )

    outcome = await loop._process_issue(1, "Title", "Body")

    assert outcome == "escalated"
    prs.swap_pipeline_labels.assert_awaited_once_with(1, loop._config.hitl_label[0])
