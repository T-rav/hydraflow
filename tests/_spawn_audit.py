"""Shared AST discovery for the WS-2.2 subprocess-spawn telemetry/credit ratchets.

``test_telemetry_source_completeness.py`` and
``test_subprocess_runner_contract_completeness.py`` both auto-discover which
``src`` modules spawn an LLM and via which mechanism, so the WS-2.2 containment
ratchets fail closed when a new spawner bypasses the telemetry/credit helpers in
``runner_utils``.

Discovery keyed on ``ast.Call`` function names (not imports — the spawn helpers
are frequently lazy-imported) with ``import ... as`` aliases resolved back to
their original names, plus ``ClassDef`` bases and a hand-rolled-agent-argv
signal (so a spawner that hand-builds a ``["claude", "-p", ...]`` argv and calls
``run_simple`` directly — bypassing ``build_lightweight_command`` — is still
caught). Modules are keyed by their path RELATIVE to ``src`` so a future
``src/<subdir>/runner_utils.py`` cannot silently inherit a top-level exemption.

Ref: ADR-0086 (telemetry/credit contract for non-central spawn paths),
``docs/wiki/dark-factory.md`` §6 (conventions made structurally enforced).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# CLI tool names that, as the first element of a list literal, mark a
# hand-built agent command line (the shape build_lightweight_command produces).
_AGENT_TOOLS: frozenset[str] = frozenset({"claude", "codex", "gemini", "pi"})


@dataclass(frozen=True)
class ModuleFacts:
    """The spawn-relevant facts extracted from one ``src`` module."""

    name: str  # bare filename, e.g. "runner_utils.py"
    rel: str  # path relative to src/ (posix), e.g. "runners/base_subprocess_runner.py"
    calls: frozenset[str]  # function/method names called (alias-resolved)
    class_bases: frozenset[str]  # base-class names of every ClassDef in the module
    has_agent_argv: bool  # contains a list literal whose first element is an agent tool


def _call_name(node: ast.Call) -> str | None:
    """Return the called name for ``foo(...)`` or ``obj.foo(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


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


def _is_agent_argv(node: ast.List) -> bool:
    """True if *node* is a list literal whose first element is an agent-tool string."""
    if not node.elts:
        return False
    first = node.elts[0]
    return isinstance(first, ast.Constant) and first.value in _AGENT_TOOLS


def iter_module_facts() -> list[ModuleFacts]:
    """Parse every ``src/**/*.py`` and return its spawn-relevant facts."""
    facts: list[ModuleFacts] = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        aliases = _alias_map(tree)
        calls: set[str] = set()
        bases: set[str] = set()
        has_agent_argv = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name:
                    calls.add(aliases.get(name, name))
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_id = getattr(base, "id", None) or getattr(base, "attr", None)
                    if base_id:
                        bases.add(base_id)
            elif isinstance(node, ast.List) and _is_agent_argv(node):
                has_agent_argv = True
        facts.append(
            ModuleFacts(
                name=path.name,
                rel=path.relative_to(SRC).as_posix(),
                calls=frozenset(calls),
                class_bases=frozenset(bases),
                has_agent_argv=has_agent_argv,
            )
        )
    return facts
