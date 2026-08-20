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
caught). It also identifies modules that combine an agent argv with raw
``subprocess.run`` so synchronous side-channel spawns cannot evade the same
ratchets. Modules are keyed by their path RELATIVE to ``src`` so a future
``src/<subdir>/runner_utils.py`` cannot silently inherit a top-level exemption.

Ref: ADR-0055 (OpenTelemetry Instrumentation as the Telemetry Layer — the
telemetry/credit contract for spawn paths: ``stream_claude_process`` spans +
``reraise_on_credit_or_bug`` credit/exception classification),
``docs/wiki/dark-factory.md`` §6 (conventions made structurally enforced).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# CLI tool names that, as the first element of a list literal, mark a
# hand-built agent command line (the shape build_lightweight_command produces).
_AGENT_TOOLS: frozenset[str] = frozenset({"claude", "codex"})


@dataclass(frozen=True)
class ModuleFacts:
    """The spawn-relevant facts extracted from one ``src`` module."""

    name: str  # bare filename, e.g. "runner_utils.py"
    rel: str  # path relative to src/ (posix), e.g. "runners/base_subprocess_runner.py"
    calls: frozenset[str]  # function/method names called (alias-resolved)
    class_bases: frozenset[str]  # base-class names of every ClassDef in the module
    has_agent_argv: bool  # contains a list literal whose first element is an agent tool
    has_agent_inference_argv: bool  # agent argv that initiates an inference
    has_raw_subprocess_run: bool  # calls subprocess.run (including import aliases)


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


def _is_agent_inference_argv(node: ast.List) -> bool:
    """Exclude management commands such as ``claude plugin install``."""

    if not _is_agent_argv(node):
        return False
    first = node.elts[0]
    assert isinstance(first, ast.Constant)
    if first.value == "codex":
        return True
    return any(
        isinstance(element, ast.Constant) and element.value in {"-p", "--prompt"}
        for element in node.elts[1:]
    )


def _subprocess_symbols(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Return local names for the subprocess module and imported ``run``."""

    module_names: set[str] = set()
    run_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    module_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name == "run":
                    run_names.add(alias.asname or alias.name)
    return module_names, run_names


def _is_raw_subprocess_run(
    node: ast.Call, *, module_names: set[str], run_names: set[str]
) -> bool:
    """Return whether *node* invokes the synchronous subprocess primitive."""

    func = node.func
    if isinstance(func, ast.Name):
        return func.id in run_names
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "run"
        and isinstance(func.value, ast.Name)
        and func.value.id in module_names
    )


def iter_module_facts() -> list[ModuleFacts]:
    """Parse every ``src/**/*.py`` and return its spawn-relevant facts."""
    facts: list[ModuleFacts] = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        aliases = _alias_map(tree)
        subprocess_modules, subprocess_runs = _subprocess_symbols(tree)
        calls: set[str] = set()
        bases: set[str] = set()
        has_agent_argv = False
        has_agent_inference_argv = False
        has_raw_subprocess_run = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if name:
                    calls.add(aliases.get(name, name))
                if _is_raw_subprocess_run(
                    node,
                    module_names=subprocess_modules,
                    run_names=subprocess_runs,
                ):
                    has_raw_subprocess_run = True
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_id = getattr(base, "id", None) or getattr(base, "attr", None)
                    if base_id:
                        bases.add(base_id)
            elif isinstance(node, ast.List) and _is_agent_argv(node):
                has_agent_argv = True
                has_agent_inference_argv = (
                    has_agent_inference_argv or _is_agent_inference_argv(node)
                )
        facts.append(
            ModuleFacts(
                name=path.name,
                rel=path.relative_to(SRC).as_posix(),
                calls=frozenset(calls),
                class_bases=frozenset(bases),
                has_agent_argv=has_agent_argv,
                has_agent_inference_argv=has_agent_inference_argv,
                has_raw_subprocess_run=has_raw_subprocess_run,
            )
        )
    return facts
