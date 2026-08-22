"""Structural gate: the fatal-exception set is defined ONLY in ``exception_classify``.

Issue #11618: the concurrent worker pools re-stated "fatal" as a literal
``(AuthenticationError, CreditExhaustedError, MemoryError)`` tuple — a second
copy of a policy that ``exception_classify.reraise_on_credit_or_bug`` already
owned.  The two copies drifted: the pools' copy omitted
``LIKELY_BUG_EXCEPTIONS``, so a ``TypeError`` in a pooled worker was logged and
dropped while the same exception escalated off-pool.  Restating a policy is how
it drifts; this gate makes a third copy structurally impossible.

Any exception-set expression naming ``CreditExhaustedError`` — an ``except``
clause tuple, an ``isinstance`` type argument, or an assigned tuple constant —
must come from ``exception_classify`` (``INFRA_FATAL_EXCEPTIONS`` /
``FATAL_EXCEPTIONS`` / ``is_fatal``), not from a literal enumerated in place.

``_GRANDFATHERED`` freezes the pre-existing ``(AuthenticationError,
CreditExhaustedError)`` re-raise guards.  Those sit *ahead* of a handler that
already classifies likely bugs, so they do not swallow anything — but they are
the same restatement shape, so the list may shrink and must never grow.
Static AST scan only; never imports the modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

_OWNER = "exception_classify.py"

#: Modules that still enumerate a fatal set in place, as of #11618.  Every one
#: is an ``except (AuthenticationError, CreditExhaustedError)`` re-raise guard
#: in front of a classifying handler, not a swallowing pool.  Shrink freely;
#: adding an entry means a new hand-rolled copy and needs a different fix.
_GRANDFATHERED = frozenset(
    {
        "adr_reviewer.py",
        "approval_records.py",
        "base_background_loop.py",
        "diagnostic_loop.py",
        "entry_evidence_loop.py",
        "plan_council.py",
        "post_merge_handler.py",
        "pr_unsticker.py",
        "review_phase/_phase.py",
        "subprocess_util.py",
        "term_proposer_loop.py",
    }
)

_IGNORED_DIRS = {".venv", "node_modules", "__pycache__", "hydraflow.egg-info"}


def _names(node: ast.expr | None) -> set[str]:
    """Exception type names mentioned by an ``except``/``isinstance`` operand."""
    if node is None:
        return set()
    if isinstance(node, ast.Tuple):
        return {e.id for e in node.elts if isinstance(e, ast.Name)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    return set()


def _fatal_set_literals(tree: ast.AST) -> list[int]:
    """Line numbers of in-place exception-set literals naming CreditExhaustedError."""
    lines: list[int] = []
    for node in ast.walk(tree):
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
        names = _names(operand)
        if "CreditExhaustedError" in names and len(names) > 1:
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
            found[py.relative_to(src).as_posix()] = lines
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
