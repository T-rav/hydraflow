"""Stamped document bodies live in files, not in Python string literals.

`kernel_writer` (the `make stamp` CLI) and `templating` (the `/api/onboarding`
wizard) each held their own f-string copy of the same stamped documents --
eleven same-named builders across two modules. They had already drifted: the
kernel's CLAUDE.md carried ownership markers and the full rule set, the
wizard's carried neither, so two repos born the same week through different
doors got different kernels.

The only thing nominally holding that split was a sentence in `kernel_writer`'s
module docstring saying the modules must not diverge. That is prose, enforced
by nothing -- the same shape as the ownership markers in the stamped CLAUDE.md,
which turned out to be read by no parser at all. This file is the structural
check that replaces it: the f-strings cannot grow back, because a document body
large enough to be a document has to be a file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# DERIVED, never spelled: every module in the onboarding package. A literal
# tuple naming the two known writers is a predicate that silently narrows —
# add a third materializer and the guard simply stops covering it while staying
# green, which is the exact defect class this file exists to close
# (docs/standards/parametrised_guards/README.md, #11723). Widening the subject
# to the whole package costs nothing: no module here has any business holding a
# document body, whether or not it stamps one today.
GUARDED = tuple(
    sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "src/onboarding").glob("*.py")
    )
)
BODIES = REPO_ROOT / "src/hydraflow_resources/kernel_templates/bodies"

# A fragment a builder may still legitimately hold (a Makefile prerequisite
# line, a shell snippet) is short and has at most a couple of newlines. Every
# body extracted from these two modules had >= 3.
MAX_NEWLINES_IN_A_LITERAL = 2


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """id() of every Constant that is a docstring, which may stay inline."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            out.add(id(body[0].value))
    return out


@pytest.mark.parametrize("relative", GUARDED)
def test_no_module_holds_a_document_body_as_a_string_literal(relative: str) -> None:
    path = REPO_ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)

    offenders = [
        (node.lineno, node.value.splitlines()[0][:60])
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and node.value.count("\n") > MAX_NEWLINES_IN_A_LITERAL
    ]
    assert not offenders, (
        f"{relative} holds document text as a string literal; stamped bodies "
        f"belong in {BODIES.relative_to(REPO_ROOT)} so a change to a document "
        f"is a diff in that document:\n  "
        + "\n  ".join(f"line {line}: {head!r}" for line, head in offenders)
    )


def test_the_bodies_directory_is_populated() -> None:
    """Anti-vacuity: the guard above passes trivially against an empty design.

    Deleting every template file and every call site would satisfy
    "no literals" while stamping nothing at all.
    """
    found = [p for p in BODIES.rglob("*") if p.is_file()]
    assert len(found) >= 30, (
        f"only {len(found)} template bodies under {BODIES}; the two writers "
        "stamp far more documents than that, so the bodies are not all here"
    )
