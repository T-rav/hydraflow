"""The pre-migration resolution of every legacy `*_provider` dial (#11991).

P6b migrates these dials into generated baseline policies and has the resolver
read policy instead. Its own instruction is the reason this file exists and is
landing *first*:

    Write the parity test first, against the *unmigrated* code. A parity test
    written after the migration proves the new code agrees with itself.

So this records what the dials resolve to **today**, before anything moves.
After migration, the same assertions must still hold with the resolver reading
policy — and because the expectations here were captured against the old path,
agreement then means the migration preserved behaviour rather than that the new
code is self-consistent.

**The failure mode P6b guards against is silent.** A dial that stops being read
does not raise; it stops steering and the spawn routes to a default that looks
reasonable. That is #11853's shape, where `apply_credit_failover` was correct
and simply never called. A parity check is the only thing that sees it.

Every assertion is derived from `HydraFlowConfig.model_fields` by reference. A
hand-copied dial list would be one more place to forget the fifteenth dial, and
forgetting it is indistinguishable from the dial silently going unread.
"""

from __future__ import annotations

import typing

import pytest

from config import HydraFlowConfig
from hydraflow_gateway.routing_policy import RequestFace, RouteTransport
from route_shadow import provider_binding_for, transport_for

#: The governed seam. A dial that can name it can be migrated to policy.
_GATEWAY = "gateway"


def _provider_dials() -> tuple[str, ...]:
    """Every legacy routing dial, by reference to the model."""
    return tuple(
        sorted(
            name for name in HydraFlowConfig.model_fields if name.endswith("_provider")
        )
    )


def _allowed_values(dial: str) -> frozenset[str]:
    """The Literal a dial admits, read off the annotation rather than listed."""
    annotation = HydraFlowConfig.model_fields[dial].annotation
    return frozenset(arg for arg in typing.get_args(annotation) if isinstance(arg, str))


_DIALS = _provider_dials()


def test_the_sweep_found_the_dials_it_was_built_from() -> None:
    """Anti-vacuity: an empty dial set would pass every parametrised case."""
    assert len(_DIALS) >= 13, f"expected the ~13 dials #11991 names, got {_DIALS}"
    assert "maintenance_provider" in _DIALS


class TestEveryDialCanReachTheGovernedSeam:
    """P6b can only migrate a dial into policy if policy can express it."""

    @pytest.mark.parametrize("dial", _DIALS, ids=_DIALS)
    def test_the_dial_admits_gateway(self, dial: str) -> None:
        assert _GATEWAY in _allowed_values(dial), (
            f"{dial} cannot name the governed seam, so no generated baseline "
            f"policy can reproduce a governed resolution for it"
        )


class TestThePreMigrationDefaultIsRecorded:
    """What the dials resolve to today, captured before anything moves."""

    @pytest.mark.parametrize("dial", _DIALS, ids=_DIALS)
    def test_the_default_is_claude(self, dial: str) -> None:
        """Every dial ships defaulting to `claude`; the migration must agree.

        Asserted per dial rather than over the set so a single changed default
        names itself, and so adding a dial with a different default is a
        deliberate decision recorded here.
        """
        assert HydraFlowConfig.model_fields[dial].default == "claude"

    @pytest.mark.parametrize("dial", _DIALS, ids=_DIALS)
    def test_the_default_resolves_to_the_anthropic_lane(self, dial: str) -> None:
        """The binding a default dial produces, through the shared classifier."""
        default = str(HydraFlowConfig.model_fields[dial].default)

        assert provider_binding_for(default, "sonnet").value == "anthropic"

    @pytest.mark.parametrize("dial", _DIALS, ids=_DIALS)
    def test_a_default_dial_is_ungoverned_transport_today(self, dial: str) -> None:
        """Pre-migration these route harness-direct, not through the gateway.

        This is the baseline the migration changes *deliberately*: after it, a
        repository whose policy names the gateway resolves to
        `RouteTransport.GATEWAY`. Recording the old value is what makes that
        change visible rather than silent.
        """
        default = str(HydraFlowConfig.model_fields[dial].default)

        assert (
            transport_for(default, RequestFace.AGENTIC) is RouteTransport.HARNESS_DIRECT
        )


class TestMaintenanceInheritanceIsPinnedBeforeMigration:
    """#11524/#11525, pinned against OLD behaviour per #11991's third criterion.

    The pin has to land before the legacy path is removed, or it is a pin
    against whatever the migration happened to produce.
    """

    async def test_an_omitted_provider_inherits_the_maintenance_dial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller naming no provider routes on `config.maintenance_provider`.

        Driven through the real call rather than asserted against the source
        text of the expression. A substring pin would redden on a harmless
        rewrite and — the half that matters — would stay green if the rule
        changed while the words survived.
        """
        import runner_utils

        seen: dict[str, object] = {}

        async def _record(provider: str, config: object, **kwargs: object) -> dict:
            seen["provider"] = provider
            return {}

        monkeypatch.setattr(runner_utils, "resolve_harness_env", _record)

        await runner_utils.run_lightweight_agent(
            runner=_StubRunner(),  # type: ignore[arg-type]
            config=HydraFlowConfig(maintenance_provider="gateway"),
            tool="claude",
            model="sonnet",
            prompt="hello",
            source="spec_intake_review",
            timeout=5.0,
        )

        assert seen.get("provider") == "gateway", (
            "an omitted provider stopped inheriting maintenance_provider — the "
            "#11853 shape: the dial is still there and simply no longer steers"
        )

    def test_the_maintenance_dial_still_exists_to_be_inherited(self) -> None:
        assert "maintenance_provider" in HydraFlowConfig.model_fields

    def test_gateway_is_reachable_through_inheritance(self) -> None:
        """Setting one dial governs every caretaker that inherits it, which is
        what makes the migration expressible as policy at all."""
        assert _GATEWAY in _allowed_values("maintenance_provider")


class _StubRunner:
    """Returns a trivial success without starting a process."""

    async def run_simple(self, *args: object, **kwargs: object) -> object:
        from models import SimpleResult

        return SimpleResult(stdout="ok", returncode=0)
