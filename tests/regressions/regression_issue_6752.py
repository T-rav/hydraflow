"""Regression test for issue #6752.

Bug: High-frequency ``except Exception`` blocks in production phase files
do not call ``capture_if_bug()`` or ``reraise_on_credit_or_bug()``.
This means programming errors (TypeError, KeyError, AttributeError, etc.)
are silently swallowed alongside transient failures, making bug triage
impossible from logs alone.

Expected behaviour after fix:
  - Every ``except Exception`` block in phase/diagnostic files either calls
    ``capture_if_bug(exc)`` (to report probable bugs to Sentry) or
    ``reraise_on_credit_or_bug(exc)`` (to re-raise fatal + bug exceptions).

Anchored on the METHOD, not on a line number (#11664)
-----------------------------------------------------

This file had the worst line-anchor rot in the repo. The per-site assertion
filtered whole-file handler line numbers to a ±15-line window around a line
captured when the issue was filed; TWO of the five anchors pointed PAST
end-of-file (``review_phase/_phase.py:861`` in a 799-line file,
``plan_phase.py:660`` in a module that no longer has a single
``except Exception``). Every window matched an EMPTY set, so
``assert not []`` passed VACUOUSLY, and the non-strict ``xfail`` reported the
result as XPASS — which reads like the bug got fixed. It did not.

The anchors are now enclosing method names, resolved through
``tests.regressions._handler_anchors.unguarded_handlers``, which RAISES if the
method disappears. With honest anchors these assertions go RED, because most of
the underlying defect is real and still unfixed — which is why the ``xfail``
markers stay. See ``_handler_anchors`` for the full rationale.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.regressions._handler_anchors import (  # noqa: E402
    BUG_CLASSIFICATION_CALLS,
    SRC,
    _except_exception_handlers,
    _handler_calls_any,
    unguarded_handlers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Files and enclosing METHODS from the issue's findings table. The original
#: table carried line numbers; see the module docstring for why those rotted.
#:
#: Original (line-anchored) -> current (method-anchored):
#:   review_phase/_phase.py:626 -> _post_review_transcript
#:   review_phase/_phase.py:861 -> _review_one_inner   (861 was PAST EOF)
#:   diagnostic_runner.py:145   -> diagnose
#:   diagnostic_loop.py:219     -> _run_fix
#:
#: DROPPED: ``plan_phase.py:660``. That anchor was past EOF *and* the module it
#: pointed at has since been split (#11547) into ``plan_phase_flow`` /
#: ``plan_phase_prepass`` / ``plan_phase_disposition`` and friends;
#: ``src/plan_phase.py`` today contains ZERO ``except Exception`` handlers, so
#: there is no site left for this row to anchor onto. Re-pointing it would mean
#: picking a method in a successor module that the #6752 findings table never
#: examined — a new claim, not a preserved one. Dropped rather than faked.
KNOWN_UNGUARDED_SITES: list[tuple[str, str]] = [
    ("review_phase/_phase.py", "_post_review_transcript"),
    ("review_phase/_phase.py", "_review_one_inner"),
    ("diagnostic_runner.py", "diagnose"),
    ("diagnostic_loop.py", "_run_fix"),
]


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
        if not _handler_calls_any(h, BUG_CLASSIFICATION_CALLS)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExceptBlocksBugClassification:
    """Issue #6752 — ``except Exception`` blocks must classify bugs."""

    @pytest.mark.parametrize(
        "filename",
        [
            # T36 — ``review_phase`` is now a package; the ``ReviewPhase``
            # class (which held the original anchored ``except Exception``
            # sites) lives in ``review_phase/_phase.py``.
            "review_phase/_phase.py",
            "diagnostic_runner.py",
            "diagnostic_loop.py",
            # #11547 split ``plan_phase`` into ``plan_phase_flow`` /
            # ``_prepass`` / ``_disposition`` / …; what remains here is
            # construction + queue draining and carries no broad handlers.
            "plan_phase.py",
            # ``implement_phase`` is likewise a package now. The old
            # ``implement_phase.py`` path stopped existing, so this param used
            # to die on ``assert filepath.exists()`` — a failure the non-strict
            # xfail swallowed, meaning the file went unswept entirely.
            "implement_phase/_phase.py",
        ],
        ids=lambda f: f.removesuffix(".py").replace("/", "_"),
    )
    @pytest.mark.xfail(
        reason="Issue #6752 is genuinely UNFIXED for several of these modules. "
        "Paths and anchors are current as of #11664, so a failure here is the "
        "real defect, no longer path/line rot. Tracked by #11668.",
        strict=False,
    )
    def test_all_except_exception_blocks_call_bug_classifier(
        self, filename: str
    ) -> None:
        """Every ``except Exception`` in production phase files must call
        ``capture_if_bug()`` or ``reraise_on_credit_or_bug()`` so that
        programming errors are not silently swallowed.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = _unguarded_handlers_in_file(filepath)

        assert not unguarded, (
            f"{filename} has {len(unguarded)} ``except Exception`` block(s) "
            f"that do not call capture_if_bug() or reraise_on_credit_or_bug().\n"
            f"Lines: {[lineno for lineno, _ in unguarded]}\n"
            f"Programming errors (TypeError, KeyError, etc.) in these blocks "
            f"will be silently swallowed — see issue #6752."
        )

    @pytest.mark.parametrize(
        ("filename", "method"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{m}" for f, m in KNOWN_UNGUARDED_SITES],
    )
    @pytest.mark.xfail(
        reason="Issue #6752 is genuinely UNFIXED for several of these methods. "
        "Anchors are method-based as of #11664, so a failure here is the real "
        "defect, no longer line-anchor rot. Tracked by #11668.",
        strict=False,
    )
    def test_known_site_has_bug_classifier(self, filename: str, method: str) -> None:
        """Every ``except Exception`` inside the anchored method from the
        issue's findings table must call a bug-classification helper.

        ``unguarded_handlers`` raises if *method* is gone, so this can never
        pass by matching nothing.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = [
            ln
            for ln, _ in unguarded_handlers(
                filepath, method, required_calls=BUG_CLASSIFICATION_CALLS
            )
        ]

        assert not unguarded, (
            f"{filename}:{method}() — ``except Exception`` at line "
            f"{unguarded[0]} does not call capture_if_bug() or "
            f"reraise_on_credit_or_bug().  Programming errors here are "
            f"silently swallowed (issue #6752)."
        )


# ---------------------------------------------------------------------------
# AST anchors for the ValidationError finding
# ---------------------------------------------------------------------------


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Map every node in *tree* to its parent node."""
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _model_validate_calls(tree: ast.AST) -> list[ast.Call]:
    """Return every ``<something>.model_validate(...)`` call in *tree*."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "model_validate"
    ]


def _enclosing_try(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.Try | None:
    """Return the nearest ``ast.Try`` whose *body* (not handlers) holds *node*.

    Walking up the real parent chain is what makes this anchor honest: the old
    version guessed at containment with a ±10 source-line text window, which
    stops matching the instant the ``try`` grows past ten lines.
    """
    child: ast.AST = node
    parent = parents.get(child)
    while parent is not None:
        if isinstance(parent, ast.Try) and any(stmt is child for stmt in parent.body):
            return parent
        child, parent = parent, parents.get(parent)
    return None


class TestDiagnosticRunnerValidationError:
    """``diagnostic_runner.diagnose`` — pydantic ValidationError (a ValueError
    subclass) is caught by ``except Exception`` and treated the same as a
    network failure.  The fix should catch ValidationError specifically
    with ``exc_info=True`` for actionable stack traces.
    """

    @pytest.mark.xfail(
        reason="Issue #6752 is genuinely UNFIXED — the try around "
        "DiagnosisResult.model_validate() still catches bare Exception. The "
        "anchor is AST-based as of #11664, so this failure is the real defect, "
        "no longer a missed proximity window. Tracked by #11668.",
        strict=False,
    )
    def test_validation_error_not_caught_specifically(self) -> None:
        """The except block around ``DiagnosisResult.model_validate()``
        must catch ``pydantic.ValidationError`` explicitly (with exc_info)
        rather than lumping it into the generic ``except Exception``.

        Anchored on the AST: find the ``model_validate`` call, take the ``try``
        that actually encloses it, and assert on *that* try's handlers. The
        previous version built a ±10-source-line proximity window and
        ``continue``d when ``model_validate`` was not inside it — with no
        assertion after the loop, a window miss meant the test ran ZERO
        assertions and passed. The terminal ``raise`` below closes that hole:
        finding nothing is now a failure, not a free green.
        """
        filepath = SRC / "diagnostic_runner.py"
        assert filepath.exists(), f"Source file not found: {filepath}"

        tree = ast.parse(filepath.read_text(), filename=str(filepath))
        parents = _parent_map(tree)

        checked_any = False
        for call in _model_validate_calls(tree):
            guard = _enclosing_try(call, parents)
            if guard is None:
                continue
            checked_any = True
            for handler in guard.handlers:
                assert not (
                    isinstance(handler.type, ast.Name)
                    and handler.type.id == "Exception"
                ), (
                    f"diagnostic_runner.py:{handler.lineno} — "
                    f"``except Exception`` around the model_validate() call at "
                    f"line {call.lineno} catches pydantic ValidationError "
                    f"(a ValueError subclass, i.e. a LIKELY_BUG_EXCEPTION) "
                    f"generically.  It should catch ValidationError explicitly "
                    f"with exc_info=True for actionable stack traces "
                    f"(issue #6752)."
                )

        if not checked_any:
            raise AssertionError(
                "diagnostic_runner.py no longer wraps a ``model_validate()`` "
                "call in a ``try`` — this test has lost its anchor and would "
                "otherwise assert nothing at all (the #11664 vacuity class). "
                "Re-point it at wherever the diagnosis payload is now parsed."
            )
