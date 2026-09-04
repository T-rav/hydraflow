"""A mirrored mixin seam must match the implementation it stands in for.

Regression for the ADR-0149 build. ``PlanPhase`` inherits
``_run_spec_ac_and_judge``'s real body from ``PlanAdversarialMixin`` and a
``TYPE_CHECKING``-only declaration of the same method from
``PlanRecordsMixin``. Changing the implementation's return type from
``None`` to ``CriteriaDraft | None`` left the mirror behind, and every base
class then defined the method "in an incompatible way".

The escape route this closes: **no test could see it.** The declaration
does not exist at runtime — ``if TYPE_CHECKING`` never executes — so
importing the class, calling the method, and asserting on its result all
pass with the mirror stale. Only pyright noticed, in the pre-push gate.
That is the same shape as "stated in N places, pinned in N-1", and the
repo has a standard for it: parametrise over the set, by reference.

This guard reads both sides from source and compares them, so a future
signature change to any mirrored seam reddens here rather than surviving
until someone happens to run a type checker.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

# The marker every mirrored declaration in this repo carries.
_PROVIDED_BY = "provided by"


def _return_annotation(node: ast.AsyncFunctionDef | ast.FunctionDef) -> str:
    """The method's return annotation, normalised to source text."""
    return ast.unparse(node.returns) if node.returns is not None else ""


def _is_seam_stub(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """True when the body is just ``...`` — a declaration, not an implementation."""
    body = [n for n in node.body if not isinstance(n, ast.Expr | ast.Pass)]
    if body:
        return False
    return any(
        isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Constant)
        and n.value.value is Ellipsis
        for n in node.body
    )


def _walk_functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            yield node


def _collect() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (declarations, implementations) as name -> set of annotations."""
    declarations: dict[str, set[str]] = {}
    implementations: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        source = path.read_text(encoding="utf-8")
        for node in _walk_functions(tree):
            if not node.name.startswith("_"):
                continue
            annotation = _return_annotation(node)
            if not annotation:
                continue
            if _is_seam_stub(node):
                # Only count stubs that are declared AS mirrors.
                line = source.splitlines()[node.lineno - 1 : node.end_lineno]
                if any(_PROVIDED_BY in text for text in line):
                    declarations.setdefault(node.name, set()).add(annotation)
            else:
                implementations.setdefault(node.name, set()).add(annotation)
    return declarations, implementations


_DECLARATIONS, _IMPLEMENTATIONS = _collect()

# ``Any`` is compatible with every type by the type system's own rules, so a
# seam deliberately declared loose is not the defect this guard hunts. The
# defect is a declaration that CONTRADICTS its implementation. Filtered out of
# the subject set rather than skipped inside it, so the parametrise count is
# the number of seams actually being checked.
_ALWAYS_COMPATIBLE = frozenset({"Any", "object"})

# Only names that appear on BOTH sides, with at least one committal
# declaration, can disagree.
_MIRRORED = sorted(
    name
    for name in set(_DECLARATIONS) & set(_IMPLEMENTATIONS)
    if _DECLARATIONS[name] - _ALWAYS_COMPATIBLE
)


def test_the_sweep_found_mirrored_seams():
    """A sweep with an empty subject passes for the wrong reason."""
    assert _MIRRORED, (
        "no mirrored mixin seams found — the `# provided by <Mixin>` "
        "convention moved, and this guard now checks nothing"
    )


def test_the_known_regression_subject_is_in_the_set():
    """The method whose mirror went stale must be one of the subjects."""
    assert "_run_spec_ac_and_judge" in _MIRRORED


@pytest.mark.parametrize("name", _MIRRORED)
def test_a_mirrored_seam_agrees_with_its_implementation(name: str):
    declared = _DECLARATIONS[name] - _ALWAYS_COMPATIBLE
    implemented = _IMPLEMENTATIONS[name]

    assert declared <= implemented, (
        f"the mirrored declaration of `{name}` returns {sorted(declared)} but "
        f"its implementation returns {sorted(implemented)}. A TYPE_CHECKING "
        "seam does not exist at runtime, so no test can call this difference "
        "into failure — update both sides together."
    )
