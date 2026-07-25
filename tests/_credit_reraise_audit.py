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
call to a known spawn marker inside the ``try`` body, or (b) a call to a
same-module helper (bare function, or ``self.foo()`` / ``obj.foo()`` resolved
by NAME across the whole module — no type inference) that itself reaches a
spawn, computed as a fixed point over the module's local call graph. This
deliberately over-approximates: a same-named helper on an unrelated class can
cause a false positive, but a spawn reached only through ANOTHER module
(e.g. a callback handed to a cross-module orchestrator) is invisible to it.
Prefer the over-approximation — grandfather any false positive rather than
narrow the heuristic and risk missing a real swallow site.

Ref: ADR-0055 (telemetry/credit contract for spawn paths),
``docs/wiki/dark-factory.md`` §2.2, ``src/exception_classify.py``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

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


def _if_is_isinstance_credit_auth_guard(if_stmt: ast.If) -> bool:
    """True for `if isinstance(exc, (AuthenticationError, CreditExhaustedError)): raise`."""
    test = if_stmt.test
    return (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(if_stmt.body) == 1
        and isinstance(if_stmt.body[0], ast.Raise)
    )


def _handler_reraises_as_first_action(handler: ast.ExceptHandler) -> bool:
    """True if *handler*'s first statement reraises credit/auth (or everything)."""
    if not handler.body:
        return False
    first = handler.body[0]
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


def find_unprotected_credit_swallows(tree: ast.Module) -> list[UnprotectedSwallow]:
    """Return every ``try`` in *tree* that reaches an LLM spawn and can swallow credit."""
    aliases = _alias_map(tree)
    funcs_by_name = _collect_functions(tree)
    reaches_map = _build_reaches_spawn_map(funcs_by_name, aliases)
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


def find_violations_in_source(source: str) -> list[UnprotectedSwallow]:
    """Parse *source* and return its unprotected-credit-swallow ``try`` blocks."""
    return find_unprotected_credit_swallows(ast.parse(source))


def find_violations_in_file(path: Path) -> list[UnprotectedSwallow]:
    return find_violations_in_source(path.read_text())


def iter_supervised_loop_files() -> list[Path]:
    """Every top-level ``src/*_loop.py`` — the ``BaseBackgroundLoop`` convention."""
    return sorted(SRC.glob("*_loop.py"))
