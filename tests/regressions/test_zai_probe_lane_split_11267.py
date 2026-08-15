"""Regression pin for the #11267 key-split probe rule.

With `ZAI_CODING_PLAN_KEY` set, agentic CLI spawns bill the coding plan
while the one-shot REST lane stays on `ZAI_API_KEY`. The credit-pause
corroboration probe (`backend_probe_endpoint`) must follow the credential
the failing lane actually bills: probing the REST key against a plan-quota
exhaustion reports "credits available", the signal is discarded as a false
positive, and the loop retry-storms the still-capped plan — the
#9895/#10558 class the probe exists to prevent.
"""

from __future__ import annotations

from runner_utils import backend_probe_endpoint
from tests.helpers import ConfigFactory

_ALL_KEYS = (
    "ZAI_CODING_PLAN_KEY",
    "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
    "ZAI_API_KEY",
    "HYDRAFLOW_ZAI_API_KEY",
)


def test_probe_follows_the_plan_key_when_lanes_diverge(monkeypatch) -> None:
    for env in _ALL_KEYS:
        monkeypatch.delenv(env, raising=False)
    config = ConfigFactory.create()
    monkeypatch.setenv("ZAI_API_KEY", "sk-api")
    monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "sk-plan")

    base_url, key = backend_probe_endpoint("zai", config)
    assert key == "sk-plan"
    assert base_url == config.zai_harness_base_url


def test_probe_keeps_rest_pair_for_single_key_setups(monkeypatch) -> None:
    for env in _ALL_KEYS:
        monkeypatch.delenv(env, raising=False)
    config = ConfigFactory.create()
    monkeypatch.setenv("ZAI_API_KEY", "sk-api")

    base_url, key = backend_probe_endpoint("zai", config)
    assert key == "sk-api"
    assert base_url == config.zai_base_url
