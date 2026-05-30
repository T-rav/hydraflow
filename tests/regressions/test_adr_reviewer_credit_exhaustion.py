"""Regression: ADRCouncilReviewer must surface credit-exhaustion (W2MS-04).

The ADR council orchestrator runs through ``run_simple``, which surfaces a
credit-out as a nonzero rc / "usage limit reached" blob *without* raising.
Previously the reviewer degraded that to ``return None`` (treated as an
unavailable orchestrator) and the per-ADR ``except Exception`` swallowed
anything that did raise — so a billing signal never reached the loop's
dedicated credit handler.

Expected behaviour after the fix:
  - ``_execute_orchestrator`` raises ``CreditExhaustedError`` when run_simple
    surfaces a credit-out blob.
  - The per-ADR ``except Exception`` in ``review_proposed_adrs`` re-raises
    that credit error instead of swallowing-and-continuing, so it
    propagates out of the public entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from subprocess_util import CreditExhaustedError
from tests.test_adr_reviewer import _make_reviewer, _write_adr


@pytest.mark.asyncio
async def test_execute_orchestrator_raises_on_credit_out_blob(tmp_path: Path) -> None:
    """A 'usage limit reached' blob from run_simple must raise, not return None."""
    reviewer = _make_reviewer(tmp_path)
    reviewer._runner.run_simple = AsyncMock(
        return_value=SimpleNamespace(
            returncode=1,
            stdout="Claude usage limit reached. resets 3am (America/Denver)",
            stderr="",
        )
    )

    with pytest.raises(CreditExhaustedError):
        await reviewer._execute_orchestrator("any prompt")


@pytest.mark.asyncio
async def test_review_proposed_adrs_propagates_credit_out(tmp_path: Path) -> None:
    """A credit-out during a per-ADR council session must propagate out of
    review_proposed_adrs rather than being swallowed-and-continued."""
    reviewer = _make_reviewer(tmp_path)
    adr_dir = tmp_path / "repo" / "docs" / "adr"
    _write_adr(adr_dir, 9001, "Sample Decision", "Proposed")

    # Pre-validation gate must pass so the council session actually runs.
    reviewer._pre_validator.validate = lambda *a, **k: SimpleNamespace(
        passed=True, issues=[]
    )

    reviewer._runner.run_simple = AsyncMock(
        return_value=SimpleNamespace(
            returncode=1,
            stdout="you've hit your limit",
            stderr="",
        )
    )

    with pytest.raises(CreditExhaustedError):
        await reviewer.review_proposed_adrs()
