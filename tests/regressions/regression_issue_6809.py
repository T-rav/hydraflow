"""Regression test for issue #6809.

Bug: ``diagnostic_loop.py`` has three ``except Exception`` handlers that
do NOT call ``reraise_on_credit_or_bug``:

- Line ~231: ``_run_stage2_fix`` / ``_process_issue`` catches
  ``runner.fix()`` crashes but silently absorbs
  ``AuthenticationError`` / ``CreditExhaustedError``, treating them
  as a soft fix failure and recording a ``DiagnosticAttempt``.
- Line ~309: ``_escalate_to_hitl`` catches ``post_comment`` failures
  without re-raising auth/credit errors.
- Line ~319: ``_escalate_to_hitl`` catches ``swap_pipeline_labels``
  failures without re-raising auth/credit errors, leaving the issue
  stuck on the diagnose label.

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate up
    from all three sites so the orchestrator's credit-pause / auth-retry
    logic can handle them.

These tests assert the *correct* behaviour and are RED against the
current (buggy) code.
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

SRC = Path(__file__).resolve().parent.parent.parent / "src"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

REQUIRED_GUARD = "reraise_on_credit_or_bug"

#: (approx_line, short description) from the issue findings.
KNOWN_UNGUARDED_SITES: list[tuple[int, str]] = [
    (231, "runner.fix() crash handler in _process_issue"),
    (309, "_escalate_to_hitl post_comment handler"),
    (319, "_escalate_to_hitl swap_pipeline_labels handler"),
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


def _except_exception_handlers(tree: ast.Module) -> list[ast.ExceptHandler]:
    """Return all ``except Exception`` handler nodes in *tree*."""
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_calls_reraise_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body calls ``reraise_on_credit_or_bug``."""
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == REQUIRED_GUARD:
            return True
        if isinstance(func, ast.Attribute) and func.attr == REQUIRED_GUARD:
            return True
    return False


def _unguarded_handlers(filepath: Path) -> list[tuple[int, ast.ExceptHandler]]:
    """Return ``(lineno, handler)`` pairs for every ``except Exception``
    that does **not** call ``reraise_on_credit_or_bug``.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(tree)
        if not _handler_calls_reraise_guard(h)
    ]


class TestDiagnosticLoopExceptBlocksHaveReraise:
    """AST check — every ``except Exception`` in diagnostic_loop.py must
    call ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
    def test_all_except_exception_blocks_have_reraise_guard(self) -> None:
        """Every ``except Exception`` in diagnostic_loop.py must call
        ``reraise_on_credit_or_bug()`` so that auth/credit failures
        and likely-bug exceptions are not silently consumed.
        """
        filepath = SRC / "diagnostic_loop.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        assert not unguarded, (
            f"diagnostic_loop.py has {len(unguarded)} ``except Exception`` "
            f"block(s) that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures are silently swallowed — see issue #6809."
        )

    @pytest.mark.parametrize(
        ("approx_line", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"diagnostic_loop.py:{ln}" for ln, _ in KNOWN_UNGUARDED_SITES],
    )
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
    def test_known_site_has_reraise_guard(self, approx_line: int, desc: str) -> None:
        """Each specific site from the issue's findings table must have
        ``reraise_on_credit_or_bug`` within +/-15 lines.
        """
        filepath = SRC / "diagnostic_loop.py"
        assert filepath.exists()

        unguarded = _unguarded_handlers(filepath)
        nearby = [ln for ln, _ in unguarded if abs(ln - approx_line) <= 15]

        assert not nearby, (
            f"diagnostic_loop.py:{approx_line} ({desc}) — ``except Exception`` "
            f"near line {nearby[0]} does not call reraise_on_credit_or_bug(). "
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
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
    async def test_authentication_error_from_fix_propagates(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError from runner.fix() must not be silently caught."""
        loop, runner, _prs, _state = _make_loop(tmp_path)
        runner.fix.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await loop._process_issue(42, "Title", "Body")

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
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
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
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
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
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
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
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
    @pytest.mark.xfail(reason="Regression for issue #6809 — fix not yet landed", strict=False)
    async def test_auth_error_from_label_swap_propagates(self, tmp_path: Path) -> None:
        """AuthenticationError during HITL label swap must propagate."""
        loop, _runner, prs, state = _make_loop(tmp_path)
        state.get_escalation_context.return_value = None
        prs.swap_pipeline_labels.side_effect = AuthenticationError("bad token")

        with pytest.raises(AuthenticationError):
            await loop._process_issue(42, "Title", "Body")
