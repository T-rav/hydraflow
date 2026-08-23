"""Regression test for issue #6809.

Bug: ``diagnostic_loop.py`` has ``except Exception`` handlers that do NOT call
``reraise_on_credit_or_bug``:

- ``_run_fix`` (the ``runner.fix()`` crash handler reached from
  ``_process_issue``) silently absorbs ``AuthenticationError`` /
  ``CreditExhaustedError``, treating them as a soft fix failure and
  recording a ``DiagnosticAttempt``.
- ``_escalate_to_hitl`` catches ``post_comment`` failures without
  re-raising auth/credit errors.
- ``_escalate_to_hitl`` catches ``swap_pipeline_labels`` failures without
  re-raising auth/credit errors, leaving the issue stuck on the diagnose
  label.

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate up
    from all three sites so the orchestrator's credit-pause / auth-retry
    logic can handle them.

Anchored on the METHOD, not on a line number (#11664)
-----------------------------------------------------

The per-site assertion below used to filter whole-file handler line numbers to
a ±15-line window around ``diagnostic_loop.py:231`` / ``:309`` / ``:319``. All
three targets have since moved well past those windows (``_run_fix`` now starts
near 398, ``_escalate_to_hitl`` near 535), so each filter matched an EMPTY set
and ``assert not []`` passed VACUOUSLY — three green tests asserting nothing
about a defect that was never fixed. The non-strict ``xfail`` then reported
them as XPASS, which reads like good news and is not.

The anchors are now enclosing method names, resolved through
``tests.regressions._handler_anchors.unguarded_handlers``, which RAISES if the
method disappears. With honest anchors these assertions go RED, because the
underlying defect is real and still unfixed — which is why the ``xfail``
markers stay. See ``_handler_anchors`` for the full rationale.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from diagnostic_loop import DiagnosticLoop
from models import EscalationContext, Severity
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import make_bg_loop_deps
from tests.regressions._handler_anchors import (
    RERAISE_GUARD,
    SRC,
    _except_exception_handlers,
    _handler_calls_reraise_guard,
    unguarded_handlers,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

REQUIRED_GUARD = RERAISE_GUARD

#: (enclosing method, short description) from the issue findings.
#:
#: The two ``_escalate_to_hitl`` rows are kept separate so each finding stays
#: traceable, but the method-scoped scan checks every broad handler in the
#: method — so both rows assert the same (strictly stronger) property.
KNOWN_UNGUARDED_SITES: list[tuple[str, str]] = [
    ("_run_fix", "runner.fix() crash handler reached from _process_issue"),
    ("_escalate_to_hitl", "_escalate_to_hitl post_comment handler"),
    ("_escalate_to_hitl", "_escalate_to_hitl swap_pipeline_labels handler"),
]


def _make_loop(
    tmp_path: Path,
) -> tuple[DiagnosticLoop, MagicMock, MagicMock, MagicMock]:
    """Build a DiagnosticLoop with mocked collaborators.

    Returns ``(loop, runner, prs, state)``.
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    runner = MagicMock()
    runner.diagnose = AsyncMock(
        return_value=MagicMock(
            root_cause="test",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="plan",
            human_guidance="guidance",
            affected_files=["src/foo.py"],
        ),
    )
    runner.fix = AsyncMock(return_value=(True, "ok"))

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    state = MagicMock()
    state.get_escalation_context = MagicMock(
        return_value=EscalationContext(cause="ci_failure", origin_phase="review"),
    )
    state.get_diagnostic_attempts = MagicMock(return_value=[])
    state.add_diagnostic_attempt = MagicMock()
    state.set_diagnosis_severity = MagicMock()

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, runner, prs, state


# ---------------------------------------------------------------------------
# AST-based: verify source has the guard
# ---------------------------------------------------------------------------


def _unguarded_handlers_in_file(
    filepath: Path,
) -> list[tuple[int, ast.ExceptHandler]]:
    """Whole-file variant used by the file-wide sweep below.

    The per-site tests use the method-scoped
    :func:`~tests.regressions._handler_anchors.unguarded_handlers` instead.
    """
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(tree)
        if not _handler_calls_reraise_guard(h)
    ]


class TestDiagnosticLoopExceptBlocksHaveReraise:
    """AST check — every ``except Exception`` in diagnostic_loop.py must
    call ``reraise_on_credit_or_bug``.
    """

    def test_all_except_exception_blocks_have_reraise_guard(self) -> None:
        """Every ``except Exception`` in diagnostic_loop.py must call
        ``reraise_on_credit_or_bug()`` so that auth/credit failures
        and likely-bug exceptions are not silently consumed.
        """
        filepath = SRC / "diagnostic_loop.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers_in_file(filepath)

        assert not unguarded, (
            f"diagnostic_loop.py has {len(unguarded)} ``except Exception`` "
            f"block(s) that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures are silently swallowed — see issue #6809."
        )

    @pytest.mark.parametrize(
        ("method", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[
            f"diagnostic_loop.py:{m}:{i}"
            for i, (m, _) in enumerate(KNOWN_UNGUARDED_SITES)
        ],
    )
    def test_known_site_has_reraise_guard(self, method: str, desc: str) -> None:
        """Every ``except Exception`` inside the anchored method from the
        issue's findings table must call ``reraise_on_credit_or_bug``.

        ``unguarded_handlers`` raises if *method* is gone, so this can never
        pass by matching nothing.
        """
        filepath = SRC / "diagnostic_loop.py"
        assert filepath.exists()

        unguarded = [ln for ln, _ in unguarded_handlers(filepath, method)]

        assert not unguarded, (
            f"diagnostic_loop.py:{method}() ({desc}) — ``except Exception`` at "
            f"line {unguarded[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth/credit failures are silently swallowed (issue #6809)."
        )


# ---------------------------------------------------------------------------
# Behavioural: AuthenticationError / CreditExhaustedError must propagate
# ---------------------------------------------------------------------------


class TestRunnerFixAuthErrorPropagates:
    """Issue #6809, finding 1 — ``runner.fix()`` raising
    ``AuthenticationError`` must propagate, not be treated as a soft
    fix failure.
    """

    @pytest.mark.asyncio
    async def test_authentication_error_from_fix_propagates(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from runner.fix() must not be silently caught."""
        loop, runner, _prs, _state = _make_loop(tmp_path)
        runner.fix.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await loop._process_issue(42, "Title", "Body")

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_from_fix_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError from runner.fix() must not be silently caught."""
        loop, runner, _prs, _state = _make_loop(tmp_path)
        runner.fix.side_effect = CreditExhaustedError("credits gone")

        with pytest.raises(CreditExhaustedError):
            await loop._process_issue(42, "Title", "Body")


class TestEscalateToHitlPostCommentAuthErrorPropagates:
    """Issue #6809, finding 2 — ``post_comment`` in ``_escalate_to_hitl``
    raising a credit/auth error must propagate.
    """

    @pytest.mark.asyncio
    async def test_credit_error_from_post_comment_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError during HITL escalation comment must propagate."""
        loop, _runner, prs, state = _make_loop(tmp_path)
        # Force escalation path: no escalation context → immediate HITL
        state.get_escalation_context.return_value = None
        prs.post_comment.side_effect = CreditExhaustedError("credits gone")

        with pytest.raises(CreditExhaustedError):
            await loop._process_issue(42, "Title", "Body")

    @pytest.mark.asyncio
    async def test_auth_error_from_post_comment_propagates(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError during HITL escalation comment must propagate."""
        loop, _runner, prs, state = _make_loop(tmp_path)
        state.get_escalation_context.return_value = None
        prs.post_comment.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await loop._process_issue(42, "Title", "Body")


class TestEscalateToHitlLabelSwapAuthErrorPropagates:
    """Issue #6809, finding 3 — ``swap_pipeline_labels`` in
    ``_escalate_to_hitl`` raising a credit/auth error must propagate.
    """

    @pytest.mark.asyncio
    async def test_credit_error_from_label_swap_propagates(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError during HITL label swap must propagate."""
        loop, _runner, prs, state = _make_loop(tmp_path)
        state.get_escalation_context.return_value = None
        prs.swap_pipeline_labels.side_effect = CreditExhaustedError("credits gone")

        with pytest.raises(CreditExhaustedError):
            await loop._process_issue(42, "Title", "Body")

    @pytest.mark.asyncio
    async def test_auth_error_from_label_swap_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError during HITL label swap must propagate."""
        loop, _runner, prs, state = _make_loop(tmp_path)
        state.get_escalation_context.return_value = None
        prs.swap_pipeline_labels.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await loop._process_issue(42, "Title", "Body")
