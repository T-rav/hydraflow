"""Regression pins for the #11302 env-hermeticity class.

Class: tests and native spawn paths were not hermetic against real
provider credentials in the host environment — a live checkout's shell
carrying ZAI_CODING_PLAN_KEY / ANTHROPIC_BASE_URL broke 'no key' tests
under make quality (#11317, #11368) and silently rerouted/billed native
Claude spawns against the wrong lane (#11316).

Pins:
1. make_clean_env strips the redirect quartet (ZAI pair + ANTHROPIC
   BASE_URL/AUTH_TOKEN) — native spawns are pristine.
2. ANTHROPIC_API_KEY survives — it is a legitimate native auth path.
3. The harness lane is unaffected: resolve_harness_env still injects the
   backend pair explicitly per-spawn (failover cannot break).
4. The test environment itself is hermetic (the conftest autouse fixture
   deleted any host values before this test ran).
"""

from __future__ import annotations

import os

import pytest

from subprocess_util import make_clean_env


def test_make_clean_env_strips_redirect_quartet(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "zk-test")
    monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "zp-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "at-test")
    env = make_clean_env()
    for key in (
        "ZAI_API_KEY",
        "ZAI_CODING_PLAN_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        assert key not in env


def test_make_clean_env_keeps_native_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-native")
    assert make_clean_env().get("ANTHROPIC_API_KEY") == "sk-native"


@pytest.mark.asyncio
async def test_harness_lane_still_injects_backend_pair(monkeypatch) -> None:
    from config import HydraFlowConfig
    from runner_utils import resolve_harness_env

    monkeypatch.setenv("ZAI_CODING_PLAN_KEY", "zp-test")
    env = await resolve_harness_env("zai", HydraFlowConfig())
    assert env.get("ANTHROPIC_AUTH_TOKEN") == "zp-test"
    assert env.get("ANTHROPIC_BASE_URL")


def test_test_environment_is_hermetic() -> None:
    """The conftest autouse fixture stripped host credentials before us."""
    for key in (
        "ZAI_API_KEY",
        "ZAI_CODING_PLAN_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        assert key not in os.environ
