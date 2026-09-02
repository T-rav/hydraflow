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

import inspect
import typing
from pathlib import Path

import pytest

import runner_utils
from config import HydraFlowConfig
from credit_failover import apply_credit_failover
from hydraflow_gateway.routing_policy import RequestFace, RouteTransport
from repo_backend import apply_repo_provider
from route_shadow import provider_binding_for, transport_for

#: The source tree the seam sweep reads, by reference to this file.
_SRC = Path(__file__).resolve().parents[1] / "src"

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


class TestTheRewriterStackIsPinnedBeforeMigration:
    """#11991's fourth criterion, stated as the order the rewriters compose in.

    "Credit failover still reroutes after migration" is the visible half. The
    half that decides it is the *order*: `config.py` documents the stack as
    `role dial > repo_provider > credit-failover`, and each layer is written to
    act only on a spawn still resolving to `"claude"`. Once the resolver reads
    policy, that ordering has to be reproduced by policy priority — so what it
    resolves to today is recorded here, against the unmigrated path.

    Driven through the real functions. Asserting the order from the source text
    of `_execute` would redden on a harmless rewrite and stay green if the
    layers were reordered while the words survived.
    """

    def test_a_role_dial_already_off_claude_wins_over_the_repo_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The top of the stack: `repo_provider` never overrules an explicit dial.

        The key is set deliberately. `apply_repo_provider` refuses to reroute to
        an endpoint with no credential, so on a host without `ZAI_API_KEY` this
        assertion is satisfied by the missing key rather than by the ordering it
        is meant to pin — and would stay green with the ordering guard deleted.
        Caught by mutating that guard away and watching the test pass.
        """
        monkeypatch.setenv("ZAI_API_KEY", "zai-parity-baseline-key")
        config = HydraFlowConfig(repo_provider="zai", repo_model="glm-5.2")

        assert apply_repo_provider("gateway", _claude_cmd(), config) == (
            "gateway",
            _claude_cmd(),
        )

    def test_the_repo_override_reroutes_a_spawn_still_on_claude(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The middle of the stack, and the anti-vacuity partner of the test above.

        Without this, a broken `apply_repo_provider` that returned its input
        unchanged for every argument would satisfy the ordering assertion.
        """
        monkeypatch.setenv("ZAI_API_KEY", "zai-parity-baseline-key")
        config = HydraFlowConfig(repo_provider="zai", repo_model="glm-5.2")

        provider, cmd = apply_repo_provider("claude", _claude_cmd(), config)

        assert (provider, "glm-5.2" in cmd) == ("zai", True)

    def test_credit_failover_does_not_touch_a_spawn_the_repo_moved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bottom of the stack. A GLM-native repo is untouched by a Claude cap.

        This is the property the migration is most likely to lose: expressed as
        policy, "failover applies" and "this repo is already elsewhere" stop
        being an ordering and become two rules that must not both match.
        """
        monkeypatch.setenv("ZAI_API_KEY", "zai-parity-baseline-key")
        config = HydraFlowConfig(credit_failover_enabled=True)

        assert apply_credit_failover("zai", _claude_cmd(), config) == (
            "zai",
            _claude_cmd(),
        )

    def test_the_maintenance_seam_is_out_of_the_repo_override_s_scope(self) -> None:
        """The scope boundary, recorded because migration could quietly widen it.

        `repo_provider` is documented as governing "this repo's **work** spawns";
        the lightweight seam routes on `maintenance_provider` instead and calls
        no repo override. Expressed as policy both become rules matching on a
        repo, and nothing about a rule says which spawns it was meant for — so
        the boundary is written down while it is still structural.
        """
        source = inspect.getsource(runner_utils.run_lightweight_agent)

        assert "apply_credit_failover" in source
        assert "apply_repo_provider" not in source


def test_every_seam_that_failover_reaches_is_a_known_one() -> None:
    """The #11853 property itself: a new spawn seam cannot skip failover quietly.

    #11853 was not a wrong function — `apply_credit_failover` was correct and
    simply never called from one of the places that spawns. A test of the
    function cannot see that; only a test of the *call sites* can. The set is
    swept out of `src/` rather than listed in prose, so a fourth seam added
    after the migration fails here and has to be classified rather than
    inherited.
    """
    found = {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if "apply_credit_failover(" in path.read_text(encoding="utf-8")
        and path.name not in {"credit_failover.py", "repo_backend.py"}
    }

    assert found == {
        "base_runner.py",
        "runner_utils.py",
        "runners/base_subprocess_runner.py",
    }, (
        f"the credit-failover seam set changed: {sorted(found)}. A new seam must "
        f"apply failover (#11853) and be recorded here before P6b migrates the "
        f"resolution off the dials"
    )


def _claude_cmd() -> list[str]:
    return ["claude", "--model", "sonnet", "-p", "hello"]
