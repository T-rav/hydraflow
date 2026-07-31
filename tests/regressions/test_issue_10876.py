"""Regression: conftest env isolation missed non-prefixed config env keys.

``tests/conftest.py::setup_test_environment`` only scrubbed ``os.environ``
keys prefixed ``HYDRAFLOW_``/``HYDRA_`` plus a fixed ``GIT_*`` list; module
scope additionally popped ``SENTRY_DSN``. But ``src/config.py``'s override
tables also declare non-prefixed keys — e.g. ``sentry_org`` reads
``SENTRY_ORG`` (``_ENV_STR_OVERRIDES``), ``otel_environment`` reads ``HF_ENV``.
A developer or CI runner with ``SENTRY_ORG``/``HF_ENV``/etc. exported (as this
very sandbox does, from a sourced ``.env``) therefore leaked host
configuration into every ``HydraFlowConfig`` built during the test session —
observed live while investigating #10859, where ``sentry_org`` resolved to a
real org value instead of the declared default.

The same fixture also independently clobbered ``HYDRAFLOW_SENTRY_DISABLED``:
``tests/conftest.py`` sets it at import time, but the old ``HYDRAFLOW_*``
prefix-pop swept it up and never re-seeded it, so the Sentry kill switch was
off for the whole session.

Fix: ``config.declared_env_keys()`` (#10876) derives the full scrub set from
the override tables at runtime; ``setup_test_environment`` scrubs the union
of that set with the prefix rule and a fixed GIT/credential-fallback list,
and seeds ``HYDRAFLOW_SENTRY_DISABLED`` in ``test_env`` so it survives.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import config as config_module
from config import declared_env_keys

# Non-prefixed env keys read directly in src/config.py OUTSIDE any
# _ENV_*_OVERRIDES table (credential/identity fallbacks read by
# build_credentials() and the GIT-identity resolver). declared_env_keys()
# deliberately does not cover these — they are scrubbed/seeded by conftest's
# fixed GIT_*/GH_TOKEN handling instead of the table-derived scrub set.
_EXEMPT_DIRECT_READ_KEYS = frozenset(
    {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "SENTRY_AUTH_TOKEN",
    }
)


def test_no_declared_key_leaks_into_a_running_test() -> None:
    """Every key declared_env_keys() covers must be absent from os.environ
    while a test runs, except HYDRAFLOW_SENTRY_DISABLED — the one declared
    key the fixture deliberately seeds (it's also a HYDRAFLOW_* key, so the
    belt-and-braces prefix rule would otherwise sweep it up as well)."""
    leaked = {
        key: os.environ[key]
        for key in declared_env_keys()
        if key in os.environ and key != "HYDRAFLOW_SENTRY_DISABLED"
    }
    assert not leaked, f"declared config env key(s) leaked into the test session: {leaked}"


def test_sentry_kill_switch_survives_the_sweep() -> None:
    """HYDRAFLOW_SENTRY_DISABLED is set at conftest import time (module
    scope); it must still read '1' inside a running test. Before the fix,
    the HYDRAFLOW_* prefix-pop removed it and nothing re-seeded it."""
    assert os.environ.get("HYDRAFLOW_SENTRY_DISABLED") == "1"


def test_sentry_dsn_absent_during_test_session() -> None:
    assert os.environ.get("SENTRY_DSN") is None


def test_sentry_auth_token_absent_during_test_session() -> None:
    assert os.environ.get("SENTRY_AUTH_TOKEN") is None


def test_git_author_name_resolves_to_deterministic_test_identity() -> None:
    """GIT_AUTHOR_NAME must be the fixture's seeded value, not whatever the
    host/CI runner's ambient git identity happens to be."""
    assert os.environ.get("GIT_AUTHOR_NAME") == "HydraFlow Test"


# ---------------------------------------------------------------------------
# Drift guard: a future non-prefixed env key added to src/config.py must be
# swept up automatically by declared_env_keys(), or explicitly exempted here.
# ---------------------------------------------------------------------------


def _literal_env_keys_read_in_config() -> set[str]:
    """AST-scan src/config.py for string-literal env-var keys passed to
    ``os.environ.get(...)``, ``os.environ[...]``, or ``_get_env(...)`` —
    anchored to those three call/subscript shapes (not a bare uppercase-word
    regex) so the guard can't false-positive on unrelated string literals."""
    source_path = Path(inspect.getfile(config_module))
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    keys: set[str] = set()

    def _string_const(node: ast.AST) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_environ_get = (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
            )
            is_get_env = isinstance(func, ast.Name) and func.id == "_get_env"
            if (is_environ_get or is_get_env) and node.args:
                key = _string_const(node.args[0])
                if key is not None:
                    keys.add(key)
        elif isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "environ":
                key = _string_const(node.slice)
                if key is not None:
                    keys.add(key)
    return keys


def test_drift_guard_every_non_prefixed_literal_key_is_declared_or_exempt() -> None:
    non_prefixed = {
        key
        for key in _literal_env_keys_read_in_config()
        if not key.startswith(("HYDRAFLOW_", "HYDRA_"))
    }
    unlisted = non_prefixed - declared_env_keys() - _EXEMPT_DIRECT_READ_KEYS
    assert not unlisted, (
        "Non-prefixed env key(s) read in src/config.py are neither covered by "
        f"declared_env_keys() nor the documented exemption set: {sorted(unlisted)}"
    )


def test_exemption_set_is_scrubbed_or_seeded_by_conftest() -> None:
    """Every key the drift guard exempts must actually be neutralised by the
    fixture some other way — either absent during the session or pinned to a
    deterministic seeded value — so the exemption can't quietly reopen the
    same leak this issue closes."""
    seeded = {
        "GH_TOKEN": "test-token",
        "GIT_AUTHOR_NAME": "HydraFlow Test",
        "GIT_AUTHOR_EMAIL": "test@hydraflow.local",
        "GIT_COMMITTER_NAME": "HydraFlow Test",
        "GIT_COMMITTER_EMAIL": "test@hydraflow.local",
    }
    for key in _EXEMPT_DIRECT_READ_KEYS:
        if key in seeded:
            assert os.environ.get(key) == seeded[key], key
        else:
            assert os.environ.get(key) is None, key
