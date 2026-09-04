"""#11991 AC4 — credit failover still reroutes once the dials live in policy.

The other four acceptance criteria are covered: parity over the generated dial
set (`test_routing_baseline_generator`), the reversible round-trip
(`test_routing_migration_roundtrip`), maintenance-provider inheritance pinned
before the legacy path moved (#12123), and the MockWorld scenario
(`tests/scenarios/test_dial_migration_scenario.py`). This is the one that was
not.

It matters for the reason the issue gives, which is #11853: *"a dial that stops
being read does not raise; it just stops steering, and the spawn routes to a
default that looks reasonable."* `apply_credit_failover` was correct there and
simply never called. Migration is exactly the event that could sever a caller
from it — the dials it reads move into policy, and nothing about the rewrite
itself would fail loudly if the failover seam stopped being reached.

So the property under test is not "the failover function works". It is that a
capped Anthropic-lane spawn is still rerouted **after** the migration has run,
and still rerouted after the down-path has put the dials back — because the
migration is reversible and a caller can be severed by either direction.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import credit_failover  # noqa: E402
from config import HydraFlowConfig  # noqa: E402
from credit_failover import apply_credit_failover  # noqa: E402
from hydraflow_gateway.routing_workspace import PolicyWorkspace  # noqa: E402
from routing_migration import (  # noqa: E402
    down_path_mutation,
    migrate_dials_to_policy,
)

_REPO = "acme/hydraflow"
_ACTOR = "migration-operator"
_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
_GLM = "glm-5.2"
_CAPPED_CMD = ["claude", "--model", "claude-opus-4-8", "-p", "work"]


@pytest.fixture(autouse=True)
def _capped_with_a_reachable_zai_lane(monkeypatch: pytest.MonkeyPatch):
    """Claude capped, and z.ai reachable on both lanes.

    Both credentials because the lanes need different things (#12131): a direct
    `claude` spawn addresses z.ai itself and needs `ZAI_API_KEY`; a `gateway`
    spawn needs the PROXY to have a z.ai upstream to mint against. Arming one
    would leave the other testing a failover that legitimately declines, and
    the test would then be asserting the wrong reason for the right answer.
    """
    monkeypatch.setenv("ZAI_API_KEY", "ac4-not-a-real-credential")
    monkeypatch.setenv("GATEWAY_ZAI_HARNESS_BASE_URL", "https://zai.invalid")
    monkeypatch.setenv("GATEWAY_ZAI_HARNESS_API_KEY", "ac4-not-a-real-credential")
    credit_failover.reset_for_tests()
    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=60)
    yield
    credit_failover.reset_for_tests()


@pytest.fixture
def config() -> HydraFlowConfig:
    """One moved dial — the same smallest config the round-trip test uses."""
    return HydraFlowConfig(repo=_REPO, planner_provider="zai", planner_model=_GLM)


@pytest.fixture
def workspace(tmp_path: Path) -> PolicyWorkspace:
    return PolicyWorkspace(tmp_path / "routing", repo=_REPO)


def _reroutes(provider: str, config: HydraFlowConfig) -> bool:
    """Whether a capped spawn on *provider* is moved off the Anthropic lane."""
    resolved, cmd = apply_credit_failover(provider, _CAPPED_CMD, config)
    return resolved != "claude" or _GLM in cmd


def test_a_capped_spawn_reroutes_before_the_migration(
    config: HydraFlowConfig,
) -> None:
    """The starting point, asserted rather than assumed.

    Without it, "still reroutes after migrating" could be true of a build where
    failover never worked in the first place — the assertion would pass for the
    wrong reason and this file would be measuring nothing.
    """
    assert _reroutes("claude", config)


def test_a_capped_spawn_still_reroutes_after_the_migration(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """AC4. The dials now live in policy; the capped caller must still be moved.

    This is the #11853 shape: severing the failover seam does not raise, it
    routes to a default that looks reasonable, and the only symptom is spend on
    a provider that is already capped.
    """
    migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    assert _reroutes("claude", config), (
        "a capped Claude spawn stopped rerouting once the dials moved into "
        "policy — the failover seam is no longer reached (#11853)"
    )


def test_a_capped_gateway_spawn_still_reroutes_after_the_migration(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """The other lane. ADR-0147 put every dial on the gateway by default, so
    this is the path most spawns actually take, and it fails over by rewriting
    the model while keeping the transport rather than by changing provider."""
    migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    provider, cmd = apply_credit_failover("gateway", _CAPPED_CMD, config)

    assert provider == "gateway"
    assert _GLM in cmd, "a capped gateway spawn kept its Claude model after migrating"


def test_a_capped_spawn_still_reroutes_after_the_down_path(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """Reversibility cuts both ways.

    AC2 makes the migration undoable, which means a caller can be severed by
    the reverse as easily as by the forward direction. A round-trip that
    restores the policy set but leaves failover unreachable would satisfy AC2's
    tests and still strand a capped factory.
    """
    result = migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)
    workspace.apply(down_path_mutation(result), actor=_ACTOR, now=_NOW)

    assert _reroutes("claude", config)


def test_an_uncapped_spawn_is_untouched_after_the_migration(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """The decoy. Every assertion above is satisfied by a build that rewrites
    every spawn to GLM unconditionally — which would be a far worse bug than
    the one they guard, and invisible to them."""
    migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)
    credit_failover.reset_for_tests()

    assert apply_credit_failover("claude", _CAPPED_CMD, config) == (
        "claude",
        _CAPPED_CMD,
    )
