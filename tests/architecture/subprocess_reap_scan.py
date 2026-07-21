"""AST enumeration of raw subprocess spawns and reap-on-cancel pairing (#9623).

Support code for the spawn-side reap guard
(``tests/architecture/test_subprocess_reap_guard.py``) and its regression
story (``tests/regressions/test_issue_9623.py``). Pure functions only — no
repo mutation, no subprocesses.

Two orthogonal scans over ``src/**/*.py``:

1. **Raw-spawn containment** (:func:`scan_raw_spawn_signatures`): every call
   site of a *live-child* spawn primitive (``asyncio.create_subprocess_exec``
   / ``create_subprocess_shell``, ``subprocess.Popen``, the ``os.spawn*`` /
   ``posix_spawn*`` family), keyed line-number-free as
   ``"{relpath}::{qualname}::{primitive}"`` with call counts — the same
   drift-immune signature shape as ``sandbox_seam_scan``. The guard confines
   these to the sanctioned reap-aware implementations
   (``HostRunner.run_simple`` / ``HostRunner.create_streaming_process`` —
   everything else must route through ``subprocess_util.run_subprocess`` /
   ``run_subprocess_result`` or ``runner_utils.stream_claude_process``).

   The synchronous run-to-completion family (``subprocess.run`` /
   ``check_output`` / …) is deliberately out of scope: those calls cannot be
   abandoned by asyncio cancellation mid-flight — they are the subject of the
   ``communicate``-timeout guards, a different failure class.

2. **Reap pairing** (:func:`scan_reap_violations`): every function whose own
   body spawns a session leader — ``create_subprocess_exec``/``_shell`` with
   literal ``start_new_session=True``, or any ``create_streaming_process``
   call not passing literal ``start_new_session=False`` (its default is
   ``True``) — must contain BOTH an ``except asyncio.CancelledError`` and an
   ``except TimeoutError`` handler, each calling the guarded primitive
   ``process_group.kill_process_group`` (directly, or via a module-local
   one-hop wrapper such as ``execution._reap_process_group`` /
   ``runner_utils._kill_proc_group``). A session leader reaped with a bare
   ``proc.kill()`` orphans every grandchild in its group — the #9648/#9553
   defect class this guard fences statically.

Scope notes (deliberate):

* Attribution is per enclosing function (nested defs are attributed to
  themselves, never their parent), so handlers and spawns must live in the
  same function scope.
* ``start_new_session`` threaded as a *variable* (the
  ``HostRunner.create_streaming_process`` factory signature) is out of reap
  scope by construction — the containment scan is what fences new raw spawn
  sites regardless of keyword shape.
* Wrapper resolution is exactly one hop deep: a module-local function whose
  own body calls ``kill_process_group`` counts as a reaper alias; deeper
  indirection must be flattened (or the site baselined) — a fixpoint walk
  would wrongly bless e.g. ``run_simple`` itself as a "reaper".
* Handlers that catch strictly wider types still count where the runtime
  semantics cover the requirement: bare ``except:`` / ``BaseException``
  catch ``CancelledError``; those plus ``Exception`` catch ``TimeoutError``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

#: Call names that create a live child process at the OS level. ``Popen`` and
#: the ``os.spawn*``/``posix_spawn*`` family are included so a regression to a
#: non-asyncio spawn cannot dodge the guard. ``os.fork``/``forkpty`` are
#: excluded on purpose: "fork" is a GitHub-domain verb in this codebase and a
#: bare fork is not a subprocess-helper concern.
RAW_SPAWN_PRIMITIVES: frozenset[str] = frozenset(
    {
        "create_subprocess_exec",
        "create_subprocess_shell",
        "Popen",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    }
)

#: The single sanctioned group-reap primitive (#10017); see
#: ``src/process_group.py`` and ``tests/architecture/test_process_group_kill_guard.py``.
REAP_PRIMITIVE = "kill_process_group"

_SESSION_SPAWNERS = frozenset({"create_subprocess_exec", "create_subprocess_shell"})
_STREAMING_FACTORY = "create_streaming_process"

# Exception-name sets that satisfy each required handler. ``CancelledError``
# derives from BaseException (3.8+), so ``except Exception`` does NOT cover
# the cancel path and is deliberately absent from _CANCEL_NAMES.
_CANCEL_NAMES = frozenset({"CancelledError", "BaseException"})
_TIMEOUT_NAMES = frozenset({"TimeoutError", "Exception", "BaseException"})

_MISSING_CANCEL = (
    "no `except asyncio.CancelledError` handler calling kill_process_group"
)
_MISSING_TIMEOUT = "no `except TimeoutError` handler calling kill_process_group"


def _callee_name(func: ast.expr) -> str | None:
    """Simple callee name for ``f(...)`` or ``mod.f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _own_nodes(root: ast.AST) -> Iterator[ast.AST]:
    """Descendants of *root* without descending into nested function scopes.

    Keeps spawns/handlers attributed to the function that owns them: a nested
    def's body belongs to the nested def (which the scoped visitors analyze
    separately), never to its parent.
    """
    stack = list(ast.iter_child_nodes(root))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            stack.extend(ast.iter_child_nodes(node))


def _src_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "src").rglob("*.py"))


# ---------------------------------------------------------------------------
# Scan 1 — raw-spawn containment
# ---------------------------------------------------------------------------


class _RawSpawnVisitor(ast.NodeVisitor):
    """Collects (enclosing qualname, primitive) for every raw spawn call."""

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
        name = _callee_name(node.func)
        if name in RAW_SPAWN_PRIMITIVES:
            qualname = ".".join(self._stack) or "<module>"
            self.hits.append((qualname, name))
        self.generic_visit(node)


def scan_raw_spawn_signatures(repo_root: Path) -> dict[str, int]:
    """``{signature: count}`` for every raw spawn call site under ``src/``.

    ``signature`` is ``"{posix relpath}::{enclosing qualname}::{primitive}"``
    — line-number-free so in-function refactors do not churn the baseline;
    counts catch a second spawn call added to an already-listed function.
    """
    counts: dict[str, int] = {}
    for path in _src_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        visitor = _RawSpawnVisitor()
        visitor.visit(ast.parse(path.read_text(), filename=rel))
        for qualname, primitive in visitor.hits:
            signature = f"{rel}::{qualname}::{primitive}"
            counts[signature] = counts.get(signature, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Scan 2 — reap pairing for session-leader spawns
# ---------------------------------------------------------------------------


def _module_reaper_names(tree: ast.Module) -> frozenset[str]:
    """``kill_process_group`` plus its module-local one-hop wrappers."""
    names = {REAP_PRIMITIVE}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
            isinstance(sub, ast.Call) and _callee_name(sub.func) == REAP_PRIMITIVE
            for sub in _own_nodes(node)
        ):
            names.add(node.name)
    return frozenset(names)


def _session_leader_spawns(fn: ast.AST) -> list[str]:
    """Primitive names of in-reap-scope spawn calls in *fn*'s own body."""
    hits: list[str] = []
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node.func)
        if name in _SESSION_SPAWNERS:
            if any(
                kw.arg == "start_new_session"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            ):
                hits.append(name)
        elif name == _STREAMING_FACTORY:
            opted_out = any(
                kw.arg == "start_new_session"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is False
                for kw in node.keywords
            )
            if not opted_out:
                hits.append(name)
    return hits


def _handler_exception_names(handler: ast.ExceptHandler) -> set[str] | None:
    """``None`` for a bare ``except:`` (catches everything); else the names."""
    if handler.type is None:
        return None
    nodes = (
        list(handler.type.elts)
        if isinstance(handler.type, ast.Tuple)
        else [handler.type]
    )
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _handler_reaps(handler: ast.ExceptHandler, reaper_names: frozenset[str]) -> bool:
    return any(
        isinstance(node, ast.Call) and _callee_name(node.func) in reaper_names
        for node in _own_nodes(handler)
    )


def _reap_deficits(fn: ast.AST, reaper_names: frozenset[str]) -> list[str]:
    cancel_ok = False
    timeout_ok = False
    for node in _own_nodes(fn):
        if not isinstance(node, ast.ExceptHandler):
            continue
        names = _handler_exception_names(node)
        catches_cancel = names is None or bool(names & _CANCEL_NAMES)
        catches_timeout = names is None or bool(names & _TIMEOUT_NAMES)
        if (catches_cancel or catches_timeout) and _handler_reaps(node, reaper_names):
            cancel_ok = cancel_ok or catches_cancel
            timeout_ok = timeout_ok or catches_timeout
    deficits: list[str] = []
    if not cancel_ok:
        deficits.append(_MISSING_CANCEL)
    if not timeout_ok:
        deficits.append(_MISSING_TIMEOUT)
    return deficits


class _ReapVisitor(ast.NodeVisitor):
    """Per-function session-leader spawn scope and handler deficits."""

    def __init__(self, reaper_names: frozenset[str]) -> None:
        self._stack: list[str] = []
        self._reapers = reaper_names
        self.in_scope: dict[str, list[str]] = {}
        self.deficits: dict[str, list[str]] = {}

    def _visit_scoped(self, node: ast.AST, name: str) -> None:
        self._stack.append(name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node, node.name)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        spawns = _session_leader_spawns(node)
        if spawns:
            qualname = ".".join([*self._stack, node.name])
            self.in_scope[qualname] = spawns
            missing = _reap_deficits(node, self._reapers)
            if missing:
                self.deficits[qualname] = missing
        self._visit_scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)


def _scan_reap(
    repo_root: Path,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    in_scope: dict[str, list[str]] = {}
    violations: dict[str, str] = {}
    for path in _src_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        tree = ast.parse(path.read_text(), filename=rel)
        visitor = _ReapVisitor(_module_reaper_names(tree))
        visitor.visit(tree)
        for qualname, spawns in visitor.in_scope.items():
            in_scope[f"{rel}::{qualname}"] = spawns
        for qualname, missing in visitor.deficits.items():
            violations[f"{rel}::{qualname}"] = "; ".join(missing)
    return in_scope, violations


def scan_reap_scope(repo_root: Path) -> dict[str, list[str]]:
    """``{"relpath::qualname": [spawn primitives]}`` for in-reap-scope fns."""
    in_scope, _violations = _scan_reap(repo_root)
    return in_scope


def scan_reap_violations(repo_root: Path) -> dict[str, str]:
    """``{"relpath::qualname": deficit description}`` for non-conforming fns."""
    _in_scope, violations = _scan_reap(repo_root)
    return violations
