"""Pure conformance model + check resolution/evaluation (ADR-0100).

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


# High-confidence mutation signals scanned in a make target's recipe. Chosen
# to be unambiguous — a read-only check (pytest, arch-check, lint-check,
# `git diff`/`git log`) never contains these — so the recipe scan hardens the
# denylist toward fail-CLOSED (an unknown target that writes to the repo/remote
# is caught) without false-flagging legitimate side-effect-free checks.
_RECIPE_MUTATION_SIGNALS: tuple[str, ...] = (
    "git commit",
    "git push",
    "git add",
    "git checkout",
    "git reset",
    "git rm",
    "git mv",
    "git stash",
    "git merge",
    "git rebase",
    "git tag",
    "git apply",
    "gh pr create",
    "gh pr merge",
    "gh issue create",
    "gh release",
    "sed -i",
    "pip install",
    "uv sync",
    "npm install",
    "npm ci",
)


def _make_recipe(repo_root: Path, target: str) -> str:
    """Return the recipe body of a Makefile *target* (its tab-indented lines).

    A make recipe is the contiguous run of tab-prefixed lines following the
    ``target:`` line; it ends at the first non-tab line. Returns "" when the
    Makefile or target is absent.
    """
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return ""
    target_re = re.compile(rf"^{re.escape(target)}\s*:")
    recipe: list[str] = []
    in_target = False
    for line in makefile.read_text().splitlines():
        if target_re.match(line):
            in_target = True
            continue
        if in_target:
            if line.startswith("\t"):
                recipe.append(line)
            else:
                break
    return "\n".join(recipe)


def _recipe_mutates(repo_root: Path, target: str) -> bool:
    recipe = _make_recipe(repo_root, target)
    return any(sig in recipe for sig in _RECIPE_MUTATION_SIGNALS)


def is_mutating(check: Check, repo_root: Path | None = None) -> bool:
    """True when a make check has side effects and so may not be `enforced`.

    Two layers: the ``MUTATING_MAKE_TARGETS`` denylist (authoritative for
    known-mutating targets whose mutation isn't visible in the recipe text,
    e.g. ``arch-regen`` writing files via a python entrypoint), plus — when
    *repo_root* is given — a recipe scan for high-confidence mutation commands.
    The scan closes the denylist's fail-open gap: a NEW mutating target that
    isn't listed is still caught if its recipe pushes/commits/opens PRs/etc.
    """
    if check.kind != "make":
        return False
    if check.target in MUTATING_MAKE_TARGETS:
        return True
    return repo_root is not None and _recipe_mutates(repo_root, check.target)


def _module_level_name_defined(tree: ast.Module, wanted: str) -> bool:
    return any(
        isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and n.name == wanted
        for n in tree.body
    )


def _class_method_defined(
    tree: ast.Module, class_name: str, wanted_method: str
) -> bool:
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == class_name:
            return any(
                isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
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


def _script_defined(repo_root: Path, target: str) -> bool:
    """A ``script:`` check resolves when the named script file exists.

    An ADR enforced by a repo script (e.g. ``script:scripts/audit_prompts.py``)
    is executable enforcement, not prose — resolvable iff the file is present at
    the repo-relative path. Any trailing arguments after the path (``script:
    scripts/foo.py --check``) are ignored for the existence check.
    """
    if not target:
        return False
    path_part = target.split(maxsplit=1)[0]
    return (repo_root / path_part).is_file()


def resolve_check(check: Check, repo_root: Path) -> bool:
    if check.kind == "pytest":
        return _pytest_node_defined(repo_root, check.target)
    if check.kind == "make":
        return _make_target_defined(repo_root, check.target)
    if check.kind == "script":
        return _script_defined(repo_root, check.target)
    return False  # prose is unresolvable by design


class EnforcementClass(StrEnum):
    """How firmly an Accepted ADR's decision is bound to a runnable check.

    Inverts ADR conformance from the citation-drift firehose (a post-merge
    stream of flags over the unenforceable tail) to the load-bearing
    question: does the ADR's named enforcement resolve to a *real*
    machine-checkable artifact, or is it unenforced-decision debt?

    - ``REAL`` — the ADR is ``enforced`` and at least one of its typed
      checks resolves to an existing, side-effect-free artifact that
      genuinely asserts (a ``pytest:`` node/module carrying an assertion, or
      a ``make:`` guard target).
    - ``WEAK`` — the decision has an ``**Enforced by:**`` pointer but it is
      not a real machine check: a ``manual`` prose pointer (a review-checklist
      sentence), or an ``enforced`` ADR whose typed checks don't resolve /
      are mutating.
    - ``MISSING`` — no ``**Enforced by:**`` check at all (e.g. a bare
      ``decision-of-record`` ADR). The decision is recorded but nothing on
      disk fails when it is violated.

    ``WEAK`` + ``MISSING`` together are the *unenforced-decision debt*. The
    *assertion-strength* signal (``check_is_tautological`` — a resolving but
    hollow check) is deliberately NOT folded in here: it is a soft, advisory
    flag surfaced separately in the debt report, never a hard-fail, because a
    conservative heuristic must not gate CI on its own false positives.
    """

    REAL = "REAL"
    WEAK = "WEAK"
    MISSING = "MISSING"


# Assertion-signal name prefixes/idioms scanned in a resolved pytest node's
# body. A check whose target function/module contains NONE of these (and no
# bare ``assert``) is *tautological*: it resolves (so ADR-0100's existing
# ratchet stays green) yet asserts nothing, so the "decision" it claims to
# enforce could drift without ever turning the check red. Conservative by
# construction — biased toward calling a check STRONG so real tests that
# delegate their assertion to a helper (``verify_*``, ``expect_*``, custom
# ``check_*``) are never mis-flagged as weak.
_ASSERT_NAME_RE = re.compile(
    r"^(assert|verify|expect|ensure|require|raises|warns|fail|check_|should_)"
)


def _callee_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _node_asserts(node: ast.AST) -> bool:
    """True if *node* (a function, class, or whole module AST) contains any
    assertion signal: a bare ``assert``, a ``pytest.raises``/``warns``/``fail``
    (as a call OR a ``with`` context manager), a unittest/mock ``assert*``
    call, or a call to a helper whose name reads as an assertion idiom
    (``verify_*``, ``expect_*``, ``ensure_*``, ``require_*``, ``check_*``,
    ``should_*``)."""
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            return True
        if isinstance(n, ast.Call) and _ASSERT_NAME_RE.match(_callee_name(n)):
            return True
        if isinstance(n, ast.With | ast.AsyncWith):
            for item in n.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and _ASSERT_NAME_RE.match(
                    _callee_name(ctx)
                ):
                    return True
    return False


def _resolve_pytest_node_ast(repo_root: Path, target: str) -> ast.AST | None:
    """Return the AST of the specific node a ``pytest:`` target names, or None.

    ``tests/foo.py`` (module-only) → the whole ``ast.Module``.
    ``tests/foo.py::test_x`` → that function's ``FunctionDef``.
    ``tests/foo.py::TestC::test_x`` → that method's ``FunctionDef`` (a direct
    child of ``TestC``). Anything deeper, unresolvable, or unparseable → None.
    Mirrors ``_pytest_node_defined``'s resolution semantics so the strength
    signal is defined over exactly the nodes the ADR-0100 ratchet accepts.
    """
    file_part, _, name_part = target.partition("::")
    path = repo_root / file_part
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    if not name_part:
        return tree  # module-only citation: strength is over the whole module
    segments = name_part.split("::")
    if len(segments) > 2:
        return None
    if len(segments) == 1:
        wanted = _PARAM_SUFFIX_RE.sub("", segments[0])
        return _named_node(tree, wanted)
    class_name, method_part = segments
    wanted_method = _PARAM_SUFFIX_RE.sub("", method_part)
    return _class_child_node(tree, class_name, wanted_method)


def _named_node(tree: ast.Module, wanted: str) -> ast.AST | None:
    for n in tree.body:
        if (
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and n.name == wanted
        ):
            return n
    return None


def _class_child_node(
    tree: ast.Module, class_name: str, wanted_method: str
) -> ast.AST | None:
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == class_name:
            for m in cls.body:
                if (
                    isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                    and m.name == wanted_method
                ):
                    return m
    return None


def check_is_tautological(check: Check, repo_root: Path) -> bool:
    """True when a ``pytest:`` check RESOLVES to a real node yet that node
    asserts nothing — a green-but-hollow guard.

    Conservative: returns True only for a ``pytest:`` check whose target node
    is found AND contains no assertion signal (see ``_node_asserts``).
    Non-pytest checks, prose, and unresolvable targets return False — this
    flag is exclusively about *resolved-but-hollow* pytest enforcement, not
    about resolution (ADR-0100's ratchet already owns resolution)."""
    if check.kind != "pytest":
        return False
    node = _resolve_pytest_node_ast(repo_root, check.target)
    if node is None:
        return False
    return not _node_asserts(node)


def has_real_enforcement(adr: ADR, repo_root: Path) -> bool:
    """True when *adr* is ``enforced`` and carries at least one resolving,
    non-mutating, non-prose typed check — ADR-0100's ``enforced`` bar.

    This is the robust, non-heuristic predicate the ratchet hard-fails on.
    It deliberately does NOT apply the tautology heuristic: assertion-strength
    is advisory only (surfaced in the debt report), never a CI gate.
    """
    if classify_enforcement(adr.enforcement) is not ConformanceKind.ENFORCED:
        return False
    return any(
        chk.kind != "prose"
        and not is_mutating(chk, repo_root)
        and resolve_check(chk, repo_root)
        for chk in adr.enforced_by
    )


def classify_adr_enforcement(adr: ADR, repo_root: Path) -> EnforcementClass:
    """Classify an Accepted ADR as REAL / WEAK / MISSING (see EnforcementClass).

    Pure over ``adr`` + the on-disk repo; reuses ADR-0100's ``resolve_check``
    / ``is_mutating`` so this never forks the parser or the resolver. REAL iff
    ``has_real_enforcement``; an ADR with no ``**Enforced by:**`` checks is
    MISSING; anything else (a ``manual`` prose pointer, or ``enforced`` checks
    that don't resolve) is WEAK.
    """
    if not adr.enforced_by:
        return EnforcementClass.MISSING
    if has_real_enforcement(adr, repo_root):
        return EnforcementClass.REAL
    return EnforcementClass.WEAK


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
