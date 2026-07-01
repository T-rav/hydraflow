"""Pure conformance model + check resolution/evaluation (ADR-0094).

Mirrors src/loop_fitness.py: pure functions over data, no I/O in the model
layer, replay-safe. Execution is injected via ConformanceRunnerPort so this
module never shells out. Sibling of ADR-0093's loop fitness — fitness for
architecture decisions instead of loops.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from adr_index import Check


class ConformanceKind(StrEnum):
    ENFORCED = "enforced"
    MANUAL = "manual"
    DECISION_OF_RECORD = "decision-of-record"


class CheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    MANUAL = "manual"
    SKIPPED = "skipped"
    UNRESOLVED = "unresolved"


class CheckResult(BaseModel):
    check: str
    outcome: CheckOutcome
    duration_s: float = 0.0
    detail: str | None = None


class AdrConformance(BaseModel):
    adr_id: str
    kind: ConformanceKind
    outcome: CheckOutcome
    checks: list[CheckResult] = Field(default_factory=list)
    timestamp: datetime


def classify_enforcement(raw: str) -> ConformanceKind | None:
    try:
        return ConformanceKind(raw.strip().lower())
    except ValueError:
        return None


MUTATING_MAKE_TARGETS: frozenset[str] = frozenset(
    {
        "lint",
        "lint-fix",
        "lint-ul",
        "arch-regen",
        "arch-regen-stage",
        "install",
        "setup",
    }
)

_PARAM_SUFFIX_RE = re.compile(r"\[.*\]$")


def is_mutating(check: Check) -> bool:
    return check.kind == "make" and check.target in MUTATING_MAKE_TARGETS


def _module_level_name_defined(tree: ast.Module, wanted: str) -> bool:
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and n.name == wanted
        for n in tree.body
    )


def _class_method_defined(
    tree: ast.Module, class_name: str, wanted_method: str
) -> bool:
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == class_name:
            return any(
                isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                and m.name == wanted_method
                for m in cls.body
            )
    return False


def _pytest_node_defined(repo_root: Path, node: str) -> bool:
    file_part, _, name_part = node.partition("::")
    path = repo_root / file_part
    if not path.is_file():
        return False
    if not name_part:
        return True  # module-only citation, e.g. "tests/t.py"

    segments = name_part.split("::")
    if len(segments) > 2:
        # Deeper nesting (e.g. Class::Nested::method) is out of scope for this
        # resolver; be strict and treat it as unresolved rather than guess.
        return False

    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return False

    if len(segments) == 1:
        wanted = _PARAM_SUFFIX_RE.sub("", segments[0])
        return True if not wanted else _module_level_name_defined(tree, wanted)

    # Two segments: Class::method. The method must be a direct child of the
    # named class, not merely present somewhere in the file (the reviewer's
    # false-positive: same method name defined in an unrelated class).
    class_name, method_part = segments
    wanted_method = _PARAM_SUFFIX_RE.sub("", method_part)
    return _class_method_defined(tree, class_name, wanted_method)


def _make_target_defined(repo_root: Path, target: str) -> bool:
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return False
    pattern = re.compile(rf"^{re.escape(target)}\s*:", re.MULTILINE)
    return bool(pattern.search(makefile.read_text()))


def resolve_check(check: Check, repo_root: Path) -> bool:
    if check.kind == "pytest":
        return _pytest_node_defined(repo_root, check.target)
    if check.kind == "make":
        return _make_target_defined(repo_root, check.target)
    return False  # prose is unresolvable by design
