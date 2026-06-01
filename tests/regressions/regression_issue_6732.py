"""Regression test for issue #6732.

``ADRCouncilReviewer.review_proposed_adrs()`` iterates proposed ADRs and
wraps each in ``except Exception: logger.exception(...)``.  This catches
``AuthenticationError`` and ``CreditExhaustedError`` (both subclass
``RuntimeError``) as if they were per-ADR errors, then continues to the
next item.  Auth failures and credit exhaustion should propagate to the
background loop supervisor so the orchestrator can pause or stop, not be
silently swallowed.

These tests will be RED until the handler re-raises
``AuthenticationError`` and ``CreditExhaustedError`` before the generic
``except Exception`` block (e.g. via ``reraise_on_credit_or_bug``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adr_reviewer import ADRCouncilReviewer
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reviewer(tmp_path: Path) -> ADRCouncilReviewer:
    """Build an ADRCouncilReviewer with test-friendly defaults."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    from events import EventBus

    bus = EventBus()
    prs = MagicMock()
    runner = MagicMock()
    return ADRCouncilReviewer(config, bus, prs, runner)


def _write_proposed_adr(adr_dir: Path, number: int = 99) -> Path:
    """Write a minimal proposed ADR so the review loop processes it."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{number:04d}-test-regression.md"
    path = adr_dir / filename
    content = f"""# ADR-{number:04d}: Test regression

**Status:** Proposed

## Context

Context for testing.

## Decision

We decided to test.

## Consequences

Testing consequences.
"""
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReviewProposedAdrsPropagatesFatalErrors:
    """AuthenticationError and CreditExhaustedError must propagate out of
    ``review_proposed_adrs``, not be caught by the per-ADR handler."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6732 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError must NOT be caught by except Exception."""
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_proposed_adr(adr_dir)

        reviewer._run_council_session = AsyncMock(
            side_effect=AuthenticationError("bad credentials"),
        )

        with pytest.raises(AuthenticationError, match="bad credentials"):
            await reviewer.review_proposed_adrs()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6732 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates(self, tmp_path: Path) -> None:
        """CreditExhaustedError must NOT be caught by except Exception."""
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_proposed_adr(adr_dir)

        reviewer._run_council_session = AsyncMock(
            side_effect=CreditExhaustedError("usage limit reached"),
        )

        with pytest.raises(CreditExhaustedError, match="usage limit reached"):
            await reviewer.review_proposed_adrs()

    @pytest.mark.asyncio
    async def test_plain_runtime_error_still_caught(self, tmp_path: Path) -> None:
        """Plain RuntimeError should still be caught — loop continues."""
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_proposed_adr(adr_dir)

        reviewer._run_council_session = AsyncMock(
            side_effect=RuntimeError("empty LLM response"),
        )

        # This should NOT raise — the generic handler catches plain RuntimeError.
        stats = await reviewer.review_proposed_adrs()
        assert stats["reviewed"] >= 0  # Loop completed without raising
