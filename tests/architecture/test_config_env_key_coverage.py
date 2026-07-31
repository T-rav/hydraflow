"""Env-key coverage ratchet for ``config.declared_default_config()`` (#10859).

A naive implementation derives ``env_override_keys()`` by scanning only
``_apply_env_overrides``'s own source — and misses that ``resolve_defaults``
(the pydantic ``model_validator`` that ``HydraFlowConfig()`` runs at
construction time) has *seven* steps, not one. ``_resolve_base_paths`` reads
``HYDRAFLOW_DATA_ROOT``/``HYDRAFLOW_HOME`` directly, and
``_resolve_repo_and_identity`` reads ``HYDRAFLOW_GITHUB_REPO``,
``HYDRAFLOW_GIT_USER_NAME``/``EMAIL``, and ``GIT_AUTHOR_*``/``GIT_COMMITTER_*``
directly — none of them routed through ``_apply_env_overrides`` at all. A
suppression scheme scoped to one function in the call graph silently leaks
the others, reintroducing the exact machine-dependence #10859 exists to close.

This test walks the *whole* ``resolve_defaults`` call graph (BFS over bare-name
calls, starting from ``resolve_defaults`` itself), collects every string
literal passed as the key to ``os.environ.get``/``os.getenv``/``_get_env``/
``_dotenv_lookup`` found anywhere in that graph, and asserts each one is
either prefix-covered (``HYDRAFLOW_``/``HYDRA_``/``GIT_`` — the prefixes
``declared_default_config`` scrubs unconditionally) or explicitly named by
``config.env_override_keys()``. A new resolution step reading a genuinely
non-prefixed env var would fail this test until registered — that failure is
the point.
"""

from __future__ import annotations

import ast
import inspect
import re

import config

_ENV_KEY_LITERAL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENV_READ_QUALNAMES = frozenset(
    {"os.environ.get", "os.getenv", "_get_env", "_dotenv_lookup"}
)


def _call_qualname(node: ast.AST) -> str | None:
    """Dotted name for a bare-name or attribute-chain call target, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_qualname(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _module_function_defs() -> dict[str, ast.FunctionDef]:
    """Every function definition (at any nesting depth) in config.py, by name."""
    tree = ast.parse(inspect.getsource(config), filename=str(config.__file__))
    defs: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defs[node.name] = node
    return defs


def _env_literals_in_call(call: ast.Call) -> set[str]:
    """String-literal args that look like env var names for a matched call.

    ``_dotenv_lookup``'s first arg is ``repo_root`` (an expression, never a
    string ``Constant``), so scanning every arg is safe; the other three
    take the env var name as their sole/first positional argument.
    """
    return {
        arg.value
        for arg in call.args
        if isinstance(arg, ast.Constant)
        and isinstance(arg.value, str)
        and _ENV_KEY_LITERAL_RE.fullmatch(arg.value)
    }


def _parse_call(src: str) -> ast.Call:
    """Parse a single-expression-statement snippet and return its Call node."""
    stmt = ast.parse(src).body[0]
    assert isinstance(stmt, ast.Expr)
    call = stmt.value
    assert isinstance(call, ast.Call)
    return call


def _reachable_env_literals(start: str) -> tuple[set[str], set[str]]:
    """BFS the call graph from *start*; return (visited functions, env literals)."""
    defs = _module_function_defs()
    visited: set[str] = set()
    literals: set[str] = set()
    queue = [start]
    while queue:
        name = queue.pop()
        if name in visited or name not in defs:
            continue
        visited.add(name)
        for node in ast.walk(defs[name]):
            if not isinstance(node, ast.Call):
                continue
            qualname = _call_qualname(node.func)
            if qualname is None:
                continue
            if qualname in _ENV_READ_QUALNAMES:
                literals |= _env_literals_in_call(node)
            elif qualname in defs and qualname not in visited:
                queue.append(qualname)
    return visited, literals


class TestCallGraphDiscovery:
    """Guards the ratchet's own plumbing — if these break, the coverage
    assertion below could pass vacuously and stop meaning anything."""

    def test_reaches_every_resolve_defaults_step(self) -> None:
        visited, _literals = _reachable_env_literals("resolve_defaults")
        for step in (
            "_resolve_base_paths",
            "_resolve_repo_and_identity",
            "_resolve_repo_scoped_paths",
            "_apply_env_overrides",
            "_apply_profile_overrides",
            "_harmonize_tool_model_defaults",
            "_validate_docker",
        ):
            assert step in visited, f"BFS never reached {step!r}"

    def test_finds_literals_outside_apply_env_overrides(self) -> None:
        """Sanity check that the scan isn't accidentally scoped to just one
        function — this is exactly the gap a naive implementation reopens."""
        _visited, literals = _reachable_env_literals("resolve_defaults")
        for key in ("HYDRAFLOW_GITHUB_REPO", "GIT_AUTHOR_NAME", "HYDRAFLOW_DATA_ROOT"):
            assert key in literals

    def test_extractor_ignores_non_key_shaped_defaults(self) -> None:
        call = _parse_call('os.environ.get("HYDRAFLOW_X", "not a key")')
        assert _env_literals_in_call(call) == {"HYDRAFLOW_X"}

    def test_extractor_scans_all_dotenv_lookup_keys(self) -> None:
        call = _parse_call('_dotenv_lookup(repo_root, "HYDRAFLOW_A", "GIT_B")')
        assert _env_literals_in_call(call) == {"HYDRAFLOW_A", "GIT_B"}


def test_resolve_defaults_env_literals_are_all_covered() -> None:
    """The ratchet: every env-var literal reachable from resolve_defaults must
    be prefix-covered or explicitly present in env_override_keys()."""
    _visited, literals = _reachable_env_literals("resolve_defaults")
    declared = config.env_override_keys()
    gaps = {
        lit
        for lit in literals
        if not lit.startswith(("HYDRAFLOW_", "HYDRA_", "GIT_")) and lit not in declared
    }
    assert not gaps, (
        f"{sorted(gaps)} are read somewhere in resolve_defaults's call graph but "
        "are neither HYDRAFLOW_/HYDRA_/GIT_-prefixed nor in env_override_keys() — "
        "declared_default_config() would leak these env vars into a supposedly "
        "machine-independent config"
    )
