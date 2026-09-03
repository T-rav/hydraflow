"""Scenario: under a Claude credit cap, NO caller addresses the dead provider.

This is the layer that was missing when #11853 shipped, and the one that would
have caught it. `apply_credit_failover` had unit tests and was correct; the
defect was that `run_lightweight_agent` never called it. A unit test of the
helper cannot see that — only exercising the real lightweight path can.

Measured cost of the gap (2026-08-31, ~7.5h after the cap engaged at 06:15):

    434  Loop 'issue_refinement' crashed - claude signaled credit exhaustion
    283  Loop 'plan' crashed - claude signaled credit exhaustion
    141  credit-failover: rerouting claude spawn to zai/glm-5.2   <- base_runner, worked
      5  Wiki compilation model failed (rc=-1: timed out after 300s)

The factory split in half: work spawns rerouted and kept completing, while
every lightweight caller pinned to `claude` burned a full 300s timeout per
call. Both wiki-breaker trips that night were downstream of this.

The scenario asserts the property that matters for credit waste: **with failover
engaged, the resolved transport for a claude-pinned lightweight call is the
failover provider, and the model moves with it.** The zai backend only accepts
`glm-*`, so a provider that moved without its model would trade a timeout for a
rejection — no better.
"""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

import credit_failover
import runner_utils
from credit_failover import ANTHROPIC_LANE_PROVIDERS
from prompt_telemetry import parse_command_tool_model
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario


@pytest.fixture
def capped(monkeypatch: pytest.MonkeyPatch):
    """Claude credits exhausted, a z.ai credential present — failover armed."""
    monkeypatch.setenv("ZAI_API_KEY", "test-key-not-a-real-credential")
    credit_failover.reset_for_tests()
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=60)
    yield
    credit_failover.reset_for_tests()


def _spawn_capture() -> tuple[MagicMock, list[dict]]:
    """A runner that records what it was asked to spawn and returns success."""
    seen: list[dict] = []

    async def _run(*args, **kwargs):
        seen.append({"args": args, "kwargs": kwargs})
        return MagicMock(returncode=0, stdout="{}", stderr="")

    runner = MagicMock()
    runner.run = AsyncMock(side_effect=_run)
    return runner, seen


@pytest.mark.asyncio
async def test_a_lightweight_call_does_not_address_the_capped_provider(
    capped,
) -> None:
    """The #11853 property, through the real seam.

    Asserted on the provider the LIGHTWEIGHT PATH resolves, not on
    `apply_credit_failover`'s return value: the helper was already correct
    while the factory was burning timeouts, so re-testing it proves nothing
    about this path. `_telemetry_cmd` is the first thing called with the
    resolved transport, which makes it the observation point.

    The call is allowed to fail downstream on fakes — resolution happens
    before any spawn, and that is the whole assertion.
    """
    config = ConfigFactory.create()
    resolved: list[str] = []
    real_cmd = runner_utils._telemetry_cmd

    def _capture(provider: str, tool: str, model: str):
        resolved.append(provider)
        return real_cmd(provider, tool, model)

    runner, _seen = _spawn_capture()
    # The spawn is allowed to fail on fakes; resolution happens before it, and
    # resolution is the whole assertion. suppress() rather than try/except/pass
    # so the intent is explicit and ruff SIM105 stays satisfied.
    with (
        patch.object(runner_utils, "_telemetry_cmd", side_effect=_capture),
        contextlib.suppress(Exception),
    ):
        await runner_utils.run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="haiku",
            provider="claude",
            prompt="x",
            source="scenario",
            timeout=1,
            gh_token="",
        )

    assert resolved, "the provider was never resolved — the seam did not run"
    assert resolved[-1] != "claude", (
        f"a lightweight call still addressed the capped provider: {resolved}"
    )
    assert resolved[-1] == "zai", f"expected the failover transport, got {resolved}"


def test_the_model_moves_with_the_provider(capped) -> None:
    """The zai backend only accepts glm-*.

    Rerouting the provider while still requesting `haiku` would trade a 300s
    timeout for an immediate rejection — a different failure, not a fix.
    """
    config = ConfigFactory.create()
    provider, cmd = credit_failover.apply_credit_failover(
        "claude", runner_utils._telemetry_cmd("claude", "claude", "haiku"), config
    )
    _tool, model = parse_command_tool_model(cmd)
    assert provider == "zai"
    assert model == config.credit_failover_model
    assert model != "haiku"


def test_nothing_reroutes_when_no_cap_is_engaged(monkeypatch) -> None:
    """The guard that keeps this inert in normal operation.

    Without this the scenario above could pass against a change that rerouted
    unconditionally, which would send every call to GLM at full price.
    """
    monkeypatch.setenv("ZAI_API_KEY", "test-key-not-a-real-credential")
    credit_failover.reset_for_tests()
    config = ConfigFactory.create()
    provider, cmd = credit_failover.apply_credit_failover(
        "claude", runner_utils._telemetry_cmd("claude", "claude", "haiku"), config
    )
    assert provider == "claude"
    assert parse_command_tool_model(cmd)[1] == "haiku"


def test_every_anthropic_lane_role_dial_is_covered_by_the_failover(capped) -> None:
    """The blast radius, by reference rather than by a copied list.

    Role dials default onto the Anthropic lane -- `claude` before ADR-0147,
    `gateway` after -- and each one was dead for the duration of a cap. Derived
    from config.py so a NEW role dial landing on that lane is caught here; a
    hand-written list could never notice one.

    Each dial is exercised with ITS OWN default as the provider. Feeding a
    hardcoded "claude" for every name, as this did before ADR-0147, makes the
    loop body independent of the dial and re-asserts a single case N times --
    it would keep passing with every dial moved off the lane.

    The two lanes fail over differently: a direct `claude` spawn changes
    provider to `zai`, while a `gateway` spawn keeps its transport (the proxy
    mints a z.ai-bound virtual key) and moves only its model. The property that
    holds for both, and the one credit waste actually turns on, is that the
    spawn stops addressing an Anthropic model.
    """
    import re

    src = (Path(runner_utils.__file__).parent / "config.py").read_text("utf-8")
    dials = dict(
        re.findall(
            r'(\w+_provider): Literal\[[^\]]*\] = (?:\(\s*)?Field\(\s*default="(\w+)"',
            src,
        )
    )
    at_risk = {
        name: default
        for name, default in dials.items()
        if default in ANTHROPIC_LANE_PROVIDERS
    }
    assert len(at_risk) >= 10, "extraction found too few dials to be meaningful"

    config = ConfigFactory.create()
    for name, default in at_risk.items():
        provider, cmd = credit_failover.apply_credit_failover(
            default,
            runner_utils._telemetry_cmd(default, "claude", "haiku"),
            config,
        )
        assert provider != "claude", f"{name} still addresses the capped CLI"
        assert parse_command_tool_model(cmd)[1] == config.credit_failover_model, (
            f"{name} moved provider without its model"
        )


def test_a_dial_off_the_anthropic_lane_is_left_alone(capped) -> None:
    """Decoy: the failover must not conscript a dial already off the lane.

    Pins that the sweep above discriminates. A failover that rewrote every
    provider unconditionally would satisfy it while breaking z.ai-pinned dials.
    """
    provider, cmd = credit_failover.apply_credit_failover(
        "zai",
        runner_utils._telemetry_cmd("zai", "zai", "glm-4.6"),
        config=ConfigFactory.create(),
    )

    assert provider == "zai"
    assert parse_command_tool_model(cmd)[1] == "glm-4.6"
