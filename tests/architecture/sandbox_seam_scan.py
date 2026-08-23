"""AST enumeration of LLM/subprocess spawn call sites in loop + runner modules.

Support code for the sandbox seam completeness guard (#10012, s51/s56/s57
wedge class). Pure functions only — no repo mutation, no subprocesses. The
guard test (``test_sandbox_seam_completeness.py``) and its regression story
(``tests/regressions/test_sandbox_seam_guard.py``) both import from here.

A "spawn primitive" is one of the call names through which loop/runner code
reaches a real ``claude`` or a raw subprocess. The scan is lexical (call
sites by name, per module), deliberately line-number-free so signatures are
drift-immune, mirroring ``disturbance.models.Finding``.

``scan_runner_constructions`` covers the blind spot that scan cannot see
(#11590/#11602): a ``BaseSubprocessRunner`` subclass spawns through the base's
``run``, so the CONSTRUCTING module has no lexical spawn call and never appears
in a spawn signature. Its air-gap depends on where the instance is built —
injected at the composition root (attachable sentinel) vs. built inside a
method (not attachable) — so the construction sites are enumerated in their own
right.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Mapping
from pathlib import Path

# Call names that spawn an LLM or subprocess. ``run_subprocess_result`` is
# subprocess_util's non-raising twin of ``run_subprocess`` — same spawn class,
# included so switching a caller between the two cannot dodge the guard.
from tests.loop_module_scan import loop_source_files

SPAWN_PRIMITIVES: frozenset[str] = frozenset(
    {
        "run_lightweight_agent",
        "get_default_runner",
        "stream_claude_process",
        "create_subprocess_exec",
        "run_subprocess",
        "run_subprocess_result",
    }
)


def spawn_target_files(repo_root: Path) -> list[Path]:
    """Enumerate the loop + runner modules the guard scans.

    Scope per #10012: every background loop, ``src/*_runner.py``, and everything
    under ``src/runners/``. Non-recursive at the ``src`` top level, so
    ``src/mockworld/**`` (the Fakes — sandbox-side seam machinery itself)
    stays out of scope.

    A loop is enumerated as a UNIT: a decomposed loop (``src/foo_loop/``) still
    contributes all of its files, so relocating a spawn call into a mixin
    cannot walk it out of this guard's scope.
    """
    src = repo_root / "src"
    files: set[Path] = set(loop_source_files(src))
    files.update(src.glob("*_runner.py"))
    files.update(p for p in (src / "runners").glob("**/*.py"))
    return sorted(files)


class _SpawnCallVisitor(ast.NodeVisitor):
    """Collects (enclosing qualname, primitive name) for every spawn call."""

    def __init__(self) -> None:
        self._stack: list[str] = []
        self.hits: list[tuple[str, str]] = []

    def _visit_scoped(self, node: ast.AST, name: str) -> None:
        self._stack.append(name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        callee = node.func
        name: str | None = None
        if isinstance(callee, ast.Name):
            name = callee.id
        elif isinstance(callee, ast.Attribute):
            name = callee.attr
        if name in SPAWN_PRIMITIVES:
            qualname = ".".join(self._stack) or "<module>"
            self.hits.append((qualname, name))
        self.generic_visit(node)


def _distinct_owner(first: str, second: str) -> bool:
    """True when two paths sharing a seam key are genuinely different modules.

    Two private members of the SAME package legitimately share the package's
    key — that is the point of ``seam_key``, not a collision.
    """
    return Path(first).parent != Path(second).parent


def seam_key(rel_path: str) -> str:
    """The SANDBOX_SEAMS key namespace for a repo-relative source path.

    Normally the module stem. A module that is a PRIVATE member of a package
    (``health_monitor_loop/_freshness.py``, or the package ``__init__``) keys on
    the PACKAGE instead: after a god-class decomposition the loop's spawn sites
    scatter across its mixins, but the thing that declares a seam is still the
    loop, and ``__init__`` alone is not even a unique name (Refs #11547).
    """
    path = Path(rel_path)
    if path.stem == "__init__" or path.stem.startswith("_"):
        return path.parent.name
    return path.stem


def scan_spawn_signatures(repo_root: Path) -> dict[str, int]:
    """Return ``{signature: count}`` for every spawn call site in scope.

    ``signature`` is ``"{posix relpath}::{enclosing qualname}::{primitive}"``
    — line-number-free so refactors that move code within a function do not
    churn the baseline; counts catch a second spawn call added to the same
    function of a grandfathered module.
    """
    counts: dict[str, int] = {}
    stems_seen: dict[str, str] = {}
    for path in spawn_target_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        stem = seam_key(rel)
        if (
            stem in stems_seen
            and stems_seen[stem] != rel
            and _distinct_owner(stems_seen[stem], rel)
        ):
            msg = (
                f"module stem collision: {stems_seen[stem]} vs {rel} — "
                "SANDBOX_SEAMS keys are module stems and must stay unique"
            )
            raise ValueError(msg)
        stems_seen[stem] = rel
        visitor = _SpawnCallVisitor()
        visitor.visit(ast.parse(path.read_text(), filename=rel))
        for qualname, primitive in visitor.hits:
            signature = f"{rel}::{qualname}::{primitive}"
            counts[signature] = counts.get(signature, 0) + 1
    return counts


#: Base class whose subclasses spawn through ``BaseSubprocessRunner.run``.
#: Their construction sites are invisible to ``scan_spawn_signatures`` — the
#: only lexical spawn is inside ``src/runners/base_subprocess_runner.py`` — so
#: they get their own scan (#11590/#11602).
SUBPROCESS_RUNNER_BASE = "BaseSubprocessRunner"


def runner_construction_target_files(repo_root: Path) -> list[Path]:
    """Enumerate the modules the construction-site scan reads.

    All of ``src/`` recursively, minus ``src/mockworld/`` (the Fakes — the
    sandbox-side seam machinery itself) and vendored ``node_modules`` trees.
    Composition roots that build runners live anywhere (``service_registry``,
    a loop module, a phase), so this scan cannot use the narrow
    loop/runner glob ``spawn_target_files`` uses.
    """
    src = repo_root / "src"
    return sorted(
        path
        for path in src.glob("**/*.py")
        if "node_modules" not in path.parts and (src / "mockworld") not in path.parents
    )


def _base_names(node: ast.ClassDef) -> set[str]:
    """Names of *node*'s bases, unwrapping ``Generic[...]`` subscripts."""
    names: set[str] = set()
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def subprocess_runner_subclasses(repo_root: Path) -> set[str]:
    """Class names in ``src/`` that subclass ``BaseSubprocessRunner``.

    Transitive: a subclass of a subclass spawns through the same base ``run``
    and needs a seam just as much, so the class set is closed to a fixed point
    rather than matched against the literal base name once.
    """
    by_class: dict[str, set[str]] = {}
    for path in runner_construction_target_files(repo_root):
        tree = ast.parse(path.read_text(), filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                by_class.setdefault(node.name, set()).update(_base_names(node))
    found = {SUBPROCESS_RUNNER_BASE}
    while True:
        grown = {name for name, bases in by_class.items() if bases & found} | found
        if grown == found:
            return found - {SUBPROCESS_RUNNER_BASE}
        found = grown


class _RunnerConstructionVisitor(ast.NodeVisitor):
    """Collects (enclosing qualname, class name) for every runner construction.

    Import aliases are resolved back to the real class name
    (``from x import AutoAgentRunner as AAR`` → ``AAR(...)`` is recorded as
    ``AutoAgentRunner``) so renaming at the import site cannot dodge the
    ratchet — and so the recorded signature stays stable across such a rename.
    """

    def __init__(self, class_names: Collection[str]) -> None:
        self._class_names = set(class_names)
        self._aliases: dict[str, str] = {}
        self._stack: list[str] = []
        self.hits: list[tuple[str, str]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.asname and alias.name in self._class_names:
                self._aliases[alias.asname] = alias.name
        self.generic_visit(node)

    def _visit_scoped(self, node: ast.AST, name: str) -> None:
        self._stack.append(name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        callee = node.func
        name: str | None = None
        if isinstance(callee, ast.Name):
            name = callee.id
        elif isinstance(callee, ast.Attribute):
            name = callee.attr
        resolved = self._aliases.get(name or "", name)
        if resolved in self._class_names:
            qualname = ".".join(self._stack) or "<module>"
            self.hits.append((qualname, resolved))
        self.generic_visit(node)


def scan_runner_constructions(repo_root: Path) -> dict[str, int]:
    """Return ``{signature: count}`` for every ``BaseSubprocessRunner`` build.

    ``signature`` is ``"{posix relpath}::{enclosing qualname}::{ClassName}"``,
    line-number-free like ``scan_spawn_signatures``. Counts matter: the three
    ``AutoAgentRunner``s of ``service_registry.build_services`` share one
    signature, so a fourth added there must be declared too.
    """
    class_names = subprocess_runner_subclasses(repo_root)
    counts: dict[str, int] = {}
    for path in runner_construction_target_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        visitor = _RunnerConstructionVisitor(class_names)
        visitor.visit(ast.parse(path.read_text(), filename=rel))
        for qualname, class_name in visitor.hits:
            signature = f"{rel}::{qualname}::{class_name}"
            counts[signature] = counts.get(signature, 0) + 1
    return counts


def signature_module(signature: str) -> str:
    """Module stem for a signature (the SANDBOX_SEAMS key namespace)."""
    return seam_key(signature.split("::", 1)[0])


def undeclared_signatures(
    current: Mapping[str, int], declared_modules: Collection[str]
) -> dict[str, int]:
    """Signatures whose module declares no seam in SANDBOX_SEAMS."""
    return {
        signature: count
        for signature, count in current.items()
        if signature_module(signature) not in declared_modules
    }


def ratchet_diff(
    current: Mapping[str, int], baseline: Mapping[str, int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Compare undeclared spawn counts to the grandfathered baseline.

    Returns ``(new, resolved)`` — mirrors ``disturbance.baseline.diff``:
    ``new`` maps signature -> excess over baseline (guard reddens);
    ``resolved`` maps signature -> shortfall under baseline (baseline must
    be pruned in the same change so the ratchet only shrinks).
    """
    new: dict[str, int] = {}
    resolved: dict[str, int] = {}
    for signature, count in current.items():
        allowed = baseline.get(signature, 0)
        if count > allowed:
            new[signature] = count - allowed
    for signature, allowed in baseline.items():
        count = current.get(signature, 0)
        if count < allowed:
            resolved[signature] = allowed - count
    return new, resolved
