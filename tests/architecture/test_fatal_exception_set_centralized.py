"""Structural gate: the fatal-exception set is defined ONLY in ``exception_classify``.

Issue #11618: the concurrent worker pools re-stated "fatal" as a literal
``(AuthenticationError, CreditExhaustedError, MemoryError)`` tuple — a second
copy of a policy that ``exception_classify.reraise_on_credit_or_bug`` already
owned.  The two copies drifted: the pools' copy omitted
``LIKELY_BUG_EXCEPTIONS``, so a ``TypeError`` in a pooled worker was logged and
dropped while the same exception escalated off-pool.  Restating a policy is how
it drifts; this gate makes a third copy structurally impossible.

Any exception-set expression naming ``CreditExhaustedError`` must come from
``exception_classify`` (``INFRA_FATAL_EXCEPTIONS`` / ``FATAL_EXCEPTIONS`` /
``is_fatal``), not from a literal enumerated in place.  The detector covers the
shapes a restatement actually takes:

* an ``except`` clause, ``isinstance`` operand, or assigned constant holding a
  tuple / list / set literal, or a ``A | B`` union;
* the same written through an import alias (``CreditExhaustedError as CE``) or
  a module attribute (``subprocess_util.CreditExhaustedError``);
* the tuple split across sibling bare-``raise`` ``except`` clauses on one
  ``try`` — the same policy, one type per clause.

``_GRANDFATHERED`` freezes the pre-existing re-raise guards.  Those sit *ahead*
of a handler that already classifies likely bugs, so they do not swallow
anything — but they are the same restatement shape, so the list may shrink and
must never grow.  Static AST scan only; never imports the modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_OWNER = "exception_classify.py"

#: The type whose presence marks an expression as a fatal-set restatement.
_NEEDLE = "CreditExhaustedError"

#: Modules that still enumerate a fatal set in place, as of #11618.  Every one
#: re-raises ahead of a handler that classifies the rest, rather than a pool
#: that would swallow it.  Shrink freely; adding an entry means a new
#: hand-rolled copy and needs a different fix.
_GRANDFATHERED = frozenset(
    {
        "adr_reviewer.py",
        "approval_records.py",
        "base_background_loop.py",
        "entry_evidence_loop.py",
        "evidence_pack.py",
        "plan_council.py",
        "post_merge_handler.py",
        "pr_unsticker.py",
        "subprocess_util.py",
        "term_proposer_loop.py",
    }
)

_IGNORED_DIRS = {".venv", "node_modules", "__pycache__", "hydraflow.egg-info"}


def _leaf(node: ast.expr | None) -> str | None:
    """The bare type name of one operand: ``X`` or ``mod.X``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _flatten_union(node: ast.expr) -> list[ast.expr]:
    """Split an ``A | B | C`` chain into its operands."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_union(node.left) + _flatten_union(node.right)
    return [node]


def _set_names(node: ast.expr | None) -> set[str]:
    """Type names of a *multi-type* operand — literal collection or union."""
    if node is None:
        return set()
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        elts: list[ast.expr] = list(node.elts)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        elts = _flatten_union(node)
    else:
        return set()
    return {leaf for e in elts if (leaf := _leaf(e)) is not None}


def _aliases(tree: ast.AST) -> set[str]:
    """Local names bound to the needle, following ``import ... as`` renames."""
    names = {_NEEDLE}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == _NEEDLE and a.asname}
    return names


def _split_reraise_names(node: ast.Try) -> set[str]:
    """Types caught by this ``try``'s bare-``raise`` handlers, unioned.

    ``except A: raise`` / ``except B: raise`` is the same policy as
    ``except (A, B): raise``, just spelled one clause at a time.
    """
    names: set[str] = set()
    for handler in node.handlers:
        body = handler.body
        if len(body) != 1 or not isinstance(body[0], ast.Raise) or body[0].exc:
            continue
        names |= _set_names(handler.type) or {
            leaf for leaf in [_leaf(handler.type)] if leaf is not None
        }
    return names


def _fatal_set_literals(tree: ast.AST) -> list[int]:
    """Line numbers of in-place exception-set literals naming the needle."""
    aliases = _aliases(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            names = _split_reraise_names(node)
        else:
            operand: ast.expr | None = None
            if isinstance(node, ast.ExceptHandler):
                operand = node.type
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "isinstance"
                and len(node.args) == 2
            ):
                operand = node.args[1]
            elif isinstance(node, ast.Assign | ast.AnnAssign):
                operand = node.value
            names = _set_names(operand)
        if names & aliases and len(names) > 1:
            lines.append(node.lineno)
    return lines


def _offenders(src: Path) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for py in sorted(src.rglob("*.py")):
        if _IGNORED_DIRS.intersection(py.parts):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = _fatal_set_literals(tree)
        if lines:
            found[py.relative_to(src).as_posix()] = sorted(set(lines))
    return found


def test_no_new_module_hand_rolls_a_fatal_exception_set(real_repo_root: Path) -> None:
    """Only ``exception_classify`` defines what "fatal" means (#11618)."""
    allowed = _GRANDFATHERED | {_OWNER}
    offenders = {
        rel: lines
        for rel, lines in _offenders(real_repo_root / "src").items()
        if rel not in allowed
    }
    assert offenders == {}, (
        "Hand-rolled fatal-exception set outside exception_classify.py: "
        f"{offenders}. Import INFRA_FATAL_EXCEPTIONS / FATAL_EXCEPTIONS, or "
        "call is_fatal() / reraise_on_credit_or_bug() — a restated tuple is "
        "how the worker pools drifted from the canonical set (#11618)."
    )


def test_grandfathered_list_has_no_stale_entries(real_repo_root: Path) -> None:
    """Guard the ratchet: a cleaned-up module must leave the allowlist."""
    offenders = set(_offenders(real_repo_root / "src"))
    stale = sorted(_GRANDFATHERED - offenders)
    assert stale == [], (
        f"These modules no longer hand-roll a fatal set: {stale}. "
        "Remove them from _GRANDFATHERED so the ratchet keeps shrinking."
    )


def test_the_canonical_owner_still_defines_the_set(real_repo_root: Path) -> None:
    """Guard the guard: an empty scan must not silently pass."""
    tree = ast.parse((real_repo_root / "src" / _OWNER).read_text(encoding="utf-8"))
    assert _fatal_set_literals(tree), f"{_OWNER} no longer defines the fatal set?"


def _detect(fixture_src_tree, body: str) -> list[int]:
    root = fixture_src_tree({"src/probe.py": body})
    return _fatal_set_literals(ast.parse((root / "src" / "probe.py").read_text()))


#: Every way a fatal set gets re-stated in place.  An evadable guard rots, so
#: each shape the detector claims to reach is pinned here.
_RESTATEMENT_SHAPES = [
    pytest.param(
        """
        try:
            work()
        except (AuthenticationError, CreditExhaustedError, MemoryError):
            raise
        """,
        id="except-clause-tuple",
    ),
    pytest.param(
        "if isinstance(exc, AuthenticationError | CreditExhaustedError):\n"
        "    raise exc\n",
        id="isinstance-union",
    ),
    pytest.param(
        "_FATAL = (AuthenticationError, CreditExhaustedError, MemoryError)\n",
        id="assigned-tuple",
    ),
    pytest.param(
        "_FATAL = [AuthenticationError, CreditExhaustedError, MemoryError]\n",
        id="list-literal",
    ),
    pytest.param(
        """
        from subprocess_util import CreditExhaustedError as CE

        try:
            work()
        except (AuthenticationError, CE, MemoryError):
            raise
        """,
        id="import-alias",
    ),
    pytest.param(
        """
        try:
            work()
        except (subprocess_util.CreditExhaustedError, MemoryError):
            raise
        """,
        id="module-attribute",
    ),
    pytest.param(
        """
        try:
            work()
        except CreditExhaustedError:
            raise
        except AuthenticationError:
            raise
        except MemoryError:
            raise
        """,
        id="split-across-sibling-clauses",
    ),
]

#: Shapes that name the needle without restating a policy.
_INNOCENT_SHAPES = [
    pytest.param(
        "try:\n    work()\nexcept CreditExhaustedError:\n    pause()\n",
        id="single-type-handler",
    ),
    pytest.param(
        "_pending: dict[int, CreditExhaustedError] = {}\n", id="type-annotation"
    ),
]


@pytest.mark.parametrize("body", _RESTATEMENT_SHAPES)
def test_detector_catches_every_restatement_shape(fixture_src_tree, body: str) -> None:
    assert _detect(fixture_src_tree, body)


@pytest.mark.parametrize("body", _INNOCENT_SHAPES)
def test_detector_ignores_non_restatements(fixture_src_tree, body: str) -> None:
    assert not _detect(fixture_src_tree, body)
