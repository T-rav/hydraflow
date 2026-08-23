"""Regression test for issue #6766.

Bug: ``triage_phase.py`` and ``stale_issue_gc_loop.py`` have broad
``except Exception:`` handlers that do NOT call ``reraise_on_credit_or_bug``.
This silently swallows ``AuthenticationError``, ``CreditExhaustedError``,
and likely-bug exceptions (``TypeError``, ``KeyError``, ``AttributeError``,
``ValueError``, ``IndexError``, ``NotImplementedError``) instead of
propagating them.

Expected behaviour after fix:
  - The ``except Exception`` blocks in the anchored methods call
    ``reraise_on_credit_or_bug(exc)`` before the log statement so that
    fatal/bug exceptions propagate.

Anchored on the METHOD, not on a line number (#11664)
-----------------------------------------------------

The per-site assertion below used to filter whole-file handler line numbers to
a ±15-line window around a line captured when the issue was filed. Both
targets have since moved: ``_run_issue_reproductions`` was replaced by
``_flow_reproduce`` (now at a completely different line), and
``stale_issue_gc_loop``'s handlers drifted off their window too. The window
matched an EMPTY set, and ``assert not []`` passed VACUOUSLY — green while
asserting nothing.

The anchors are now enclosing method names, resolved through
``tests.regressions._handler_anchors.unguarded_handlers``, which RAISES if the
method disappears. A rotted anchor is now a red test with a "lost its anchor"
message, not a silent no-op. See ``_handler_anchors`` for the full rationale.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.regressions._handler_anchors import (
    RERAISE_GUARD,
    SRC,
    _except_exception_handlers,
    _handler_calls_reraise_guard,
    unguarded_handlers,
)

#: The function name that constitutes the required guard.
REQUIRED_GUARD = RERAISE_GUARD

#: (filename, enclosing method, short description) from the issue findings.
#:
#: The issue's findings table listed three line-anchored sites. Two of them
#: (``stale_issue_gc_loop.py:63`` — issue list fetch, and
#: ``stale_issue_gc_loop.py:106`` — per-issue processing) are both handlers
#: inside ``_do_work``, so they collapse to a single method anchor: scoping the
#: scan to the method already checks *every* broad handler it contains, which
#: is strictly stronger than two overlapping line windows.
#:
#: ``triage_phase.py:386`` named ``_run_issue_reproductions``, which no longer
#: exists; ``_flow_reproduce`` is its successor and owns the handler.
KNOWN_UNGUARDED_SITES: list[tuple[str, str, str]] = [
    ("triage_phase.py", "_flow_reproduce", "issue-reproduction broad except"),
    (
        "stale_issue_gc_loop.py",
        "_do_work",
        "issue list fetch + per-issue processing broad excepts",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unguarded_handlers_in_file(
    filepath: Path,
) -> list[tuple[int, ast.ExceptHandler]]:
    """Whole-file variant used by the file-wide sweep below.

    The per-site tests use the method-scoped
    :func:`~tests.regressions._handler_anchors.unguarded_handlers` instead —
    only this file-wide sweep wants every handler in the module.
    """
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
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
        [
            # This file-wide sweep is BROADER than the issue's findings table:
            # triage_phase.py still carries an unguarded handler outside
            # ``_flow_reproduce`` that #6766 never covered. Marked per-param
            # rather than on the whole test, so the stale_issue_gc_loop case
            # stays an honest green instead of a masked XPASS.
            pytest.param(
                "triage_phase.py",
                marks=pytest.mark.xfail(
                    reason="Residual unguarded ``except Exception`` in "
                    "triage_phase.py outside the #6766 findings table — tracked by #11668",
                    strict=False,
                ),
            ),
            "stale_issue_gc_loop.py",
        ],
        ids=lambda f: f.removesuffix(".py"),
    )
    def test_all_except_exception_blocks_have_reraise_guard(
        self, filename: str
    ) -> None:
        """Every ``except Exception`` in the target files must call
        ``reraise_on_credit_or_bug()`` so that programming errors and
        auth/credit failures are not silently consumed.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers_in_file(filepath)

        assert not unguarded, (
            f"{filename} has {len(unguarded)} ``except Exception`` block(s) "
            f"that do not call reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Auth/credit failures and likely-bug exceptions (TypeError, "
            f"KeyError, etc.) are silently swallowed — see issue #6766."
        )

    @pytest.mark.parametrize(
        ("filename", "method", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{m}" for f, m, _ in KNOWN_UNGUARDED_SITES],
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, method: str, desc: str
    ) -> None:
        """Every ``except Exception`` inside the anchored method from the
        issue's findings table must call ``reraise_on_credit_or_bug``.

        ``unguarded_handlers`` raises if *method* is gone, so this can never
        pass by matching nothing.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = [ln for ln, _ in unguarded_handlers(filepath, method)]

        assert not unguarded, (
            f"{filename}:{method}() ({desc}) — ``except Exception`` at line "
            f"{unguarded[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth failures and bug exceptions are silently swallowed "
            f"(issue #6766)."
        )
