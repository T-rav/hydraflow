"""Pure conformance model + check resolution/evaluation (ADR-0098).

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
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from adr_index import ADR, Check

if TYPE_CHECKING:
    from ports import ConformanceRunnerPort


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


def _wanted_node_name(name_part: str) -> tuple[str, ...] | None:
    """Split a pytest node's ``name`` segment(s) into a tuple of bare names
    (param-suffix stripped), or ``None`` if the shape isn't one this
    resolver understands (no name, or >2 segments)."""
    if not name_part:
        return None
    segments = name_part.split("::")
    if len(segments) > 2:
        return None
    return tuple(_PARAM_SUFFIX_RE.sub("", s) for s in segments)


def _defines_node(path: Path, wanted: tuple[str, ...]) -> bool:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    if len(wanted) == 1:
        return _module_level_name_defined(tree, wanted[0])
    class_name, method_name = wanted
    return _class_method_defined(tree, class_name, method_name)


def find_renamed_pytest_node(node_target: str, repo_root: Path) -> str | None:
    """High-confidence rename detection for an UNRESOLVED pytest node target.

    ``node_target`` is the *unresolved* target half of a ``pytest:`` check
    (e.g. ``tests/old.py::test_x`` or ``tests/old.py::TestFoo::test_x``,
    optionally with a trailing ``[param]`` suffix). Scans
    ``repo_root/tests/**/*.py`` for files (other than the original) that
    define the same bare function/class-method name via the same AST
    matching ``_pytest_node_defined`` uses.

    Returns the new typed identity string ``pytest:<newpath>::<name>``
    (preserving ``Class::method`` structure) only when EXACTLY ONE other
    file defines the name — that is the high-confidence bar. Zero or
    multiple matches are ambiguous and return ``None`` so the caller routes
    to FILE_ISSUE instead of a possibly-wrong REPOINT.

    Make-target renames are out of scope here (this function only handles
    ``pytest:`` targets structurally — callers should not pass make targets
    in) and this never raises: any AST/OSError during a scan is treated as
    "that candidate doesn't match" rather than propagated.
    """
    file_part, _, name_part = node_target.partition("::")
    wanted = _wanted_node_name(name_part)
    if not wanted:
        return None  # module-only citation or unsupported nesting depth

    original = (repo_root / file_part).resolve()
    tests_root = repo_root / "tests"
    if not tests_root.is_dir():
        return None

    try:
        candidates = list(tests_root.rglob("*.py"))
    except OSError:
        return None

    matches: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.resolve() == original:
                continue
        except OSError:
            continue
        if _defines_node(candidate, wanted):
            matches.append(candidate)

    if len(matches) != 1:
        return None  # zero -> not found; >1 -> ambiguous, not high-confidence

    new_path = matches[0].relative_to(repo_root).as_posix()
    return f"pytest:{new_path}::{'::'.join(wanted)}"


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


_WORST = {
    CheckOutcome.PASS: 0,
    CheckOutcome.SKIPPED: 0,
    CheckOutcome.MANUAL: 0,
    CheckOutcome.UNRESOLVED: 1,
    CheckOutcome.FAIL: 2,
}


def evaluate_adrs(
    adrs: list[ADR],
    runner: ConformanceRunnerPort,
    *,
    repo_root: Path,
    timestamp: datetime,
) -> list[AdrConformance]:
    out: list[AdrConformance] = []
    for a in adrs:
        if a.status != "Accepted":
            continue
        kind = classify_enforcement(a.enforcement)
        if kind is None:
            continue  # unknown — the ratchet blocks these at CI; runner ignores
        adr_id = f"ADR-{a.number:04d}"
        if kind is ConformanceKind.DECISION_OF_RECORD:
            out.append(
                AdrConformance(
                    adr_id=adr_id,
                    kind=kind,
                    outcome=CheckOutcome.SKIPPED,
                    checks=[],
                    timestamp=timestamp,
                )
            )
            continue
        if kind is ConformanceKind.MANUAL:
            checks = [
                CheckResult(check=c.raw, outcome=CheckOutcome.MANUAL)
                for c in a.enforced_by
            ]
            out.append(
                AdrConformance(
                    adr_id=adr_id,
                    kind=kind,
                    outcome=CheckOutcome.MANUAL,
                    checks=checks,
                    timestamp=timestamp,
                )
            )
            continue
        # enforced
        results: list[CheckResult] = []
        for c in a.enforced_by:
            if c.kind != "prose" and not resolve_check(c, repo_root):
                results.append(
                    CheckResult(check=c.raw, outcome=CheckOutcome.UNRESOLVED)
                )
                continue
            results.append(runner.run(c, repo_root=repo_root))
        worst = max(
            (r.outcome for r in results),
            key=lambda o: _WORST[o],
            default=CheckOutcome.PASS,
        )
        out.append(
            AdrConformance(
                adr_id=adr_id,
                kind=kind,
                outcome=worst,
                checks=results,
                timestamp=timestamp,
            )
        )
    return out
