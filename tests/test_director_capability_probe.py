"""Tests for the director capability probe (ADR-0137, #11533).

The live lane is operator-run and is never exercised here: CI validates the
committed sanitized fixture's schema and the probe's pure/hermetic parts only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.director_capability_probe import (
    DIRECTOR_DENIED_TOOLS,
    DIRECTOR_ENV_ALLOWLIST,
    TURN_TIMED_OUT,
    Lane,
    ProbeEvidence,
    ProofName,
    ProofResult,
    Verdict,
    _frames_or_empty,
    _probe_environment_scrubbing,
    _probe_process_tree_teardown,
    _probe_short_lived_key_expiry,
    build_scrubbed_env,
    captured_session_id,
    describe_id_shape,
    last_init_frame,
    leaked_secret_names,
    parse_stream_json,
    turn_failed,
)

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "director"
    / "director_capability_probe_evidence.json"
)


# --------------------------------------------------------------------------
# Environment scrubbing
# --------------------------------------------------------------------------


def test_scrubbed_env_drops_a_real_provider_key() -> None:
    env = build_scrubbed_env(
        {"ANTHROPIC_API_KEY": "sk-live", "PATH": "/bin"}, home="/h", config_dir="/c"
    )

    assert "ANTHROPIC_API_KEY" not in env


def test_scrubbed_env_drops_an_inherited_auth_token_not_passed_explicitly() -> None:
    env = build_scrubbed_env(
        {"ANTHROPIC_AUTH_TOKEN": "inherited", "PATH": "/bin"},
        home="/h",
        config_dir="/c",
    )

    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_scrubbed_env_keeps_only_the_explicitly_passed_virtual_key() -> None:
    env = build_scrubbed_env(
        {"ANTHROPIC_AUTH_TOKEN": "inherited", "PATH": "/bin"},
        home="/h",
        config_dir="/c",
        gateway_token="hf-virtual-fresh",
    )

    assert env["ANTHROPIC_AUTH_TOKEN"] == "hf-virtual-fresh"


def test_scrubbed_env_drops_the_gateway_control_token() -> None:
    env = build_scrubbed_env(
        {"HYDRAFLOW_GATEWAY_TOKEN": "control", "PATH": "/bin"},
        home="/h",
        config_dir="/c",
    )

    assert "HYDRAFLOW_GATEWAY_TOKEN" not in env


def test_scrubbed_env_drops_the_ssh_agent_socket() -> None:
    env = build_scrubbed_env(
        {"SSH_AUTH_SOCK": "/tmp/agent.sock", "PATH": "/bin"}, home="/h", config_dir="/c"
    )

    assert "SSH_AUTH_SOCK" not in env


def test_scrubbed_env_overwrites_an_inherited_home() -> None:
    env = build_scrubbed_env(
        {"HOME": "/Users/operator"}, home="/sandbox", config_dir="/c"
    )

    assert env["HOME"] == "/sandbox"


def test_scrubbed_env_never_exceeds_the_allowlist() -> None:
    hostile = dict.fromkeys(("FOO", "GH_TOKEN", "AWS_SECRET_ACCESS_KEY", "PATH"), "x")

    env = build_scrubbed_env(hostile, home="/h", config_dir="/c")

    assert set(env) <= DIRECTOR_ENV_ALLOWLIST


def test_leaked_secret_names_ignores_the_virtual_key_slot() -> None:
    assert leaked_secret_names({"ANTHROPIC_AUTH_TOKEN": "hf-virtual"}) == []


def test_leaked_secret_names_reports_a_provider_key() -> None:
    assert leaked_secret_names({"ANTHROPIC_API_KEY": "sk"}) == ["ANTHROPIC_API_KEY"]


# --------------------------------------------------------------------------
# Framing — the two observed hazards
# --------------------------------------------------------------------------


def test_parse_stream_json_reads_one_object_per_line() -> None:
    raw = '{"type":"system"}\n\n{"type":"result"}\n'

    assert len(parse_stream_json(raw)) == 2


def test_parse_stream_json_rejects_an_unframed_banner_line() -> None:
    with pytest.raises(ValueError, match="unframed output at line 1"):
        parse_stream_json('Welcome to the CLI\n{"type":"result"}\n')


def test_parse_stream_json_rejects_a_bare_json_array() -> None:
    with pytest.raises(ValueError, match="not a JSON object"):
        parse_stream_json("[1, 2]\n")


def test_turn_failed_keys_on_is_error_not_on_a_success_subtype() -> None:
    # The exact shape observed live: subtype says success, is_error says otherwise.
    frames = [{"type": "result", "subtype": "success", "is_error": True}]

    assert turn_failed(frames) is True


def test_turn_failed_is_false_for_a_genuinely_clean_turn() -> None:
    frames = [{"type": "result", "subtype": "success", "is_error": False}]

    assert turn_failed(frames) is False


def test_turn_failed_treats_a_missing_result_frame_as_failure() -> None:
    assert turn_failed([{"type": "system", "subtype": "init"}]) is True


def test_last_init_frame_wins_when_a_turn_emits_repeated_inits() -> None:
    frames = [
        {"type": "system", "subtype": "init", "attempt": 1},
        {"type": "system", "subtype": "init", "attempt": 11},
    ]

    assert last_init_frame(frames) == {
        "type": "system",
        "subtype": "init",
        "attempt": 11,
    }


def test_last_init_frame_is_none_without_an_init() -> None:
    assert last_init_frame([{"type": "result"}]) is None


def test_captured_session_id_reads_the_first_frame_carrying_one() -> None:
    frames = [{"type": "system"}, {"type": "result", "session_id": "abc"}]

    assert captured_session_id(frames) == "abc"


def test_describe_id_shape_does_not_reproduce_a_uuid() -> None:
    shape = describe_id_shape("11111111-2222-4333-8444-555555555555")

    assert shape == "uuid-v4-shape"


def test_describe_id_shape_reports_absent_for_none() -> None:
    assert describe_id_shape(None) == "absent"


# --------------------------------------------------------------------------
# Evidence schema — sanitization is enforced, not merely intended
# --------------------------------------------------------------------------


def _proof(**overrides: object) -> ProofResult:
    base: dict[str, object] = {
        "proof": ProofName.ENVIRONMENT_SCRUBBING,
        "lane": Lane.HERMETIC,
        "verdict": Verdict.PASS,
        "summary": "ok",
    }
    base.update(overrides)
    return ProofResult(**base)  # type: ignore[arg-type]


def test_evidence_rejects_a_raw_secret_in_an_observation() -> None:
    with pytest.raises(ValidationError):
        _proof(observations={"note": "sk-live-AbC123XyZ"})


def test_evidence_rejects_a_host_home_path_in_an_observation() -> None:
    with pytest.raises(ValidationError):
        _proof(observations={"path": "/users/operator/.claude"})


def test_evidence_accepts_a_lowercase_shape_descriptor() -> None:
    assert _proof(observations={"shape": "uuid-v4-shape"}).observations["shape"] == (
        "uuid-v4-shape"
    )


def test_a_constrained_pass_must_name_its_constraint() -> None:
    with pytest.raises(ValidationError):
        _proof(verdict=Verdict.PASS_WITH_CONSTRAINT)


def test_evidence_rejects_an_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError):
        ProbeEvidence(
            recorded_at="2026-08-22T00:00:00Z",
            platform="darwin",
            live_lane_ran=False,
            proofs=(),
            anthropic_api_key="sk-live",  # type: ignore[call-arg]
        )


def test_evidence_rejects_an_artifact_missing_a_required_proof() -> None:
    with pytest.raises(ValidationError, match="omits required proofs"):
        ProbeEvidence(
            recorded_at="2026-08-22T00:00:00Z",
            platform="darwin",
            live_lane_ran=False,
            proofs=(_proof(),),
        )


# --------------------------------------------------------------------------
# Hermetic proofs actually run in CI
# --------------------------------------------------------------------------


def test_environment_scrubbing_proof_passes() -> None:
    assert _probe_environment_scrubbing().verdict is Verdict.PASS


def test_process_tree_teardown_proof_leaves_no_survivor() -> None:
    result = _probe_process_tree_teardown()

    assert result.observations["descendants_surviving_after_teardown"] == 0


def test_process_tree_teardown_proof_actually_spawned_a_tree() -> None:
    # Guards against a vacuous pass: zero survivors of zero descendants is not a proof.
    assert _probe_process_tree_teardown().observations["descendants_spawned"] >= 2


def test_short_lived_key_expiry_proof_refuses_the_key_after_its_ttl() -> None:
    assert _probe_short_lived_key_expiry().observations["refused_after_ttl"] is True


def test_short_lived_key_expiry_proof_retains_no_plaintext_token() -> None:
    assert (
        _probe_short_lived_key_expiry().observations["plaintext_token_retained"]
        is False
    )


# --------------------------------------------------------------------------
# The committed live evidence
# --------------------------------------------------------------------------


def _fixture() -> ProbeEvidence:
    return ProbeEvidence.model_validate_json(FIXTURE.read_text())


def test_committed_evidence_validates_against_the_schema() -> None:
    assert _fixture().schema_version == 1


def test_committed_evidence_records_a_real_live_run() -> None:
    assert _fixture().live_lane_ran is True


def test_committed_evidence_has_no_falsified_proof() -> None:
    failed = [p.proof for p in _fixture().proofs if p.verdict is Verdict.FAIL]

    assert failed == []


def test_committed_evidence_ran_every_proof() -> None:
    not_run = [p.proof for p in _fixture().proofs if p.verdict is Verdict.NOT_RUN]

    assert not_run == []


def test_committed_evidence_proves_no_ambient_credential_reached_the_child() -> None:
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["ambient_credential_reached_child"] is False


def test_committed_evidence_proves_the_tool_surface_reaches_empty() -> None:
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["tools_with_exhaustive_denylist"] == 0


def test_committed_evidence_records_that_isolation_alone_leaves_tools_exposed() -> None:
    # The finding that forces the runtime observed-empty assertion.
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert int(proof.observations["tools_with_isolation_only"]) > 0


def test_committed_evidence_proves_resume_loss_is_detectable() -> None:
    proof = next(p for p in _fixture().proofs if p.proof is ProofName.RESUME_LOSS)

    assert proof.observations["resume_loss_is_detectable"] is True


def test_committed_evidence_proves_resume_loss_starts_no_silent_fresh_session() -> None:
    proof = next(p for p in _fixture().proofs if p.proof is ProofName.RESUME_LOSS)

    assert proof.observations["silently_started_fresh_session"] is False


def test_committed_evidence_contains_no_secret_shaped_string() -> None:
    raw = json.loads(FIXTURE.read_text())
    blob = json.dumps(raw)

    assert "sk-" not in blob and "hf-virtual-" not in blob


def test_committed_evidence_leaks_no_operator_home_path() -> None:
    blob = FIXTURE.read_text()

    assert "/Users/" not in blob and "/home/" not in blob


def test_deny_list_covers_the_two_tools_the_cli_does_not_advertise() -> None:
    # Denying only the advertised names left Glob and Grep enabled (#11533).
    assert {"Glob", "Grep"} <= set(DIRECTOR_DENIED_TOOLS)


# --------------------------------------------------------------------------
# Sanitizer hardening (#11627 fresh-eyes findings)
# --------------------------------------------------------------------------


def test_sanitizer_rejects_a_raw_lowercase_uuid_session_id() -> None:
    # The exact value describe_id_shape exists to avoid recording.
    with pytest.raises(ValidationError):
        _proof(observations={"shape": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"})


def test_sanitizer_rejects_a_lowercase_hex_digest() -> None:
    with pytest.raises(ValidationError):
        _proof(observations={"shape": "da39a3ee5e6b4b0d3255bfef95601890afd80709"})


def test_sanitizer_rejects_a_github_token_shape() -> None:
    with pytest.raises(ValidationError):
        _proof(observations={"shape": "ghp_abcdefghij0123456789"})


def test_sanitizer_still_accepts_the_real_descriptors_the_probe_emits() -> None:
    observations: dict[str, bool | int | str] = {
        "result_frame_subtype": "error_during_execution",
        "api_key_source_reported": "none",
        "session_id_shape": "uuid-v4-shape",
        "parse_error_shape": "none",
    }

    assert _proof(observations=observations).observations == observations


def test_key_expiry_proof_actually_sampled_a_record() -> None:
    # Guards the vacuous form: the store deletes expired records, so a check
    # made after expiry would always "pass" against an empty store.
    assert (
        _probe_short_lived_key_expiry().observations["record_sampled_before_expiry"]
        is True
    )


def test_environment_scrubbing_proof_was_offered_real_secrets() -> None:
    # Guards a vacuous pass: zero leaks out of zero secrets proves nothing.
    assert (
        int(_probe_environment_scrubbing().observations["secret_shaped_vars_offered"])
        > 0
    )


def test_frames_or_empty_degrades_instead_of_aborting_on_a_banner_line() -> None:
    assert _frames_or_empty('Welcome!\n{"type":"result"}\n') == []


def test_frames_or_empty_parses_clean_output() -> None:
    assert _frames_or_empty('{"type":"result"}\n') == [{"type": "result"}]


def test_committed_evidence_proves_hostile_project_memory_was_not_loaded() -> None:
    proof = next(
        p for p in _fixture().proofs if p.proof is ProofName.ISOLATED_SETTINGS_HOME
    )

    assert proof.observations["hostile_project_memory_loaded"] is False


def test_committed_evidence_actually_planted_the_hostile_files() -> None:
    # Guards a vacuous pass: "not loaded" proves nothing if nothing was planted.
    proof = next(
        p for p in _fixture().proofs if p.proof is ProofName.ISOLATED_SETTINGS_HOME
    )

    assert proof.observations["hostile_project_files_planted"] is True


def test_committed_evidence_measured_the_allowlist_experiment() -> None:
    # F2's "an allow-list does not narrow the surface" must be measured, not asserted.
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert int(proof.observations["tools_with_allowlist_of_one"]) > 0


def test_committed_evidence_measured_the_incomplete_advertised_array() -> None:
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert int(proof.observations["tools_after_denying_every_advertised_name"]) > 0


def test_committed_evidence_tested_the_runtime_credential_configuration() -> None:
    # The virtual key was present and the turn still never authenticated.
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["credential_turn_authenticated"] is False


def test_committed_evidence_confirms_the_tools_key_was_present() -> None:
    # S4 must never read an absent key as "empty".
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["tools_key_present_on_init"] is True


def test_committed_evidence_reports_the_credential_turn_did_not_complete() -> None:
    # The claim is "never observed to authenticate", not "cleanly refused" —
    # the artifact must say which.
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["credential_turn_completed"] is False


def test_committed_evidence_records_whether_each_tool_turn_produced_a_frame() -> None:
    # A turn that never ran must not read as "the allow-list narrowed to zero".
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["allowlist_init_frame_seen"] is True


def test_committed_evidence_records_the_denied_turn_produced_a_frame() -> None:
    proof = next(
        p
        for p in _fixture().proofs
        if p.proof is ProofName.NO_AMBIENT_TOOLS_OR_CREDENTIALS
    )

    assert proof.observations["advertised_denial_init_frame_seen"] is True


def test_timed_out_turn_sentinel_is_distinguishable_from_a_real_exit_code() -> None:
    assert TURN_TIMED_OUT < 0
