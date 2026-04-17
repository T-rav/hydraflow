"""Regression test for issue #6728.

``TriagePhase._triage_single_traced()`` catches ``RuntimeError`` at line 239::

    try:
        result = await self._triage.evaluate(issue)
    except RuntimeError as exc:
        ...
        return 0

Both ``AuthenticationError`` and ``CreditExhaustedError`` inherit from
``RuntimeError``, so they are silently swallowed by this handler.  The
issue is left in the find queue and the orchestrator's credit-pause
mechanism is never triggered.

These tests will be RED until the handler re-raises
``AuthenticationError`` and ``CreditExhaustedError`` before the generic
``except RuntimeError`` block.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_triage_phase, supply_once

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ISSUE = TaskFactory.create(id=99, title="Regression issue", body="A" * 100)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTriageSingleTracedPropagatesFatalErrors:
    """AuthenticationError and CreditExhaustedError must propagate, not be caught."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6728 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates(self) -> None:
        """AuthenticationError must NOT be caught by the RuntimeError handler."""
        config = ConfigFactory.create()
        phase, _state, triage, _prs, store, _stop = make_triage_phase(config)

        triage.evaluate = AsyncMock(
            side_effect=AuthenticationError("bad credentials"),
        )
        store.get_triageable = supply_once([_ISSUE])

        with pytest.raises(AuthenticationError, match="bad credentials"):
            await phase._triage_single_traced(_ISSUE)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6728 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates(self) -> None:
        """CreditExhaustedError must NOT be caught by the RuntimeError handler."""
        config = ConfigFactory.create()
        phase, _state, triage, _prs, store, _stop = make_triage_phase(config)

        triage.evaluate = AsyncMock(
            side_effect=CreditExhaustedError("usage limit reached"),
        )
        store.get_triageable = supply_once([_ISSUE])

        with pytest.raises(CreditExhaustedError, match="usage limit reached"):
            await phase._triage_single_traced(_ISSUE)

    @pytest.mark.asyncio
    async def test_plain_runtime_error_still_caught(self) -> None:
        """Plain RuntimeError (infra) should still be caught and return 0."""
        config = ConfigFactory.create()
        phase, _state, triage, _prs, store, _stop = make_triage_phase(config)

        triage.evaluate = AsyncMock(
            side_effect=RuntimeError("empty LLM response"),
        )
        store.get_triageable = supply_once([_ISSUE])

        # This should NOT raise — the generic handler catches plain RuntimeError.
        result = await phase._triage_single_traced(_ISSUE)
        assert result == 0
