"""Shared AST analysis for the WS-2.2 loop-layer credit-reraise ratchet (#9101).

``test_loop_credit_reraise_completeness.py`` uses this module to prove a
STRUCTURAL property that the existing WS-2.2 containment ratchets
(``test_telemetry_source_completeness.py``,
``test_subprocess_runner_contract_completeness.py``) cannot: not just that a
spawn module *contains* a credit detector, but that a credit/auth signal
raised by an LLM spawn actually *reaches* ``BaseBackgroundLoop``'s pause
handler instead of being re-swallowed by a broad ``except`` one layer up in
the supervised ``*_loop.py`` itself.

``CreditExhaustedError`` and ``AuthenticationError`` both subclass
``RuntimeError`` (``src/subprocess_util.py``), so ANY ``except Exception`` /
``except RuntimeError`` / ``except (..., RuntimeError)`` guarding a call path
that reaches an LLM spawn is a potential swallow site. It is safe (does NOT
swallow) only if one of the following holds:

1. its first action calls ``exception_classify.reraise_on_credit_or_bug(exc)``
   (the documented convention, ``docs/wiki/dark-factory.md`` §2.2), or
2. its first action unconditionally re-raises (bare ``raise``, or
   ``raise CreditExhaustedError``/``raise AuthenticationError``), or
3. an earlier, narrower handler on the SAME ``try`` already intercepts
   ``AuthenticationError``/``CreditExhaustedError`` with a bare ``raise`` —
   Python matches ``except`` clauses in order, so the broad handler below it
   never sees those two types (the ``base_background_loop.py`` /
   ``term_proposer_loop.py`` / ``entry_evidence_loop.py`` pattern).

SCOPE OF THE GUARANTEE: this is a *structural* ratchet over an AST heuristic,
not a type checker. "Reaches an LLM spawn" is resolved two ways: (a) a direct
call to a known spawn marker inside the ``try`` body, or (b) a call to a helper
(bare function, or ``self.foo()`` / ``obj.foo()`` resolved by NAME — no type
inference) that itself reaches a spawn, computed as a fixed point over a call
graph. This deliberately over-approximates: a same-named helper on an unrelated
class can cause a false positive, but a spawn reached only through a module
OUTSIDE the loop (e.g. a callback handed to a cross-module orchestrator) is
invisible to it. Prefer the over-approximation — grandfather any false positive
rather than narrow the heuristic and risk missing a real swallow site.

UNIT OF ANALYSIS — THE LOOP, NOT THE FILE (#11666): the call graph spans every
source file of a loop, not one file at a time. A per-file graph is correct only
while a loop is exactly one module. The moment a loop is decomposed into a
package, a ``try`` in ``foo_loop/_a.py`` wrapping ``self._helper()`` whose
spawn-reaching body lives in the sibling ``foo_loop/_b.py`` resolves to "does
not reach a spawn" and the ratchet silently stays green — the gate narrows at
exactly the moment the code it guards gets harder to read. #11665 fixed the
same class of hole in *discovery* (``loop_source_files`` replacing
``SRC.glob("*_loop.py")``); this fixes it in *resolution*. Sibling modules are
unioned into one scope per loop unit, which also covers the package's re-export
surface by construction: a helper is in the union no matter how ``__init__.py``
re-exports it. Where a file's own imports disagree with a sibling's alias for
the same name, the file's own imports win.

Ref: ADR-0055 (telemetry/credit contract for spawn paths),
``docs/wiki/dark-factory.md`` §2.2, ``src/exception_classify.py``.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.loop_module_scan import loop_source_files, loop_sources, loop_units

SRC = Path(__file__).resolve().parent.parent / "src"

# Spawn primitives that ALWAYS indicate an LLM subprocess spawn regardless of
# their arguments.
_UNAMBIGUOUS_SPAWN_MARKERS = frozenset(
    {
        "stream_claude_process",
        "build_lightweight_command",
        "run_lightweight_agent",
        "stream_claude_with_telemetry",
    }
)

# `run_simple` is used for BOTH agent spawns and plain subprocess calls (git,
# gh, ...). Only treat it as a spawn marker when paired with a hand-built
# agent argv in the same scope (mirrors tests/_spawn_audit.py's
# `has_agent_argv` heuristic) — otherwise every git-calling loop would be a
# false positive.
_AGENT_TOOLS = frozenset({"claude", "codex"})

_RERAISE_HELPER = "reraise_on_credit_or_bug"
_CREDIT_AUTH_NAMES = frozenset({"CreditExhaustedError", "AuthenticationError"})
_BROAD_EXCEPT_NAMES = frozenset({"Exception", "BaseException", "RuntimeError"})


@dataclass(frozen=True)
class UnprotectedSwallow:
    """One ``try`` block that reaches an LLM spawn without reraising credit/auth."""

    try_lineno: int
    handler_lineno: int


def _alias_map(tree: ast.Module) -> dict[str, str]:
    """Map ``import ... as X`` local names back to their original symbol."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name.split(".")[-1]
    return aliases


def _call_name(node: ast.Call, aliases: dict[str, str]) -> str | None:
    """Return the called name for ``foo(...)`` or ``obj.foo(...)``, alias-resolved."""
    func = node.func
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_self_llm_call(node: ast.Call) -> bool:
    """True for ``self._llm.<anything>(...)`` — the injected-LLM-port spawn shape."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    val = func.value
    return (
        isinstance(val, ast.Attribute)
        and val.attr == "_llm"
        and isinstance(val.value, ast.Name)
        and val.value.id == "self"
    )


def _is_runner_ctor(node: ast.Call) -> bool:
    """True for ``SomeRunner(...)`` — every ``*Runner`` class in src spawns an agent."""
    return isinstance(node.func, ast.Name) and node.func.id.endswith("Runner")


def _is_agent_argv(node: ast.List) -> bool:
    if not node.elts:
        return False
    first = node.elts[0]
    return isinstance(first, ast.Constant) and first.value in _AGENT_TOOLS


def _has_agent_argv(node: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.List) and _is_agent_argv(sub) for sub in ast.walk(node)
    )


def _is_spawn_call(node: ast.Call, aliases: dict[str, str], has_argv: bool) -> bool:
    name = _call_name(node, aliases)
    if name in _UNAMBIGUOUS_SPAWN_MARKERS:
        return True
    if name == "run_simple" and has_argv:
        return True
    return _is_self_llm_call(node) or _is_runner_ctor(node)


def _collect_functions(tree: ast.Module) -> dict[str, list[ast.AST]]:
    """Map bare function/method name -> every def with that name in the module."""
    funcs: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            funcs.setdefault(node.name, []).append(node)
    return funcs


def _calls_in(node: ast.AST, aliases: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = _call_name(sub, aliases)
            if name:
                names.add(name)
    return names


def _direct_markers(node: ast.AST, aliases: dict[str, str]) -> bool:
    has_argv = _has_agent_argv(node)
    return any(
        isinstance(sub, ast.Call) and _is_spawn_call(sub, aliases, has_argv)
        for sub in ast.walk(node)
    )


def _build_reaches_spawn_map(
    funcs_by_name: dict[str, list[ast.AST]], aliases: dict[str, str]
) -> dict[str, bool]:
    """Fixed-point: does calling a function named X (eventually) reach a spawn?"""
    direct = {
        name: any(_direct_markers(n, aliases) for n in nodes)
        for name, nodes in funcs_by_name.items()
    }
    calls = {
        name: set().union(*(_calls_in(n, aliases) for n in nodes))
        for name, nodes in funcs_by_name.items()
    }
    reaches = dict(direct)
    changed = True
    while changed:
        changed = False
        for name in funcs_by_name:
            if reaches[name]:
                continue
            if any(callee != name and reaches.get(callee) for callee in calls[name]):
                reaches[name] = True
                changed = True
    return reaches


def _body_reaches_spawn(
    stmts: list[ast.stmt], aliases: dict[str, str], reaches_map: dict[str, bool]
) -> bool:
    has_argv = any(_has_agent_argv(s) for s in stmts)
    for stmt in stmts:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                if _is_spawn_call(sub, aliases, has_argv):
                    return True
                name = _call_name(sub, aliases)
                if name and reaches_map.get(name):
                    return True
    return False


def _handler_type_names(handler: ast.ExceptHandler) -> list[str]:
    t = handler.type
    if t is None:
        return ["<bare>"]
    if isinstance(t, ast.Tuple):
        names = []
        for elt in t.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                names.append(elt.attr)
        return names
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, ast.Attribute):
        return [t.attr]
    return ["<unknown>"]


def _is_broad(names: list[str]) -> bool:
    return "<bare>" in names or bool(set(names) & _BROAD_EXCEPT_NAMES)


def _is_narrow_credit_auth(names: list[str]) -> bool:
    return bool(names) and set(names) <= _CREDIT_AUTH_NAMES


def _raise_reraises_credit_or_bug(raise_stmt: ast.Raise) -> bool:
    """True for bare `raise` or `raise CreditExhaustedError`/`AuthenticationError`."""
    exc = raise_stmt.exc
    if exc is None:
        return True  # bare `raise` — unconditionally re-raises, never swallows
    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
        return exc.func.id in _CREDIT_AUTH_NAMES
    return isinstance(exc, ast.Name) and exc.id in _CREDIT_AUTH_NAMES


def _expr_calls_reraise_helper(expr: ast.Expr) -> bool:
    """True for a bare `reraise_on_credit_or_bug(exc)` expression statement."""
    if not isinstance(expr.value, ast.Call):
        return False
    func = expr.value.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name == _RERAISE_HELPER


def _isinstance_type_names(node: ast.expr) -> list[str]:
    """Flatten ``A``, ``(A, B)`` and ``A | B`` into their type names."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        return [name for elt in node.elts for name in _isinstance_type_names(elt)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _isinstance_type_names(node.left) + _isinstance_type_names(node.right)
    return []


def _if_is_isinstance_credit_auth_guard(if_stmt: ast.If) -> bool:
    """True for `if isinstance(exc, (AuthenticationError, CreditExhaustedError)): raise`.

    Both the TYPES and the bareness of the ``raise`` are checked. Accepting any
    ``if isinstance(...): raise`` shape — the previous behaviour — let a handler
    that re-raises some UNRELATED type read as protected while still swallowing
    credit on every path where the check is false. Harmless while this audit
    only covered the loop layer; a real hole now that it covers all of ``src/``
    (#11664 fresh-eyes review finding).

    Accepts the tuple and PEP 604 (``A | B``) spellings, both of which are live
    in ``src/`` (``diagnostic_loop.py``, ``post_merge_handler.py``).
    """
    test = if_stmt.test
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == 2
        and len(if_stmt.body) == 1
    ):
        return False
    body = if_stmt.body[0]
    if not (isinstance(body, ast.Raise) and body.exc is None):
        return False
    # Must cover BOTH fatal types — re-raising only one still swallows the other.
    return set(_isinstance_type_names(test.args[1])) >= _CREDIT_AUTH_NAMES


def _significant_body(handler: ast.ExceptHandler) -> list[ast.stmt]:
    """*handler*'s body with leading ``import`` statements dropped.

    An import cannot swallow an exception, so a guard sitting behind one is
    still the handler's first ACTION. ``docker_runner.py`` imports
    ``reraise_on_credit_or_bug`` inside the handler to dodge a module cycle;
    treating the import as the first action reported it as unprotected when it
    is not.
    """
    body = list(handler.body)
    index = 0
    while index < len(body) and isinstance(body[index], ast.Import | ast.ImportFrom):
        index += 1
    return body[index:]


def _body_always_reraises(body: list[ast.stmt]) -> bool:
    """True if *body* ends in a bare ``raise`` it cannot exit before reaching.

    ``except Exception: <cleanup>; raise`` never swallows anything, but
    demanding the ``raise`` be the FIRST statement reported ``base_runner.py``'s
    trace-finalizing handler — which re-raises unconditionally after one
    cleanup branch — as a violation.

    Deliberately conservative: any ``return``/``break``/``continue`` anywhere in
    the body means some path does NOT reach the ``raise``, so the handler is
    only accepted without them. Nested ``def``s are not exempted from that
    scan; over-approximating toward "unprotected" is the documented preference.
    """
    if not body:
        return False
    last = body[-1]
    if not (isinstance(last, ast.Raise) and last.exc is None):
        return False
    return not any(
        isinstance(sub, ast.Return | ast.Break | ast.Continue)
        for stmt in body
        for sub in ast.walk(stmt)
    )


def _handler_reraises_as_first_action(handler: ast.ExceptHandler) -> bool:
    """True if *handler* reraises credit/auth (or everything) rather than swallowing."""
    body = _significant_body(handler)
    if not body:
        return False
    if _body_always_reraises(body):
        return True
    first = body[0]
    if isinstance(first, ast.Raise):
        return _raise_reraises_credit_or_bug(first)
    if isinstance(first, ast.Expr):
        return _expr_calls_reraise_helper(first)
    if isinstance(first, ast.If):
        return _if_is_isinstance_credit_auth_guard(first)
    return False


def _try_swallows_credit(node: ast.Try) -> bool:
    """True if *node* has an unprotected broad handler (credit/auth can leak through)."""
    intercepted_by_narrow_handler = False
    for handler in node.handlers:
        names = _handler_type_names(handler)
        if _is_narrow_credit_auth(names):
            if (
                handler.body
                and isinstance(handler.body[0], ast.Raise)
                and handler.body[0].exc is None
            ):
                intercepted_by_narrow_handler = True
            continue
        if _is_broad(names):
            if intercepted_by_narrow_handler:
                continue
            if not _handler_reraises_as_first_action(handler):
                return True
    return False


def _union_scope(
    trees: Sequence[ast.Module],
) -> tuple[dict[str, str], dict[str, list[ast.AST]]]:
    """Merge *trees* into one alias map and one name -> defs map.

    This is what makes resolution package-aware (#11666): a helper defined in a
    sibling module of the same loop lands in the same ``funcs_by_name`` bucket
    as a helper defined locally, so the fixed point in
    ``_build_reaches_spawn_map`` crosses module boundaries within the loop.
    """
    aliases: dict[str, str] = {}
    funcs_by_name: dict[str, list[ast.AST]] = {}
    for tree in trees:
        aliases.update(_alias_map(tree))
        for name, nodes in _collect_functions(tree).items():
            funcs_by_name.setdefault(name, []).extend(nodes)
    return aliases, funcs_by_name


def find_unprotected_credit_swallows(
    tree: ast.Module, *, siblings: Sequence[ast.Module] = ()
) -> list[UnprotectedSwallow]:
    """Return every ``try`` in *tree* that reaches an LLM spawn and can swallow credit.

    *siblings* are the other modules of the same loop unit. They contribute
    their helpers to the call graph but their own ``try`` blocks are NOT
    reported here — each file is reported against its own path so a violation
    points at the file that must be edited.
    """
    scope_aliases, funcs_by_name = _union_scope([tree, *siblings])
    reaches_map = _build_reaches_spawn_map(funcs_by_name, scope_aliases)
    # The file's own imports win over a sibling's alias for the same name.
    aliases = {**scope_aliases, **_alias_map(tree)}
    violations: list[UnprotectedSwallow] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Try)
            and _body_reaches_spawn(node.body, aliases, reaches_map)
            and _try_swallows_credit(node)
        ):
            broad_handler = next(
                h
                for h in node.handlers
                if _is_broad(_handler_type_names(h))
                and not _handler_reraises_as_first_action(h)
            )
            violations.append(
                UnprotectedSwallow(
                    try_lineno=node.lineno, handler_lineno=broad_handler.lineno
                )
            )
    return violations


def find_violations_in_source(
    source: str, *, sibling_sources: Sequence[str] = ()
) -> list[UnprotectedSwallow]:
    """Parse *source* and return its unprotected-credit-swallow ``try`` blocks.

    *sibling_sources* stand in for the other modules of the same loop package.
    """
    return find_unprotected_credit_swallows(
        ast.parse(source), siblings=[ast.parse(s) for s in sibling_sources]
    )


def find_violations_in_file(path: Path) -> list[UnprotectedSwallow]:
    """Violations in *path* alone — no sibling context.

    Correct only for a single-module loop. For anything that might be a
    package, go through :func:`find_violations_in_unit`, which supplies the
    sibling modules the call graph needs.
    """
    return find_violations_in_source(path.read_text(encoding="utf-8"))


def find_violations_in_unit(unit: Path) -> dict[Path, list[UnprotectedSwallow]]:
    """Violations in *unit*, resolved against the WHOLE loop's call graph.

    *unit* is a ``*_loop.py`` file or a ``*_loop/`` package directory, as
    returned by ``loop_module_scan.loop_units``. Returns ``{path: violations}``
    for the files that have any — keyed by the individual file, so the failure
    message points at what to edit, while resolution used every sibling.
    """
    trees: dict[Path, ast.Module] = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in loop_sources(unit)
    }
    found: dict[Path, list[UnprotectedSwallow]] = {}
    for path, tree in trees.items():
        siblings = [t for p, t in trees.items() if p != path]
        violations = find_unprotected_credit_swallows(tree, siblings=siblings)
        if violations:
            found[path] = violations
    return found


def iter_supervised_loop_units() -> list[Path]:
    """Every background loop as a UNIT — a ``*_loop.py`` or a ``*_loop/`` package.

    The right granularity to iterate for this audit: resolution must see a
    whole loop at once (#11666). Pair with :func:`find_violations_in_unit`.
    """
    return loop_units(SRC)


def iter_src_units() -> list[Path]:
    """Every module in ``src/`` as a UNIT — a top-level ``.py`` or a package dir.

    The loop layer is where a swallowed credit error is most costly, but it is
    not the only place one can hide. Running the audit over all of ``src/``
    (first done in the #11664/#11666 sweep) found the transcript-summary chain:
    ``TranscriptSummarizer.summarize_and_comment`` swallowed everything and
    returned ``False``, and all five of its phase callers re-swallowed on top.
    Nothing in the loop layer could see it.
    """
    units: list[Path] = []
    for path in sorted(SRC.iterdir()):
        if path.is_dir() and (path / "__init__.py").is_file() or path.suffix == ".py":
            units.append(path)
    return units


def iter_supervised_loop_files() -> list[Path]:
    """Every source file of every background loop — module OR package, flattened.

    A bare ``src.glob("*_loop.py")`` stops seeing a loop the moment it is
    decomposed into a package, and this audit would then pass over the very
    ``except Exception`` blocks it exists to check. ``loop_source_files``
    flattens both shapes; see ``tests/loop_module_scan.py``.

    Prefer :func:`iter_supervised_loop_units` for anything that then resolves
    calls: iterating FILES is what narrowed the call graph in the first place.
    """
    return loop_source_files(SRC)
