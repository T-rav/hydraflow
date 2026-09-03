"""Moonshot Kimi as an agentic harness lane, not just a one-shot endpoint.

``kimi`` was already a one-shot provider: a direct POST to
``/v1/chat/completions`` with no tools and no agent loop. Moonshot now
publishes an Anthropic-shaped face at ``/anthropic``, which is the same shape
the Claude CLI is already pointed at for z.ai, so a tool-using role can run on
Kimi. ``_HARNESS_BACKENDS`` carried a comment saying "kimi stays
one-shot-only"; that comment was the design, and this file is the design that
replaced it.

The decoy running through these cases is z.ai. Every table kimi joins already
had a z.ai row, and the shapes are close enough that a change can look correct
while quietly serving one lane's traffic from the other's account —
``route_shadow`` really did bill kimi spawns to ``zai-harness`` before this.
So each case that asserts kimi lands somewhere is paired with one asserting
z.ai still lands where it did.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import get_args

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (  # noqa: E402
    GATEWAY_CAPABLE_PROVIDER_FIELDS,
    HydraFlowConfig,
    _gateway_direct_harness_roles,
)
from dashboard_routes._state_routes import _effective_repo_provider  # noqa: E402
from hydraflow_gateway.models import (  # noqa: E402
    ProviderBinding,
    binding_for_lane,
    binding_for_model,
)
from repo_backend import apply_repo_provider  # noqa: E402
from route_shadow import provider_binding_for  # noqa: E402
from runner_utils import (  # noqa: E402
    _HARNESS_BACKENDS,
    _OPENAI_COMPAT_BACKENDS,
    harness_billing_provider,
    resolve_harness_env,
)

# ---------------------------------------------------------------------------
# Which lane serves a model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("kimi-k3", ProviderBinding.KIMI_HARNESS),
        ("kimi-k2.7-code", ProviderBinding.KIMI_HARNESS),
        ("KIMI-K3", ProviderBinding.KIMI_HARNESS),
        ("  kimi-k3  ", ProviderBinding.KIMI_HARNESS),
        ("glm-4.6", ProviderBinding.ZAI_HARNESS),
        ("claude-opus-4", ProviderBinding.ANTHROPIC),
        ("gpt-4", ProviderBinding.ANTHROPIC),
    ],
)
def test_a_model_id_names_its_lane(model: str, expected: ProviderBinding) -> None:
    """``binding_for_model`` is the single definition of "who serves this".

    It was ``ZAI_HARNESS if startswith("glm") else ANTHROPIC`` — a shape with
    no third answer available, so ``kimi-k3`` would have resolved to Anthropic
    and minted a key against an account that never served the request. The
    glm and claude rows are here so the table's other answers are pinned too.
    """
    assert binding_for_model(model) is expected


@pytest.mark.parametrize(
    ("lane", "expected"),
    [
        ("kimi", ProviderBinding.KIMI_HARNESS),
        ("zai", ProviderBinding.ZAI_HARNESS),
        ("claude", ProviderBinding.ANTHROPIC),
        ("gateway", ProviderBinding.ANTHROPIC),
        # Unchanged on purpose: openrouter has always reported the z.ai lane
        # and re-attributing it is a separate decision from adding Moonshot.
        ("openrouter", ProviderBinding.ZAI_HARNESS),
    ],
)
def test_a_provider_dial_names_its_lane(lane: str, expected: ProviderBinding) -> None:
    assert binding_for_lane(lane) is expected


def test_a_kimi_spawn_is_no_longer_billed_to_the_zai_lane() -> None:
    """The defect this change fixes, stated as its own case.

    ``provider_binding_for`` mapped ``{"zai", "kimi", "openrouter"}`` onto
    ``ZAI_HARNESS`` wholesale, so every kimi spawn's ledger row named an
    account it never touched. Written as an inequality as well as an equality
    because the equality alone would pass against a build that mapped
    everything to KIMI_HARNESS.
    """
    assert provider_binding_for("kimi", "kimi-k3") is ProviderBinding.KIMI_HARNESS
    assert provider_binding_for("kimi", "kimi-k3") is not ProviderBinding.ZAI_HARNESS
    assert provider_binding_for("zai", "glm-4.6") is ProviderBinding.ZAI_HARNESS


@pytest.mark.parametrize(
    ("model", "expected"),
    [("kimi-k3", "kimi"), ("glm-4.6", "zai"), ("claude-opus-4", "claude")],
)
def test_the_gateway_bills_the_lane_the_model_belongs_to(
    model: str, expected: str
) -> None:
    """A gateway spawn's billing lane follows its model, not its dial."""
    assert harness_billing_provider("gateway", model) == expected


# ---------------------------------------------------------------------------
# The harness itself
# ---------------------------------------------------------------------------


def test_kimi_is_registered_as_a_harness_backend() -> None:
    """Registration is what makes an agentic (tool-using) role possible."""
    assert "kimi" in _HARNESS_BACKENDS


def test_kimi_remains_a_one_shot_backend_too() -> None:
    """The harness face is additive. z.ai sits in both registries; so does kimi.

    Without this, moving the entry rather than adding one would read as a
    success: agentic roles would work and every existing one-shot caretaker
    role would quietly lose its backend.
    """
    assert "kimi" in _OPENAI_COMPAT_BACKENDS


def test_the_two_kimi_faces_have_different_urls(tmp_path: Path) -> None:
    """One-shot speaks OpenAI at /v1; the harness speaks Anthropic at /anthropic.

    Pointing the Claude CLI at the /v1 face fails as an opaque upstream error,
    so a single shared URL would be a silent misconfiguration rather than a
    loud one.
    """
    config = HydraFlowConfig(repo_root=tmp_path)

    assert config.kimi_harness_base_url == "https://api.moonshot.ai/anthropic"
    assert config.kimi_base_url != config.kimi_harness_base_url


def test_a_kimi_spawn_is_pointed_at_moonshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The env a kimi role's Claude CLI actually receives.

    ``ANTHROPIC_API_KEY`` is cleared alongside, or a host Claude key shadows
    the bearer token and the spawn silently runs on Anthropic's endpoint with
    Anthropic's billing.
    """
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test-moonshot")
    config = HydraFlowConfig(repo_root=tmp_path)

    env = asyncio.run(resolve_harness_env("kimi", config, model="kimi-k3"))

    assert env["ANTHROPIC_BASE_URL"] == "https://api.moonshot.ai/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-moonshot"
    assert env["ANTHROPIC_API_KEY"] == ""


def test_a_kimi_spawn_without_a_key_falls_back_rather_than_half_configuring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No credential means no override, not a base URL with an empty token."""
    for name in ("MOONSHOT_API_KEY", "KIMI_API_KEY", "HYDRAFLOW_KIMI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = HydraFlowConfig(repo_root=tmp_path)

    assert asyncio.run(resolve_harness_env("kimi", config, model="kimi-k3")) == {}


def test_a_claude_spawn_still_gets_a_pristine_env(tmp_path: Path) -> None:
    """The decoy for every case above: the main coding workers must not move."""
    config = HydraFlowConfig(repo_root=tmp_path)

    assert asyncio.run(resolve_harness_env("claude", config, model="opus")) == {}


# ---------------------------------------------------------------------------
# The dials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dial", GATEWAY_CAPABLE_PROVIDER_FIELDS)
def test_every_routable_dial_accepts_kimi(dial: str) -> None:
    """A harness backend nothing can select is a backend that does not exist.

    Parametrised over `GATEWAY_CAPABLE_PROVIDER_FIELDS` by reference rather
    than over the six dials this change happened to edit. The one-shot dials
    already accepted `kimi`; the agentic ones now do; and stating it over the
    whole routable set means a dial added later is held to it without anyone
    remembering to come back here.
    """
    choices = get_args(HydraFlowConfig.model_fields[dial].annotation)

    assert "kimi" in choices, f"{dial} cannot be pointed at the kimi harness"
    assert "zai" in choices, f"{dial} lost the zai lane it already had"


def test_a_kimi_dial_requires_a_kimi_model(tmp_path: Path) -> None:
    """The lane serves one model family, so the pairing is locked both ways."""
    with pytest.raises(ValueError, match="kimi"):
        HydraFlowConfig(
            repo_root=tmp_path,
            maintenance_provider="kimi",
            maintenance_model="glm-4.6",
        )


def test_a_kimi_model_requires_the_kimi_dial(tmp_path: Path) -> None:
    """The inverse. Together these stop a model reaching a lane that cannot serve it."""
    with pytest.raises(ValueError, match="kimi"):
        HydraFlowConfig(
            repo_root=tmp_path,
            maintenance_provider="zai",
            maintenance_model="kimi-k3",
        )


def test_a_coherent_kimi_pair_loads(tmp_path: Path) -> None:
    """The positive case, without which the two rejections above are satisfied
    by a build that rejects every kimi configuration there is."""
    config = HydraFlowConfig(
        repo_root=tmp_path, maintenance_provider="kimi", maintenance_model="kimi-k3"
    )

    assert (config.maintenance_provider, config.maintenance_model) == (
        "kimi",
        "kimi-k3",
    )


def test_the_gateway_may_still_front_a_kimi_model(tmp_path: Path) -> None:
    """The gateway is not a model family, so it is exempt from the lock.

    It has a Moonshot upstream of its own; refusing this pairing would make the
    gateway the one dial that could not reach a lane it is configured for.
    """
    config = HydraFlowConfig(
        repo_root=tmp_path, maintenance_provider="gateway", maintenance_model="kimi-k3"
    )

    assert config.maintenance_provider == "gateway"


def test_the_zai_pairing_rule_is_unchanged(tmp_path: Path) -> None:
    """Generalising the validator over a table must not loosen z.ai's rule."""
    with pytest.raises(ValueError, match="glm"):
        HydraFlowConfig(
            repo_root=tmp_path,
            maintenance_provider="zai",
            maintenance_model="claude-opus-4",
        )


# ---------------------------------------------------------------------------
# The consumers a widened dial reaches
# ---------------------------------------------------------------------------
#
# Adding "kimi" to a `*_provider` Literal is not, by itself, support for it.
# Each of these is a place that asked `== "zai"` or listed the lanes it knew,
# and would have accepted a kimi dial while doing nothing with it. A dial the
# operator can select and save that changes no behaviour is worse than one that
# was never offered: it reads as configured.


def test_a_kimi_repo_override_actually_reroutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`apply_repo_provider` acted only on {"gateway", "zai"} — kimi was inert."""
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test-moonshot")
    config = HydraFlowConfig(
        repo_root=tmp_path, repo_provider="kimi", repo_model="kimi-k3"
    )

    provider, cmd = apply_repo_provider(
        "claude", ["claude", "--model", "opus", "-p", "hi"], config
    )

    assert provider == "kimi"
    assert "kimi-k3" in cmd


def test_a_kimi_repo_override_without_a_key_stays_on_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fail-safe z.ai already had: never reroute to an endpoint with no key.

    Without this the override would rewrite `--model` to a kimi id and leave
    the spawn pointed at Anthropic, which answers with a model-not-found rather
    than anything an operator could read as a missing credential.
    """
    for name in ("MOONSHOT_API_KEY", "KIMI_API_KEY", "HYDRAFLOW_KIMI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = HydraFlowConfig(
        repo_root=tmp_path, repo_provider="kimi", repo_model="kimi-k3"
    )
    cmd = ["claude", "--model", "opus", "-p", "hi"]

    assert apply_repo_provider("claude", cmd, config) == ("claude", cmd)


def test_the_ui_reports_the_lane_a_keyless_kimi_repo_actually_runs_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The badge must show the resolved effect, not the configured intent."""
    for name in ("MOONSHOT_API_KEY", "KIMI_API_KEY", "HYDRAFLOW_KIMI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = HydraFlowConfig(
        repo_root=tmp_path, repo_provider="kimi", repo_model="kimi-k3"
    )

    assert _effective_repo_provider(config) == "claude"


def test_a_kimi_role_counts_as_a_gateway_bypass(tmp_path: Path) -> None:
    """`_gateway_direct_harness_roles` listed {"claude", "zai"} by hand.

    A kimi role bypasses the gateway exactly as a zai one does — same direct
    harness, same host credential, same absence from the gateway ledger. Going
    unreported is the failure that matters: this function exists so the fleet
    ratchet can see what is still off the gateway.

    Asserted on an agentic dial because those are the fields this function
    scans. `GATEWAY_INHERITED_PROVIDER_FIELDS` — `maintenance_provider` and
    `retro_finder_provider` — is scanned by neither loop here, so a direct
    `maintenance_provider` goes unreported today for z.ai as much as for kimi.
    That is a pre-existing hole in the ratchet, not one this change opened, and
    closing it can fail configurations that load today, so it is filed rather
    than folded in.
    """
    config = HydraFlowConfig(
        repo_root=tmp_path, repo_provider="kimi", repo_model="kimi-k3"
    )

    reported = _gateway_direct_harness_roles(config)

    assert any("repo_provider" in row and "kimi" in row for row in reported), (
        f"a kimi-dialled role is missing from {reported}"
    )


def test_the_dashboard_and_the_spawn_read_one_map() -> None:
    """Identity, not equality — two equal copies are still two copies.

    `_effective_repo_provider` exists to answer "what will the spawn actually
    do", so the moment it consults its own copy of the lane→key-presence map it
    can answer a question about a different program than the one that runs.
    Equality would pass on the day someone duplicated the map and both copies
    still happened to agree, which is exactly the day the divergence starts.

    This is also why the map is public. Reaching it through a `noqa: PLC2701`
    said the name was private and the rule wrong; the rule was right and the
    name was in the wrong namespace.
    """
    from dashboard_routes import _state_routes
    from repo_backend import DIRECT_HARNESS_KEY_PRESENT

    assert _state_routes.DIRECT_HARNESS_KEY_PRESENT is DIRECT_HARNESS_KEY_PRESENT


def test_a_lane_with_no_failover_model_is_refused_at_load(tmp_path: Path) -> None:
    """`repo_provider="kimi"` with no `repo_model` must not load.

    z.ai's override inherits `credit_failover_model` when `repo_model` is
    unset. No other lane has one, and `rewrite_command_model` does not decline
    an empty model — it writes `--model ""` onto the spawned CLI, which comes
    back as an opaque upstream error rather than as the half-finished
    configuration it is. Refused here so it cannot reach a spawn.
    """
    with pytest.raises(ValueError, match="repo_model"):
        HydraFlowConfig(repo_root=tmp_path, repo_provider="kimi")


def test_an_unset_zai_repo_model_still_inherits_its_failover(tmp_path: Path) -> None:
    """The decoy for the refusal above: z.ai has something to inherit, so it
    must keep loading with `repo_model` unset. A rule stated as "a locked lane
    needs a model" rather than "a lane with nothing to inherit needs one"
    would break every existing z.ai repo override."""
    config = HydraFlowConfig(repo_root=tmp_path, repo_provider="zai")

    assert config.repo_model == ""
    assert config.credit_failover_model.startswith("glm")


def test_a_repo_override_never_asks_a_lane_for_an_empty_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt to the validator's braces, asserted at the rewrite itself.

    `_default_model_for` returned `config.repo_model.strip()` for any non-zai
    lane — the same empty string the caller had just tried — so the `or`
    fallback was a no-op and the rewrite ran with "". Constructed here by
    bypassing validation, because the point is that this function is safe even
    when something upstream was not.
    """
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test-moonshot")
    config = HydraFlowConfig(
        repo_root=tmp_path, repo_provider="kimi", repo_model="kimi-k3"
    )
    object.__setattr__(config, "repo_model", "")
    cmd = ["claude", "--model", "opus", "-p", "hi"]

    provider, rewritten = apply_repo_provider("claude", cmd, config)

    assert (provider, rewritten) == ("claude", cmd), (
        "an unresolvable model must leave the spawn alone, not reroute it and "
        f"ask for --model '' (got {provider!r}, {rewritten!r})"
    )
