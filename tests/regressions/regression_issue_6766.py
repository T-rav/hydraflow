"""Regression test for issue #6766.

Bug: ``triage_phase.py`` and ``stale_issue_gc_loop.py`` have broad
``except Exception:`` handlers that do NOT call ``reraise_on_credit_or_bug``.
This silently swallows ``AuthenticationError``, ``CreditExhaustedError``,
and likely-bug exceptions (``TypeError``, ``KeyError``, ``AttributeError``,
``ValueError``, ``IndexError``, ``NotImplementedError``) instead of
propagating them.

Expected behaviour after fix:
  - All three ``except Exception`` blocks call ``reraise_on_credit_or_bug(exc)``
    before the log statement so that fatal/bug exceptions propagate.

These tests assert the *correct* behaviour and are RED against the current
(buggy) code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"

#: The function name that constitutes the required guard.
REQUIRED_GUARD = "reraise_on_credit_or_bug"

#: (filename, approximate line, short description) from the issue findings.
KNOWN_UNGUARDED_SITES: list[tuple[str, int, str]] = [
    ("triage_phase.py", 386, "_run_issue_reproductions broad except"),
    ("stale_issue_gc_loop.py", 63, "issue list fetch broad except"),
    ("stale_issue_gc_loop.py", 106, "per-issue processing broad except"),
]


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExceptBlocksReraisGuard:
    """Issue #6766 — broad ``except Exception`` blocks must call
    ``reraise_on_credit_or_bug`` so that auth, credit, and bug exceptions
    propagate instead of being silently swallowed.
    """

    @pytest.mark.parametrize(
        "filename",
        ["triage_phase.py", "stale_issue_gc_loop.py"],
        ids=lambda f: f.removesuffix(".py"),
    )
    @pytest.mark.xfail(reason="Regression for issue #6766 — fix not yet landed", strict=False)
    def test_all_except_exception_blocks_have_reraise_guard(
        self, filename: str
    ) -> None:
        """Every ``except Exception`` in the target files must call
        ``reraise_on_credit_or_bug()`` so that programming errors and
        auth/credit failures are not silently consumed.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        assert not unguarded, (
            f"{filename} has {len(unguarded)} ``except Exception`` block(s) "
            f"that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures and likely-bug exceptions (TypeError, "
            f"KeyError, etc.) are silently swallowed — see issue #6766."
        )

    @pytest.mark.parametrize(
        ("filename", "approx_line", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{ln}" for f, ln, _ in KNOWN_UNGUARDED_SITES],
    )
    @pytest.mark.xfail(reason="Regression for issue #6766 — fix not yet landed", strict=False)
    def test_known_site_has_reraise_guard(
        self, filename: str, approx_line: int, desc: str
    ) -> None:
        """Each specific site from the issue's findings table must have
        ``reraise_on_credit_or_bug`` within ±15 lines of the reported
        location.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers(filepath)

        nearby = [lineno for lineno, _ in unguarded if abs(lineno - approx_line) <= 15]

        assert not nearby, (
            f"{filename}:{approx_line} ({desc}) — ``except Exception`` near "
            f"line {nearby[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth failures and bug exceptions are silently swallowed "
            f"(issue #6766)."
        )
