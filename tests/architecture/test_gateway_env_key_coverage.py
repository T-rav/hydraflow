"""Env-key coverage ratchet for ``GATEWAY_CONTROL_PLANE_ENV_KEYS`` (#11540).

``subprocess_util.GATEWAY_CONTROL_PLANE_ENV_KEYS`` is a hand-maintained copy of
what ``GatewaySettings.from_env`` actually reads, and
``scrub_gateway_spawn_env`` strips it from every routed worker's environment so
a worker can never inherit a real provider or admin credential.  Nothing kept
the two in sync: a review of PR #11653 found ``GATEWAY_GOVERNED_REPOS`` had
simply been left out, which is a silent credential-adjacent leak rather than a
loud failure — exactly the class of defect a hand-maintained duplicate produces.

This test AST-parses ``src/hydraflow_gateway/settings.py``, walks the body of
``GatewaySettings.from_env``, and collects every ``GATEWAY_``-shaped string
*literal* handed to one of the environment readers (``env.get``, ``_required``,
``_positive_int``, ``_non_negative_int``, ``_optional_path``, ``_add_upstream``)
— reading source, never importing and executing, so the guard needs no
environment and cannot be satisfied by a happens-to-be-set variable.  It then
asserts that set is a subset of the scrub registry.

``_add_upstream`` is in the reader set alongside the five direct readers because
it takes its two variable *names* as keyword arguments; leaving it out would let
a third provider pair (``GATEWAY_OPENAI_BASE_URL``/``_API_KEY``) be added
without the guard noticing, which is the same hole one lane down.

The non-vacuity tests are the load-bearing half.  An extractor that quietly
returns an empty set turns the subset assertion into a tautology that passes
forever and protects nothing, so the collector's own reach is asserted first.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import subprocess_util

_SETTINGS_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "hydraflow_gateway" / "settings.py"
)
_GATEWAY_KEY_RE = re.compile(r"^GATEWAY_[A-Z0-9_]+$")
_ENV_READ_TARGETS = frozenset(
    {
        "env.get",
        "_required",
        "_positive_int",
        "_non_negative_int",
        "_optional_path",
        "_add_upstream",
    }
)
_MINIMUM_KEYS_READ = 10


def _call_qualname(node: ast.AST) -> str | None:
    """Dotted name for a bare-name or attribute-chain call target, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_qualname(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _from_env_node(source: str) -> ast.FunctionDef:
    """The ``GatewaySettings.from_env`` definition parsed out of *source*."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "from_env":
            return node
    raise AssertionError("GatewaySettings.from_env not found in the parsed source")


def _gateway_env_literals(source: str) -> frozenset[str]:
    """Every ``GATEWAY_*`` literal read by ``from_env`` in *source*.

    Both positional and keyword arguments are scanned: the direct readers take
    the variable name positionally, ``_add_upstream`` takes it as
    ``base_url_name=``/``api_key_name=``.  Scanning every argument is safe
    because the ``GATEWAY_`` shape filter excludes the default *values* that
    share those calls (``".hydraflow/gateway/bodies"``, ``86_400``).
    """
    literals: set[str] = set()
    for node in ast.walk(_from_env_node(source)):
        if not isinstance(node, ast.Call):
            continue
        if _call_qualname(node.func) not in _ENV_READ_TARGETS:
            continue
        arguments = list(node.args) + [keyword.value for keyword in node.keywords]
        literals |= {
            argument.value
            for argument in arguments
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and _GATEWAY_KEY_RE.fullmatch(argument.value)
        }
    return frozenset(literals)


def _keys_read_by_from_env() -> frozenset[str]:
    """The live extraction against the real settings module."""
    return _gateway_env_literals(_SETTINGS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("reader", "key"),
    [
        ("_required", "GATEWAY_CONTROL_TOKEN"),
        ("env.get", "GATEWAY_GOVERNED_REPOS"),
        ("_optional_path", "GATEWAY_ACCOUNTS_FILE"),
        ("_non_negative_int", "GATEWAY_MAX_FALLBACK_HOPS"),
        ("_positive_int", "GATEWAY_MAX_KEY_TTL_SECONDS"),
        ("_add_upstream", "GATEWAY_ANTHROPIC_API_KEY"),
    ],
    ids=[
        "required",
        "env-get",
        "optional-path",
        "non-negative-int",
        "positive-int",
        "add-upstream",
    ],
)
def test_collector_reaches_every_reader_form(reader: str, key: str) -> None:
    """Non-vacuity: each reader form in from_env is actually seen by the scan."""
    assert key in _keys_read_by_from_env(), (
        f"the extractor missed {key!r}, which GatewaySettings.from_env reads via "
        f"{reader} — the coverage assertion below is only as good as this scan"
    )


def test_collector_is_not_vacuous() -> None:
    """Non-vacuity: an extractor returning ~nothing would pass forever."""
    keys = _keys_read_by_from_env()
    assert len(keys) >= _MINIMUM_KEYS_READ, (
        f"only {len(keys)} GATEWAY_* keys extracted from "
        f"GatewaySettings.from_env ({sorted(keys)}) — expected at least "
        f"{_MINIMUM_KEYS_READ}. The extractor has stopped matching the source; "
        "fix _ENV_READ_TARGETS/_gateway_env_literals before trusting this file"
    )


def test_collector_ignores_literals_that_are_not_read_keys() -> None:
    """Default values and unrelated calls must not inflate the extraction."""
    source = (
        "class GatewaySettings:\n"
        "    @classmethod\n"
        "    def from_env(cls, env):\n"
        '        a = env.get("GATEWAY_REAL_KEY", "GATEWAY_not_a_key_lowercase")\n'
        '        b = _required(env, "GATEWAY_ALSO_REAL")\n'
        '        c = log.info("GATEWAY_MENTIONED_IN_PROSE")\n'
        "        return a, b, c\n"
    )
    assert _gateway_env_literals(source) == {"GATEWAY_REAL_KEY", "GATEWAY_ALSO_REAL"}


def test_every_gateway_key_from_env_reads_is_scrubbed_from_workers() -> None:
    """The ratchet: from_env's GATEWAY_* contract is a subset of the scrub set."""
    missing = _keys_read_by_from_env() - subprocess_util.GATEWAY_CONTROL_PLANE_ENV_KEYS
    assert not missing, (
        f"{sorted(missing)} are read by GatewaySettings.from_env but are absent "
        "from GATEWAY_CONTROL_PLANE_ENV_KEYS — add it to "
        "GATEWAY_CONTROL_PLANE_ENV_KEYS in src/subprocess_util.py, or a routed "
        "worker will inherit it"
    )
