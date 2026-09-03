"""#11992: a governed repo may not configure a face around the gateway.

The epic has three gauges for "no governed direct-provider bypass": the
architecture gate refuses it in the source (#11987), the runtime gauge counts
it after the fact (#11999), and this refuses the CONFIGURATION that would
produce one — where the mistake is still free to fix.

This criterion stalled on an objection that turned out to be false: that the
`*_provider` dials are global while a provider lock is per-repository. Each
registered repo gets its own `HydraFlowConfig` from `load_runtime_config` (see
`RepoRuntime`), so the check is per-repo and cannot force `gateway` on a host
that merely shares a process with a locked repo. The last case below is that
property.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402

_PROVIDER_DIALS = tuple(
    sorted(n for n in HydraFlowConfig.model_fields if n.endswith("_provider"))
)
_GOVERNED = "acme/hydraflow"


def _all_gateway() -> dict[str, str]:
    return dict.fromkeys(_PROVIDER_DIALS, "gateway")


def _governed(**overrides: object) -> dict[str, object]:
    """A canary config that has already satisfied the fleet-ratchet clause.

    The ratchet is checked before the dials, because a repo without it has
    ungoverned faces no dial can name. These fixtures turn it on so the dial
    assertions reach the dial check rather than stopping short of it.
    """
    return {
        "repo": _GOVERNED,
        "gateway_enforcement_canary_repo": _GOVERNED,
        "gateway_fleet_ratchet_enabled": True,
        "execution_mode": "docker",
        **overrides,
    }


def test_the_dial_set_is_derived_and_non_empty() -> None:
    """Anti-vacuity: an empty set would make every assertion below pass."""
    assert len(_PROVIDER_DIALS) >= 14
    assert "maintenance_provider" in _PROVIDER_DIALS


class TestAGovernedRepoMustRouteEveryFaceThroughTheGateway:
    def test_a_direct_face_is_refused_at_load(self) -> None:
        # The direct face is set EXPLICITLY. ADR-0147 made `gateway` the dial
        # default, so `_governed()` alone no longer produces a violation — and
        # a test that relied on the default would have started asserting
        # nothing while still passing.
        with pytest.raises(ValueError, match="must resolve through the gateway"):
            HydraFlowConfig(**_governed(maintenance_provider="claude"))

    def test_the_refusal_names_the_offending_face(self) -> None:
        """ "Something is ungoverned" is not something an operator can act on."""
        with pytest.raises(ValueError) as caught:
            HydraFlowConfig(
                **_governed(**{**_all_gateway(), "review_provider": "claude"})
            )

        assert "review_provider='claude'" in str(caught.value)

    def test_all_faces_on_the_gateway_loads(self) -> None:
        config = HydraFlowConfig(**_governed(**_all_gateway()))

        assert config.maintenance_provider == "gateway"


class TestTheGateIsScopedToTheGovernedRepo:
    """Non-conscription, asserted as a property rather than as a default.

    These once read `== "claude"`, which was the DEFAULT standing in for "this
    repo was not forced". ADR-0147 made `gateway` the default, so that spelling
    would now pass for the wrong reason on a conscripted config. Each case sets
    a direct dial explicitly and asserts the gate LEFT IT ALONE — the property
    the objection was actually about.
    """

    def test_an_unarmed_deployment_is_untouched(self) -> None:
        config = HydraFlowConfig(repo="acme/other", maintenance_provider="claude")

        assert config.maintenance_provider == "claude"

    def test_another_repo_is_not_forced_onto_the_gateway(self) -> None:
        """The objection that stalled this criterion, asserted as a property.

        A canary armed for one repository must not conscript every other
        repository the host serves — they are separate configs.
        """
        config = HydraFlowConfig(
            repo="acme/other",
            gateway_enforcement_canary_repo=_GOVERNED,
            maintenance_provider="claude",
        )

        assert config.maintenance_provider == "claude"

    def test_a_repo_with_no_identity_is_not_judged(self) -> None:
        """Without a canonical repo there is nothing to compare the lock to."""
        config = HydraFlowConfig(
            gateway_enforcement_canary_repo=_GOVERNED, maintenance_provider="claude"
        )

        assert config.maintenance_provider == "claude"


class TestAGovernedRepoNeedsTheFleetRatchet:
    """Dials are only half the faces (#11992).

    Twenty of twenty-four `BaseRunner` subclasses declare no `PROVIDER_FIELD`,
    so `_resolve_provider` returns a hardcoded "claude" — bug_reproducer, hitl,
    research, discover, shape, plan_reviewer, diagnostic. No `*_provider`
    setting can move them. The fleet ratchet is the only thing that rewrites a
    still-claude spawn to "gateway".

    The first version of this gate checked the dials alone, so a canary with
    every dial on "gateway" and the ratchet off passed while seven runners went
    straight to Anthropic — an ungoverned face no configuration named, which is
    what the gate exists to refuse.
    """

    def test_every_dial_on_the_gateway_is_not_enough(self) -> None:
        with pytest.raises(ValueError, match="gateway_fleet_ratchet_enabled"):
            HydraFlowConfig(
                repo=_GOVERNED,
                gateway_enforcement_canary_repo=_GOVERNED,
                **_all_gateway(),
            )

    def test_the_refusal_says_why_the_dials_are_insufficient(self) -> None:
        with pytest.raises(ValueError) as caught:
            HydraFlowConfig(
                repo=_GOVERNED,
                gateway_enforcement_canary_repo=_GOVERNED,
                **_all_gateway(),
            )

        assert "declare no provider dial" in str(caught.value)

    def test_the_ratchet_plus_every_dial_loads(self) -> None:
        config = HydraFlowConfig(
            repo=_GOVERNED,
            gateway_enforcement_canary_repo=_GOVERNED,
            gateway_fleet_ratchet_enabled=True,
            execution_mode="docker",
            **_all_gateway(),
        )

        assert config.gateway_fleet_ratchet_enabled is True

    def test_an_ungoverned_repo_needs_no_ratchet(self) -> None:
        """Scoped like the dial check: only the canary repo is judged."""
        config = HydraFlowConfig(
            repo="acme/other", gateway_enforcement_canary_repo=_GOVERNED
        )

        assert config.gateway_fleet_ratchet_enabled is False
