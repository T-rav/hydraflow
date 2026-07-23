"""AST enumeration of LLM/subprocess spawn call sites in loop + runner modules.

Support code for the sandbox seam completeness guard (#10012, s51/s56/s57
wedge class). Pure functions only — no repo mutation, no subprocesses. The
guard test (``test_sandbox_seam_completeness.py``) and its regression story
(``tests/regressions/test_sandbox_seam_guard.py``) both import from here.

A "spawn primitive" is one of the call names through which loop/runner code
reaches a real ``claude`` or a raw subprocess. The scan is lexical (call
sites by name, per module), deliberately line-number-free so signatures are
drift-immune, mirroring ``disturbance.models.Finding``.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Mapping
from pathlib import Path

# Call names that spawn an LLM or subprocess. ``run_subprocess_result`` is
# subprocess_util's non-raising twin of ``run_subprocess`` — same spawn class,
# included so switching a caller between the two cannot dodge the guard.
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

    Scope per #10012: ``src/*_loop.py``, ``src/*_runner.py``, and everything
    under ``src/runners/``. Non-recursive at the ``src`` top level, so
    ``src/mockworld/**`` (the Fakes — sandbox-side seam machinery itself)
    stays out of scope.
    """
    src = repo_root / "src"
    files: set[Path] = set(src.glob("*_loop.py"))
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
        stem = path.stem
        if stem in stems_seen and stems_seen[stem] != rel:
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


def signature_module(signature: str) -> str:
    """Module stem for a signature (the SANDBOX_SEAMS key namespace)."""
    return Path(signature.split("::", 1)[0]).stem


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
