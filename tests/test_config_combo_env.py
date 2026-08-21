"""Tests for the HydraFlowConfig combo env var restructure."""

from __future__ import annotations

import os
from typing import Literal, get_args
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import config as config_module
from config import HydraFlowConfig, _parse_combo


def test_wired_agentic_roles_have_provider_dial_defaulting_claude() -> None:
    """Every role with a provider-honoring spawn carries a dial defaulting claude.

    Only roles with a dedicated spawn get a dial — sub-spawns inherit their
    outer runner's provider, so a dial for them would validate yet never route.
    """
    cfg = HydraFlowConfig()
    for role in ("implementation", "review", "planner", "triage", "ac"):
        assert getattr(cfg, f"{role}_provider") == "claude", role


def test_sub_spawn_roles_have_no_dead_provider_dial() -> None:
    """Sub-spawn roles must NOT expose a validated-but-unrouted provider dial."""
    fields = HydraFlowConfig.model_fields
    for role in (
        "subskill",
        "debug",
        "verification_judge",
        "test_adequacy_verifier",
        "system",
        "background",
    ):
        assert f"{role}_provider" not in fields, role


def test_reject_glm_model_on_claude_provider() -> None:
    """A glm-* model on a claude-provider role is incoherent and must fail loud."""
    with pytest.raises((ValueError, ValidationError), match="provider"):
        HydraFlowConfig(implementation_provider="claude", model="glm-5.2")


def test_reject_opus_model_on_zai_provider() -> None:
    """The zai (GLM) harness backend must pair with a glm-* model."""
    with pytest.raises((ValueError, ValidationError), match="glm"):
        HydraFlowConfig(wiki_compilation_provider="zai", wiki_compilation_model="opus")


def test_allow_glm_on_zai_provider() -> None:
    cfg = HydraFlowConfig(
        wiki_compilation_provider="zai", wiki_compilation_model="glm-5.2"
    )
    assert cfg.wiki_compilation_provider == "zai"
    assert cfg.wiki_compilation_model == "glm-5.2"


@pytest.mark.parametrize("model", ["sonnet", "glm-5.2"])
def test_allow_claude_harness_models_through_gateway(model: str) -> None:
    cfg = HydraFlowConfig(implementation_provider="gateway", model=model)
    assert cfg.implementation_provider == "gateway"
    assert cfg.model == model


def test_reject_gateway_provider_with_codex_tool() -> None:
    with pytest.raises((ValueError, ValidationError), match="gateway.*claude"):
        HydraFlowConfig(
            implementation_provider="gateway",
            implementation_tool="codex",
            model="gpt-5-codex",
        )


def test_reject_gateway_pr_unstick_with_codex_background_tool() -> None:
    with pytest.raises(
        (ValueError, ValidationError), match="pr_unstick.*background_tool"
    ):
        HydraFlowConfig(
            pr_unstick_provider="gateway",
            background_tool="codex",
        )


@pytest.mark.parametrize("tool", ["inherit", "claude"])
def test_allow_gateway_pr_unstick_with_claude_background_tool(
    tool: Literal["inherit", "claude"],
) -> None:
    cfg = HydraFlowConfig(
        pr_unstick_provider="gateway",
        background_tool=tool,
    )
    assert cfg.pr_unstick_provider == "gateway"
    assert cfg.background_tool == tool


def test_adr_reviewer_is_explicit_gateway_canary_not_global_default() -> None:
    direct = HydraFlowConfig()
    canary = HydraFlowConfig(adr_review_provider="gateway")
    assert direct.adr_review_provider == "claude"
    assert canary.adr_review_provider == "gateway"
    assert canary.implementation_provider == "claude"


def test_adr_reviewer_gateway_canary_env_is_not_ignored() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_ADR_REVIEW_PROVIDER": "gateway"}, clear=False
    ):
        cfg = HydraFlowConfig()
    assert cfg.adr_review_provider == "gateway"
    assert cfg.implementation_provider == "claude"


def test_gateway_fleet_ratchet_promotes_untouched_roles_to_terminal_profile() -> None:
    cfg = HydraFlowConfig(
        gateway_fleet_ratchet_enabled=True,
        execution_mode="docker",
    )
    assert all(
        getattr(cfg, field) == "gateway"
        for field in config_module.GATEWAY_CAPABLE_PROVIDER_FIELDS
    )


@pytest.mark.parametrize("field", config_module.GATEWAY_AGENTIC_PROVIDER_FIELDS)
@pytest.mark.parametrize("provider", ["claude", "zai"])
def test_gateway_fleet_ratchet_rejects_explicit_direct_harness_role(
    field: str, provider: str
) -> None:
    with pytest.raises((ValueError, ValidationError), match="fleet ratchet.*direct"):
        HydraFlowConfig(
            gateway_fleet_ratchet_enabled=True,
            execution_mode="docker",
            **{field: provider},
        )


def test_gateway_fleet_ratchet_accepts_centralized_routed_role_set() -> None:
    routed = dict.fromkeys(config_module.GATEWAY_CAPABLE_PROVIDER_FIELDS, "gateway")
    cfg = HydraFlowConfig(
        gateway_fleet_ratchet_enabled=True,
        execution_mode="docker",
        **routed,
    )
    assert all(
        getattr(cfg, field) == "gateway"
        for field in config_module.GATEWAY_CAPABLE_PROVIDER_FIELDS
    )


def test_gateway_terminal_profile_and_direct_rejection_work_via_env() -> None:
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_GATEWAY_FLEET_RATCHET_ENABLED": "true",
            "HYDRAFLOW_EXECUTION_MODE": "docker",
        },
        clear=False,
    ):
        cfg = HydraFlowConfig()
    assert all(
        getattr(cfg, field) == "gateway"
        for field in config_module.GATEWAY_CAPABLE_PROVIDER_FIELDS
    )

    with (
        patch.dict(
            os.environ,
            {
                "HYDRAFLOW_GATEWAY_FLEET_RATCHET_ENABLED": "true",
                "HYDRAFLOW_IMPLEMENTATION_PROVIDER": "claude",
                "HYDRAFLOW_EXECUTION_MODE": "docker",
            },
            clear=False,
        ),
        pytest.raises((ValueError, ValidationError), match="fleet ratchet.*direct"),
    ):
        HydraFlowConfig()


def test_gateway_fleet_ratchet_preserves_excluded_one_shot_http_provider() -> None:
    routed = dict.fromkeys(config_module.GATEWAY_CAPABLE_PROVIDER_FIELDS, "gateway")
    routed["pr_unstick_provider"] = "zai"
    cfg = HydraFlowConfig(
        gateway_fleet_ratchet_enabled=True,
        execution_mode="docker",
        **routed,
    )
    assert cfg.pr_unstick_provider == "zai"


def test_gateway_terminal_profile_rejects_host_keychain_runtime() -> None:
    with pytest.raises((ValueError, ValidationError), match="requires execution_mode"):
        HydraFlowConfig(gateway_fleet_ratchet_enabled=True, execution_mode="host")


def test_gateway_terminal_profile_rejects_arbitrary_host_mounts() -> None:
    with pytest.raises(
        (ValueError, ValidationError), match="forbids docker_extra_mounts"
    ):
        HydraFlowConfig(
            gateway_fleet_ratchet_enabled=True,
            execution_mode="docker",
            docker_extra_mounts=["/home/operator:/host-home:ro"],
        )


def test_gateway_repo_class_env_override_and_capture_policy() -> None:
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_GATEWAY_BASE_URL": "http://gateway:8080",
            "HYDRAFLOW_GATEWAY_LEDGER_PATH": "/gateway-metadata/requests.jsonl",
            "HYDRAFLOW_GATEWAY_REPO_CLASS": "client",
            "HYDRAFLOW_GATEWAY_KEY_TTL_SECONDS": "300",
        },
        clear=False,
    ):
        cfg = HydraFlowConfig()
    assert cfg.gateway_base_url == "http://gateway:8080"
    assert cfg.gateway_ledger_path == "/gateway-metadata/requests.jsonl"
    assert cfg.gateway_repo_class == "client"
    assert cfg.gateway_key_ttl_seconds == 300

    with pytest.raises((ValueError, ValidationError), match="metadata-only"):
        HydraFlowConfig(gateway_repo_class="client", gateway_capture_bodies=True)


def test_maintenance_knob_routes_only_maintenance_roles() -> None:
    """maintenance_* sets provider+model on maintenance roles, never work loops."""
    cfg = HydraFlowConfig(maintenance_provider="zai", maintenance_model="glm-5.2")
    # maintenance roles routed to GLM…
    assert cfg.wiki_compilation_provider == "zai"
    assert cfg.wiki_compilation_model == "glm-5.2"
    assert cfg.adr_review_provider == "zai"
    assert cfg.pr_unstick_provider == "zai"  # provider even though it has no model
    # …work loops untouched (still Claude).
    assert cfg.implementation_provider == "claude"
    assert cfg.model != "glm-5.2"
    assert cfg.review_provider == "claude"


def test_shared_maintenance_roles_resolve_maintenance_model() -> None:
    from config import resolve_maintenance_model, resolve_maintenance_tool

    cfg = HydraFlowConfig(
        maintenance_provider="gateway",
        maintenance_model="glm-5.2",
    )
    for field in (
        "sampled_audit_model",
        "issue_refinement_model",
        "intervention_tally_model",
        "skill_prompt_refine_model",
    ):
        assert (
            resolve_maintenance_model(
                role_model=getattr(cfg, field),
                maintenance_model=cfg.maintenance_model,
                background_model=cfg.background_model,
            )
            == "glm-5.2"
        )
    assert resolve_maintenance_tool(cfg) == "claude"


@pytest.mark.parametrize(
    ("field", "stage"),
    [
        ("sampled_audit_model", "sampled_audit"),
        ("issue_refinement_model", "issue_refinement"),
        ("intervention_tally_model", "intervention_tally"),
        ("skill_prompt_refine_model", "skill_prompt_refine"),
    ],
)
def test_shared_maintenance_roles_reject_glm_on_direct_claude(
    field: str,
    stage: str,
) -> None:
    with pytest.raises((ValueError, ValidationError), match=stage):
        HydraFlowConfig(**{field: "glm-5.2"})


def test_terminal_fleet_rejects_host_codex_caretaker_spawns() -> None:
    with pytest.raises((ValueError, ValidationError), match="background_tool"):
        HydraFlowConfig(
            gateway_fleet_ratchet_enabled=True,
            execution_mode="docker",
            background_tool="codex",
            background_model="gpt-5-codex",
        )


def test_verifier_model_validated_against_implementation_provider() -> None:
    """The test-adequacy verifier runs on the implementation harness, so its
    model is validated against implementation_provider, not a dial of its own."""
    # impl → GLM but an opus verifier model is incoherent (runs on the GLM
    # harness) and must fail at load.
    with pytest.raises((ValueError, ValidationError), match="glm|provider"):
        HydraFlowConfig(
            implementation_provider="zai",
            model="glm-5.2",
            test_adequacy_verifier_model="opus",
        )
    # A glm verifier model under impl=zai is coherent and accepted.
    cfg = HydraFlowConfig(
        implementation_provider="zai",
        model="glm-5.2",
        test_adequacy_verifier_model="glm-5.2",
    )
    assert cfg.test_adequacy_verifier_model == "glm-5.2"


def test_subskill_debug_models_validated_against_all_routing_providers() -> None:
    """subskill/debug run on BOTH ac_provider and review_provider, so their
    (default, claude) models must be rejected the moment either routes to GLM."""
    # ac routed to GLM but subskill/debug keep their default claude models →
    # incoherent (they'd run a claude model on the GLM harness) → rejected.
    with pytest.raises((ValueError, ValidationError)):
        HydraFlowConfig(ac_provider="zai", ac_model="glm-5.2")
    # Coherent only when EVERY routing runner is on GLM and the sub-spawn models
    # are glm too.
    cfg = HydraFlowConfig(
        ac_provider="zai",
        ac_model="glm-5.2",
        review_provider="zai",
        review_model="glm-5.2",
        subskill_model="glm-5.2",
        debug_model="glm-5.2",
    )
    assert cfg.subskill_model == "glm-5.2"
    assert cfg.debug_model == "glm-5.2"


def test_valid_background_model_does_not_leak_into_work_roles() -> None:
    """A valid (same-provider) background_model never reaches implement/review."""
    cfg = HydraFlowConfig(background_model="sonnet")
    assert cfg.model != "sonnet"  # implementation keeps its own default
    assert cfg.review_model == HydraFlowConfig.model_fields["review_model"].default


def test_no_gemini_or_pi_tool_literal_in_config() -> None:
    """gemini/pi are gutted — no *_tool Literal nor the combo allowlist admits them."""
    for name, field in HydraFlowConfig.model_fields.items():
        if name.endswith("_tool"):
            args = get_args(field.annotation)
            assert "gemini" not in args, name
            assert "pi" not in args, name
    assert {"claude", "codex"} == config_module._ALLOWED_TOOLS_COMBO


def test_system_tool_accepts_codex() -> None:
    cfg = HydraFlowConfig(system_tool="codex", system_model="gpt-5-codex")
    assert cfg.system_tool == "codex"


def test_invalid_tool_rejected() -> None:
    with pytest.raises(ValidationError):
        HydraFlowConfig(triage_tool="bogus")


def test_parse_combo_basic() -> None:
    assert _parse_combo("HYDRAFLOW_IMPLEMENT", "claude:opus") == ("claude", "opus")


def test_parse_combo_codex() -> None:
    assert _parse_combo("HYDRAFLOW_TRIAGE", "codex:gpt-5-codex") == (
        "codex",
        "gpt-5-codex",
    )


def test_parse_combo_inherit() -> None:
    assert _parse_combo("HYDRAFLOW_SYSTEM", "inherit") == ("inherit", "")


def test_parse_combo_missing_colon_raises() -> None:
    with pytest.raises(ValueError, match="must be 'tool:model'"):
        _parse_combo("HYDRAFLOW_IMPLEMENT", "claude-opus")


def test_parse_combo_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        _parse_combo("HYDRAFLOW_IMPLEMENT", "bogus:opus")


def test_parse_combo_empty_model_raises() -> None:
    with pytest.raises(ValueError, match="model part is empty"):
        _parse_combo("HYDRAFLOW_IMPLEMENT", "claude:")


def test_combo_env_sets_triage_tool_and_model() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_TRIAGE": "codex:gpt-5-codex"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.triage_tool == "codex"
        assert cfg.triage_model == "gpt-5-codex"


def test_combo_env_sets_implementation_tool_and_model() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_IMPLEMENT": "codex:gpt-5-codex"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert cfg.implementation_tool == "codex"
        assert cfg.model == "gpt-5-codex"


def test_combo_env_review_and_planner() -> None:
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_REVIEW": "claude:sonnet",
            "HYDRAFLOW_PLANNER": "claude:opus",
        },
        clear=False,
    ):
        cfg = HydraFlowConfig()
        assert cfg.review_tool == "claude"
        assert cfg.review_model == "sonnet"
        assert cfg.planner_tool == "claude"
        assert cfg.planner_model == "opus"


def test_combo_env_system_inherit() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_SYSTEM": "inherit"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.system_tool == "inherit"
        assert cfg.system_model == ""


def test_legacy_triage_tool_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_TRIAGE_TOOL": "codex"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.triage_tool == HydraFlowConfig.model_fields["triage_tool"].default


def test_legacy_model_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_MODEL": "gpt-5-codex"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.model == HydraFlowConfig.model_fields["model"].default


def test_legacy_label_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_LABEL_READY": "custom-ready"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.ready_label == HydraFlowConfig.model_fields["ready_label"].default


def test_legacy_max_subskill_attempts_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_MAX_SUBSKILL_ATTEMPTS": "5"}, clear=False):
        cfg = HydraFlowConfig()
        assert (
            cfg.max_subskill_attempts
            == HydraFlowConfig.model_fields["max_subskill_attempts"].default
        )


def test_legacy_debug_escalation_env_var_is_ignored() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_DEBUG_ESCALATION_ENABLED": "false"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert (
            cfg.debug_escalation_enabled
            == HydraFlowConfig.model_fields["debug_escalation_enabled"].default
        )


def test_harmonize_rejects_flash_model() -> None:
    with pytest.raises(ValueError, match="flash"):
        HydraFlowConfig(
            implementation_tool="codex",
            model="gpt-5-flash",
        )


def test_harmonize_rejects_claude_model_on_codex_tool() -> None:
    with pytest.raises(ValueError, match="mismatched"):
        HydraFlowConfig(implementation_tool="codex", model="opus")


def test_harmonize_rejects_codex_model_on_claude_tool() -> None:
    with pytest.raises(ValueError, match="mismatched"):
        HydraFlowConfig(implementation_tool="claude", model="gpt-5-codex")


def test_harmonize_allows_claude_opus() -> None:
    cfg = HydraFlowConfig(implementation_tool="claude", model="opus")
    assert cfg.model == "opus"


def test_harmonize_allows_codex_gpt() -> None:
    cfg = HydraFlowConfig(implementation_tool="codex", model="gpt-5-codex")
    assert cfg.model == "gpt-5-codex"


def test_triage_defaults_to_claude_sonnet() -> None:
    cfg = HydraFlowConfig()
    assert cfg.triage_tool == "claude"
    assert cfg.triage_model == "sonnet"


def test_combo_env_sets_adr_review_tool_and_model() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_ADR_REVIEW": "claude:opus"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.adr_review_tool == "claude"
        assert cfg.adr_review_model == "opus"


def test_background_cascade_reaches_adr_review() -> None:
    """HYDRAFLOW_BACKGROUND=claude:sonnet must pin the bg-only workers."""
    with patch.dict(os.environ, {"HYDRAFLOW_BACKGROUND": "claude:sonnet"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.adr_review_tool == "claude"
        assert cfg.adr_review_model == "sonnet"


def test_background_cascade_cross_provider_codex() -> None:
    """HYDRAFLOW_BACKGROUND=codex:gpt-5-codex must cascade tool+model coherently
    to every bg-only worker and pass harmonize's cross-provider check."""
    with patch.dict(
        os.environ, {"HYDRAFLOW_BACKGROUND": "codex:gpt-5-codex"}, clear=False
    ):
        cfg = HydraFlowConfig()
        for stage in ("adr_review",):
            assert getattr(cfg, f"{stage}_tool") == "codex"
            assert getattr(cfg, f"{stage}_model") == "gpt-5-codex"
