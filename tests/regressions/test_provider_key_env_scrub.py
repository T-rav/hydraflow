"""Regression: ambient provider API key envs leaked into the test session.

``tests/conftest.py::setup_test_environment`` scrubbed ``HYDRAFLOW_``/``HYDRA_``
prefixed keys, ``declared_env_keys()``, and ``CREDENTIAL_ENV_KEYS`` — but bare
(non-prefixed) provider API key envs like ``ZAI_API_KEY`` and
``ZAI_CODING_PLAN_KEY`` live in none of those sets. A developer/CI shell with
those exported (as ``Makefile``'s ``-include .env`` + ``export`` does on every
``make quality``) leaked them into every pytest session, defeating
``*_without_zai_key``-style preconditions in tests like
``test_repo_backend.py::test_noop_without_zai_key`` and
``test_llm_provider.py::TestHarnessBackend::test_resolve_harness_env_missing_key_falls_open``
— the code found a real ``ZAI_CODING_PLAN_KEY`` and rerouted/resolved a
harness env instead of no-op'ing.

Fix: ``runner_utils.provider_api_key_envs()`` derives the full provider-key
scrub surface at runtime from ``_OPENAI_COMPAT_BACKENDS`` and
``_HARNESS_BACKENDS`` (the single source of truth for which env vars a spawn
would actually read); ``setup_test_environment`` unions it into ``scrub_keys``
alongside the existing prefix/declared/credential sets.
"""

from __future__ import annotations

import os

from runner_utils import provider_api_key_envs
from subprocess_util import gateway_sensitive_env_keys


def test_provider_api_key_envs_covers_known_backend_keys() -> None:
    """The derived set must include every provider key env a real spawn can
    read today — bare and HYDRAFLOW_-prefixed, one-shot and harness lanes."""
    envs = provider_api_key_envs()
    assert envs >= {
        "ZAI_API_KEY",
        "HYDRAFLOW_ZAI_API_KEY",
        "ZAI_CODING_PLAN_KEY",
        "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
        "OPENROUTER_API_KEY",
        "HYDRAFLOW_OPENROUTER_API_KEY",
        "MOONSHOT_API_KEY",
        "KIMI_API_KEY",
        "HYDRAFLOW_KIMI_API_KEY",
    }


def test_gateway_scrub_covers_every_registered_provider_key() -> None:
    assert provider_api_key_envs() <= gateway_sensitive_env_keys()


def test_no_provider_api_key_leaks_into_a_running_test() -> None:
    """Every key provider_api_key_envs() covers must be absent from
    os.environ while a test runs, regardless of what the host/CI shell has
    exported (e.g. from a sourced .env)."""
    leaked = {key: os.environ[key] for key in provider_api_key_envs() if key in os.environ}
    assert not leaked, f"provider API key env(s) leaked into the test session: {leaked}"
