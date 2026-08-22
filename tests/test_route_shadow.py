"""Shadow routing instrumentation: what legacy did, what policy would have done."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from driver_contracts import ModelRequirementKind
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.routing_audit import RoutingAuditLog
from hydraflow_gateway.routing_policy import (
    DecisionOutcome,
    LegacyRouteMechanism,
    PolicySource,
    RequestFace,
    RequirementMapping,
    RouteTransport,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
)
from hydraflow_gateway.routing_store import RoutingPolicyStore
from route_shadow import (
    RouteStage,
    ShadowDivergence,
    classify_legacy_mechanism,
    policy_snapshot_path,
    provider_binding_for,
    record_agentic_route_shadow,
    record_dialled_route_shadow,
    requirement_for_model,
    shadow_decision_log_path,
    transport_for,
)
from tests.helpers import ConfigFactory


@pytest.fixture
def config(tmp_path: Path) -> Any:
    built = ConfigFactory.create(repo="acme/project-x")
    built.data_root = tmp_path / "data"
    built.gateway_route_shadow_enabled = True
    return built


def _stage(mechanism: LegacyRouteMechanism, provider: str) -> RouteStage:
    return RouteStage(mechanism=mechanism, provider=provider, detail="d")


# --- Which dial actually decided the route ----------------------------------


def test_the_last_stage_that_moved_the_provider_is_the_deciding_one() -> None:
    """ "Why did this spawn go to GLM?" is answered by the stage that moved it."""
    stages = [
        _stage(LegacyRouteMechanism.ROLE_DIAL, "claude"),
        _stage(LegacyRouteMechanism.REPO_PROVIDER, "zai"),
        _stage(LegacyRouteMechanism.CREDIT_FAILOVER, "zai"),
    ]

    assert classify_legacy_mechanism(stages).mechanism is (
        LegacyRouteMechanism.REPO_PROVIDER
    )


def test_a_route_nothing_moved_is_credited_to_the_dial_it_started_on() -> None:
    """No stage rerouted it, so the answer is the dial, not the last stage."""
    stages = [
        _stage(LegacyRouteMechanism.ROLE_DIAL, "zai"),
        _stage(LegacyRouteMechanism.CREDIT_FAILOVER, "zai"),
    ]

    assert classify_legacy_mechanism(stages).mechanism is LegacyRouteMechanism.ROLE_DIAL


def test_classifying_no_stages_at_all_is_a_programming_error() -> None:
    """A legacy route always came from somewhere; a caller passing none is wrong."""
    with pytest.raises(ValueError, match="at least one stage"):
        classify_legacy_mechanism([])


# --- Binding, transport, and requirement classification ---------------------


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        pytest.param("claude", "opus", ProviderBinding.ANTHROPIC, id="direct-claude"),
        pytest.param("zai", "glm-5.2", ProviderBinding.ZAI_HARNESS, id="direct-zai"),
        pytest.param(
            "gateway", "glm-5.2", ProviderBinding.ZAI_HARNESS, id="gateway-glm"
        ),
        pytest.param(
            "gateway",
            "claude-opus-4-8",
            ProviderBinding.ANTHROPIC,
            id="gateway-claude",
        ),
    ],
)
def test_the_upstream_binding_follows_the_model_for_gateway_routes(
    provider: str, model: str, expected: ProviderBinding
) -> None:
    """Mirrors ``harness_billing_provider``: the gateway binds by model, not lane."""
    assert provider_binding_for(provider, model) is expected


def test_agentic_zai_is_a_harness_not_a_direct_http_backend() -> None:
    """At the agentic seam ``zai`` is the Claude CLI pointed at GLM."""
    assert transport_for("zai", RequestFace.AGENTIC) is RouteTransport.HARNESS_DIRECT


def test_one_shot_zai_is_a_direct_http_backend_the_gateway_never_sees() -> None:
    """The same provider name means a different transport at the one-shot seam."""
    assert transport_for("zai", RequestFace.ONE_SHOT) is RouteTransport.DIRECT_HTTP


def test_a_gateway_route_is_the_only_governed_transport() -> None:
    """Only traffic through the tap can be bound by a gateway policy."""
    assert transport_for("gateway", RequestFace.ONE_SHOT) is RouteTransport.GATEWAY


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        pytest.param("opus", ModelRequirementKind.LITERAL_FAMILY, id="cli-alias"),
        pytest.param(
            "claude-opus-4-8", ModelRequirementKind.CONCRETE_MODEL, id="qualified-id"
        ),
        pytest.param("glm-5.2", ModelRequirementKind.CONCRETE_MODEL, id="glm-id"),
        pytest.param("", ModelRequirementKind.CAPABILITY, id="unspecified"),
    ],
)
def test_the_requested_requirement_is_classified_from_what_the_spawn_asked_for(
    model: str, expected: ModelRequirementKind
) -> None:
    """A bare CLI alias *is* a family request; a qualified id is a concrete one."""
    assert requirement_for_model(model).kind is expected


def test_a_bare_opus_alias_is_recorded_as_the_claude_opus_family() -> None:
    """The family name is the shared contract's, not the CLI's shorthand."""
    assert requirement_for_model("opus").value == "claude-opus"


# --- The kill switch --------------------------------------------------------


def test_shadow_recording_is_off_when_the_switch_is_off(config: Any) -> None:
    """A named kill switch that does not actually stop the write is theatre."""
    config.gateway_route_shadow_enabled = False

    assert (
        record_dialled_route_shadow(
            config=config,
            principal_id="adr_reviewer",
            requested_provider="zai",
            transport_provider="zai",
            model="glm-5.2",
            request_face=RequestFace.ONE_SHOT,
        )
        is None
    )


def test_a_truthy_mock_config_does_not_switch_shadow_recording_on() -> None:
    """``is not True`` guards the footgun: every MagicMock attribute is truthy."""
    mock_config = MagicMock()

    assert (
        record_dialled_route_shadow(
            config=mock_config,
            principal_id="adr_reviewer",
            requested_provider="zai",
            transport_provider="zai",
            model="glm-5.2",
            request_face=RequestFace.ONE_SHOT,
        )
        is None
    )


def test_the_switch_being_off_writes_no_decision_file(config: Any) -> None:
    """Off means nothing is created, not that an empty file appears."""
    config.gateway_route_shadow_enabled = False
    record_dialled_route_shadow(
        config=config,
        principal_id="adr_reviewer",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert not shadow_decision_log_path(config).exists()


# --- The legacy role dials are explained, not laundered ---------------------


@pytest.mark.parametrize(
    "principal",
    [
        pytest.param("adr_reviewer", id="adr-review"),
        pytest.param("term_proposer", id="term-proposer"),
        pytest.param("transcript_summarizer", id="transcript-summary"),
        pytest.param("triage_honeypot", id="triage-honeypot"),
        pytest.param("wiki_compiler", id="wiki-compilation"),
    ],
)
def test_a_zai_pinned_loop_is_recorded_as_a_legacy_role_dial(
    config: Any, principal: str
) -> None:
    """The five loops this repo pins to z.ai route by dial, and the record says so."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id=principal,
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.actual.mechanism is LegacyRouteMechanism.ROLE_DIAL


def test_a_zai_pinned_loop_is_not_claimed_by_policy(config: Any) -> None:
    """No managed policy chose it, and the decision must not pretend one did."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="adr_reviewer",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.proposed.policy_source is PolicySource.LEGACY_COMPATIBILITY


def test_a_zai_pinned_loop_names_the_dial_value_that_decided_it(config: Any) -> None:
    """The detail is the greppable evidence behind the mechanism code."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="adr_reviewer",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.actual.mechanism_detail == "provider=zai"


def test_a_zai_pinned_one_shot_loop_is_recorded_as_an_ungoverned_bypass(
    config: Any,
) -> None:
    """It never touches the gateway, and the record must not imply it did."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="adr_reviewer",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.actual.transport is RouteTransport.DIRECT_HTTP


def test_a_loop_with_no_dial_is_recorded_as_the_maintenance_default(
    config: Any,
) -> None:
    """An omitted provider inherits ``maintenance_provider``, and that is named."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="sampled_audit",
        requested_provider=None,
        transport_provider="claude",
        model="sonnet",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.actual.mechanism is LegacyRouteMechanism.MAINTENANCE_DEFAULT


def test_a_loop_name_is_not_guessed_into_a_worker_role(config: Any) -> None:
    """ADR-0138 §D6 again: ``adr_reviewer`` is a loop, not a catalogued role."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="adr_reviewer",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.proposed.explanation.context.worker_role is None


# --- Agreement and divergence ------------------------------------------------


def test_an_unpoliced_spawn_agrees_with_itself(config: Any) -> None:
    """With no policy, the proposal is the legacy route, so there is no gap."""
    record = record_agentic_route_shadow(
        config=config,
        principal_id="implementer",
        dial_field=None,
        dial_provider="claude",
        after_ratchet="claude",
        after_repo_provider="claude",
        final_provider="claude",
        final_model="claude-opus-4-8",
    )

    assert record is not None
    assert record.agreed


def test_a_policy_that_would_reroute_the_spawn_is_recorded_as_a_divergence(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measurement the burn-in phase needs: proposed versus actual."""
    monkeypatch.setenv("ZAI_API_KEY", "k")
    RoutingPolicyStore(policy_snapshot_path(config)).save(
        [
            RoutingPolicy(
                id="project-x-zai",
                match=RoutingMatch(repo_ids=("acme/project-x",)),
                action=RoutingAction(
                    provider_lock=ProviderBinding.ZAI_HARNESS,
                    requirement_map=(
                        RequirementMapping(
                            requirement=requirement_for_model("claude-opus-4-8"),
                            effective_model="glm-5.3",
                        ),
                    ),
                ),
            )
        ]
    )

    record = record_agentic_route_shadow(
        config=config,
        principal_id="implementer",
        dial_field=None,
        dial_provider="claude",
        after_ratchet="claude",
        after_repo_provider="claude",
        final_provider="claude",
        final_model="claude-opus-4-8",
    )

    assert record is not None
    assert record.divergence is ShadowDivergence.PROVIDER_AND_MODEL


def test_a_divergent_decision_is_not_recorded_as_agreement(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``agreed`` and ``divergence`` cannot drift apart."""
    monkeypatch.setenv("ZAI_API_KEY", "k")
    RoutingPolicyStore(policy_snapshot_path(config)).save(
        [
            RoutingPolicy(
                id="project-x-zai",
                match=RoutingMatch(repo_ids=("acme/project-x",)),
                action=RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
            )
        ]
    )

    record = record_agentic_route_shadow(
        config=config,
        principal_id="implementer",
        dial_field=None,
        dial_provider="claude",
        after_ratchet="claude",
        after_repo_provider="claude",
        final_provider="claude",
        final_model="glm-5.2",
    )

    assert record is not None
    assert not record.agreed


def test_a_held_proposal_is_recorded_as_not_selected(config: Any) -> None:
    """A held route proposes nothing, which is neither agreement nor a divergence."""
    RoutingPolicyStore(policy_snapshot_path(config)).save(
        [
            RoutingPolicy(
                id="capability-only",
                match=RoutingMatch(repo_ids=("acme/project-x",)),
                action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
            )
        ]
    )

    record = record_agentic_route_shadow(
        config=config,
        principal_id="implementer",
        dial_field=None,
        dial_provider="claude",
        after_ratchet="claude",
        after_repo_provider="claude",
        final_provider="claude",
        final_model="",
    )

    assert record is not None
    assert record.divergence is ShadowDivergence.NOT_SELECTED


def test_a_held_proposal_reaches_the_held_outcome(config: Any) -> None:
    """The capability with no mapping holds rather than picking a lane."""
    RoutingPolicyStore(policy_snapshot_path(config)).save(
        [
            RoutingPolicy(
                id="capability-only",
                match=RoutingMatch(repo_ids=("acme/project-x",)),
                action=RoutingAction(provider_lock=ProviderBinding.ANTHROPIC),
            )
        ]
    )

    record = record_agentic_route_shadow(
        config=config,
        principal_id="implementer",
        dial_field=None,
        dial_provider="claude",
        after_ratchet="claude",
        after_repo_provider="claude",
        final_provider="claude",
        final_model="",
    )

    assert record is not None
    assert record.proposed.outcome is DecisionOutcome.HELD


# --- Durability and failure behaviour ---------------------------------------


def test_every_shadowed_spawn_appends_to_the_chain(config: Any) -> None:
    """ "Every governed spawn records" has to mean every one."""
    for index in range(3):
        record_dialled_route_shadow(
            config=config,
            principal_id=f"loop_{index}",
            requested_provider="zai",
            transport_provider="zai",
            model="glm-5.2",
            request_face=RequestFace.ONE_SHOT,
        )

    assert len(RoutingAuditLog(shadow_decision_log_path(config)).read_all()) == 3


def test_the_recorded_chain_verifies(config: Any) -> None:
    """A chain nobody can verify is a log, not an audit."""
    for index in range(3):
        record_dialled_route_shadow(
            config=config,
            principal_id=f"loop_{index}",
            requested_provider="zai",
            transport_provider="zai",
            model="glm-5.2",
            request_face=RequestFace.ONE_SHOT,
        )

    assert RoutingAuditLog(shadow_decision_log_path(config)).verify().ok


def test_an_unwritable_sink_is_swallowed(config: Any) -> None:
    """Disk trouble degrades to no record, never to a raised spawn failure."""
    with patch("route_shadow.RoutingAuditLog.append", side_effect=OSError("disk full")):
        assert (
            record_dialled_route_shadow(
                config=config,
                principal_id="adr_reviewer",
                requested_provider="zai",
                transport_provider="zai",
                model="glm-5.2",
                request_face=RequestFace.ONE_SHOT,
            )
            is None
        )


def test_a_genuine_bug_in_the_shadow_path_still_surfaces(config: Any) -> None:
    """The house rule: a silently wrong shadow is worse than a loud one."""
    with (
        patch("route_shadow.RoutingAuditLog.append", side_effect=TypeError("bug")),
        pytest.raises(TypeError),
    ):
        record_dialled_route_shadow(
            config=config,
            principal_id="adr_reviewer",
            requested_provider="zai",
            transport_provider="zai",
            model="glm-5.2",
            request_face=RequestFace.ONE_SHOT,
        )


def test_a_corrupt_policy_snapshot_holds_rather_than_claiming_a_route(
    config: Any,
) -> None:
    """Fail closed all the way through the wiring, not just in the pure core."""
    path = policy_snapshot_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    record = record_dialled_route_shadow(
        config=config,
        principal_id="adr_reviewer",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert record is not None
    assert record.proposed.outcome is DecisionOutcome.HELD


def test_no_credential_reaches_a_recorded_decision(config: Any, tmp_path: Path) -> None:
    """The record is durable and sanitized; a leaked key would be permanent."""
    del tmp_path
    record_dialled_route_shadow(
        config=config,
        principal_id="sk-ant-" + "a" * 44,
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.ONE_SHOT,
    )

    assert "sk-ant-" not in shadow_decision_log_path(config).read_text(encoding="utf-8")


# --- The streaming telemetry seam (the fourth governed spawn site) -----------


def test_the_streaming_seam_records_an_agentic_face(config: Any) -> None:
    """``stream_claude_with_telemetry`` is agentic, not one-shot."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="acceptance_criteria",
        requested_provider="claude",
        transport_provider="gateway",
        model="claude-sonnet-4-6",
        request_face=RequestFace.AGENTIC,
    )

    assert record is not None
    assert record.proposed.explanation.context.request_face is RequestFace.AGENTIC


def test_a_ratcheted_streaming_spawn_is_recorded_as_governed_transport(
    config: Any,
) -> None:
    """With the fleet ratchet on this traffic IS what a policy could bind."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="acceptance_criteria",
        requested_provider="claude",
        transport_provider="gateway",
        model="claude-sonnet-4-6",
        request_face=RequestFace.AGENTIC,
    )

    assert record is not None
    assert record.actual.transport is RouteTransport.GATEWAY


def test_a_ratcheted_streaming_spawn_credits_the_ratchet_not_the_dial(
    config: Any,
) -> None:
    """The dial said claude; the ratchet is what moved it onto the tap."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="acceptance_criteria",
        requested_provider="claude",
        transport_provider="gateway",
        model="claude-sonnet-4-6",
        request_face=RequestFace.AGENTIC,
    )

    assert record is not None
    assert record.actual.mechanism is LegacyRouteMechanism.FLEET_RATCHET


def test_the_same_zai_dial_means_a_harness_at_the_streaming_seam(
    config: Any,
) -> None:
    """One-shot ``zai`` is direct HTTP; streaming ``zai`` is the CLI on GLM."""
    record = record_dialled_route_shadow(
        config=config,
        principal_id="verification_judge",
        requested_provider="zai",
        transport_provider="zai",
        model="glm-5.2",
        request_face=RequestFace.AGENTIC,
    )

    assert record is not None
    assert record.actual.transport is RouteTransport.HARNESS_DIRECT
