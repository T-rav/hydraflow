"""AST enumeration of Quality-only-CLI shell-out sites in ``src/``.

Support code for the Quality-only CLI guard (#9411). Pure functions only —
no repo mutation, no subprocesses. The guard test
(``test_quality_only_cli_guard.py``) imports from here.

Background: the GitHub **Quality** workflow runs on a runner image that ships
ripgrep (``rg``); the leaner **CI / Tests** runner does not. ``src/`` code
that shells out to a Quality-only CLI without a ``shutil.which(...)`` guard
passes local ``make quality`` and the Quality runner, then crashes only on
the CI/Tests runner — invisible until CI (#9403→#9404). This scan finds those
call sites so the guard can red at PR time.

The scan is lexical (call sites by shape, per module), deliberately
line-number-free so refactors that move code within a function do not churn
the baseline, mirroring ``sandbox_seam_scan.py`` / ``disturbance.models``.

A **site** is a Quality-only CLI name (``QUALITY_ONLY_CLIS``) appearing in
command position — either the first element of a command list/tuple literal
(``["rg", ...]`` — the executable-first idiom) or a positional string arg to
a subprocess primitive call (``run_subprocess_result("rg", ...)``). A site is
**guarded** iff its nearest enclosing function references
``shutil.which("<tool>")`` (or ``which("<tool>")``) for that same tool — the
enclosing-function scope check that
``FakeCoverageAuditorLoop._grep_scenario_for_helper`` satisfies. Shell-string
forms (``os.system("rg ...")``) are out of scope by design: HydraFlow shells
out via list-form bounded helpers, and the #9403 failure was list-form.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

# Curated set of external CLIs present on the Quality runner but NOT the
# leaner CI/Tests runner. Start with ripgrep; extend by adding a name here.
QUALITY_ONLY_CLIS: frozenset[str] = frozenset({"rg", "ripgrep"})

# Call names through which ``src/`` reaches a raw subprocess. Covers the
# HydraFlow bounded helpers (``run_subprocess`` / ``run_subprocess_result``),
# asyncio, and the stdlib ``subprocess`` surface — so a Quality-only CLI
# passed as a bare positional arg (not wrapped in a list) is still caught.
SUBPROCESS_PRIMITIVES: frozenset[str] = frozenset(
    {
        "run_subprocess",
        "run_subprocess_result",
        "create_subprocess_exec",
        "create_subprocess_shell",
        "run",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
        "Popen",
    }
)


class CliSite(NamedTuple):
    """One Quality-only-CLI shell-out signature's aggregate state.

    ``guarded`` is a function-level property (the whole enclosing function is
    scanned for a ``shutil.which`` guard), so every physical site collapsed
    into one signature shares it.
    """

    count: int
    guarded: bool


def quality_only_target_files(repo_root: Path) -> list[Path]:
    """Every ``.py`` module under ``src/`` (recursive)."""
    return sorted((repo_root / "src").glob("**/*.py"))


def _which_guarded_tool(node: ast.Call) -> str | None:
    """Return the CLI name a ``shutil.which("<tool>")`` call guards, if any.

    Accepts both ``shutil.which("rg")`` (Attribute) and a bare
    ``which("rg")`` (``from shutil import which``).
    """
    callee = node.func
    if isinstance(callee, ast.Attribute):
        is_which = callee.attr == "which"
    elif isinstance(callee, ast.Name):
        is_which = callee.id == "which"
    else:
        is_which = False
    if not is_which or not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and arg.value in QUALITY_ONLY_CLIS:
        return arg.value
    return None


def _guarded_tools(func: ast.AST) -> frozenset[str]:
    """CLI names guarded by a ``shutil.which(...)`` anywhere in ``func``."""
    tools: set[str] = set()
    for sub in ast.walk(func):
        if isinstance(sub, ast.Call):
            tool = _which_guarded_tool(sub)
            if tool is not None:
                tools.add(tool)
    return frozenset(tools)


class _CliSiteVisitor(ast.NodeVisitor):
    """Collects Quality-only-CLI shell-out sites with guard status.

    Maintains a scope stack (for the ``Class.method`` qualname) and a
    function stack (for the nearest-enclosing-function guard scope).
    """

    def __init__(self, relpath: str) -> None:
        self._relpath = relpath
        self._scope: list[str] = []
        self._func_stack: list[ast.AST] = []
        self._guard_cache: dict[int, frozenset[str]] = {}
        # signature -> [count, guarded]
        self.sites: dict[str, list[object]] = {}

    # -- scope tracking -------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def _enter_func(self, node: ast.AST, name: str) -> None:
        self._scope.append(name)
        self._func_stack.append(node)
        self.generic_visit(node)
        self._func_stack.pop()
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_func(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_func(node, node.name)

    # -- site detection -------------------------------------------------

    def visit_List(self, node: ast.List) -> None:
        self._check_command_seq(node.elts)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._check_command_seq(node.elts)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        callee = node.func
        name: str | None = None
        if isinstance(callee, ast.Name):
            name = callee.id
        elif isinstance(callee, ast.Attribute):
            name = callee.attr
        if name in SUBPROCESS_PRIMITIVES:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value in QUALITY_ONLY_CLIS:
                    self._record(arg.value)
        self.generic_visit(node)

    # -- helpers --------------------------------------------------------

    def _check_command_seq(self, elts: list[ast.expr]) -> None:
        if not elts:
            return
        first = elts[0]
        if isinstance(first, ast.Constant) and first.value in QUALITY_ONLY_CLIS:
            self._record(first.value)

    def _current_guarded(self, tool: str) -> bool:
        if not self._func_stack:
            return False
        func = self._func_stack[-1]
        key = id(func)
        guarded = self._guard_cache.get(key)
        if guarded is None:
            guarded = _guarded_tools(func)
            self._guard_cache[key] = guarded
        return tool in guarded

    def _record(self, tool: str) -> None:
        guarded = self._current_guarded(tool)
        qual = ".".join(self._scope) or "<module>"
        signature = f"{self._relpath}::{qual}::{tool}"
        entry = self.sites.get(signature)
        if entry is None:
            self.sites[signature] = [1, guarded]
        else:
            entry[0] = int(entry[0]) + 1
            entry[1] = bool(entry[1]) or guarded


def scan_source(source: str, relpath: str = "<memory>") -> dict[str, CliSite]:
    """Scan one source string. Returns ``{signature: CliSite}``.

    ``signature`` is ``"{posix relpath}::{enclosing qualname}::{tool}"``.
    """
    visitor = _CliSiteVisitor(relpath)
    visitor.visit(ast.parse(source, filename=relpath))
    return {
        signature: CliSite(count=int(count), guarded=bool(guarded))
        for signature, (count, guarded) in visitor.sites.items()
    }


def scan_cli_sites(repo_root: Path) -> dict[str, CliSite]:
    """Scan every ``src/`` module. Returns ``{signature: CliSite}``.

    Signatures embed the posix relpath, so they are unique across files.
    """
    sites: dict[str, CliSite] = {}
    for path in quality_only_target_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        sites.update(scan_source(path.read_text(encoding="utf-8"), rel))
    return sites


def signature_tool(signature: str) -> str:
    """The CLI tool a signature targets (its trailing ``::<tool>`` field)."""
    return signature.rsplit("::", 1)[1]


def unguarded_signatures(sites: Mapping[str, CliSite]) -> dict[str, int]:
    """Signatures (with counts) whose enclosing function has no ``which`` guard."""
    return {
        signature: site.count for signature, site in sites.items() if not site.guarded
    }


def ratchet_diff(
    current: Mapping[str, int], baseline: Mapping[str, int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Compare unguarded site counts to the grandfathered baseline.

    Returns ``(new, resolved)`` — mirrors ``sandbox_seam_scan.ratchet_diff``
    / ``disturbance.baseline.diff``: ``new`` maps signature -> excess over
    baseline (guard reddens); ``resolved`` maps signature -> shortfall under
    baseline (baseline must be pruned in the same change so the ratchet only
    shrinks).
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
