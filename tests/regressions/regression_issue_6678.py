"""Regression test for issue #6678.

``ShapePhase._check_for_response`` wraps the WhatsApp state lookup in a
bare ``except Exception: pass`` (line 473).  Programming errors —
``TypeError``, ``AttributeError``, ``KeyError`` — are silently swallowed
instead of being re-raised via ``reraise_on_credit_or_bug``.

This differs from #6475 (which focuses on the missing log line) in that
the acceptance criteria here require *re-raising* programming errors, not
just logging them.  A ``TypeError`` from corrupt state data should
propagate as a crash-worthy bug, not be silently absorbed.

Test 1: ``TypeError`` from ``get_shape_response`` must propagate (currently
swallowed by bare ``except Exception: pass``).

Test 2: ``AttributeError`` from ``clear_shape_response`` must propagate
(currently swallowed after the response is read but before it's returned).

Test 3: A transient ``RuntimeError`` should NOT propagate (it's not a
programming bug) — it should be caught.  This test is GREEN today and
guards against over-correction.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shape_phase import ShapePhase


def _make_shape_phase() -> tuple[ShapePhase, MagicMock]:
    """Build a ShapePhase with just enough mocks for _check_for_response."""
    config = MagicMock()
    state = MagicMock()
    store = MagicMock()
    store.enrich_with_comments = AsyncMock(
        return_value=MagicMock(comments=[]),
    )
    prs = MagicMock()
    event_bus = MagicMock()
    stop_event = MagicMock()

    phase = ShapePhase(
        config=config,
        state=state,
        store=store,
        prs=prs,
        event_bus=event_bus,
        stop_event=stop_event,
    )
    return phase, state


# ---------------------------------------------------------------------------
# Test 1: TypeError from get_shape_response must propagate
# ---------------------------------------------------------------------------


class TestTypeErrorPropagates:
    """A TypeError in get_shape_response is a programming bug and must not
    be silently swallowed."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6678 — fix not yet landed", strict=False)
    async def test_type_error_from_state_read_is_reraised(self) -> None:
        """If get_shape_response raises TypeError (e.g. state file contains
        an int where a dict was expected), _check_for_response must let it
        propagate so the bug is visible.

        Currently FAILS: the bare ``except Exception: pass`` catches it.
        """
        phase, state = _make_shape_phase()
        issue = MagicMock()
        issue.id = 42

        state.get_shape_response.side_effect = TypeError(
            "argument of type 'int' is not iterable"
        )

        with pytest.raises(TypeError, match="not iterable"):
            await phase._check_for_response(issue)


# ---------------------------------------------------------------------------
# Test 2: AttributeError from clear_shape_response must propagate
# ---------------------------------------------------------------------------


class TestAttributeErrorPropagates:
    """An AttributeError in clear_shape_response is a programming bug."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6678 — fix not yet landed", strict=False)
    async def test_attribute_error_from_state_clear_is_reraised(self) -> None:
        """If get_shape_response succeeds but clear_shape_response raises
        AttributeError (e.g. a missing method after refactor), the error
        must propagate — not be swallowed, losing the WhatsApp response.

        Currently FAILS: the bare ``except Exception: pass`` catches it.
        """
        phase, state = _make_shape_phase()
        issue = MagicMock()
        issue.id = 99

        # get_shape_response succeeds — there IS a WhatsApp reply
        state.get_shape_response.return_value = "Go with Direction B"
        # But clear_shape_response is broken
        state.clear_shape_response.side_effect = AttributeError(
            "'NoneType' object has no attribute 'pop'"
        )

        with pytest.raises(AttributeError, match="pop"):
            await phase._check_for_response(issue)


# ---------------------------------------------------------------------------
# Test 3: Transient RuntimeError should NOT propagate (guard rail)
# ---------------------------------------------------------------------------


class TestTransientErrorIsCaught:
    """A transient RuntimeError (lock contention, I/O hiccup) is not a
    programming bug and should be caught, not propagated.

    This test is GREEN today and ensures the fix doesn't over-correct by
    re-raising everything.
    """

    @pytest.mark.asyncio
    async def test_runtime_error_does_not_propagate(self) -> None:
        """RuntimeError from state read should be caught (fall through to
        GitHub path), not crash the shape loop."""
        phase, state = _make_shape_phase()
        issue = MagicMock()
        issue.id = 7

        state.get_shape_response.side_effect = RuntimeError(
            "Failed to acquire state lock"
        )

        # Should NOT raise — falls through to GitHub comments path
        result = await phase._check_for_response(issue)
        assert result is None, "Expected None when both sources return nothing"
