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


def test_the_dial_set_is_derived_and_non_empty() -> None:
    """Anti-vacuity: an empty set would make every assertion below pass."""
    assert len(_PROVIDER_DIALS) >= 13
    assert "maintenance_provider" in _PROVIDER_DIALS


class TestAGovernedRepoMustRouteEveryFaceThroughTheGateway:
    def test_a_direct_face_is_refused_at_load(self) -> None:
        with pytest.raises(ValueError, match="must resolve through the gateway"):
            HydraFlowConfig(repo=_GOVERNED, gateway_enforcement_canary_repo=_GOVERNED)

    def test_the_refusal_names_the_offending_face(self) -> None:
        """ "Something is ungoverned" is not something an operator can act on."""
        with pytest.raises(ValueError) as caught:
            HydraFlowConfig(
                repo=_GOVERNED,
                gateway_enforcement_canary_repo=_GOVERNED,
                **{**_all_gateway(), "review_provider": "claude"},
            )

        assert "review_provider='claude'" in str(caught.value)

    def test_all_faces_on_the_gateway_loads(self) -> None:
        config = HydraFlowConfig(
            repo=_GOVERNED,
            gateway_enforcement_canary_repo=_GOVERNED,
            **_all_gateway(),
        )

        assert config.maintenance_provider == "gateway"


class TestTheGateIsScopedToTheGovernedRepo:
    def test_an_unarmed_deployment_is_untouched(self) -> None:
        assert HydraFlowConfig(repo="acme/other").maintenance_provider == "claude"

    def test_another_repo_is_not_forced_onto_the_gateway(self) -> None:
        """The objection that stalled this criterion, asserted as a property.

        A canary armed for one repository must not conscript every other
        repository the host serves — they are separate configs.
        """
        config = HydraFlowConfig(
            repo="acme/other", gateway_enforcement_canary_repo=_GOVERNED
        )

        assert config.maintenance_provider == "claude"

    def test_a_repo_with_no_identity_is_not_judged(self) -> None:
        """Without a canonical repo there is nothing to compare the lock to."""
        config = HydraFlowConfig(gateway_enforcement_canary_repo=_GOVERNED)

        assert config.maintenance_provider == "claude"
