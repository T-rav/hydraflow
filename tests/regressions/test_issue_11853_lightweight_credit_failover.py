"""Regression (#11853): the lightweight path must honour credit failover.

`apply_credit_failover` lived only in `base_runner` (#10844). `run_lightweight_agent`
never called it, so a Claude credit cap split the factory in half:

    work spawns (base_runner)      -> rerouted to zai/glm, work completes
    lightweight calls (this path)  -> keep addressing the dead provider

Measured 2026-08-31, over ~7.5h after the cap engaged at 06:15:

    434  Loop 'issue_refinement' crashed - claude CLI signaled credit exhaustion
    283  Loop 'plan' crashed - claude CLI signaled credit exhaustion
    141  credit-failover: rerouting claude spawn to zai/glm-5.2   <- the half that worked
      5  Wiki compilation model failed (rc=-1: timed out after 300s)

The wiki breaker opening twice (#11819) was a symptom of this, not a wiki bug:
`wiki_compilation_provider` defaulted to `claude`, so every compile call went to
the capped provider and burned its full 300s. ADR-0147 moved that default to
`gateway`, which reaches the same upstream -- the exposure moved transport, it
did not go away.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

import credit_failover
from credit_failover import ANTHROPIC_LANE_PROVIDERS
import runner_utils
from prompt_telemetry import parse_command_tool_model


def _provider_defaults() -> dict[str, str]:
    """Every ``*_provider`` setting and its default, DERIVED from config.py.

    Deliberately not a hand-copied list: a new role dial added with a `claude`
    default is exactly the regression this file exists to catch, and a literal
    list cannot notice one (docs/standards/parametrised_guards/).
    """
    src = (Path(runner_utils.__file__).parent / "config.py").read_text("utf-8")
    return dict(
        re.findall(
            r'(\w+_provider): Literal\[[^\]]*\] = (?:\(\s*)?Field\(\s*default="(\w+)"',
            src,
        )
    )


def test_the_provider_sweep_is_not_empty() -> None:
    """Anti-vacuity floor: every parametrised assertion below is trivially true
    against an empty set, so pin that the extraction actually found dials."""
    assert len(_provider_defaults()) >= 10


def test_anthropic_lane_dials_exist_and_are_the_population_at_risk() -> None:
    """Documents WHY this matters: most role dials default to the capped lane."""
    at_risk = [
        n for n, d in _provider_defaults().items() if d in ANTHROPIC_LANE_PROVIDERS
    ]
    assert "wiki_compilation_provider" in at_risk
    assert len(at_risk) >= 10


def test_a_dial_off_the_anthropic_lane_is_not_counted_as_at_risk() -> None:
    """Decoy: keeps the population above from degenerating into 'every dial'.

    Without this, widening ANTHROPIC_LANE_PROVIDERS to cover everything would
    still satisfy the count assertion and the guard would stop discriminating.
    """
    assert "zai" not in ANTHROPIC_LANE_PROVIDERS
    assert "openrouter" not in ANTHROPIC_LANE_PROVIDERS


@pytest.fixture
def _capped(monkeypatch: pytest.MonkeyPatch):
    """Failover engaged with a z.ai credential present."""
    monkeypatch.setenv("ZAI_API_KEY", "test-key-not-a-real-credential")
    credit_failover.reset_for_tests()
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=60)
    yield
    credit_failover.reset_for_tests()


def test_lightweight_call_is_rerouted_while_capped(_capped, config) -> None:
    """The fix: a claude-pinned lightweight call resolves to zai."""
    provider, cmd = credit_failover.apply_credit_failover(
        "claude", runner_utils._telemetry_cmd("claude", "claude", "haiku"), config
    )
    assert provider == "zai"


def test_the_model_moves_with_the_provider(_capped, config) -> None:
    """The zai backend only accepts glm-*. Rerouting the provider while still
    asking for `haiku` would trade a timeout for a rejection — no better."""
    _, cmd = credit_failover.apply_credit_failover(
        "claude", runner_utils._telemetry_cmd("claude", "claude", "haiku"), config
    )
    _, model = parse_command_tool_model(cmd)
    assert model == config.credit_failover_model
    assert model != "haiku"


def test_no_reroute_when_nothing_is_capped(config, monkeypatch) -> None:
    """The guard that makes this safe in normal operation."""
    monkeypatch.setenv("ZAI_API_KEY", "test-key-not-a-real-credential")
    credit_failover.reset_for_tests()
    provider, cmd = credit_failover.apply_credit_failover(
        "claude", runner_utils._telemetry_cmd("claude", "claude", "haiku"), config
    )
    assert provider == "claude"
    assert parse_command_tool_model(cmd)[1] == "haiku"


def _lightweight_body() -> str:
    """Source of `run_lightweight_agent`, bounded by the next top-level def OR EOF.

    It is currently the last `async def` in the module, so slicing on a
    following one raises ValueError — a brittleness that would read as a test
    failure rather than a fixture bug.
    """
    src = Path(runner_utils.__file__).read_text("utf-8")
    start = src.index("async def run_lightweight_agent")
    rest = src[start + 10 :]
    nxt = min(
        (i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1),
        default=-1,
    )
    return rest if nxt == -1 else rest[:nxt]


def test_run_lightweight_agent_actually_calls_the_failover() -> None:
    """The WIRING, not the helper.

    `apply_credit_failover` was already correct and already tested — the defect
    was that this path never invoked it. A test of the helper alone would have
    stayed green through the entire outage.
    """
    assert "apply_credit_failover(" in _lightweight_body(), (
        "run_lightweight_agent does not call apply_credit_failover — the #11853 defect"
    )


def test_reroute_reassigns_the_transport_not_just_a_local() -> None:
    """A call whose result is discarded looks identical to a fix.

    Pins that the rerouted provider is assigned back to `transport_provider`,
    which is what the backend selection below actually reads.
    """
    assert "transport_provider = failover_provider" in _lightweight_body()
