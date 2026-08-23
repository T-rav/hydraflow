"""Shared, rot-proof anchors for the ``except Exception`` guard regressions.

Several regression tests (#6752, #6766, #6809, #6814, #6983, #6855) assert the
same structural property: a broad ``except Exception`` handler in production
code must call ``reraise_on_credit_or_bug()`` — or, for #6752, at least one of
``capture_if_bug()`` / ``reraise_on_credit_or_bug()`` — so that credit, auth,
and likely-bug exceptions are not silently swallowed.

Why this module exists — the line-anchor rot class (#11664)
-----------------------------------------------------------

Every one of those tests originally anchored its per-site assertion on a
hardcoded SOURCE LINE NUMBER captured when the issue was filed::

    unguarded = _unguarded_handlers(filepath)          # whole file
    nearby = [ln for ln, _ in unguarded if abs(ln - approx_line) <= 15]
    assert not nearby, ...

That shape is a trap. The moment the target code moves — a refactor, an
extraction, a module split — the ±15-line window stops covering the handler it
was written for. The filter then matches the EMPTY set, and ``assert not []``
passes **vacuously**. The test reports green while asserting nothing at all,
and it keeps doing so forever, because nothing about a green test invites
scrutiny. A sweep for #11664 found that *every* line-anchored site in this repo
had already rotted this way; two anchors in ``regression_issue_6752.py`` even
pointed past end-of-file.

The fix is to anchor on the enclosing **method name** instead of a line number,
and — crucially — to make a missing anchor LOUD:

* :func:`method_node` raises ``AssertionError`` when the named method is absent
  from the file, rather than returning an empty node or ``None``. A rotted
  anchor therefore fails RED with a message telling the next reader to
  re-point it, instead of quietly degrading into a no-op assertion.
* :func:`unguarded_handlers` scopes the handler scan to that method's subtree,
  so the assertion stays targeted (it does not go red on unrelated handlers
  elsewhere in a large module) without depending on line numbers.

That raise is the load-bearing part of this module. Anyone editing these
helpers must preserve it: a helper that returns "no handlers found" for a
method that does not exist re-creates the exact defect #11664 was filed for.

``regression_issue_6855.py`` carries its own private copy of these helpers on
purpose — it is the worked reference for the pattern and is kept
self-contained so the lesson survives even if this module is refactored.
"""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

#: Repo ``src/`` directory — the root every anchor below is relative to.
SRC = Path(__file__).resolve().parent.parent.parent / "src"

#: The guard that makes credit/auth/bug exceptions escape a broad handler.
RERAISE_GUARD = "reraise_on_credit_or_bug"

#: #6752 accepts either helper: ``capture_if_bug`` reports a probable bug to
#: Sentry, ``reraise_on_credit_or_bug`` re-raises it. Both count as "the
#: handler classified the exception rather than swallowing it blind."
BUG_CLASSIFICATION_CALLS: frozenset[str] = frozenset({"capture_if_bug", RERAISE_GUARD})


def _except_exception_handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    """Return every ``except Exception`` handler node inside *tree*.

    Matches exactly ``except Exception`` — not a tuple of types, not a bare
    ``except:``, not a narrower subclass. Those are the handlers broad enough
    to swallow a ``CreditExhaustedError`` by accident.
    """
    handlers: list[ast.ExceptHandler] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            handlers.append(node)
    return handlers


def _handler_calls_any(handler: ast.ExceptHandler, names: Collection[str]) -> bool:
    """Return True if *handler*'s body calls any function named in *names*.

    Accepts both the direct call (``capture_if_bug(exc)``) and the qualified
    one (``exception_classify.capture_if_bug(exc)``).
    """
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in names:
            return True
        if isinstance(func, ast.Attribute) and func.attr in names:
            return True
    return False


def _handler_calls_reraise_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler body calls ``reraise_on_credit_or_bug``."""
    return _handler_calls_any(handler, (RERAISE_GUARD,))


def method_node(filepath: Path, method: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Return the ``def``/``async def`` named *method* defined in *filepath*.

    Raises ``AssertionError`` when no such function exists. This is the
    anti-vacuity property of the whole module (see the module docstring): a
    caller that scans "the handlers inside method X" must fail loudly when X
    has been renamed, moved, or deleted — never silently scan an empty set and
    let ``assert not []`` report a green that proves nothing.
    """
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == method
        ):
            return node
    raise AssertionError(
        f"{filepath.name} no longer defines {method}() — the guard has lost its "
        "anchor and would pass vacuously. Re-point it at the method's new home."
    )


def unguarded_handlers(
    filepath: Path,
    method: str,
    *,
    required_calls: Collection[str] = (RERAISE_GUARD,),
) -> list[tuple[int, ast.ExceptHandler]]:
    """Return ``(lineno, handler)`` for every unguarded handler inside *method*.

    "Unguarded" means an ``except Exception`` whose body calls none of
    *required_calls*. Scoped to *method*'s AST subtree, so the assertion tracks
    the code it was written for even as the file grows or shrinks around it.

    Propagates :func:`method_node`'s ``AssertionError`` when the anchor method
    is gone — deliberately, so a rotted anchor is a red test, not an empty list.
    """
    return [
        (h.lineno, h)
        for h in _except_exception_handlers(method_node(filepath, method))
        if not _handler_calls_any(h, required_calls)
    ]
