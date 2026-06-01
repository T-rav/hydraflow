"""Regression test for issue #6773.

Several production code paths catch ``Exception`` and either do nothing
(``pass``) or suppress errors without any logging, making failures invisible.

The highest-severity finding is in ``shape_phase.py:_check_for_response``:
if ``get_shape_response`` raises *any* exception, the WhatsApp reply is
silently lost and the product conversation stalls with no diagnostic signal.

Other findings: ``base_runner.py``, ``orchestrator.py``, and
``exception_classify.py`` all use ``except Exception: pass`` where a narrower
catch (``ImportError``, ``AttributeError``) or at least a ``logger.debug``
would be appropriate.

These tests will fail (RED) until the bare ``except Exception: pass`` blocks
are either narrowed to the expected exception type or replaced with logging.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from models import Task
from shape_phase import ShapePhase

SRC = Path(__file__).resolve().parents[2] / "src"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_bare_except_exception_pass(source: str) -> list[int]:
    """Return line numbers of ``except Exception: pass`` blocks in *source*.

    A "bare" suppression block is an ExceptHandler that:
    - catches ``Exception`` (no ``as`` binding)
    - has a single-statement body of ``pass`` (no logging, no re-raise)
    """
    tree = ast.parse(source)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # Must catch exactly ``Exception``
        if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
            continue
        # Must have no ``as`` alias (i.e. not ``except Exception as e``)
        if node.name is not None:
            continue
        # Body must be a single ``pass`` statement
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            hits.append(node.lineno)
    return hits


# ---------------------------------------------------------------------------
# Test 1 — shape_phase.py must not silently swallow state errors (HIGH)
# ---------------------------------------------------------------------------


class TestShapePhaseNoSilentSwallow:
    """``_check_for_response`` must not use ``except Exception: pass``."""

    @pytest.mark.xfail(reason="Regression for issue #6773 — fix not yet landed", strict=False)
    def test_no_bare_except_exception_pass_in_shape_phase(self) -> None:
        """shape_phase.py should have zero ``except Exception: pass`` blocks.

        The block at line ~473 swallows errors from ``get_shape_response``,
        silently losing the human's WhatsApp reply.  Fails until the
        handler is either narrowed or replaced with a debug log.
        """
        source = (SRC / "shape_phase.py").read_text()
        hits = _find_bare_except_exception_pass(source)
        assert hits == [], (
            f"shape_phase.py has bare 'except Exception: pass' at line(s) {hits} — "
            "if get_shape_response raises, the WhatsApp reply is silently lost "
            "(issue #6773)"
        )


# ---------------------------------------------------------------------------
# Test 2 — behavioral: state error must propagate, not vanish (HIGH)
# ---------------------------------------------------------------------------


class TestShapeResponseErrorSurfaces:
    """When ``get_shape_response`` raises, the error must not be silently lost."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6773 — fix not yet landed", strict=False)
    async def test_state_error_is_not_swallowed(self) -> None:
        """If state.get_shape_response raises a RuntimeError (e.g. corrupt
        state file), ``_check_for_response`` currently swallows it and falls
        through to GitHub comments, silently losing the WhatsApp reply.

        A correct implementation should either:
        - Let the exception propagate, OR
        - Log at WARNING+ so operators can diagnose the issue

        This test fails until the ``except Exception: pass`` is fixed.
        """
        deps = {
            "config": MagicMock(),
            "state": MagicMock(),
            "store": MagicMock(),
            "prs": AsyncMock(),
            "event_bus": AsyncMock(),
            "stop_event": asyncio.Event(),
        }
        phase = ShapePhase(**deps)

        task = Task(
            id=42,
            title="Test issue",
            body="Test body",
            labels=["hydraflow-shape"],
        )

        # Simulate a corrupt/broken state that raises on access
        deps["state"].get_shape_response.side_effect = RuntimeError(
            "corrupt state file"
        )

        # Also set up store so if the code falls through to GitHub,
        # it returns None (no GitHub comments)
        enriched = task.model_copy(update={"comments": []})
        deps["store"].enrich_with_comments = AsyncMock(return_value=enriched)

        # The current buggy code swallows the RuntimeError and falls
        # through to GitHub comments, returning None.
        # A correct implementation should either raise or log.
        result = await phase._check_for_response(task)

        # If the state layer is broken, we should NOT silently return None
        # and pretend no response exists — that loses the human's reply.
        # This assertion fails on the buggy code because it returns None.
        assert (
            result is not None or deps["state"].get_shape_response.side_effect is None
        ), (
            "_check_for_response silently swallowed a RuntimeError from "
            "get_shape_response and returned None — the WhatsApp reply is lost "
            "with no diagnostic signal (issue #6773)"
        )


# ---------------------------------------------------------------------------
# Test 3 — base_runner.py Sentry block is too broad (MEDIUM)
# ---------------------------------------------------------------------------


class TestBaseRunnerSentryExceptBlock:
    """``base_runner.py`` should narrow its Sentry catch to ImportError."""

    @pytest.mark.xfail(reason="Regression for issue #6773 — fix not yet landed", strict=False)
    def test_no_bare_except_exception_pass_in_base_runner(self) -> None:
        """base_runner.py should have zero ``except Exception: pass`` blocks.

        The block at line ~161 is meant to handle "Sentry not installed" but
        catches *all* exceptions, masking real SDK errors.  Fails until the
        handler is narrowed to ``(ImportError, AttributeError)``.
        """
        source = (SRC / "base_runner.py").read_text()
        hits = _find_bare_except_exception_pass(source)
        assert hits == [], (
            f"base_runner.py has bare 'except Exception: pass' at line(s) {hits} — "
            "the Sentry try-block comment says 'Sentry not installed' but catches "
            "all exceptions, masking real SDK errors (issue #6773)"
        )


# ---------------------------------------------------------------------------
# Test 4 — orchestrator.py Sentry block is too broad (MEDIUM)
# ---------------------------------------------------------------------------


class TestOrchestratorSentryExceptBlock:
    """``orchestrator.py`` should narrow its Sentry catch to ImportError."""

    @pytest.mark.xfail(reason="Regression for issue #6773 — fix not yet landed", strict=False)
    def test_no_bare_except_exception_pass_in_orchestrator(self) -> None:
        """orchestrator.py should have zero ``except Exception: pass`` blocks.

        The block at line ~710 catches ``Exception`` where only
        ``(ImportError, AttributeError)`` is expected.
        """
        source = (SRC / "orchestrator.py").read_text()
        hits = _find_bare_except_exception_pass(source)
        assert hits == [], (
            f"orchestrator.py has bare 'except Exception: pass' at line(s) {hits} — "
            "Sentry is optional, but not all exceptions should be silenced "
            "(issue #6773)"
        )


# ---------------------------------------------------------------------------
# Test 5 — exception_classify.py should not silently swallow all errors (MEDIUM)
# ---------------------------------------------------------------------------


class TestExceptionClassifyNotSilent:
    """``capture_if_bug`` should not use ``except Exception: pass``."""

    @pytest.mark.xfail(reason="Regression for issue #6773 — fix not yet landed", strict=False)
    def test_no_bare_except_exception_pass_in_exception_classify(self) -> None:
        """exception_classify.py should have zero ``except Exception: pass``
        blocks.

        The block at line ~47 swallows all errors including real bugs in the
        ``capture_if_bug`` logic itself (e.g. TypeError if ``is_likely_bug``
        is passed a bad argument).  Fails until the handler is narrowed or
        adds at minimum a debug log.
        """
        source = (SRC / "exception_classify.py").read_text()
        hits = _find_bare_except_exception_pass(source)
        assert hits == [], (
            f"exception_classify.py has bare 'except Exception: pass' at "
            f"line(s) {hits} — the comment says 'never let Sentry errors crash' "
            "but this swallows ALL errors silently (issue #6773)"
        )
