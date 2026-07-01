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
    {"lint", "lint-fix", "lint-ul", "arch-regen", "arch-regen-stage", "install", "setup"}
)

_PARAM_SUFFIX_RE = re.compile(r"\[.*\]$")


def is_mutating(check: Check) -> bool:
    return check.kind == "make" and check.target in MUTATING_MAKE_TARGETS


def _pytest_node_defined(repo_root: Path, node: str) -> bool:
    file_part, _, name_part = node.partition("::")
    path = repo_root / file_part
    if not path.is_file():
        return False
    # Last segment is the test function (possibly Class::method); strip params.
    wanted = _PARAM_SUFFIX_RE.sub("", name_part.split("::")[-1]) if name_part else ""
    if not wanted:
        return True  # module-level citation
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return False
    names = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    return wanted in names


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
