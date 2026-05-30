"""Regression: PRUnsticker must surface credit-exhaustion (W2MS-03).

PRUnsticker drives real CLI subprocesses to fix stuck PRs. Two code
paths could previously swallow a credit-out:

  1. The reflection path (``_reflect_on_fix`` via ``run_simple``) surfaces
     credit-out as a nonzero rc / "usage limit reached" blob *without*
     raising, then degraded to ``return None`` — silently dropping the
     billing signal.
  2. The per-item driver excepts catch ``RuntimeError`` (and
     ``CreditExhaustedError`` is a ``RuntimeError`` subclass), folding a
     fatal billing signal into a recoverable "unstick failed" outcome.

Expected behaviour after the fix:
  - ``_reflect_on_fix`` raises ``CreditExhaustedError`` when run_simple
    surfaces a credit-out blob.
  - ``_persist_troubleshooting_pattern`` re-raises that credit error
    instead of burying it.
  - ``unstick`` re-raises a per-item ``CreditExhaustedError`` instead of
    counting it as ``stats["failed"]`` so the outer loop can pause.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from subprocess_util import CreditExhaustedError
from tests.test_pr_unsticker import _make_hitl_item, _make_unsticker


@pytest.mark.asyncio
async def test_reflect_on_fix_raises_on_credit_out_blob(tmp_path: Path) -> None:
    """A 'usage limit reached' blob from run_simple must raise, not return None."""
    store = MagicMock()
    store.load_patterns = MagicMock(return_value=[])
    h = _make_unsticker(tmp_path, troubleshooting_store=store)

    # run_simple surfaces credit-out as rc!=0 + a credit blob, without raising.
    h.agents._runner = SimpleNamespace(
        run_simple=AsyncMock(
            return_value=SimpleNamespace(
                returncode=1,
                stdout="Claude usage limit reached. resets 3am (America/Denver)",
                stderr="",
            )
        )
    )

    with pytest.raises(CreditExhaustedError):
        await h.unsticker._reflect_on_fix("transcript body", 42, "python")


@pytest.mark.asyncio
async def test_persist_pattern_propagates_credit_out(tmp_path: Path) -> None:
    """_persist_troubleshooting_pattern must re-raise the reflection credit error."""
    store = MagicMock()
    store.load_patterns = MagicMock(return_value=[])
    h = _make_unsticker(tmp_path, troubleshooting_store=store)

    h.agents._runner = SimpleNamespace(
        run_simple=AsyncMock(
            return_value=SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="you've hit your limit",
            )
        )
    )

    # No explicit TROUBLESHOOTING_PATTERN block in the transcript, so stage 2
    # (reflection) runs and must surface the credit-out.
    with pytest.raises(CreditExhaustedError):
        await h.unsticker._persist_troubleshooting_pattern(
            "a transcript with no explicit pattern block", 42, "python"
        )


@pytest.mark.asyncio
async def test_unstick_reraises_per_item_credit_exhaustion(tmp_path: Path) -> None:
    """A CreditExhaustedError from _process_item must propagate out of unstick,
    not be folded into stats['failed'] by the return_exceptions gather."""
    h = _make_unsticker(tmp_path, unstick_all_causes=True)

    async def _boom(_item):
        raise CreditExhaustedError("usage limit reached", resume_at=None)

    h.unsticker._process_item = _boom

    with pytest.raises(CreditExhaustedError, match="usage limit reached"):
        await h.unsticker.unstick([_make_hitl_item(42)])
