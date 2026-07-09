"""Unit tests for the CH-6 data-governance prompt gate (``src/prompt_gate.py``).

Issue #9734: classification (repo class + upward-only label override),
redaction pattern sets for ``regulated-*`` classes, per-class allowed-backend
policy (fail closed), and audit records that carry pattern NAMES and counts —
never content.
"""

from __future__ import annotations

import json

import pytest

from prompt_gate import (
    BUILTIN_REDACTION_PATTERNS,
    DATA_CLASS_LABEL_PREFIX,
    FAIL_CLOSED_DATA_CLASS,
    PromptGateBlockedError,
    effective_data_class,
    gate_context_fields,
    gate_prompt,
    is_regulated,
    normalize_data_class,
    restriction_rank,
)
from tests.helpers import ConfigFactory

_SENSITIVE_PROMPT = (
    "Patient SSN 123-45-6789, card 4111 1111 1111 1111, "
    "api_key=sk-ant-verysecret plus password: hunter2"
)


def _config(tmp_path, **updates):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    return cfg.model_copy(update=updates) if updates else cfg


def _regulated_config(tmp_path, *, backends=None, **extra):
    return _config(
        tmp_path,
        repo_data_class="regulated-phi",
        data_class_allowed_backends=backends if backends is not None else {},
        **extra,
    )


def _read_audit(config) -> list[dict]:
    path = config.prompt_gate_audit_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestClassificationModel:
    def test_valid_classes_normalize_to_themselves(self):
        assert normalize_data_class("public-code") == "public-code"
        assert normalize_data_class("internal") == "internal"
        assert normalize_data_class("regulated-phi") == "regulated-phi"
        assert normalize_data_class("regulated-mnpi-eu2") == "regulated-mnpi-eu2"

    @pytest.mark.parametrize(
        "raw",
        ["", "Internal", "public", "regulated-", "regulated-PHI", "phi", "  "],
    )
    def test_invalid_or_empty_class_fails_closed(self, raw):
        assert normalize_data_class(raw) == FAIL_CLOSED_DATA_CLASS

    def test_restriction_rank_ordering(self):
        assert (
            restriction_rank("public-code")
            < restriction_rank("internal")
            < restriction_rank("regulated-phi")
        )

    def test_is_regulated(self):
        assert is_regulated("regulated-phi")
        assert is_regulated(FAIL_CLOSED_DATA_CLASS)
        assert not is_regulated("internal")
        assert not is_regulated("public-code")

    def test_label_override_moves_up(self):
        cls = effective_data_class(
            "internal", [f"{DATA_CLASS_LABEL_PREFIX}regulated-phi", "hydraflow-ready"]
        )
        assert cls == "regulated-phi"

    def test_label_override_never_moves_down(self):
        cls = effective_data_class(
            "regulated-phi", [f"{DATA_CLASS_LABEL_PREFIX}public-code"]
        )
        assert cls == "regulated-phi"

    def test_label_cannot_move_sideways_between_regulated_classes(self):
        cls = effective_data_class(
            "regulated-phi", [f"{DATA_CLASS_LABEL_PREFIX}regulated-mnpi"]
        )
        assert cls == "regulated-phi"

    def test_conflicting_regulated_labels_fail_closed(self):
        cls = effective_data_class(
            "internal",
            [
                f"{DATA_CLASS_LABEL_PREFIX}regulated-phi",
                f"{DATA_CLASS_LABEL_PREFIX}regulated-mnpi",
            ],
        )
        assert cls == FAIL_CLOSED_DATA_CLASS

    def test_invalid_label_class_fails_closed(self):
        cls = effective_data_class("internal", [f"{DATA_CLASS_LABEL_PREFIX}bogus!"])
        assert cls == FAIL_CLOSED_DATA_CLASS

    def test_unrelated_labels_are_ignored(self):
        cls = effective_data_class("internal", ["hydraflow-ready", "bug"])
        assert cls == "internal"


class TestZeroRegressionNoOp:
    """With no regulated class configured, every gate call is a structured no-op."""

    def test_default_config_gate_is_noop(self, tmp_path):
        config = _config(tmp_path)
        assert config.repo_data_class == "internal"
        result = gate_prompt(
            _SENSITIVE_PROMPT, config=config, source="implementer", tool="claude"
        )
        assert result.prompt == _SENSITIVE_PROMPT  # untouched, even with hits
        assert result.decision.action == "allow"
        assert result.decision.patterns_hit == {}
        assert not config.prompt_gate_audit_path.exists()  # no audit writes

    def test_public_code_gate_is_noop(self, tmp_path):
        config = _config(tmp_path, repo_data_class="public-code")
        result = gate_prompt(
            _SENSITIVE_PROMPT, config=config, source="planner", tool="codex"
        )
        assert result.prompt == _SENSITIVE_PROMPT
        assert result.decision.action == "allow"
        assert not config.prompt_gate_audit_path.exists()

    def test_noop_ignores_backend_policy(self, tmp_path):
        # Backend allowlists apply to regulated classes only.
        config = _config(tmp_path, data_class_allowed_backends={"internal": ["codex"]})
        result = gate_prompt("hello", config=config, source="triage", tool="claude")
        assert result.decision.action == "allow"


class TestRedaction:
    def test_builtin_patterns_redact_and_count(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        result = gate_prompt(
            _SENSITIVE_PROMPT, config=config, source="implementer", tool="claude"
        )
        assert "123-45-6789" not in result.prompt
        assert "4111 1111 1111 1111" not in result.prompt
        assert "sk-ant-verysecret" not in result.prompt
        assert "hunter2" not in result.prompt
        assert "[REDACTED:ssn_like]" in result.prompt
        assert "[REDACTED:credit_card_like]" in result.prompt
        assert "[REDACTED:key_value_secret]" in result.prompt
        assert result.decision.action == "redact"
        assert result.decision.patterns_hit["ssn_like"] == 1
        assert result.decision.patterns_hit["key_value_secret"] == 2

    def test_clean_prompt_allowed_with_no_hits(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        result = gate_prompt(
            "just fix the flaky test",
            config=config,
            source="implementer",
            tool="claude",
        )
        assert result.prompt == "just fix the flaky test"
        assert result.decision.action == "allow"
        assert result.decision.patterns_hit == {}

    def test_configured_extra_pattern_merges_over_builtins(self, tmp_path):
        config = _regulated_config(
            tmp_path,
            backends={"regulated-phi": ["claude"]},
            data_class_redaction_patterns={"mrn_like": r"\bMRN-\d{6}\b"},
        )
        result = gate_prompt(
            "chart MRN-123456 follow-up",
            config=config,
            source="implementer",
            tool="claude",
        )
        assert "MRN-123456" not in result.prompt
        assert "[REDACTED:mrn_like]" in result.prompt
        assert result.decision.patterns_hit == {"mrn_like": 1}

    def test_invalid_configured_pattern_is_skipped_builtins_still_apply(self, tmp_path):
        config = _regulated_config(
            tmp_path,
            backends={"regulated-phi": ["claude"]},
            data_class_redaction_patterns={"broken": r"([unclosed"},
        )
        result = gate_prompt(
            "SSN 123-45-6789", config=config, source="implementer", tool="claude"
        )
        assert "[REDACTED:ssn_like]" in result.prompt

    def test_builtin_set_is_exactly_the_v1_trio(self):
        assert set(BUILTIN_REDACTION_PATTERNS) == {
            "ssn_like",
            "credit_card_like",
            "key_value_secret",
        }

    def test_label_elevated_issue_gets_redaction_on_internal_repo(self, tmp_path):
        config = _config(
            tmp_path,
            data_class_allowed_backends={"regulated-phi": ["claude"]},
        )
        result = gate_prompt(
            "SSN 123-45-6789",
            config=config,
            source="implementer",
            tool="claude",
            issue_labels=[f"{DATA_CLASS_LABEL_PREFIX}regulated-phi"],
        )
        assert result.decision.data_class == "regulated-phi"
        assert "[REDACTED:ssn_like]" in result.prompt


class TestBackendPolicy:
    def test_disallowed_backend_blocks(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["codex"]})
        with pytest.raises(PromptGateBlockedError) as excinfo:
            gate_prompt("body", config=config, source="implementer", tool="claude")
        assert excinfo.value.decision.action == "block"
        assert excinfo.value.decision.data_class == "regulated-phi"

    def test_no_allowlist_entry_fails_closed(self, tmp_path):
        config = _regulated_config(tmp_path, backends={})
        with pytest.raises(PromptGateBlockedError):
            gate_prompt("body", config=config, source="implementer", tool="claude")

    def test_unknown_tool_fails_closed(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        with pytest.raises(PromptGateBlockedError):
            gate_prompt("body", config=config, source="implementer", tool="")

    def test_allowed_backend_passes(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        result = gate_prompt("body", config=config, source="implementer", tool="claude")
        assert result.decision.action == "allow"

    def test_fail_closed_class_blocks_even_with_other_allowlists(self, tmp_path):
        config = _config(
            tmp_path,
            repo_data_class="regulated-TYPO",  # invalid -> fail-closed class
            data_class_allowed_backends={"regulated-phi": ["claude"]},
        )
        with pytest.raises(PromptGateBlockedError) as excinfo:
            gate_prompt("body", config=config, source="implementer", tool="claude")
        assert excinfo.value.decision.data_class == FAIL_CLOSED_DATA_CLASS


class TestAuditRecords:
    def test_redact_decision_emits_names_and_counts_never_content(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        gate_prompt(
            _SENSITIVE_PROMPT,
            config=config,
            source="implementer",
            tool="claude",
            issue_number=77,
        )
        records = _read_audit(config)
        assert len(records) == 1
        rec = records[0]
        assert rec["action"] == "redact"
        assert rec["data_class"] == "regulated-phi"
        assert rec["source"] == "implementer"
        assert rec["tool"] == "claude"
        assert rec["issue_number"] == 77
        assert rec["patterns_hit"]["ssn_like"] == 1
        raw = json.dumps(records)
        assert "123-45-6789" not in raw
        assert "hunter2" not in raw
        assert _SENSITIVE_PROMPT[:20] not in raw

    def test_block_decision_emits_audit_record(self, tmp_path):
        config = _regulated_config(tmp_path, backends={})
        with pytest.raises(PromptGateBlockedError):
            gate_prompt("body", config=config, source="implementer", tool="claude")
        records = _read_audit(config)
        assert len(records) == 1
        assert records[0]["action"] == "block"
        assert records[0]["reason"]

    def test_regulated_allow_decision_emits_audit_record(self, tmp_path):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        gate_prompt("clean", config=config, source="implementer", tool="claude")
        records = _read_audit(config)
        assert len(records) == 1
        assert records[0]["action"] == "allow"

    def test_audit_write_failure_never_raises(self, tmp_path, monkeypatch):
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["claude"]})
        monkeypatch.setattr(
            "prompt_gate.append_jsonl",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        result = gate_prompt(
            "clean", config=config, source="implementer", tool="claude"
        )
        assert result.decision.action == "allow"


class TestGateContextFields:
    def test_noop_for_internal_class(self, tmp_path):
        config = _config(tmp_path)
        fields = {"issue_body": "SSN 123-45-6789"}
        redacted, decision = gate_context_fields(
            fields, config=config, source="preflight_context"
        )
        assert redacted == fields
        assert decision.action == "allow"
        assert not config.prompt_gate_audit_path.exists()

    def test_redacts_every_field_and_emits_one_record(self, tmp_path):
        config = _regulated_config(tmp_path)
        fields = {
            "issue_body": "SSN 123-45-6789",
            "comment_0": "token=abc123secret",
            "wiki_excerpts": "clean text",
        }
        redacted, decision = gate_context_fields(
            fields, config=config, source="preflight_context", issue_number=9
        )
        assert "[REDACTED:ssn_like]" in redacted["issue_body"]
        assert "[REDACTED:key_value_secret]" in redacted["comment_0"]
        assert redacted["wiki_excerpts"] == "clean text"
        assert decision.action == "redact"
        assert decision.patterns_hit == {"ssn_like": 1, "key_value_secret": 1}
        assert len(_read_audit(config)) == 1

    def test_no_backend_check_on_assembly_only_seam(self, tmp_path):
        # gather_context has no backend in scope: redaction applies, blocking
        # is the spawn seams' job.
        config = _regulated_config(tmp_path, backends={})
        redacted, decision = gate_context_fields(
            {"issue_body": "x"}, config=config, source="preflight_context"
        )
        assert decision.action == "allow"
