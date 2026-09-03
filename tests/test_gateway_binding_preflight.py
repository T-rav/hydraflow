"""The boot preflight for a gateway-routed factory (ADR-0147).

ADR-0147 points the role dials at the gateway, which makes the ability to mint
a virtual key a prerequisite for spawning at all. `resolve_harness_env` raises
at the point of use, once per spawn; this preflight names the gap once at boot.

The scope is the thing under test. An earlier revision demanded the gateway's
own upstream credentials (`GATEWAY_ANTHROPIC_*`) from the FACTORY's
environment. Those belong to the gateway server -- `GATEWAY_CONTROL_PLANE_ENV_KEYS`
exists to keep them out of this process -- so it reported a gap on every
correctly-configured deployment running the gateway as its own service.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import (  # noqa: E402
    HydraFlowConfig,
    gateway_binding_gaps,
    reset_gateway_binding_warnings,
    warn_once_on_gateway_binding_gaps,
)
from gateway_control_reader import GATEWAY_CONTROL_TOKEN_ENV  # noqa: E402

#: Every role dial pointed off the gateway, so `routed` is driven only by what
#: the individual test sets. Derived from the model so a new dial joins here.
_ALL_DIRECT = {
    n: "claude" for n in HydraFlowConfig.model_fields if n.endswith("_provider")
}


@pytest.fixture(autouse=True)
def _forget_prior_warnings() -> None:
    reset_gateway_binding_warnings()


def _direct_config(**overrides: object) -> HydraFlowConfig:
    return HydraFlowConfig(repo="o/r", **{**_ALL_DIRECT, **overrides})


def test_a_gateway_routed_factory_without_a_control_token_names_it() -> None:
    """The gap an operator can act on, by name."""
    config = HydraFlowConfig(repo="o/r")

    assert gateway_binding_gaps(config, env={}) == [GATEWAY_CONTROL_TOKEN_ENV]


def test_a_bound_factory_reports_no_gap() -> None:
    config = HydraFlowConfig(repo="o/r")

    assert gateway_binding_gaps(config, env={GATEWAY_CONTROL_TOKEN_ENV: "tok"}) == []


def test_the_gateways_own_upstream_credentials_are_not_demanded_here() -> None:
    """Regression: the check must not fire on the supported topology.

    The gateway runs as its own service with its own environment. A factory
    holding only its control token is correctly configured, and this returning
    a gap for `GATEWAY_ANTHROPIC_API_KEY` made every such boot look broken.
    """
    config = HydraFlowConfig(repo="o/r")

    gaps = gateway_binding_gaps(config, env={GATEWAY_CONTROL_TOKEN_ENV: "tok"})

    assert not any(gap.startswith("GATEWAY_ANTHROPIC") for gap in gaps)


def test_a_factory_on_no_gateway_dial_is_not_asked_for_a_token() -> None:
    """Decoy: the check discriminates instead of always firing.

    Without this, hardcoding `return [GATEWAY_CONTROL_TOKEN_ENV]` satisfies
    the assertions above.
    """
    assert gateway_binding_gaps(_direct_config(), env={}) == []


def test_a_single_gateway_dial_is_enough_to_require_the_token() -> None:
    """Routing is per-dial: one role on the gateway still needs a mint."""
    config = _direct_config(triage_provider="gateway")

    assert gateway_binding_gaps(config, env={}) == [GATEWAY_CONTROL_TOKEN_ENV]


#: Models pinned to a backend of their own, which cannot be moved to Codex.
_NON_CODEX_MODELS = frozenset(
    {"scheduling_model", "repo_model", "credit_failover_model"}
)


def _all_codex_config(**overrides: object) -> HydraFlowConfig:
    """A deployment running Codex everywhere, so every defaulted dial demotes.

    `_demote_defaulted_gateway_for_non_claude_tools` sends a dial back to the
    direct harness when its stage runs a tool the gateway cannot serve. Built
    from the model rather than a literal list so a new tool/model pair joins.
    """
    fields = HydraFlowConfig.model_fields
    kwargs: dict[str, object] = {n: "codex" for n in fields if n.endswith("_tool")}
    kwargs.update(
        {
            n: "gpt-5"
            for n in fields
            if n.endswith("_model") and n not in _NON_CODEX_MODELS
        }
    )
    kwargs["model"] = "gpt-5"
    return HydraFlowConfig(repo="o/r", **{**kwargs, **overrides})


def test_a_fully_demoted_deployment_is_not_warned_at_boot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ordering: the check reads dials AFTER they have settled.

    It used to run inside `_resolve_repo_and_identity`, one line BEFORE
    `_apply_env_overrides` and well before the harmonisation pass that demotes
    a defaulted `gateway` dial whose tool the gateway cannot serve. A Codex
    deployment therefore got a boot warning naming a credential it will never
    need -- and a warning that is wrong for a working deployment is how
    operators learn to skip boot warnings.

    `repo_provider` is pinned off the gateway because it is NOT demoted: its
    glm-* model is one the gateway can serve, through the zai-harness upstream.
    """
    monkeypatch.delenv(GATEWAY_CONTROL_TOKEN_ENV, raising=False)

    with caplog.at_level(logging.WARNING):
        config = _all_codex_config(repo_provider="zai")

    assert [
        n
        for n in HydraFlowConfig.model_fields
        if n.endswith("_provider") and getattr(config, n) == "gateway"
    ] == []
    assert GATEWAY_CONTROL_TOKEN_ENV not in caplog.text


def test_one_dial_left_on_the_gateway_still_warns_at_boot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Positive control for the test above.

    Identical config except `repo_provider` keeps its gateway default. Without
    this pair, a preflight that had been deleted outright would look correct.
    """
    monkeypatch.delenv(GATEWAY_CONTROL_TOKEN_ENV, raising=False)

    with caplog.at_level(logging.WARNING):
        config = _all_codex_config()

    assert config.repo_provider == "gateway"
    assert GATEWAY_CONTROL_TOKEN_ENV in caplog.text


def test_the_gap_is_reported_once_not_once_per_construction(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`HydraFlowConfig()` is built on nearly every code path."""
    monkeypatch.delenv(GATEWAY_CONTROL_TOKEN_ENV, raising=False)
    config = HydraFlowConfig(repo="o/r")

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            warn_once_on_gateway_binding_gaps(config)

    assert caplog.text.count(GATEWAY_CONTROL_TOKEN_ENV) == 1


def test_a_different_gap_appearing_later_is_still_reported(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Keyed on the gap, not a bare 'already warned' flag."""
    monkeypatch.delenv(GATEWAY_CONTROL_TOKEN_ENV, raising=False)
    warn_once_on_gateway_binding_gaps(HydraFlowConfig(repo="o/r"))

    with caplog.at_level(logging.WARNING):
        widened = HydraFlowConfig(repo="o/r")
        object.__setattr__(widened, "gateway_base_url", "")
        warn_once_on_gateway_binding_gaps(widened)

    assert "HYDRAFLOW_GATEWAY_BASE_URL" in caplog.text
