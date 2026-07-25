"""Regression #10536: diagnose credit-exhaustion must pause, not scatter to HITL.

When the diagnose agent hits a usage/credit limit it returns **no structured
output**. ``DiagnosticRunner.diagnose`` used to fabricate a ``fixable=False``
diagnosis in that case (which the diagnostic loop then escalates to HITL) —
so every credit-starved issue was mislabeled un-fixable and pushed to the human
queue, AND the orchestrator's global credit-pause never fired (the credit
signal in the transcript never became a ``CreditExhaustedError``). It must
raise ``CreditExhaustedError`` so the signal propagates through
``reraise_on_credit_or_bug`` to ``_handle_credit_exhaustion`` and the whole
factory pauses until the limit resets.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from diagnostic_runner import DiagnosticRunner
from models import EscalationContext
from subprocess_util import CreditExhaustedError


@pytest.mark.asyncio
async def test_credit_exhaustion_transcript_raises_not_hitl(tmp_path: Path) -> None:
    runner = DiagnosticRunner.__new__(DiagnosticRunner)
    runner._config = MagicMock(repo_root=tmp_path)
    runner._mockworld_diagnosis = lambda: None  # type: ignore[method-assign]
    runner._build_command = lambda: ["fake-agent"]  # type: ignore[method-assign]
    # Weekly-limit hit: the transcript carries the credit line but NO JSON.
    runner._execute = AsyncMock(  # type: ignore[method-assign]
        return_value=(
            "You've hit your weekly limit · resets Jul 29 at 10pm (America/Denver)\n"
        )
    )

    ctx = EscalationContext(cause="test build failure", origin_phase="implement")

    with pytest.raises(CreditExhaustedError):
        await runner.diagnose(123, "Some issue", "issue body", ctx)


@pytest.mark.asyncio
async def test_non_credit_no_output_still_returns_fallback(tmp_path: Path) -> None:
    """A non-credit empty/garbage transcript keeps the existing fallback path
    (fixable=False) — the change is scoped to the credit-exhaustion signal."""
    runner = DiagnosticRunner.__new__(DiagnosticRunner)
    runner._config = MagicMock(repo_root=tmp_path)
    runner._mockworld_diagnosis = lambda: None  # type: ignore[method-assign]
    runner._build_command = lambda: ["fake-agent"]  # type: ignore[method-assign]
    runner._execute = AsyncMock(  # type: ignore[method-assign]
        return_value="some prose with no json and no limit signal"
    )

    ctx = EscalationContext(cause="test build failure", origin_phase="implement")

    result = await runner.diagnose(123, "Some issue", "issue body", ctx)
    assert result.fixable is False
