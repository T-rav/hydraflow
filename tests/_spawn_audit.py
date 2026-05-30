"""Shared AST discovery for the WS-2.2 subprocess-spawn telemetry/credit ratchets.

``test_telemetry_source_completeness.py`` and
``test_subprocess_runner_contract_completeness.py`` both auto-discover which
``src`` modules spawn an LLM and via which mechanism, so the WS-2.2 containment
ratchets fail closed when a new spawner bypasses the telemetry/credit helpers in
``runner_utils``. Keyed on ``ast.Call`` function names (not imports — the
spawn helpers are frequently lazy-imported) and ``ClassDef`` bases.

Ref: ADR-0086 (telemetry/credit contract for non-central spawn paths),
``docs/wiki/dark-factory.md`` §6 (conventions made structurally enforced).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


@dataclass(frozen=True)
class ModuleFacts:
    """The spawn-relevant facts extracted from one ``src`` module."""

    name: str  # bare filename, e.g. "runner_utils.py"
    rel: str  # path relative to src/ (posix), e.g. "runners/base_subprocess_runner.py"
    calls: frozenset[str]  # every function/method name called (ast.Call func name)
    class_bases: frozenset[str]  # base-class names of every ClassDef in the module


def _call_name(node: ast.Call) -> str | None:
    """Return the called name for ``foo(...)`` or ``obj.foo(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def iter_module_facts() -> list[ModuleFacts]:
    """Parse every ``src/**/*.py`` and return its spawn-relevant facts."""
    facts: list[ModuleFacts] = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        calls: set[str] = set()
        bases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name:
                    calls.add(name)
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_id = getattr(base, "id", None) or getattr(base, "attr", None)
                    if base_id:
                        bases.add(base_id)
        facts.append(
            ModuleFacts(
                name=path.name,
                rel=path.relative_to(SRC).as_posix(),
                calls=frozenset(calls),
                class_bases=frozenset(bases),
            )
        )
    return facts
